"""
NT-Analyzer file-queue helpers (shared by CLI and backend).

Contract mirrors docs/job-schema.md and tools/enqueue-smoke-job.ps1:

    pending/.staging/<job_id>/job.json.tmp -> job.json (rename)
                              ^
    pending/.staging/<job_id>/  --(Directory move)-->  pending/<job_id>/

The bridge AddOn picks up `pending/<job_id>/`, moves it to `running/`,
then to `done|failed|cancelled/`.

This module is read-mostly: the only mutating operation is `create_job`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import marginrefresh  # informational margin catalog auto-refresh

# ---------------------------------------------------------------------------
# Whitelist + defaults. Strategy whitelist on the backend MUST match what the
# bridge accepts; the bridge has its own whitelist and rejects unknown classes,
# so this is just a UX guard rail to keep the UI honest.
# ---------------------------------------------------------------------------

# Conservative fallback used only when the bridge has not yet written
# data/catalog/strategies.json (e.g. NinjaTrader is offline). The bridge
# itself enforces the real whitelist on every job.
_FALLBACK_STRATEGIES: List[str] = ["SampleMACrossOver"]

# Public: kept for backwards-compatibility with /api/strategies and the
# pre-catalog UI. Always re-evaluated through `whitelisted_strategies()`.
WHITELISTED_STRATEGIES: List[str] = list(_FALLBACK_STRATEGIES)

JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")
QUEUE_SUBDIRS = ("pending", "running", "done", "failed", "cancelled")

# Project-level validation status. The bridge path has been manually
# cross-checked against NinjaTrader Strategy Analyzer and is now the accepted
# baseline for future strategy work.
VALIDATED_AGAINST_STRATEGY_ANALYZER = True


def utcnow_iso(precision: str = "seconds") -> str:
    now = datetime.now(timezone.utc)
    if precision == "ms":
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def gen_job_id(prefix: str = "ui") -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')[:-3]}Z"


def project_root() -> Path:
    """
    Resolve project root. Priority:
      1. env NT_ANALYZER_ROOT
      2. parent dir of this file (NT-Analyzer/app/jobqueue.py -> NT-Analyzer)
    """
    env = os.environ.get("NT_ANALYZER_ROOT")
    if env:
        p = Path(env).resolve()
        if (p / "jobs").exists():
            return p
    here = Path(__file__).resolve().parent.parent
    return here


def jobs_dir() -> Path:
    return project_root() / "jobs"


# ---------------------------------------------------------------------------
# Catalog (bridge-generated metadata of strategies + instruments)
# ---------------------------------------------------------------------------

def catalog_dir() -> Path:
    return project_root() / "data" / "catalog"


def reports_dir() -> Path:
    return project_root() / "data" / "reports"


def report_numbers_file() -> Path:
    return reports_dir() / "report_numbers.json"


def _report_key(kind: str, report_id: str) -> str:
    return f"{kind}:{report_id}"


def _read_report_numbers() -> Dict[str, Any]:
    p = report_numbers_file()
    if not p.is_file():
        return {"schema_version": "1.0", "next_number": 1, "reports": {}}
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("reports"), dict):
            try:
                data["next_number"] = int(data.get("next_number") or 1)
            except (TypeError, ValueError):
                data["next_number"] = 1
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"schema_version": "1.0", "next_number": 1, "reports": {}}


def _write_report_numbers(data: Dict[str, Any]) -> None:
    p = report_numbers_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, p)


def _report_sort_time(created_at: Optional[str], fallback_mtime: float) -> float:
    if created_at:
        try:
            return datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return float(fallback_mtime or 0.0)


def _collect_report_number_candidates() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for sub in QUEUE_SUBDIRS:
        d = jobs_dir() / sub
        if not d.is_dir():
            continue
        for child in d.iterdir():
            if not child.is_dir() or child.name == ".staging":
                continue
            job = _read_json_safe(child / "job.json") or {}
            if job.get("batch"):
                continue
            try:
                mtime = child.stat().st_mtime
            except OSError:
                mtime = 0.0
            candidates.append({
                "key": _report_key("job", child.name),
                "kind": "job",
                "id": child.name,
                "created_at_utc": job.get("created_at_utc"),
                "sort_time": _report_sort_time(job.get("created_at_utc"), mtime),
            })
    bdir = batches_dir()
    if bdir.is_dir():
        for child in bdir.iterdir():
            if not child.is_dir():
                continue
            meta = _read_json_safe(child / "batch.json") or {}
            try:
                mtime = child.stat().st_mtime
            except OSError:
                mtime = 0.0
            candidates.append({
                "key": _report_key("batch", child.name),
                "kind": "batch",
                "id": child.name,
                "created_at_utc": meta.get("created_at_utc"),
                "sort_time": _report_sort_time(meta.get("created_at_utc"), mtime),
            })
    candidates.sort(key=lambda x: (x.get("sort_time") or 0.0, x.get("key") or ""))
    return candidates


def sync_report_numbers() -> Dict[str, int]:
    data = _read_report_numbers()
    reports = data.setdefault("reports", {})
    changed = False
    max_seen = 0
    for entry in reports.values():
        try:
            max_seen = max(max_seen, int(entry.get("number") if isinstance(entry, dict) else entry))
        except (TypeError, ValueError):
            continue
    next_number = max(int(data.get("next_number") or 1), max_seen + 1)
    for cand in _collect_report_number_candidates():
        key = cand["key"]
        entry = reports.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("number"), int):
            continue
        if isinstance(entry, int):
            reports[key] = {"number": entry, "kind": cand["kind"], "id": cand["id"]}
            changed = True
            continue
        reports[key] = {
            "number": next_number,
            "kind": cand["kind"],
            "id": cand["id"],
            "created_at_utc": cand.get("created_at_utc"),
            "assigned_at_utc": utcnow_iso(),
        }
        next_number += 1
        changed = True
    if data.get("next_number") != next_number:
        data["next_number"] = next_number
        changed = True
    data["schema_version"] = "1.0"
    if changed:
        _write_report_numbers(data)
    out: Dict[str, int] = {}
    for key, entry in reports.items():
        try:
            out[key] = int(entry.get("number") if isinstance(entry, dict) else entry)
        except (TypeError, ValueError):
            continue
    return out


def profiles_dir() -> Path:
    """Directory holding the curated Strategy Profiles registry (Phase 22e)."""
    return project_root() / "data" / "profiles"


def read_strategy_profiles() -> Dict[str, Any]:
    """Return the Strategy Profiles registry in the UI-facing schema.

    Profiles are user-curated "best-of" configurations (strategy + instrument +
    timeframe + locked params + status). The Backtesting page uses them as a
    second left-panel tab; the Trading page will compare live-running NT
    strategies against them to surface parameter drift.
    """
    p = profiles_dir() / "strategies.json"
    if not p.is_file():
        return {"schema_version": "1.0", "profiles": []}
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("profiles"), list):
            out = dict(data)
            out["profiles"] = [
                _normalize_strategy_profile_for_ui(x)
                for x in data.get("profiles", [])
                if isinstance(x, dict)
            ]
            return out
    except (OSError, json.JSONDecodeError):
        pass
    return {"schema_version": "1.0", "profiles": []}


def _date_to_utc_midnight(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    if "T" in s:
        return s
    return f"{s}T00:00:00Z"


def _normalize_strategy_profile_for_ui(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Accept legacy and current profile JSON shapes.

    Phase 22e originally stored profiles as id/strategy/parameters/period while
    the UI renders profile_id/strategy_class/locked_parameters/test_period.
    Keep the registry readable across both shapes so a stale or hand-edited
    profile file does not produce blank cards.
    """
    out = dict(profile)
    if "profile_id" not in out and "id" in out:
        out["profile_id"] = out.get("id")
    if "strategy_class" not in out and "strategy" in out:
        out["strategy_class"] = out.get("strategy")
    if "locked_parameters" not in out and isinstance(out.get("parameters"), dict):
        out["locked_parameters"] = out.get("parameters")
    if "last_job_id" not in out:
        src = out.get("source")
        if isinstance(src, dict) and src.get("best_job_id"):
            out["last_job_id"] = src.get("best_job_id")

    if "test_period" not in out:
        period = out.get("period")
        if isinstance(period, dict):
            out["test_period"] = {
                "from_utc": _date_to_utc_midnight(period.get("from") or period.get("start")),
                "to_utc":   _date_to_utc_midnight(period.get("to") or period.get("end")),
            }

    metrics = out.get("metrics")
    if isinstance(metrics, dict):
        normalized = dict(metrics)
        if "trade_count" not in normalized and "trades" in metrics:
            normalized["trade_count"] = metrics.get("trades")
        if "winning_pct" not in normalized and "win_pct" in metrics:
            normalized["winning_pct"] = metrics.get("win_pct")
        if "net_profit_after_commission" not in normalized and "adj_net" in metrics:
            normalized["net_profit_after_commission"] = metrics.get("adj_net")
        if "profit_factor_after_commission" not in normalized and "adj_pf" in metrics:
            normalized["profit_factor_after_commission"] = metrics.get("adj_pf")
        if "max_drawdown" not in normalized and "adj_max_drawdown" in metrics:
            normalized["max_drawdown"] = metrics.get("adj_max_drawdown")
        out["metrics"] = normalized

    return out


def _read_catalog_file(name: str) -> Optional[Dict[str, Any]]:
    p = catalog_dir() / name
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def read_strategies_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/strategies.json or None."""
    return _read_catalog_file("strategies.json")


def read_instruments_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/instruments.json or None."""
    return _read_catalog_file("instruments.json")


def read_templates_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/templates.json (commission + trading hours)
    or None.
    """
    return _read_catalog_file("templates.json")


def read_margins_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/margins.json or None.

    The margin catalog is a manually-seeded broker reference (NinjaTrader
    futures intraday/overnight margins). It is informational only — bridge
    execution and the validated baseline backtest path do not consume it.
    """
    return _read_catalog_file("margins.json")


def read_instrument_groups_catalog() -> Optional[Dict[str, Any]]:
    """Returns parsed data/catalog/instrument_groups.json or None.

    The file holds *root* symbol prefixes ("MES", "6B", ...) per group.
    Resolution against the actual instruments.json catalog happens in
    build_catalog_response so the UI receives concrete contract symbols.
    """
    return _read_catalog_file("instrument_groups.json")


# ---------------------------------------------------------------------------
# Catalog refresh: detect staleness vs NinjaTrader.Custom.dll and trigger
# the bridge to rebuild the catalog without restarting NinjaTrader.
# ---------------------------------------------------------------------------

def commands_dir() -> Path:
    return project_root() / "data" / "commands"


