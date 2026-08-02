from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import production_workers
from app.production_storage import (
    CommandRepository,
    MigrationRunner,
    Scope,
    StorageConflictError,
)
from app.production_storage.core import PostgresClient, _jsonb, _psycopg


ADMIN_URL = os.environ.get("STRATFORGE_TEST_POSTGRES_ADMIN_URL", "")
APP_URL = os.environ.get("STRATFORGE_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_URL,
    reason="set STRATFORGE_TEST_POSTGRES_ADMIN_URL and STRATFORGE_TEST_POSTGRES_URL",
)


@pytest.fixture()
def worker_store():
    MigrationRunner(ADMIN_URL).apply()
    psycopg = _psycopg()
    workspace_ids = [f"ws_stage7_{suffix}000000" for suffix in "ABCDE"]
    user_ids = [77001, 77002, 77003, 77004, 77005]
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM sf_jobs")
        conn.execute("DELETE FROM sf_commands")
        conn.execute("DELETE FROM sf_idempotency_keys")
        conn.execute("DELETE FROM sf_rate_limit_buckets")
        conn.execute("DELETE FROM sf_queue_workspace_state")
        conn.execute("DELETE FROM sf_workspace_queue_quotas")
        conn.execute("DELETE FROM sf_workspaces WHERE workspace_id = ANY(%s)", (workspace_ids,))
        conn.execute("DELETE FROM sf_users WHERE user_id = ANY(%s)", (user_ids,))
        for user_id in user_ids:
            conn.execute(
                """INSERT INTO sf_users(user_id,status,is_owner,document)
                   VALUES(%s,'active',FALSE,%s)""",
                (
                    user_id,
                    _jsonb({
                        "user_id": user_id, "status": "active",
                        "role": "full_control", "is_owner": False,
                    }),
                ),
            )
        for workspace_id, user_id in zip(workspace_ids, user_ids):
            conn.execute(
                """INSERT INTO sf_workspaces(
                     workspace_id,owner_user_id,status,kind,document
                   ) VALUES(%s,%s,'active','personal',%s)""",
                (
                    workspace_id, user_id,
                    _jsonb({"workspace_id": workspace_id, "owner_user_id": user_id}),
                ),
            )
            conn.execute(
                """INSERT INTO sf_workspace_memberships(
                     workspace_id,user_id,role,document
                   ) VALUES(%s,%s,'owner',%s)""",
                (
                    workspace_id, user_id,
                    _jsonb({"workspace_id": workspace_id, "user_id": user_id, "role": "owner"}),
                ),
            )
    client = PostgresClient(APP_URL, production=False)
    queue = production_workers.ProductionQueue(client)
    queue.ensure_defaults()
    yield {
        "client": client,
        "queue": queue,
        "workspaces": workspace_ids,
        "users": user_ids,
        "admin": psycopg,
    }
    production_workers.reset_for_tests()
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM sf_jobs")
        conn.execute("DELETE FROM sf_commands")
        conn.execute("DELETE FROM sf_idempotency_keys")
        conn.execute("DELETE FROM sf_rate_limit_buckets")
        conn.execute("DELETE FROM sf_queue_workspace_state")
        conn.execute("DELETE FROM sf_workspace_queue_quotas")
        conn.execute("DELETE FROM sf_workspaces WHERE workspace_id = ANY(%s)", (workspace_ids,))
        conn.execute("DELETE FROM sf_users WHERE user_id = ANY(%s)", (user_ids,))


def _scope(store, index: int) -> Scope:
    return Scope(
        user_id=store["users"][index],
        workspace_id=store["workspaces"][index],
    )


def _enqueue(store, index: int, key: str, **kwargs):
    return store["queue"].enqueue(
        "noop", kwargs.pop("payload", {}), scope=_scope(store, index),
        idempotency_key=key, **kwargs,
    )


