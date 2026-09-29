"""Secret-free fixture coverage of the typed owner-model import logic.

The real server gate additionally requires PostgreSQL/RLS and ServerSecrets;
these tests do not claim a live Canary migration or provider connection.
"""
from __future__ import annotations

from uuid import UUID, uuid4
from types import SimpleNamespace

import pytest

from app.ai_control_center import contracts as c, owner_model_migration as migration
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tools import owner_model_migrate as transport


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def available(self):
        return True

    def set_secret(self, key, value):
        previous = self.values.get(key)
        if previous is not None and previous != value:
            raise ContractError("model_connection_idempotency_conflict")
        self.values[key] = value

    def get_secret(self, key):
        return self.values.get(key)


def _fixture(tmp_path):
    owner = uuid4()
    context = c.RequestContext(scope=c.TenantScope(environment=c.Environment.DEVELOPMENT,
        workspace_id="ws_migration_test"), user_uuid=owner,
        actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=owner))
    secrets = MemorySecrets()
    service = ModelService(SQLiteAgentWorldRepository(tmp_path / "source.sqlite"),
        admit=lambda *_: None, secrets=secrets)
    policy = service._put(context, {"version": "test"})
    persona = service._ensure(context, c.Persona, uuid4(), uuid4(), policy,
        display_name="Owner persona", profile=service._put(context, {"description": "kept"}))
    service._walk(context, persona, "active")
    model = service.connect(context=context, payload={"label": "Owner model", "provider": "deepseek",
        "model": "deepseek-v4-flash", "persona_id": str(persona.header.entity_id),
        "api_key": "fixture-secret-never-persist"}, idempotency_key="migration-source")
    return service, context, secrets, model


def test_local_snapshot_and_typed_import_preserve_ids_without_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "state"))
    source, context, local_secrets, original = _fixture(tmp_path)
    snapshot = migration.prepare_local_snapshot(repository=source.repository, context=context,
        local_secrets=local_secrets, resolve_registry=lambda *_: pytest.fail("no registry binding"),
        resolve_share=lambda *_: None, source_commit="a" * 40, migration_id=str(uuid4()))
    item = snapshot["models"][0]
    assert item["model_id"] == original["id"]
    assert item["account_id"] == original["provider_account_id"]
    assert item["persona_id"] == original["persona_id"]
    assert item["secret"] == "fixture-secret-never-persist"
    migration._validate_item(item)

    destination_secrets = MemorySecrets()
    destination = ModelService(SQLiteAgentWorldRepository(tmp_path / "destination.sqlite"),
        admit=lambda *_: None, secrets=destination_secrets)
    assert migration._import_one(destination, context, item, snapshot["migration_id"])["status"] == "imported"
    assert migration._import_one(destination, context, item, snapshot["migration_id"])["status"] == "already_imported"
    detail = destination.model_detail(context=context, model_id=original["id"])
    assert detail["provider_account_id"] == original["provider_account_id"]
    assert detail["persona_id"] == original["persona_id"]
    assert detail["provider"] == "deepseek" and detail["model"] == "deepseek-v4-flash"
    assert destination.repository.get(context=context, kind=EntityKind.PERSONA,
        entity_id=UUID(original["persona_id"]))
    assert b"fixture-secret-never-persist" not in (tmp_path / "destination.sqlite").read_bytes()
    assert destination_secrets.get_secret("aw_provider." + original["provider_account_id"]) == item["secret"]


