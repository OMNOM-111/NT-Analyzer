"""User-Owned Market Data Entitlements and Connector Registry (BYOMD).

This module manages individual market data entitlements, secure credential storage via
DPAPI-backed secure_store, connector registrations, and per-user routing.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

from . import secure_store

logger = logging.getLogger("stratforge.market_data_entitlements")


@dataclass
class UserMarketDataEntitlement:
    workspace_id: str
    user_id: str
    provider: str  # 'ninjatrader', 'topstep', 'rithmic', 'cqg_tradovate'
    account_id: str
    entitlement_type: str = "demo"  # 'live', 'delayed', 'replay', 'demo'
    exchanges: List[str] = field(default_factory=lambda: ["CME"])
    channels: List[str] = field(default_factory=lambda: ["trades", "quotes"])
    live_eligible: bool = False
    expiration: str = ""  # ISO format UTC timestamp
    sharing_scope: str = "private"  # 'private', 'shared'
    API_access_enabled: bool = False
    credentials_ref: str = ""  # Key index in secure_store
    runtime_state: str = "DISABLED"

    def get_credential_key(self) -> str:
        """Returns the unique index key inside secure_store."""
        if not self.credentials_ref:
            self.credentials_ref = f"entitlement:{self.workspace_id}:{self.user_id}:{self.provider}:{self.account_id}"
        return self.credentials_ref

    def save_credentials(self, credentials: Dict[str, str]) -> None:
        """Saves credentials securely using DPAPI, never in plaintext database."""
        key = self.get_credential_key()
        serialized = json.dumps(credentials)
        secure_store.set_secret(key, serialized)

    def load_credentials(self) -> Dict[str, str]:
        """Loads credentials securely from DPAPI."""
        key = self.get_credential_key()
        raw = secure_store.get_secret(key)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception as exc:
            logger.error(f"Failed to parse decrypted credentials: {exc}")
            return {}

    def is_expired(self) -> bool:
        """Checks if the entitlement has expired based on expiration timestamp."""
        if not self.expiration:
            return False
        try:
            from datetime import datetime, timezone
            expire_dt = datetime.fromisoformat(self.expiration.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > expire_dt
        except Exception:
            # A malformed non-empty expiry must never make an entitlement look
            # valid.  Treat it as expired until an owner fixes the record.
            return True

    def health(self) -> Dict[str, Any]:
        """Returns health diagnostics, masking any sensitive credentials."""
        return {
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "provider": self.provider,
            "account_id": self.account_id,
            "entitlement_type": self.entitlement_type,
            "live_eligible": self.live_eligible and not self.is_expired(),
            "expired": self.is_expired(),
            "runtime_state": self.runtime_state if not self.is_expired() else "DISABLED",
            "credentials_present": bool(secure_store.get_secret(self.get_credential_key())),
        }


class UserMarketDataConnector:
    """Abstract connector representing a user-owned market data feed."""

    def __init__(self, entitlement: UserMarketDataEntitlement) -> None:
        self.entitlement = entitlement
        self._sink: Optional[type] = None
        self._lock = threading.RLock()

    def set_sink(self, sink: Any) -> None:
        self._sink = sink

    def connect(self) -> Dict[str, Any]:
        raise NotImplementedError()

    def disconnect(self) -> None:
        raise NotImplementedError()

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        raise NotImplementedError()

    def unsubscribe(self, subscription_id: str) -> None:
        raise NotImplementedError()

    def backfill(self, exact_contract: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        raise NotImplementedError()

    def health(self) -> Dict[str, Any]:
        raise NotImplementedError()

    def authenticate(self) -> bool:
        raise NotImplementedError()


class ConnectorRegistry:
    """Registry containing all connector definitions and active user-owned instances."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._types: Dict[str, Type[UserMarketDataConnector]] = {}
        self._instances: Dict[str, UserMarketDataConnector] = {}

    def register_type(self, provider: str, connector_cls: Type[UserMarketDataConnector]) -> None:
        with self._lock:
            self._types[provider.lower()] = connector_cls

    def create_connector(self, entitlement: UserMarketDataEntitlement) -> UserMarketDataConnector:
        provider = entitlement.provider.lower()
        with self._lock:
            connector_cls = self._types.get(provider)
            if not connector_cls:
                raise ValueError(f"No connector registered for provider: {provider}")
            instance_key = f"{entitlement.workspace_id}:{entitlement.user_id}:{provider}:{entitlement.account_id}"
            conn = connector_cls(entitlement)
            self._instances[instance_key] = conn
            return conn

    def get_connector(self, workspace_id: str, user_id: str, provider: str, account_id: str) -> Optional[UserMarketDataConnector]:
        instance_key = f"{workspace_id}:{user_id}:{provider.lower()}:{account_id}"
        with self._lock:
            return self._instances.get(instance_key)

    def remove_connector(self, workspace_id: str, user_id: str, provider: str, account_id: str) -> None:
        instance_key = f"{workspace_id}:{user_id}:{provider.lower()}:{account_id}"
        with self._lock:
            conn = self._instances.pop(instance_key, None)
            if conn:
                try:
                    conn.disconnect()
                except Exception:
                    pass


