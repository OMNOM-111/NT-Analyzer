"""Native SQLite lifecycle/lock evidence, no provider or working Local data."""
from dataclasses import replace
import multiprocessing

import pytest

from app.ai_control_center.external_agent_repository import NativeExternalRepository
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError
from tests.test_external_agent_protocol import agent, connection, KEY
from tests.test_external_agent_ports import setup, create_active


def _attempt_guard(path, context, identity, output):
    port = NativeExternalRepository(SQLiteAgentWorldRepository(path))
    try:
        with port.guard(context, identity, timeout=0.2):
            output.put("acquired")
    except ContractError as error:
        output.put(error.code)


def test_native_record_commit_replay_scope_and_process_guard(tmp_path):
    row, context, _ = connection()
    repo = SQLiteAgentWorldRepository(tmp_path / "native.sqlite")
    policy = repo.put_artifact(context=context, content=b'{}', media_type="application/json")
    row = replace(row, header=replace(row.header, revision=1, policy=policy), status="draft",
                  allowed_capabilities=(), last_verification=None, card_sha256=None)
    port = NativeExternalRepository(repo)
    result = port.commit_external_connection(context=context, connection=row, expected_revision=0, idempotency_key="create-native")
    assert result == row
    assert port.commit_external_connection(context=context, connection=row, expected_revision=0, idempotency_key="create-native") == row
    assert port.get_external_connection(context=context, connection_id=row.header.entity_id) == row
    output = multiprocessing.get_context("spawn").Queue()
    with port.guard(context, row.header.entity_id):
        process = multiprocessing.get_context("spawn").Process(target=_attempt_guard,
            args=(str(repo.path), context, row.header.entity_id, output))
        process.start(); process.join(15)
        assert not process.is_alive()
        assert output.get(timeout=2) == "external_agent_connection_busy"
    with port.guard(context, row.header.entity_id, timeout=0.2):
        pass


def test_rotation_disables_old_revision_and_requires_handshake(agent):
    parts = setup(agent[0]); service, store, secrets, context, _, _, _, _ = parts
    active = create_active(parts)
    old = store.records[active["id"]]
    rotated = service.rotate_credential(context=context, connection_id=active["id"], expected_revision=3,
        credential="different-invalid-test-key", idempotency_key="rotate-one")
    assert rotated["status"] == "disabled" and not rotated["allowed_capabilities"]
    assert secrets.get_secret(old.credential.key) is None
    assert service.rotate_credential(context=context, connection_id=active["id"], expected_revision=3,
        credential="different-invalid-test-key", idempotency_key="rotate-one") == rotated
    with pytest.raises(ContractError):
        service.verify(context=context, connection_id=active["id"], expected_revision=4, idempotency_key="verify-invalid")
    assert store.records[active["id"]].status == "degraded"
    changed = service.rotate_credential(context=context, connection_id=active["id"], expected_revision=6,
        credential=KEY, idempotency_key="rotate-two")
    assert service.verify(context=context, connection_id=active["id"], expected_revision=changed["revision"], idempotency_key="verify-valid")["status"] == "active"


def test_failed_cleanup_queues_existing_worker_and_retry_is_idempotent(agent):
    parts = setup(agent[0]); service, store, secrets, context, _, _, _, _ = parts
    active = create_active(parts)
    queued = []
    service.enqueue_cleanup = lambda **kw: queued.append(kw)
    delete = secrets.delete_secret
    secrets.delete_secret = lambda key: (_ for _ in ()).throw(OSError("test-secret-not-exposed"))
    # The revocation itself succeeded and is durable, so it is reported as what
    # it is. Raising here would tell the person the agent still has access,
    # which is the opposite of what happened; the retired secret is what is
    # still pending, and the answer says so.
    revoked = service.revoke(context=context, connection_id=active["id"], expected_revision=3,
                             idempotency_key="revoke-retry")
    assert revoked["status"] == "revoked" and revoked["credential_cleanup"] == "pending"
    assert store.records[active["id"]].status == "revoked" and queued[0]["connection_id"] == active["id"]
    secrets.delete_secret = delete
    service.cleanup_revoked(context=context, connection_id=active["id"])
    service.cleanup_revoked(context=context, connection_id=active["id"])
    assert not secrets.values
    with pytest.raises(ContractError, match="revoked"):
        service.rotate_credential(context=context, connection_id=active["id"], expected_revision=4,
            credential=KEY, idempotency_key="rotate-revoked")


def test_rotation_retired_key_cleanup_preserves_current_and_removes_staged_orphan(agent):
    parts = setup(agent[0]); service, store, secrets, context, _, _, _, _ = parts
    active = create_active(parts)
    previous_key = store.records[active["id"]].credential.key
    delete = secrets.delete_secret
    queued = []
    service.enqueue_cleanup = lambda **kw: queued.append(kw)
    secrets.delete_secret = lambda key: (_ for _ in ()).throw(OSError("temporary"))
    service.rotate_credential(context=context, connection_id=active["id"], expected_revision=3,
        credential="replacement-test-credential", idempotency_key="rotate-cleanup")
    current = store.records[active["id"]]
    assert previous_key in secrets.values and queued
    orphan = f"aw_external.{current.header.entity_id}.revision.{current.header.revision + 1}"
    secrets.values[orphan] = "orphan-test-only-credential"
    secrets.delete_secret = delete
    service.cleanup_credentials(context=context, connection_id=active["id"])
    assert secrets.values == {current.credential.key: "replacement-test-credential"}