def test_worker_migration_and_class_contract(worker_store) -> None:
    plan = MigrationRunner(ADMIN_URL).plan()
    assert plan["applied_versions"] == [1, 2, 3, 4, 5, 6, 7]
    assert plan["pending"] == []
    configs = worker_store["queue"].class_configs()
    assert set(configs) == set(production_workers.DEFAULT_WORKER_CLASSES)
    assert all(row["enabled"] for row in configs.values())


def test_enqueue_is_idempotent_and_enforces_payload_and_workspace_quota(worker_store) -> None:
    queue = worker_store["queue"]
    first = _enqueue(worker_store, 0, "worker:idempotent:0001", payload={"value": 1})
    replay = _enqueue(worker_store, 0, "worker:idempotent:0001", payload={"value": 1})
    assert replay["job_id"] == first["job_id"]
    assert replay["idempotent_replay"] is True
    with pytest.raises(production_workers.QueueIdempotencyConflict):
        _enqueue(worker_store, 0, "worker:idempotent:0001", payload={"value": 2})
    with pytest.raises(production_workers.QueuePayloadTooLarge):
        _enqueue(worker_store, 0, "worker:payload:oversize", payload={"value": "x" * 70000})

    with queue.client.transaction(_scope(worker_store, 0)) as conn:
        conn.execute(
            """UPDATE sf_workspace_queue_quotas SET max_queued=1
               WHERE workspace_id=%s AND worker_class='maintenance'""",
            (worker_store["workspaces"][0],),
        )
    with pytest.raises(production_workers.QueueQuotaExceeded):
        _enqueue(worker_store, 0, "worker:quota:0002")


def test_round_robin_fairness_across_workspaces(worker_store) -> None:
    queue = worker_store["queue"]
    for round_no in range(2):
        for index in range(3):
            _enqueue(worker_store, index, f"fair:{index}:{round_no}:0000")
    claimed_workspaces = []
    for number in range(6):
        claimed = queue.claim("maintenance", worker_id=f"fair-worker-{number}")
        assert claimed is not None
        claimed_workspaces.append(claimed["workspace_id"])
        completed = queue.complete(
            claimed["job_id"], {"ok": True}, worker_id=f"fair-worker-{number}",
            lease_token=claimed["lease_token"],
        )
        assert completed["status"] == "succeeded"
    assert claimed_workspaces == [
        worker_store["workspaces"][0], worker_store["workspaces"][1],
        worker_store["workspaces"][2], worker_store["workspaces"][0],
        worker_store["workspaces"][1], worker_store["workspaces"][2],
    ]


def test_claim_is_atomic_across_competing_workers(worker_store) -> None:
    queue = worker_store["queue"]
    _enqueue(worker_store, 0, "atomic:claim:0001")
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(
            lambda number: queue.claim("maintenance", worker_id=f"atomic-{number}"),
            range(8),
        ))
    claimed = [row for row in rows if row]
    assert len(claimed) == 1
    row = claimed[0]
    assert queue.complete(
        row["job_id"], {"ok": True}, worker_id=row["lease_owner"],
        lease_token=row["lease_token"],
    )["status"] == "succeeded"


def test_retry_dead_letter_and_dangerous_no_retry(worker_store) -> None:
    queue = worker_store["queue"]
    _enqueue(worker_store, 0, "retry:normal:0001", max_attempts=2)
    first = queue.claim("maintenance", worker_id="retry-worker-1")
    retried = queue.fail(
        first["job_id"], "provider outage", worker_id="retry-worker-1",
        lease_token=first["lease_token"], error_class="provider_outage",
    )
    assert retried["status"] == "queued"
    with queue.client.transaction(Scope.global_service_scope()) as conn:
        conn.execute(
            "UPDATE sf_jobs SET available_at=clock_timestamp() WHERE job_id=%s",
            (first["job_id"],),
        )
    second = queue.claim("maintenance", worker_id="retry-worker-2")
    terminal = queue.fail(
        second["job_id"], "provider still unavailable", worker_id="retry-worker-2",
        lease_token=second["lease_token"], error_class="provider_outage",
    )
    assert terminal["status"] == "failed"
    assert terminal["queue_status"] == "dead_letter"
    assert terminal["attempts"] == 2

    dangerous = _enqueue(
        worker_store, 1, "dangerous:exactly-once:0001",
        max_attempts=10, dangerous=True,
    )
    assert dangerous["max_attempts"] == 1
    claimed = queue.claim("maintenance", worker_id="danger-worker")
    dead = queue.fail(
        claimed["job_id"], "uncertain downstream state", worker_id="danger-worker",
        lease_token=claimed["lease_token"], error_class="uncertain_side_effect",
    )
    assert dead["queue_status"] == "dead_letter"
    assert queue.claim("maintenance", worker_id="danger-retry") is None