_REGISTRY = ConnectorRegistry()


class NinjaTraderLocalConnector(UserMarketDataConnector):
    """Phase 1: NinjaTrader per-user local bridge connector."""

    def connect(self) -> Dict[str, Any]:
        with self._lock:
            try:
                from . import market_data_ipc
                ipc = market_data_ipc.metrics()
                is_active = bool(
                    int(ipc.get("connections") or 0) > 0
                    and str(ipc.get("state") or "").upper() in {"CONNECTED", "LIVE", "DEGRADED"}
                )
            except Exception:
                is_active = False

            if is_active:
                self.entitlement.runtime_state = "LIVE"
            else:
                self.entitlement.runtime_state = "ERROR"
            return self.health()

    def disconnect(self) -> None:
        with self._lock:
            self.entitlement.runtime_state = "DISABLED"

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        return f"nt_local:{exact_contract}:{channel}"

    def unsubscribe(self, subscription_id: str) -> None:
        pass

    def backfill(self, exact_contract: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        return []

    def health(self) -> Dict[str, Any]:
        h = self.entitlement.health()
        h.update({
            "connection_type": "localhost_loopback",
            "active_port": 18765,
            "probe": "authenticated_market_data_ipc",
        })
        return h

    def authenticate(self) -> bool:
        return True


class TopstepXConnector(UserMarketDataConnector):
    """Phase 2 configuration prototype; it does not prove vendor auth."""

    def connect(self) -> Dict[str, Any]:
        with self._lock:
            creds = self.entitlement.load_credentials()
            if not creds.get("username") or not creds.get("api_key"):
                self.entitlement.runtime_state = "ERROR"
                return self.health()
            self.entitlement.runtime_state = "CONFIGURED_UNVERIFIED"
            return self.health()

    def disconnect(self) -> None:
        self.entitlement.runtime_state = "DISABLED"

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        return f"topstep:{exact_contract}:{channel}"

    def unsubscribe(self, subscription_id: str) -> None:
        pass

    def backfill(self, exact_contract: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        return []

    def health(self) -> Dict[str, Any]:
        return self.entitlement.health()

    def authenticate(self) -> bool:
        creds = self.entitlement.load_credentials()
        return bool(creds.get("username") and creds.get("api_key"))


class RithmicConnector(UserMarketDataConnector):
    """Phase 3 credential schema only; no Rithmic session is implemented."""

    def connect(self) -> Dict[str, Any]:
        with self._lock:
            creds = self.entitlement.load_credentials()
            if not creds.get("username") or not creds.get("password") or not creds.get("firm"):
                self.entitlement.runtime_state = "ERROR"
                return self.health()
            self.entitlement.runtime_state = "CONFIGURED_UNVERIFIED"
            return self.health()

    def disconnect(self) -> None:
        self.entitlement.runtime_state = "DISABLED"

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        return f"rithmic:{exact_contract}:{channel}"

    def unsubscribe(self, subscription_id: str) -> None:
        pass

    def backfill(self, exact_contract: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        return []

    def health(self) -> Dict[str, Any]:
        return self.entitlement.health()

    def authenticate(self) -> bool:
        creds = self.entitlement.load_credentials()
        return bool(creds.get("username") and creds.get("password") and creds.get("firm"))


class CQGTradovateConnector(UserMarketDataConnector):
    """Phase 4 credential schema only; no vendor session is implemented."""

    def connect(self) -> Dict[str, Any]:
        with self._lock:
            creds = self.entitlement.load_credentials()
            if not creds.get("username") or not creds.get("password"):
                self.entitlement.runtime_state = "ERROR"
                return self.health()
            self.entitlement.runtime_state = "CONFIGURED_UNVERIFIED"
            return self.health()

    def disconnect(self) -> None:
        self.entitlement.runtime_state = "DISABLED"

    def subscribe(self, exact_contract: str, channel: str = "trades") -> str:
        return f"cqg_tradovate:{exact_contract}:{channel}"

    def unsubscribe(self, subscription_id: str) -> None:
        pass

    def backfill(self, exact_contract: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        return []

    def health(self) -> Dict[str, Any]:
        return self.entitlement.health()

    def authenticate(self) -> bool:
        creds = self.entitlement.load_credentials()
        return bool(creds.get("username") and creds.get("password"))


_REGISTRY.register_type("ninjatrader", NinjaTraderLocalConnector)
_REGISTRY.register_type("topstep", TopstepXConnector)
_REGISTRY.register_type("rithmic", RithmicConnector)
_REGISTRY.register_type("cqg_tradovate", CQGTradovateConnector)


def get_connector_registry() -> ConnectorRegistry:
    return _REGISTRY
