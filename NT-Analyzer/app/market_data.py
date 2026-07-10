"""Runtime market-data subscriptions and persistent price alerts.

The browser registers the instrument/timeframe pairs it currently displays.
The NinjaTrader bridge consumes ``market_data_requests.json`` and publishes an
atomic ``market_bars.json`` snapshot.  Alerts live on the backend so they keep
working when the desktop page is closed.
"""
from __future__ import annotations

import base64
import copy
import json
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_LOCK = threading.RLock()
_REQUEST_TTL_SEC = 180
_VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}
_VALID_DRAWING_TYPES = {"line", "point", "arrow", "arrow_up", "arrow_down",
                        "flag", "target", "label"}
_VALID_REPORT_MODES = {"touch", "expire", "both"}
_COMMAND_TTL_SEC = 600
_SNAPSHOT_KEEP = 400
_SNAPSHOT_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_SNAPSHOT_INDEX_CACHE: Dict[str, Any] = {"signature": "", "index": {}}
_ALERTS_INDEX_CACHE: Dict[str, Any] = {"signature": "", "index": {}}
_SERIES_PAYLOAD_CACHE: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
_SERIES_PAYLOAD_CACHE_MAX = 256


class MarketDataError(ValueError):
    pass


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _runtime_dir() -> Path:
    path = _root() / "data" / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _requests_path() -> Path:
    return _runtime_dir() / "market_data_requests.json"


def _snapshot_path() -> Path:
    return _runtime_dir() / "market_bars.json"


def _alerts_path() -> Path:
    return _runtime_dir() / "price_alerts.json"


def _commands_path() -> Path:
    return _runtime_dir() / "chart_commands.json"


def _snapshot_dir() -> Path:
    path = _runtime_dir() / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_index_path() -> Path:
    return _snapshot_dir() / "index.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _utcnow()).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _read(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return dict(doc) if isinstance(doc, dict) else {}


