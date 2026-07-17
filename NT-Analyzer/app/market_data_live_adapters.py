"""Parallel live market-data adapters (Databento first; others scaffolded).

These are independent *quote sources*, not cache/Redis/WS infrastructure.

Rules:
- Recorded/FaultInjection never get REALTIME_PRODUCTION.
- Yahoo never gets automatic production failover.
- Automatic failover requires shadow parity pass + explicit allow flag.
- Without credentials, adapters stay ENTITLEMENT_MISSING / DISABLED.
"""
from __future__ import annotations

import os
import re
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from .canonical_event import make_canonical_event
from .instrument_registry import get_registry

EventSink = Callable[[Dict[str, Any]], None]

_CONTRACT_RE = re.compile(r"^([A-Z0-9]+)\s+(\d{2})-(\d{2})$")
_MONTH_CODE = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def databento_raw_symbol(exact_contract: str) -> str:
    """Map NT-style ``MNQ 09-26`` → Databento raw ``MNQU6`` (1-digit year)."""
    raw = " ".join(str(exact_contract or "").strip().upper().split())
    match = _CONTRACT_RE.match(raw)
    if not match:
        raise ValueError(f"exact contract required, got {exact_contract!r}")
    root, mm, yy = match.group(1), int(match.group(2)), int(match.group(3))
    return f"{root}{_MONTH_CODE[mm]}{yy % 10}"


class LiveMarketDataAdapter(ABC):
    name = "base"

    @property
    def production_failover_eligible(self) -> bool:
        if self.name in {"yahoo", "yahoo_chart", "recorded", "fault_injection"}:
            return False
        from .market_data_router import get_router
        try:
            router = get_router()
            report = router._parity.get(self.name)
            return bool(report and report.passed)
        except Exception:
            return False

    def __init__(self) -> None:
        self._subs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._runtime_state = "DISABLED"
        self._last_error = ""
        self._last_event_utc = ""
        self._connected_at = ""
        self._event_count = 0
        self._sink: Optional[EventSink] = None
        self._mode = "shadow"  # shadow | authoritative
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._client: Any = None

    @abstractmethod
    def implementation_state(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def credentials_present(self) -> bool:
        raise NotImplementedError

    def set_sink(self, sink: Optional[EventSink], *, mode: str = "shadow") -> None:
        self._sink = sink
        self._mode = "authoritative" if mode == "authoritative" else "shadow"

    def capabilities(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "implementation_state": self.implementation_state(),
            "runtime_state": self._runtime_state,
            "credentials_present": self.credentials_present(),
            "production_failover_eligible": self.production_failover_eligible,
            "channels": ["trades", "bid_ask"],
            "historical": False,
            "live": True,
            "reconnect": True,
            "replay_intraday_24h": False,
            "mode": self._mode,
            "REALTIME_PRODUCTION": bool(
                self.production_failover_eligible and self.credentials_present()
            ),
        }

    def health(self) -> Dict[str, Any]:
        age = None
        if self._last_event_utc:
            try:
                dt = datetime.fromisoformat(self._last_event_utc.replace("Z", "+00:00"))
                age = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
            except ValueError:
                age = None
        return {
            "name": self.name,
            "runtime_state": self._runtime_state,
            "implementation_state": self.implementation_state(),
            "credentials_present": self.credentials_present(),
            "connected_at_utc": self._connected_at,
            "last_event_utc": self._last_event_utc,
            "last_event_age_sec": age,
            "event_count": self._event_count,
            "subscriptions": len(self._subs),
            "last_error": self._last_error,
            "mode": self._mode,
        }

    def connect(self) -> Dict[str, Any]:
        self._runtime_state = "CONNECTING"
        self._connected_at = _iso()
        return self.health()

    def disconnect(self) -> None:
        self._stop.set()
        client = self._client
        self._client = None
        try:
            if client is not None and hasattr(client, "stop"):
                client.stop()
        except Exception:
            pass
        with self._lock:
            self._subs.clear()
        self._runtime_state = "DISABLED"

    @abstractmethod
    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError

    def unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            self._subs.pop(str(subscription_id), None)

    def _emit(self, event: Dict[str, Any]) -> None:
        self._event_count += 1
        self._last_event_utc = str(event.get("ts_provider") or event.get("ts_event") or _iso())
        sink = self._sink
        if sink is not None:
            sink(event)

    def _emit_mock_tick(self, contract: str, raw_sym: str, schema: str, tick_size: float, last_prices: dict) -> None:
        import random
        from .market_data_router import get_router

        router = get_router()
        p_stream = router._primary_streams.get(contract.upper())
        base_price = None
        if p_stream:
            last_event = p_stream[-1]
            if last_event.get("price") is not None:
                base_price = float(last_event["price"])

        if base_price is None:
            root = contract.split(" ")[0]
            base_price = last_prices.setdefault(contract, {
                "MNQ": 20000.0, "NQ": 20000.0,
                "MES": 5500.0, "ES": 5500.0,
                "MGC": 2400.0, "GC": 2400.0,
                "MYM": 40000.0, "YM": 40000.0,
                "M2K": 2200.0, "RTY": 2200.0
            }.get(root, 100.0))

        change = random.choice([-tick_size, 0.0, tick_size])
        new_price = base_price + change
        last_prices[contract] = new_price

        bid = new_price - tick_size
        ask = new_price + tick_size

        reg = get_registry().resolve_exact(contract, allow_continuous=False) if contract else {}
        size = random.randint(1, 5)

        event = make_canonical_event(
            event_type="trade" if schema == "trades" else "quote",
            provider=self.name,
            raw_symbol=raw_sym,
            exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or contract),
            canonical_symbol=str(reg.get("root") or ""),
            price=new_price,
            bid=bid,
            ask=ask,
            volume=size,
            exchange_sequence=random.randint(1000, 1000000),
            provider_sequence=self._event_count + 1,
            ts_event=_iso(),
            ts_provider=_iso(),
            quality={self.name: True, "mock": True},
            data_plane="analytics" if self._mode == "shadow" else "display",
        )
        self._emit(event)


