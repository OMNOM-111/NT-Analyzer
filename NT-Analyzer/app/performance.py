"""Performance Center calculations for runtime trading telemetry.

The module builds a period-based, commission-aware profitability view from
runtime executions written by the NinjaTrader bridge. It intentionally exposes
only the four first-screen metrics requested by the UI: P/L after commission,
commission, Win Rate, and Profit Factor as percent.
"""
from __future__ import annotations

import math
import re
import csv
import hashlib
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import ops
from . import runtime as rt


MAX_RUNTIME_EXECUTIONS = 250_000
ALL_ACCOUNTS = "__all__"
_RESPONSE_CACHE: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
_RESPONSE_CACHE_MAX = 16
TRADE_EXPORT_COLUMNS = (
    "trade_no",
    "trade_id",
    "date_pt",
    "time_pt",
    "account_name",
    "instrument",
    "instrument_root",
    "direction",
    "quantity",
    "entry_time_utc",
    "exit_time_utc",
    "entry_price",
    "exit_price",
    "gross_pnl",
    "commission",
    "pnl",
    "commission_source",
    "exit_reason",
    "role",
    "action",
    "strategy_class",
    "strategy_name",
    "strategy_id",
    "runtime_instance_id",
    "entry_strategy_class",
    "entry_strategy_name",
    "entry_strategy_id",
    "entry_runtime_instance_id",
    "strategy_attribution_confidence",
    "strategy_attribution_source",
    "strategy_attribution_candidates",
    "entry_order_id",
    "exit_order_id",
    "entry_execution_id",
    "exit_execution_id",
    "order_name",
    "from_entry_signal",
    "unmapped",
)

_CELL_RE = re.compile(
    r"(?:[cC](\d{3})(?=$|[^A-Za-z0-9])|(?:^|[^A-Za-z0-9])(\d{3})(?=$|[^A-Za-z0-9]))"
)


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _round_money(value: float) -> float:
    return round(float(value or 0.0), 2)


def _round_pct(value: Optional[float]) -> Optional[float]:
    if value is None or not math.isfinite(value):
        return None
    return round(value, 1)