def _custom_dll_path() -> Path:
    return ninjatrader_user_dir() / "bin" / "Custom" / "NinjaTrader.Custom.dll"


def _nt_strategies_dir() -> Path:
    return ninjatrader_user_dir() / "bin" / "Custom" / "Strategies"


def _nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _resolve_strategy_source_file(class_name: str,
                                  catalog_source_file: Any = None) -> Optional[str]:
    """Resolve the real .cs file from Custom/Strategies.

    The bridge catalog can be stale after folders were archived or after a
    zero-byte root stub existed. Prefer a non-empty catalog path, otherwise
    fall back to Strategies/<Class>/<Class>.cs and then Strategies/<Class>.cs.
    """
    raw = str(catalog_source_file or "")
    if raw and _nonempty_file(Path(raw)):
        return raw

    safe = str(class_name or "").strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", safe):
        return None
    base = _nt_strategies_dir()
    for candidate in (base / safe / f"{safe}.cs", base / f"{safe}.cs"):
        if _nonempty_file(candidate):
            return str(candidate)
    return None


def _safe_mtime(p: Path) -> Optional[float]:
    try:
        return p.stat().st_mtime if p.is_file() else None
    except OSError:
        return None


def catalog_staleness() -> Dict[str, Any]:
    """Compare strategies.json mtime against NinjaTrader.Custom.dll mtime.

    If the DLL is newer (NinjaScript was recompiled after the bridge built
    the catalog), the catalog is stale and the user should refresh.
    """
    dll = _custom_dll_path()
    cat = catalog_dir() / "strategies.json"
    dll_mt = _safe_mtime(dll)
    cat_mt = _safe_mtime(cat)
    out: Dict[str, Any] = {
        "stale": False,
        "reason": None,
        "dll_mtime": dll_mt,
        "catalog_mtime": cat_mt,
        "dll_path": str(dll),
    }
    if cat_mt is None:
        out["stale"] = True
        out["reason"] = "catalog_missing"
        return out
    if dll_mt is None:
        return out  # DLL not found — leave catalog as-is, no actionable warning
    # Allow a small fudge factor (5s) for filesystem clock skew.
    if dll_mt - cat_mt > 5.0:
        out["stale"] = True
        out["reason"] = "dll_newer"
    return out