def test_replay_rejects_changed_secret_and_never_reopens_share(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "state"))
    source, context, local_secrets, original = _fixture(tmp_path)
    snapshot = migration.prepare_local_snapshot(repository=source.repository, context=context,
        local_secrets=local_secrets, resolve_registry=lambda *_: pytest.fail("no registry binding"),
        resolve_share=lambda *_: None, source_commit="b" * 40, migration_id=str(uuid4()))
    item = {**snapshot["models"][0], "shared": True}
    destination = ModelService(SQLiteAgentWorldRepository(tmp_path / "destination.sqlite"),
        admit=lambda *_: None, secrets=MemorySecrets())
    migration._import_one(destination, context, item, snapshot["migration_id"])
    destination.set_sharing(context=context, model_id=original["id"], shared=False)
    assert migration._import_one(destination, context, item, snapshot["migration_id"])["status"] == "already_imported"
    assert not destination.model_detail(context=context, model_id=original["id"])["shared"]
    with pytest.raises(ContractError, match="model_migration_conflict"):
        migration._import_one(destination, context, {**item, "secret": "different-secret-fixture"},
            snapshot["migration_id"])


@pytest.mark.parametrize("field,value", [("base_url", "http://127.0.0.1"),
    ("secret", "short"), ("shared", "true"), ("provider", "custom")])
def test_migration_rejects_unsafe_snapshot_field(tmp_path, field, value):
    source, context, local_secrets, _ = _fixture(tmp_path)
    snapshot = migration.prepare_local_snapshot(repository=source.repository, context=context,
        local_secrets=local_secrets, resolve_registry=lambda *_: None,
        resolve_share=lambda *_: None, source_commit="c" * 40, migration_id=str(uuid4()))
    with pytest.raises(ContractError):
        migration._validate_item({**snapshot["models"][0], field: value})


def test_sender_uses_pinned_ssh_stdin_and_outputs_receipt_only(monkeypatch):
    migration_id = str(uuid4())
    owner = str(uuid4())
    args = SimpleNamespace(ssh_target="stratforge@example.test", remote_app_dir="/srv/releases/beta101",
        remote_env_file="/srv/config/canary.env", remote_python="/srv/venv/bin/python",
        environment="canary", owner_uuid=owner, workspace_id="ws_migration_test",
        migration_id=migration_id)
    monkeypatch.setattr(transport, "_source_snapshot", lambda *_: {"secret": "fixture-secret-never-log"})
    captured = {}
    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return SimpleNamespace(returncode=0, stdout=(
            '{"ok":true,"migration_id":"' + migration_id + '","metadata_sha256":"' + "a" * 64 + '"}').encode())
    monkeypatch.setattr(transport.subprocess, "run", run)
    result = transport._sender(args)
    assert result["ok"] is True
    assert "fixture-secret-never-log" not in " ".join(captured["command"])
    assert b"fixture-secret-never-log" in captured["kwargs"]["input"]
    assert "StrictHostKeyChecking=yes" in captured["command"]
    assert captured["kwargs"]["capture_output"] is True


def test_sender_denies_unpinned_or_invalid_target_before_secret_read(monkeypatch):
    args = SimpleNamespace(ssh_target="stratforge@example.test;touch /tmp/x",
        remote_app_dir="/srv/releases/beta101", remote_env_file="/srv/config/canary.env",
        remote_python="/srv/venv/bin/python", environment="canary",
        owner_uuid=str(uuid4()), workspace_id="ws_migration_test", migration_id=str(uuid4()))
    monkeypatch.setattr(transport, "_source_snapshot", lambda *_: pytest.fail("secret read"))
    with pytest.raises(ContractError, match="transport_denied"):
        transport._sender(args)


def test_migration_actor_is_trusted_service_on_behalf_of_owner(monkeypatch):
    person = uuid4()
    args = SimpleNamespace(owner_uuid=str(person), workspace_id="ws_migration_test",
        migration_id=str(uuid4()))
    monkeypatch.setattr(transport.account_auth, "find_active_user_by_uuid",
        lambda *_: {"is_owner": True, "status": "active", "user_id": 42})
    monkeypatch.setattr(transport.workspaces, "require_workspace_writer", lambda *_args, **_kw: {
        "status": "active", "owner_user_id": 42, "membership": {"role": "owner"}})
    ctx = transport._identity(args, environment=c.Environment.CANARY)
    assert ctx.actor.kind == c.ActorKind.SERVICE
    assert ctx.actor.on_behalf_of == person and ctx.actor.actor_id != person
    assert migration._owner_actor(ctx)
