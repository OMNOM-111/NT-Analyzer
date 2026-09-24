"""Real provisioning, common erasure and public-only Preview boundaries."""
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.test_preview_sandbox import preview_env
from app import account_auth, account_lifecycle, community, preview_sandbox, preview_public
from app import market_data_demo, market_data_ws_http, market_data_access, security_devices, workspaces
from app.ai_control_center import model_sharing
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError


def test_demo_is_deterministic_bounded_and_never_opens_owner_transport(monkeypatch):
    now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
    for timeframe in ("1m", "5m", "1h", "1D", "1w", "1M"):
        result = market_data_demo.series("MES", timeframe, 75, now=now)
        assert result == market_data_demo.series("MES", timeframe, 75, now=now)
        assert len(result["bars"]) == 75
        assert result["live"] is False and result["source"]["data_plane"] == "history_replay"
        assert all(bar["l"] <= min(bar["o"], bar["c"]) <= max(bar["o"], bar["c"]) <= bar["h"] for bar in result["bars"])
    decision = market_data_access.MarketDataAccessDecision(True, "trial_demo", source="demo_replay", scope_id="public-demo-v1")
    client = SimpleNamespace(upstream_refs={})
    assert market_data_ws_http._acquire_client_upstream(client, "MES", "5m", decision)
    assert client.upstream_refs == {}
    assert not market_data_access.decision_allows_message(decision, {"market_data_scope": "owner-shared"})
    from app import server
    from app.market_data_failover import TopstepXProvider
    monkeypatch.setattr(TopstepXProvider, "configured", lambda *a: pytest.fail("demo contacted owner provider"))
    payload = server._market_bars_payload_impl("MES", "5m", 75, access_decision=decision)
    assert payload["status"] == "demo_replay" and len(payload["bars"]) == 75


def test_public_projection_excludes_private_content_and_cannot_persist_imports(preview_env, monkeypatch):
    public = community.create_social_post(41, text="owner public", visibility="network")
    community.create_social_post(41, text="owner private", visibility="private")
    doc = community._load(include_preview=False)
    doc["profiles"][0].update(email="private@example.test", user_uuid=str(uuid4()))
    projected = preview_public.snapshot(doc)
    encoded = json.dumps(projected)
    assert "owner public" in encoded and "owner private" not in encoded and "private@example.test" not in encoded
    assert str(doc["profiles"][0]["user_uuid"]) not in encoded
    assert all(row["allow_messages"] == "nobody" and row["user_id"] == 0 for row in projected["profiles"])
    assert preview_public.local_only(projected)["posts"] == []
    from app import preview_shared_models
    monkeypatch.setattr(preview_shared_models, "transport_enabled", lambda: True)
    monkeypatch.setattr(preview_shared_models, "request", lambda path, body: projected)
    # The child owns a separate document; overlay is live and never copied back.
    community._store_path().unlink()
    child_post = community.create_social_post(99, text="child public", visibility="network")
    feed = community.social_feed(99)["posts"]
    assert {row["text"] for row in feed} == {"child public", "owner public"}
    persisted = json.loads(community._store_path().read_text(encoding="utf-8"))
    assert [row["text"] for row in persisted["posts"]] == ["child public"]


def _registered():
    preview_sandbox.activate_scenario("shared_models_user", device_credential="lifecycle-browser")
    state = preview_sandbox._STATE
    return state["current_user_id"], state["current_user_uuid"], state["current_session_id"]


def test_self_delete_requires_fresh_purpose_session_and_exact_confirmation(preview_env):
    uid, canonical, sid = _registered()
    started = account_lifecycle.start(uid, sid)
    args = dict(challenge_id=started["challenge_id"], code=started["test_code"], confirmation="УДАЛИТЬ")
    with pytest.raises(security_devices.SecurityDeviceError, match="другой сессии"):
        account_lifecycle.confirm(uid, "foreign", **args)
    with pytest.raises(account_auth.AccountAuthError):
        account_lifecycle.confirm(uid, sid, **{**args, "confirmation": "yes"})
    with pytest.raises(security_devices.SecurityDeviceError):
        account_lifecycle.confirm(uid, sid, **{**args, "code": "xxxxxx"})
    assert account_auth.find_active_user(uid)
    result = account_lifecycle.confirm(uid, sid, **args)
    assert result["deleted"] and account_auth.find_active_user(uid) is None
    assert canonical in account_lifecycle.deleted_ids()
    assert not workspaces.user_footprint(canonical, uid)["owned_workspaces"]
    doc = account_auth._read_doc()
    assert all(not account_lifecycle._matches(row, uid, canonical) for rows in doc.values() if isinstance(rows, list) for row in rows)


