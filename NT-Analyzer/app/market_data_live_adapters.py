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
import json
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import local_secrets, runtime_env
from .canonical_event import make_canonical_event
from .instrument_registry import get_registry

EventSink = Callable[[Dict[str, Any]], None]

_CONTRACT_RE = re.compile(r"^([A-Z0-9]+)\s+(\d{2})-(\d{2})$")
_MONTH_CODE = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
_CODE_MONTH = {code: month for month, code in _MONTH_CODE.items()}


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _post_json(url: str, payload: Dict[str, Any], *, headers: Optional[Dict[str, str]] = None,
               timeout: float = 10.0) -> Dict[str, Any]:
    """POST JSON without adding a third-party dependency to the stdlib backend."""
    request = urllib.request.Request(
        str(url), data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **dict(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=float(timeout)) as response:
        raw = response.read().decode("utf-8")
    decoded = json.loads(raw or "{}")
    if not isinstance(decoded, dict):
        raise ValueError("JSON response must be an object")
    return decoded


def databento_raw_symbol(exact_contract: str) -> str:
    """Map NT-style ``MNQ 09-26`` → Databento raw ``MNQU6`` (1-digit year)."""
    raw = " ".join(str(exact_contract or "").strip().upper().split())
    match = _CONTRACT_RE.match(raw)
    if not match:
        raise ValueError(f"exact contract required, got {exact_contract!r}")
    root, mm, yy = match.group(1), int(match.group(2)), int(match.group(3))
    return f"{root}{_MONTH_CODE[mm]}{yy % 10}"


def topstep_exact_contract(root: str, item: Dict[str, Any]) -> str:
    """Translate a ProjectX contract id into the explicit NT contract form."""
    normalized_root = str(root or "").strip().upper()
    contract_id = str(item.get("id") or "").strip().upper()
    suffix = contract_id.rsplit(".", 1)[-1]
    match = re.fullmatch(r"([FGHJKMNQUVXZ])(\d{2})", suffix)
    if not normalized_root or not match:
        return normalized_root
    month = _CODE_MONTH.get(match.group(1))
    if month is None:
        return normalized_root
    return f"{normalized_root} {month:02d}-{int(match.group(2)):02d}"


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
            "note": "OPTIONAL_ENTERPRISE_PROVIDER | DISABLED_BY_DEFAULT | NOT_REQUIRED_FOR_MVP | NO PURCHASE APPROVED",
        })
        if not deps_ok:
            caps["capability"] = "DEPENDENCY_MISSING"
        else:
            caps["capability"] = "OPTIONAL_ENTERPRISE_PROVIDER"
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