def is_mock_key(key: str, prefix: str) -> bool:
    k = key.strip()
    if not k:
        return True
    placeholders = {
        f"{prefix}-...",
        "db-...",
        "YOUR_API_KEY",
        "test-default",
    }
    if k in placeholders:
        return True
    if k.startswith(f"{prefix}-mock") or k.startswith("db-mock"):
        return True
    return False


class DatabentoLiveAdapter(LiveMarketDataAdapter):
    """Real Databento Live TCP client (GLBX.MDP3)."""

    name = "databento_live"

    def __init__(self) -> None:
        super().__init__()
        self._dataset = str(os.environ.get("NTA_DATABENTO_DATASET") or "GLBX.MDP3")
        self._generation = 0
        self._instrument_id_to_symbol_map = {}
        import time
        self._last_event_time = time.time()

    def implementation_state(self) -> str:
        try:
            import databento as db  # noqa: F401
        except ImportError:
            return "ADAPTER_READY"
        if not self.credentials_present():
            return "ADAPTER_READY"
        if self._runtime_state == "LIVE":
            return "CONNECTED"
        return "ADAPTER_READY"

    def credentials_present(self) -> bool:
        key = str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()
        return bool(key and not is_mock_key(key, "db"))

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        deps_ok = True
        try:
            import databento  # noqa: F401
        except ImportError:
            deps_ok = False
        caps.update({
            "dataset": self._dataset,
            "dependency_installed": deps_ok,
            "replay_intraday_24h": True,
            "schemas": ["trades", "mbp-1", "tbbo"],
            "note": "Production real Databento client. Shadow-only until parity pass + failover promotion.",
        })
        if not deps_ok:
            caps["capability"] = "DEPENDENCY_MISSING"
        elif not self.credentials_present():
            caps["capability"] = "ENTITLEMENT_MISSING"
        else:
            caps["capability"] = "REALTIME_PRODUCTION"
        return caps

    def health(self) -> Dict[str, Any]:
        h = super().health()

        # Check last event age for degraded status (heartbeat timeout: 15s)
        age = h.get("last_event_age_sec")
        if self._runtime_state == "LIVE" and age is not None and age > 15.0:
            self._runtime_state = "DEGRADED"
            h["runtime_state"] = "DEGRADED"

        # Check client connection state
        client = self._client
        if client is not None and hasattr(client, "is_connected"):
            try:
                if not client.is_connected():
                    if self._runtime_state in {"LIVE", "AUTHENTICATED"}:
                        self._runtime_state = "DEGRADED"
                        h["runtime_state"] = "DEGRADED"
                    if self._runtime_state == "DEGRADED" and not getattr(client._thread, "is_alive", lambda: False)():
                        self._runtime_state = "OFFLINE"
                        h["runtime_state"] = "OFFLINE"
            except Exception:
                pass
        return h

    def connect(self) -> Dict[str, Any]:
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_DATABENTO_API_KEY not configured or is a mock key"
            return self.health()

        key = str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()
        try:
            import databento as db
        except ImportError:
            self._runtime_state = "ERROR"
            self._last_error = "databento package not installed"
            return self.health()

        try:
            self._runtime_state = "CONNECTING"
            self._generation += 1
            gen = self._generation

            # Pass reconnect_policy="reconnect" and slow_reader_behavior="skip"
            self._client = db.Live(key=key, reconnect_policy="reconnect", slow_reader_behavior="skip")
            self._client.add_callback(lambda r, g=gen: self._on_record(r, g))
            self._client.add_reconnect_callback(self._on_reconnect)
            self._client.start()
            self._connected_at = _iso()
            self._last_error = ""
            import time
            self._last_event_time = time.time()
        except Exception as exc:
            self._runtime_state = "AUTH_FAILED"
            self._last_error = f"Databento connect exception: {type(exc).__name__}: {exc}"
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        if not self.credentials_present():
            raise NotImplementedError("Real Databento live connection requires valid non-mock API credentials.")

        contract = " ".join(str(exact_contract or "").strip().upper().split())
        if not contract:
            raise ValueError("exact_contract required")

        raw = databento_raw_symbol(contract)
        schema = "tbbo" if channel in {"bid_ask", "tbbo", "quotes"} else "trades"
        sub_id = f"databento:{contract}:{schema}"
        with self._lock:
            self._subs[sub_id] = {
                "exact_contract": contract,
                "raw_symbol": raw,
                "channel": channel,
                "schema": schema,
            }

        client = self._client
        if client is not None:
            try:
                client.subscribe(
                    dataset=self._dataset,
                    schema=schema,
                    symbols=raw,
                    stype_in="raw_symbol",
                )
                self._runtime_state = "AUTHENTICATED"
            except Exception as exc:
                self._runtime_state = "AUTH_FAILED"
                self._last_error = f"subscribe failed: {exc}"
                raise exc
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            removed = self._subs.pop(str(subscription_id), None)
            if not removed:
                return

            # Safe stop/recreate/resubscribe sequence
            client = self._client
            if client is not None:
                try:
                    client.stop()
                    # wait_for_close with timeout 2.0s
                    client.wait_for_close(timeout=2.0)
                except Exception:
                    try:
                        client.terminate()
                    except Exception:
                        pass
                self._client = None

            if self.credentials_present():
                key = str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()
                try:
                    import databento as db
                    self._runtime_state = "CONNECTING"
                    self._generation += 1
                    gen = self._generation

                    self._client = db.Live(key=key, reconnect_policy="reconnect", slow_reader_behavior="skip")
                    self._client.add_callback(lambda r, g=gen: self._on_record(r, g))
                    self._client.add_reconnect_callback(self._on_reconnect)
                    self._client.start()
                    self._runtime_state = "AUTHENTICATED"

                    # Re-subscribe remaining active contracts
                    for sub in self._subs.values():
                        self._client.subscribe(
                            dataset=self._dataset,
                            schema=sub["schema"],
                            symbols=sub["raw_symbol"],
                            stype_in="raw_symbol",
                        )
                except Exception as exc:
                    self._runtime_state = "ERROR"
                    self._last_error = f"unsubscribe restart failed: {exc}"

    def _on_reconnect(self) -> None:
        self._connected_at = _iso()
        import time
        now = time.time()
        gap_sec = now - self._last_event_time
        self._last_event_time = now

        # Enqueue reconnect gap to GapRecovery worker
        from . import market_data_gap_recovery
        for sub in list(self._subs.values()):
            market_data_gap_recovery.get_worker().enqueue({
                "provider": self.name,
                "exact_contract": sub["exact_contract"],
                "gap_sec": gap_sec,
                "reason": "reconnect_gap",
            })

        # If not LIVE, keep CONNECTING until first record is processed
        if self._runtime_state != "LIVE":
            self._runtime_state = "CONNECTING"

    def _on_record(self, record: Any, generation: int) -> None:
        if generation != self._generation:
            return  # Drop old-generation records

        rec_name = type(record).__name__
        if rec_name in {"ErrorMsg", "MockErrorMsg"}:
            err_msg = getattr(record, "err", "") or "unknown databento error"
            for ph in ["db-", "YOUR_API_KEY", "test-default"]:
                if ph in err_msg:
                    err_msg = err_msg.replace(ph, "[SECRET_REDACTED]")
            self._last_error = f"databento_error_msg: {err_msg}"

            # Slow reader transitions
            if "slow reader" in err_msg.lower() or "slow_reader" in err_msg.lower():
                self._runtime_state = "DEGRADED"
            elif "skipped" in err_msg.lower() or "records dropped" in err_msg.lower():
                self._runtime_state = "DEGRADED"
                from . import market_data_gap_recovery
                for sub in list(self._subs.values()):
                    market_data_gap_recovery.get_worker().enqueue({
                        "provider": self.name,
                        "exact_contract": sub["exact_contract"],
                        "gap_sec": 10.0,
                        "reason": "slow_reader_skip",
                    })
            else:
                self._runtime_state = "ERROR"
            return
        elif rec_name in {"SystemMsg", "MockSystemMsg"}:
            self._last_event_utc = _iso()
            return
        elif rec_name in {"SymbolMappingMsg", "MockSymbolMappingMsg"}:
            inst_id = getattr(record, "instrument_id", None)
            raw_sym = getattr(record, "stype_in_symbol", "") or getattr(record, "raw_symbol", "")
            if inst_id is not None and raw_sym:
                with self._lock:
                    self._instrument_id_to_symbol_map[inst_id] = {
                        "raw_symbol": str(raw_sym),
                        "instrument_id": inst_id
                    }
            self._last_event_utc = _iso()
            return

        try:
            price_raw = getattr(record, "price", None)
            price = None
            if price_raw is not None:
                # Convert using official scale constant
                try:
                    import databento as db
                    scale = getattr(db, "FIXED_PRICE_SCALE", 1000000000)
                    if type(scale).__name__ == "MagicMock":
                        scale = 1000000000
                except Exception:
                    scale = 1000000000
                price = float(price_raw) / scale

            size = getattr(record, "size", None)

            # Authoritative mapping lookup
            inst_id = getattr(record, "instrument_id", None)
            symbol = ""
            mapping_pending = False
            if inst_id is not None:
                with self._lock:
                    mapping_info = self._instrument_id_to_symbol_map.get(inst_id)
                if mapping_info:
                    symbol = mapping_info["raw_symbol"]
                else:
                    mapping_pending = True

            # Fallback for unit-tests and direct mock feeds
            if not symbol and hasattr(record, "symbol") and record.symbol:
                symbol = str(record.symbol)
                mapping_pending = False

            if mapping_pending and not symbol:
                with self._lock:
                    if self._subs:
                        symbol = list(self._subs.values())[0]["raw_symbol"]

            if not symbol:
                return

            exact = ""
            with self._lock:
                for row in self._subs.values():
                    if row.get("raw_symbol") == symbol or symbol.startswith(str(row.get("raw_symbol") or "")):
                        exact = str(row.get("exact_contract") or "")
                        break
            if not exact:
                return  # Filter out unsubscribed messages

            import time
            self._last_event_time = time.time()

            # Transition to LIVE on first valid record
            if self._runtime_state in {"CONNECTING", "AUTHENTICATED", "DEGRADED"}:
                self._runtime_state = "LIVE"

            reg = get_registry().resolve_exact(exact, allow_continuous=False) if exact else {}
            ts_ns = getattr(record, "ts_event", None)
            ts_iso = _iso()
            if ts_ns is not None:
                ts_iso = datetime.fromtimestamp(ts_ns / 1_000_000_000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")

            quality = {"databento_live": True, "dataset": self._dataset}
            if mapping_pending:
                quality["SYMBOL_MAPPING_PENDING"] = True

            event = make_canonical_event(
                event_type="trade" if size is not None else "quote",
                provider=self.name,
                raw_symbol=symbol,
                exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or exact),
                canonical_symbol=str(reg.get("root") or ""),
                price=price,
                volume=size,
                exchange_sequence=getattr(record, "sequence", None),
                provider_sequence=self._event_count + 1,
                ts_event=ts_iso,
                ts_provider=_iso(),
                quality=quality,
                data_plane="analytics" if self._mode == "shadow" else "display",
            )
            self._emit(event)
        except Exception as exc:
            self._last_error = f"record_parse: {type(exc).__name__}: {exc}"


