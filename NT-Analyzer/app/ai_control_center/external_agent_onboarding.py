"""Onboarding application service; native registry/CAS port required.

No production storage, route or fake in-memory registry is installed here.
The composition owner wires this to the existing Agent World unit of work,
auth/device admission and secure_store after shared contract registration.
"""
from datetime import datetime, timezone
import json
import time
from uuid import UUID, uuid5

from .. import secure_store
from . import contracts as c
from .external_agent_contracts import ExternalAgentConnection
from .external_agent_protocol import A2AClient, CAPABILITIES, PROTOCOL, target
from .states import ContractError


NAMESPACE = UUID("2bcb64e4-0592-4fb1-9984-1c0aa397c462")


class ExternalAgentOnboarding:
    def __init__(self, *, repository, admit, policy, secrets=secure_store, client=None, validate_endpoint=target, synthetic_workspace=None):
        if not callable(admit) or not callable(policy):
            raise ContractError("external_agent_composition_required")
        self.repository, self.admit, self.policy = repository, admit, policy
        self.secrets, self.client, self.validate_endpoint = secrets, client or A2AClient(), validate_endpoint
        # Trusted test composition only, no payload switch or remote claim.
        self.synthetic_workspace = synthetic_workspace

    def _access(self, context, operation):
        if not isinstance(context, c.RequestContext) or context.scope.environment != c.Environment.DEVELOPMENT:
            raise ContractError("external_agent_environment_denied")
        if self.synthetic_workspace is not None and context.scope.workspace_id != self.synthetic_workspace:
            raise ContractError("external_agent_test_scope_denied")
        # Existing admission must reject Preview, missing capability, inactive
        # session/device/workspace and read-only writes on EVERY call.
        self.admit(context=context, operation=operation)

    def _get(self, context, identity):
        self._access(context, "read")
        row = self.repository.get_external_connection(context=context, connection_id=identity)
        if not isinstance(row, ExternalAgentConnection) or str(row.header.entity_id) != str(identity):
            raise ContractError("external_agent_not_found")
        row.require_owner(context)
        return row

    def _save(self, context, row, previous, key):
        self._access(context, "write")
        # Host contract: native CAS + immutable revision/event/outbox + replay
        # receipt in ONE existing UnitOfWork transaction. No side table here.
        return self.repository.commit_external_connection(context=context, connection=row,
            expected_revision=previous, idempotency_key=key)

    def create(self, *, context, payload, idempotency_key):
        self._access(context, "connect")
        fields = {"display_name", "protocol", "endpoint", "credential", "allowed_capabilities"}
        if type(payload) is not dict or set(payload) != fields:
            raise ContractError("external_agent_fields_invalid")
        c.require_token(idempotency_key, limit=120)
        if payload["protocol"] != PROTOCOL:
            raise ContractError("external_agent_protocol_unsupported")
        c.require_text(payload["display_name"], limit=80)
        credential = payload["credential"]
        if type(credential) is not str or not 8 <= len(credential) <= 4096 or any(ord(ch) < 33 or ord(ch) > 126 for ch in credential):
            raise ContractError("external_agent_credential_invalid")
        caps = payload["allowed_capabilities"]
        if type(caps) is not list or not caps or any(type(item) is not str for item in caps) or not set(caps) <= CAPABILITIES or len(set(caps)) != len(caps):
            raise ContractError("external_agent_capability_denied")
        if credential in json.dumps({k: v for k, v in payload.items() if k != "credential"}, ensure_ascii=False):
            raise ContractError("external_agent_credential_in_metadata")
        self.validate_endpoint(payload["endpoint"])
        identity = uuid5(NAMESPACE, f"{context.scope.environment.value}:{context.scope.workspace_id}:{context.user_uuid}:{idempotency_key}")
        key = "aw_external." + str(identity)
        old = self.repository.get_external_connection(context=context, connection_id=str(identity))
        if old is not None:
            old.require_owner(context)
            if (old.display_name != payload["display_name"] or old.endpoint != payload["endpoint"]
                    or old.protocol != payload["protocol"] or old.requested_capabilities != tuple(sorted(caps))
                    or self.secrets.get_secret(key) != credential):
                raise ContractError("external_agent_idempotency_conflict")
            return old.public()
        if not self.secrets.available():
            raise ContractError("external_agent_secure_storage_unavailable")
        prior = self.secrets.get_secret(key)
        if prior is not None and prior != credential:
            raise ContractError("external_agent_idempotency_conflict")
        if prior is None:
            self.secrets.set_secret(key, credential)
        now = datetime.now(timezone.utc)
        header = c.RecordHeader(entity_id=identity, scope=context.scope, owner_user_uuid=context.user_uuid, revision=1,
            created_at=now, updated_at=now, created_by=context.actor, correlation_id=identity, policy=self.policy(context))
        row = ExternalAgentConnection(header=header, display_name=payload["display_name"], protocol=PROTOCOL,
            endpoint=payload["endpoint"], credential=c.ExternalRef(authority=c.ExternalAuthority.CREDENTIAL, key=key, scope=context.scope),
            requested_capabilities=tuple(sorted(caps)), synthetic=self.synthetic_workspace is not None)
        return self._save(context, row, 0, idempotency_key).public()

    def verify(self, *, context, connection_id, expected_revision, idempotency_key):
        self._access(context, "verify")
        row = self._get(context, connection_id)
        if row.header.revision != expected_revision:
            raise ContractError("external_agent_revision_conflict")
        verifying = row.transition("verifying", now=datetime.now(timezone.utc))
        verifying = self._save(context, verifying, expected_revision, idempotency_key + ".begin")
        started = time.monotonic()
        try:
            proof = self.client.verify(row.endpoint, self.secrets.get_secret(row.credential.key),
                allowed=row.requested_capabilities, request_id=idempotency_key)
        except ContractError as error:
            current = self._get(context, connection_id)
            if current.header.revision == verifying.header.revision:
                failed = current.transition("degraded", now=datetime.now(timezone.utc), error=error.code)
                self._save(context, failed, current.header.revision, idempotency_key + ".failed")
            raise
        self._access(context, "verify")
        current = self._get(context, connection_id)
        if current.header.revision != verifying.header.revision:
            raise ContractError("external_agent_connection_changed")
        active = current.transition("active", now=datetime.now(timezone.utc), proof=proof,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)))
        return self._save(context, active, current.header.revision, idempotency_key + ".verified").public()

    def revoke(self, *, context, connection_id, expected_revision, idempotency_key):
        self._access(context, "revoke")
        row = self._get(context, connection_id)
        if row.status == "revoked":
            self._cleanup_credential(row)
            return row.public()
        if row.header.revision != expected_revision:
            raise ContractError("external_agent_revision_conflict")
        row = self._save(context, row.transition("revoked", now=datetime.now(timezone.utc)), expected_revision, idempotency_key)
        # Revoke first: no later task can use this connection even if deletion
        # fails. Remote cancellation needs an explicit host cleanup decision.
        self._cleanup_credential(row)
        return row.public()

    def _cleanup_credential(self, row):
        # Retryable local cleanup only. Never contact the remote agent using
        # revoked credentials, restore authority or write another revision.
        try:
            self.secrets.delete_secret(row.credential.key)
        except Exception:
            raise ContractError("external_agent_credential_cleanup_pending") from None

    def get(self, *, context, connection_id):
        return self._get(context, connection_id).public()