def test_running_cancellation_is_cooperative_and_late_finish_is_rejected(worker_store) -> None:
    queue = worker_store["queue"]
    job = _enqueue(worker_store, 0, "cancel:running:0001")
    claimed = queue.claim("maintenance", worker_id="cancel-worker")
    cancelled = queue.cancel(job["job_id"], scope=_scope(worker_store, 0))
    assert cancelled["cancel_requested"] is True
    terminal = queue.complete(
        job["job_id"], {"should_not": "commit"}, worker_id="cancel-worker",
        lease_token=claimed["lease_token"],
    )
    assert terminal["status"] == "cancelled"
    late = queue.complete(
        job["job_id"], {"late": True}, worker_id="cancel-worker",
        lease_token=claimed["lease_token"],
    )
    assert late["status"] == "cancelled"
    assert not late["result"]


def test_crashed_worker_lease_is_recovered_and_restarted(worker_store) -> None:
    queue = worker_store["queue"]
    job = _enqueue(worker_store, 0, "crash:recovery:0001", max_attempts=2)
    first = queue.claim("maintenance", worker_id="crashed-worker")
    with queue.client.transaction(Scope.global_service_scope()) as conn:
        conn.execute(
            "UPDATE sf_jobs SET leased_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",
            (job["job_id"],),
        )
    assert queue.sweep_stale() == 1
    with queue.client.transaction(Scope.global_service_scope()) as conn:
        conn.execute(
            "UPDATE sf_jobs SET available_at=clock_timestamp() WHERE job_id=%s",
            (job["job_id"],),
        )
    second = queue.claim("maintenance", worker_id="replacement-worker")
    assert second["attempts"] == 2
    assert second["lease_token"] != first["lease_token"]
    done = queue.complete(
        job["job_id"], {"recovered": True}, worker_id="replacement-worker",
        lease_token=second["lease_token"],
    )
    assert done["status"] == "succeeded"


def test_shared_rate_limit_is_atomic_across_connections(worker_store) -> None:
    subject = "rate-test-" + uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=10) as pool:
        rows = list(pool.map(
            lambda _number: production_workers.consume_rate_limit(
                subject, "test.rate", limit=5, period_sec=60,
                client=worker_store["client"],
            ),
            range(10),
        ))
    assert sum(1 for row in rows if row["allowed"]) == 5
    assert sorted(row["count"] for row in rows) == list(range(1, 11))
    with worker_store["client"].transaction(Scope.global_service_scope(), read_only=True) as conn:
        stored = conn.execute(
            "SELECT subject_hash FROM sf_rate_limit_buckets WHERE action_class='test.rate'"
        ).fetchone()
    assert stored["subject_hash"] == hashlib.sha256(subject.encode()).hexdigest()
    assert subject not in stored["subject_hash"]