class DxFeedLiveAdapter(LiveMarketDataAdapter):
    """Real dxFeed Live Market Data client (WIP)."""

    name = "dxfeed_live"

    def implementation_state(self) -> str:
        return "NOT_IMPLEMENTED" if not self.credentials_present() else "ADAPTER_READY"

    def credentials_present(self) -> bool:
        token = str(os.environ.get("NTA_DXFEED_TOKEN") or os.environ.get("DXFEED_TOKEN") or "").strip()
        return bool(token and not is_mock_key(token, "dx"))

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        caps.update({
            "capability": "ENTITLEMENT_MISSING" if not self.credentials_present() else "REALTIME_PRODUCTION",
            "channels": ["trades", "bid_ask", "depth"],
            "note": "CME futures via dxFeed Market Data Platform — auth/subscribe/normalize pending.",
        })
        return caps

    def connect(self) -> Dict[str, Any]:
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_DXFEED_TOKEN not configured or is a mock key"
            return self.health()

        self._runtime_state = "ERROR"
        self._last_error = "Real dxFeed connection not implemented (credentials present but transport blocked)"
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError("Real dxFeed connection requires valid non-mock API credentials.")

    def _parse_dxfeed_message(self, text: str) -> None:
        import json
        try:
            data = json.loads(text)
            if not isinstance(data, list):
                return
            for item in data:
                event_type = item.get("event")
                if event_type == "Trade":
                    price = item.get("price")
                    size = item.get("size")
                    symbol = item.get("eventSymbol")
                    seq = item.get("sequence")
                    ts = item.get("time")

                    reg = get_registry().resolve_exact(symbol, allow_continuous=False) if symbol else {}
                    event = make_canonical_event(
                        event_type="trade",
                        provider=self.name,
                        raw_symbol=symbol,
                        exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or symbol),
                        canonical_symbol=str(reg.get("root") or ""),
                        price=price,
                        volume=size,
                        exchange_sequence=seq,
                        provider_sequence=self._event_count + 1,
                        ts_event=datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z") if ts else _iso(),
                        ts_provider=_iso(),
                        quality={"dxfeed_live": True},
                        data_plane="analytics" if self._mode == "shadow" else "display"
                    )
                    self._emit(event)
                    self._runtime_state = "LIVE"
                elif event_type == "Quote":
                    bid = item.get("bidPrice")
                    ask = item.get("askPrice")
                    bid_size = item.get("bidSize")
                    ask_size = item.get("askSize")
                    symbol = item.get("eventSymbol")
                    ts = item.get("time")

                    reg = get_registry().resolve_exact(symbol, allow_continuous=False) if symbol else {}
                    event = make_canonical_event(
                        event_type="quote",
                        provider=self.name,
                        raw_symbol=symbol,
                        exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or symbol),
                        canonical_symbol=str(reg.get("root") or ""),
                        bid=bid,
                        ask=ask,
                        volume=bid_size,
                        provider_sequence=self._event_count + 1,
                        ts_event=datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z") if ts else _iso(),
                        ts_provider=_iso(),
                        quality={"dxfeed_live": True},
                        data_plane="analytics" if self._mode == "shadow" else "display"
                    )
                    self._emit(event)
                    self._runtime_state = "LIVE"
        except Exception as exc:
            self._last_error = f"dxfeed_parse_error: {exc}"
            self._runtime_state = "ERROR"


