"""
Margin Catalog refresher (informational layer only).

Fetches futures margin data from the NinjaTrader broker margins page
(https://ninjatrader.com/pricing/margins/) and rewrites
``data/catalog/margins.json`` atomically. The refresher is a pure
information layer — it must NEVER affect strategy execution, the bridge,
Account binding, or the validated NinjaTrader Strategy Analyzer backtest
path. On any failure (network, parse, write) the existing margins.json is
left intact and the failure is recorded for the UI / catalog warnings.

Two entry points:

  * ``refresh_margins_now(reason)``
        Runs the fetch synchronously. Used by the manual "Refresh now"
        button (POST /api/margins/refresh).

  * ``maybe_daily_refresh()``
        Lazy daily auto-refresh. Called from build_catalog_response().
        If the on-disk snapshot is older than ~24h and no refresh is
        already in progress, a daemon thread is dispatched. Returns
        immediately so the GET /api/catalog request stays fast.

Both paths share the same fetch+parse code so behaviour is identical.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Single source of truth — the broker's public per-symbol margin page.
MARGIN_SOURCE_URL = "https://ninjatrader.com/pricing/margins/"
MARGIN_BROKER = "NinjaTrader"
SCHEMA_VERSION = "0.1"
HTTP_TIMEOUT_S = 30
USER_AGENT = "NT-Analyzer/0.1 (+local margin refresh)"

# Daily refresh window: re-fetch if the snapshot is older than this.
DAILY_REFRESH_AGE_S = 24 * 3600

# Concurrency guards — only one refresh may run at a time, regardless of
# whether it was triggered manually or by the daily lazy check.
_REFRESH_LOCK = threading.Lock()
_REFRESH_IN_PROGRESS = threading.Event()

# Last-attempt status, exposed to /api/catalog warnings + the UI panel.
_LAST_STATUS_LOCK = threading.Lock()
_LAST_STATUS: Dict[str, Any] = {
    "last_attempt_at_utc": None,
    "last_success_at_utc": None,
    "last_error":          None,
    "last_trigger":        None,    # "manual" | "auto" | None
    "in_progress":         False,
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def margins_json_path() -> Path:
    return _project_root() / "data" / "catalog" / "margins.json"


# ---------------------------------------------------------------------------
# Status helpers (thread-safe)
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_status(**fields: Any) -> None:
    with _LAST_STATUS_LOCK:
        _LAST_STATUS.update(fields)


def last_status() -> Dict[str, Any]:
    """Return a snapshot of the last refresh attempt."""
    with _LAST_STATUS_LOCK:
        return dict(_LAST_STATUS)


# ---------------------------------------------------------------------------
# Page fetch + parse
# ---------------------------------------------------------------------------

# The broker page renders a single <table> with rows of the form:
#   <td><a href="/margin-details/?symbol=MES">MES</a></td>
#   <td><a href="...">Micro E-mini S&P 500</a></td>
#   <td>CME</td>
#   <td>Micro Indices</td>
#   <td data-day-margin="50">$50.00</td>
#   <td data-initial-margin="330">$330.00</td>
# We rely on the data-* attributes (numeric, no currency formatting) which
# are stable; the rendered $ text is just a fallback if attrs change name.

_TR_RE   = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_TD_RE   = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", re.S | re.I)
_TAG_RE  = re.compile(r"<[^>]+>")
_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.S | re.I)
_DAY_ATTR_RE  = re.compile(r'data-day-margin\s*=\s*"([^"]*)"', re.I)
_INIT_ATTR_RE = re.compile(r'data-initial-margin\s*=\s*"([^"]*)"', re.I)
_DOLLAR_RE    = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")


def _strip_html(s: str) -> str:
    return _TAG_RE.sub("", s).replace("&amp;", "&").replace("&nbsp;", " ").strip()


def _parse_money(text: str) -> Optional[float]:
    """Parse '50', '$50.00', '1,234.5' → float. None on failure."""
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    # numeric attribute value first
    try:
        return float(t.replace(",", ""))
    except ValueError:
        pass
    m = _DOLLAR_RE.search(t)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _http_get(url: str, timeout: int = HTTP_TIMEOUT_S) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} from {url}")
        return resp.read().decode("utf-8", errors="replace")


def parse_margins_html(html: str) -> Dict[str, Dict[str, Any]]:
    """Extract {root: {display_name, exchange, intraday_margin, initial_margin,
    maintenance_margin}} from the broker's margins page HTML.

    Raises ValueError if the page structure is so different that no rows can
    be parsed — caller should treat that as a parse failure.
    """
    tbl_match = _TABLE_RE.search(html)
    if not tbl_match:
        raise ValueError("margins page: no <table> found")
    table_html = tbl_match.group(1)

    rows = _TR_RE.findall(table_html)
    out: Dict[str, Dict[str, Any]] = {}
    for row_html in rows:
        # Header rows on the broker page use <th>; data rows use <td>.
        # Skip any row that contains a <th> so headers / sub-headers
        # never leak into the catalog as a fake "SYMBOL" instrument.
        if re.search(r"<th\b", row_html, re.I):
            continue
        cells_raw = _TD_RE.findall(row_html)
        if len(cells_raw) < 5:
            continue  # malformed / spacer row
        # Tolerant lookup of the data-* margin attributes anywhere in the row.
        day_attr  = _DAY_ATTR_RE.search(row_html)
        init_attr = _INIT_ATTR_RE.search(row_html)

        cells_text = [_strip_html(c) for c in cells_raw]
        # Heuristic columns: [0]=Symbol, [1]=Market name, [2]=Exchange,
        # [3]=Group, [4]=Day margin (text), [5]=Initial margin (text)
        symbol = cells_text[0].upper()
        if not symbol or len(symbol) > 8 or not re.fullmatch(r"[A-Z0-9_]+", symbol):
            # Skip non-symbol rows (header repeats, footnotes).
            continue
        display_name = cells_text[1] if len(cells_text) > 1 else ""
        exchange     = cells_text[2] if len(cells_text) > 2 else ""

        intraday_val = _parse_money(day_attr.group(1)) if day_attr else None
        if intraday_val is None and len(cells_text) > 4:
            intraday_val = _parse_money(cells_text[4])

        initial_val = _parse_money(init_attr.group(1)) if init_attr else None
        if initial_val is None and len(cells_text) > 5:
            initial_val = _parse_money(cells_text[5])

        # A real instrument row must have at least one numeric margin value.
        # This belt-and-braces check rejects any header-like row that somehow
        # slipped past the <th> filter (e.g. the page later switches to <td>
        # for headings).
        if intraday_val is None and initial_val is None:
            continue

        out[symbol] = {
            "display_name":       display_name,
            "exchange":           exchange,
            "intraday_margin":    intraday_val,
            "initial_margin":     initial_val,
            # The broker page does not publish maintenance margin per symbol.
            "maintenance_margin": None,
        }

    if not out:
        raise ValueError("margins page: parsed 0 symbols (page format changed?)")
    return out


def fetch_and_parse() -> Tuple[Dict[str, Dict[str, Any]], str]:
    """Fetch + parse the broker page. Returns (symbols, raw_html_url)."""
    html = _http_get(MARGIN_SOURCE_URL)
    symbols = parse_margins_html(html)
    return symbols, MARGIN_SOURCE_URL


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Public refresh entry points
# ---------------------------------------------------------------------------

def refresh_margins_now(trigger: str = "manual") -> Dict[str, Any]:
    """Fetch the margins page, parse it and overwrite margins.json atomically.

    Returns a result dict that is safe to expose to the UI:

        {
          "ok": bool,
          "trigger": "manual" | "auto",
          "fetched_at_utc": "...",
          "symbols_count": int,
          "source_url": "...",
          "error": "..."   # only when ok=false; previous snapshot is kept
        }

    On any error (network, parse, write) the existing margins.json file is
    NOT touched and ``ok=False`` is returned with a human-readable error.
    """
    started_at = _utcnow_iso()
    if not _REFRESH_LOCK.acquire(blocking=False):
        return {
            "ok":      False,
            "trigger": trigger,
            "error":   "refresh already in progress",
        }
    _REFRESH_IN_PROGRESS.set()
    _set_status(in_progress=True, last_trigger=trigger,
                last_attempt_at_utc=started_at)
    try:
        try:
            symbols, source_url = fetch_and_parse()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            err = f"network error: {e}"
            _set_status(in_progress=False, last_error=err)
            return {"ok": False, "trigger": trigger, "error": err}
        except ValueError as e:
            err = f"parse error: {e}"
            _set_status(in_progress=False, last_error=err)
            return {"ok": False, "trigger": trigger, "error": err}
        except Exception as e:  # pragma: no cover — last-resort safety
            err = f"fetch failed: {e}"
            _set_status(in_progress=False, last_error=err)
            return {"ok": False, "trigger": trigger, "error": err}

        fetched_at = _utcnow_iso()
        payload: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "broker":         MARGIN_BROKER,
            "source":         "auto_refresh",
            "source_url":     source_url,
            "fetched_at_utc": fetched_at,
            "trigger":        trigger,
            "notes": [
                "Intraday margins can change without notice.",
                "News events may temporarily increase intraday margins.",
                "Maintenance margins are exchange-driven and are not "
                "published per-symbol on the broker margins page.",
                "Auto-fetched from " + source_url + ".",
            ],
            "symbols": symbols,
        }

        path = margins_json_path()
        try:
            _atomic_write_json(path, payload)
        except OSError as e:
            err = f"write error: {e}"
            _set_status(in_progress=False, last_error=err)
            return {"ok": False, "trigger": trigger, "error": err}

        _set_status(
            in_progress=False,
            last_error=None,
            last_success_at_utc=fetched_at,
        )
        return {
            "ok":             True,
            "trigger":        trigger,
            "fetched_at_utc": fetched_at,
            "symbols_count":  len(symbols),
            "source_url":     source_url,
        }
    finally:
        _REFRESH_IN_PROGRESS.clear()
        _REFRESH_LOCK.release()


def _file_age_seconds(path: Path) -> Optional[float]:
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    return max(0.0, time.time() - mtime)


def maybe_daily_refresh() -> Dict[str, Any]:
    """Lazy daily auto-refresh. Returns immediately.

    Spawns a background daemon thread to refresh margins.json if it is
    missing or older than ~24 hours and no refresh is currently running.
    The HTTP request that triggered this call is NOT blocked; the next
    /api/catalog after the background thread completes will pick up the
    new file.

    Returns a small status dict the caller can include in API responses.
    """
    path = margins_json_path()
    age = _file_age_seconds(path)

    needs_refresh = (age is None) or (age >= DAILY_REFRESH_AGE_S)
    dispatched = False
    if needs_refresh and not _REFRESH_IN_PROGRESS.is_set():
        try:
            t = threading.Thread(
                target=refresh_margins_now,
                kwargs={"trigger": "auto"},
                name="nt-margin-refresh",
                daemon=True,
            )
            t.start()
            dispatched = True
        except RuntimeError:
            # Thread creation can fail under interpreter shutdown; ignore.
            dispatched = False

    return {
        "needs_refresh":   bool(needs_refresh),
        "dispatched":      dispatched,
        "age_seconds":     age,
        "max_age_seconds": DAILY_REFRESH_AGE_S,
    }
