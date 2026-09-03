"""Phase 6: agent allocation and shared-NinjaTrader durable resource lease/queue.

Covers atomic acquire, exclusive conflict, FIFO ordering, idempotent enqueue,
TTL/heartbeat/recovery, release/cancel, concurrent races, read-only parallelism,
ownership/UUID isolation, stale tokens, personal-vs-shared isolation, agent
allocation, anonymized user status, owner/admin detail and the migration
contract. PostgreSQL acceptance is gated separately by real DSNs.
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, agent_allocation, ninjatrader_resources, workspaces
from app import server as server_mod

OWNER_UUID = "00000000-0000-4000-8000-000000000999"
ALICE_UUID = "00000000-0000-4000-8000-000000000042"  # personal NinjaTrader
BOB_UUID = "00000000-0000-4000-8000-000000000007"    # owner-training viewer
CAROL_UUID = "00000000-0000-4000-8000-000000000008"  # owner-training viewer
PERSONAL_WS = "ws_personal_ALICE0001"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    for mod in (account_auth, workspaces):
        monkeypatch.setattr(mod.secure_store, "available", lambda: True)
        monkeypatch.setattr(mod.secure_store, "_protect", lambda v: v)
        monkeypatch.setattr(mod.secure_store, "_unprotect", lambda v: v)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    account_auth._write_doc({
        "version": 3,
        "users": [
            {"user_id": 999, "user_uuid": OWNER_UUID, "username": "owner", "first_name": "Owner",
             "role": "owner", "status": "active", "is_owner": True, "telegram_user_id": 999},
            {"user_id": 42, "user_uuid": ALICE_UUID, "username": "alice", "first_name": "Alice",
             "role": "full_control", "status": "active", "is_owner": False, "telegram_user_id": 42,
             "ux_mode": "professional"},
            {"user_id": 7, "user_uuid": BOB_UUID, "username": "bob", "first_name": "Bob",
             "role": "read_only", "status": "active", "is_owner": False, "telegram_user_id": 7,
             "ux_mode": "professional"},
            {"user_id": 8, "user_uuid": CAROL_UUID, "username": "carol", "first_name": "Carol",
             "role": "read_only", "status": "active", "is_owner": False, "telegram_user_id": 8,
             "ux_mode": "professional"},
        ],
        "auth_identities": [], "challenges": [], "sessions": [],
        "trusted_devices": [], "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    owner_ws = workspaces._owner_workspace_id(999)
    workspaces._write_doc({
        "version": 2,
        "workspaces": [
            {"workspace_id": owner_ws, "kind": "owner_training", "owner_user_id": 999,
             "status": "active", "default_runtime_connection_id": "owner_local",
             "entitlement_id": "founder", "display_name": "Owner NinjaTrader"},
            {"workspace_id": PERSONAL_WS, "kind": "personal", "owner_user_id": 42,
             "status": "active", "default_runtime_connection_id": "conn_alice",
             "entitlement_id": "pro", "display_name": "Alice NinjaTrader"},
        ],
        "memberships": [
            {"workspace_id": owner_ws, "user_id": 999, "role": "owner", "created_by_user_id": 999},
            {"workspace_id": owner_ws, "user_id": 7, "role": "viewer", "created_by_user_id": 999},
            {"workspace_id": owner_ws, "user_id": 8, "role": "viewer", "created_by_user_id": 999},
            {"workspace_id": PERSONAL_WS, "user_id": 42, "role": "owner", "created_by_user_id": 42},
        ],
        "active_workspaces": {"999": owner_ws, "7": owner_ws, "8": owner_ws, "42": PERSONAL_WS},
        "active_workspaces_by_uuid": {},
        "connections": [], "pairings": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    return {"tmp": tmp_path, "owner_ws": owner_ws, "owner_resource": f"owner_training:{owner_ws}"}


def _enqueue(uid, op="backtest", *, key, group="exclusive", is_owner=False, workspace_id=""):
    return ninjatrader_resources.enqueue_job(
        uid, operation_kind=op, idempotency_key=key, parallel_group=group,
        is_owner=is_owner, workspace_id=workspace_id,
    )


# --------------------------------------------------------------------------- #
# Enqueue / FIFO / idempotency.
# --------------------------------------------------------------------------- #
def test_enqueue_owner_training_queued(store):
    out = _enqueue(7, key="bob-backtest-001")
    assert out["state"] == "queued"
    assert out["resource_id"] == store["owner_resource"]
    assert out["position"] == 1
    assert out["shared"] is True


def test_fifo_ordering(store):
    first = _enqueue(7, key="bob-fifo-1")
    second = _enqueue(8, key="carol-fifo-1")
    claimed = ninjatrader_resources.claim_next(store["owner_resource"])
    assert claimed["available"] is True
    assert claimed["job_id"] == first["job_id"]
    assert second["position"] == 2


def test_idempotent_enqueue_no_duplicate(store):
    a = _enqueue(7, key="bob-same")
    b = _enqueue(7, key="bob-same")
    assert a["job_id"] == b["job_id"]
    assert b["idempotent"] is True


def test_operation_not_allowed_owner_training(store):
    with pytest.raises(ninjatrader_resources.NinjaTraderResourceError) as exc:
        _enqueue(7, op="optimization", key="bob-optim")
    assert exc.value.code == "operation_not_allowed_here"


# --------------------------------------------------------------------------- #
# Exclusive conflict / atomic acquire.
# --------------------------------------------------------------------------- #
def test_exclusive_single_active(store):
    _enqueue(7, key="bob-excl-x")
    _enqueue(8, key="carol-excl-x")
    first = ninjatrader_resources.claim_next(store["owner_resource"])
    assert first["available"] is True
    second = ninjatrader_resources.claim_next(store["owner_resource"])
    # An exclusive job is already active: no second active on the same resource.
    assert second["available"] is False


def test_concurrent_claim_single_winner(store):
    _enqueue(7, key="bob-conc-c")
    _enqueue(8, key="carol-conc-c")
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(ninjatrader_resources.claim_next(store["owner_resource"]))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    claimed = [r for r in results if r.get("available")]
    assert len(claimed) == 1


# --------------------------------------------------------------------------- #
# Read-only parallelism.
# --------------------------------------------------------------------------- #
def test_readonly_parallelism_owner(store):
    a = _enqueue(999, op="telemetry_read", key="own-ro-1", group="readonly", is_owner=True)
    b = _enqueue(999, op="telemetry_read", key="own-ro-2", group="readonly", is_owner=True)
    first = ninjatrader_resources.claim_next(store["owner_resource"])
    second = ninjatrader_resources.claim_next(store["owner_resource"])
    assert first["available"] is True
    assert second["available"] is True
    assert {first["job_id"], second["job_id"]} == {a["job_id"], b["job_id"]}


def test_readonly_classification_required(store):
    with pytest.raises(ninjatrader_resources.NinjaTraderResourceError) as exc:
        _enqueue(7, op="backtest", key="bob-ro-bad", group="readonly")
    assert exc.value.code == "parallel_not_allowed"


def test_exclusive_blocks_after_readonly(store):
    _enqueue(999, op="telemetry_read", key="owner-ro-001", group="readonly", is_owner=True)
    _enqueue(999, op="backtest", key="owner-excl-x", group="exclusive", is_owner=True)
    ro = ninjatrader_resources.claim_next(store["owner_resource"])
    assert ro["available"] is True
    # An exclusive job cannot start while a read-only lease is active.
    ex = ninjatrader_resources.claim_next(store["owner_resource"])
    assert ex["available"] is False


# --------------------------------------------------------------------------- #
# Heartbeat / TTL / recovery / release / stale token.
# --------------------------------------------------------------------------- #
def test_heartbeat_and_release_lifecycle(store):
    _enqueue(7, key="bob-hb-001")
    claim = ninjatrader_resources.claim_next(store["owner_resource"])
    token = claim["lease_token"]
    hb = ninjatrader_resources.heartbeat(claim["job_id"], lease_token=token)
    assert hb["ok"] is True
    rel = ninjatrader_resources.release(claim["job_id"], lease_token=token)
    assert rel["state"] == "released"
    # Stale token no longer works after release.
    with pytest.raises(ninjatrader_resources.NinjaTraderResourceError) as exc:
        ninjatrader_resources.heartbeat(claim["job_id"], lease_token=token)
    assert exc.value.code == "lease_not_active"


def test_heartbeat_wrong_token_rejected(store):
    _enqueue(7, key="bob-hb-002")
    claim = ninjatrader_resources.claim_next(store["owner_resource"])
    with pytest.raises(ninjatrader_resources.NinjaTraderResourceError) as exc:
        ninjatrader_resources.heartbeat(claim["job_id"], lease_token="not-the-token")
    assert exc.value.code == "lease_token_invalid"


def test_worker_crash_recovery(store):
    _enqueue(7, key="bob-crash")
    _enqueue(8, key="carol-next")
    claim = ninjatrader_resources.claim_next(store["owner_resource"])
    # Simulate a crashed worker: force the active lease past its expiry.
    doc = workspaces._read_doc()
    lease = next(l for l in doc[ninjatrader_resources._KEY] if l["job_id"] == claim["job_id"])
    lease["expires_at"] = 1.0
    workspaces._write_doc(doc)
    recovered = ninjatrader_resources.recover_expired(store["owner_resource"])
    assert recovered["recovered"] >= 1
    # The queue is no longer blocked: the next job can be claimed.
    nxt = ninjatrader_resources.claim_next(store["owner_resource"])
    assert nxt["available"] is True
    assert nxt["job_id"] != claim["job_id"]


def test_expired_lease_no_double_execution(store):
    _enqueue(7, key="bob-expiry-1")
    claim = ninjatrader_resources.claim_next(store["owner_resource"])
    doc = workspaces._read_doc()
    lease = next(l for l in doc[ninjatrader_resources._KEY] if l["job_id"] == claim["job_id"])
    lease["expires_at"] = 1.0
    workspaces._write_doc(doc)
    ninjatrader_resources.recover_expired(store["owner_resource"])
    # The old worker's heartbeat now fails; it cannot keep running.
    with pytest.raises(ninjatrader_resources.NinjaTraderResourceError):
        ninjatrader_resources.heartbeat(claim["job_id"], lease_token=claim["lease_token"])


# --------------------------------------------------------------------------- #
# Cancel / ownership.
# --------------------------------------------------------------------------- #
def test_cancel_own_job(store):
    out = _enqueue(7, key="bob-cancel")
    cancelled = ninjatrader_resources.cancel_job(7, job_id=out["job_id"])
    assert cancelled["state"] == "cancelled"


def test_cannot_cancel_other_users_job(store):
    out = _enqueue(7, key="bob-owned")
    with pytest.raises(ninjatrader_resources.NinjaTraderResourceError) as exc:
        ninjatrader_resources.cancel_job(8, job_id=out["job_id"])
    assert exc.value.code == "job_not_found"


def test_cancel_active_prevents_double_run(store):
    _enqueue(7, key="bob-cancel-active")
    claim = ninjatrader_resources.claim_next(store["owner_resource"])
    ninjatrader_resources.cancel_job(7, job_id=claim["job_id"])
    with pytest.raises(ninjatrader_resources.NinjaTraderResourceError):
        ninjatrader_resources.heartbeat(claim["job_id"], lease_token=claim["lease_token"])


def test_owner_can_cancel_any(store):
    out = _enqueue(7, key="bob-ownercancel")
    cancelled = ninjatrader_resources.cancel_job(999, job_id=out["job_id"], is_owner=True)
    assert cancelled["state"] == "cancelled"


# --------------------------------------------------------------------------- #
# Personal isolation / UUID boundary.
# --------------------------------------------------------------------------- #
def test_personal_job_never_uses_owner_runtime(store):
    personal = _enqueue(42, op="optimization", key="alice-optim")
    assert personal["resource_id"].startswith("personal:")
    assert personal["resource_id"] != store["owner_resource"]
    # A busy shared resource does not block the independent personal resource.
    _enqueue(7, key="bob-busy")
    ninjatrader_resources.claim_next(store["owner_resource"])
    claim_personal = ninjatrader_resources.claim_next(personal["resource_id"])
    assert claim_personal["available"] is True


def test_requested_by_is_uuid(store):
    out = _enqueue(7, key="bob-uuid")
    doc = workspaces._read_doc()
    lease = next(l for l in doc[ninjatrader_resources._KEY] if l["job_id"] == out["job_id"])
    assert lease["requested_by_user_id"] == BOB_UUID


def test_enqueue_requires_membership(store):
    # User 8 is a member of owner-training but not of Alice's personal workspace.
    with pytest.raises(workspaces.WorkspaceError):
        _enqueue(8, key="carol-personal", workspace_id=PERSONAL_WS)


# --------------------------------------------------------------------------- #
# Agent allocation.
# --------------------------------------------------------------------------- #
def test_allocation_owner_training_limited_coordinator(store):
    context = {"is_owner": False, "active_workspace": {
        "workspace_id": store["owner_ws"], "kind": "owner_training", "uses_owner_runtime": True}}
    alloc = agent_allocation.resolve_allocation(context)
    assert alloc["team_kind"] == "owner_training_coordinator"
    assert alloc["coordinator"] == "Координатор"
    assert alloc["agents"] == ["Координатор"]
    assert alloc["administrative"] is False
    assert set(alloc["allowed_operations"]) == {"training", "backtest"}


def test_allocation_personal_isolated_team(store):
    context = {"is_owner": False, "active_workspace": {
        "workspace_id": PERSONAL_WS, "kind": "personal", "uses_owner_runtime": False}}
    alloc = agent_allocation.resolve_allocation(context)
    assert alloc["team_kind"] == "personal_team"
    assert alloc["isolated"] is True
    assert alloc["uses_owner_runtime"] is False
    assert "Координатор" not in alloc["agents"]
    assert len(alloc["agents"]) > 1


def test_allocation_owner_full_team(store):
    context = {"is_owner": True, "active_workspace": {
        "workspace_id": store["owner_ws"], "kind": "owner_training", "uses_owner_runtime": True}}
    alloc = agent_allocation.resolve_allocation(context)
    assert alloc["team_kind"] == "owner_team"
    assert alloc["administrative"] is True
    assert "Виктор" in alloc["agents"]


# --------------------------------------------------------------------------- #
# Status views: anonymized user vs owner/admin detail.
# --------------------------------------------------------------------------- #
def test_status_is_anonymized(store):
    _enqueue(7, key="bob-status")
    ninjatrader_resources.claim_next(store["owner_resource"])
    status = ninjatrader_resources.resource_status(8)  # Carol observes
    assert status["busy"] is True
    assert status["state"] == "busy"
    text = json.dumps(status, ensure_ascii=False)
    # No other user's identity, workspace, uuid or token leaks to the observer.
    assert BOB_UUID not in text
    assert store["owner_ws"] not in text
    assert "lease_token" not in text
    assert "bob" not in text


def test_status_own_position(store):
    _enqueue(7, key="bob-first")
    ninjatrader_resources.claim_next(store["owner_resource"])
    carol = _enqueue(8, key="carol-queued")
    status = ninjatrader_resources.resource_status(8)
    assert status["state"] == "queued"
    assert status["your_job"]["job_id"] == carol["job_id"]
    assert status["your_job"]["position"] >= 1


def test_admin_detail_has_operational_metadata(store):
    _enqueue(7, key="bob-admin")
    detail = ninjatrader_resources.admin_resource_detail(resource_id=store["owner_resource"])
    assert detail["leases"]
    assert detail["leases"][0]["requested_by_user_id"] == BOB_UUID
    assert "lease_token" not in json.dumps(detail)


# --------------------------------------------------------------------------- #
# Migration static contract.
# --------------------------------------------------------------------------- #
def test_migration_0008_is_additive():
    from app.production_storage.core import MigrationRunner

    migrations = {row["version"]: row for row in MigrationRunner.migrations()}
    assert 8 in migrations
    sql = str(migrations[8]["sql"]).lower()
    assert "drop table" not in sql
    assert "create table if not exists sf_ninjatrader_resource_leases" in sql
    assert "enable row level security" in sql
    assert "one_active_exclusive" in sql
    assert "lease_token_hash" in sql


# --------------------------------------------------------------------------- #
# HTTP contract: self-service enqueue, capability-gated worker, anonymized.
# --------------------------------------------------------------------------- #
def _login(uid):
    out = account_auth.create_session_for_user(
        uid, ip="203.0.113.5", user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/120",
        require_google=False, skip_dual_auth_gate=True,
        device_confirmation_required=False,
    )
    return out["session_token"]


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
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _serve():
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{server.server_address[0]}:{server.server_address[1]}"


def test_http_allocation_and_enqueue_owner_training(store):
    account_auth.set_auth_required(True)
    token = _login(7)
    ctx = account_auth.authenticate_session(token)
    csrf = ctx["csrf_token"]
    server, base = _serve()
    try:
        _, alloc = _request(base, "/api/ninjatrader/allocation", token=token)
        assert alloc["allocation"]["team_kind"] == "owner_training_coordinator"
        status, out = _request(base, "/api/ninjatrader/jobs", token=token, csrf=csrf,
                               method="POST", body={"operation_kind": "backtest",
                                                    "idempotency_key": "http-bob-001"})
        assert status == 200
        assert out["state"] == "queued"
    finally:
        server.shutdown()
        server.server_close()


def test_http_worker_claim_denied_for_ordinary_user(store):
    account_auth.set_auth_required(True)
    token = _login(7)
    ctx = account_auth.authenticate_session(token)
    csrf = ctx["csrf_token"]
    server, base = _serve()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/ninjatrader/worker/claim", token=token, csrf=csrf,
                     method="POST", body={"resource_id": store["owner_resource"]})
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