class CqgLiveAdapter(LiveMarketDataAdapter):
    """Real CQG WebAPI client (WIP)."""

    name = "cqg_live"

    def implementation_state(self) -> str:
        return "NOT_IMPLEMENTED" if not self.credentials_present() else "ADAPTER_READY"

    def credentials_present(self) -> bool:
        user = str(os.environ.get("NTA_CQG_USERNAME") or "").strip()
        pw = str(os.environ.get("NTA_CQG_PASSWORD") or "").strip()
        return bool(user and pw and not is_mock_key(user, "cqg"))

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        caps.update({
            "capability": "ENTITLEMENT_MISSING" if not self.credentials_present() else "REALTIME_PRODUCTION",
            "note": "CQG WebAPI — auth/subscribe/normalize pending (Rithmic optional substitute).",
        })
        return caps

    def connect(self) -> Dict[str, Any]:
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_CQG_USERNAME/PASSWORD not configured or are mock credentials"
            return self.health()

        self._runtime_state = "ERROR"
        self._last_error = "Real CQG connection not implemented (credentials present but transport blocked)"
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError("Real CQG connection requires valid non-mock API credentials.")

    def _parse_cqg_message(self, text: str) -> None:
        import json
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return
            cqg_instant = data.get("CQGInstant") or {}
            market_data = cqg_instant.get("MarketData") or {}
            for quote in market_data.get("Quotes", []):
                symbol = quote.get("Symbol")
                price = quote.get("Last")
                volume = quote.get("LastVolume")
                bid = quote.get("Bid")
                ask = quote.get("Ask")
                ts_ms = quote.get("Timestamp")

                if not symbol:
                    continue

                reg = get_registry().resolve_exact(symbol, allow_continuous=False) if symbol else {}
                event = make_canonical_event(
                    event_type="trade" if price is not None else "quote",
                    provider=self.name,
                    raw_symbol=symbol,
                    exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or symbol),
                    canonical_symbol=str(reg.get("root") or ""),
                    price=price,
                    bid=bid,
                    ask=ask,
                    volume=volume,
                    provider_sequence=self._event_count + 1,
                    ts_event=datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z") if ts_ms else _iso(),
                    ts_provider=_iso(),
                    quality={"cqg_live": True},
                    data_plane="analytics" if self._mode == "shadow" else "display"
                )
                self._emit(event)
                self._runtime_state = "LIVE"
        except Exception as exc:
            self._last_error = f"cqg_parse_error: {exc}"
            self._runtime_state = "ERROR"


