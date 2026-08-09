"""Supervisor for parallel live market-data sources (warm shadow streams).

Does not treat Redis/PostgreSQL/cache as live sources.
Databento starts in shadow mode; automatic chart failover stays blocked until
``MarketDataRouter.allow_automatic_failover('databento_live')`` after parity.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Sequence

from . import market_data_live_adapters as adapters
from .market_data_router import get_router

_LOCK = threading.RLock()
_STARTED = False
_ADAPTERS: List[adapters.LiveMarketDataAdapter] = []

# Core CME micros for first Databento shadow pass (exact contracts filled at subscribe time).
_DEFAULT_ROOTS = ("MNQ", "MES", "M2K", "MYM", "MGC")


def _sink_for(adapter: adapters.LiveMarketDataAdapter):
    router = get_router()
    from .market_data_router import ProviderHealth

    def _sink(event: Dict[str, Any]) -> None:
        # Always shadow until explicit allow + try_failover promotes provider.
        router.ingest_shadow(adapter.name, event)
        contract = str(event.get("exact_contract") or "")
        router.update_health(ProviderHealth(
            provider=adapter.name,
            instrument=contract,
            channel="trades",
            transport_heartbeat_age_sec=0.0,
            provider_heartbeat_age_sec=0.0,
            last_age_sec=0.0,
            market_session_state="open",
            ok=True,
        ))

    return _sink


def status() -> Dict[str, Any]:
    with _LOCK:
        rows = [a.capabilities() | {"health": a.health()} for a in _ADAPTERS]
        connected = sum(1 for a in _ADAPTERS if a.health().get("runtime_state") == "LIVE")
        credentialed = sum(1 for a in _ADAPTERS if a.credentials_present())
        return {
            "started": _STARTED,
            "live_providers_connected": connected,
            "credentialed_providers": credentialed,
            "backup_live_providers_available": connected,
            "automatic_failover": get_router().status().get("auto_failover_allow") or {},
            "adapters": rows,
            "milestone": "MARKET_DATA_LIVE_SOURCES",
            "production_blocked": connected == 0,
            "note": (
                "Cache/Redis/PostgreSQL are not live sources. "
                "Provide NTA_DATABENTO_API_KEY + pip install databento to start first warm backup."
            ),
        }


def start(
    *,
    exact_contracts: Optional[Sequence[str]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Start credentialed adapters in shadow mode."""
    global _STARTED, _ADAPTERS
    with _LOCK:
        if _STARTED and not force:
            return status()
        _ADAPTERS = adapters.default_live_adapters()
        for adapter in _ADAPTERS:
            adapter.set_sink(_sink_for(adapter), mode="shadow")
            health = adapter.connect()
            # Every implemented credentialed read-only provider receives the
            # same exact-contract shadow subscriptions. Provider policy gates
            # (not this supervisor) decide whether remote use is permitted.
            if (
                adapter.name in {"databento_live", "topstep_live"}
                and adapter.credentials_present()
                and health.get("runtime_state") not in {
                    "DISABLED", "POLICY_BLOCKED", "ENTITLEMENT_MISSING", "AUTH_FAILED", "ERROR",
                }
            ):
                contracts = list(exact_contracts or [])
                if not contracts:
                    # Subscribe parent roots via continuous is forbidden for charts;
                    # require explicit exact contracts from caller/workspace later.
                    pass
                for contract in contracts:
                    try:
                        adapter.subscribe(contract, "trades")
                        adapter.subscribe(contract, "bid_ask")
                    except Exception as exc:
                        adapter._last_error = str(exc)[:300]
                        adapter._runtime_state = "ERROR"
        _STARTED = True
        return status()


def stop() -> None:
    global _STARTED
    with _LOCK:
        for adapter in _ADAPTERS:
            try:
                adapter.disconnect()
            except Exception:
                pass
        _STARTED = False


def get_adapter(name: str) -> Optional[adapters.LiveMarketDataAdapter]:
    with _LOCK:
        for adapter in _ADAPTERS:
            if adapter.name == name:
                return adapter
    return None