def test_shared_idempotency_reservation_and_conflict(worker_store) -> None:
    scope = _scope(worker_store, 0)
    key = "shared:idempotency:0001"
    request_hash = hashlib.sha256(b"same-request").hexdigest()
    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = list(pool.map(
            lambda _number: production_workers.reserve_idempotency(
                scope=scope, operation="test.dangerous", key=key,
                request_hash=request_hash, client=worker_store["client"],
            ),
            range(12),
        ))
    assert sum(1 for row in rows if row["reserved"]) == 1
    production_workers.complete_idempotency(
        scope=scope, operation="test.dangerous", key=key,
        request_hash=request_hash, response={"command_id": "cmd_once"},
        client=worker_store["client"],
    )
    replay = production_workers.reserve_idempotency(
        scope=scope, operation="test.dangerous", key=key,
        request_hash=request_hash, client=worker_store["client"],
    )
    assert replay["replay"] is True
    assert replay["response"] == {"command_id": "cmd_once"}
    with pytest.raises(production_workers.QueueIdempotencyConflict):
        production_workers.reserve_idempotency(
            scope=scope, operation="test.dangerous", key=key,
            request_hash=hashlib.sha256(b"different").hexdigest(),
            client=worker_store["client"],
        )


def test_dangerous_command_repository_never_creates_duplicate(worker_store) -> None:
    repository = CommandRepository(worker_store["client"])
    scope = _scope(worker_store, 0)
    envelope_hash = hashlib.sha256(b"paper-command").hexdigest()

    def put(number: int):
        return repository.put({
            "command_id": f"cmd_stage7_{number:04d}",
            "workspace_id": scope.workspace_id,
            "user_id": scope.user_id,
            "command_type": "enable_strategy",
            "status": "queued",
            "dangerous": True,
            "idempotency_key": "paper:command:exactly-once",
            "envelope_hash": envelope_hash,
        }, scope=scope)

    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = list(pool.map(put, range(12)))
    assert sum(1 for row in rows if not row.get("idempotent_replay")) == 1
    with worker_store["client"].transaction(scope, read_only=True) as conn:
        count = conn.execute(
            """SELECT count(*) AS count FROM sf_commands
               WHERE workspace_id=%s AND idempotency_key=%s""",
            (scope.workspace_id, "paper:command:exactly-once"),
        ).fetchone()["count"]
    assert count == 1
    with pytest.raises(StorageConflictError):
        repository.put({
            "command_id": "cmd_stage7_conflict",
            "workspace_id": scope.workspace_id,
            "user_id": scope.user_id,
            "command_type": "disable_strategy",
            "status": "queued",
            "dangerous": True,
            "idempotency_key": "paper:command:exactly-once",
            "envelope_hash": hashlib.sha256(b"different-command").hexdigest(),
        }, scope=scope)


def test_real_worker_executes_noop_and_metrics_are_redacted(worker_store, monkeypatch) -> None:
    queue = worker_store["queue"]
    _enqueue(worker_store, 0, "execute:noop:0001", payload={"private": "secret"})
    monkeypatch.setattr(production_workers, "_QUEUE", queue)
    done = production_workers.run_once("maintenance", worker_id="runtime-worker")
    assert done["status"] == "succeeded"
    assert done["result"] == {"ok": True}
    metrics = queue.metrics()
    assert metrics["counts"]["maintenance"]["completed"] == 1
    assert metrics["payload_bytes"]["max"] > 0
    public = production_workers.public_job(done)
    assert "payload" not in public
    assert "result" not in public
    assert "workspace_id" not in public


def test_worker_service_graceful_shutdown_waits_for_inflight_job(
    worker_store, monkeypatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_run_once(_worker_class: str, *, worker_id: str = ""):
        assert worker_id
        started.set()
        release.wait(timeout=2)
        return {"status": "succeeded"}

    monkeypatch.setattr(production_workers, "_QUEUE", worker_store["queue"])
    monkeypatch.setattr(production_workers, "run_once", blocking_run_once)
    service = production_workers.WorkerService(["maintenance"], poll_ms=50)
    service.start()
    assert started.wait(timeout=2)
    releaser = threading.Timer(0.15, release.set)
    releaser.start()
    before = time.perf_counter()
    assert service.stop(grace_sec=2) is True
    elapsed = time.perf_counter() - before
    releaser.join(timeout=1)
    assert elapsed >= 0.1
    assert all(not thread.is_alive() for thread in service.threads)