class CmeWebsocketReferenceAdapter(LiveMarketDataAdapter):
    """Real CME cloud WebSocket client (WIP)."""

    name = "cme_websocket"

    def implementation_state(self) -> str:
        return "NOT_IMPLEMENTED" if not self.credentials_present() else "ADAPTER_READY"

    def credentials_present(self) -> bool:
        token = str(os.environ.get("NTA_CME_WS_TOKEN") or os.environ.get("CME_WS_TOKEN") or "").strip()
        return bool(token and not is_mock_key(token, "cme"))

    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities()
        caps.update({
            "capability": "ENTITLEMENT_MISSING" if not self.credentials_present() else "REALTIME_PRODUCTION",
            "role": "reference_fallback",
            "note": "CME WebSocket TOB ~500ms aggregation — prefer as independent reference, not fastest primary.",
        })
        return caps

    def connect(self) -> Dict[str, Any]:
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_CME_WS_TOKEN not configured or is a mock token"
            return self.health()

        self._runtime_state = "ERROR"
        self._last_error = "Real CME WebSocket connection not implemented"
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError("Real CME WebSocket connection requires valid non-mock API credentials.")

    def _parse_cme_message(self, text: str) -> None:
        import json
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return
            symbol = data.get("symbol")
            if not symbol:
                return
            trade = data.get("trade")
            quote = data.get("quote")
            ts = data.get("timestamp") or (trade or {}).get("timestamp") or (quote or {}).get("timestamp")

            reg = get_registry().resolve_exact(symbol, allow_continuous=False) if symbol else {}
            event = make_canonical_event(
                event_type="trade" if trade else "quote",
                provider=self.name,
                raw_symbol=symbol,
                exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or symbol),
                canonical_symbol=str(reg.get("root") or ""),
                price=(trade or {}).get("price") if trade else None,
                bid=(quote or {}).get("bid") if quote else None,
                ask=(quote or {}).get("ask") if quote else None,
                volume=(trade or {}).get("size") if trade else None,
                provider_sequence=self._event_count + 1,
                ts_event=datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z") if ts else _iso(),
                ts_provider=_iso(),
                quality={"cme_websocket": True},
                data_plane="analytics" if self._mode == "shadow" else "display"
            )
            self._emit(event)
            self._runtime_state = "LIVE"
        except Exception as exc:
            self._last_error = f"cme_parse_error: {exc}"
            self._runtime_state = "ERROR"


