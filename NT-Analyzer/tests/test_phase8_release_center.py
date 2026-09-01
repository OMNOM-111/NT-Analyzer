"""Phase 8 — Release Center state machine, exact-artifact invariants, security.

These tests exercise the immutable-artifact promotion control plane directly (no
real build, deployment, network, secret or Production access) plus a few HTTP
permission contracts. The deployment adapter is always the fail-closed dry-run.
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, auth_identity, google_auth, permissions, release_center
from app import security_devices
from app import server as server_mod


OWNER_ID = 999


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
        "migration_count": 9,
    }


def _invalid_signature_builder(candidate, git_commit_sha):
    report = _fake_builder(candidate, git_commit_sha)
    report["signature_status"] = "invalid"
    return report


@pytest.fixture()
def rc_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", str(OWNER_ID))
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.delenv("STRATFORGE_RELEASE_DEPLOY_ADAPTER", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(google_auth, "_root", lambda: tmp_path)
    for mod in (account_auth.secure_store, google_auth.secure_store):
        monkeypatch.setattr(mod, "_protect", lambda b: b)
        monkeypatch.setattr(mod, "_unprotect", lambda b: b)
        monkeypatch.setattr(mod, "available", lambda: True)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    # Isolate the release store + audit to the temp dir.
    monkeypatch.setattr(release_center, "_store_path", lambda: tmp_path / "releases.dpapi")
    monkeypatch.setattr(release_center, "_audit_path", lambda: tmp_path / "release-audit.jsonl")
    monkeypatch.setattr(release_center, "_git_state", lambda: ("a" * 40, False))
    monkeypatch.setattr(release_center.release_summary, "summary_for", lambda version: {
        "title": "Test release", "description": "Test change summary",
        "points": ["Test user change"], "prs": ["#1"],
        "subsystems": "release", "release_impact": "test only",
        "source": "test.md",
    })
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


OWNER = {"user_id": OWNER_ID, "is_owner": True}


def _mk(actor=OWNER, version="0.10.0-dev.1", channel="dev", key="candidate-key-1"):
    return release_center.create_candidate(
        actor=actor, app_version=version, release_channel=channel,
        git_commit_sha="a" * 40, idempotency_key=key,
    )["candidate"]["candidate_id"]


def _to_signed(cid, builder=_fake_builder):
    release_center.build_release(actor=OWNER, candidate_id=cid, idempotency_key="b-" + cid[:8], builder=builder)
    release_center.verify_release(actor=OWNER, candidate_id=cid, idempotency_key="v-" + cid[:8])


def _to_canary_passed(cid):
    _to_signed(cid)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-" + cid[:8])
    release_center.record_canary_check(
        actor=OWNER, candidate_id=cid, name="acceptance", result="pass", final=True,
        idempotency_key="cc-" + cid[:8])


def _record_verified_production_executor(cid):
    """Unit-test fixture for the explicit post-deploy verification boundary."""
    doc = release_center._read_doc()
    deployment = next(
        d for d in doc["deployments"]
        if d.get("candidate_id") == cid and d.get("environment") == "production"
    )
    deployment["document"] = {
        **(deployment.get("document") or {}),
        "status": "pass",
        "external_result": "pass",
    }
    release_center._write_doc(doc)


def _enable_verified_rollback(monkeypatch):
    monkeypatch.setattr(release_center, "_adapter_status", lambda: {
        "name": "stage9_ssh", "real_configured": True, "real_available": True,
        "canary_available": True, "production_available": True,
        "mode": "real", "configuration_state": "ready",
    })
    monkeypatch.setattr(release_center.release_executor, "rollback_production", lambda current, target: {
        "status": "pass", "external_result": "pass", "rollback_verified": True,
    })


# --------------------------------------------------------------------------- #
# State machine.
# --------------------------------------------------------------------------- #
def test_full_happy_path(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-" + cid[:8])
    release_center.schedule_production(actor=OWNER, candidate_id=cid, mode="now", idempotency_key="sc-" + cid[:8])
    out = release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-" + cid[:8])
    assert out["state"] == "production_deploying"
    assert out["external_result"] == "pending"
    detail = release_center.get_release(cid)
    assert detail["summary"]["state"] == "production_deploying"
    assert detail["summary"]["production_state"] == "deploying"


def test_candidate_snapshots_the_release_change_record(rc_store):
    cid = _mk()
    record = release_center.get_release(cid)["summary"]["release_record"]
    assert record["title"] == "Test release"
    assert record["change_summary"] == "Test change summary"
    assert record["source_sha"] == "a" * 40
    assert record["verification_result"] == "PENDING"
    assert record["ready_for_production"] is False


def test_missing_release_record_blocks_production_approval(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    doc = release_center._read_doc()
    candidate = next(row for row in doc["candidates"] if row["candidate_id"] == cid)
    candidate["release_record"]["change_summary"] = ""
    release_center._write_doc(doc)
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.approve_production(
            actor=OWNER, candidate_id=cid, idempotency_key="missing-record-approval")
    assert exc.value.code == "release_record_incomplete"
    assert "change_summary" in str(exc.value)


def test_release_record_is_rechecked_at_promotion(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(
        actor=OWNER, candidate_id=cid, idempotency_key="record-approval-ok")
    doc = release_center._read_doc()
    candidate = next(row for row in doc["candidates"] if row["candidate_id"] == cid)
    candidate["release_record"]["source_sha"] = ""
    release_center._write_doc(doc)
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.promote_production(
            actor=OWNER, candidate_id=cid, idempotency_key="missing-record-promote")
    assert exc.value.code == "release_record_incomplete"


def test_invalid_transition_denied(rc_store):
    cid = _mk()
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="x-1234567")
    assert exc.value.code == "invalid_transition"


def test_idempotent_repeat_returns_same_candidate(rc_store):
    first = release_center.create_candidate(
        actor=OWNER, app_version="0.10.0-dev.1", release_channel="dev",
        git_commit_sha="a" * 40, idempotency_key="dup-key-123")
    second = release_center.create_candidate(
        actor=OWNER, app_version="0.10.0-dev.1", release_channel="dev",
        git_commit_sha="a" * 40, idempotency_key="dup-key-123")
    assert first["candidate"]["candidate_id"] == second["candidate"]["candidate_id"]


def test_concurrent_build_is_idempotent(rc_store):
    cid = _mk()
    results = []
    errors = []

    def worker():
        try:
            results.append(release_center.build_release(
                actor=OWNER, candidate_id=cid, idempotency_key="race-key-1", builder=_fake_builder))
        except release_center.ReleaseCenterError as exc:  # a losing racer may see immutable
            errors.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    detail = release_center.get_release(cid)
    # Exactly one artifact exists no matter how many concurrent builds ran.
    assert detail["summary"]["state"] == "built"
    assert len([a for a in [detail["artifact"]] if a.get("artifact_id")]) == 1


def test_double_deploy_is_rejected(rc_store):
    cid = _mk()
    _to_signed(cid)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-first-1")
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-second-1")
    assert exc.value.code == "invalid_transition"


def test_double_approval_is_rejected(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-first-1")
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-second-1")
    assert exc.value.code == "invalid_transition"


# --------------------------------------------------------------------------- #
# Build / dirty / immutability / checksums.
# --------------------------------------------------------------------------- #
def test_dirty_worktree_rejected_at_create(rc_store, monkeypatch):
    monkeypatch.setattr(release_center, "_git_state", lambda: ("a" * 40, True))
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.create_candidate(
            actor=OWNER, app_version="0.10.0-dev.1", release_channel="dev",
            git_commit_sha="a" * 40, idempotency_key="dirty-key-1")
    assert exc.value.code == "dirty_worktree"


def test_dirty_worktree_rejected_at_build(rc_store, monkeypatch):
    cid = _mk()
    monkeypatch.setattr(release_center, "_git_state", lambda: ("a" * 40, True))
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.build_release(actor=OWNER, candidate_id=cid, idempotency_key="db-key-1", builder=_fake_builder)
    assert exc.value.code == "dirty_worktree"
    assert release_center.get_release(cid)["summary"]["state"] == "build_failed"


def test_build_from_clean_commit_records_checksums(rc_store):
    cid = _mk()
    out = release_center.build_release(actor=OWNER, candidate_id=cid, idempotency_key="bk-000001", builder=_fake_builder)
    assert out["state"] == "built"
    assert out["artifact"]["artifact_sha256"] == "A" * 64
    assert out["artifact"]["manifest_sha256"] == "B" * 64
    assert out["artifact"]["immutable"] is True


def test_artifact_is_immutable(rc_store):
    cid = _mk()
    release_center.build_release(actor=OWNER, candidate_id=cid, idempotency_key="bk-000001", builder=_fake_builder)
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.build_release(actor=OWNER, candidate_id=cid, idempotency_key="bk-000002", builder=_fake_builder)
    assert exc.value.code == "artifact_immutable"


def test_invalid_signature_rejected(rc_store):
    cid = _mk()
    release_center.build_release(actor=OWNER, candidate_id=cid, idempotency_key="bk-000001", builder=_invalid_signature_builder)
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.verify_release(actor=OWNER, candidate_id=cid, idempotency_key="vk-000001")
    assert exc.value.code == "signature_invalid"


def test_manifest_tampering_rejected(rc_store):
    cid = _mk()
    _to_signed(cid)
    doc = release_center._read_doc()
    doc["artifacts"][0]["manifest_sha256"] = "C" * 64
    release_center._write_doc(doc)
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-tamper-1")
    assert exc.value.code == "artifact_mismatch"


# --------------------------------------------------------------------------- #
# Canary.
# --------------------------------------------------------------------------- #
def test_canary_deployment_record_is_dry_run(rc_store):
    cid = _mk()
    _to_signed(cid)
    out = release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-000001")
    assert out["state"] == "canary_checking"
    assert out["deployment"]["document"]["status"] == "dry_run"
    assert out["deployment"]["document"]["external_result"] == "pending"


def test_canary_check_fail_moves_to_failed(rc_store):
    cid = _mk()
    _to_signed(cid)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-000001")
    out = release_center.record_canary_check(
        actor=OWNER, candidate_id=cid, name="smoke", result="fail", idempotency_key="cc-000001")
    assert out["state"] == "canary_failed"


def test_canary_check_pass_moves_to_passed(rc_store):
    cid = _mk()
    _to_signed(cid)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-000001")
    out = release_center.record_canary_check(
        actor=OWNER, candidate_id=cid, name="acceptance", result="pass", final=True, idempotency_key="cc-000001")
    assert out["state"] == "canary_passed"


# --------------------------------------------------------------------------- #
# Exact-artifact Production promotion.
# --------------------------------------------------------------------------- #
def test_promotion_requires_matching_approval(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    # Tamper the stored approval fingerprint so it no longer matches the artifact.
    doc = release_center._read_doc()
    doc["approvals"][0]["artifact_sha256"] = "D" * 64
    release_center._write_doc(doc)
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    assert exc.value.code == "approval_artifact_mismatch"


def test_promotion_requires_active_approval(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    # Remove the approval to simulate a bypass attempt.
    doc = release_center._read_doc()
    doc["approvals"] = []
    release_center._write_doc(doc)
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    assert exc.value.code == "approval_required"


def test_promotion_without_approval_state_is_invalid(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    assert exc.value.code == "invalid_transition"


def test_promotion_does_not_auto_go_live(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    out = release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    assert out["state"] == "production_deploying"
    assert release_center.get_release(cid)["summary"]["state"] != "production_live"


def test_dry_run_cannot_be_confirmed_as_production_live(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-verify-1")
    release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-verify-1")
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.mark_production_live(actor=OWNER, candidate_id=cid, idempotency_key="lv-verify-1")
    assert exc.value.code == "production_deploy_unverified"


# --------------------------------------------------------------------------- #
# Rollback.
# --------------------------------------------------------------------------- #
def test_rollback_to_known_prod_artifact(rc_store, monkeypatch):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    _record_verified_production_executor(cid)
    release_center.mark_production_live(actor=OWNER, candidate_id=cid, idempotency_key="lv-000001")
    artifact_id = release_center.get_release(cid)["summary"]["artifact_id"]
    _enable_verified_rollback(monkeypatch)
    out = release_center.rollback_production(
        actor=OWNER, candidate_id=cid, to_artifact_id=artifact_id, reason="test",
        idempotency_key="rb-000001")
    assert out["state"] == "rolled_back"


def test_rollback_unknown_artifact_denied(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    _record_verified_production_executor(cid)
    release_center.mark_production_live(actor=OWNER, candidate_id=cid, idempotency_key="lv-000001")
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.rollback_production(
            actor=OWNER, candidate_id=cid, to_artifact_id="art_unknown", reason="x",
            idempotency_key="rb-000001")
    assert exc.value.code == "rollback_target_unknown"


def test_rollback_incompatible_artifact_denied(rc_store):
    # Build a second candidate/artifact that was never deployed to Production.
    other = _mk(key="other-candidate-1")
    release_center.build_release(actor=OWNER, candidate_id=other, idempotency_key="ob-000001", builder=_fake_builder)
    other_artifact = release_center.get_release(other)["summary"]["artifact_id"]

    cid = _mk(key="main-candidate-1")
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    _record_verified_production_executor(cid)
    release_center.mark_production_live(actor=OWNER, candidate_id=cid, idempotency_key="lv-000001")
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.rollback_production(
            actor=OWNER, candidate_id=cid, to_artifact_id=other_artifact, reason="x",
            idempotency_key="rb-000001")
    assert exc.value.code == "rollback_incompatible"


# --------------------------------------------------------------------------- #
# Scheduling + notifications + audit.
# --------------------------------------------------------------------------- #
def test_schedule_modes(rc_store):
    for mode, key in (("now", "sked0001"), ("in_5m", "sked0002"), ("in_15m", "sked0003")):
        cid = _mk(key="cand-" + key)
        _to_canary_passed(cid)
        release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-" + key)
        out = release_center.schedule_production(actor=OWNER, candidate_id=cid, mode=mode, idempotency_key="sc-" + key)
        assert out["mode"] == mode
        assert out["state"] == "production_scheduled"


def test_explicit_schedule_time(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    out = release_center.schedule_production(
        actor=OWNER, candidate_id=cid, mode="explicit", explicit_utc="2099-01-01T00:00:00Z",
        idempotency_key="sc-000001")
    assert out["mode"] == "explicit"


def test_market_close_option_disabled(rc_store):
    options = release_center.schedule_options()
    assert options["market_close"]["available"] is False
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.schedule_production(
            actor=OWNER, candidate_id=cid, mode="after_market_close", idempotency_key="sc-000001")
    assert exc.value.code == "market_calendar_unavailable"


def test_notifications_created_on_schedule(rc_store):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-000001")
    release_center.schedule_production(actor=OWNER, candidate_id=cid, mode="now", idempotency_key="sc-000001")
    kinds = {n["kind"] for n in release_center.get_release(cid)["notifications"]}
    assert {"scheduled_update", "warn_5m", "warn_60s", "deploy_started"} <= kinds


def test_audit_and_events_redact_secrets(rc_store):
    cid = _mk()
    _to_signed(cid)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-000001")
    release_center.record_canary_check(
        actor=OWNER, candidate_id=cid, name="acceptance", result="pass", final=True,
        evidence={"api_token": "supersecretvalue123", "count": 5}, idempotency_key="cc-000001")
    serialized = json.dumps(release_center.get_release(cid))
    assert "supersecretvalue123" not in serialized


def test_dry_run_adapter_never_reports_real_pass(rc_store):
    status = release_center.list_releases()["adapter"]
    assert status["real_available"] is False
    assert status["mode"] == "dry_run"


def test_configured_but_unavailable_adapter_fails_canary_without_checking(rc_store, monkeypatch):
    cid = _mk()
    _to_signed(cid)
    monkeypatch.setenv("STRATFORGE_RELEASE_DEPLOY_ADAPTER", "stage9_ssh")
    monkeypatch.delenv("STRATFORGE_RELEASE_SSH_HOST", raising=False)
    monkeypatch.delenv("STRATFORGE_RELEASE_SSH_KEY", raising=False)
    out = release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-blocked-1")
    assert out["ok"] is False
    assert out["state"] == "canary_failed"
    assert release_center.get_release(cid)["summary"]["state"] == "canary_failed"


def test_real_canary_pass_advances_to_acceptance_checks(rc_store, monkeypatch):
    cid = _mk()
    _to_signed(cid)
    monkeypatch.setattr(release_center.release_executor, "status", lambda: {
        "name": "stage9_ssh", "real_configured": True, "real_available": True,
        "canary_available": True, "production_available": False,
        "mode": "real", "configuration_state": "ready",
    })
    monkeypatch.setattr(release_center.release_executor, "deploy", lambda env, artifact: {
        "status": "pass", "external_result": "pass", "adapter": "stage9_ssh",
        "environment": env, "artifact_id": artifact["artifact_id"], "steps": [],
    })
    monkeypatch.setenv("STRATFORGE_RELEASE_DEPLOY_ADAPTER", "stage9_ssh")
    out = release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-realpass-1")
    assert out["ok"] is True
    assert out["state"] == "canary_checking"
    assert out["deployment"]["state"] == "deployed"


# --------------------------------------------------------------------------- #
# Step-up (non-owner delegated admin).
# --------------------------------------------------------------------------- #
def _make_delegated_admin(caps):
    uid = 4242
    admin_uuid = auth_identity.new_user_uuid()
    grants = {
        cap: {"enabled": True, "granted_at_utc": account_auth._now_iso(),
              "expires_at_utc": "", "granted_by": "test"}
        for cap in caps
    }
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc["users"].append({
            "user_id": uid, "user_uuid": admin_uuid, "username": "dev",
            "first_name": "Dev", "role": "read_only", "status": "active",
            "is_owner": False, "admin_permission_grants": grants,
        })
        account_auth._write_doc(doc)
    return uid, admin_uuid


def test_missing_step_up_denies_delegated_deploy(rc_store):
    uid, _ = _make_delegated_admin(["releases.view", "releases.deploy_canary"])
    cid = _mk()
    _to_signed(cid)
    actor = {"user_id": uid, "is_owner": False}
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.deploy_canary(actor=actor, candidate_id=cid, idempotency_key="dc-000001")
    assert exc.value.code == "step_up_required"


def test_step_up_grant_allows_delegated_deploy(rc_store):
    uid, admin_uuid = _make_delegated_admin(["releases.view", "releases.deploy_canary"])
    cid = _mk()
    _to_signed(cid)
    # Write a consumed step-up grant for the release deploy action.
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc.setdefault("security_challenges", []).append({
            "challenge_id": "chal-1", "user_uuid": admin_uuid, "legacy_user_id": uid,
            "purpose": security_devices.PURPOSE_STEP_UP,
            "action": release_center.ACTION_DEPLOY_CANARY,
            "environment": "development", "status": "consumed",
            "consumed_at_utc": account_auth._now_iso(),
        })
        account_auth._write_doc(doc)
    actor = {"user_id": uid, "is_owner": False}
    out = release_center.deploy_canary(actor=actor, candidate_id=cid, idempotency_key="dc-000001")
    assert out["state"] == "canary_checking"
    # The grant is single-use: a second critical action must not reuse it.
    with pytest.raises(release_center.ReleaseCenterError):
        release_center.deploy_canary(actor=actor, candidate_id=cid, idempotency_key="dc-2")


# --------------------------------------------------------------------------- #
# Migration additivity (static, no live PostgreSQL).
# --------------------------------------------------------------------------- #
def test_migration_0009_is_additive():
    from app.production_storage.core import MigrationRunner

    migrations = {row["version"]: row for row in MigrationRunner.migrations()}
    assert 9 in migrations
    sql = str(migrations[9]["sql"]).lower()
    assert "drop table" not in sql
    assert "create table if not exists sf_release_candidates" in sql
    assert "create table if not exists sf_release_artifacts" in sql
    assert "enable row level security" in sql
    assert "sf_scope_global()" in sql


# --------------------------------------------------------------------------- #
# HTTP permission contracts.
# --------------------------------------------------------------------------- #
def _token_row(user_id, token, csrf, **extra):
    row = {
        "session_id": "sess_" + token[:8],
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
        "csrf_token": csrf, "user_id": user_id,
        "created_at_utc": "2026-07-15T00:00:00Z", "expires_at": 4_000_000_000,
        "revoked": False, "device_id": "dev", "client": "Chrome", "machine": "PC",
        "ip": "127.0.0.1",
    }
    row.update(extra)
    return row


def _request(base, path, *, token="", csrf="", method="GET", body=None):
    data = None
    headers = {"Origin": base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


@pytest.fixture()
def rc_http(rc_store):
    account_auth.set_auth_required(True)
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        yield base
    finally:
        server.shutdown()
        account_auth.set_auth_required(False)


def test_ordinary_user_cannot_see_release_center(rc_http):
    uid = 5001
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc["users"].append({
            "user_id": uid, "user_uuid": auth_identity.new_user_uuid(), "username": "user",
            "first_name": "User", "role": "read_only", "status": "active", "is_owner": False,
            "ux_mode": "professional",
        })
        token, csrf = "u" * 64, "v" * 48
        doc["sessions"] = [_token_row(uid, token, csrf)]
        account_auth._write_doc(doc)
    status, _ = _request(rc_http, "/api/admin/releases", token=token, csrf=csrf)
    assert status == 403


def test_owner_can_list_releases(rc_http):
    token, csrf = "o" * 64, "p" * 48
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc["sessions"] = [_token_row(OWNER_ID, token, csrf)]
        account_auth._write_doc(doc)
    status, payload = _request(rc_http, "/api/admin/releases", token=token, csrf=csrf)
    assert status == 200
    assert payload["ok"] is True
    assert "releases" in payload


def test_delegated_viewer_cannot_create_candidate(rc_http):
    uid, _ = _make_delegated_admin(["releases.view"])
    token, csrf = "d" * 64, "e" * 48
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc["sessions"] = [_token_row(uid, token, csrf)]
        account_auth._write_doc(doc)
    # Can view.
    status, _ = _request(rc_http, "/api/admin/releases", token=token, csrf=csrf)
    assert status == 200
    # Cannot create (needs releases.create).
    status, payload = _request(
        rc_http, "/api/admin/releases/candidates", token=token, csrf=csrf, method="POST",
        body={"app_version": "0.10.0-dev.1", "release_channel": "dev", "idempotency_key": "http-key-1"})
    assert status == 403


def test_failed_canary_can_retry_the_same_artifact_without_rebuild(rc_store, monkeypatch):
    # An environment problem must not force a rebuild: the immutable artifact
    # is still valid, and the transition map already allows the retry.
    cid = _mk(key="canary-retry-key-1")
    _to_signed(cid)
    original_adapter = release_center._run_deploy_adapter

    def failing(environment, artifact):
        return {"status": "fail", "adapter": "test", "external_result": "fail",
                "environment": environment, "note": "health check failed"}

    monkeypatch.setattr(release_center, "_run_deploy_adapter", failing)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-retry-01")
    detail = release_center.get_release(cid)
    assert detail["summary"]["state"] == "canary_failed"
    artifact_before = detail["summary"]["artifact_sha256"]

    monkeypatch.setattr(release_center, "_run_deploy_adapter", original_adapter)
    release_center.deploy_canary(actor=OWNER, candidate_id=cid, idempotency_key="dc-retry-02")
    detail = release_center.get_release(cid)
    assert detail["summary"]["state"] in {"canary_deploying", "canary_checking"}
    assert detail["summary"]["artifact_sha256"] == artifact_before


# --------------------------------------------------------------------------- #
# A verified Production deploy must reach a terminal state, and an errored
# attempt must stay retryable.
#
# A promotion that errored before the executor reported an outcome left the
# candidate in production_deploying with nothing deployed: not live, not
# failed, and with no transition out of it. The retry was refused as an
# invalid transition, so the ledger disagreed with the live environment
# permanently.
# --------------------------------------------------------------------------- #
def _real_pass_adapter(monkeypatch):
    monkeypatch.setattr(release_center, "_run_deploy_adapter", lambda env, artifact: {
        "status": "pass", "external_result": "pass", "verified": True,
    })


def _stuck_adapter(monkeypatch):
    """Neither pass nor fail -- exactly what an errored attempt records."""
    monkeypatch.setattr(release_center, "_run_deploy_adapter", lambda env, artifact: {
        "status": "pending", "external_result": "pending",
    })


def test_verified_production_deploy_reaches_production_live(rc_store, monkeypatch):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-" + cid[:8])
    _real_pass_adapter(monkeypatch)
    out = release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-" + cid[:8])
    assert out["state"] == "production_live"
    detail = release_center.get_release(cid)
    assert detail["summary"]["state"] == "production_live"
    assert detail["summary"]["production_state"] == "live"


def test_an_errored_promotion_stays_retryable(rc_store, monkeypatch):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-" + cid[:8])
    _stuck_adapter(monkeypatch)
    first = release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    assert first["state"] == "production_deploying"
    # Nothing landed, so the retry must be allowed rather than refused.
    _real_pass_adapter(monkeypatch)
    second = release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000002")
    assert second["state"] == "production_live"
    assert release_center.get_release(cid)["summary"]["state"] == "production_live"


def test_a_landed_deploy_is_not_promoted_twice(rc_store, monkeypatch):
    cid = _mk()
    _to_canary_passed(cid)
    release_center.approve_production(actor=OWNER, candidate_id=cid, idempotency_key="ap-" + cid[:8])
    _real_pass_adapter(monkeypatch)
    release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000001")
    # production_live is terminal; a fresh promotion is an invalid transition.
    with pytest.raises(release_center.ReleaseCenterError) as exc:
        release_center.promote_production(actor=OWNER, candidate_id=cid, idempotency_key="pr-000002")
    assert exc.value.code == "invalid_transition"
