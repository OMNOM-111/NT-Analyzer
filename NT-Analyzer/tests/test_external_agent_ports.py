"""Isolated service/authority ports, NOT native registry/Coordinator E2E.

The test store and admission doubles cannot be shipped as composition. Actual
HTTP handshake and task exchange use the separate deterministic test agent.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.external_agent_adapter import ExternalAgentAdapter
from app.ai_control_center.external_agent_onboarding import ExternalAgentOnboarding
from app.ai_control_center.model_evaluation import prepare
from app.ai_control_center.states import ContractError
from tests.test_external_agent_protocol import agent, connection, CAP, ENDPOINT, KEY


class TestOnlyStore:
    __test__ = False
    def __init__(self): self.records, self.history = {}, []
    def get_external_connection(self, *, context, connection_id):
        row = self.records.get(str(connection_id))
        if row is not None: row.require_owner(context)
        return row
    def commit_external_connection(self, *, context, connection, expected_revision, idempotency_key):
        connection.require_owner(context)
        old = self.get_external_connection(context=context, connection_id=connection.header.entity_id)
        if (old.header.revision if old else 0) != expected_revision:
            raise ContractError("external_agent_revision_conflict")
        assert connection.header.revision == expected_revision + 1
        self.records[str(connection.header.entity_id)] = connection
        self.history.append(connection)
        return connection


class TestOnlySecrets:
    __test__ = False
    def __init__(self): self.values = {}
    def available(self): return True
    def get_secret(self, key): return self.values.get(key)
    def set_secret(self, key, value): self.values[key] = value
    def delete_secret(self, key): self.values.pop(key, None)


def setup(client):
    row, context, role = connection()
    store, secrets = TestOnlyStore(), TestOnlySecrets()
    live = {"allowed": True}
    def admit(**kw):
        if not live["allowed"]: raise ContractError("external_agent_admission_denied")
    service = ExternalAgentOnboarding(repository=store, admit=admit, policy=lambda ctx: row.header.policy,
        secrets=secrets, client=client, validate_endpoint=lambda endpoint: endpoint == ENDPOINT,
        synthetic_workspace=context.scope.workspace_id)
    payload = dict(display_name="External agent fixture", protocol=row.protocol, endpoint=ENDPOINT,
        credential=KEY, allowed_capabilities=[CAP])
    return service, store, secrets, context, role, payload, live, admit


def create_active(parts):
    service, _, _, context, _, payload, _, _ = parts
    new = service.create(context=context, payload=payload, idempotency_key="create-one")
    verified = service.verify(context=context, connection_id=new["id"], expected_revision=1, idempotency_key="verify-one")
    assert verified["status"] == "active" and verified["revision"] == 3
    return verified


def test_onboarding_real_handshake_cas_revoke_without_returning_secret(agent):
    parts = setup(agent[0]); service, store, secrets, context, _, payload, _, _ = parts
    verified = create_active(parts)
    assert verified["provenance"]["synthetic"] is True
    assert verified["model_id"] is None and not verified["real_benchmark_eligible"]
    assert [row.status for row in store.history] == ["draft", "verifying", "active"]
    assert "credential" not in verified and KEY not in str(verified)
    assert service.create(context=context, payload=payload, idempotency_key="create-one")["id"] == verified["id"]
    assert len(store.history) == 3
    revoked = service.revoke(context=context, connection_id=verified["id"], expected_revision=3, idempotency_key="revoke-one")
    assert revoked["status"] == "revoked" and revoked["allowed_capabilities"] == []
    assert not secrets.values and len(store.history) == 4
    with pytest.raises(ContractError, match="transition_denied"):
        service.verify(context=context, connection_id=verified["id"], expected_revision=4, idempotency_key="reverify")


@pytest.mark.parametrize("field,value", [("verified", True), ("status", "active"), ("synthetic", False), ("workspace_id", "ws_other_tenant"), ("model_id", "guessed-model")])
def test_onboarding_body_cannot_set_state_scope_provenance_or_model(agent, field, value):
    service, store, secrets, context, _, payload, _, _ = setup(agent[0])
    with pytest.raises(ContractError, match="fields_invalid"):
        service.create(context=context, payload={**payload, field: value}, idempotency_key="bad-body")
    assert not store.records and not secrets.values


def test_revoke_during_handshake_is_not_undone_by_late_success(agent):
    parts = setup(agent[0]); service, store, _, context, _, payload, _, _ = parts
    row = service.create(context=context, payload=payload, idempotency_key="create-race")
    original = service.client.verify
    def verify(*a, **kw):
        proof = original(*a, **kw)
        service.revoke(context=context, connection_id=row["id"], expected_revision=2, idempotency_key="revoke-race")
        return proof
    service.client.verify = verify
    with pytest.raises(ContractError, match="connection_changed"):
        service.verify(context=context, connection_id=row["id"], expected_revision=1, idempotency_key="verify-race")
    assert store.records[row["id"]].status == "revoked"


def execution(parts):
    service, store, secrets, context, role, _, live, admit = parts
    row = create_active(parts)
    now = datetime.now(timezone.utc)
    intent = c.Intent(header=replace(role.header, entity_id=uuid4()), status="ready", goal=role.header.policy,
        acceptance=role.header.policy, risk=c.Risk.LOW, autonomy=c.Autonomy.ADVICE,
        budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET, key="existing-budget", scope=context.scope), deadline=now + timedelta(minutes=1))
    task = c.Task(header=replace(role.header, entity_id=uuid4()), status="ready", intent=intent.ref(), role=role.ref())
    binding = {"connection_id": row["id"], "connection_revision": row["revision"], "spec": prepare("json_arithmetic", "[3,6,9]")}
    claims = set()
    def claim(**kw):
        identity = str(kw["task"].header.entity_id)
        if identity in claims: return False
        claims.add(identity); return True
    adapter = ExternalAgentAdapter(load_connection=store.get_external_connection, load_task_binding=lambda **kw: binding,
        claim_dispatch=claim, read_secret=secrets.get_secret, admit=admit,
        reserve_budget=lambda **kw: {"ok": True, "reservation_id": "existing-reservation-test-double"}, client=service.client)
    args = dict(context=context, connection_id=row["id"], task=task, intent=intent, role=role,
                capability=CAP, values=[3, 6, 9], request_id="dispatch-one")
    return adapter, args, binding, live, row


def test_revoke_cleanup_failure_stays_revoked_and_retry_removes_secret(agent):
    parts = setup(agent[0]); service, store, secrets, context, *_ = parts
    row = create_active(parts)
    original = secrets.delete_secret
    def fail(key): raise OSError(KEY)
    secrets.delete_secret = fail
    with pytest.raises(ContractError, match="credential_cleanup_pending") as error:
        service.revoke(context=context, connection_id=row["id"], expected_revision=3, idempotency_key="cleanup")
    assert KEY not in str(error.value)
    assert store.records[row["id"]].status == "revoked"
    assert secrets.values
    secrets.delete_secret = original
    before = len(agent[2])
    result = service.revoke(context=context, connection_id=row["id"], expected_revision=3, idempotency_key="cleanup")
    assert result["status"] == "revoked" and not secrets.values
    assert len(store.history) == 4 and len(agent[2]) == before


@pytest.mark.parametrize("phase", ["claim", "secret"])
def test_revoke_during_dispatch_preparation_never_sends(agent, phase):
    parts = setup(agent[0]); adapter, args, _, _, row = execution(parts)
    def revoke():
        parts[0].revoke(context=args["context"], connection_id=row["id"], expected_revision=3, idempotency_key="pre-send-revoke")
    if phase == "claim":
        original = adapter.claim_dispatch
        def claim(**kw):
            result = original(**kw); revoke(); return result
        adapter.claim_dispatch = claim
    else:
        original = adapter.read_secret
        def read(key):
            result = original(key); revoke(); return result
        adapter.read_secret = read
    before = len(agent[2])
    with pytest.raises(ContractError): adapter.send(**args)
    assert len(agent[2]) == before


def test_unknown_dispatch_outcome_does_not_allow_automatic_resend(agent):
    parts = setup(agent[0]); adapter, args, _, _, _ = execution(parts)
    calls = []
    def unknown(*a, **kw):
        calls.append(kw); raise ContractError("external_agent_outcome_unknown")
    adapter.client.send = unknown
    with pytest.raises(ContractError, match="outcome_unknown"): adapter.send(**args)
    with pytest.raises(ContractError, match="dispatch_already_claimed"): adapter.send(**args)
    assert len(calls) == 1


def test_guarded_adapter_checks_result_not_model_quality_and_prevents_resend(agent):
    parts = setup(agent[0]); adapter, args, binding, _, row = execution(parts)
    sent = adapter.send(**args)
    assert sent.remote.state == "working" and sent.verification is None
    binding["remote_task_id"] = sent.remote.task_id
    completed = adapter.poll(**{**args, "request_id": "poll-one"}, remote=sent.remote, connection_revision=row["revision"])
    assert completed.verification["passed"] and completed.verification["synthetic"]
    assert completed.model_id is None and completed.performance_scope == "external_agent"
    assert completed.verification["model_performance_effect"] == "none"
    assert completed.verification["requires_human_review"]
    before = len(agent[2])
    with pytest.raises(ContractError, match="dispatch_already_claimed"):
        adapter.send(**args)
    assert len(agent[2]) == before


@pytest.mark.parametrize("mode", ["cancel", "foreign_id", "revoked", "admission", "completed"])
def test_adapter_cancel_is_bound_and_never_assumes_remote_stopped(agent, mode):
    parts = setup(agent[0]); adapter, args, binding, live, row = execution(parts)
    sent = adapter.send(**args)
    binding["remote_task_id"] = sent.remote.task_id
    remote = sent.remote
    if mode == "foreign_id":
        remote = replace(remote, task_id="foreign-task")
    elif mode == "revoked":
        parts[0].revoke(context=args["context"], connection_id=row["id"], expected_revision=3, idempotency_key="revoke-cancel")
    elif mode == "admission":
        live["allowed"] = False
    elif mode == "completed":
        adapter.poll(**args, remote=remote, connection_revision=3)
    before = len(agent[2])
    if mode in {"foreign_id", "revoked", "admission"}:
        with pytest.raises(ContractError):
            adapter.cancel(**args, remote=remote, connection_revision=3)
        assert len(agent[2]) == before
    else:
        result = adapter.cancel(**args, remote=remote, connection_revision=3)
        assert result.remote.state == ("completed" if mode == "completed" else "canceled")
        assert result.verification is None
        observed = adapter.poll(**args, remote=remote, connection_revision=3)
        assert observed.remote.state == result.remote.state
        if mode == "cancel":
            assert observed.verification is None


@pytest.mark.parametrize("failure", ["budget", "admission", "revoked", "spec", "capability", "timeout", "late-revoke"])
def test_worker_step_refuses_without_new_authority_or_silent_retry(agent, failure):
    parts = setup(agent[0]); adapter, args, binding, live, row = execution(parts)
    service, store, _, context, *_ = parts
    if failure == "budget": adapter.reserve_budget = lambda **kw: {"ok": False}
    elif failure == "admission": live["allowed"] = False
    elif failure == "revoked": service.revoke(context=context, connection_id=row["id"], expected_revision=3, idempotency_key="revoke-before")
    elif failure == "spec": args["values"] = [9, 9, 9]
    elif failure == "capability": args["capability"] = "trading.execute"
    elif failure == "timeout":
        def interrupted(*a, **kw): raise ContractError("external_agent_outcome_unknown")
        adapter.client.send = interrupted
    else:
        original = adapter.client.send
        def late(*a, **kw):
            result = original(*a, **kw)
            service.revoke(context=context, connection_id=row["id"], expected_revision=3, idempotency_key="revoke-late")
            return result
        adapter.client.send = late
    before = len(agent[2])
    with pytest.raises(ContractError): adapter.send(**args)
    assert len(agent[2]) == before + (1 if failure == "late-revoke" else 0)