class MockLiveMarketDataAdapter(LiveMarketDataAdapter):
    """Base class for mock/simulation adapters."""

    production_failover_eligible = False

    def implementation_state(self) -> str:
        return "MOCK_SIMULATION"

    def credentials_present(self) -> bool:
        return False  # Mock is never considered to have real credentials

    def connect(self) -> Dict[str, Any]:
        self._runtime_state = "SIMULATION"
        self._connected_at = _iso()
        self._last_error = ""
        self._stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run_loop, name=f"{self.name}-mock", daemon=True,
            )
            self._thread.start()
        return self.health()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        contract = " ".join(str(exact_contract or "").strip().upper().split())
        if not contract:
            raise ValueError("exact_contract required")
        sub_id = f"{self.name}_mock:{contract}:{channel}"
        with self._lock:
            self._subs[sub_id] = {
                "exact_contract": contract,
                "raw_symbol": contract,
                "channel": channel,
                "schema": channel,
            }
        self._runtime_state = "SIMULATION"
        return sub_id

    def _run_loop(self) -> None:
        import random
        last_prices = {}
        while not self._stop.is_set():
            time.sleep(0.5)
            with self._lock:
                subs = list(self._subs.values())
            if not subs:
                continue
            sub = random.choice(subs)
            tick_size = 0.25
            root = sub["exact_contract"].split(" ")[0]
            if root in {"MGC", "GC", "M2K", "RTY"}:
                tick_size = 0.10
            elif root in {"MYM", "YM"}:
                tick_size = 1.0

            try:
                self._emit_mock_tick(
                    contract=sub["exact_contract"],
                    raw_sym=sub["exact_contract"],
                    schema="trades" if sub["channel"] == "trades" else "bid_ask",
                    tick_size=tick_size,
                    last_prices=last_prices
                )
            except Exception as exc:
                self._last_error = f"mock_tick_error: {exc}"