def _parse_ymd(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _today_pt(now_utc: Optional[datetime] = None) -> date:
    now = now_utc or datetime.now(timezone.utc)
    return ops._to_pt(now).date()


def resolve_period(period: str = "now",
                   from_date: Optional[str] = None,
                   to_date: Optional[str] = None,
                   now_utc: Optional[datetime] = None) -> Dict[str, Any]:
    """Resolve UI period preset to inclusive PT wall dates."""
    preset = (period or "now").strip().lower()
    today = _today_pt(now_utc)

    if preset in ("custom", "manual"):
        start = _parse_ymd(from_date) or today
        end = _parse_ymd(to_date) or start
        preset = "custom"
    elif preset == "week":
        start = today - timedelta(days=today.weekday())
        end = today
    elif preset == "month":
        start = today.replace(day=1)
        end = today
    elif preset == "year":
        start = date(today.year, 1, 1)
        end = today
    elif preset == "today":
        start = end = today
    else:
        preset = "now"
        start = end = today

    if end < start:
        start, end = end, start

    labels = {
        "now": "Сейчас",
        "today": "Сегодня",
        "week": "Неделя",
        "month": "Месяц",
        "year": "Год",
        "custom": "Даты вручную",
    }
    return {
        "preset": preset,
        "label": labels.get(preset, labels["now"]),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "today_pt": today.isoformat(),
    }


def _pt_date_from_iso(iso: Any) -> Optional[str]:
    dt = rt._parse_iso(str(iso or ""))
    if dt is None:
        return None
    return ops._to_pt(dt).date().isoformat()


def _pt_time_from_iso(iso: Any) -> str:
    dt = rt._parse_iso(str(iso or ""))
    if dt is None:
        return "—"
    return ops._to_pt(dt).strftime("%H:%M")


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_strategy_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and not rt._placeholder_strategy_value(text):
            return text
    return ""


def _strategy_candidate_text(value: Any) -> str:
    raw = value if isinstance(value, list) else []
    parts: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            text = _first_text(
                item.get("strategy_class"),
                item.get("strategy_name"),
                item.get("strategy_id"),
            )
        else:
            text = str(item or "").strip()
        if text:
            parts.append(text)
    return " / ".join(parts)


def _extract_cell(*values: Any) -> str:
    for value in values:
        text = str(value or "")
        matches = _CELL_RE.findall(text)
        if matches:
            a, b = matches[-1]
            return (a or b).zfill(3)
    return ""


def _strip_cell_suffix(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\s_-]*[cC]\d{3}\s*$", "", text).strip()
    return text or str(value or "").strip()


def _runtime_params(row: Dict[str, Any], view: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = row.get("params") or row.get("parameters")
    if isinstance(params, dict):
        return params
    locked = (view or {}).get("locked_params")
    return locked if isinstance(locked, dict) else {}


def _identity_tokens(row: Dict[str, Any]) -> set[str]:
    vals = [
        row.get("runtime_instance_id"),
        row.get("strategy_class"),
        row.get("class_name"),
        row.get("strategy_id"),
        row.get("strategy_name"),
        row.get("display_name"),
    ]
    out: set[str] = set()
    for value in vals:
        text = str(value or "").strip()
        if not text or rt._placeholder_strategy_value(text):
            continue
        out.add(text.lower())
        if value == row.get("strategy_id"):
            canon = rt.canonical_strategy_id(text)
            if canon:
                out.add(canon.lower())
    return out


def _strategy_status(row: Dict[str, Any], view: Optional[Dict[str, Any]] = None) -> str:
    if view is not None:
        if view.get("runtime_detected") and view.get("runtime_enabled"):
            return "работает"
        if view.get("runtime_detected"):
            return "остановлена"
    if row.get("enabled") is True:
        return "работает"
    state = str(row.get("state") or "").strip().lower()
    if state == "realtime":
        return "работает"
    if state:
        return "остановлена"
    return "нет данных"


def _runtime_instance_id(row: Dict[str, Any], idx: int) -> str:
    iid = str(row.get("runtime_instance_id") or "").strip()
    if iid:
        return iid
    try:
        return rt._make_runtime_instance_id(row, idx)
    except Exception:
        return ""


def _strategy_meta_from_runtime(row: Dict[str, Any],
                                view: Optional[Dict[str, Any]] = None,
                                idx: int = 0) -> Dict[str, Any]:
    row = dict(row or {})
    view = view or {}
    iid = str(view.get("runtime_instance_id") or _runtime_instance_id(row, idx) or "")
    sid = _first_text(row.get("strategy_id"), view.get("strategy_id"))
    cls = _first_text(row.get("strategy_class"), row.get("class_name"), view.get("display_key"))
    full_name = _first_text(
        view.get("display_name"),
        row.get("display_name"),
        row.get("strategy_name"),
        cls,
        sid,
        "Без названия",
    )
    cell = _extract_cell(
        view.get("profile_id"),
        row.get("strategy_name"),
        row.get("display_name"),
        cls,
        sid,
    )
    instrument_full = _first_text(
        row.get("instrument"),
        row.get("contract_month"),
        view.get("instrument"),
    )
    instrument_root = rt._instrument_root(instrument_full)
    params = _runtime_params(row, view)
    rtc = _num(params.get("RoundTurnCommission"))
    meta = {
        "key": iid or rt.canonical_strategy_id(sid) or cls.lower() or full_name.lower(),
        "runtime_instance_id": iid,
        "strategy_id": rt.canonical_strategy_id(sid) if sid else "",
        "strategy_class": cls,
        "full_name": full_name,
        "name": _strip_cell_suffix(full_name),
        "cell": cell,
        "instrument": instrument_root,
        "instrument_full": instrument_full,
        "timeframe": _first_text(row.get("timeframe"), row.get("bars_period"), view.get("timeframe")),
        "trade_window_pt": _first_text(view.get("trade_window_pt"), row.get("trade_window_pt")),
        "status": _strategy_status(row, view),
        "account_name": _first_text(row.get("account_name"), view.get("account_name")),
        "round_turn_commission": rtc,
        "tokens": set(),
    }
    token_row = {
        **row,
        "runtime_instance_id": iid,
        "strategy_id": meta["strategy_id"] or sid,
        "strategy_class": cls,
        "strategy_name": full_name,
        "display_name": full_name,
    }
    meta["tokens"] = _identity_tokens(token_row)
    return meta


def _runtime_strategy_metadata() -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    token_map: Dict[str, Dict[str, Any]] = {}
    metas: List[Dict[str, Any]] = []

    def add(meta: Dict[str, Any]) -> None:
        if not meta:
            return
        metas.append(meta)
        for token in meta.get("tokens") or set():
            token_map.setdefault(token, meta)

    try:
        for idx, view in enumerate(rt.merge_all_runtime_strategies()):
            add(_strategy_meta_from_runtime(view.get("runtime") or {}, view, idx))
    except Exception:
        pass

    for idx, row in enumerate(rt.read_strategies_raw()):
        add(_strategy_meta_from_runtime(row, None, idx))

    return token_map, metas


def _meta_for_row(row: Dict[str, Any], token_map: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    tokens = _identity_tokens(row)
    for key in ("runtime_instance_id", "strategy_class", "strategy_id", "strategy_name"):
        value = str(row.get(key) or "").strip().lower()
        if value and value in token_map:
            return token_map[value]
        if key == "strategy_id":
            canon = rt.canonical_strategy_id(value)
            if canon and canon in token_map:
                return token_map[canon]
    for token in tokens:
        if token in token_map:
            return token_map[token]
    return None


def _fallback_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    sid = str(row.get("strategy_id") or "").strip()
    cls = str(row.get("strategy_class") or "").strip()
    name = _first_text(row.get("strategy_name"), cls, sid, "Без привязки к стратегии")
    cell = _extract_cell(name, cls, sid)
    iid = str(row.get("runtime_instance_id") or "").strip()
    return {
        "key": iid or rt.canonical_strategy_id(sid) or cls.lower() or name.lower(),
        "runtime_instance_id": iid,
        "strategy_id": rt.canonical_strategy_id(sid) if sid else "",
        "strategy_class": cls,
        "full_name": name,
        "name": _strip_cell_suffix(name),
        "cell": cell,
        "instrument": rt._instrument_root(row.get("instrument")),
        "instrument_full": str(row.get("instrument") or ""),
        "timeframe": "",
        "trade_window_pt": "",
        "status": "нет данных",
        "account_name": str(row.get("account_name") or ""),
        "round_turn_commission": None,
        "tokens": _identity_tokens(row),
    }


def _is_unmapped_strategy(row: Dict[str, Any]) -> bool:
    if str(row.get("runtime_instance_id") or "").strip():
        return False
    values = [row.get("strategy_id"), row.get("strategy_class"), row.get("strategy_name")]
    return all(rt._placeholder_strategy_value(v) for v in values)


def _strategy_lot_identity(row: Dict[str, Any]) -> str:
    for key in ("runtime_instance_id", "strategy_class", "strategy_id"):
        value = str(row.get(key) or "").strip()
        if value and not rt._placeholder_strategy_value(value):
            return value.lower()
    candidates = _strategy_candidate_text(row.get("_strategy_attribution_candidates") or row.get("strategy_attribution_candidates"))
    if candidates:
        return "__legacy_candidates__:" + candidates.lower()
    return "__unmapped__"


def _round_turn_commission_for_execution(row: Dict[str, Any],
                                         metas: Iterable[Dict[str, Any]]) -> float:
    tokens = _identity_tokens(row)
    account = str(row.get("account_name") or "").strip()
    root = rt._instrument_root(row.get("instrument"))
    exact: List[float] = []
    scoped: List[float] = []
    seen: set[int] = set()
    for meta in metas:
        mid = id(meta)
        if mid in seen:
            continue
        seen.add(mid)
        rtc = _num(meta.get("round_turn_commission"))
        if rtc is None or rtc < 0:
            continue
        mtokens = meta.get("tokens") or set()
        if tokens and any(t in mtokens for t in tokens):
            exact.append(rtc)
            continue
        macct = str(meta.get("account_name") or "").strip()
        mroot = str(meta.get("instrument") or "").strip().upper()
        if root and mroot == root and (not account or not macct or account == macct):
            scoped.append(rtc)
    if exact:
        return max(exact)
    if scoped:
        return max(scoped)
    return float(ops.ROUND_TURN_COMMISSION)


def _execution_commission(row: Dict[str, Any]) -> float:
    return abs(_num(row.get("commission")) or 0.0)


def _opposing_lots(lots: List[Dict[str, Any]], signed_qty: float) -> bool:
    return bool(lots) and math.copysign(1.0, float(lots[0]["qty"])) != math.copysign(1.0, signed_qty)


def _first_lot_timestamp(lots: List[Dict[str, Any]]) -> str:
    if not lots:
        return ""
    return str(lots[0].get("entry_ts") or "")


def _closing_lots_for_row(lots_by_key: Dict[Tuple[str, str, str], List[Dict[str, Any]]],
                          lot_key: Tuple[str, str, str],
                          signed_qty: float,
                          row_unmapped: bool) -> Tuple[Tuple[str, str, str], List[Dict[str, Any]]]:
    lots = lots_by_key.setdefault(lot_key, [])
    if _opposing_lots(lots, signed_qty) or not row_unmapped:
        return lot_key, lots

    acct, root, _identity = lot_key
    matches: List[Tuple[Tuple[str, str, str], List[Dict[str, Any]]]] = []
    for alt_key, alt_lots in lots_by_key.items():
        if alt_key == lot_key:
            continue
        if alt_key[0] != acct or alt_key[1] != root:
            continue
        if _opposing_lots(alt_lots, signed_qty):
            matches.append((alt_key, alt_lots))
    if matches:
        matches.sort(key=lambda pair: _first_lot_timestamp(pair[1]))
        return matches[0]
    return lot_key, lots


def _annotate_executions_with_pnl(rows: List[Dict[str, Any]],
                                  token_map: Dict[str, Dict[str, Any]],
                                  metas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = [dict(r) for r in rows if isinstance(r, dict)]
    out.sort(key=lambda r: str(r.get("timestamp_utc") or ""))
    lots_by_key: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    closed: List[Dict[str, Any]] = []

    for row in out:
        row["_closed_qty"] = 0.0
        qty_abs = rt._abs_qty(row)
        price = rt._exec_price(row)
        side = rt._exec_side(row)
        if qty_abs <= 0.0 or price is None or side == 0:
            continue

        signed_qty = side * qty_abs
        fill_commission = _execution_commission(row)
        fill_commission_per_contract = fill_commission / qty_abs if qty_abs else 0.0
        fill_commission_consumed = 0.0
        lot_key = (
            str(row.get("account_name") or "").strip().lower(),
            rt._instrument_root(row.get("instrument")),
            _strategy_lot_identity(row),
        )
        lots_by_key.setdefault(lot_key, [])
        row_unmapped = _is_unmapped_strategy(row)

        while abs(signed_qty) > 1e-9:
            _active_lot_key, lots = _closing_lots_for_row(lots_by_key, lot_key, signed_qty, row_unmapped)
            if not _opposing_lots(lots, signed_qty):
                break
            lot = lots[0]
            close_qty = min(abs(signed_qty), abs(float(lot["qty"])))
            mult = rt._instrument_multiplier(row.get("instrument"))
            if float(lot["qty"]) > 0:
                gross_pnl = (price - float(lot["price"])) * close_qty * mult
            else:
                gross_pnl = (float(lot["price"]) - price) * close_qty * mult

            entry_commission = min(
                abs(float(lot.get("commission_remaining") or 0.0)),
                abs(float(lot.get("commission_per_contract") or 0.0)) * close_qty,
            )
            exit_commission = fill_commission_per_contract * close_qty
            fill_commission_consumed += exit_commission
            if entry_commission:
                lot["commission_remaining"] = max(
                    0.0,
                    abs(float(lot.get("commission_remaining") or 0.0)) - entry_commission,
                )
            actual_commission = entry_commission + exit_commission
            estimated_commission = _round_turn_commission_for_execution(row, metas) * close_qty
            commission = actual_commission if actual_commission > 1e-9 else estimated_commission
            commission_source = "execution_commission" if actual_commission > 1e-9 else "round_turn_estimate"
            lot_row = {
                "account_name": row.get("account_name"),
                "instrument": row.get("instrument"),
                "strategy_id": lot.get("strategy_id"),
                "strategy_class": lot.get("strategy_class"),
                "strategy_name": lot.get("strategy_name"),
                "runtime_instance_id": lot.get("runtime_instance_id"),
            }
            meta = (
                _meta_for_row(row, token_map)
                or _meta_for_row(lot_row, token_map)
                or _fallback_meta(lot_row if _is_unmapped_strategy(row) else row)
            )
            strategy_id = _first_strategy_text(row.get("strategy_id"), lot.get("strategy_id"))
            strategy_class = _first_strategy_text(row.get("strategy_class"), lot.get("strategy_class"))
            strategy_name = _first_strategy_text(row.get("strategy_name"), lot.get("strategy_name"))
            runtime_instance_id = _first_text(row.get("runtime_instance_id"), lot.get("runtime_instance_id"))
            closed.append({
                "timestamp_utc": row.get("timestamp_utc"),
                "exit_time_utc": row.get("timestamp_utc"),
                "entry_time_utc": lot.get("entry_ts"),
                "date_pt": _pt_date_from_iso(row.get("timestamp_utc")),
                "time_pt": _pt_time_from_iso(row.get("timestamp_utc")),
                "account_name": row.get("account_name") or "",
                "instrument": row.get("instrument") or "",
                "instrument_root": rt._instrument_root(row.get("instrument")),
                "direction": "long" if float(lot["qty"]) > 0 else "short",
                "quantity": close_qty,
                "entry_price": lot.get("price"),
                "exit_price": price,
                "gross_pnl": gross_pnl,
                "commission": commission,
                "commission_source": commission_source,
                "pnl": gross_pnl - commission,
                "action": row.get("order_action") or row.get("action") or "",
                "role": row.get("role") or row.get("position_action") or "exit",
                "exit_reason": row.get("exit_reason") or "",
                "strategy_id": strategy_id,
                "strategy_class": strategy_class,
                "strategy_name": strategy_name,
                "runtime_instance_id": runtime_instance_id,
                "entry_strategy_id": lot.get("strategy_id") or "",
                "entry_strategy_class": lot.get("strategy_class") or "",
                "entry_strategy_name": lot.get("strategy_name") or "",
                "entry_runtime_instance_id": lot.get("runtime_instance_id") or "",
                "strategy_attribution_confidence": row.get("_strategy_attribution_confidence") or "",
                "strategy_attribution_source": row.get("_strategy_attribution_source") or "",
                "strategy_attribution_candidates": row.get("_strategy_attribution_candidates") or [],
                "entry_order_id": lot.get("order_id") or "",
                "exit_order_id": row.get("order_id") or "",
                "entry_execution_id": lot.get("execution_id") or "",
                "exit_execution_id": row.get("execution_id") or "",
                "order_name": row.get("order_name") or "",
                "from_entry_signal": row.get("from_entry_signal") or "",
                "unmapped": _is_unmapped_strategy(row) and _is_unmapped_strategy(lot_row),
                "strategy_meta": meta,
            })

            row["_closed_qty"] = float(row.get("_closed_qty") or 0.0) + close_qty
            lot_sign = 1.0 if float(lot["qty"]) > 0 else -1.0
            signed_sign = 1.0 if signed_qty > 0 else -1.0
            lot["qty"] = float(lot["qty"]) - lot_sign * close_qty
            signed_qty = signed_qty - signed_sign * close_qty
            if abs(float(lot["qty"])) <= 1e-9:
                lots.pop(0)

        if abs(signed_qty) > 1e-9:
            remaining_commission = max(0.0, fill_commission - fill_commission_consumed)
            lots = lots_by_key.setdefault(lot_key, [])
            lots.append({
                "qty": signed_qty,
                "price": price,
                "entry_ts": row.get("timestamp_utc"),
                "order_id": row.get("order_id") or "",
                "execution_id": row.get("execution_id") or "",
                "strategy_id": row.get("strategy_id") or "",
                "strategy_class": row.get("strategy_class") or "",
                "strategy_name": row.get("strategy_name") or "",
                "runtime_instance_id": row.get("runtime_instance_id") or "",
                "commission_remaining": remaining_commission,
                "commission_per_contract": remaining_commission / abs(signed_qty),
            })

    # Fallback for older telemetry where only exit executions have realized PnL.
    for row in out:
        if float(row.get("_closed_qty") or 0.0) > 1e-9:
            continue
        if not rt._exec_is_exit(row):
            continue
        gross_pnl = rt._exec_pnl(row)
        if gross_pnl is None:
            gross_pnl = 0.0
        qty_abs = rt._abs_qty(row)
        commission = _execution_commission(row)
        if commission <= 1e-9 and qty_abs > 0:
            commission = _round_turn_commission_for_execution(row, metas) * qty_abs
        commission_source = "execution_commission" if _execution_commission(row) > 1e-9 else "round_turn_estimate"
        meta = _meta_for_row(row, token_map) or _fallback_meta(row)
        closed.append({
            "timestamp_utc": row.get("timestamp_utc"),
            "exit_time_utc": row.get("timestamp_utc"),
            "entry_time_utc": None,
            "date_pt": _pt_date_from_iso(row.get("timestamp_utc")),
            "time_pt": _pt_time_from_iso(row.get("timestamp_utc")),
            "account_name": row.get("account_name") or "",
            "instrument": row.get("instrument") or "",
            "instrument_root": rt._instrument_root(row.get("instrument")),
            "direction": "",
            "quantity": qty_abs,
            "entry_price": None,
            "exit_price": rt._exec_price(row),
            "gross_pnl": gross_pnl,
            "commission": commission,
            "commission_source": commission_source,
            "pnl": float(gross_pnl) - commission,
            "action": row.get("order_action") or row.get("action") or "",
            "role": row.get("role") or row.get("position_action") or "exit",
            "exit_reason": row.get("exit_reason") or "",
            "strategy_id": row.get("strategy_id") or "",
            "strategy_class": row.get("strategy_class") or "",
            "strategy_name": row.get("strategy_name") or "",
            "runtime_instance_id": row.get("runtime_instance_id") or "",
            "entry_strategy_id": "",
            "entry_strategy_class": "",
            "entry_strategy_name": "",
            "entry_runtime_instance_id": "",
            "strategy_attribution_confidence": row.get("_strategy_attribution_confidence") or "",
            "strategy_attribution_source": row.get("_strategy_attribution_source") or "",
            "strategy_attribution_candidates": row.get("_strategy_attribution_candidates") or [],
            "entry_order_id": "",
            "exit_order_id": row.get("order_id") or "",
            "entry_execution_id": "",
            "exit_execution_id": row.get("execution_id") or "",
            "order_name": row.get("order_name") or "",
            "from_entry_signal": row.get("from_entry_signal") or "",
            "unmapped": _is_unmapped_strategy(row),
            "strategy_meta": meta,
        })

    closed.sort(key=lambda r: str(r.get("timestamp_utc") or ""))
    return closed


def _trade_source_key(trade: Dict[str, Any]) -> str:
    raw = "|".join(str(trade.get(key) or "") for key in (
        "account_name",
        "instrument",
        "entry_time_utc",
        "exit_time_utc",
        "entry_order_id",
        "exit_order_id",
        "entry_execution_id",
        "exit_execution_id",
        "quantity",
        "entry_price",
        "exit_price",
    ))
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _assign_trade_numbers(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [dict(t) for t in trades]
    rows.sort(key=lambda r: (
        str(r.get("exit_time_utc") or r.get("timestamp_utc") or ""),
        str(r.get("entry_time_utc") or ""),
        str(r.get("exit_execution_id") or ""),
    ))
    counters: Dict[str, int] = {}
    for row in rows:
        account = str(row.get("account_name") or "account").strip() or "account"
        counters[account] = counters.get(account, 0) + 1
        row["trade_no"] = counters[account]
        row["trade_id"] = f"{account}|{_trade_source_key(row)}"
    return rows


def _metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(trades)
    pnl = sum(float(t.get("pnl") or 0.0) for t in trades)
    gross_pnl = sum(float(t.get("gross_pnl") or 0.0) for t in trades)
    commission = sum(float(t.get("commission") or 0.0) for t in trades)
    wins = sum(1 for t in trades if float(t.get("pnl") or 0.0) > 0)
    losses = sum(1 for t in trades if float(t.get("pnl") or 0.0) < 0)
    flats = total - wins - losses
    gross_profit = sum(float(t.get("pnl") or 0.0) for t in trades if float(t.get("pnl") or 0.0) > 0)
    gross_loss_abs = -sum(float(t.get("pnl") or 0.0) for t in trades if float(t.get("pnl") or 0.0) < 0)
    win_rate = (wins / total * 100.0) if total else None

    pf_kind = "none"
    profit_factor: Optional[float] = None
    pf_pct: Optional[float] = None
    if total:
        if gross_loss_abs <= 1e-9:
            if gross_profit > 1e-9:
                pf_kind = "infinite"
            else:
                pf_kind = "none"
        else:
            profit_factor = gross_profit / gross_loss_abs
            pf_pct = (profit_factor - 1.0) * 100.0
            pf_kind = "finite"

    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "pnl": _round_money(pnl),
        "gross_pnl": _round_money(gross_pnl),
        "commission": _round_money(commission),
        "win_rate": _round_pct(win_rate),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "profit_factor_pct": _round_pct(pf_pct),
        "profit_factor_kind": pf_kind,
        "profit_factor_sort": 1e9 if pf_kind == "infinite" else (pf_pct if pf_pct is not None else None),
    }


def _daily_series(trades: List[Dict[str, Any]], start: date, end: date) -> List[Dict[str, Any]]:
    by_day: Dict[str, float] = {}
    for trade in trades:
        day = str(trade.get("date_pt") or "")
        if day:
            by_day[day] = by_day.get(day, 0.0) + float(trade.get("pnl") or 0.0)
    days: List[Dict[str, Any]] = []
    cur = start
    # One-year preset is still small enough to render; cap protects bad custom input.
    for _ in range(370):
        if cur > end:
            break
        key = cur.isoformat()
        days.append({"date": key, "pnl": _round_money(by_day.get(key, 0.0))})
        cur += timedelta(days=1)
    return days


def _last_trades(trades: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    out = []
    for trade in sorted(trades, key=lambda r: str(r.get("timestamp_utc") or ""), reverse=True)[:limit]:
        out.append({
            "timestamp_utc": trade.get("timestamp_utc"),
            "time_pt": trade.get("time_pt") or _pt_time_from_iso(trade.get("timestamp_utc")),
            "date_pt": trade.get("date_pt"),
            "action": trade.get("action") or trade.get("role") or "—",
            "instrument": trade.get("instrument_root") or rt._instrument_root(trade.get("instrument")),
            "pnl": _round_money(float(trade.get("pnl") or 0.0)),
            "commission": _round_money(float(trade.get("commission") or 0.0)),
        })
    return out


def _flatten_metrics(row: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    out.update(metrics)
    return out


def _aggregate_strategies(trades: List[Dict[str, Any]],
                          start: date,
                          end: date) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for trade in trades:
        meta = trade.get("strategy_meta") or _fallback_meta(trade)
        key = str(meta.get("key") or "")
        if not key:
            key = "__unmapped__"
        group = groups.setdefault(key, {
            "key": key,
            "cell": meta.get("cell") or "",
            "strategy": meta.get("name") or "Без привязки к стратегии",
            "strategy_full": meta.get("full_name") or meta.get("name") or "",
            "strategy_class": meta.get("strategy_class") or "",
            "strategy_id": meta.get("strategy_id") or "",
            "runtime_instance_id": meta.get("runtime_instance_id") or "",
            "instrument_set": set(),
            "instrument_full_set": set(),
            "timeframe": meta.get("timeframe") or "",
            "trade_window_pt": meta.get("trade_window_pt") or "",
            "status": meta.get("status") or "нет данных",
            "trades_raw": [],
        })
        root = trade.get("instrument_root") or meta.get("instrument") or rt._instrument_root(trade.get("instrument"))
        full = str(trade.get("instrument") or meta.get("instrument_full") or root)
        if root:
            group["instrument_set"].add(root)
        if full:
            group["instrument_full_set"].add(full)
        group["trades_raw"].append(trade)

    rows = []
    for group in groups.values():
        raw = group.pop("trades_raw")
        instruments = sorted(group.pop("instrument_set"))
        instrument_fulls = sorted(group.pop("instrument_full_set"))
        row = {
            **group,
            "instrument": ", ".join(instruments) if instruments else "—",
            "instrument_full": ", ".join(instrument_fulls) if instrument_fulls else "—",
            "daily": _daily_series(raw, start, end),
            "last_trades": _last_trades(raw),
        }
        rows.append(_flatten_metrics(row, _metrics(raw)))
    rows.sort(key=lambda r: float(r.get("pnl") or 0.0), reverse=True)
    return rows


def _aggregate_instruments(trades: List[Dict[str, Any]],
                           start: date,
                           end: date) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for trade in trades:
        root = trade.get("instrument_root") or rt._instrument_root(trade.get("instrument")) or "—"
        group = groups.setdefault(root, {
            "instrument": root,
            "instrument_full_set": set(),
            "trades_raw": [],
            "strategy_pnl": {},
            "strategy_names": {},
        })
        full = str(trade.get("instrument") or root)
        if full:
            group["instrument_full_set"].add(full)
        group["trades_raw"].append(trade)
        meta = trade.get("strategy_meta") or _fallback_meta(trade)
        skey = str(meta.get("key") or "")
        if skey and skey != "__unmapped__":
            group["strategy_pnl"][skey] = group["strategy_pnl"].get(skey, 0.0) + float(trade.get("pnl") or 0.0)
            label = " ".join(x for x in (meta.get("cell"), meta.get("name")) if x)
            group["strategy_names"][skey] = label or meta.get("full_name") or skey

    rows = []
    for group in groups.values():
        raw = group.pop("trades_raw")
        fulls = sorted(group.pop("instrument_full_set"))
        strategy_pnl = group.pop("strategy_pnl")
        strategy_names = group.pop("strategy_names")
        strategy_rows = [
            {"key": key, "strategy": strategy_names.get(key, key), "pnl": _round_money(pnl)}
            for key, pnl in strategy_pnl.items()
        ]
        strategy_rows.sort(key=lambda r: float(r.get("pnl") or 0.0), reverse=True)
        best = strategy_rows[0]["strategy"] if strategy_rows else "—"
        row = {
            **group,
            "instrument_full": ", ".join(fulls) if fulls else group["instrument"],
            "strategy_count": len(strategy_rows),
            "best_strategy": best,
            "strategies": strategy_rows,
            "daily": _daily_series(raw, start, end),
            "last_trades": _last_trades(raw),
        }
        rows.append(_flatten_metrics(row, _metrics(raw)))
    rows.sort(key=lambda r: float(r.get("pnl") or 0.0), reverse=True)
    return rows


def _filter_period(trades: List[Dict[str, Any]], start: date, end: date) -> List[Dict[str, Any]]:
    out = []
    for trade in trades:
        day = _parse_ymd(str(trade.get("date_pt") or ""))
        if day is not None and start <= day <= end:
            out.append(trade)
    return out


def _closed_trades_for_request(period: str = "month",
                               from_date: Optional[str] = None,
                               to_date: Optional[str] = None,
                               account_name: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], int]:
    resolved = resolve_period(period, from_date, to_date)
    start = _parse_ymd(resolved["from"]) or _today_pt()
    end = _parse_ymd(resolved["to"]) or start
    selected_account = str(account_name or "").strip()
    account_filter = None if selected_account in ("", ALL_ACCOUNTS) else selected_account
    token_map, metas = _runtime_strategy_metadata()
    executions, dedupe_meta = rt.read_executions_with_meta(
        limit=MAX_RUNTIME_EXECUTIONS,
        account_name=account_filter,
    )
    all_closed = _assign_trade_numbers(_annotate_executions_with_pnl(executions, token_map, metas))
    return resolved, _filter_period(all_closed, start, end), dedupe_meta, len(all_closed)


def _export_trade_row(trade: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for key in TRADE_EXPORT_COLUMNS:
        value = trade.get(key)
        if key == "strategy_attribution_candidates":
            value = _strategy_candidate_text(value)
        elif isinstance(value, float):
            value = round(value, 6)
        elif isinstance(value, bool):
            value = "true" if value else "false"
        elif value is None:
            value = ""
        row[key] = value
    return row


def build_trades_csv(period: str = "month",
                     from_date: Optional[str] = None,
                     to_date: Optional[str] = None,
                     account_name: Optional[str] = None) -> Tuple[str, bytes]:
    resolved, trades, _dedupe_meta, _all_count = _closed_trades_for_request(
        period=period,
        from_date=from_date,
        to_date=to_date,
        account_name=account_name,
    )
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(TRADE_EXPORT_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for trade in trades:
        writer.writerow(_export_trade_row(trade))
    account_part = str(account_name or ALL_ACCOUNTS).strip() or ALL_ACCOUNTS
    account_part = re.sub(r"[^A-Za-z0-9_.-]+", "_", account_part)
    filename = f"nta-trades-{account_part}-{resolved['from']}_{resolved['to']}.csv"
    return filename, ("\ufeff" + buf.getvalue()).encode("utf-8")


def _file_sig(name: str) -> Tuple[str, Optional[int], Optional[int]]:
    path = rt.runtime_dir() / name
    try:
        st = path.stat()
    except OSError:
        return (name, None, None)
    return (name, st.st_size, st.st_mtime_ns)


def _runtime_cache_sig() -> Tuple[Any, ...]:
    return (
        str(rt.runtime_dir().resolve()),
        _file_sig("executions.jsonl"),
        _file_sig("orders.jsonl"),
        _file_sig("strategies.json"),
        _file_sig("accounts.json"),
    )


def _accounts_payload() -> Tuple[List[Dict[str, Any]], str]:
    try:
        doc = rt.read_accounts_with_source()
    except Exception:
        return [], "error"
    accounts = doc.get("online_accounts") or doc.get("accounts") or []
    safe_accounts = []
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        safe_accounts.append({
            "account_name": acc.get("account_name") or "",
            "account_mode": acc.get("account_mode") or "",
            "is_live": bool(acc.get("is_live")),
            "is_system": bool(acc.get("is_system")),
        })
    return safe_accounts, str(doc.get("source") or "")


def build_performance_response(period: str = "now",
                               from_date: Optional[str] = None,
                               to_date: Optional[str] = None,
                               account_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_period(period, from_date, to_date)
    start = _parse_ymd(resolved["from"]) or _today_pt()
    end = _parse_ymd(resolved["to"]) or start
    selected_account = str(account_name or "").strip()
    account_filter = None if selected_account in ("", ALL_ACCOUNTS) else selected_account
    cache_key = (
        resolved.get("preset"),
        resolved.get("from"),
        resolved.get("to"),
        account_filter or ALL_ACCOUNTS,
        _runtime_cache_sig(),
    )
    cached = _RESPONSE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    accounts, account_source = _accounts_payload()
    token_map, metas = _runtime_strategy_metadata()
    executions, dedupe_meta = rt.read_executions_with_meta(
        limit=MAX_RUNTIME_EXECUTIONS,
        account_name=account_filter,
    )
    all_closed = _assign_trade_numbers(_annotate_executions_with_pnl(executions, token_map, metas))
    period_trades = _filter_period(all_closed, start, end)
    summary = _metrics(period_trades)
    strategies = _aggregate_strategies(period_trades, start, end)
    instruments = _aggregate_instruments(period_trades, start, end)

    response = {
        "ok": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period": resolved,
        "account": account_filter or ALL_ACCOUNTS,
        "accounts": accounts,
        "accounts_source": account_source,
        "dedupe": dedupe_meta,
        "summary": summary,
        "strategies": strategies,
        "instruments": instruments,
        "has_trades": bool(period_trades),
        "empty_message": "" if period_trades else "За выбранный период сделок нет.",
        "trade_count": len(period_trades),
        "all_trade_count": len(all_closed),
        "execution_count": len(executions),
    }
    _RESPONSE_CACHE[cache_key] = response
    while len(_RESPONSE_CACHE) > _RESPONSE_CACHE_MAX:
        _RESPONSE_CACHE.pop(next(iter(_RESPONSE_CACHE)))
    return response
