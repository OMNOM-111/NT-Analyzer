from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest

from app.production_storage import (
    AuthRepository,
    CommandRepository,
    ConnectorRepository,
    DocumentRepository,
    EntitlementRepository,
    JobRepository,
    MigrationRunner,
    Scope,
    StorageConflictError,
    StorageConstraintError,
    StorageReadOnlyError,
    StorageUnavailableError,
    WorkspaceRepository,
    apply_owner_plan,
    build_owner_plan,
    reset_for_tests,
)
from app.production_storage.artifacts import FileArtifactStore
from app.production_storage.core import PostgresClient


ADMIN_URL = os.environ.get("STRATFORGE_TEST_POSTGRES_ADMIN_URL", "")
APP_URL = os.environ.get("STRATFORGE_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_URL,
    reason="real PostgreSQL acceptance DSNs were not provided",
)


@pytest.fixture(autouse=True)
def clean_database(tmp_path: Path, monkeypatch):
    import psycopg

    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_ALLOW_INSECURE_LOCAL_POSTGRES", "1")
    monkeypatch.setenv("STRATFORGE_ARTIFACT_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("STRATFORGE_DEFAULT_WORKSPACE_QUOTA_BYTES", "1048576")
    monkeypatch.setenv("STRATFORGE_MAX_ARTIFACT_BYTES", "524288")
    (tmp_path / "objects").mkdir()
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(
            """
            TRUNCATE sf_repository_documents, sf_auth_challenges, sf_auth_sessions,
              sf_workspace_memberships, sf_active_workspaces, sf_workspace_ledgers,
              sf_connections, sf_entitlements, sf_connector_sessions,
              sf_commands, sf_connector_installations, sf_jobs, sf_audit_events,
              sf_storage_quotas, sf_artifacts, sf_migration_runs, sf_workspaces,
              sf_users RESTART IDENTITY CASCADE
            """
        )
    yield


def _client(url: str = APP_URL) -> PostgresClient:
    return PostgresClient(url, production=False)


def _seed(client: PostgresClient) -> dict[str, str]:
    docs = DocumentRepository(client)
    auth = docs.read("auth", {"version": 2, "users": [], "challenges": [], "sessions": []})
    auth["users"] = [
        {"user_id": 101, "status": "active", "is_owner": True, "first_name": "Owner"},
        {"user_id": 202, "status": "active", "is_owner": False, "first_name": "Alpha"},
        {"user_id": 303, "status": "active", "is_owner": False, "first_name": "Beta"},
    ]
    docs.write("auth", auth)

    ws_a = "ws_personal_ALPHA1234"
    ws_b = "ws_personal_BETA12345"
    workspaces = docs.read(
        "workspaces",
        {"version": 1, "workspaces": [], "memberships": [],
         "active_workspaces": {}, "connections": [], "pairings": []},
    )
    workspaces.update({
        "workspaces": [
            {"workspace_id": ws_a, "owner_user_id": 202, "status": "active", "kind": "personal"},
            {"workspace_id": ws_b, "owner_user_id": 303, "status": "active", "kind": "personal"},
        ],
        "memberships": [
            {"workspace_id": ws_a, "user_id": 202, "role": "owner"},
            {"workspace_id": ws_b, "user_id": 303, "role": "owner"},
        ],
        "active_workspaces": {"202": ws_a, "303": ws_b},
        "connections": [],
        "pairings": [],
    })
    docs.write("workspaces", workspaces)

    entitlements = docs.read(
        "entitlements",
        {"version": 1, "vouchers": [], "entitlements": [], "plan_overrides": {},
         "payment_config": {}, "paypal": {}, "payment_requests": []},
    )
    entitlements["entitlements"] = [
        {"entitlement_id": "ent_alpha_001", "user_id": 202, "workspace_id": ws_a,
         "plan_id": "pro", "status": "active"},
        {"entitlement_id": "ent_beta_001", "user_id": 303, "workspace_id": ws_b,
         "plan_id": "basic", "status": "active"},
    ]
    docs.write("entitlements", entitlements)
    return {"a": ws_a, "b": ws_b}


def test_migration_is_applied_and_checksum_stable() -> None:
    plan = MigrationRunner(ADMIN_URL).plan()
    assert plan["latest_version"] == 1
    assert plan["applied_versions"] == [1]
    assert plan["pending"] == []
    assert len(plan["migration_set_sha256"]) == 64


def test_rls_denies_foreign_user_workspace_and_entitlement() -> None:
    client = _client()
    ids = _seed(client)
    alpha = Scope(user_id=202, workspace_id=ids["a"])

    assert AuthRepository(client).get_user(202, scope=alpha)["first_name"] == "Alpha"
    assert AuthRepository(client).get_user(303, scope=alpha) is None
    assert WorkspaceRepository(client).get(ids["a"], scope=alpha)["workspace_id"] == ids["a"]
    assert WorkspaceRepository(client).get(ids["b"], scope=alpha) is None
    assert [row["entitlement_id"] for row in EntitlementRepository(client).list(scope=alpha)] == [
        "ent_alpha_001"
    ]


def test_jobs_commands_and_direct_foreign_write_are_workspace_scoped() -> None:
    client = _client()
    ids = _seed(client)
    alpha = Scope(user_id=202, workspace_id=ids["a"])
    beta = Scope(user_id=303, workspace_id=ids["b"])

    job = {"job_id": "job_alpha_0001", "workspace_id": ids["a"], "user_id": 202,
           "kind": "backtest", "status": "queued", "idempotency_key": "idem-job-alpha-1"}
    command = {"command_id": "cmd_alpha_0001", "workspace_id": ids["a"], "user_id": 202,
               "command_type": "paper_order", "status": "queued",
               "idempotency_key": "idem-cmd-alpha-1", "dangerous": False}
    assert JobRepository(client).put(job, scope=alpha)["job_id"] == job["job_id"]
    assert CommandRepository(client).put(command, scope=alpha)["command_id"] == command["command_id"]
    assert JobRepository(client).get(job["job_id"], scope=beta) is None
    assert CommandRepository(client).get(command["command_id"], scope=beta) is None
    with pytest.raises(StorageConstraintError):
        JobRepository(client).put({**job, "job_id": "job_scope_bad1", "workspace_id": ids["b"]}, scope=alpha)
    with pytest.raises(StorageConstraintError):
        with client.transaction(alpha) as conn:
            conn.execute(
                """INSERT INTO sf_jobs(job_id,workspace_id,user_id,kind,status,idempotency_key,document)
                   VALUES('job_foreign_01',%s,303,'backtest','queued','idem-foreign-job','{}')""",
                (ids["b"],),
            )


def test_document_optimistic_concurrency_rejects_lost_update() -> None:
    first = _client()
    ids = _seed(first)
    second = _client()
    repo_a = DocumentRepository(first)
    repo_b = DocumentRepository(second)
    doc_a = repo_a.read("workspaces", {})
    doc_b = repo_b.read("workspaces", {})
    doc_a["active_workspaces"]["202"] = ids["a"]
    repo_a.write("workspaces", doc_a)
    doc_b["active_workspaces"]["303"] = ids["b"]
    with pytest.raises(StorageConflictError, match="Concurrent workspaces"):
        repo_b.write("workspaces", doc_b)


def test_parallel_scoped_job_writes_are_lossless_and_isolated() -> None:
    seed_client = _client()
    ids = _seed(seed_client)

    def write_job(index: int) -> tuple[str, str]:
        workspace = ids["a"] if index % 2 == 0 else ids["b"]
        user_id = 202 if index % 2 == 0 else 303
        scope = Scope(user_id=user_id, workspace_id=workspace)
        job_id = f"job_parallel_{index:04d}"
        row = {
            "job_id": job_id,
            "workspace_id": workspace,
            "user_id": user_id,
            "kind": "stage6-load",
            "status": "queued",
            "idempotency_key": f"idem-parallel-{index:04d}",
        }
        client = _client()
        saved = JobRepository(client).put(row, scope=scope)
        assert saved["job_id"] == job_id
        return workspace, job_id

    with ThreadPoolExecutor(max_workers=20) as pool:
        rows = list(pool.map(write_job, range(60)))
    assert len(rows) == 60
    with seed_client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        assert conn.execute("SELECT count(*) AS count FROM sf_jobs").fetchone()["count"] == 60
    with seed_client.transaction(Scope(user_id=202, workspace_id=ids["a"]), read_only=True) as conn:
        assert conn.execute("SELECT count(*) AS count FROM sf_jobs").fetchone()["count"] == 30
    with seed_client.transaction(Scope(user_id=303, workspace_id=ids["b"]), read_only=True) as conn:
        assert conn.execute("SELECT count(*) AS count FROM sf_jobs").fetchone()["count"] == 30


def test_artifacts_are_opaque_checksum_verified_quota_bound_and_isolated(monkeypatch) -> None:
    client = _client()
    ids = _seed(client)
    alpha = Scope(user_id=202, workspace_id=ids["a"])
    beta = Scope(user_id=303, workspace_id=ids["b"])
    store = FileArtifactStore(client)

    row = store.put_bytes(
        b"verified payload", scope=alpha, logical_name="../../client/C:/report.json",
        media_type="application/json", retention_days=1,
    )
    assert row["logical_name"] == "report.json"
    assert store.read_bytes(row["artifact_id"], scope=alpha) == b"verified payload"
    with pytest.raises(FileNotFoundError):
        store.read_bytes(row["artifact_id"], scope=beta)
    with pytest.raises(StorageConstraintError, match="per-file limit"):
        store.put_bytes(b"x" * 524289, scope=alpha)

    monkeypatch.setenv("STRATFORGE_RETENTION_EXECUTION_ALLOWED", "1")
    plan = store.retention_plan(scope=alpha, now=datetime.now(timezone.utc) + timedelta(days=2))
    assert plan["count"] == 1
    result = store.quarantine_expired(plan, scope=alpha, confirm_sha256=plan["plan_sha256"])
    assert result == {"ok": True, "quarantined": [row["artifact_id"]], "recoverable": True}
    with pytest.raises(FileNotFoundError):
        store.read_bytes(row["artifact_id"], scope=alpha)


def test_database_outage_and_read_only_fail_closed() -> None:
    bad = APP_URL.replace(":55432/", ":55433/")
    with pytest.raises(StorageUnavailableError):
        AuthRepository(_client(bad)).get_user(202, scope=Scope(user_id=202))

    separator = "&" if "?" in APP_URL else "?"
    read_only_url = APP_URL + separator + "options=" + quote("-c default_transaction_read_only=on")
    read_only = _client(read_only_url)
    with pytest.raises(StorageReadOnlyError):
        with read_only.transaction(Scope.global_service_scope()) as conn:
            conn.execute(
                "INSERT INTO sf_repository_documents(repository,revision,document) VALUES('auth',1,'{}')"
            )


def test_selected_owner_migration_is_atomic_scoped_and_idempotent() -> None:
    owner_id = 404
    workspace_id = "ws_owner_STAGE6001"
    installation_id = "inst_owner_stage6_001"
    documents = {
        "auth": {
            "version": 2,
            "users": [{"user_id": owner_id, "is_owner": True, "status": "active",
                       "first_name": "Selected", "session_token": "excluded"}],
            "challenges": [{"challenge_id": "excluded-challenge"}],
            "sessions": [{"session_id": "excluded-session", "user_id": owner_id}],
        },
        "workspaces": {
            "version": 1,
            "workspaces": [{"workspace_id": workspace_id, "owner_user_id": owner_id,
                            "status": "active", "kind": "personal",
                            "data_root": r"C:\\client\\must-not-migrate"}],
            "memberships": [{"workspace_id": workspace_id, "user_id": owner_id, "role": "owner"}],
            "active_workspaces": {str(owner_id): workspace_id},
            "connections": [],
            "pairings": [],
        },
        "entitlements": {
            "version": 1,
            "entitlements": [{"entitlement_id": "ent_owner_stage6", "user_id": owner_id,
                              "workspace_id": workspace_id, "plan_id": "pro", "status": "active"}],
        },
        "connectors": {
            "schema_version": 1,
            "installations": [{"installation_id": installation_id,
                               "workspace_id": workspace_id,
                               "enrolled_by_user_id": owner_id,
                               "status": "online",
                               "public_key_fingerprint": "c" * 64,
                               "public_key": {"kty": "EC", "crv": "P-256", "x": "x", "y": "y"}}],
            "enrollments": [], "sessions": [], "commands": [], "results": [],
        },
    }
    ledgers = {workspace_id: {"version": 1, "accounts": {}}}
    plan = build_owner_plan(
        documents, ledgers, owner_user_id=owner_id,
        categories=("auth", "workspaces", "entitlements", "connectors", "ledgers"),
        workspace_ids=(workspace_id,), installation_ids=(installation_id,),
    )
    client = _client()
    result = apply_owner_plan(client, plan, confirm_sha256=plan["plan_sha256"])
    assert result["applied"] is True
    repeated = apply_owner_plan(client, plan, confirm_sha256=plan["plan_sha256"])
    assert repeated["already_applied"] is True

    scope = Scope(user_id=owner_id, workspace_id=workspace_id)
    assert AuthRepository(client).get_user(owner_id, scope=scope)["first_name"] == "Selected"
    assert WorkspaceRepository(client).get(workspace_id, scope=scope)["workspace_id"] == workspace_id
    assert EntitlementRepository(client).list(scope=scope)[0]["entitlement_id"] == "ent_owner_stage6"
    installation = ConnectorRepository(client).installations(scope=scope)[0]
    assert installation["installation_id"] == installation_id
    assert installation["status"] == "offline"
    assert WorkspaceRepository(client).get_ledger(scope=scope, default={}) == {
        "version": 1, "accounts": {},
    }
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        assert conn.execute("SELECT count(*) AS count FROM sf_auth_sessions").fetchone()["count"] == 0
        assert conn.execute("SELECT count(*) AS count FROM sf_auth_challenges").fetchone()["count"] == 0
        assert conn.execute("SELECT count(*) AS count FROM sf_migration_runs").fetchone()["count"] == 1


def test_real_application_modules_route_production_state_to_postgres_only(
    tmp_path: Path, monkeypatch,
) -> None:
    from app import account_auth, connector_protocol, runtime_env, storage_router, subscriptions, workspaces

    data_root = tmp_path / "production-state"
    artifact_root = tmp_path / "production-objects"
    data_root.mkdir()
    artifact_root.mkdir()
    for key in (
        "NTA_APP_ENV", "NTA_ENV", "NTA_TEST_BYPASS_AUTH", "NTA_ENABLE_TEST_AUTH",
        "NTA_ENABLE_IMPERSONATION", "NTA_DISABLE_RATE_LIMIT",
        "NTA_ALLOW_LIVE_ORDERS", "NTA_ALLOW_REAL_PAYMENTS",
    ):
        monkeypatch.delenv(key, raising=False)
    values = {
        "STRATFORGE_ENV": "production",
        "STRATFORGE_INSTANCE_ID": "stratforge-prod-stage6-test",
        "STRATFORGE_DEPLOYMENT_ROLE": "all-in-one",
        "STRATFORGE_CONFIG_PROFILE": "production-primary",
        "STRATFORGE_BUILD_VERSION": "1.0.0-test",
        "STRATFORGE_BUILD_DATE": "2026-07-21",
        "STRATFORGE_RELEASE_CHANNEL": "stable",
        "STRATFORGE_REGION": "primary",
        "STRATFORGE_BIND_HOST": "127.0.0.1",
        "STRATFORGE_ALLOWED_HOSTS": "app.stratforges.com",
        "STRATFORGE_PUBLIC_ORIGIN": "https://app.stratforges.com",
        "STRATFORGE_EDGE_MODE": "cloudflare-tunnel",
        "STRATFORGE_TRUSTED_PROXY_IPS": "127.0.0.1,::1",
        "STRATFORGE_DATA_ROOT": str(data_root),
        "STRATFORGE_DATABASE_ID": "postgres-stage6-test",
        "STRATFORGE_QUEUE_ID": "production-jobs",
        "STRATFORGE_OBJECT_STORAGE_ID": "production-artifacts",
        "STRATFORGE_TELEGRAM_BOT_ID": "production-main",
        "STRATFORGE_COOKIE_NAMESPACE": "sf-prod",
        "STRATFORGE_SIGNING_KEY_ID": "production-key-v1",
        "STRATFORGE_LOG_NAMESPACE": "production",
        "STRATFORGE_LIVE_TRADING_ALLOWED": "0",
        "STRATFORGE_REAL_PAYMENTS_ALLOWED": "0",
        "STRATFORGE_STORAGE_MODE": "postgresql",
        "STRATFORGE_DATABASE_URL": APP_URL,
        "STRATFORGE_ARTIFACT_ROOT": str(artifact_root),
        "STRATFORGE_ARTIFACT_MIN_FREE_BYTES": "1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    reset_for_tests()
    try:
        runtime_env.assert_startup_safe()
        storage_router.assert_production_storage_safe()
        assert storage_router.storage_status()["available"] is True

        owner_id = 505
        workspace_id = "ws_owner_PRODMOD01"
        auth_doc = account_auth._read_doc()
        auth_doc["users"] = [{
            "user_id": owner_id, "is_owner": True, "role": "owner",
            "status": "active", "first_name": "Production",
        }]
        account_auth._write_doc(auth_doc)

        workspace_doc = workspaces._read_doc()
        workspace_doc.update({
            "workspaces": [{"workspace_id": workspace_id, "owner_user_id": owner_id,
                            "status": "active", "kind": "personal"}],
            "memberships": [{"workspace_id": workspace_id, "user_id": owner_id, "role": "owner"}],
            "active_workspaces": {str(owner_id): workspace_id},
            "connections": [], "pairings": [],
        })
        workspaces._write_doc(workspace_doc)

        entitlement_doc = subscriptions._read_doc()
        entitlement_doc["entitlements"] = [{
            "entitlement_id": "ent_prod_module_01", "user_id": owner_id,
            "workspace_id": workspace_id, "plan_id": "pro", "status": "active",
        }]
        subscriptions._write_doc(entitlement_doc)

        connector_doc = connector_protocol._read_doc()
        connector_doc["installations"] = [{
            "installation_id": "inst_prod_module_01", "workspace_id": workspace_id,
            "enrolled_by_user_id": owner_id, "status": "offline",
            "public_key_fingerprint": "d" * 64,
        }]
        connector_protocol._write_doc(connector_doc)

        assert account_auth._read_doc()["users"][0]["first_name"] == "Production"
        assert workspaces._read_doc()["workspaces"][0]["workspace_id"] == workspace_id
        assert subscriptions._read_doc()["entitlements"][0]["entitlement_id"] == "ent_prod_module_01"
        assert connector_protocol._read_doc()["installations"][0]["installation_id"] == "inst_prod_module_01"
        assert not account_auth._store_path().exists()
        assert not workspaces._store_path().exists()
        assert not subscriptions._store_path().exists()
        assert not connector_protocol._store_path().exists()
    finally:
        reset_for_tests()