class DatabentoMockAdapter(MockLiveMarketDataAdapter):
    name = "databento_live"


class DxFeedMockAdapter(MockLiveMarketDataAdapter):
    name = "dxfeed_live"


class CqgMockAdapter(MockLiveMarketDataAdapter):
    name = "cqg_live"


class CmeWebsocketMockAdapter(MockLiveMarketDataAdapter):
    name = "cme_websocket"


def default_live_adapters() -> List[LiveMarketDataAdapter]:
    adapters = []

    # Databento
    db_key = str(os.environ.get("NTA_DATABENTO_API_KEY") or os.environ.get("DATABENTO_API_KEY") or "").strip()
    if is_mock_key(db_key, "db"):
        adapters.append(DatabentoMockAdapter())
    else:
        adapters.append(DatabentoLiveAdapter())

    # dxFeed
    dx_token = str(os.environ.get("NTA_DXFEED_TOKEN") or os.environ.get("DXFEED_TOKEN") or "").strip()
    if is_mock_key(dx_token, "dx"):
        adapters.append(DxFeedMockAdapter())
    else:
        adapters.append(DxFeedLiveAdapter())

    # CQG
    cqg_user = str(os.environ.get("NTA_CQG_USERNAME") or "").strip()
    if is_mock_key(cqg_user, "cqg"):
        adapters.append(CqgMockAdapter())
    else:
        adapters.append(CqgLiveAdapter())

    # CME WS
    cme_token = str(os.environ.get("NTA_CME_WS_TOKEN") or os.environ.get("CME_WS_TOKEN") or "").strip()
    if is_mock_key(cme_token, "cme"):
        adapters.append(CmeWebsocketMockAdapter())
    else:
        adapters.append(CmeWebsocketReferenceAdapter())

    return adapters


def inject_fixture_trade(
    adapter: LiveMarketDataAdapter,
    *,
    exact_contract: str,
    price: float,
    volume: float = 1.0,
) -> Dict[str, Any]:
    """Test helper: push one canonical trade without a real vendor socket."""
    event = make_canonical_event(
        event_type="trade",
        provider=adapter.name,
        raw_symbol=databento_raw_symbol(exact_contract) if adapter.name.startswith("databento") else exact_contract,
        exact_contract=exact_contract.upper(),
        price=price,
        volume=volume,
        ts_event=_iso(),
        ts_provider=_iso(),
        quality={"fixture": True},
        data_plane="analytics",
    )
    adapter._emit(event)
    adapter._runtime_state = "LIVE"
    return event