class TopstepXProjectXAdapter(LiveMarketDataAdapter):
    """Read-only TopstepX / ProjectX market-data client.

    Remote use remains policy-blocked unless the deployment records both the
    remote-server and redistribution permissions required for that contour.
    """

    name = "topstep_live"

    def __init__(self) -> None:
        super().__init__()
        self._token = ""
        self._token_expires_at = 0.0
        self._loop = None
        self._ws_client = None
        self._contract_id_map = {}
        self._contract_symbol_map = {}
        self._resolved_exact_map = {}
        self._session_refresh_thread = None

    def implementation_state(self) -> str:
        if self._runtime_state == "LIVE":
            return "CONNECTED"
        return "ADAPTER_READY"

    @staticmethod
    def _flag(name: str, *, default: bool = False) -> bool:
        raw = str(os.environ.get(name) or "").strip().lower()
        if not raw:
            return bool(default)
        return raw in {"1", "true", "yes", "on"}

    @classmethod
    def settings(cls) -> Dict[str, Any]:
        """Return secret-free adapter configuration and policy state."""
        local_secrets.apply()
        username = str(
            os.environ.get("NTA_TOPSTEPX_USERNAME")
            or os.environ.get("NTA_TOPSTEP_USERNAME")
            or ""
        ).strip()
        api_key = str(
            os.environ.get("NTA_TOPSTEPX_API_KEY")
            or os.environ.get("NTA_TOPSTEP_API_KEY")
            or ""
        ).strip()
        requested = cls._flag("NTA_ENABLE_TOPSTEPX_MARKET_DATA", default=True)
        # Backward-compatible opt-in: an explicit old flag can still disable.
        if "NTA_ENABLE_TOPSTEPX_LIVE" in os.environ:
            requested = requested and cls._flag("NTA_ENABLE_TOPSTEPX_LIVE")
        remote = not runtime_env.is_development()
        remote_authorized = cls._flag("NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED")
        redistribution_authorized = cls._flag("NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED")
        policy_allowed = bool(
            not remote or (remote_authorized and redistribution_authorized)
        )
        mode = str(os.environ.get("NTA_TOPSTEPX_DATA_MODE") or "sim").strip().lower()
        if mode not in {"sim", "live"}:
            mode = "invalid"
        credentials_present = bool(
            username and api_key and not is_mock_key(api_key, "topstep")
        )
        blocking_reasons: List[str] = []
        if not username:
            blocking_reasons.append("topstepx_username_missing")
        if not api_key or is_mock_key(api_key, "topstep"):
            blocking_reasons.append("topstepx_api_key_missing")
        if mode == "invalid":
            blocking_reasons.append("topstepx_data_mode_invalid")
        if not requested:
            blocking_reasons.append("topstepx_market_data_disabled")
        if remote and not remote_authorized:
            blocking_reasons.append("remote_server_authorization_missing")
        if remote and not redistribution_authorized:
            blocking_reasons.append("market_data_redistribution_authorization_missing")
        return {
            "username": username,
            "api_key": api_key,
            "username_configured": bool(username),
            "api_key_configured": bool(api_key and not is_mock_key(api_key, "topstep")),
            "credentials_present": credentials_present,
            "requested": requested,
            "remote_environment": remote,
            "remote_server_authorized": remote_authorized,
            "redistribution_authorized": redistribution_authorized,
            "policy_allowed": policy_allowed,
            "data_mode": mode,
            "live_subscription": mode == "live",
            "blocking_reasons": blocking_reasons,
        }

    @staticmethod
    def enabled() -> bool:
        cfg = TopstepXProjectXAdapter.settings()
        return bool(
            cfg["requested"] and cfg["policy_allowed"]
            and cfg["data_mode"] != "invalid"
        )

    def credentials_present(self) -> bool:
        return bool(self.settings()["credentials_present"])

    def capabilities(self) -> Dict[str, Any]:
        cfg = self.settings()
        return {
            **super().capabilities(),
            "historical": True,
            "read_only": True,
            "trade_routing": False,
            "data_mode": cfg["data_mode"],
            "policy_allowed": cfg["policy_allowed"],
            "remote_environment": cfg["remote_environment"],
            "blocking_reasons": list(cfg["blocking_reasons"]),
        }

    def _authenticate(self, *, force: bool = False) -> bool:
        if not self.enabled():
            cfg = self.settings()
            self._runtime_state = "POLICY_BLOCKED" if not cfg["policy_allowed"] else "DISABLED"
            self._last_error = ",".join(cfg["blocking_reasons"]) or "TopstepX market data disabled"
            return False
        if not self.credentials_present():
            self._runtime_state = "ENTITLEMENT_MISSING"
            self._last_error = "NTA_TOPSTEPX_USERNAME or NTA_TOPSTEPX_API_KEY missing"
            return False
        if not force and self._token and self._token_expires_at > time.time() + 300:
            return True
        cfg = self.settings()
        try:
            self._runtime_state = "CONNECTING"
            data = _post_json(
                "https://api.topstepx.com/api/Auth/loginKey",
                {"userName": cfg["username"], "apiKey": cfg["api_key"]},
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            if not data.get("success") or not data.get("token"):
                raise ValueError(
                    f"Auth response unsuccessful: {data.get('errorMessage') or 'no token returned'}"
                )
            self._token = str(data["token"])
            self._token_expires_at = time.time() + 24 * 3600
            self._last_error = ""
            return True
        except Exception as exc:
            self._token = ""
            self._token_expires_at = 0.0
            self._runtime_state = "AUTH_FAILED"
            self._last_error = f"TopstepX login failed: {type(exc).__name__}"
            return False

    def connect(self) -> Dict[str, Any]:
        if not self._authenticate():
            return self.health()

        if self._thread is not None and self._thread.is_alive():
            return self.health()

        self._stop.clear()
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()

        return self.health()

    def _run_async_loop(self) -> None:
        import asyncio
        self._loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._websocket_worker())
        finally:
            self._loop.close()
            self._loop = None

    async def _websocket_worker(self) -> None:
        import websockets
        import json
        import asyncio

        backoff = 1.0
        while not self._stop.is_set():
            if not self._authenticate():
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            url = f"wss://rtc.topstepx.com/hubs/market?access_token={self._token}"
            try:
                async with websockets.connect(url) as ws:
                    self._ws_client = ws
                    await ws.send(json.dumps({"protocol": "json", "version": 1}) + "\x1e")
                    handshake_resp = await ws.recv()
                    handshake_parts = [part for part in str(handshake_resp).split("\x1e") if part]
                    if handshake_parts:
                        handshake = json.loads(handshake_parts[0])
                        if isinstance(handshake, dict) and handshake.get("error"):
                            raise ValueError(str(handshake.get("error")))
                    self._runtime_state = "AUTHENTICATED"
                    self._connected_at = _iso()
                    self._last_error = ""
                    backoff = 1.0

                    for sub in list(self._subs.values()):
                        await self._subscribe_ws(ws, sub["raw_symbol"])

                    while not self._stop.is_set():
                        if self._token_expires_at <= time.time() + 300:
                            break
                        try:
                            raw_data = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            parts = raw_data.split("\x1e")
                            for part in parts:
                                if not part:
                                    continue
                                msg = json.loads(part)
                                if msg.get("type") == 6:
                                    await ws.send('{"type":6}\x1e')
                                    continue
                                if msg.get("type") == 1:
                                    self._on_ws_message(
                                        msg.get("target"), msg.get("arguments", []),
                                    )
                        except asyncio.TimeoutError:
                            await ws.send('{"type":6}\x1e')
            except Exception as exc:
                # A websocket exception may echo its URL, which contains the
                # short-lived bearer token. Expose only the exception class.
                self._last_error = f"WS connection failed: {type(exc).__name__}"
                self._runtime_state = "DEGRADED"
            finally:
                self._ws_client = None
            if not self._stop.is_set():
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        contract = " ".join(str(exact_contract or "").strip().upper().split())
        if not contract:
            raise ValueError("exact_contract required")

        raw_symbol = self._resolve_topstep_symbol(contract)
        schema = "quotes" if channel in {"bid_ask", "quotes"} else "trades"
        sub_id = f"topstep:{contract}:{schema}"

        with self._lock:
            self._subs[sub_id] = {
                "exact_contract": contract,
                "raw_symbol": raw_symbol,
                "channel": channel,
                "schema": schema,
            }

        if self._ws_client is not None and self._loop is not None:
            import asyncio
            asyncio.run_coroutine_threadsafe(self._subscribe_ws(self._ws_client, raw_symbol), self._loop)
            self._runtime_state = "AUTHENTICATED"

        return sub_id

    async def _subscribe_ws(self, ws: Any, symbol: str) -> None:
        import json
        import uuid
        contract_id = self._contract_id_map.get(symbol)
        if not contract_id:
            raise ValueError(f"ProjectX contract id not resolved for {symbol}")
        inv_id_quotes = f"sub_quotes_{uuid.uuid4().hex[:6]}"
        inv_id_trades = f"sub_trades_{uuid.uuid4().hex[:6]}"

        msg_quotes = {
            "type": 1,
            "invocationId": inv_id_quotes,
            "target": "SubscribeContractQuotes",
            "arguments": [contract_id]
        }
        await ws.send(json.dumps(msg_quotes) + "\x1e")

        msg_trades = {
            "type": 1,
            "invocationId": inv_id_trades,
            "target": "SubscribeContractTrades",
            "arguments": [contract_id]
        }
        await ws.send(json.dumps(msg_trades) + "\x1e")

    def _resolve_topstep_symbol(self, contract: str) -> str:
        contract = " ".join(str(contract or "").strip().upper().split())
        with self._lock:
            if contract in self._contract_id_map:
                return self._contract_id_map[contract]

        root = contract.split(" ")[0]
        try:
            data = _post_json(
                "https://api.topstepx.com/api/Contract/search",
                {"searchText": root, "live": bool(self.settings()["live_subscription"])},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=5.0
            )
            rows = [
                item for item in data.get("contracts", data.get("available", []))
                if isinstance(item, dict)
            ]
            exact_requested = bool(_CONTRACT_RE.fullmatch(contract))
            expected_raw = databento_raw_symbol(contract) if exact_requested else ""

            def matches_root(item: Dict[str, Any]) -> bool:
                symbol_root = str(item.get("symbolId") or "").upper().rsplit(".", 1)[-1]
                provider_symbol = str(item.get("name") or item.get("symbol") or "").upper()
                return bool(
                    symbol_root == root
                    or re.fullmatch(
                        re.escape(root) + r"[FGHJKMNQUVXZ]\d{1,2}", provider_symbol,
                    )
                )

            matching = [item for item in rows if matches_root(item)]
            if exact_requested:
                matching = [
                    item for item in matching
                    if str(item.get("name") or item.get("symbol") or "").upper()
                    == expected_raw.upper()
                ]
            else:
                matching.sort(key=lambda item: not bool(item.get("activeContract")))

            if matching:
                item = matching[0]
                raw = str(item.get("name") or item.get("symbol") or "").upper()
                cid = str(item["id"])
                resolved_exact = contract if exact_requested else topstep_exact_contract(root, item)
                if not raw or not cid:
                    raise ValueError("ProjectX contract response is incomplete")
                with self._lock:
                    self._contract_id_map[contract] = raw
                    self._contract_id_map[raw] = cid
                    self._contract_symbol_map[cid] = resolved_exact
                    self._resolved_exact_map[contract] = resolved_exact
                    self._resolved_exact_map[raw] = resolved_exact
                return raw
        except Exception as exc:
            self._last_error = f"TopstepX contract search failed: {type(exc).__name__}"
            raise ValueError(self._last_error) from None
        self._last_error = f"TopstepX active/exact contract not found: {contract}"
        raise ValueError(self._last_error)

    def resolved_exact_contract(self, contract: str) -> str:
        normalized = " ".join(str(contract or "").strip().upper().split())
        with self._lock:
            return str(self._resolved_exact_map.get(normalized) or normalized)

    def _on_ws_message(self, target: str, args: List[Any]) -> None:
        # Official ProjectX callbacks are (contractId, data).  Accept the old
        # single-dict shape too so recorded fixtures remain replayable.
        rows: List[tuple[str, Dict[str, Any]]] = []
        if len(args) >= 2 and isinstance(args[1], dict):
            rows.append((str(args[0]), args[1]))
        else:
            rows.extend(("", arg) for arg in args if isinstance(arg, dict))
        for contract_id, arg in rows:
            if not arg:
                continue
            exact = self._contract_symbol_map.get(contract_id, "")
            symbol = str(arg.get("symbol") or arg.get("symbolId") or "")
            with self._lock:
                if not exact:
                    for sub in self._subs.values():
                        mapped_id = self._contract_id_map.get(sub["raw_symbol"])
                        if (symbol and sub["raw_symbol"] == symbol) or (
                            contract_id and mapped_id == contract_id
                        ):
                            exact = sub["exact_contract"]
                            symbol = symbol or sub["raw_symbol"]
                            break
            if not exact:
                continue
            symbol = symbol or contract_id

            price = arg.get("price")
            if price is None:
                price = arg.get("lastPrice")
            if price is None:
                price = arg.get("bestBid")
            if price is None:
                price = arg.get("bestAsk")
            size = arg.get("size")
            if size is None:
                size = arg.get("volume")

            if self._runtime_state in {"CONNECTING", "AUTHENTICATED", "DEGRADED"}:
                self._runtime_state = "LIVE"

            reg = get_registry().resolve_exact(exact, allow_continuous=False) if exact else {}
            target_lower = str(target or "").lower()
            is_trade = target_lower in {"gatewaytrade", "ontrade", "trade", "trades"}

            event = make_canonical_event(
                event_type="trade" if is_trade else "quote",
                provider=self.name,
                raw_symbol=symbol,
                exact_contract=str(reg.get("exact_contract") or reg.get("resolved") or exact),
                canonical_symbol=str(reg.get("root") or ""),
                price=float(price) if price is not None else None,
                volume=float(size) if size is not None else None,
                exchange_sequence=arg.get("sequence"),
                provider_sequence=self._event_count + 1,
                ts_event=arg.get("timestamp") or arg.get("lastUpdated") or arg.get("time") or _iso(),
                ts_provider=_iso(),
                quality={"topstep_live": True},
                data_plane="analytics" if self._mode == "shadow" else "display",
            )
            self._emit(event)

    def backfill(self, exact_contract: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        if not self._authenticate():
            return []
        unit = 2
        unit_num = 1
        tf = str(timeframe).lower()
        if "s" in tf:
            unit = 1
            unit_num = int(tf.replace("s", "") or 1)
        elif "m" in tf:
            unit = 2
            unit_num = int(tf.replace("m", "") or 1)
        elif "h" in tf:
            unit = 3
            unit_num = int(tf.replace("h", "") or 1)
        elif "d" in tf:
            unit = 4
            unit_num = int(tf.replace("d", "") or 1)

        raw_symbol = self._resolve_topstep_symbol(exact_contract)
        cid = self._contract_id_map.get(raw_symbol)
        if not cid:
            return []

        try:
            seconds_per_unit = {1: 1, 2: 60, 3: 3600, 4: 86400}.get(unit, 60)
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(
                seconds=max(1, unit_num) * seconds_per_unit * max(10, min(int(limit or 1), 20000)) * 2
            )
            data = _post_json(
                "https://api.topstepx.com/api/History/retrieveBars",
                {
                    "contractId": cid,
                    "unit": unit,
                    "unitNumber": unit_num,
                    "limit": min(limit, 20000),
                    "live": bool(self.settings()["live_subscription"]),
                    "startTime": start_time.isoformat().replace("+00:00", "Z"),
                    "endTime": end_time.isoformat().replace("+00:00", "Z"),
                    "includePartialBar": True,
                },
                headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
                timeout=10.0
            )

            bars = []
            for item in data.get("bars", []):
                bars.append({
                    "t": item.get("t") or item.get("time"),
                    "o": float(item.get("o") or item.get("open", 0.0)),
                    "h": float(item.get("h") or item.get("high", 0.0)),
                    "l": float(item.get("l") or item.get("low", 0.0)),
                    "c": float(item.get("c") or item.get("close", 0.0)),
                    "v": float(item.get("v") or item.get("volume", 0.0)),
                })
            return bars
        except Exception as exc:
            self._last_error = f"TopstepX retrieve bars failed: {type(exc).__name__}"
            return []


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

    # TopstepX (BYOMD user-owned connector adapter)
    adapters.append(TopstepXProjectXAdapter())

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
