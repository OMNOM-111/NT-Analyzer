"""Canonical market-data event model.

Sequence identity rules:
- ``exchange_sequence`` — only when the venue/provider supplies it; never invented.
- ``provider_sequence`` — provider-native monotonic id when available.
- ``connection_sequence`` — per IPC/connection counter.
- ``generated_sequence`` — local generator; MUST NOT be copied into exchange_sequence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Tuple

PROTOCOL_VERSION = 1
VALID_EVENT_TYPES = {"trade", "bid", "ask", "quote", "depth", "status", "correction"}
VALID_DATA_PLANES = {"display", "analytics", "strategy", "execution", "history_replay"}
VALID_QUALITY_FLAGS = {
    "bridge_tick",
    "delayed",
    "estimated_bid_ask",
    "stale",
    "out_of_order",
    "duplicate",
    "synthetic",
    "corrected",
    "gap_fill",
    "shadow",
}


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def make_canonical_event(
    *,
    event_type: str,
    provider: str,
    raw_symbol: str,
    exact_contract: str,
    canonical_symbol: str = "",
    price: Any = None,
    bid: Any = None,
    ask: Any = None,
    volume: Any = None,
    exchange_sequence: Any = None,
    provider_sequence: Any = None,
    connection_sequence: Any = None,
    generated_sequence: Any = None,
    connection_id: str = "",
    subscription_id: str = "",
    source_epoch: int = 0,
    channel: str = "trades",
    data_plane: str = "display",
    ts_event: Any = None,
    ts_provider: Any = None,
    ts_receive: Any = None,
    quality: Optional[Dict[str, Any]] = None,
    tick_size: Optional[float] = None,
) -> Dict[str, Any]:
    et = str(event_type or "trade").strip().lower()
    if et not in VALID_EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")
    plane = str(data_plane or "display").strip().lower()
    if plane not in VALID_DATA_PLANES:
        raise ValueError(f"unsupported data_plane: {data_plane}")

    exch = _optional_int(exchange_sequence)
    prov = _optional_int(provider_sequence)
    conn = _optional_int(connection_sequence)
    gen = _optional_int(generated_sequence)
    # Hard rule: never promote generated → exchange.
    if exch is not None and gen is not None and exch == gen and provider == "local":
        exch = None

    px = _finite_float(price)
    if tick_size and px is not None and tick_size > 0:
        # Soft quality flag only; do not mutate price here.
        rem = abs(px / tick_size - round(px / tick_size))
        off_tick = rem > 1e-8
    else:
        off_tick = False

    qflags = dict(quality or {})
    if off_tick:
        qflags["off_tick"] = True

    return {
        "protocol_version": PROTOCOL_VERSION,
        "type": et,
        "provider": str(provider or "").strip().lower(),
        "raw_symbol": str(raw_symbol or "").strip(),
        "canonical_symbol": str(canonical_symbol or "").strip(),
        "exact_contract": str(exact_contract or "").strip(),
        "channel": str(channel or "trades"),
        "data_plane": plane,
        "connection_id": str(connection_id or ""),
        "subscription_id": str(subscription_id or ""),
        "source_epoch": int(source_epoch or 0),
        "price": px,
        "bid": _finite_float(bid),
        "ask": _finite_float(ask),
        "volume": _finite_float(volume),
        "exchange_sequence": exch,
        "provider_sequence": prov,
        "connection_sequence": conn,
        "generated_sequence": gen,
        "ts_event": str(ts_event or "") or None,
        "ts_provider": str(ts_provider or "") or None,
        "ts_receive": str(ts_receive or _iso()),
        "quality": qflags,
    }


def dedupe_key(event: Dict[str, Any]) -> Tuple[Any, ...]:
    """Deterministic dedupe identity. Prefer exchange/provider sequences."""
    if event.get("exchange_sequence") is not None:
        return (
            "exchange",
            event.get("provider"),
            event.get("exact_contract"),
            event.get("exchange_sequence"),
            event.get("type"),
        )
    if event.get("provider_sequence") is not None:
        return (
            "provider",
            event.get("provider"),
            event.get("exact_contract"),
            event.get("provider_sequence"),
            event.get("type"),
        )
    return (
        "generated",
        event.get("provider"),
        event.get("connection_id"),
        event.get("exact_contract"),
        event.get("generated_sequence"),
        event.get("type"),
        event.get("ts_event"),
        event.get("price"),
    )


class EventDedupeCache:
    def __init__(self, capacity: int = 50_000) -> None:
        self._capacity = max(100, capacity)
        self._seen: Set[Tuple[Any, ...]] = set()
        self._order: list = []

    def seen(self, event: Dict[str, Any]) -> bool:
        key = dedupe_key(event)
        if key in self._seen:
            return True
        self._seen.add(key)
        self._order.append(key)
        if len(self._order) > self._capacity:
            old = self._order.pop(0)
            self._seen.discard(old)
        return False


def event_time_utc(event: Dict[str, Any]) -> Optional[datetime]:
    for key in ("ts_event", "ts_provider", "ts_receive"):
        dt = _parse_iso(event.get(key))
        if dt is not None:
            return dt.astimezone(timezone.utc)
    return None
