"""External-agent values, separate from Persona, Role, Account and Model.

Native record-kind/codec registration belongs to the integration owner. These
values deliberately do not masquerade as a Model or create another registry.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from . import contracts as c
from .external_agent_protocol import CAPABILITIES, PROTOCOL, Handshake
from .states import ContractError


TRANSITIONS = {
    "draft": frozenset({"verifying", "disabled", "revoked"}),
    "verifying": frozenset({"active", "degraded", "disabled", "revoked"}),
    "active": frozenset({"verifying", "degraded", "disabled", "revoked"}),
    "degraded": frozenset({"verifying", "disabled", "revoked"}),
    "disabled": frozenset({"verifying", "revoked"}),
    "revoked": frozenset(),
}


@dataclass(frozen=True, kw_only=True)
class ExternalAgentConnection:
    header: c.RecordHeader
    display_name: str
    protocol: str
    endpoint: str
    credential: c.ExternalRef
    requested_capabilities: tuple[str, ...]
    status: str = "draft"
    advertised_capabilities: tuple[str, ...] = ()
    allowed_capabilities: tuple[str, ...] = ()
    last_verification: datetime | None = None
    card_sha256: str | None = None
    last_latency_ms: int | None = None
    last_error: str | None = None
    synthetic: bool = False

    def __post_init__(self):
        if not isinstance(self.header, c.RecordHeader):
            raise ContractError("external_agent_header_required")
        c.require_text(self.display_name, limit=80)
        c.require_text(self.endpoint, limit=350)
        if self.protocol != PROTOCOL:
            raise ContractError("external_agent_protocol_unsupported")
        c.require_external(self.credential, c.ExternalAuthority.CREDENTIAL)
        c.require_same_scope(self.header.scope, self.credential.scope)
        for values in (self.requested_capabilities, self.advertised_capabilities, self.allowed_capabilities):
            c.require_tuple(values, str)
            if len(values) > 32 or len(set(values)) != len(values):
                raise ContractError("external_agent_capability_invalid")
            for value in values:
                c.require_token(value, limit=128)
        if (not self.requested_capabilities or not set(self.requested_capabilities) <= CAPABILITIES
                or not set(self.allowed_capabilities) <= set(self.requested_capabilities) & set(self.advertised_capabilities)):
            raise ContractError("external_agent_capability_denied")
        if self.status not in TRANSITIONS or type(self.synthetic) is not bool:
            raise ContractError("external_agent_state_invalid")
        if self.last_verification is not None:
            c.require_utc(self.last_verification)
        if self.status == "active" and (not self.allowed_capabilities or not self.last_verification or not self.card_sha256):
            raise ContractError("external_agent_verification_required")
        if self.card_sha256 is not None:
            import re
            if not re.fullmatch(r"[0-9a-f]{64}", self.card_sha256):
                raise ContractError("external_agent_verification_invalid")
        if self.last_latency_ms is not None and (type(self.last_latency_ms) is not int or self.last_latency_ms < 0):
            raise ContractError("external_agent_latency_invalid")
        if self.last_error is not None:
            c.require_token(self.last_error, limit=80)
        if self.synthetic and self.header.scope.environment != c.Environment.DEVELOPMENT:
            raise ContractError("external_agent_test_environment_denied")

    def require_owner(self, context):
        c.require_same_scope(context.scope, self.header.scope)
        if context.user_uuid != self.header.owner_user_uuid:
            raise ContractError("external_agent_not_found")

    def transition(self, status, *, now, proof=None, latency_ms=None, error=None):
        if status not in TRANSITIONS[self.status]:
            raise ContractError("external_agent_transition_denied")
        c.require_utc(now)
        if now < self.header.updated_at:
            raise ContractError("external_agent_clock_invalid")
        fields = {}
        if status == "active":
            if not isinstance(proof, Handshake) or proof.protocol != self.protocol or not set(proof.allowed) <= set(self.requested_capabilities):
                raise ContractError("external_agent_verification_required")
            fields.update(advertised_capabilities=proof.advertised, allowed_capabilities=proof.allowed,
                          last_verification=now, card_sha256=proof.card_sha256, last_latency_ms=latency_ms, last_error=None)
        if status in {"degraded", "disabled", "revoked"}:
            fields.update(allowed_capabilities=(), last_error=error)
        return replace(self, header=replace(self.header, revision=self.header.revision + 1, updated_at=now),
                       status=status, **fields)

    def public(self):
        """Explicit allowlist: raw secrets and even storage key names stay server-side."""
        return {"id": str(self.header.entity_id), "workspace_id": self.header.scope.workspace_id,
            "revision": self.header.revision, "display_name": self.display_name, "protocol": self.protocol,
            "endpoint": self.endpoint, "credential_configured": True, "status": self.status,
            "advertised_capabilities": list(self.advertised_capabilities), "allowed_capabilities": list(self.allowed_capabilities),
            "availability": "available" if self.status == "active" else "unavailable",
            "verification_state": "verified" if self.status == "active" else self.status,
            "last_verification": self.last_verification.isoformat() if self.last_verification else None,
            "last_latency_ms": self.last_latency_ms, "last_error": self.last_error,
            "provenance": {"synthetic": self.synthetic, "card_sha256": self.card_sha256},
            "model": "unknown / externally managed", "model_id": None,
            "performance_scope": "external_agent", "real_benchmark_eligible": False}


def candidate(connection, *, context, role, capability):
    """Coordinator/Router seam. No role selection or new Router is implemented."""
    connection.require_owner(context)
    if not isinstance(role, c.AgentRole):
        raise ContractError("external_agent_role_required")
    c.require_same_scope(context.scope, role.header.scope)
    if role.header.owner_user_uuid != context.user_uuid:
        raise ContractError("external_agent_role_owner_denied")
    return (connection.status == "active" and role.status == "active"
        and role.autonomy_ceiling == c.Autonomy.ADVICE
        and "ai_pro_models" in role.capability_ceiling
        and capability in connection.allowed_capabilities)
