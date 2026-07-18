"""Market-data cache keys and series identity helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence


SCHEMA_VERSION = "v1"
BAR_ENGINE_VERSION = "be1"


def market_cache_key(
    *,
    provider: str,
    exchange: str,
    exact_contract: str,
    channel: str,
    sharing_scope: str = "global",
    workspace_id: str = "",
    user_id: str = "",
    account_id: str = "",
    timeframe: str = "",
    session_template: str = "cme_equity_eth",
    adjustment_mode: str = "raw",
    bar_engine_version: str = BAR_ENGINE_VERSION,
    source_epoch: int = 0,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """Build a collision-resistant market-data cache key.

    Exact contract is mandatory — roots alone are insufficient.
    """
    scope = str(sharing_scope or "global").strip().lower()
    if scope not in {"global", "workspace", "private"}:
        raise ValueError(f"unsupported market-data sharing scope: {scope}")
    workspace = str(workspace_id or "").strip()
    user = str(user_id or "").strip()
    account = str(account_id or "").strip()
    if scope == "workspace" and not workspace:
        raise ValueError("workspace_id is required for workspace cache scope")
    if scope == "private" and not (workspace and user and account):
        raise ValueError("workspace_id, user_id and account_id are required for private cache scope")
    parts = [
        "md",
        schema_version,
        scope,
        workspace if scope in {"workspace", "private"} else "-",
        user if scope == "private" else "-",
        account if scope == "private" else "-",
        str(provider or "unknown").strip().lower(),
        str(exchange or "CME").strip().upper(),
        str(exact_contract or "").strip().upper(),
        str(channel or "trades").strip().lower(),
        str(timeframe or "-").strip().lower(),
        str(session_template or "-").strip().lower(),
        str(adjustment_mode or "raw").strip().lower(),
        str(bar_engine_version or BAR_ENGINE_VERSION).strip().lower(),
        f"epoch{int(source_epoch or 0)}",
    ]
    if not parts[8]:
        raise ValueError("exact_contract is required for market cache keys")
    return ":".join(parts)


def series_hash(bars: Sequence[Dict[str, Any]], limit: int = 200) -> str:
    """Stable hash of OHLC series for identity checks (not for crypto security)."""
    rows = list(bars or [])[-max(1, limit):]
    payload = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload.append([
            str(row.get("t") or row.get("time") or ""),
            _num(row.get("o", row.get("open"))),
            _num(row.get("h", row.get("high"))),
            _num(row.get("l", row.get("low"))),
            _num(row.get("c", row.get("close"))),
            _num(row.get("v", row.get("volume"))),
        ])
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _num(value: Any) -> Optional[float]:
    try:
        return round(float(value), 8)
    except (TypeError, ValueError):
        return None


def diagnostics_for_series(
    *,
    requested_symbol: str,
    exact_contract: str,
    timeframe: str,
    provider: str,
    bars: Sequence[Dict[str, Any]],
    cache_key: str,
    cache_level: str = "MISS",
    cache_hit: bool = False,
    transport: str = "http",
    ws_state: str = "unknown",
    subscription_id: str = "",
    source_epoch: int = 0,
    session_template: str = "cme_equity_eth",
    subscriber_count: int = 0,
    last_event_age_sec: Optional[float] = None,
    e2e_latency_ms: Optional[float] = None,
    canonical_symbol: str = "",
    raw_provider_symbol: str = "",
) -> Dict[str, Any]:
    rows = [b for b in (bars or []) if isinstance(b, dict)]
    first = rows[0] if rows else {}
    last = rows[-1] if rows else {}
    return {
        "requested_symbol": requested_symbol,
        "canonical_symbol": canonical_symbol or exact_contract,
        "raw_provider_symbol": raw_provider_symbol or exact_contract,
        "exact_contract": exact_contract,
        "timeframe": timeframe,
        "session_template": session_template,
        "provider": provider,
        "provider_subscription_id": subscription_id,
        "cache_key": cache_key,
        "cache_level": cache_level,
        "cache_hit": bool(cache_hit),
        "series_hash": series_hash(rows),
        "source_epoch": int(source_epoch or 0),
        "first_bar_time": first.get("t") or first.get("time"),
        "last_bar_time": last.get("t") or last.get("time"),
        "last_price": last.get("c", last.get("close")),
        "bar_count": len(rows),
        "transport": transport,
        "ws_state": ws_state,
        "subscriber_count": int(subscriber_count or 0),
        "last_event_age_sec": last_event_age_sec,
        "e2e_latency_ms": e2e_latency_ms,
    }