def request_catalog_refresh(timeout_s: float = 25.0) -> Dict[str, Any]:
    """Drop a refresh_catalog.request file the bridge polls for, then wait
    for refresh_catalog.response.

    The 25 s timeout accommodates NinjaTrader cold-startup: the AddOn's
    CatalogRefresher only starts once the assemblies are loaded, which can
    take 15–20 s on first launch. After that, refresh round-trips in ~1–2 s.

    Returns {ok, reason, strategies_count, error, request_id, timed_out}.
    """
    cdir = commands_dir()
    try:
        cdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "reason": "cannot_create_commands_dir", "error": str(e)}

    request_id = uuid.uuid4().hex
    req_path  = cdir / "refresh_catalog.request"
    resp_path = cdir / "refresh_catalog.response"

    # Drop any stale response from a previous (timed-out) call.
    try:
        if resp_path.exists():
            resp_path.unlink()
    except OSError:
        pass

    payload = {
        "schema_version": "0.1",
        "request_id":     request_id,
        "requested_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z",
    }
    try:
        # Write atomically so the bridge never sees a half-written request.
        tmp = req_path.with_suffix(".request.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, req_path)
    except OSError as e:
        return {"ok": False, "reason": "cannot_write_request", "error": str(e)}

    # Poll for the matching response. The bridge is responsible for deleting
    # the request file after handling it; we delete the response after reading.
    deadline = time.monotonic() + max(0.5, timeout_s)
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if not resp_path.is_file():
            continue
        try:
            with open(resp_path, "r", encoding="utf-8-sig") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        # Tolerate older bridge that doesn't echo request_id back.
        rid = doc.get("request_id")
        if rid and rid != request_id:
            continue
        try: resp_path.unlink()
        except OSError: pass
        return {
            "ok":               bool(doc.get("ok")),
            "reason":           "bridge_responded",
            "request_id":       request_id,
            "strategies_count": int(doc.get("strategies_count") or 0),
            "error":            doc.get("error") or None,
            "responded_at_utc": doc.get("responded_at_utc"),
            "timed_out":        False,
        }

    # Timed out. Clean up our orphan request so the next click starts clean
    # and doesn't get answered by the bridge with our (now stale) request_id.
    request_still_pending = req_path.is_file()
    try:
        if req_path.is_file():
            req_path.unlink()
    except OSError:
        pass

    if request_still_pending:
        # Bridge never picked up the request -> AddOn is not running.
        msg = ("Bridge не отвечает: AddOn ещё не загружен или NinjaTrader не запущен. "
               "Если только что перезапустили NinjaTrader — подождите ~30 секунд и попробуйте ещё раз "
               "(холодный старт NinjaTrader долгий). Если NinjaTrader не открыт — запустите его.")
        reason = "bridge_not_running"
    else:
        # Bridge picked up the request but didn't write a response in time.
        msg = ("Bridge принял запрос, но не успел ответить за {:.0f} секунд. "
               "Попробуйте ещё раз; если повторится — посмотрите Bridge log в Диагностике.").format(timeout_s)
        reason = "bridge_slow"

    return {
        "ok":         False,
        "reason":     reason,
        "request_id": request_id,
        "timed_out":  True,
        "error":      msg,
    }




def _resolve_group_instruments(
    roots: List[str],
    instrument_index: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[str], List[str]]:
    """Resolve a list of symbol roots (e.g. ['MES','MNQ']) to concrete
    instrument names found in the catalog.

    Returns (all_instruments, current_instruments) where current is the
    front-month contract per root (max data_last among those with minute
    data; falls back to alphabetical first if no data). The UI exposes a
    "Only current contracts" toggle that picks the second list — without
    it Micros (~12 roots × 30 historical expiries) is unusable.
    """
    out_all: List[str] = []
    out_current: List[str] = []
    for root in roots:
        bucket = instrument_index.get(root.upper())
        if not bucket:
            continue
        bucket_sorted = sorted(
            bucket,
            key=lambda r: (
                0 if r.get("has_minute_data") else 1,
                # data_last desc -> use negation via reverse string order
                -(int((r.get("data_last") or "0000-00-00").replace("-", "")) or 0),
                str(r.get("instrument") or ""),
            ),
        )
        # Track the front-month: first row with minute data, else first row.
        front_name: Optional[str] = None
        for r in bucket_sorted:
            name = r.get("instrument")
            if not isinstance(name, str):
                continue
            if name not in out_all:
                out_all.append(name)
            if front_name is None and r.get("has_minute_data"):
                front_name = name
        if front_name is None and bucket_sorted:
            n = bucket_sorted[0].get("instrument")
            if isinstance(n, str):
                front_name = n
        if front_name and front_name not in out_current:
            out_current.append(front_name)
    return out_all, out_current


def whitelisted_strategies() -> List[str]:
    """Return the current strategy whitelist. Sourced from bridge catalog
    when available, otherwise the conservative fallback list. Result is also
    pushed back into module-level WHITELISTED_STRATEGIES so that older
    callers (incl. /api/strategies) see fresh values."""
    cat = read_strategies_catalog()
    names: List[str] = []
    if cat and isinstance(cat.get("strategies"), list):
        for s in cat["strategies"]:
            if isinstance(s, dict) and isinstance(s.get("class_name"), str):
                sf = _resolve_strategy_source_file(s["class_name"], s.get("source_file"))
                if not sf:
                    continue
                names.append(s["class_name"])
    if not names:
        names = list(_FALLBACK_STRATEGIES)
    # update mutable module-level reference
    WHITELISTED_STRATEGIES[:] = names
    return names


def build_catalog_response() -> Dict[str, Any]:
    """Aggregate response for GET /api/catalog. Combines strategies.json and
    instruments.json (bridge-written) with backend-side defaults and the
    explicit list of MVP-1 unsupported features so the UI does not have to
    hardcode anything.
    """
    warnings: List[str] = []

    # Lazy daily auto-refresh of the broker margin catalog. Non-blocking:
    # spawns a background daemon thread if the file is older than ~24h.
    try:
        marginrefresh.maybe_daily_refresh()
    except Exception:  # pragma: no cover — never fail catalog on this
        pass

    strat_doc = read_strategies_catalog()
    instr_doc = read_instruments_catalog()
    tmpl_doc  = read_templates_catalog()
    grp_doc   = read_instrument_groups_catalog()
    marg_doc  = read_margins_catalog()

    stale_info = catalog_staleness()
    if stale_info.get("stale") and stale_info.get("reason") == "dll_newer":
        warnings.append(
            "Каталог стратегий устарел: NinjaTrader.Custom.dll был "
            "перекомпилирован после последнего сканирования. "
            "Нажмите «Обновить каталог»."
        )

    if strat_doc is None:
        warnings.append(
            "strategies.json не найден — bridge ещё не запускался "
            "после старта NinjaTrader; показан резервный список."
        )
        strategies = [{
            "class_name":   name,
            "display_name": name,
            "source_file":  None,
            "parameters":   [],
            "fallback":     True,
        } for name in _FALLBACK_STRATEGIES]
        strategies_generated_at = None
    else:
        raw_strategies = strat_doc.get("strategies") or []
        strategies_generated_at = strat_doc.get("generated_at_utc")
        # Filter out ghost strategies: classes that exist in the compiled DLL
        # but whose source file has been deleted (.cs absent → source_file="").
        # Also filter out NT template stubs (source_file starts with "@").
        strategies = []
        for s in raw_strategies:
            cls_name = s.get("class_name", "")
            sf = _resolve_strategy_source_file(cls_name, s.get("source_file"))
            if not sf:
                warnings.append(
                    f"Стратегия {cls_name} исключена из каталога: "
                    "файл .cs удалён/архивирован, но класс ещё в DLL. "
                    "Перекомпилируйте скрипты в NinjaTrader (Tools → Compile)."
                )
                continue
            s = dict(s, source_file=sf)
            if os.path.basename(sf).startswith("@"):
                # Sample templates — keep but mark
                s = dict(s, is_sample=True)
            strategies.append(s)

    if instr_doc is None:
        warnings.append(
            "instruments.json не найден — bridge ещё не сканировал базу "
            "NinjaTrader; список инструментов пуст."
        )
        instruments = []
        instruments_generated_at = None
    else:
        instruments = instr_doc.get("instruments") or []
        instruments_generated_at = instr_doc.get("generated_at_utc")

    if tmpl_doc is None:
        warnings.append(
            "templates.json не найден — bridge ещё не сканировал шаблоны "
            "NinjaTrader; доступен только синтетический шаблон «None»."
        )
        commission_templates = [{
            "name": "None", "display": "None / 0 commission",
            "supported": True, "source": "synthetic-fallback",
        }]
        trading_hours_templates = []
        templates_generated_at = None
    else:
        commission_templates    = tmpl_doc.get("commission_templates") or []
        trading_hours_templates = tmpl_doc.get("trading_hours_templates") or []
        templates_generated_at  = tmpl_doc.get("generated_at_utc")
        # Surface any bridge-side notes.
        for n in (tmpl_doc.get("notes") or []):
            warnings.append(f"шаблоны: {n}")
        # If the catalog still contains explicitly-unsupported entries, surface
        # them — but a fully-supported list is silent.
        unsupported_names = [c.get("name") for c in commission_templates
                             if not c.get("supported") and c.get("name") != "None"]
        if unsupported_names:
            warnings.append(
                "Часть шаблонов комиссий не поддерживается bridge: " +
                ", ".join(unsupported_names)
            )

    return {
        "strategies": strategies,
        "instruments": instruments,
        "timeframes": {
            "types": ["Minute", "Second", "Tick", "Day", "Volume"],
            "presets": [
                {"label": "1 Minute",  "type": "Minute", "value": 1},
                {"label": "5 Minute",  "type": "Minute", "value": 5},
                {"label": "15 Minute", "type": "Minute", "value": 15},
                {"label": "60 Minute", "type": "Minute", "value": 60},
            ],
        },
        "commission_templates":    commission_templates,
        "trading_hours_templates": trading_hours_templates,
        "execution_defaults": {
            "calculate":             "OnBarClose",
            "is_tick_replay":        False,
            "order_fill_resolution": "High",
            "slippage_ticks":        1,
            "commission":            0.0,
            "commission_template":   "NinjaTrader Brokerage Free",
            "session_template":      "CME US Index Futures RTH",
            "timezone":              "UTC",
        },
        "supported_features": [
            "strategy_whitelist",
            "ninjascript_property_dynamic_form",
            "minute_data_instrument_scan",
            "period_invariant_check",
        ],
        "unsupported_features": [
            {"key": "trading_hours_template_other",
             "reason": "Bridge fixes session_template to CME US Index Futures RTH in MVP-1"},
            {"key": "break_at_eod",       "reason": "Not supported in MVP-1"},
            {"key": "exit_on_session_close", "reason": "Not supported in MVP-1"},
            {"key": "tick_replay",        "reason": "Not exposed in MVP-1 (fixed false)"},
            {"key": "include_trade_history_in_backtest", "reason": "Always true in MVP-1"},
        ],
        "generated_at_utc": {
            "strategies":  strategies_generated_at,
            "instruments": instruments_generated_at,
            "templates":   templates_generated_at,
            "instrument_groups": (grp_doc or {}).get("generated_at_utc"),
        },
        "instrument_groups": _build_instrument_groups_block(
            grp_doc, instruments, warnings),
        "margin_catalog": _build_margin_catalog_block(marg_doc, warnings),
        "staleness": stale_info,
        "warnings": warnings,
    }


def _build_margin_catalog_block(
    marg_doc: Optional[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    """Project margins.json into the /api/catalog response.

    The block is informational; if the file is missing or malformed we
    return an empty catalog and a warning so the UI can still render.
    The block also exposes the auto-refresh status so the UI can show
    last fetch time / errors next to the "Refresh now" button.
    """
    refresh_status = marginrefresh.last_status()
    if refresh_status.get("last_error") and not refresh_status.get("in_progress"):
        warnings.append(
            "Авто-обновление маржи не удалось: "
            f"{refresh_status['last_error']}. "
            "Используется предыдущий снимок margins.json."
        )

    if not isinstance(marg_doc, dict):
        warnings.append(
            "margins.json не найден — UI не сможет рассчитать "
            "доступность инструментов по марже (Account / Risk Profile)."
        )
        return {
            "schema_version": "0.1",
            "broker": "",
            "source": "missing",
            "source_url": "",
            "fetched_at_utc": "",
            "notes": [],
            "symbols": {},
            "warning": "margins_catalog_missing",
            "refresh": refresh_status,
        }

    symbols_in = marg_doc.get("symbols")
    symbols_out: Dict[str, Any] = {}
    if isinstance(symbols_in, dict):
        for root, rec in symbols_in.items():
            if not isinstance(root, str) or not isinstance(rec, dict):
                continue
            symbols_out[root.upper()] = {
                "display_name":       str(rec.get("display_name") or ""),
                "exchange":           str(rec.get("exchange") or ""),
                "intraday_margin":    rec.get("intraday_margin"),
                "initial_margin":     rec.get("initial_margin"),
                "maintenance_margin": rec.get("maintenance_margin"),
            }

    return {
        "schema_version": str(marg_doc.get("schema_version") or "0.1"),
        "broker":         str(marg_doc.get("broker") or ""),
        "source":         str(marg_doc.get("source") or ""),
        "source_url":     str(marg_doc.get("source_url") or ""),
        "fetched_at_utc": str(marg_doc.get("fetched_at_utc") or ""),
        "notes":          [str(n) for n in (marg_doc.get("notes") or [])
                           if isinstance(n, (str, int, float))],
        "symbols":        symbols_out,
        "refresh":        refresh_status,
    }


def _build_instrument_groups_block(
    grp_doc: Optional[Dict[str, Any]],
    instruments: List[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    """Resolve roots -> contract names against instruments catalog."""
    # Index instruments by root token (the first space-separated word, or the
    # whole symbol for non-futures naming like FOREX 6-letter codes).
    index: Dict[str, List[Dict[str, Any]]] = {}
    for r in instruments:
        name = r.get("instrument")
        if not isinstance(name, str):
            continue
        head = name.split(" ", 1)[0].upper()
        index.setdefault(head, []).append(r)
        # Also index on the full symbol so forex like "EURUSD" matches.
        index.setdefault(name.upper(), []).append(r)
    if not grp_doc or not isinstance(grp_doc.get("groups"), list):
        warnings.append(
            "instrument_groups.json не найден — панель групп скрыта.")
        return {
            "source": "missing",
            "warning": "instrument_groups.json missing",
            "groups": [],
        }
    src = grp_doc.get("source") or "fallback"
    out_groups: List[Dict[str, Any]] = []
    for g in grp_doc["groups"]:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("group_name") or "").strip()
        roots = [str(x) for x in (g.get("roots") or [])]
        if not gname:
            continue
        all_inst, current_inst = _resolve_group_instruments(roots, index)
        out_groups.append({
            "group_name":          gname,
            "roots":               roots,
            "instruments":         all_inst,
            "current_instruments": current_inst,
            "count":               len(all_inst),
            "current_count":       len(current_inst),
            "note":                str(g.get("note") or ""),
        })
    if src == "fallback":
        warnings.append(
            "Группы: эвристика, не список NinjaTrader.")
    return {
        "source":  src,
        "warning": grp_doc.get("warning") or "",
        "groups":  out_groups,
    }


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


@dataclass
class CreateJobRequest:
    class_name: str
    instrument: str
    bars_period_type: str
    bars_period_value: int
    from_utc: str
    to_utc: str
    parameters: Dict[str, Any]
    risk_profile: Dict[str, Any] = field(default_factory=dict)
    # execution defaults are validated/normalized below
    calculate: str = "OnBarClose"
    is_tick_replay: bool = False
    order_fill_resolution: str = "High"
    slippage_ticks: int = 1
    commission: float = 0.0
    commission_template: str = "None"
    session_template: str = "CME US Index Futures RTH"
    timezone: str = "UTC"
    job_id: Optional[str] = None
    # role gates the research-grade execution validator. Allowed:
    #   "research" (default) — High fill, slip>=1, commission honest.
    #   "smoke" / "debug"     — bypass research-grade checks.
    role: str = "research"
    # Batch membership (set by create_batch). For standalone /api/jobs POST
    # these stay None and the job behaves exactly as before.
    batch_id: Optional[str] = None
    batch_index: Optional[int] = None
    batch_total: Optional[int] = None


class JobValidationError(ValueError):
    pass


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _money(v: Any, name: str, min_value: float = 0.0,
           max_value: float = 100_000_000.0) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise JobValidationError(f"{name}: numeric value required")
    if not (min_value <= n <= max_value):
        raise JobValidationError(f"{name}: out of range {min_value}..{max_value}")
    return round(n, 2)


_RISK_STATUS_TEXT_INFORMATIONAL = (
    "Risk Profile сохранён в запуске; стратегия пока не ограничивается."
)


def _normalize_risk_profile(profile: Any) -> Dict[str, Any]:
    """Validate and normalize the optional informational account profile.

    Schema v0.1 (margin-catalog era):
        {
          "schema_version": "0.1",
          "mode": "informational",
          "currency": "USD",
          "starting_capital": 2000.0,
          "intraday_only": true,
          "margin_source": {"broker": "...", "source": "...", "fetched_at_utc": "..."},
          "instrument_margins": {
            "MES 06-26": {
              "root": "MES",
              "margin_type": "intraday",
              "margin_per_contract": 50.0,
              "max_contracts_by_capital": 40,
              "status": "allowed" | "blocked" | "unknown"
            }
          },
          "status": "informational_only",
          "status_text": "..."
        }

    The bridge stores this block in `result.context.risk_profile` and does
    NOT consume it for execution. The validated NinjaTrader Strategy Analyzer
    backtest path is unchanged.

    Legacy payloads (margin_per_contract.{intraday,overnight}) from older
    builds are accepted for read-back compatibility but are not required:
    the new UI never sends them.
    """
    if profile in (None, ""):
        return {}
    if not isinstance(profile, dict):
        raise JobValidationError("risk_profile must be an object")

    mode = str(profile.get("mode") or "informational")
    if mode != "informational":
        raise JobValidationError("risk_profile.mode unsupported")

    currency = str(profile.get("currency") or "USD").upper()
    if currency != "USD":
        raise JobValidationError("risk_profile.currency must be USD")

    starting = _money(profile.get("starting_capital", 0),
                      "risk_profile.starting_capital")
    intraday_only = bool(profile.get("intraday_only", True))

    msrc = profile.get("margin_source") or {}
    if not isinstance(msrc, dict):
        raise JobValidationError("risk_profile.margin_source must be an object")
    margin_source = {
        "broker":         str(msrc.get("broker") or ""),
        "source":         str(msrc.get("source") or ""),
        "fetched_at_utc": str(msrc.get("fetched_at_utc") or ""),
    }

    raw_margins = profile.get("instrument_margins") or {}
    if not isinstance(raw_margins, dict):
        raise JobValidationError(
            "risk_profile.instrument_margins must be an object")

    allowed_status = ("allowed", "blocked", "unknown")
    allowed_margin_type = ("intraday", "initial", "maintenance", "unknown")
    instrument_margins: Dict[str, Any] = {}
    for inst, info in raw_margins.items():
        if not isinstance(inst, str) or not isinstance(info, dict):
            continue
        root = str(info.get("root") or inst.split(" ", 1)[0]).upper()
        margin_type = str(info.get("margin_type") or
                          ("intraday" if intraday_only else "initial"))
        if margin_type not in allowed_margin_type:
            margin_type = "unknown"
        margin_val = info.get("margin_per_contract")
        if margin_val is None:
            margin_norm: Optional[float] = None
        else:
            margin_norm = _money(margin_val,
                                 f"risk_profile.instrument_margins[{inst}].margin_per_contract")
        max_c_raw = info.get("max_contracts_by_capital")
        if max_c_raw is None:
            max_c: Optional[int] = None
        else:
            try:
                max_c = max(0, int(max_c_raw))
            except (TypeError, ValueError):
                raise JobValidationError(
                    f"risk_profile.instrument_margins[{inst}].max_contracts_by_capital "
                    "must be an integer or null")
        status = str(info.get("status") or "unknown")
        if status not in allowed_status:
            status = "unknown"
        instrument_margins[inst] = {
            "root":                     root,
            "margin_type":              margin_type,
            "margin_per_contract":      margin_norm,
            "max_contracts_by_capital": max_c,
            "status":                   status,
        }

    return {
        "schema_version":     "0.1",
        "mode":               "informational",
        "currency":           "USD",
        "starting_capital":   starting,
        "intraday_only":      intraday_only,
        "margin_source":      margin_source,
        "instrument_margins": instrument_margins,
        "status":             "informational_only",
        "status_text":        _RISK_STATUS_TEXT_INFORMATIONAL,
    }


# ---------------------------------------------------------------------------
# Risk Profile -> strategy.parameters bridge contract
# ---------------------------------------------------------------------------
# Phase 0 contract documented in:
#   РАЗРАБОТКА СТРАТЕГИЙ/01_ПЛАН_СТРАТЕГИИ_NTAMicroVwapRiskPilot.md §3
#
# The bridge (StrategyAnalyzerRunner.ApplyStrategyParameters) only injects
# job.strategy.parameters into NinjaScriptProperty fields. The raw
# `risk_profile` block is preserved in result.context but never reaches the
# strategy. To let strategies consume capital / margin / intraday flag, we
# project the normalized Risk Profile into strategy.parameters under a fixed
# whitelist of names. UI-generated zero/unknown placeholders are overwritten
# by the normalized profile; real non-placeholder operator values are kept.
RISK_PROFILE_PARAM_KEYS = (
    "StartingCapital",
    "IntradayOnly",
    "ActiveMarginPerContract",
    "MaxContractsByCapital",
    "InstrumentStatus",
    "MarginSourceBroker",
)

RESEARCH_ROUND_TURN_COMMISSION = 1.90

LOCKED_B1_SHORTONLY_PARAMS: Dict[str, Any] = {
    "StartingCapital": 2000.0,
    "IntradayOnly": True,
    "ActiveMarginPerContract": 50.0,
    "MaxContractsByCapital": 40,
    "InstrumentStatus": "allowed",
    "MarginSourceBroker": "NinjaTrader",
    "EnableLong": False,
    "EnableShort": True,
    "UseDailyBiasFilter": False,
    "EmaFastPeriod": 50,
    "EmaSlowPeriod": 200,
    "TradeStartTime": 635,
    "TradeEndTime": 700,
    "MinStopTicks": 12,
    "MaxStopTicks": 12,
    "RewardRiskRatio": 3.5,
    "RiskPerTradePct": 2.0,
    "UserMaxContracts": 5,
    "RoundTurnCommission": 1.90,
    "SlippageTicks": 1,
}


def _strategy_parameter_names(class_name: str) -> set[str]:
    """Return tunable NinjaScriptProperty names for class_name from catalog.

    The bridge rejects unknown strategy.parameters. Backend-side injections
    therefore must only add fields the concrete strategy actually exposes.
    """
    try:
        cat = read_strategies_catalog() or {}
    except Exception:
        cat = {}
    for s in cat.get("strategies") or []:
        if not isinstance(s, dict) or s.get("class_name") != class_name:
            continue
        names: set[str] = set()
        for p in s.get("parameters") or []:
            if isinstance(p, dict) and isinstance(p.get("name"), str):
                names.add(p["name"])
        return names
    return set()


def _effective_round_turn_commission(req: "CreateJobRequest") -> float:
    try:
        rtc = float((req.parameters or {}).get("RoundTurnCommission", 0.0) or 0.0)
    except (TypeError, ValueError):
        rtc = 0.0
    return rtc if rtc >= RESEARCH_ROUND_TURN_COMMISSION else RESEARCH_ROUND_TURN_COMMISSION


def _inject_research_accounting_parameters(req: "CreateJobRequest") -> None:
    """Inject honest accounting params only when the strategy exposes them.

    For older/sample strategies that do not have RoundTurnCommission or
    SlippageTicks properties, we keep those fields out of strategy.parameters
    so the strict NinjaTrader bridge can still run the backtest. The honest
    commission used for UI/report metrics is stored in execution instead.
    """
    if not isinstance(req.parameters, dict):
        req.parameters = {}
    exposed = _strategy_parameter_names(req.class_name)
    if "RoundTurnCommission" in exposed:
        try:
            cur = float(req.parameters.get("RoundTurnCommission", 0.0) or 0.0)
        except (TypeError, ValueError):
            cur = 0.0
        if cur < RESEARCH_ROUND_TURN_COMMISSION:
            req.parameters["RoundTurnCommission"] = RESEARCH_ROUND_TURN_COMMISSION
    if "SlippageTicks" in exposed:
        try:
            cur = int(req.parameters.get("SlippageTicks", 0) or 0)
        except (TypeError, ValueError):
            cur = 0
        if cur < 1:
            req.parameters["SlippageTicks"] = max(1, int(req.slippage_ticks))


def _apply_locked_strategy_parameters(req: "CreateJobRequest") -> None:
    """Enforce locked production/paper defaults for approved strategies."""
    if req.class_name != "NTAMicroVwapRiskPilot":
        return
    if not isinstance(req.parameters, dict):
        req.parameters = {}
    req.parameters.update(LOCKED_B1_SHORTONLY_PARAMS)


def _inject_risk_profile_parameters(req: "CreateJobRequest") -> None:
    """Project req.risk_profile -> req.parameters using RISK_PROFILE_PARAM_KEYS.

    Safe defaults when the instrument is missing from instrument_margins:
        ActiveMarginPerContract = 0.0
        MaxContractsByCapital   = 0
        InstrumentStatus        = "unknown"

    The strategy is responsible for refusing to trade when these are unsafe
    (status != "allowed", margin <= 0, max contracts < 1, capital <= 0).

    When a Risk Profile is present it is authoritative for account/margin
    values. Locked strategy defaults are trading-logic defaults, not a reason
    to keep stale margin assumptions (for example MNQ intraday margin moving
    from $50 to $100).
    """
    rp = req.risk_profile or {}
    if not isinstance(rp, dict) or not rp:
        return
    inst_map = rp.get("instrument_margins") or {}
    inst_info = inst_map.get(req.instrument) if isinstance(inst_map, dict) else None
    if not isinstance(inst_info, dict):
        inst_info = {}

    margin_val = inst_info.get("margin_per_contract")
    max_c      = inst_info.get("max_contracts_by_capital")
    status     = inst_info.get("status") or "unknown"
    broker     = ""
    msrc       = rp.get("margin_source")
    if isinstance(msrc, dict):
        broker = str(msrc.get("broker") or "")

    derived: Dict[str, Any] = {
        "StartingCapital":         float(rp.get("starting_capital") or 0.0),
        "IntradayOnly":            bool(rp.get("intraday_only", True)),
        "ActiveMarginPerContract": float(margin_val) if margin_val is not None else 0.0,
        "MaxContractsByCapital":   int(max_c) if max_c is not None else 0,
        "InstrumentStatus":        str(status),
        "MarginSourceBroker":      str(broker),
    }
    if not isinstance(req.parameters, dict):
        req.parameters = {}
    exposed = _strategy_parameter_names(req.class_name)
    for k in RISK_PROFILE_PARAM_KEYS:
        if k not in exposed:
            continue
        req.parameters[k] = derived[k]


def _risk_profile_param_is_placeholder(key: str, value: Any) -> bool:
    """Return True for empty UI defaults that should not block risk injection."""
    if value is None:
        return True
    if key in ("StartingCapital", "ActiveMarginPerContract"):
        try:
            return float(value) <= 0
        except (TypeError, ValueError):
            return True
    if key == "MaxContractsByCapital":
        try:
            return int(value) <= 0
        except (TypeError, ValueError):
            return True
    if key == "InstrumentStatus":
        return str(value or "").strip().lower() in ("", "unknown", "blocked")
    if key == "MarginSourceBroker":
        return str(value or "").strip() == ""
    return False


def _validate(req: CreateJobRequest) -> None:
    allowed = whitelisted_strategies()
    if req.class_name not in allowed:
        raise JobValidationError(
            f"strategy '{req.class_name}' is not whitelisted. "
            f"Allowed: {allowed}"
        )
    if not req.instrument or len(req.instrument) > 64:
        raise JobValidationError("instrument: required, max 64 chars")
    if req.bars_period_type not in ("Minute", "Day", "Tick", "Second", "Volume"):
        raise JobValidationError(f"bars_period_type unsupported: {req.bars_period_type}")
    if not (1 <= int(req.bars_period_value) <= 1440):
        raise JobValidationError("bars_period_value out of range 1..1440")
    if not _ISO_RE.match(req.from_utc) or not _ISO_RE.match(req.to_utc):
        raise JobValidationError("from_utc/to_utc must match YYYY-MM-DDTHH:MM:SSZ")
    if req.from_utc >= req.to_utc:
        raise JobValidationError("from_utc must be strictly before to_utc")
    if req.calculate not in ("OnBarClose", "OnEachTick", "OnPriceChange"):
        raise JobValidationError(f"calculate unsupported: {req.calculate}")
    if req.order_fill_resolution not in ("Standard", "High"):
        raise JobValidationError(f"order_fill_resolution unsupported: {req.order_fill_resolution}")
    if not (0 <= int(req.slippage_ticks) <= 100):
        raise JobValidationError("slippage_ticks out of range 0..100")
    # Numeric commission is informational only — bridge does NOT apply a
    # per-trade $ commission, only commission_template. Any non-zero numeric
    # commission would silently produce wrong metrics, so reject it.
    if float(req.commission) != 0.0:
        raise JobValidationError(
            "Числовая комиссия не поддерживается: используйте commission_template. "
            "Поле commission должно быть 0."
        )
    # commission_template: require it to exist in the catalog and be supported.
    # 'None' is always allowed (synthetic 0-commission). Real templates are
    # marked supported=true once bridge can apply them.
    if req.commission_template != "None":
        try:
            tmpl_doc = read_templates_catalog() or {}
        except Exception:
            tmpl_doc = {}
        templates = {t.get("name"): t
                     for t in (tmpl_doc.get("commission_templates") or [])}
        tmpl = templates.get(req.commission_template)
        if tmpl is None:
            raise JobValidationError(
                f"Шаблон комиссии «{req.commission_template}» не найден в каталоге. "
                "Перезапустите bridge, чтобы пересканировать templates/Commission."
            )
        if not tmpl.get("supported"):
            reason = tmpl.get("reason") or "не поддерживается bridge"
            raise JobValidationError(
                f"Шаблон комиссии «{req.commission_template}» найден, но "
                f"bridge пока не умеет его применять: {reason}"
            )
    if req.session_template != "CME US Index Futures RTH":
        raise JobValidationError(
            "trading_hours_template_unsupported: bridge fixes session_template "
            f"to 'CME US Index Futures RTH' in MVP-1, got '{req.session_template}'"
        )
    if req.timezone != "UTC":
        raise JobValidationError("timezone must be 'UTC'")
    if not isinstance(req.parameters, dict):
        raise JobValidationError("parameters must be an object")
    for k, v in req.parameters.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
            raise JobValidationError(f"parameter name not identifier-safe: {k}")
        if not isinstance(v, (int, float, bool, str)):
            raise JobValidationError(f"parameter '{k}': only int/float/bool/string allowed")
    req.risk_profile = _normalize_risk_profile(req.risk_profile)
    if req.job_id is not None and not JOB_ID_PATTERN.match(req.job_id):
        raise JobValidationError("job_id contains forbidden characters")

    # ------------------------------------------------------------------
    # Research-grade execution gate. Phase 12A (post-Phase-11 retraction).
    # Any job tagged role="research" (default) MUST use realistic fill +
    # explicit honest commission. Standard fill / slip=0 / no commission
    # silently inflate edge by 3-5x; this gate prevents that ever again.
    # role="smoke" or "debug" bypasses the gate but is recorded in job.json
    # so post-hoc audits can exclude such runs from any acceptance verdict.
    # ------------------------------------------------------------------
    role = (getattr(req, "role", "research") or "research").lower()
    if role not in ("research", "smoke", "debug"):
        raise JobValidationError(
            f"role must be 'research'|'smoke'|'debug' (got {req.role!r})"
        )
    req.role = role
    if role == "research":
        errs: List[str] = []
        exposed_params = _strategy_parameter_names(req.class_name)
        if req.order_fill_resolution != "High":
            errs.append(
                "order_fill_resolution must be 'High' for research jobs "
                f"(got {req.order_fill_resolution!r}). Use role='smoke' to bypass."
            )
        if int(req.slippage_ticks) < 1:
            errs.append(
                "slippage_ticks must be >=1 for research jobs "
                f"(got {req.slippage_ticks!r})."
            )
        if req.commission_template != "None":
            # If a real template is set, _validate above already required
            # bridge support. For research we additionally require that
            # commission accounting is honest — currently NT bridge can only
            # post-adjust via parameters.RoundTurnCommission, so template
            # 'None' is the supported research path.
            pass
        if "RoundTurnCommission" in exposed_params:
            rtc = req.parameters.get("RoundTurnCommission")
            try:
                rtc_v = float(rtc) if rtc is not None else None
            except (TypeError, ValueError):
                rtc_v = None
            if rtc_v is None or rtc_v < RESEARCH_ROUND_TURN_COMMISSION:
                errs.append(
                    "parameters.RoundTurnCommission must be >=1.90 for research jobs "
                    f"(got {rtc!r}). Micro futures minimum honest round-turn."
                )
        if "SlippageTicks" in exposed_params:
            pst = req.parameters.get("SlippageTicks")
            try:
                pst_v = int(pst) if pst is not None else None
            except (TypeError, ValueError):
                pst_v = None
            if pst_v is None or pst_v < 1:
                errs.append(
                    "parameters.SlippageTicks must be >=1 for research jobs "
                    f"(got {pst!r}). Must match top-level slippage_ticks."
                )
        if errs:
            raise JobValidationError(
                "research-grade gate failed: " + "; ".join(errs)
            )


def create_job(req: CreateJobRequest) -> Tuple[str, Path]:
    """Create a job in pending/. Returns (job_id, pending_job_dir)."""
    _apply_locked_strategy_parameters(req)
    _inject_research_accounting_parameters(req)
    # Risk Profile bridge contract (see _inject_risk_profile_parameters):
    # projects normalized risk_profile -> strategy.parameters so the strategy
    # can read capital/margin/intraday/status via [NinjaScriptProperty].
    _inject_risk_profile_parameters(req)
    _validate(req)

    job_id = req.job_id or gen_job_id("ui")
    pending = jobs_dir() / "pending"
    staging_root = pending / ".staging"
    staging_job = staging_root / job_id
    pending_job = pending / job_id

    if pending_job.exists():
        raise JobValidationError(f"pending/{job_id} already exists")
    if staging_job.exists():
        shutil.rmtree(staging_job)

    staging_job.mkdir(parents=True, exist_ok=True)

    job_doc = {
        "schema_version": "0.1",
        "job_id": job_id,
        "created_at_utc": utcnow_iso(),
        "kind": "historical_backtest",
        "strategy": {
            "class_name": req.class_name,
            "source_file_hint": "",
            "parameters": dict(req.parameters),
        },
        "instrument": req.instrument,
        "timeframe": {
            "bars_period_type": req.bars_period_type,
            "value": int(req.bars_period_value),
        },
        "period": {"from_utc": req.from_utc, "to_utc": req.to_utc},
        "risk_profile": dict(req.risk_profile or {}),
        "execution": {
            "calculate": req.calculate,
            "is_tick_replay": bool(req.is_tick_replay),
            "order_fill_resolution": req.order_fill_resolution,
            "slippage_ticks": int(req.slippage_ticks),
            "commission": float(req.commission),
            "commission_template": req.commission_template,
            "session_template": req.session_template,
            "timezone": req.timezone,
            "role": getattr(req, "role", "research"),
            "round_turn_commission": _effective_round_turn_commission(req),
        },
    }
    if req.batch_id:
        job_doc["batch"] = {
            "batch_id":    req.batch_id,
            "batch_index": int(req.batch_index or 0),
            "batch_total": int(req.batch_total or 0),
        }

    _atomic_write_text(staging_job / "job.json",
                       json.dumps(job_doc, ensure_ascii=False, indent=2))

    # Atomic Directory.Move staging\<id> -> pending\<id>
    os.rename(staging_job, pending_job)
    # try cleanup empty staging
    try:
        if staging_root.exists() and not any(staging_root.iterdir()):
            staging_root.rmdir()
    except OSError:
        pass

    return job_id, pending_job


# ---------------------------------------------------------------------------
# Read-side: list / get / metrics summary
# ---------------------------------------------------------------------------

def _safe_job_id(job_id: str) -> str:
    if not JOB_ID_PATTERN.match(job_id or ""):
        raise JobValidationError("invalid job_id")
    return job_id


def find_job_dir(job_id: str) -> Optional[Tuple[str, Path]]:
    """Return (status, dir) or None."""
    job_id = _safe_job_id(job_id)
    for sub in QUEUE_SUBDIRS:
        p = jobs_dir() / sub / job_id
        if p.is_dir():
            return sub, p
    return None


def queue_counts() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for sub in QUEUE_SUBDIRS:
        d = jobs_dir() / sub
        if not d.is_dir():
            out[sub] = 0
            continue
        n = 0
        for child in d.iterdir():
            if child.is_dir() and child.name != ".staging":
                n += 1
        out[sub] = n
    return out


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """Most recent first across all queues."""
    report_numbers = sync_report_numbers()
    rows: List[Dict[str, Any]] = []
    for sub in QUEUE_SUBDIRS:
        d = jobs_dir() / sub
        if not d.is_dir():
            continue
        for child in d.iterdir():
            if not child.is_dir() or child.name == ".staging":
                continue
            try:
                mtime = child.stat().st_mtime
            except OSError:
                continue
            rows.append({
                "job_id": child.name,
                "status": sub,
                "path": str(child),
                "mtime": mtime,
            })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    out: List[Dict[str, Any]] = []
    for r in rows[: max(1, limit)]:
        meta = read_job_summary(r["job_id"])
        if meta:
            r.update(meta)
        if not (r.get("batch") or {}).get("batch_id"):
            r["report_no"] = report_numbers.get(_report_key("job", r["job_id"]))
        out.append(r)
    return out


def latest_job() -> Optional[Dict[str, Any]]:
    rows = list_jobs(limit=1)
    return rows[0] if rows else None


def _read_json_safe(path: Path) -> Optional[Any]:
    # utf-8-sig tolerates the BOM that PowerShell's Set-Content -Encoding UTF8
    # writes by default in Windows PowerShell 5.1.
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _compute_adjusted_metrics(trades: Optional[List[Any]],
                              parameters: Optional[Dict[str, Any]],
                              base_metrics: Optional[Dict[str, Any]] = None,
                              round_turn_commission: Optional[Any] = None
                              ) -> Optional[Dict[str, Any]]:
    """Compute commission-adjusted metrics from per-trade data.

    NinjaTrader runs use commission_template=None for backtests. Some
    strategies expose RoundTurnCommission as a NinjaScriptProperty, older/sample
    strategies do not. metrics.net_profit in result.json is therefore GROSS
    PnL; this helper recomputes adjusted metrics after paying the research
    round-turn commission per contract per trade.
    """
    if not isinstance(trades, list) or not trades:
        return None
    rtc = 0.0
    if isinstance(parameters, dict):
        try:
            rtc = float(parameters.get("RoundTurnCommission", 0.0) or 0.0)
        except (TypeError, ValueError):
            rtc = 0.0
    if rtc <= 0 and round_turn_commission is not None:
        try:
            rtc = float(round_turn_commission or 0.0)
        except (TypeError, ValueError):
            rtc = 0.0
    if rtc <= 0:
        return None

    n = 0
    gross_profit = 0.0
    gross_loss = 0.0
    commission_total = 0.0
    adjusted_pnls: List[float] = []
    wins = 0
    sum_w = 0.0
    sum_l = 0.0
    for t in trades:
        if not isinstance(t, dict):
            continue
        try:
            pnl = float(t.get("pnl_currency", 0.0) or 0.0)
            qty = float(t.get("quantity", 1) or 1)
        except (TypeError, ValueError):
            continue
        comm = qty * rtc
        adj = pnl - comm
        n += 1
        commission_total += comm
        if pnl > 0:
            gross_profit += pnl
        else:
            gross_loss += pnl
        if adj > 0:
            wins += 1
            sum_w += adj
        else:
            sum_l += abs(adj)
        adjusted_pnls.append(adj)

    if n == 0:
        return None

    gross_net = gross_profit + gross_loss
    net_after = gross_net - commission_total
    pf_after = (sum_w / sum_l) if sum_l > 0 else (None if sum_w == 0 else float("inf"))
    win_pct_after = round(wins / n * 100.0, 4)

    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for x in adjusted_pnls:
        cum += x
        if cum > peak:
            peak = cum
        if cum - peak < mdd:
            mdd = cum - peak

    out = {
        "round_turn_commission": rtc,
        "commission_total_adjusted": round(commission_total, 4),
        "net_profit_after_commission": round(net_after, 4),
        "profit_factor_after_commission":
            (round(pf_after, 6) if isinstance(pf_after, float) and pf_after != float("inf") else pf_after),
        "max_drawdown_after_commission": round(mdd, 4),
        "win_pct_after_commission": win_pct_after,
        "trade_count_adjusted": n,
        "commission_template_used": "None (research round-turn commission)",
    }
    return out


def read_job_summary(job_id: str) -> Optional[Dict[str, Any]]:
    located = find_job_dir(job_id)
    if not located:
        return None
    status, jdir = located

    summary: Dict[str, Any] = {"status": status}

    job = _read_json_safe(jdir / "job.json") or {}
    summary["class_name"] = (job.get("strategy") or {}).get("class_name")
    summary["instrument"] = job.get("instrument")
    summary["timeframe"] = job.get("timeframe")
    summary["period"] = job.get("period")
    summary["created_at_utc"] = job.get("created_at_utc")
    summary["batch"] = job.get("batch")  # None for single jobs

    if status == "done":
        res = _read_json_safe(jdir / "result.json") or {}
        summary["finished_at_utc"] = res.get("finished_at_utc")
        summary["duration_ms"] = res.get("duration_ms")
        summary["metrics"] = res.get("metrics") or {}
        m = summary["metrics"]
        summary["trade_count"] = m.get("trade_count")
        summary["winning_pct"] = m.get("winning_pct")
        summary["net_profit"]  = m.get("net_profit")
        summary["gross_profit"] = m.get("gross_profit")
        summary["gross_loss"] = m.get("gross_loss")
        # Phase 22d/22i — surface/fallback for the reports rating column.
        summary["profit_factor"] = m.get("profit_factor")
        if summary["profit_factor"] is None:
            pf = _profit_factor_from_gross(m.get("gross_profit"), m.get("gross_loss"))
            if pf is not None:
                summary["profit_factor"] = pf
        summary["max_drawdown"]  = m.get("max_drawdown")

        # --- Commission-adjusted metrics ---
        # NinjaTrader runs use commission_template=None so metrics.net_profit
        # is GROSS. Recompute "real" metrics from per-trade RoundTurnCommission.
        try:
            trades_doc = _read_json_safe(jdir / "trades.json")
            params = ((job.get("strategy") or {}).get("parameters") or {})
            execution = (job.get("execution") or {})
            adj = _compute_adjusted_metrics(
                trades_doc,
                params,
                m,
                execution.get("round_turn_commission"),
            )
            if adj:
                m.update(adj)
                summary["net_profit_after_commission"] = adj.get("net_profit_after_commission")
                summary["profit_factor_after_commission"] = adj.get("profit_factor_after_commission")
                summary["commission_total_adjusted"] = adj.get("commission_total_adjusted")
        except Exception:
            pass

        summary["validated_against_strategy_analyzer"] = VALIDATED_AGAINST_STRATEGY_ANALYZER
    elif status == "failed":
        err = _read_json_safe(jdir / "error.json") or {}
        summary["error_type"] = err.get("error_type")
        summary["error_message"] = (err.get("message") or "").splitlines()[0] if err.get("message") else None
        summary["finished_at_utc"] = err.get("finished_at_utc")
    elif status == "running":
        hb = _read_json_safe(jdir / "heartbeat.json") or {}
        summary["heartbeat_at_utc"] = hb.get("updated_at_utc")
    return summary


def read_job_full(job_id: str) -> Optional[Dict[str, Any]]:
    located = find_job_dir(job_id)
    if not located:
        return None
    status, jdir = located
    out: Dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "path": str(jdir),
        "files": [p.name for p in jdir.iterdir() if p.is_file()],
        "validated_against_strategy_analyzer": VALIDATED_AGAINST_STRATEGY_ANALYZER,
    }
    out["job"] = _read_json_safe(jdir / "job.json")
    # Lift the batch link (if any) to the top level so the UI can detect
    # batch membership without diving into the raw job.json sub-object.
    job_doc = out["job"]
    if isinstance(job_doc, dict) and isinstance(job_doc.get("batch"), dict):
        out["batch"] = job_doc["batch"]
    if status == "done":
        out["result"] = _read_json_safe(jdir / "result.json")
        # Augment metrics with commission-adjusted view (real net etc).
        try:
            res = out["result"] or {}
            m = res.get("metrics") or {}
            trades_doc = _read_json_safe(jdir / "trades.json")
            params = ((job_doc.get("strategy") if isinstance(job_doc, dict) else None) or {}).get("parameters") or {}
            execution = ((job_doc.get("execution") if isinstance(job_doc, dict) else None) or {})
            adj = _compute_adjusted_metrics(
                trades_doc,
                params,
                m,
                execution.get("round_turn_commission"),
            )
            if adj and isinstance(m, dict):
                m.update(adj)
                res["metrics"] = m
                out["result"] = res
        except Exception:
            pass
    elif status == "failed":
        out["error"] = _read_json_safe(jdir / "error.json")
        out["result_partial"] = _read_json_safe(jdir / "result.partial.json")
    elif status == "running":
        out["heartbeat"] = _read_json_safe(jdir / "heartbeat.json")
    return out


def read_trades(job_id: str, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
    located = find_job_dir(job_id)
    if not located:
        return {"job_id": job_id, "found": False, "trades": [], "total": 0}
    status, jdir = located
    tj = jdir / "trades.json"
    if not tj.is_file():
        return {"job_id": job_id, "status": status, "trades": [], "total": 0,
                "note": "trades.json missing for this job"}
    arr = _read_json_safe(tj)
    if not isinstance(arr, list):
        return {"job_id": job_id, "status": status, "trades": [], "total": 0,
                "note": "trades.json malformed"}
    total = len(arr)
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 100
    if limit > 1000:
        limit = 1000
    return {
        "job_id": job_id,
        "status": status,
        "total": total,
        "offset": offset,
        "limit": limit,
        "trades": arr[offset: offset + limit],
    }


def read_bars(job_id: str, offset: int = 0, limit: int = 5000) -> Dict[str, Any]:
    """Returns OHLCV bars artifact for a job.

    Older jobs have no bars.json — surface a 'note' instead of raising so
    the UI can render an "artifact missing" state cleanly.
    """
    located = find_job_dir(job_id)
    if not located:
        return {"job_id": job_id, "found": False, "bars": [], "total": 0}
    status, jdir = located
    bj = jdir / "bars.json"
    if not bj.is_file():
        return {"job_id": job_id, "status": status, "bars": [], "total": 0,
                "note": "bars.json missing for this job"}
    arr = _read_json_safe(bj)
    if not isinstance(arr, list):
        return {"job_id": job_id, "status": status, "bars": [], "total": 0,
                "note": "bars.json malformed"}
    total = len(arr)
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 5000
    if limit > 200000:
        limit = 200000
    return {
        "job_id": job_id,
        "status": status,
        "total": total,
        "offset": offset,
        "limit": limit,
        "bars": arr[offset: offset + limit],
    }


def read_draw_objects(job_id: str) -> Dict[str, Any]:
    """Returns the strategy-draw-objects artifact for a job.

    Universal schema: {version, objects:[...], diagnostics:[...]}.
    Older jobs (or jobs run with a bridge that predates draw_objects.json)
    are reported as exported=false with a reason — UI shows a friendly hint
    instead of crashing.
    """
    located = find_job_dir(job_id)
    if not located:
        return {"job_id": job_id, "exported": False, "reason": "job_not_found",
                "objects": [], "diagnostics": []}
    status, jdir = located
    f = jdir / "draw_objects.json"
    if not f.is_file():
        return {"job_id": job_id, "status": status, "exported": False,
                "reason": "file_missing",
                "objects": [], "diagnostics": [
                    "draw_objects.json не найден — job выполнен старой версией bridge"
                ]}
    payload = _read_json_safe(f)
    if not isinstance(payload, dict):
        return {"job_id": job_id, "status": status, "exported": False,
                "reason": "malformed", "objects": [], "diagnostics": []}
    objs = payload.get("objects") or []
    return {
        "job_id": job_id,
        "status": status,
        "exported": True,
        "version": payload.get("version") or 1,
        "objects": objs if isinstance(objs, list) else [],
        "diagnostics": payload.get("diagnostics") or [],
    }


# ---------------------------------------------------------------------------
# Diagnostics: NinjaTrader process + bridge log tail.
# ---------------------------------------------------------------------------

def ninjatrader_user_dir() -> Path:
    env = os.environ.get("NT_USER_DIR")
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / "Documents" / "NinjaTrader 8"


def bridge_log_tail(lines: int = 40) -> List[str]:
    log = ninjatrader_user_dir() / "log" / "NTAnalyzerBridge.log"
    if not log.is_file():
        return []
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.readlines()
        return [s.rstrip() for s in data[-lines:]]
    except OSError:
        return []


def ninjatrader_running() -> Optional[bool]:
    """Best-effort cross-process check via tasklist (Windows only).

    Returns True/False on a confident match, or None ("unknown") when the
    detection itself failed (tasklist missing, timeout, OS not Windows).
    The case-insensitive substring scan also tolerates variations like
    "NinjaTrader 8.exe".
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import subprocess
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
        out = subprocess.run(
            [str(tasklist), "/FO", "CSV", "/NH"],
            capture_output=True,
            text=False,
            timeout=4,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        if out.returncode != 0:
            return None
        stdout = (out.stdout or b"").decode("utf-8", errors="ignore")
        stderr = (out.stderr or b"").decode("utf-8", errors="ignore")
        haystack = stdout.lower() + "\n" + stderr.lower()
        return "ninjatrader" in haystack
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Batches (multi-instrument runs).
#
# A batch is a thin metadata wrapper that owns N child jobs (one per
# instrument). Bridge does not need to know about batches at all: each child
# job is a normal /jobs/pending/<id>/job.json that the bridge picks up
# sequentially. Batch state is reconstructed at read time by aggregating the
# child jobs.
# ---------------------------------------------------------------------------

BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")


def batches_dir() -> Path:
    return project_root() / "data" / "batches"


def gen_batch_id(prefix: str = "batch") -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')[:-3]}Z"


@dataclass
class CreateBatchRequest:
    class_name: str
    instruments: List[str]
    bars_period_type: str
    bars_period_value: int
    from_utc: str
    to_utc: str
    parameters: Dict[str, Any]
    risk_profile: Dict[str, Any] = field(default_factory=dict)
    calculate: str = "OnBarClose"
    is_tick_replay: bool = False
    order_fill_resolution: str = "High"
    slippage_ticks: int = 1
    commission: float = 0.0
    commission_template: str = "None"
    session_template: str = "CME US Index Futures RTH"
    timezone: str = "UTC"
    batch_id: Optional[str] = None
    name: Optional[str] = None  # display name for the batch
    # See CreateJobRequest.role.
    role: str = "research"


def create_batch(req: CreateBatchRequest) -> Tuple[str, List[str]]:
    """Create a batch + N child jobs (one per instrument).

    Returns (batch_id, [job_id, ...]).
    """
    if not isinstance(req.instruments, list) or not req.instruments:
        raise JobValidationError("instruments: non-empty list required")
    # De-duplicate while preserving order.
    seen: List[str] = []
    for s in req.instruments:
        if not isinstance(s, str) or not s.strip():
            raise JobValidationError("instruments must be non-empty strings")
        s = s.strip()
        if s not in seen:
            seen.append(s)
    if len(seen) > 50:
        raise JobValidationError("batch capped at 50 instruments")

    risk_profile = _normalize_risk_profile(req.risk_profile)
    batch_id = req.batch_id or gen_batch_id("batch")
    if not BATCH_ID_PATTERN.match(batch_id):
        raise JobValidationError("batch_id contains forbidden characters")
    bdir = batches_dir() / batch_id
    if bdir.exists():
        raise JobValidationError(f"batch {batch_id} already exists")

    total = len(seen)
    created_job_ids: List[str] = []
    children_meta: List[Dict[str, Any]] = []
    for idx, instrument in enumerate(seen):
        # Suffix the batch id into the job id so they sort together and are
        # easy to spot in jobs/pending.
        child_id = f"{batch_id}__{idx:02d}_{re.sub(r'[^A-Za-z0-9]+', '', instrument)[:16]}"
        child_req = CreateJobRequest(
            class_name=req.class_name,
            instrument=instrument,
            bars_period_type=req.bars_period_type,
            bars_period_value=req.bars_period_value,
            from_utc=req.from_utc,
            to_utc=req.to_utc,
            parameters=dict(req.parameters or {}),
            risk_profile=dict(risk_profile),
            calculate=req.calculate,
            is_tick_replay=req.is_tick_replay,
            order_fill_resolution=req.order_fill_resolution,
            slippage_ticks=req.slippage_ticks,
            commission=req.commission,
            commission_template=req.commission_template,
            session_template=req.session_template,
            timezone=req.timezone,
            job_id=child_id,
            role=getattr(req, "role", "research"),
            batch_id=batch_id,
            batch_index=idx,
            batch_total=total,
        )
        try:
            jid, _ = create_job(child_req)
        except JobValidationError as e:
            # Roll back already-created children so the batch is atomic.
            for done_id in created_job_ids:
                _try_remove_pending_job(done_id)
            raise JobValidationError(
                f"batch child {idx} ({instrument}): {e}") from e
        created_job_ids.append(jid)
        children_meta.append({
            "batch_index": idx,
            "instrument":  instrument,
            "job_id":      jid,
        })

    # Persist batch manifest.
    bdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "0.1",
        "batch_id": batch_id,
        "name": req.name or f"{req.class_name} x{total}",
        "created_at_utc": utcnow_iso(),
        "strategy": {
            "class_name": req.class_name,
            "parameters": dict(req.parameters or {}),
        },
        "timeframe": {
            "bars_period_type": req.bars_period_type,
            "value": int(req.bars_period_value),
        },
        "period": {"from_utc": req.from_utc, "to_utc": req.to_utc},
        "risk_profile": dict(risk_profile),
        "execution": {
            "calculate": req.calculate,
            "is_tick_replay": bool(req.is_tick_replay),
            "order_fill_resolution": req.order_fill_resolution,
            "slippage_ticks": int(req.slippage_ticks),
            "commission": float(req.commission),
            "commission_template": req.commission_template,
            "session_template": req.session_template,
            "timezone": req.timezone,
            "role": getattr(req, "role", "research"),
        },
        "instruments": seen,
        "children": children_meta,
        "total": total,
    }
    _atomic_write_text(bdir / "batch.json",
                       json.dumps(manifest, ensure_ascii=False, indent=2))
    return batch_id, created_job_ids


def _try_remove_pending_job(job_id: str) -> None:
    """Best-effort cleanup of a pending job dir (used to roll back partial
    batch creation)."""
    try:
        p = jobs_dir() / "pending" / job_id
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def _safe_batch_id(batch_id: str) -> str:
    if not BATCH_ID_PATTERN.match(batch_id or ""):
        raise JobValidationError("invalid batch_id")
    return batch_id


def list_batches(limit: int = 50) -> List[Dict[str, Any]]:
    """Most recent batches first."""
    report_numbers = sync_report_numbers()
    bdir = batches_dir()
    if not bdir.is_dir():
        return []
    rows: List[Tuple[float, Path]] = []
    for child in bdir.iterdir():
        if not child.is_dir():
            continue
        try:
            rows.append((child.stat().st_mtime, child))
        except OSError:
            continue
    rows.sort(reverse=True)
    out: List[Dict[str, Any]] = []
    for _, p in rows[: max(1, limit)]:
        m = _read_json_safe(p / "batch.json") or {}
        bid = p.name
        children = m.get("children") or []
        # Lightweight aggregate over children.
        agg = _aggregate_batch_status(children)
        agg_metrics = _aggregate_batch_metrics(children)
        # Phase 22d — surface instruments/period/finished so the reports
        # table can show them on batch rows (was empty before).
        instruments = m.get("instruments")
        if not instruments:
            # Older batches had instruments only on children — derive.
            seen, dedup = set(), []
            for c in children:
                inst = c.get("instrument")
                if inst and inst not in seen:
                    seen.add(inst); dedup.append(inst)
            instruments = dedup
        # Phase 22g — derive period from children's job.json when
        # batch.json doesn't have it (older batches).
        period = m.get("period")
        if not period:
            period = _aggregate_batch_period(children)
        finished_at = _aggregate_batch_finished(children)
        out.append({
            "batch_id":         bid,
            "report_no":        report_numbers.get(_report_key("batch", bid)),
            "name":             m.get("name") or bid,
            "created_at_utc":   m.get("created_at_utc"),
            "finished_at_utc":  finished_at,
            "class_name":       (m.get("strategy") or {}).get("class_name"),
            "total":            m.get("total") or len(children),
            "counts":           agg,
            "instruments":      instruments,
            "period":           period,
            "trade_count":      agg_metrics.get("trade_count"),
            "winning_pct":      agg_metrics.get("winning_pct"),
            "net_profit":       agg_metrics.get("net_profit"),
            "gross_profit":     agg_metrics.get("gross_profit"),
            "gross_loss":       agg_metrics.get("gross_loss"),
            "profit_factor":    agg_metrics.get("profit_factor"),
            "max_drawdown":     agg_metrics.get("max_drawdown"),
        })
    return out


def _aggregate_batch_period(children: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Derive the covering period for a batch from its children's job.json files.

    Returns {from_utc, to_utc} spanning min(child.from) → max(child.to), or None
    when no period data is available. Used as a fallback for older batches that
    were created before batch.json stored the period at the manifest level.
    """
    from_dates: List[str] = []
    to_dates:   List[str] = []
    for c in children:
        jid = c.get("job_id")
        if not jid:
            continue
        loc = find_job_dir(jid)
        if not loc:
            continue
        _, jdir = loc
        jmeta = _read_json_safe(jdir / "job.json") or {}
        p = jmeta.get("period") or {}
        if p.get("from_utc"):
            from_dates.append(p["from_utc"])
        if p.get("to_utc"):
            to_dates.append(p["to_utc"])
    if not from_dates or not to_dates:
        return None
    return {"from_utc": min(from_dates), "to_utc": max(to_dates)}


def _aggregate_batch_finished(children: List[Dict[str, Any]]) -> Optional[str]:
    """Return the latest finished_at_utc across done/failed child jobs, or
    None if no child has finished. Used for the "Финиш / НВ" column on
    batch rows.
    """
    latest: Optional[str] = None
    for c in children:
        jid = c.get("job_id")
        if not jid:
            continue
        loc = find_job_dir(jid)
        if not loc:
            continue
        status, jdir = loc
        ts: Optional[str] = None
        if status == "done":
            res = _read_json_safe(jdir / "result.json") or {}
            ts = res.get("finished_at_utc")
        elif status == "failed":
            err = _read_json_safe(jdir / "error.json") or {}
            ts = err.get("finished_at_utc")
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def _aggregate_batch_status(children: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0, "cancelled": 0,
              "missing": 0}
    for c in children:
        jid = c.get("job_id")
        if not jid:
            counts["missing"] += 1
            continue
        loc = find_job_dir(jid)
        if not loc:
            counts["missing"] += 1
            continue
        counts[loc[0]] = counts.get(loc[0], 0) + 1
    return counts


def _aggregate_batch_metrics(children: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return {trade_count, winning_pct, net_profit, profit_factor, max_drawdown}
    aggregated across all done child jobs.

    profit_factor is recomputed from summed gross_profit/gross_loss; max_drawdown
    is the worst (most negative) value across children — a portfolio-level lower
    bound rather than a true blended drawdown, but sufficient for the
    confidence score and table display.
    """
    total_trades = 0
    total_winners = 0
    total_net = 0.0
    total_gross_profit = 0.0
    total_gross_loss = 0.0
    worst_dd = 0.0
    has_any = False
    has_net = False
    has_gross = False
    has_dd = False
    for c in children:
        jid = c.get("job_id")
        if not jid:
            continue
        loc = find_job_dir(jid)
        if not loc or loc[0] != "done":
            continue
        _, jdir = loc
        res = _read_json_safe(jdir / "result.json") or {}
        m = res.get("metrics") or {}
        tc = m.get("trade_count")
        wp = m.get("winning_pct")
        np_ = m.get("net_profit")
        gp = m.get("gross_profit")
        gl = m.get("gross_loss")
        dd = m.get("max_drawdown")
        if tc is None:
            continue
        has_any = True
        total_trades += int(tc)
        if wp is not None:
            total_winners += round(float(wp) * int(tc) / 100)
        if np_ is not None:
            try:
                total_net += float(np_); has_net = True
            except (TypeError, ValueError): pass
        if gp is not None and gl is not None:
            try:
                total_gross_profit += float(gp)
                total_gross_loss   += float(gl)
                has_gross = True
            except (TypeError, ValueError): pass
        if dd is not None:
            try:
                ddf = float(dd)
                if ddf < worst_dd: worst_dd = ddf
                has_dd = True
            except (TypeError, ValueError): pass
    if not has_any:
        return {}
    winning_pct = (total_winners / total_trades * 100) if total_trades > 0 else None
    pf = None
    if has_gross and total_gross_loss < 0:
        pf = total_gross_profit / abs(total_gross_loss)
    return {
        "trade_count":   total_trades,
        "winning_pct":   round(winning_pct, 2) if winning_pct is not None else None,
        "net_profit":    total_net if has_net else None,
        "gross_profit":  total_gross_profit if has_gross else None,
        "gross_loss":    total_gross_loss if has_gross else None,
        "profit_factor": round(pf, 4) if pf is not None else None,
        "max_drawdown":  worst_dd if has_dd else None,
    }


def _profit_factor_from_gross(gross_profit: Any, gross_loss: Any) -> Optional[float]:
    """Return finite PF from gross profit/loss, or None for no-loss/unknown cases.

    No-loss profitable runs have infinite PF; the frontend can display ∞ from
    gross_profit/gross_loss directly, while API JSON stays standards-compliant.
    """
    if gross_profit is None or gross_loss is None:
        return None
    try:
        gp = float(gross_profit)
        gl = float(gross_loss)
    except (TypeError, ValueError):
        return None
    if gl < 0:
        return round(gp / abs(gl), 6)
    return None


def read_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    batch_id = _safe_batch_id(batch_id)
    p = batches_dir() / batch_id
    if not p.is_dir():
        return None
    m = _read_json_safe(p / "batch.json")
    if not isinstance(m, dict):
        return None
    m["counts"] = _aggregate_batch_status(m.get("children") or [])
    return m


def read_batch_results(batch_id: str) -> Optional[Dict[str, Any]]:
    """Return one row per child with the metrics needed by the Result top
    table (instrument, status, metrics, period_check)."""
    m = read_batch(batch_id)
    if not m:
        return None
    rows: List[Dict[str, Any]] = []
    for c in m.get("children") or []:
        jid = c.get("job_id")
        instrument = c.get("instrument")
        row: Dict[str, Any] = {
            "batch_index": c.get("batch_index"),
            "instrument":  instrument,
            "job_id":      jid,
            "status":      "missing",
            "metrics":     None,
            "period_check": None,
            "error":       None,
        }
        if jid:
            loc = find_job_dir(jid)
            if loc:
                status, jdir = loc
                row["status"] = status
                # Phase 22g — read job.json to get created_at_utc + period
                # for every status so the batch-details table can show them.
                jmeta = _read_json_safe(jdir / "job.json") or {}
                row["created_at_utc"] = jmeta.get("created_at_utc")
                row["period"]         = jmeta.get("period")
                row["class_name"]     = (jmeta.get("strategy") or {}).get("class_name")
                if status == "done":
                    res = _read_json_safe(jdir / "result.json") or {}
                    row["metrics"] = res.get("metrics") or {}
                    row["period_check"] = _extract_period_check(
                        res.get("verification_warnings") or [])
                elif status == "failed":
                    err = _read_json_safe(jdir / "error.json") or {}
                    row["error"] = (err.get("message") or "").splitlines()[0:1]
        rows.append(row)
    return {
        "batch_id": batch_id,
        "name":     m.get("name"),
        "created_at_utc": m.get("created_at_utc"),
        "strategy": m.get("strategy"),
        "timeframe": m.get("timeframe"),
        "period":    m.get("period"),
        "risk_profile": m.get("risk_profile"),
        "execution": m.get("execution"),
        "total":     m.get("total"),
        "counts":    m.get("counts"),
        "rows":      rows,
    }


def _extract_period_check(warnings: List[Any]) -> Optional[Dict[str, Any]]:
    """Parse the bridge-emitted `period_invariant: before_from=N after_to=M`
    line from verification_warnings into a structured dict.

    The bridge emits several `period_invariant:` lines (requested range,
    first/last trade, and finally before/after counts). We must scan ALL
    matching lines and pick the one that actually contains the numeric
    `before_from=` / `after_to=` pair — returning early on the first
    match would mask the answer.
    """
    last_raw = None
    for w in warnings:
        if not isinstance(w, str):
            continue
        if "period_invariant" not in w:
            continue
        last_raw = w
        m = re.search(r"before_from=(-?\d+).*?after_to=(-?\d+)", w)
        if m:
            bf = int(m.group(1)); at = int(m.group(2))
            return {"before_from": bf, "after_to": at,
                    "ok": bf == 0 and at == 0}
    if last_raw is not None:
        return {"raw": last_raw, "ok": None}
    return None


# ---------------------------------------------------------------------------
# Cancellation.
#
# Pending jobs are owned by the UI/CLI process (bridge has not picked them up
# yet) — we move the dir from pending/<id>/ to cancelled/<id>/ ourselves and
# write a small cancellation marker.
#
# Running jobs are owned by the bridge — we drop a `cancel.flag` file inside
# running/<id>/ that the bridge's CancelFlagChecker polls. The bridge then
# moves the directory to cancelled/<id>/ at its earliest checkpoint.
#
# Already-terminal statuses (done/failed/cancelled) are no-ops.
# ---------------------------------------------------------------------------

def cancel_job(job_id: str) -> Dict[str, Any]:
    """Idempotent cancel. Returns {job_id, status, action}.

    action ∈ {"cancelled_immediately", "cancel_requested", "noop_terminal",
              "not_found"}.
    """
    job_id = _safe_job_id(job_id)
    located = find_job_dir(job_id)
    if not located:
        return {"job_id": job_id, "status": "missing",
                "action": "not_found"}
    status, jdir = located
    if status in ("done", "failed", "cancelled"):
        return {"job_id": job_id, "status": status,
                "action": "noop_terminal"}

    if status == "pending":
        target_parent = jobs_dir() / "cancelled"
        target_parent.mkdir(parents=True, exist_ok=True)
        dest = target_parent / job_id
        # Resolve a unique destination if a same-named dir already exists.
        if dest.exists():
            dest = target_parent / f"{job_id}__{utcnow_iso('ms').replace(':','').replace('-','')}"
        try:
            os.rename(str(jdir), str(dest))
        except OSError as e:
            raise JobValidationError(
                f"failed to move pending job to cancelled: {e}") from e
        # Drop a small marker so downstream readers see why it landed in
        # cancelled/ without having to infer it.
        marker = {
            "schema_version":   "0.1",
            "status":           "cancelled",
            "cancelled_at_utc": utcnow_iso("ms"),
            "reason":           "cancelled before bridge picked it up",
            "verification_warnings": ["cancelled by user"],
        }
        try:
            _atomic_write_text(dest / "result.json",
                               json.dumps(marker, ensure_ascii=False, indent=2))
        except OSError:
            pass
        return {"job_id": job_id, "status": "cancelled",
                "action": "cancelled_immediately"}

    # status == "running": drop cancel.flag for the bridge to notice.
    flag = jdir / "cancel.flag"
    try:
        _atomic_write_text(flag, utcnow_iso("ms"))
    except OSError as e:
        raise JobValidationError(
            f"failed to write cancel.flag: {e}") from e
    return {"job_id": job_id, "status": "running",
            "action": "cancel_requested"}


def cancel_batch(batch_id: str) -> Dict[str, Any]:
    """Cancel every child job of a batch. Returns {batch_id, results: [...]}."""
    batch_id = _safe_batch_id(batch_id)
    p = batches_dir() / batch_id
    if not p.is_dir():
        return {"batch_id": batch_id, "results": [], "found": False}
    m = _read_json_safe(p / "batch.json") or {}
    results: List[Dict[str, Any]] = []
    for c in m.get("children") or []:
        jid = c.get("job_id")
        if not jid:
            continue
        try:
            results.append(cancel_job(jid))
        except JobValidationError as e:
            results.append({"job_id": jid, "action": "error",
                            "error": str(e)})
    return {"batch_id": batch_id, "found": True, "results": results,
            "total": len(results)}


def delete_job(job_id: str) -> Dict[str, Any]:
    """Permanently remove a single job directory (all statuses)."""
    job_id = _safe_job_id(job_id)
    found = find_job_dir(job_id)
    if found is None:
        return {"job_id": job_id, "deleted": False, "reason": "not_found"}
    status, p = found
    if status == "running":
        return {"job_id": job_id, "deleted": False, "reason": "running"}
    shutil.rmtree(p, ignore_errors=True)
    return {"job_id": job_id, "deleted": True, "status": status}


def delete_batch(batch_id: str) -> Dict[str, Any]:
    """Permanently remove a batch directory and all its child job directories."""
    batch_id = _safe_batch_id(batch_id)
    p = batches_dir() / batch_id
    if not p.is_dir():
        return {"batch_id": batch_id, "deleted": False, "reason": "not_found"}
    m = _read_json_safe(p / "batch.json") or {}
    # Delete child jobs first (any status except running → skip).
    deleted_jobs: List[str] = []
    skipped_jobs: List[str] = []
    for c in m.get("children") or []:
        jid = c.get("job_id")
        if not jid:
            continue
        found = find_job_dir(jid)
        if found is None:
            continue
        status, jpath = found
        if status == "running":
            skipped_jobs.append(jid)
            continue
        shutil.rmtree(jpath, ignore_errors=True)
        deleted_jobs.append(jid)
    if skipped_jobs:
        # One or more child jobs are running: don't remove the batch dir.
        return {"batch_id": batch_id, "deleted": False,
                "reason": "has_running_jobs", "skipped": skipped_jobs}
    shutil.rmtree(p, ignore_errors=True)
    return {"batch_id": batch_id, "deleted": True,
            "deleted_jobs": deleted_jobs}
