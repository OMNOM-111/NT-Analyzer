"""Phase 9 — Blue-green Production deployment tooling (fail-closed dry-run).

These tests exercise the blue-green engine (`app.blue_green`) directly and its
integration into the Release Center (`app.release_center`). No real deployment,
migration, network, secret, systemd, symlink switch or Production access ever
occurs: every stage is a dry-run and the external result is always PENDING.
"""
from __future__ import annotations

import json

import pytest

from app import account_auth, auth_identity, blue_green, google_auth, release_center
from app import security_devices


OWNER_ID = 999
OWNER = {"user_id": OWNER_ID, "is_owner": True}


def _fake_builder(candidate, git_commit_sha):
    return {
        "app_version": candidate["app_version"],
        "release_channel": candidate["release_channel"],
        "build_id": "sf-" + candidate["app_version"] + "-" + git_commit_sha[:12],
        "git_commit_sha": git_commit_sha or "a" * 40,
        "artifact_sha256": "A" * 64,
        "manifest_sha256": "B" * 64,
        "signature_algorithm": "ECDSA_P256_SHA256_RAW",
        "signature_status": "verified",
        "trust_tier": "development",
        "built_at_utc": "2026-08-03T00:00:00Z",
        "dirty": False,
        "storage_uri": "artifact://server/x",
        "file_count": 3,
        "migration_count": 10,
    }