def _write(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use a unique temp name per writer so two backends (or the bridge reading
    # the file) never collide on the same ``.tmp``. On Windows os.replace raises
    # PermissionError (WinError 5) when the destination is momentarily open by
    # another process, so retry a few times with a tiny backoff before giving up.
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        last_err: Optional[OSError] = None
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:  # transient Windows sharing violation
                last_err = exc
                time.sleep(0.02 * (attempt + 1))
        if last_err is not None:
            raise last_err
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _file_signature(path: Path) -> str:
    try:
        st = path.stat()
        return f"{path}:{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return f"{path}:missing"


def snapshot_source_signature() -> str:
    """Stable signature for the current bridge bars snapshot.

    Used by caches so many chart polls can share the same parsed snapshot until
    the bridge atomically replaces ``market_bars.json``.
    """
    return _file_signature(_snapshot_path())


def alerts_source_signature() -> str:
    return _file_signature(_alerts_path())


def _clone_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return copy.deepcopy(payload) if isinstance(payload, dict) else None


def _bar_y(row: Any) -> float:
    if not isinstance(row, dict):
        return 0.0
    values: List[float] = []
    for key in ("h", "high", "c", "close", "l", "low"):
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    if not values:
        return 0.0
    return sum(values) / len(values)


def downsample_bars(bars: Iterable[Any], max_points: int = 0) -> List[Any]:
    """LTTB downsample for visual chart payloads.

    The original bars are returned unchanged unless ``max_points`` is at least
    3 and smaller than the source length. First and last bars are always kept.
    """
    rows = list(bars or [])
    try:
        threshold = int(max_points or 0)
    except (TypeError, ValueError):
        threshold = 0
    if threshold < 3 or len(rows) <= threshold:
        return rows
    n = len(rows)
    every = (n - 2) / float(threshold - 2)
    sampled: List[Any] = [rows[0]]
    a = 0
    for i in range(threshold - 2):
        avg_start = int(math.floor((i + 1) * every)) + 1
        avg_end = int(math.floor((i + 2) * every)) + 1
        avg_end = min(avg_end, n)
        avg_range = rows[avg_start:avg_end] or [rows[min(n - 1, avg_start)]]
        avg_x = sum(range(avg_start, avg_start + len(avg_range))) / max(1, len(avg_range))
        avg_y = sum(_bar_y(row) for row in avg_range) / max(1, len(avg_range))

        range_start = int(math.floor(i * every)) + 1
        range_end = int(math.floor((i + 1) * every)) + 1
        range_end = min(range_end, n - 1)
        ax = float(a)
        ay = _bar_y(rows[a])
        max_area = -1.0
        next_a = range_start
        for idx in range(range_start, max(range_start + 1, range_end)):
            y = _bar_y(rows[idx])
            area = abs((ax - avg_x) * (y - ay) - (ax - idx) * (avg_y - ay)) * 0.5
            if area > max_area:
                max_area = area
                next_a = idx
        sampled.append(rows[next_a])
        a = next_a
    sampled.append(rows[-1])
    return sampled


def downsample_series_payload(payload: Optional[Dict[str, Any]],
                              max_points: int = 0) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    bars = payload.get("bars") if isinstance(payload.get("bars"), list) else []
    sampled = downsample_bars(bars, max_points)
    if len(sampled) == len(bars):
        return _clone_payload(payload)
    out = _clone_payload(payload) or {}
    out["bars"] = sampled
    out["raw_total"] = int(payload.get("total") or len(bars))
    out["returned"] = len(sampled)
    out["downsampled"] = True
    out["downsample_method"] = "lttb"
    return out


def _trim_series_payload_cache() -> None:
    while len(_SERIES_PAYLOAD_CACHE) > _SERIES_PAYLOAD_CACHE_MAX:
        try:
            oldest = next(iter(_SERIES_PAYLOAD_CACHE))
        except StopIteration:
            return
        _SERIES_PAYLOAD_CACHE.pop(oldest, None)


def cached_series_from_index(index: Optional[Dict[str, Dict[str, Any]]], instrument: Any,
                             timeframe: Any, limit: int = 1500, *,
                             workspace_id: str = "", range_key: str = "",
                             max_points: int = 0) -> Optional[Dict[str, Any]]:
    signature = snapshot_source_signature()
    key = (
        str(workspace_id or ""),
        series_key(instrument, timeframe),
        int(limit or 1500),
        str(range_key or ""),
        int(max_points or 0),
        signature,
    )
    with _LOCK:
        cached = _SERIES_PAYLOAD_CACHE.get(key)
        if cached is not None:
            return _clone_payload(cached)
    payload = series_from_index(index, instrument, timeframe, limit)
    payload = downsample_series_payload(payload, max_points)
    if payload is None:
        return None
    with _LOCK:
        _SERIES_PAYLOAD_CACHE[key] = _clone_payload(payload) or {}
        _trim_series_payload_cache()
    return _clone_payload(payload)


def normalize_timeframe(value: Any) -> str:
    tf = str(value or "5m").strip().lower()
    if tf not in _VALID_TIMEFRAMES:
        raise MarketDataError(f"Неподдерживаемый таймфрейм: {value}")
    return "1D" if tf == "1d" else tf


def series_key(instrument: Any, timeframe: Any) -> str:
    symbol = " ".join(str(instrument or "").strip().upper().split())
    if not symbol:
        raise MarketDataError("Инструмент не указан.")
    return f"{symbol}|{normalize_timeframe(timeframe).lower()}"


def register_request(instrument: Any, timeframe: Any, limit: int = 1500,
                     range_days: Optional[int] = None, from_date: str = "",
                     to_date: str = "") -> Dict[str, Any]:
    return register_requests([{"instrument": instrument, "timeframe": timeframe, "limit": limit,
                               "range_days": range_days, "from": from_date, "to": to_date}])[0]


def register_requests(requests: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = _utcnow()
    normalized: List[Dict[str, Any]] = []
    for spec in requests:
        symbol = " ".join(str(spec.get("instrument") or "").strip().upper().split())
        tf = normalize_timeframe(spec.get("timeframe"))
        key = series_key(symbol, tf)
        try:
            limit = max(100, min(50000, int(spec.get("limit") or 1500)))
            range_days = max(0, min(3660, int(spec.get("range_days") or 0)))
        except (TypeError, ValueError):
            raise MarketDataError("Некорректный диапазон или лимит баров.") from None
        normalized.append({"key": key, "instrument": symbol, "timeframe": tf,
                           "limit": limit, "range_days": range_days,
                           "from": str(spec.get("from") or "")[:10],
                           "to": str(spec.get("to") or "")[:10],
                           "requested_at_utc": _iso(now)})
    with _LOCK:
        doc = _read(_requests_path())
        rows = doc.get("requests") if isinstance(doc.get("requests"), list) else []
        kept: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            touched = _parse_iso(row.get("requested_at_utc"))
            if touched and (now - touched).total_seconds() > _REQUEST_TTL_SEC:
                continue
            kept.append(row)
        by_key = {str(row.get("key") or ""): row for row in kept}
        for row in normalized:
            current = by_key.get(row["key"])
            by_key[row["key"]] = _merge_request(current, row)
        kept = list(by_key.values())
        _write(_requests_path(), {"version": 1, "generated_at_utc": _iso(now),
                                  "ttl_sec": _REQUEST_TTL_SEC, "requests": kept[-64:]})
    return normalized


def _merge_request(current: Optional[Dict[str, Any]], incoming: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(current, dict):
        return dict(incoming)
    merged = dict(current)
    merged.update({
        "key": incoming.get("key") or current.get("key"),
        "instrument": incoming.get("instrument") or current.get("instrument"),
        "timeframe": incoming.get("timeframe") or current.get("timeframe"),
        "requested_at_utc": incoming.get("requested_at_utc") or current.get("requested_at_utc"),
    })
    try:
        merged["limit"] = max(int(current.get("limit") or 0), int(incoming.get("limit") or 0), 100)
    except (TypeError, ValueError):
        merged["limit"] = incoming.get("limit") or current.get("limit") or 1500
    try:
        merged["range_days"] = max(int(current.get("range_days") or 0), int(incoming.get("range_days") or 0), 0)
    except (TypeError, ValueError):
        merged["range_days"] = incoming.get("range_days") or current.get("range_days") or 0
    current_from, incoming_from = str(current.get("from") or "")[:10], str(incoming.get("from") or "")[:10]
    current_to, incoming_to = str(current.get("to") or "")[:10], str(incoming.get("to") or "")[:10]
    merged["from"] = min([v for v in (current_from, incoming_from) if v], default="")
    merged["to"] = max([v for v in (current_to, incoming_to) if v], default="")
    return merged


def read_runtime_series(instrument: Any, timeframe: Any, limit: int = 1500) -> Optional[Dict[str, Any]]:
    key = series_key(instrument, timeframe)
    doc = _read(_snapshot_path())
    rows = doc.get("series") if isinstance(doc.get("series"), list) else []
    row = next((item for item in rows if isinstance(item, dict)
                and str(item.get("key") or "") == key), None)
    return _series_from_row(row, instrument, timeframe, limit)


def read_snapshot_index() -> Dict[str, Dict[str, Any]]:
    """Read the bridge snapshot ONCE and index it by series key.

    The desktop grid polls up to 64 charts per batch; building this index a
    single time (instead of re-reading and re-parsing ``market_bars.json`` for
    every instrument) keeps a large grid fast and off the disk.
    """
    signature = snapshot_source_signature()
    with _LOCK:
        if _SNAPSHOT_INDEX_CACHE.get("signature") == signature:
            return dict(_SNAPSHOT_INDEX_CACHE.get("index") or {})
    doc = _read(_snapshot_path())
    rows = doc.get("series") if isinstance(doc.get("series"), list) else []
    index = {str(item.get("key") or ""): item for item in rows
             if isinstance(item, dict) and item.get("key")}
    with _LOCK:
        _SNAPSHOT_INDEX_CACHE["signature"] = signature
        _SNAPSHOT_INDEX_CACHE["index"] = index
    return dict(index)


def series_from_index(index: Optional[Dict[str, Dict[str, Any]]], instrument: Any,
                      timeframe: Any, limit: int = 1500) -> Optional[Dict[str, Any]]:
    """Build a runtime series payload from a pre-read snapshot index."""
    key = series_key(instrument, timeframe)
    row = (index or {}).get(key)
    return _series_from_row(row, instrument, timeframe, limit)


def _bar_ohlc(row: Any) -> Optional[Tuple[float, float, float, float]]:
    if not isinstance(row, dict):
        return None
    try:
        o = float(row.get("o", row.get("open")))
        h = float(row.get("h", row.get("high")))
        l = float(row.get("l", row.get("low")))
        c = float(row.get("c", row.get("close")))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and v > 0 for v in (o, h, l, c)):
        return None
    return o, h, l, c


def quarantine_impossible_bars(bars: Iterable[Any]) -> Tuple[List[Any], Dict[str, Any]]:
    clean: List[Any] = []
    rejected = 0
    reasons: Dict[str, int] = {}
    previous_close: Optional[float] = None
    for row in bars or []:
        ohlc = _bar_ohlc(row)
        reason = ""
        if ohlc is None:
            reason = "non_finite_or_non_positive"
        else:
            o, h, l, c = ohlc
            if h < l:
                reason = "high_below_low"
            elif max(o, c) > h or min(o, c) < l:
                reason = "ohlc_outside_range"
            elif previous_close and (h - l) > max(previous_close * 50.0, 10_000_000.0):
                reason = "range_explosion"
        if reason:
            rejected += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        clean.append(row)
        previous_close = ohlc[3] if ohlc else previous_close
    diagnostics = {"rejected_bars": rejected, "reasons": reasons} if rejected else {}
    return clean, diagnostics


def _series_from_row(row: Optional[Dict[str, Any]], instrument: Any,
                     timeframe: Any, limit: int = 1500) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    key = series_key(instrument, timeframe)
    bars = row.get("bars") if isinstance(row.get("bars"), list) else []
    clean_bars, diagnostics = quarantine_impossible_bars(bars)
    limit = max(1, min(50000, int(limit or 1500)))
    updated = _parse_iso(row.get("updated_at_utc"))
    age = max(0.0, (_utcnow() - updated).total_seconds()) if updated else None
    status = str(row.get("status") or ("live" if bars else "waiting"))
    payload = {
        "instrument": row.get("instrument") or instrument,
        "bars": clean_bars[-limit:], "total": len(clean_bars), "raw_total": len(bars),
        "live": status == "live" and bool(clean_bars),
        "source": {"kind": "ninjatrader_runtime", "key": key,
                   "updated_at_utc": row.get("updated_at_utc"), "age_sec": age},
        "status": status, "error": str(row.get("error") or ""),
        "note": str(row.get("note") or ""),
        "requested_timeframe": normalize_timeframe(timeframe),
        "matched_timeframe": row.get("timeframe") or normalize_timeframe(timeframe),
    }
    if diagnostics:
        payload["diagnostics"] = diagnostics
        payload["note"] = (str(payload.get("note") or "") + " · " if payload.get("note") else "") + "Часть битых баров изолирована backend."
    return payload


def _load_alert_doc() -> Dict[str, Any]:
    doc = _read(_alerts_path())
    if not isinstance(doc.get("alerts"), list):
        doc["alerts"] = []
    return doc


def list_alerts(*, instrument: Any = "", include_inactive: bool = True) -> Dict[str, Any]:
    symbol = " ".join(str(instrument or "").strip().upper().split())
    with _LOCK:
        rows = [dict(row) for row in _load_alert_doc()["alerts"] if isinstance(row, dict)]
    if symbol:
        rows = [row for row in rows if str(row.get("instrument") or "").upper() == symbol]
    if not include_inactive:
        rows = [row for row in rows if row.get("status") == "active"]
    rows.sort(key=lambda row: str(row.get("created_at_utc") or ""), reverse=True)
    return {"alerts": rows, "total": len(rows)}


def read_alerts_index() -> Dict[str, List[Dict[str, Any]]]:
    """Read alerts ONCE and group them by instrument symbol (all statuses).

    Used by the batch bars endpoint so a 64-chart grid does not re-read
    ``price_alerts.json`` once per instrument on every poll tick.
    """
    signature = alerts_source_signature()
    with _LOCK:
        if _ALERTS_INDEX_CACHE.get("signature") == signature:
            return {key: list(value) for key, value in (_ALERTS_INDEX_CACHE.get("index") or {}).items()}
    with _LOCK:
        rows = [dict(row) for row in _load_alert_doc()["alerts"] if isinstance(row, dict)]
    rows.sort(key=lambda row: str(row.get("created_at_utc") or ""), reverse=True)
    index: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        index.setdefault(str(row.get("instrument") or "").upper(), []).append(row)
    with _LOCK:
        _ALERTS_INDEX_CACHE["signature"] = signature
        _ALERTS_INDEX_CACHE["index"] = index
    return index


def create_alert(payload: Dict[str, Any]) -> Dict[str, Any]:
    symbol = " ".join(str(payload.get("instrument") or "").strip().upper().split())
    if not symbol:
        raise MarketDataError("Инструмент не указан.")
    tf = normalize_timeframe(payload.get("timeframe") or "5m")
    try:
        price = float(payload.get("price"))
    except (TypeError, ValueError):
        raise MarketDataError("Укажите корректную цену алерта.") from None
    if not math.isfinite(price) or price <= 0:
        raise MarketDataError("Цена алерта должна быть больше нуля.")
    drawing_type = str(payload.get("type") or "line").strip().lower()
    if drawing_type not in _VALID_DRAWING_TYPES:
        raise MarketDataError("Тип отметки должен быть line, point или arrow.")
    try:
        duration = int(payload.get("duration_minutes") or 0)
    except (TypeError, ValueError):
        raise MarketDataError("Некорректный срок действия алерта.") from None
    duration = max(0, min(525600, duration))
    now = _utcnow()
    current_price = payload.get("current_price")
    try:
        current_price = float(current_price) if current_price is not None else None
        if current_price is not None and not math.isfinite(current_price):
            current_price = None
    except (TypeError, ValueError):
        current_price = None
    runtime_row = read_runtime_series(symbol, tf, 2)
    current_bar = _last_valid_bar((runtime_row or {}).get("bars") or [])
    report_mode = str(payload.get("report_mode") or "touch").strip().lower()
    if report_mode not in _VALID_REPORT_MODES:
        report_mode = "touch"
    trigger = str(payload.get("trigger") or "price").strip().lower()
    if trigger not in {"price", "time"}:
        trigger = "price"
    try:
        delay_seconds = int(payload.get("delay_seconds") or 0)
    except (TypeError, ValueError):
        delay_seconds = 0
    delay_seconds = max(0, min(31 * 24 * 3600, delay_seconds))
    due_at = None
    if trigger == "time":
        secs = delay_seconds or (duration * 60) or 60
        due_at = now + timedelta(seconds=secs)
        # A time task should live at least until it is due (plus a small grace).
        expires_at = due_at + timedelta(minutes=10)
    else:
        expires_at = now + timedelta(minutes=duration) if duration else None
    alert = {
        "id": "pa_" + uuid.uuid4().hex,
        "drawing_id": str(payload.get("drawing_id") or ""),
        "window_id": str(payload.get("window_id") or ""),
        "instrument": symbol, "timeframe": tf, "type": drawing_type,
        "price": price, "label": str(payload.get("label") or "Уровень цены").strip()[:160],
        "color": str(payload.get("color") or "#fcc55a")[:32],
        "trigger": trigger,
        "due_at_utc": _iso(due_at) if due_at else None,
        "action": str(payload.get("action") or ("telegram" if payload.get("telegram", True) else "none"))[:24],
        "telegram": bool(payload.get("telegram", True)),
        "agent_id": str(payload.get("agent_id") or "")[:160],
        "agent_message": str(payload.get("agent_message") or "")[:2000],
        "snapshot": bool(payload.get("snapshot", False)),
        "report_mode": report_mode,
        "conversation_id": str(payload.get("conversation_id") or "")[:120],
        "created_at_utc": _iso(now),
        "expires_at_utc": _iso(expires_at) if expires_at else None,
        "status": "active", "last_price": current_price,
        "last_high": current_bar.get("high") if current_bar else current_price,
        "last_low": current_bar.get("low") if current_bar else current_price,
        "last_bar_time": current_bar.get("time") if current_bar else None,
        "triggered_at_utc": None, "trigger_price": None,
    }
    with _LOCK:
        doc = _load_alert_doc()
        doc["alerts"].append(alert)
        doc["updated_at_utc"] = _iso(now)
        _write(_alerts_path(), doc)
    return {"alert": dict(alert)}


def delete_alert(alert_id: Any) -> Dict[str, Any]:
    target = str(alert_id or "").strip()
    if not target:
        raise MarketDataError("ID алерта не указан.")
    with _LOCK:
        doc = _load_alert_doc()
        before = len(doc["alerts"])
        doc["alerts"] = [row for row in doc["alerts"]
                         if not isinstance(row, dict) or str(row.get("id") or "") != target]
        deleted = len(doc["alerts"]) != before
        if deleted:
            doc["updated_at_utc"] = _iso()
            _write(_alerts_path(), doc)
    return {"deleted": deleted, "id": target}


def _safe_series_key(alert: Dict[str, Any]) -> str:
    try:
        return series_key(alert.get("instrument"), alert.get("timeframe"))
    except (MarketDataError, TypeError, ValueError):
        return ""


def _last_valid_bar(bars: Iterable[Any]) -> Optional[Dict[str, Any]]:
    for row in reversed(list(bars)):
        if not isinstance(row, dict):
            continue
        try:
            close = float(row.get("c", row.get("close")))
            high = float(row.get("h", row.get("high", close)))
            low = float(row.get("l", row.get("low", close)))
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(v) for v in (close, high, low)):
            return {"close": close, "high": high, "low": low,
                    "time": row.get("t") or row.get("time_utc") or row.get("time")}
    return None


def evaluate_alerts() -> List[Dict[str, Any]]:
    """Evaluate one-shot crossing alerts against the newest runtime bar."""
    now = _utcnow()
    snap = _read(_snapshot_path())
    series = {str(row.get("key") or ""): row for row in (snap.get("series") or [])
              if isinstance(row, dict)}
    triggered: List[Dict[str, Any]] = []
    changed = False
    with _LOCK:
        doc = _load_alert_doc()
        for alert in doc["alerts"]:
            if not isinstance(alert, dict) or alert.get("status") != "active":
                continue
            # Time-based tasks (e.g. "снимок через минуту") fire purely on the
            # clock — no price crossing needed.
            if str(alert.get("trigger") or "price") == "time":
                due = _parse_iso(alert.get("due_at_utc"))
                if due and now >= due:
                    alert["status"] = "triggered"
                    alert["triggered_at_utc"] = _iso(now)
                    bar_now = _last_valid_bar(
                        (series.get(_safe_series_key(alert)) or {}).get("bars") or [])
                    alert["trigger_price"] = bar_now["close"] if bar_now else alert.get("last_price")
                    triggered.append(dict(alert))
                    changed = True
                continue
            expiry = _parse_iso(alert.get("expires_at_utc"))
            if expiry and now >= expiry:
                alert["status"] = "expired"
                alert["expired_at_utc"] = _iso(now)
                changed = True
                continue
            try:
                key = series_key(alert.get("instrument"), alert.get("timeframe"))
                level = float(alert.get("price"))
            except (MarketDataError, TypeError, ValueError):
                continue
            row = series.get(key)
            bar = _last_valid_bar((row or {}).get("bars") or [])
            if not bar:
                continue
            previous = alert.get("last_price")
            try:
                previous = float(previous) if previous is not None else None
            except (TypeError, ValueError):
                previous = None
            current = bar["close"]
            old_time = str(alert.get("last_bar_time") or "")
            new_time = str(bar.get("time") or "")
            try:
                old_high = float(alert.get("last_high"))
                old_low = float(alert.get("last_low"))
            except (TypeError, ValueError):
                old_high = old_low = previous if previous is not None else current
            crossed_close = previous is not None and (previous - level) * (current - level) <= 0
            if old_time and new_time == old_time:
                touched_range = (old_high < level <= bar["high"]) or (old_low > level >= bar["low"])
            else:
                touched_range = min(bar["low"], bar["high"]) <= level <= max(bar["low"], bar["high"])
            hit = previous is not None and (crossed_close or touched_range)
            alert["last_price"] = current
            alert["last_high"] = bar["high"]
            alert["last_low"] = bar["low"]
            alert["last_evaluated_at_utc"] = _iso(now)
            alert["last_bar_time"] = bar.get("time")
            changed = True
            if hit:
                alert["status"] = "triggered"
                alert["triggered_at_utc"] = _iso(now)
                alert["trigger_price"] = current
                triggered.append(dict(alert))
        if changed:
            doc["updated_at_utc"] = _iso(now)
            _write(_alerts_path(), doc)
    return triggered


def pending_telegram_alerts() -> List[Dict[str, Any]]:
    with _LOCK:
        return [dict(row) for row in _load_alert_doc()["alerts"]
                if isinstance(row, dict) and row.get("status") == "triggered"
                and row.get("telegram") and not row.get("telegram_notified_at_utc")]


def mark_telegram_notified(alert_id: Any) -> bool:
    target = str(alert_id or "")
    with _LOCK:
        doc = _load_alert_doc()
        for row in doc["alerts"]:
            if isinstance(row, dict) and str(row.get("id") or "") == target:
                row["telegram_notified_at_utc"] = _iso()
                doc["updated_at_utc"] = _iso()
                _write(_alerts_path(), doc)
                return True
    return False


def pending_agent_alerts() -> List[Dict[str, Any]]:
    with _LOCK:
        return [dict(row) for row in _load_alert_doc()["alerts"]
                if isinstance(row, dict) and row.get("status") == "triggered"
                and row.get("action") == "agent" and not row.get("agent_dispatched_at_utc")]


def mark_agent_dispatched(alert_id: Any) -> bool:
    target = str(alert_id or "")
    with _LOCK:
        doc = _load_alert_doc()
        for row in doc["alerts"]:
            if isinstance(row, dict) and str(row.get("id") or "") == target:
                row["agent_dispatched_at_utc"] = _iso()
                doc["updated_at_utc"] = _iso()
                _write(_alerts_path(), doc)
                return True
    return False


def get_alert(alert_id: Any) -> Optional[Dict[str, Any]]:
    target = str(alert_id or "").strip()
    if not target:
        return None
    with _LOCK:
        for row in _load_alert_doc()["alerts"]:
            if isinstance(row, dict) and str(row.get("id") or "") == target:
                return dict(row)
    return None


# ---------------------------------------------------------------------------
# Chart command queue — the "Иван" chart operator issues commands from the chat
# (draw a level, watch a price, snapshot on touch).  The desktop page polls this
# queue, applies each command on the live chart and acknowledges the result.
# ---------------------------------------------------------------------------
_VALID_COMMAND_TYPES = {"draw", "watch", "snapshot", "focus", "clear", "open"}


def _load_commands_doc() -> Dict[str, Any]:
    doc = _read(_commands_path())
    if not isinstance(doc.get("commands"), list):
        doc["commands"] = []
    return doc


def _command_alive(row: Dict[str, Any], now: datetime) -> bool:
    """A command stays around until its TTL, or (when scheduled) until due+grace."""
    created = _parse_iso(row.get("created_at_utc"))
    if not created:
        return False
    due = _parse_iso(row.get("due_at_utc"))
    if row.get("status") == "pending" and due:
        return now <= due + timedelta(seconds=_COMMAND_TTL_SEC)
    return (now - created).total_seconds() <= _COMMAND_TTL_SEC


def enqueue_chart_command(command: Dict[str, Any]) -> Dict[str, Any]:
    ctype = str((command or {}).get("type") or "").strip().lower()
    if ctype not in _VALID_COMMAND_TYPES:
        raise MarketDataError(f"Неизвестная команда графика: {ctype or '—'}")
    symbol = " ".join(str((command or {}).get("instrument") or "").strip().upper().split())
    tf = ""
    if command.get("timeframe"):
        try:
            tf = normalize_timeframe(command.get("timeframe"))
        except MarketDataError:
            tf = ""
    now = _utcnow()
    try:
        delay_seconds = int((command or {}).get("delay_seconds") or 0)
    except (TypeError, ValueError):
        delay_seconds = 0
    delay_seconds = max(0, min(31 * 24 * 3600, delay_seconds))
    due_at = _parse_iso((command or {}).get("due_at_utc"))
    if due_at is None and delay_seconds:
        due_at = now + timedelta(seconds=delay_seconds)
    row = {
        "id": "cc_" + uuid.uuid4().hex,
        "type": ctype,
        "instrument": symbol,
        "timeframe": tf,
        "payload": command.get("payload") if isinstance(command.get("payload"), dict) else {},
        "conversation_id": str(command.get("conversation_id") or "")[:120],
        "agent_id": str(command.get("agent_id") or "")[:120],
        "note": str(command.get("note") or "")[:400],
        "created_at_utc": _iso(now),
        "due_at_utc": _iso(due_at) if due_at else None,
        "status": "pending",
    }
    with _LOCK:
        doc = _load_commands_doc()
        rows = [r for r in doc["commands"] if isinstance(r, dict) and _command_alive(r, now)]
        rows.append(row)
        doc["commands"] = rows[-160:]
        doc["updated_at_utc"] = _iso(now)
        _write(_commands_path(), doc)
    return {"command": dict(row)}


def list_chart_commands(*, status: str = "pending") -> Dict[str, Any]:
    now = _utcnow()
    want = str(status or "pending").strip().lower()
    with _LOCK:
        doc = _load_commands_doc()
        rows: List[Dict[str, Any]] = []
        changed = False
        for row in doc["commands"]:
            if not isinstance(row, dict):
                continue
            if row.get("status") == "pending" and not _command_alive(row, now):
                row["status"] = "expired"
                changed = True
            if want == "all":
                rows.append(dict(row))
                continue
            if row.get("status") != want:
                continue
            # Scheduled commands ("через минуту") stay hidden from the pending
            # feed until they are actually due, so the desktop runs them on time.
            if want == "pending":
                due = _parse_iso(row.get("due_at_utc"))
                if due and now < due:
                    continue
            rows.append(dict(row))
        if changed:
            doc["updated_at_utc"] = _iso(now)
            _write(_commands_path(), doc)
    rows.sort(key=lambda r: str(r.get("created_at_utc") or ""))
    return {"commands": rows, "total": len(rows)}


def ack_chart_command(command_id: Any, *, status: str = "done",
                      result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    target = str(command_id or "").strip()
    final = str(status or "done").strip().lower()
    if final not in {"done", "failed", "skipped"}:
        final = "done"
    with _LOCK:
        doc = _load_commands_doc()
        updated = None
        for row in doc["commands"]:
            if isinstance(row, dict) and str(row.get("id") or "") == target:
                row["status"] = final
                row["acked_at_utc"] = _iso()
                if isinstance(result, dict):
                    row["result"] = {k: result[k] for k in list(result)[:20]}
                updated = dict(row)
                break
        if updated is not None:
            doc["updated_at_utc"] = _iso()
            _write(_commands_path(), doc)
    return {"acked": updated is not None, "id": target, "command": updated}


# ---------------------------------------------------------------------------
# Chart snapshots — the desktop captures the chart canvas as a data URL; we
# persist it as an image file and return a stable URL for the chat / Telegram.
# ---------------------------------------------------------------------------
def save_snapshot(data_url: Any, *, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = str(data_url or "").strip()
    match = re.match(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", raw, re.DOTALL)
    if not match:
        raise MarketDataError("Некорректный снимок графика.")
    mime = match.group(1)
    ext = _SNAPSHOT_MIME.get(mime)
    if not ext:
        raise MarketDataError("Неподдерживаемый формат снимка.")
    try:
        blob = base64.b64decode(match.group(2), validate=True)
    except (ValueError, TypeError):
        raise MarketDataError("Снимок повреждён.") from None
    if not blob or len(blob) > 6 * 1024 * 1024:
        raise MarketDataError("Снимок пуст или слишком большой.")
    snap_id = "cs_" + uuid.uuid4().hex
    path = _snapshot_dir() / f"{snap_id}{ext}"
    path.write_bytes(blob)
    clean_meta = {k: (meta or {})[k] for k in list(meta or {})[:20]}
    entry = {
        "id": snap_id, "file": path.name, "url": f"/api/ops/runtime/snapshots/{path.name}",
        "bytes": len(blob), "mime": mime,
        "created_at_utc": _iso(),
        "instrument": str(clean_meta.get("instrument") or ""),
        "timeframe": str(clean_meta.get("timeframe") or ""),
        "outcome": str(clean_meta.get("outcome") or ""),
        "conversation_id": str(clean_meta.get("conversation_id") or ""),
        "caption": str(clean_meta.get("caption") or "")[:300],
        "favorite": False, "pattern": "",
    }
    with _LOCK:
        doc = _read(_snapshot_index_path())
        rows = doc.get("snapshots") if isinstance(doc.get("snapshots"), list) else []
        rows.append(entry)
        doc["snapshots"] = rows
        doc["updated_at_utc"] = _iso()
        _write(_snapshot_index_path(), doc)
    _prune_snapshots()
    return {**entry, "meta": clean_meta}


def read_snapshot(name: Any) -> Optional[Tuple[bytes, str]]:
    safe = str(name or "").strip()
    if not re.match(r"^cs_[0-9a-f]{32}\.(jpg|png|webp)$", safe):
        return None
    path = _snapshot_dir() / safe
    if not path.is_file():
        return None
    mime = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix, "application/octet-stream")
    try:
        return path.read_bytes(), mime
    except OSError:
        return None


def snapshot_path(name: Any) -> Optional[Path]:
    """Absolute path to a stored snapshot file, or None if it does not exist."""
    safe = str(name or "").strip()
    if not re.match(r"^cs_[0-9a-f]{32}\.(jpg|png|webp)$", safe):
        return None
    path = _snapshot_dir() / safe
    return path if path.is_file() else None


def _prune_snapshots() -> None:
    """Keep the newest snapshots and every favorite; drop the rest (file+index)."""
    with _LOCK:
        doc = _read(_snapshot_index_path())
        rows = [r for r in (doc.get("snapshots") or []) if isinstance(r, dict)]
        rows.sort(key=lambda r: str(r.get("created_at_utc") or ""))
        favorites = [r for r in rows if r.get("favorite")]
        others = [r for r in rows if not r.get("favorite")]
        drop = others[:-_SNAPSHOT_KEEP] if len(others) > _SNAPSHOT_KEEP else []
        for row in drop:
            try:
                (_snapshot_dir() / str(row.get("file") or "")).unlink()
            except OSError:
                pass
        keep_ids = {r.get("id") for r in (favorites + others[-_SNAPSHOT_KEEP:])}
        doc["snapshots"] = [r for r in rows if r.get("id") in keep_ids]
        _write(_snapshot_index_path(), doc)
    # Also sweep any orphan files not referenced by the index.
    try:
        referenced = {str(r.get("file") or "") for r in
                      (_read(_snapshot_index_path()).get("snapshots") or []) if isinstance(r, dict)}
        for f in _snapshot_dir().glob("cs_*"):
            if f.name not in referenced:
                f.unlink()
    except OSError:
        pass


def _snapshot_file_for(snap_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        for row in (_read(_snapshot_index_path()).get("snapshots") or []):
            if isinstance(row, dict) and str(row.get("id") or "") == str(snap_id):
                return dict(row)
    return None


def list_snapshots(*, pattern: Any = None, favorites_only: bool = False,
                   limit: int = 300) -> Dict[str, Any]:
    want_pattern = None if pattern is None else str(pattern).strip()
    with _LOCK:
        rows = [dict(r) for r in (_read(_snapshot_index_path()).get("snapshots") or [])
                if isinstance(r, dict)]
    if favorites_only:
        rows = [r for r in rows if r.get("favorite")]
    if want_pattern is not None:
        rows = [r for r in rows if str(r.get("pattern") or "") == want_pattern]
    rows.sort(key=lambda r: str(r.get("created_at_utc") or ""), reverse=True)
    rows = rows[:max(1, min(2000, int(limit or 300)))]
    # pattern facets
    patterns: Dict[str, int] = {}
    with _LOCK:
        for r in (_read(_snapshot_index_path()).get("snapshots") or []):
            if isinstance(r, dict) and r.get("pattern"):
                patterns[str(r["pattern"])] = patterns.get(str(r["pattern"]), 0) + 1
    return {"snapshots": rows, "total": len(rows),
            "patterns": [{"name": k, "count": v} for k, v in sorted(patterns.items())]}


def _snapshot_match(row: Dict[str, Any], target: str) -> bool:
    return str(row.get("id") or "") == target or str(row.get("file") or "") == target


def update_snapshot(snap_id: Any, *, favorite: Optional[bool] = None,
                    pattern: Optional[str] = None, caption: Optional[str] = None) -> Dict[str, Any]:
    target = str(snap_id or "").strip()
    with _LOCK:
        doc = _read(_snapshot_index_path())
        rows = [r for r in (doc.get("snapshots") or []) if isinstance(r, dict)]
        updated = None
        for row in rows:
            if _snapshot_match(row, target):
                if favorite is not None:
                    row["favorite"] = bool(favorite)
                if pattern is not None:
                    row["pattern"] = str(pattern).strip()[:80]
                    if row["pattern"]:
                        row["favorite"] = True
                if caption is not None:
                    row["caption"] = str(caption).strip()[:300]
                updated = dict(row)
                break
        if updated is not None:
            doc["snapshots"] = rows
            doc["updated_at_utc"] = _iso()
            _write(_snapshot_index_path(), doc)
    return {"ok": updated is not None, "snapshot": updated}


def delete_snapshot(snap_id: Any) -> Dict[str, Any]:
    target = str(snap_id or "").strip()
    with _LOCK:
        doc = _read(_snapshot_index_path())
        rows = [r for r in (doc.get("snapshots") or []) if isinstance(r, dict)]
        kept, removed = [], None
        for row in rows:
            if _snapshot_match(row, target):
                removed = row
            else:
                kept.append(row)
        if removed is not None:
            try:
                (_snapshot_dir() / str(removed.get("file") or "")).unlink()
            except OSError:
                pass
            doc["snapshots"] = kept
            doc["updated_at_utc"] = _iso()
            _write(_snapshot_index_path(), doc)
    return {"deleted": removed is not None, "id": target}


def clear_snapshots(*, keep_favorites: bool = True) -> Dict[str, Any]:
    removed = 0
    with _LOCK:
        doc = _read(_snapshot_index_path())
        rows = [r for r in (doc.get("snapshots") or []) if isinstance(r, dict)]
        kept = []
        for row in rows:
            if keep_favorites and row.get("favorite"):
                kept.append(row)
                continue
            try:
                (_snapshot_dir() / str(row.get("file") or "")).unlink()
            except OSError:
                pass
            removed += 1
        doc["snapshots"] = kept
        doc["updated_at_utc"] = _iso()
        _write(_snapshot_index_path(), doc)
    return {"cleared": removed, "kept": len(kept)}