def test_erasure_keeps_usage_but_removes_workspace_chat_model_secrets(preview_env):
    from app import secure_store
    from app.ai_lab import chief_agent
    uid, canonical, sid = _registered()
    ws = workspaces.user_footprint(canonical, uid)["owned_workspaces"][0]
    scope = {"user_id": uid, "user_uuid": canonical, "workspace_id": ws}
    chat = chief_agent._conversation_file("private", scope=scope)
    chat.parent.mkdir(parents=True, exist_ok=True)
    chat.write_text('private chat and memory', encoding="utf-8")
    tenant = workspaces._tenant_root(ws)
    (tenant / "private.txt").write_text("private workspace", encoding="utf-8")
    # Seed actual relational private revisions and a DPAPI credential, plus a
    # different owner's sentinel, rather than only checking a sharing flag.
    repository = SQLiteAgentWorldRepository(preview_sandbox.isolated_root() / "agent-world.sqlite3")
    entity = str(uuid4())
    secure_store.set_secret("aw_provider." + entity, "disposable-provider-secret")
    with sqlite3.connect(repository.path) as db:
        for owner, workspace, eid in ((canonical, ws, entity), ("other-owner", "other-ws", "other-entity")):
            seq = db.execute("INSERT INTO aw_revisions(environment,workspace_id,kind,entity_id,revision,owner_uuid,visibility,payload) VALUES ('development',?,'provider_account',?,1,?,'private',?)", (workspace, eid, owner, 'private content')).lastrowid
            db.execute("INSERT INTO aw_records VALUES ('development',?,'provider_account',?,1,?,?,'private')", (workspace, eid, seq, owner))
            db.execute("INSERT INTO aw_artifacts VALUES ('development',?,?,?,'hash','application/json',?)", (workspace, owner, eid, b'private artifact'))
    from app.ai_lab import agent_registry
    agent_registry.record_usage({"user_id": uid, "user_name": "Private Name", "error": "private provider content", "input_tokens": 12, "cost_usd": .02})
    model_sharing.set_shared(environment="development", owner_workspace_id=ws, owner_user_uuid=canonical,
        model_id="owned-model", shared=True, label="own", provider="test", model_key="test", credential_source="owned")
    with model_sharing._db() as db:
        db.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "request", "other-model", "owner", "owner-ws", canonical, "Private Name", ws,
            "opaque-task", "deputy", "chat", "success", 12, 5, .02, 1, "2026-09-23"))
    started = account_lifecycle.start(uid, sid)
    account_lifecycle.confirm(uid, sid, challenge_id=started["challenge_id"], code=started["test_code"], confirmation="УДАЛИТЬ")
    assert not tenant.exists() and not chat.exists()
    assert not secure_store.get_secret("aw_provider." + entity)
    with sqlite3.connect(repository.path) as db:
        assert db.execute("SELECT owner_uuid FROM aw_revisions").fetchall() == [("other-owner",)]
        assert db.execute("SELECT owner_uuid FROM aw_artifacts").fetchall() == [("other-owner",)]
    assert "Private Name" not in agent_registry.usage_path().read_text(encoding="utf-8")
    agent_registry.record_usage({"user_id": uid, "user_name": "Private Name", "input_tokens": 9})
    assert agent_registry.usage_rows()[-1]["user_name"] == "Удалённый пользователь"
    assert model_sharing.get("owned-model")["shared"] is False
    usage = model_sharing.owner_usage("owner")
    assert usage["by_caller"][0]["caller_name"] == "Удалённый пользователь"
    assert usage["recent"][0]["input_tokens"] == 12 and usage["recent"][0]["cost_usd"] == .02
    with pytest.raises(ContractError, match="model_caller_deleted"):
        model_sharing.require("anything", environment="development", caller_user_uuid=canonical)
    with pytest.raises(community.CommunityError, match="удалён"):
        community.create_social_post(uid, user_uuid=canonical, text="late private write")


def test_failed_erasure_stays_revoked_and_is_retryable(preview_env, monkeypatch):
    uid, canonical, sid = _registered()
    original = account_lifecycle._erase_agent_world
    monkeypatch.setattr(account_lifecycle, "_erase_agent_world", lambda *args: (_ for _ in ()).throw(OSError("temporary storage failure")))
    with pytest.raises(OSError):
        account_lifecycle.erase(uid, reason="preview_reset", automatic_preview=True)
    assert account_auth.find_active_user(uid) is None
    assert not account_auth.local_session_is_active(sid, uid)
    with pytest.raises(community.CommunityError, match="удаляется"):
        community.create_social_post(uid, text="late write")
    monkeypatch.setattr(account_lifecycle, "_erase_agent_world", original)
    assert account_lifecycle.erase(uid, reason="preview_reset", automatic_preview=True)["deleted"]
    receipt = account_lifecycle.registry_rows()[0]
    assert json.loads(receipt["security_flags"])["previously_blocked"] is False


def test_unsupported_storage_refuses_before_freezing_identity(preview_env, monkeypatch):
    uid, canonical, sid = _registered()
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_STORAGE", "postgres")
    with pytest.raises(account_auth.AccountAuthError, match="адаптер"):
        account_lifecycle.erase(uid, reason="self_requested")
    assert account_auth.find_active_user(uid) and account_auth.local_session_is_active(sid, uid)
