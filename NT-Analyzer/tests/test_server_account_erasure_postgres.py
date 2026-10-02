"""Disposable PostgreSQL acceptance for the server account-erasure adapter.

Run only with the explicit disposable Agent World PostgreSQL DSNs. This suite
never connects to Canary or Production and never provisions a database.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest

from app.production_storage import DocumentRepository, Scope
from app.production_storage.core import PostgresClient
from app.production_storage.core import _jsonb
from app.production_storage import account_erasure
from app.account_auth import AccountAuthError


APP_URL = os.environ.get("STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(
    not os.environ.get("STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW") or not APP_URL,
    reason="explicit disposable PostgreSQL DSN required",
)


@pytest.fixture
def server_store(tmp_path: Path, monkeypatch):
    import psycopg
    from psycopg import sql

    admin_url = os.environ.get("STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL", "")
    target = urlsplit(admin_url)
    if target.hostname != "127.0.0.1" or not target.path.startswith("/aw_disposable_"):
        pytest.fail("refusing account erasure test outside the disposable loopback database")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        names = [row[0] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename LIKE 'sf_%' AND tablename<>'sf_schema_migrations'"
        )]
        conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
            sql.SQL(",").join(sql.Identifier(name) for name in names)))
    monkeypatch.setenv("STRATFORGE_ENV", "canary")
    monkeypatch.setenv("STRATFORGE_STORAGE_MODE", "postgresql")
    monkeypatch.setenv("STRATFORGE_DATABASE_URL", APP_URL)
    monkeypatch.setenv("STRATFORGE_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production-data"))
    monkeypatch.setenv("STRATFORGE_CANARY_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_CREDENTIAL_KEY", base64.b64encode(b"e" * 32).decode())
    (tmp_path / "artifacts").mkdir()
    client = PostgresClient(APP_URL, production=True)
    monkeypatch.setattr(account_erasure, "_client", lambda: client)
    owner, target, foreign = str(uuid4()), str(uuid4()), str(uuid4())
    docs = DocumentRepository(client)
    docs.read("auth", {})
    auth = account_erasure._defaults()["auth"]
    auth["users"] = [
        {"user_id": 101, "user_uuid": owner, "status": "active", "is_owner": True,
         "email": "owner@example.test"},
        {"user_id": 202, "user_uuid": target, "status": "active", "is_owner": False,
         "email": "target@example.test"},
        {"user_id": 303, "user_uuid": foreign, "status": "active", "is_owner": False,
         "email": "foreign@example.test"},
    ]
    auth["auth_identities"] = [
        {"identity_id": str(uuid4()), "user_uuid": identity,
         "legacy_user_id": uid, "provider": "google",
         "provider_subject": f"subject-{uid}"}
        for uid, identity in ((101, owner), (202, target), (303, foreign))
    ]
    auth["sessions"] = [
        {"session_id": f"session-{uid}-abcdefghi", "user_id": uid,
         "user_uuid": identity, "token_hash": f"{uid:064x}",
         "expires_at": "2030-01-01T00:00:00Z", "revoked": False}
        for uid, identity in ((101, owner), (202, target), (303, foreign))
    ]
    auth["trusted_devices"] = [
        {"device_id": str(uuid4()), "user_uuid": identity,
         "legacy_user_id": uid, "fingerprint": f"test-device-{uid}",
         "device_type": "browser", "status": "trusted"}
        for uid, identity in ((202, target), (303, foreign))
    ]
    docs.write("auth", auth)
    docs.read("workspaces", {})
    workspaces = account_erasure._defaults()["workspaces"]
    workspaces["workspaces"] = [
        {"workspace_id": f"ws_personal_{uid}00000", "owner_user_id": uid,
         "owner_user_uuid": identity, "kind": "personal", "status": "active"}
        for uid, identity in ((101, owner), (202, target), (303, foreign))
    ]
    workspaces["memberships"] = [
        {"workspace_id": f"ws_personal_{uid}00000", "user_id": uid, "user_uuid": identity,
         "role": "owner"}
        for uid, identity in ((101, owner), (202, target), (303, foreign))
    ]
    workspaces["active_workspaces"] = {str(uid): f"ws_personal_{uid}00000" for uid in (101, 202, 303)}
    docs.write("workspaces", workspaces)
    entitlements = account_erasure._defaults()["entitlements"]
    docs.read("entitlements", {})
    entitlements["entitlements"] = [
        {"entitlement_id": f"ent-{uid}", "user_id": uid,
         "workspace_id": f"ws_personal_{uid}00000", "plan_id": "pro", "status": "active"}
        for uid in (202, 303)
    ]
    docs.write("entitlements", entitlements)
    community = account_erasure._defaults()["community"]
    docs.read("community", {})
    community["profiles"] = [
        {"profile_id": f"profile-{uid}", "user_id": uid, "user_uuid": identity,
         "username": f"person{uid}"}
        for uid, identity in ((202, target), (303, foreign))
    ]
    community["posts"] = [
        {"post_id": f"post-{uid}", "author_profile_id": f"profile-{uid}",
         "workspace_id": f"ws_personal_{uid}00000"}
        for uid in (202, 303)
    ]
    docs.write("community", community)
    chat = account_erasure._defaults()["sf_chat"]
    docs.read("sf_chat", {})
    chat["conversations"] = [
        {"conversation_id": f"conversation-{uid}",
         "participant_profile_ids": [f"profile-{uid}"], "last_seq": 1}
        for uid in (202, 303)
    ]
    chat["messages"] = [
        {"conversation_id": f"conversation-{uid}", "message_id": f"message-{uid}",
         "sender_profile_id": f"profile-{uid}", "seq": 1, "text": "private"}
        for uid in (202, 303)
    ]
    docs.write("sf_chat", chat)
    with client.transaction(Scope.global_service_scope()) as conn:
        for uid, identity in ((202, target), (303, foreign)):
            conn.execute("""INSERT INTO sf_documents
                (document_id,scope_type,workspace_id,slug,title,owner_user_id,owner_legacy_id)
                VALUES(%s,'workspace',%s,'private-qa','Private QA',%s,%s)""",
                (str(uuid4()), f"ws_personal_{uid}00000", identity, uid))
        for uid, identity in ((202, target), (303, foreign)):
            conn.execute("""INSERT INTO sf_ai_usage_events(request_id,workspace_id,user_id,user_uuid,
                provider,model,role,purpose,status,input_tokens,output_tokens,cost_usd,prompt_sha256,document)
                VALUES(%s,%s,%s,%s,'test','model','worker','qa','success',10,5,0.01,%s,%s)""",
                (f"usage-{uid}-abcdefgh", f"ws_personal_{uid}00000", uid,
                 identity, "a" * 64, _jsonb({"user_name": f"person{uid}"})))
    with psycopg.connect(admin_url) as conn:
        conn.execute("SELECT set_config('stratforge.service_scope','global',true)")
        for uid, identity in ((202, target), (303, foreign)):
            conn.execute("""INSERT INTO sf_identity_history
                (history_id,user_uuid,legacy_user_id,provider,normalized_key,key_hash,
                 state,verified_at,document)
                VALUES(%s,%s,%s,'google',%s,%s,'active',clock_timestamp(),'{}'::jsonb)""",
                (str(uuid4()), identity, uid, f"subject-{uid}", f"{uid:064x}"))
    yield client, docs, owner, target, foreign


def test_relational_erasure_preserves_foreign_identity_and_receipt(server_store):
    client, docs, owner, target, foreign = server_store
    result = account_erasure.erase(202, reason="owner_requested")
    assert result["deleted"] is True
    assert account_erasure.erase(202, reason="owner_requested")["deleted"] is True
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        users = {str(row["user_uuid"]) for row in conn.execute("SELECT user_uuid FROM sf_users")}
        receipt = conn.execute("SELECT user_uuid,legacy_user_id FROM sf_deleted_accounts WHERE legacy_user_id=202").fetchone()
        usage = conn.execute("SELECT user_id,user_uuid,workspace_id,deleted_user_fingerprint,document "
                             "FROM sf_ai_usage_events WHERE request_id='usage-202-abcdefgh'").fetchone()
        foreign_usage = conn.execute("SELECT user_id FROM sf_ai_usage_events "
                                     "WHERE request_id='usage-303-abcdefgh'").fetchone()
        assert conn.execute("SELECT count(*) AS n FROM sf_auth_sessions WHERE user_id=202").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM sf_trusted_devices WHERE legacy_user_id=202").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM sf_trusted_devices WHERE legacy_user_id=303").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM sf_entitlements WHERE user_id=202").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM sf_community_profiles WHERE user_id=202").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM sf_chat_conversations "
                            "WHERE conversation_id='conversation-202'").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM sf_documents "
                            "WHERE workspace_id='ws_personal_20200000'").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM sf_documents "
                            "WHERE workspace_id='ws_personal_30300000'").fetchone()["n"] == 1
    assert users == {owner, foreign}
    assert str(receipt["user_uuid"]) == target
    assert usage["user_id"] is usage["user_uuid"] is usage["workspace_id"] is None
    assert usage["deleted_user_fingerprint"] and usage["document"]["deleted_user"] is True
    assert foreign_usage["user_id"] == 303
    import psycopg
    with psycopg.connect(os.environ["STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL"]) as conn:
        conn.execute("SELECT set_config('stratforge.service_scope','global',true)")
        history = conn.execute("SELECT state,user_uuid FROM sf_identity_history "
                               "WHERE legacy_user_id=202").fetchone()
        foreign_history = conn.execute("SELECT state FROM sf_identity_history "
                                       "WHERE legacy_user_id=303").fetchone()
    assert history[0] == "revoked" and history[1] is None
    assert foreign_history[0] == "active"
    assert {row["user_id"] for row in docs.read("auth", {})["users"]} == {101, 303}


def test_freeze_precedes_erasure_and_failed_transaction_can_retry(server_store, monkeypatch):
    client, docs, _, target, foreign = server_store
    model_id, account_id, foreign_model_id = str(uuid4()), str(uuid4()), str(uuid4())
    workspace = "ws_personal_20200000"
    with client.transaction(Scope.global_service_scope()) as conn:
        account_erasure._scope(conn, "canary", workspace, target)
        conn.execute("""INSERT INTO sf_aw_credentials
            (environment,workspace_id,owner_uuid,account_id,nonce,ciphertext)
            VALUES('canary',%s,%s,%s,%s,%s)""",
            (workspace, target, account_id, b"n" * 12, b"c" * 32))
        conn.execute("""INSERT INTO sf_aw_model_shares
            (environment,owner_workspace_id,owner_user_uuid,model_id,label,provider,
             model_key,credential_source,shared,revision)
            VALUES('canary',%s,%s,%s,'private','test','model','user_supplied',true,1)""",
            (workspace, target, model_id))
        account_erasure._scope(conn, "canary", "ws_personal_30300000", foreign)
        conn.execute("""INSERT INTO sf_aw_model_shares
            (environment,owner_workspace_id,owner_user_uuid,model_id,label,provider,
             model_key,credential_source,shared,revision)
            VALUES('canary','ws_personal_30300000',%s,%s,'foreign','test','model',
              'user_supplied',true,1)""", (foreign, foreign_model_id))
        account_erasure._scope(conn, "canary", workspace, target)
        conn.execute("""INSERT INTO sf_aw_model_calls
            (environment,request_id,model_id,owner_user_uuid,owner_workspace_id,
             caller_user_uuid,caller_workspace_id,caller_name)
            VALUES('canary','call-202-abcdefgh',%s,%s,'ws_personal_30300000',%s,%s,'Person 202')""",
            (foreign_model_id, foreign, target, workspace))
        account_erasure._scope(conn, "canary", "ws_historical_20200000", target)
        conn.execute("""INSERT INTO sf_aw_model_calls
            (environment,request_id,model_id,owner_user_uuid,owner_workspace_id,
             caller_user_uuid,caller_workspace_id,caller_name)
            VALUES('canary','old-call-202-abcdefgh',%s,%s,'ws_personal_30300000',
              %s,'ws_historical_20200000','Old Person 202')""",
            (foreign_model_id, foreign, target))
    original_write = account_erasure._write_document
    def interrupt(conn, db, name, document, revision):
        if name == "community":
            raise RuntimeError("injected before erasure commit")
        return original_write(conn, db, name, document, revision)
    monkeypatch.setattr(account_erasure, "_write_document", interrupt)
    with pytest.raises(RuntimeError, match="injected"):
        account_erasure.erase(202, reason="owner_requested")
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        assert conn.execute("SELECT count(*) AS n FROM sf_deleted_accounts").fetchone()["n"] == 0
        assert conn.execute("SELECT status FROM sf_users WHERE user_id=202").fetchone()["status"] == "blocked"
        account_erasure._scope(conn, "canary", workspace, target)
        assert conn.execute("SELECT shared FROM sf_aw_model_shares WHERE model_id=%s",
                            (model_id,)).fetchone()["shared"] is False
        assert conn.execute("SELECT count(*) AS n FROM sf_aw_credentials").fetchone()["n"] == 1
    assert any(row["user_id"] == 202 for row in docs.read("auth", {})["users"])
    monkeypatch.setattr(account_erasure, "_write_document", original_write)
    assert account_erasure.erase(202, reason="owner_requested")["deleted"] is True
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        account_erasure._scope(conn, "canary", workspace, target)
        assert conn.execute("SELECT count(*) AS n FROM sf_aw_credentials").fetchone()["n"] == 0
        assert conn.execute("SELECT caller_name FROM sf_aw_model_calls "
                            "WHERE request_id='call-202-abcdefgh'").fetchone()["caller_name"] == "Удалённый пользователь"
        account_erasure._scope(conn, "canary", "ws_historical_20200000", target)
        assert conn.execute("SELECT caller_name FROM sf_aw_model_calls "
                            "WHERE request_id='old-call-202-abcdefgh'").fetchone()["caller_name"] == "Удалённый пользователь"


def test_shared_workspace_and_protected_accounts_fail_before_freeze(server_store):
    client, docs, owner, target, foreign = server_store
    with pytest.raises(AccountAuthError) as protected:
        account_erasure.erase(101, reason="owner_requested")
    assert protected.value.code == "protected_account"
    workspaces = docs.read("workspaces", {})
    workspaces["memberships"].append({"workspace_id": "ws_personal_20200000",
                                      "user_id": 303, "user_uuid": foreign, "role": "viewer"})
    docs.write("workspaces", workspaces)
    with pytest.raises(AccountAuthError) as shared:
        account_erasure.erase(202, reason="owner_requested")
    assert shared.value.code == "workspace_shared"
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        assert conn.execute("SELECT status FROM sf_users WHERE user_id=202").fetchone()["status"] == "active"
        assert conn.execute("SELECT count(*) AS n FROM sf_deleted_accounts").fetchone()["n"] == 0


def test_late_usage_and_returning_identity_after_erasure(server_store):
    from app import ai_budgets

    client, docs, _, target, foreign = server_store
    assert account_erasure.erase(202, reason="self_requested")["deleted"] is True
    args = dict(request_id="late-usage-202-abcdefgh", workspace_id="ws_personal_20200000",
                user_id=202, provider="test", model="model", role="worker", purpose="qa",
                status="success", input_tokens=12, output_tokens=6, cost_usd=0.02,
                prompt_sha256="b" * 64)
    assert ai_budgets.record_usage(**args)["ok"] is True
    assert ai_budgets.record_usage(**args)["ok"] is True
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        rows = conn.execute("SELECT user_id,workspace_id,deleted_user_fingerprint FROM sf_ai_usage_events "
                            "WHERE request_id=%s", (args["request_id"],)).fetchall()
    assert len(rows) == 1 and rows[0]["user_id"] is rows[0]["workspace_id"] is None
    assert rows[0]["deleted_user_fingerprint"]
    auth = docs.read("auth", {})
    new_uuid = str(uuid4())
    auth["users"].append({"user_id": 404, "user_uuid": new_uuid,
                          "status": "active", "is_owner": False})
    auth["auth_identities"].append({"identity_id": str(uuid4()), "user_uuid": new_uuid,
        "legacy_user_id": 404, "provider": "google", "provider_subject": "subject-202"})
    docs.write("auth", auth)
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        row = conn.execute("SELECT user_uuid FROM sf_auth_identities "
                           "WHERE provider='google' AND provider_subject='subject-202'").fetchone()
    assert str(row["user_uuid"]) == new_uuid and str(row["user_uuid"]) != target


def test_agent_world_private_records_artifacts_and_events_are_removed(server_store):
    from app.ai_control_center.contracts import Environment
    from app.ai_control_center.postgres_repository import PostgresAgentWorldRepository
    from tests.test_agent_world_storage import arguments, context, persona

    client, _, _, target, _ = server_store
    aw = PostgresAgentWorldRepository(client, environment=Environment.CANARY)
    ctx = context(user=UUID(target).int, workspace="ws_personal_20200000",
                  environment=Environment.CANARY)
    record = persona(aw, ctx=ctx)
    aw.commit(**arguments(record, ctx=ctx))
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        account_erasure._scope(conn, "canary", "ws_personal_20200000", target)
        assert conn.execute("SELECT count(*) AS n FROM sf_aw_records").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM sf_aw_artifacts").fetchone()["n"] == 1
    assert account_erasure.erase(202, reason="owner_requested")["deleted"] is True
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        account_erasure._scope(conn, "canary", "ws_personal_20200000", target)
        for table in ("sf_aw_records", "sf_aw_revisions", "sf_aw_events",
                      "sf_aw_artifacts", "sf_aw_outbox", "sf_aw_mutations"):
            assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


def test_active_live_control_lease_blocks_erasure_before_freeze(server_store):
    client, _, _, target, _ = server_store
    with client.transaction(Scope.global_service_scope()) as conn:
        conn.execute("""INSERT INTO sf_ninjatrader_resource_leases
            (resource_id,job_id,workspace_id,requested_by_user_id,requested_by_legacy_id,
             operation_kind,state,queue_seq,idempotency_key)
            VALUES('paper-resource',%s,'ws_personal_20200000',%s,202,'live','active',1,
              'erasure-test-lease-202')""", (str(uuid4()), target))
    with pytest.raises(AccountAuthError) as active:
        account_erasure.erase(202, reason="owner_requested")
    assert active.value.code == "account_work_active"
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        assert conn.execute("SELECT status FROM sf_users WHERE user_id=202").fetchone()["status"] == "active"


def test_file_payload_cleanup_uses_durable_exact_object_manifest(server_store, monkeypatch, tmp_path):
    from app import runtime_env
    from app.ai_lab import paths
    from app.production_storage.artifacts import FileArtifactStore

    client, _, _, target, foreign = server_store
    store = FileArtifactStore(client, production=True)
    private = store.put_bytes(b"target private", scope=Scope(user_id=202,
        workspace_id="ws_personal_20200000"), logical_name="private.txt")
    other = store.put_bytes(b"foreign private", scope=Scope(user_id=303,
        workspace_id="ws_personal_30300000"), logical_name="foreign.txt")
    target_tenant = runtime_env.data_path("tenants", "ws_personal_20200000")
    foreign_tenant = runtime_env.data_path("tenants", "ws_personal_30300000")
    target_tenant.mkdir(parents=True)
    foreign_tenant.mkdir(parents=True)
    (target_tenant / "personal.json").write_text("private", encoding="utf-8")
    (foreign_tenant / "personal.json").write_text("foreign", encoding="utf-8")
    monkeypatch.setattr(paths, "REGISTRY_DIR", tmp_path / "legacy-registry")
    scope_root = paths.REGISTRY_DIR / "orchestrator_scopes"
    target_scope = scope_root / "u202__ws_personal_20200000"
    foreign_scope = scope_root / "u303__ws_personal_30300000"
    target_scope.mkdir(parents=True)
    foreign_scope.mkdir(parents=True)
    (target_scope / "private.jsonl").write_text("private", encoding="utf-8")
    (foreign_scope / "private.jsonl").write_text("foreign", encoding="utf-8")
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        keys = {row["artifact_id"]: row["object_key"] for row in conn.execute(
            "SELECT artifact_id,object_key FROM sf_artifacts")}
    assert account_erasure.erase(202, reason="owner_requested")["deleted"] is True
    assert not (store.root / keys[private["artifact_id"]]).exists()
    assert (store.root / keys[other["artifact_id"]]).read_bytes() == b"foreign private"
    assert not target_tenant.exists()
    assert (foreign_tenant / "personal.json").read_text(encoding="utf-8") == "foreign"
    assert not target_scope.exists()
    assert (foreign_scope / "private.jsonl").read_text(encoding="utf-8") == "foreign"
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        row = conn.execute("SELECT completed_at FROM sf_account_erasure_objects "
                           "WHERE user_uuid=%s AND category='artifact'",
                           (target,)).fetchone()
    assert row and row["completed_at"] is not None
