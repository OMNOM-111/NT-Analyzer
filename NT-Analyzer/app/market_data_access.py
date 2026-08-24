"""Fail-closed end-user authorization for live market-data delivery.

Product access and provider/exchange permission are deliberately separate.  A
trial may use the owner's shared read-only feed only when the two explicit
redistribution policy switches are enabled.  Otherwise a non-owner needs a
verified private provider entitlement or an online personal Connector.

The resolver is transport-neutral.  HTTP routes can use the same decision as
the browser WebSocket hub without exposing provider credentials to a browser.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional


OWNER_SHARED_SCOPE = "owner-shared"
DEFAULT_REVALIDATE_SECONDS = 5.0
_LIVE_STATES = frozenset({"CONNECTED", "DEGRADED", "LIVE", "ONLINE"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class MarketDataAccessDecision:
    """Immutable routing/authorization result for one subject and source."""

    allowed: bool
    reason: str
    source: str = "denied"
    sharing_scope: str = "none"
    scope_id: str = ""
    user_id: str = ""
    workspace_id: str = ""
    provider: str = ""
    account_id: str = ""
    expires_at_utc: str = ""
    revalidate_after_sec: float = DEFAULT_REVALIDATE_SECONDS
    connector: Any = field(default=None, repr=False, compare=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def to_public_dict(self) -> Dict[str, Any]:
        """Return browser-safe diagnostics (never credentials or raw subjects)."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "source": self.source,
            "sharing_scope": self.sharing_scope,
            "scope_hash": scope_hash(self.scope_id),
            "provider": self.provider,
            "expires_at_utc": self.expires_at_utc,
            "revalidate_after_sec": self.revalidate_after_sec,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> datetime:
    current = value or _utc_now()
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_utc(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _subject(context: Mapping[str, Any]) -> str:
    return str(context.get("user_uuid") or context.get("user_id") or "").strip()


def _identity_matches(row: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    row_uuid = str(row.get("user_uuid") or "").strip()
    context_uuid = str(context.get("user_uuid") or "").strip()
    if row_uuid and context_uuid:
        return row_uuid == context_uuid
    return str(row.get("user_id") or "").strip() == str(context.get("user_id") or "").strip()


def authenticated_subject(context: Optional[Mapping[str, Any]]) -> bool:
    """Whether a WS/HTTP context represents an authenticated subject/service."""
    ctx = context or {}
    return bool(
        _subject(ctx)
        # ``is_owner`` is set only by the server-side authentication layer;
        # it also covers the pre-bootstrap local owner and gateway service.
        or ctx.get("is_owner")
    )


def _digest_scope(*parts: Any) -> str:
    raw = "\x1f".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def private_scope_id(
    workspace_id: Any, user_id: Any, provider: Any, account_id: Any,
) -> str:
    return "private:" + _digest_scope(workspace_id, user_id, provider, account_id)


def workspace_scope_id(workspace_id: Any, installation_id: Any = "") -> str:
    return "workspace:" + _digest_scope(workspace_id, installation_id)


def scope_hash(scope_id: Any) -> str:
    value = str(scope_id or "")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else ""


def subject_hash(context: Optional[Mapping[str, Any]]) -> str:
    value = _subject(context or {})
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else "service"


def _flag(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in _TRUTHY


def _coerce_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUTHY


def redistribution_policy(
    policy_flags: Optional[Mapping[str, Any]] = None,
) -> Dict[str, bool]:
    flags = policy_flags or {}
    remote = (
        _coerce_flag(flags.get("remote_server_authorized"))
        if "remote_server_authorized" in flags
        else _flag("NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED")
    )
    redistribution = (
        _coerce_flag(flags.get("redistribution_authorized"))
        if "redistribution_authorized" in flags
        else _flag("NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED")
    )
    return {
        "remote_server_authorized": remote,
        "redistribution_authorized": redistribution,
        "shared_feed_allowed": bool(remote and redistribution),
    }


def _revalidate_delay(expires: Optional[datetime], now: datetime) -> float:
    if expires is None:
        return DEFAULT_REVALIDATE_SECONDS
    remaining = max(0.0, (expires - now).total_seconds())
    return max(0.1, min(DEFAULT_REVALIDATE_SECONDS, remaining))


def _denied(reason: str, context: Mapping[str, Any]) -> MarketDataAccessDecision:
    active = context.get("active_workspace")
    workspace = active if isinstance(active, Mapping) else {}
    return MarketDataAccessDecision(
        allowed=False,
        reason=reason,
        user_id=_subject(context),
        workspace_id=str(context.get("workspace_id") or workspace.get("workspace_id") or ""),
    )


def _default_subscription_lookup(user_id: Any) -> Mapping[str, Any]:
    from . import subscriptions

    try:
        return subscriptions.active_entitlement(user_id) or {}
    except Exception:
        return {}


def _entitlement_rows_from_context(context: Mapping[str, Any]) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    single = context.get("market_data_entitlement")
    if isinstance(single, Mapping):
        rows.append(dict(single))
    multiple = context.get("market_data_entitlements")
    if isinstance(multiple, list):
        rows.extend(dict(row) for row in multiple if isinstance(row, Mapping))
    return rows


def _default_owned_provider_probe(
    context: Mapping[str, Any], exact_contract: str, channel: str, now: datetime,
) -> Optional[Mapping[str, Any]]:
    rows = _entitlement_rows_from_context(context)
    try:
        from .market_data_entitlements import get_connector_registry

        registry = get_connector_registry()
        lock = getattr(registry, "_lock", None)
        if lock is not None:
            with lock:
                connectors = list(getattr(registry, "_instances", {}).values())
        else:
            connectors = []
        for connector in connectors:
            entitlement = getattr(connector, "entitlement", None)
            if entitlement is None:
                continue
            rows.append({
                "workspace_id": getattr(entitlement, "workspace_id", ""),
                "user_id": getattr(entitlement, "user_id", ""),
                "provider": getattr(entitlement, "provider", ""),
                "account_id": getattr(entitlement, "account_id", ""),
                "entitlement_type": getattr(entitlement, "entitlement_type", ""),
                "exchanges": getattr(entitlement, "exchanges", []),
                "channels": getattr(entitlement, "channels", []),
                "live_eligible": getattr(entitlement, "live_eligible", False),
                "expiration": getattr(entitlement, "expiration", ""),
                "sharing_scope": getattr(entitlement, "sharing_scope", ""),
                "API_access_enabled": getattr(entitlement, "API_access_enabled", False),
                "runtime_state": getattr(entitlement, "runtime_state", ""),
                "connector": connector,
            })
    except Exception:
        pass
    return next((row for row in rows if _owned_provider_row_valid(row, context, channel, now)), None)


def _owned_provider_row_valid(
    row: Mapping[str, Any], context: Mapping[str, Any], channel: str, now: datetime,
) -> bool:
    subject = _subject(context)
    active = context.get("active_workspace")
    workspace = active if isinstance(active, Mapping) else {}
    workspace_id = str(context.get("workspace_id") or workspace.get("workspace_id") or "")
    if not subject or not _identity_matches(row, context):
        return False
    if not workspace_id or str(row.get("workspace_id") or "") != workspace_id:
        return False
    if str(row.get("sharing_scope") or "private").lower() != "private":
        return False
    if not bool(row.get("live_eligible")):
        return False
    if not bool(row.get("API_access_enabled", row.get("api_access_enabled", False))):
        return False
    if str(row.get("runtime_state") or "").upper() not in _LIVE_STATES:
        return False
    if row.get("verified") is False:
        return False
    provider = str(row.get("provider") or "").strip().lower()
    account_id = str(row.get("account_id") or "").strip()
    if not provider or not account_id:
        return False
    channels = [str(value).lower() for value in (row.get("channels") or [])]
    if channels and str(channel or "trades").lower() not in channels:
        return False
    expires_text = row.get("expiration") or row.get("expires_at_utc")
    if expires_text:
        expires = _parse_utc(expires_text)
        if expires is None or expires <= now:
            return False
    return True


def _explicit_personal_connector(context: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    value = context.get("personal_connector")
    return dict(value) if isinstance(value, Mapping) else None


def _default_personal_connector_probe(
    context: Mapping[str, Any], exact_contract: str, channel: str, now: datetime,
) -> Optional[Mapping[str, Any]]:
    explicit = _explicit_personal_connector(context)
    if explicit is not None:
        return explicit
    active = context.get("active_workspace")
    workspace = active if isinstance(active, Mapping) else {}
    workspace_id = str(context.get("workspace_id") or workspace.get("workspace_id") or "")
    user_id = context.get("user_id")
    try:
        from . import connector_protocol

        rows = connector_protocol.list_installations(
            user_id, workspace_id=workspace_id,
        ).get("connections") or []
        online = [row for row in rows if isinstance(row, Mapping)]
        if online:
            return dict(online[0])
    except Exception:
        pass
    try:
        from . import workspaces

        rows = workspaces.list_connections(
            user_id, workspace_id=workspace_id,
        ).get("connections") or []
        online = [row for row in rows if isinstance(row, Mapping)]
        return dict(online[0]) if online else None
    except Exception:
        return None


def _personal_connector_row_valid(
    row: Mapping[str, Any], context: Mapping[str, Any], now: datetime,
) -> bool:
    active = context.get("active_workspace")
    workspace = active if isinstance(active, Mapping) else {}
    workspace_id = str(context.get("workspace_id") or workspace.get("workspace_id") or "")
    user_id = str(context.get("user_id") or "")
    if not user_id or not workspace_id:
        return False
    if bool(context.get("uses_owner_runtime") or workspace.get("uses_owner_runtime")):
        return False
    if str(workspace.get("kind") or "") not in {"personal", ""}:
        return False
    owner_id = str(workspace.get("owner_user_id") or "")
    if owner_id and owner_id != user_id:
        return False
    if str(row.get("workspace_id") or workspace_id) != workspace_id:
        return False
    row_owner = str(row.get("owner_user_id") or user_id)
    if row_owner and row_owner != user_id:
        return False
    if str(row.get("status") or "").lower() != "online":
        return False
    if row.get("revoked_at_utc"):
        return False
    capabilities = {str(value).lower() for value in (row.get("capabilities") or [])}
    if "live_read" not in capabilities:
        return False
    installation = str(row.get("installation_id") or row.get("connection_id") or "")
    if not installation:
        return False
    heartbeat_text = row.get("last_heartbeat_utc")
    heartbeat = _parse_utc(heartbeat_text)
    if heartbeat is None or (now - heartbeat).total_seconds() > 45:
        return False
    return True


def _trial_marker(entitlement: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    markers = {
        str(entitlement.get("status") or "").lower(),
        str(entitlement.get("source") or "").lower(),
        str(entitlement.get("provider") or "").lower(),
        str(
            entitlement.get("access_kind")
            or entitlement.get("entitlement_type")
            or entitlement.get("kind")
            or ""
        ).lower(),
        str(entitlement.get("plan_id") or "").lower(),
    }
    return bool(
        entitlement.get("is_trial")
        or context.get("market_data_shared_trial")
        or any("trial" in marker for marker in markers)
    )


def _active_shared_trial(
    entitlement: Mapping[str, Any], context: Mapping[str, Any], now: datetime,
) -> Optional[datetime]:
    if not entitlement or not _trial_marker(entitlement, context):
        return None
    if str(entitlement.get("status") or "").lower() not in {
        "active", "trial", "promo_grant", "manual",
    }:
        return None
    if entitlement.get("active") is False:
        return None
    if (entitlement.get("user_uuid") or entitlement.get("user_id")) and not _identity_matches(
        entitlement, context,
    ):
        return None
    expires = _parse_utc(entitlement.get("expires_at_utc"))
    # Shared trial grants are intentionally bounded. Missing/malformed expiry
    # cannot become an indefinite redistribution grant.
    if expires is None or expires <= now:
        return None
    capabilities = context.get("capabilities")
    caps = capabilities if isinstance(capabilities, Mapping) else {}
    if not bool(caps.get("charts_realtime")):
        return None
    return expires


def resolve_market_data_access(
    context: Optional[Mapping[str, Any]],
    *,
    exact_contract: str = "",
    timeframe: str = "*",
    channel: str = "trades",
    now: Optional[datetime] = None,
    subscription_lookup: Optional[Callable[[Any], Mapping[str, Any]]] = None,
    owned_provider_probe: Optional[
        Callable[[Mapping[str, Any], str, str, datetime], Optional[Mapping[str, Any]]]
    ] = None,
    personal_connector_probe: Optional[
        Callable[[Mapping[str, Any], str, str, datetime], Optional[Mapping[str, Any]]]
    ] = None,
    policy_flags: Optional[Mapping[str, Any]] = None,
) -> MarketDataAccessDecision:
    """Resolve one browser/API market-data request without implicit fallback.

    Probe callables are injectable for tests and authoritative storage adapters.
    They receive ``(context, exact_contract, channel, now_utc)`` and return a
    server-owned mapping or ``None``.  No value from a browser message is ever
    accepted as an entitlement.
    """
    del timeframe  # Reserved for provider-specific contract grants.
    ctx: Mapping[str, Any] = context or {}
    current = _as_utc(now)
    if not authenticated_subject(ctx):
        return _denied("authentication_required", ctx)

    subject = _subject(ctx)
    active = ctx.get("active_workspace")
    workspace = active if isinstance(active, Mapping) else {}
    workspace_id = str(ctx.get("workspace_id") or workspace.get("workspace_id") or "")
    if bool(ctx.get("is_owner")):
        return MarketDataAccessDecision(
            allowed=True,
            reason="owner_access",
            source="owner",
            sharing_scope="owner",
            scope_id=OWNER_SHARED_SCOPE,
            user_id=subject,
            workspace_id=workspace_id,
            provider="owner_runtime",
        )

    provider_probe = owned_provider_probe or _default_owned_provider_probe
    try:
        owned = provider_probe(ctx, str(exact_contract or "").upper(), channel, current)
    except Exception:
        owned = None
    if isinstance(owned, Mapping) and _owned_provider_row_valid(owned, ctx, channel, current):
        provider = str(owned.get("provider") or "").lower()
        account_id = str(owned.get("account_id") or "")
        expires_text = str(owned.get("expiration") or owned.get("expires_at_utc") or "")
        expires = _parse_utc(expires_text)
        return MarketDataAccessDecision(
            allowed=True,
            reason="verified_owned_provider",
            source="owned_provider",
            sharing_scope="private",
            scope_id=private_scope_id(workspace_id, subject, provider, account_id),
            user_id=subject,
            workspace_id=workspace_id,
            provider=provider,
            account_id=account_id,
            expires_at_utc=expires_text,
            revalidate_after_sec=_revalidate_delay(expires, current),
            connector=owned.get("connector"),
            metadata={"transport_managed": bool(owned.get("transport_managed"))},
        )

    connector_probe = personal_connector_probe or _default_personal_connector_probe
    try:
        connector = connector_probe(ctx, str(exact_contract or "").upper(), channel, current)
    except Exception:
        connector = None
    if isinstance(connector, Mapping) and _personal_connector_row_valid(connector, ctx, current):
        installation = str(
            connector.get("installation_id") or connector.get("connection_id") or ""
        )
        return MarketDataAccessDecision(
            allowed=True,
            reason="online_personal_connector",
            source="personal_connector",
            sharing_scope="workspace",
            scope_id=workspace_scope_id(workspace_id, installation),
            user_id=subject,
            workspace_id=workspace_id,
            provider="ninjatrader",
            account_id=installation,
            metadata={"installation_id": installation},
        )

    lookup = subscription_lookup or _default_subscription_lookup
    try:
        entitlement = lookup(ctx.get("user_id")) or {}
    except Exception:
        entitlement = {}
    expires = _active_shared_trial(entitlement, ctx, current)
    policy = redistribution_policy(policy_flags)
    if expires is not None and policy["shared_feed_allowed"]:
        return MarketDataAccessDecision(
            allowed=True,
            reason="authorized_shared_trial",
            source="shared_trial",
            sharing_scope="shared",
            scope_id=OWNER_SHARED_SCOPE,
            user_id=subject,
            workspace_id=workspace_id,
            provider="owner_runtime",
            expires_at_utc=str(entitlement.get("expires_at_utc") or ""),
            revalidate_after_sec=_revalidate_delay(expires, current),
        )
    if expires is not None:
        return _denied("redistribution_not_authorized", ctx)
    return _denied("market_data_entitlement_required", ctx)


def message_scope_id(message: Optional[Mapping[str, Any]]) -> str:
    """Derive the immutable source scope carried by a fan-out event."""
    msg = message or {}
    explicit = msg.get("market_data_scope")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if isinstance(explicit, Mapping):
        if explicit.get("scope_id"):
            return str(explicit.get("scope_id"))
        sharing = str(explicit.get("sharing_scope") or "").lower()
        if sharing == "private":
            return private_scope_id(
                explicit.get("workspace_id"),
                explicit.get("user_uuid") or explicit.get("user_id"),
                explicit.get("provider"),
                explicit.get("account_id"),
            )
        if sharing == "workspace":
            return workspace_scope_id(
                explicit.get("workspace_id"),
                explicit.get("installation_id") or explicit.get("connection_id"),
            )
        if sharing in {"owner", "shared"}:
            return OWNER_SHARED_SCOPE
    event = msg.get("event")
    row = event if isinstance(event, Mapping) else {}
    workspace_id = msg.get("workspace_id") or row.get("workspace_id")
    user_id = msg.get("user_uuid") or msg.get("user_id") or row.get("user_uuid") or row.get("user_id")
    provider = msg.get("provider") or row.get("provider")
    account_id = msg.get("account_id") or row.get("account_id")
    installation = msg.get("installation_id") or row.get("installation_id") or row.get("connection_id")
    if workspace_id and user_id and provider and account_id:
        return private_scope_id(workspace_id, user_id, provider, account_id)
    if workspace_id:
        return workspace_scope_id(workspace_id, installation)
    # Existing owner TopstepX/NinjaTrader events are intentionally unscoped.
    # They are never eligible for a private/workspace decision.
    return OWNER_SHARED_SCOPE


def decision_allows_message(
    decision: MarketDataAccessDecision, message: Optional[Mapping[str, Any]],
) -> bool:
    expires = _parse_utc(decision.expires_at_utc)
    if decision.expires_at_utc and (expires is None or expires <= _utc_now()):
        return False
    return bool(
        decision.allowed
        and decision.scope_id
        and decision.scope_id == message_scope_id(message)
    )