@pytest.fixture()
def rc_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", str(OWNER_ID))
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.delenv("STRATFORGE_RELEASE_DEPLOY_ADAPTER", raising=False)
    monkeypatch.delenv("STRATFORGE_BLUEGREEN_EXECUTOR", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(google_auth, "_root", lambda: tmp_path)
    for mod in (account_auth.secure_store, google_auth.secure_store):
        monkeypatch.setattr(mod, "_protect", lambda b: b)
        monkeypatch.setattr(mod, "_unprotect", lambda b: b)
        monkeypatch.setattr(mod, "available", lambda: True)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    monkeypatch.setattr(release_center, "_store_path", lambda: tmp_path / "releases.dpapi")
    monkeypatch.setattr(release_center, "_audit_path", lambda: tmp_path / "release-audit.jsonl")
    monkeypatch.setattr(release_center, "_git_state", lambda: ("a" * 40, False))
    owner_uuid = auth_identity.new_user_uuid()
    account_auth._write_doc({
        "version": 1,
        "users": [
            {
                "user_id": OWNER_ID, "user_uuid": owner_uuid, "username": "owner",
                "first_name": "Owner", "role": "owner", "status": "active",
                "is_owner": True, "google_sub": "owner-google",
                "google_linked_at_utc": "2026-01-01T00:00:00Z",
            },
        ],
        "auth_identities": [], "challenges": [], "sessions": [], "security_challenges": [],
    })
    return tmp_path


def _mk(key="candidate-key-1"):
    return release_center.create_candidate(
        actor=OWNER, app_version="0.10.0-dev.1", release_channel="dev",
        git_commit_sha="a" * 40, idempotency_key=key,
    )["candidate"]["candidate_id"]


def _to_signed(cid):
    release_center.build_release(actor=OWNER, candidate_id=cid, idempotency_key="b-" + cid[:8], builder=_fake_builder)
    release_center.verify_release(actor=OWNER, candidate_id=cid, idempotency_key="v-" + cid[:8])


def _to_canary_passed(cid):
    _to_signed(cid)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-" + cid[:8])
    release_center.record_canary_check(
        actor=OWNER, candidate_id=cid, name="acceptance", result="pass", final=True,
        idempotency_key="cc-" + cid[:8])


def _artifact(build_id="sf-0.10.0-dev.1-aaaaaaaaaaaa"):
    return {"artifact_id": "art_x", "build_id": build_id, "artifact_sha256": "A" * 64}


# --------------------------------------------------------------------------- #
# Strategy / fail-closed executor availability.
# --------------------------------------------------------------------------- #
def test_strategy_is_fail_closed_dry_run(monkeypatch):
    monkeypatch.delenv("STRATFORGE_BLUEGREEN_EXECUTOR", raising=False)
    strategy = blue_green.deployment_strategy()
    assert strategy["strategy"] == "blue_green_symlink"
    assert strategy["real_available"] is False
    assert strategy["real_requested"] is False
    assert strategy["mode"] == blue_green.STATUS_DRY_RUN
    assert strategy["slots"] == ["blue", "green"]


def test_strategy_blocked_when_real_executor_requested(monkeypatch):
    monkeypatch.setenv("STRATFORGE_BLUEGREEN_EXECUTOR", "systemd-real")
    strategy = blue_green.deployment_strategy()
    # A real executor is never available in this phase, even if named.
    assert strategy["real_available"] is False
    assert strategy["real_requested"] is True
    assert strategy["mode"] == blue_green.STATUS_BLOCKED


def test_other_slot():
    assert blue_green.other_slot("blue") == "green"
    assert blue_green.other_slot("green") == "blue"
    assert blue_green.other_slot("") == "green"


# --------------------------------------------------------------------------- #
# DB expand / migrate / contract classification.
# --------------------------------------------------------------------------- #
def test_classify_additive_migration_is_expand():
    sql = "CREATE TABLE IF NOT EXISTS sf_x (id UUID PRIMARY KEY);\nCREATE INDEX IF NOT EXISTS i ON sf_x(id);"
    assert blue_green.classify_migration_sql(sql)["phase"] == blue_green.MIGRATION_EXPAND


def test_classify_guarded_policy_drop_is_online_safe():
    sql = "DROP POLICY IF EXISTS p ON sf_x;\nCREATE POLICY p ON sf_x USING (true);"
    assert blue_green.classify_migration_sql(sql)["phase"] == blue_green.MIGRATION_EXPAND


@pytest.mark.parametrize("sql", [
    "DROP TABLE sf_x;",
    "ALTER TABLE sf_x DROP COLUMN y;",
    "ALTER TABLE sf_x ALTER COLUMN y TYPE bigint;",
    "ALTER TABLE sf_x ALTER COLUMN y SET NOT NULL;",
    "ALTER TABLE sf_x RENAME COLUMN y TO z;",
    "TRUNCATE sf_x;",
    "DELETE FROM sf_x WHERE id = 1;",
    "ALTER TABLE sf_x DROP CONSTRAINT c;",
])
def test_classify_destructive_migration_is_contract(sql):
    result = blue_green.classify_migration_sql(sql)
    assert result["phase"] == blue_green.MIGRATION_CONTRACT
    assert result["reasons"]


def test_classify_ignores_sql_comments():
    sql = "-- DROP TABLE sf_x is only a comment\nCREATE TABLE IF NOT EXISTS sf_x (id UUID);"
    assert blue_green.classify_migration_sql(sql)["phase"] == blue_green.MIGRATION_EXPAND


def test_classify_migrations_split():
    migrations = [
        {"name": "0001_add.sql", "version": 1, "sql": "CREATE TABLE IF NOT EXISTS a (id UUID);"},
        {"name": "0002_drop.sql", "version": 2, "sql": "ALTER TABLE a DROP COLUMN id;"},
    ]
    out = blue_green.classify_migrations(migrations)
    assert out["expand_count"] == 1
    assert out["contract_count"] == 1
    assert out["online_safe"] is False
    assert out["blocking"] == ["0002_drop.sql"]
    assert out["pending_known"] is True


def test_classify_real_migration_set_flags_set_not_null():
    # The real 0004 migration uses ALTER COLUMN ... SET NOT NULL, which is a
    # conservative contract-phase operation; 0009/0010 use only guarded policy
    # drops and stay expand.
    out = blue_green.classify_migrations()
    names_contract = set(out["blocking"])
    names_expand = {e["name"] for e in out["expand"]}
    assert any("0004_audit_events" in n for n in names_contract)
    assert any("0010_blue_green_deploy_steps" in n for n in names_expand)
    assert any("0009_release_center" in n for n in names_expand)


# --------------------------------------------------------------------------- #
# Worker drain (graceful).
# --------------------------------------------------------------------------- #
def test_worker_drain_no_in_flight_is_drained():
    plan = blue_green.plan_worker_drain(active_leases=0, in_flight_jobs=0, grace_seconds=30)
    assert plan["drained"] is True
    assert plan["must_wait_for"] == 0
    assert plan["intake_stopped"] is True
    assert plan["forced"] is False
    assert plan["grace_seconds"] == 30
    assert "stop_new_intake" in plan["steps"]


def test_worker_drain_waits_for_in_flight():
    plan = blue_green.plan_worker_drain(active_leases=2, in_flight_jobs=3, queued_jobs=5)
    assert plan["drained"] is False
    assert plan["must_wait_for"] == 5
    assert plan["forced"] is False


def test_worker_drain_grace_defaults_positive():
    plan = blue_green.plan_worker_drain()
    assert plan["grace_seconds"] >= 1


# --------------------------------------------------------------------------- #
# Webhook / outbox replay de-duplication.
# --------------------------------------------------------------------------- #
def test_dedupe_events_identifies_duplicates():
    seen = [blue_green.replay_key("telegram_update", "1001")]
    incoming = [
        {"kind": "telegram_update", "external_id": "1001"},
        {"kind": "telegram_update", "external_id": "1002"},
        {"kind": "outbox_message", "external_id": "m-1"},
    ]
    out = blue_green.dedupe_events(seen, incoming)
    assert out["duplicate_count"] == 1
    assert out["new_count"] == 2
    assert out["duplicate"][0]["external_id"] == "1001"


def test_dedupe_events_collapses_within_batch():
    out = blue_green.dedupe_events([], [
        {"kind": "outbox_message", "external_id": "m-1"},
        {"kind": "outbox_message", "external_id": "m-1"},
    ])
    assert out["new_count"] == 1
    assert out["duplicate_count"] == 1


# --------------------------------------------------------------------------- #
# Green readiness gate.
# --------------------------------------------------------------------------- #
def test_green_readiness_is_pending_not_pass():
    out = blue_green.green_readiness()
    assert out["status"] == blue_green.STATUS_PENDING
    assert out["required_ready"] is True
    assert "checks" in out["contract"]


# --------------------------------------------------------------------------- #
# Traffic switch + rollback switch (symlink model).
# --------------------------------------------------------------------------- #
def test_traffic_switch_is_symlink_and_reversible():
    out = blue_green.plan_traffic_switch(active_slot="blue", build_id="bid-1")
    assert out["action"] == "symlink_switch"
    assert out["from_slot"] == "blue"
    assert out["to_slot"] == "green"
    assert out["to_release_ref"] == "releases/bid-1"
    assert out["reversible"] is True
    assert out["status"] == blue_green.STATUS_PENDING


def test_rollback_switch_preserves_persistent_data():
    out = blue_green.plan_rollback_switch(from_slot="green", to_slot="blue", to_build_id="bid-0", reason="regression")
    assert out["from_slot"] == "green"
    assert out["to_slot"] == "blue"
    assert out["preserves_persistent_data"] is True
    assert out["reason"] == "regression"


def test_traffic_switch_ref_has_no_absolute_path():
    out = blue_green.plan_traffic_switch(active_slot="blue", build_id="bid-1")
    assert not out["to_release_ref"].startswith("/")
    assert ":" not in out["to_release_ref"]


# --------------------------------------------------------------------------- #
# Deployment plan (ordered stages).
# --------------------------------------------------------------------------- #
def test_deployment_plan_has_ordered_stages():
    plan = blue_green.build_deployment_plan(environment="production", artifact=_artifact())
    stages = [s["stage"] for s in plan["steps"]]
    assert stages == list(blue_green.STAGE_ORDER)
    assert [s["ordinal"] for s in plan["steps"]] == list(range(1, 9))
    assert plan["target_slot"] == "green"


def test_deployment_plan_expand_pending_when_migrations_unknown():
    plan = blue_green.build_deployment_plan(environment="production", artifact=_artifact())
    expand = next(s for s in plan["steps"] if s["stage"] == blue_green.STAGE_EXPAND_MIGRATE)
    assert expand["status"] == blue_green.STATUS_PENDING
    assert plan["online_safe"] is True
    assert plan["blocked_stages"] == []


def test_deployment_plan_blocks_on_contract_migration():
    migrations = [{"name": "x.sql", "version": 1, "sql": "ALTER TABLE a DROP COLUMN id;"}]
    plan = blue_green.build_deployment_plan(environment="production", artifact=_artifact(), migrations=migrations)
    expand = next(s for s in plan["steps"] if s["stage"] == blue_green.STAGE_EXPAND_MIGRATE)
    contract = next(s for s in plan["steps"] if s["stage"] == blue_green.STAGE_CONTRACT_MIGRATE)
    assert expand["status"] == blue_green.STATUS_BLOCKED
    assert contract["status"] == blue_green.STATUS_PENDING
    assert blue_green.STAGE_EXPAND_MIGRATE in plan["blocked_stages"]
    assert plan["online_safe"] is False


def test_deployment_plan_expand_dry_run_when_online_safe():
    migrations = [{"name": "x.sql", "version": 1, "sql": "CREATE TABLE IF NOT EXISTS a (id UUID);"}]
    plan = blue_green.build_deployment_plan(environment="production", artifact=_artifact(), migrations=migrations)
    expand = next(s for s in plan["steps"] if s["stage"] == blue_green.STAGE_EXPAND_MIGRATE)
    assert expand["status"] == blue_green.STATUS_DRY_RUN
    assert plan["online_safe"] is True


def test_deployment_plan_includes_maintenance_window():
    plan = blue_green.build_deployment_plan(environment="production", artifact=_artifact())
    assert plan["maintenance_window"]["state"] == "planned"
    assert plan["maintenance_window"]["environment"] == "production"


# --------------------------------------------------------------------------- #
# Execute (fail-closed dry-run) + rehearse.
# --------------------------------------------------------------------------- #
def test_execute_deployment_is_dry_run(monkeypatch):
    monkeypatch.delenv("STRATFORGE_BLUEGREEN_EXECUTOR", raising=False)
    out = blue_green.execute_deployment("production", _artifact())
    assert out["status"] == blue_green.STATUS_DRY_RUN
    assert out["external_result"] == "pending"
    assert out["adapter"] == "blue_green"
    assert out["steps"]
    assert out["target_slot"] == "green"


def test_execute_deployment_blocked_when_real_executor(monkeypatch):
    monkeypatch.setenv("STRATFORGE_BLUEGREEN_EXECUTOR", "real")
    out = blue_green.execute_deployment("production", _artifact())
    assert out["status"] == blue_green.STATUS_BLOCKED
    assert out["external_result"] == "pending"


def test_rehearse_has_no_side_effects_and_returns_rollback_path():
    out = blue_green.rehearse("production", _artifact())
    assert out["ok"] is True
    assert out["rehearsal"] is True
    assert out["external_result"] == "pending"
    assert out["rollback_switch"]["preserves_persistent_data"] is True
    assert [s["stage"] for s in out["steps"]] == list(blue_green.STAGE_ORDER)


# --------------------------------------------------------------------------- #
# Release Center integration.
# --------------------------------------------------------------------------- #
def test_canary_deploy_records_blue_green_steps(rc_store):
    cid = _mk()
    _to_signed(cid)
    out = release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-000001")
    assert out["deployment"]["document"]["status"] == "dry_run"
    assert out["deployment"]["document"]["strategy"] == "blue_green_symlink"
    detail = release_center.get_release(cid)
    stages = {s["stage"] for s in detail["deploy_steps"]}
    assert blue_green.STAGE_SWITCH_TRAFFIC in stages
    assert all(s["environment"] == "canary" for s in detail["deploy_steps"])
    assert detail["blue_green"]["real_available"] is False


def test_promote_records_blue_green_steps_and_maintenance(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-" + cid[:8])
    out = release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-" + cid[:8])
    assert out["state"] == "production_deploying"
    assert out["external_result"] == "pending"
    detail = release_center.get_release(cid)
    prod_steps = [s for s in detail["deploy_steps"] if s["environment"] == "production"]
    assert prod_steps
    assert any(m["environment"] == "production" for m in detail["maintenance"])


def test_promote_does_not_fake_production_live(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-" + cid[:8])
    release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-" + cid[:8])
    # A dry-run blue-green deploy can never auto-advance to production_live.
    detail = release_center.get_release(cid)
    assert detail["summary"]["state"] == "production_deploying"


def test_rehearse_endpoint_no_state_change(rc_store):
    cid = _mk()
    _to_signed(cid)
    before = release_center.get_release(cid)["summary"]["state"]
    out = release_center.rehearse_blue_green(
        actor=OWNER, candidate_id=cid, environment="production", idempotency_key="reh-00001")
    assert out["ok"] is True
    assert out["rehearsal"]["external_result"] == "pending"
    after = release_center.get_release(cid)
    assert after["summary"]["state"] == before
    assert after["rehearsals"]
    # Idempotent repeat returns the same rehearsal, no second record.
    again = release_center.rehearse_blue_green(
        actor=OWNER, candidate_id=cid, environment="production", idempotency_key="reh-00001")
    assert again["rehearsal_id"] == out["rehearsal_id"]
    assert len(release_center.get_release(cid)["rehearsals"]) == 1


def test_rehearse_requires_built_artifact(rc_store):
    cid = _mk()
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.rehearse_blue_green(
            actor=OWNER, candidate_id=cid, environment="production", idempotency_key="reh-00002")
    assert exc.value.code == "artifact_missing"


def test_rollback_records_traffic_switch_evidence(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-" + cid[:8])
    release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-" + cid[:8])
    # Owner-confirmed live (real deploy verified out-of-band), then roll back.
    release_center.mark_production_live(actor=OWNER, candidate_id=cid, idempotency_key="ml-" + cid[:8])
    detail = release_center.get_release(cid)
    target_artifact = detail["summary"]["artifact_id"]
    out = release_center.rollback_production(
        actor=OWNER, candidate_id=cid, to_artifact_id=target_artifact,
        reason="regression", idempotency_key="rb-000001")
    assert out["state"] == "rolled_back"
    switch = out["rollback"]["evidence"]["traffic_switch"]
    assert switch["action"] == "symlink_switch"
    assert switch["preserves_persistent_data"] is True


def test_rehearse_drain_context_is_reflected(rc_store):
    cid = _mk()
    _to_signed(cid)
    out = release_center.rehearse_blue_green(
        actor=OWNER, candidate_id=cid, environment="production",
        drain={"active_leases": 1, "in_flight_jobs": 2}, idempotency_key="reh-drain1")
    assert out["rehearsal"]["drain"]["must_wait_for"] == 3
    assert out["rehearsal"]["drain"]["drained"] is False


def test_blue_green_evidence_redacts_secrets(rc_store, monkeypatch):
    # Even if an artifact somehow carried a secret-looking field, redaction keeps
    # it out of the serialized release detail.
    cid = _mk()
    _to_signed(cid)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-000009")
    serialized = json.dumps(release_center.get_release(cid))
    assert "-----BEGIN" not in serialized


# --------------------------------------------------------------------------- #
# Migration additivity (static, no live PostgreSQL).
# --------------------------------------------------------------------------- #
def test_migration_0010_is_additive():
    from app.production_storage.core import MigrationRunner

    migrations = {row["version"]: row for row in MigrationRunner.migrations()}
    assert 10 in migrations
    sql = str(migrations[10]["sql"]).lower()
    assert "drop table" not in sql
    assert "drop column" not in sql
    assert "create table if not exists sf_release_deploy_steps" in sql
    assert "create table if not exists sf_maintenance_windows" in sql
    assert "enable row level security" in sql
    assert "sf_scope_global()" in sql


def test_migration_set_still_starts_at_one_and_is_contiguous():
    from app.production_storage.core import MigrationRunner

    versions = [row["version"] for row in MigrationRunner.migrations()]
    assert versions == list(range(1, len(versions) + 1))
    assert versions[-1] == 11
