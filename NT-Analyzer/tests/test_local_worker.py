from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import durable, local_worker


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NT_ANALYZER_ROOT", str(tmp_path))
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(tmp_path / "durable.sqlite3"))


def test_local_worker_runs_queued_job_to_success(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("noop", job_id="wj_noop")

    row = local_worker.run_once(worker_id="test-worker")

    assert row is not None
    assert row["worker_job_id"] == "wj_noop"
    assert row["status"] == "succeeded"
    assert row["result"]["ok"] is True


def test_local_worker_persists_failure_without_blocking_queue(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("fail", {"message": "boom"}, job_id="wj_fail")
    local_worker.enqueue("noop", job_id="wj_after")

    failed = local_worker.run_once(worker_id="test-worker")
    succeeded = local_worker.run_once(worker_id="test-worker")

    assert failed["status"] == "failed"
    assert "boom" in failed["error"]
    assert succeeded["worker_job_id"] == "wj_after"
    assert succeeded["status"] == "succeeded"


def test_worker_cancel_and_stale_recovery(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("noop", job_id="wj_cancel")
    cancelled = local_worker.cancel("wj_cancel")
    assert cancelled["job"]["status"] == "cancelled"

    durable.enqueue_worker_job(
        tmp_path,
        worker_job_id="wj_stale",
        kind="noop",
        timeout_sec=1,
        payload={},
    )
    claimed = durable.claim_worker_job(tmp_path, worker_id="test", now=time.time() - 5)
    assert claimed["status"] == "running"
    assert durable.sweep_stale_worker_jobs(tmp_path, now=time.time() + 10) == 1
    stale = durable.get_worker_job(tmp_path, "wj_stale")
    assert stale["status"] == "failed"
    assert "timed out" in stale["error"]


def test_claim_is_atomic_and_records_lease_owner(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("noop", job_id="wj_atomic")

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(
            lambda worker: durable.claim_worker_job(tmp_path, worker_id=worker),
            ("worker-a", "worker-b"),
        ))

    rows = [row for row in claimed if row is not None]
    assert len(rows) == 1
    assert rows[0]["worker_id"] in {"worker-a", "worker-b"}
    assert rows[0]["heartbeat_at_utc"]
    assert rows[0]["deadline_at"] > 0


def test_running_cancel_is_cooperative_and_late_finish_is_rejected(
    tmp_path: Path, monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("sleep", {"seconds": 1}, job_id="wj_running_cancel")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(local_worker.run_once, worker_id="cancel-worker")
        deadline = time.time() + 2
        while time.time() < deadline:
            row = durable.get_worker_job(tmp_path, "wj_running_cancel")
            if row and row["status"] == "running":
                break
            time.sleep(0.01)
        local_worker.cancel("wj_running_cancel", workspace_id="system")
        result = future.result(timeout=3)

    assert result["status"] == "cancelled"
    late = durable.finish_worker_job(
        tmp_path, "wj_running_cancel", {"ok": True}, worker_id="cancel-worker",
    )
    assert late["status"] == "cancelled"


def test_timeout_retries_then_becomes_terminal(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue(
        "sleep", {"seconds": 2}, job_id="wj_timeout",
        timeout_sec=1, max_attempts=2,
    )

    first = local_worker.run_once(worker_id="timeout-worker")
    second = local_worker.run_once(worker_id="timeout-worker")

    assert first["status"] == "queued"
    assert first["attempts"] == 1
    assert second["status"] == "failed"
    assert second["attempts"] == 2
    assert "timed out" in second["error"]


def test_worker_workspace_scope_blocks_cross_tenant_reads_and_cancel(
    tmp_path: Path, monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue("noop", job_id="wj_a", workspace_id="ws_a")
    local_worker.enqueue("noop", job_id="wj_b", workspace_id="ws_b")

    assert [row["worker_job_id"] for row in durable.list_worker_jobs(
        tmp_path, workspace_id="ws_a",
    )] == ["wj_a"]
    assert local_worker.cancel("wj_b", workspace_id="ws_a")["reason"] == "not_found"
    assert durable.get_worker_job(tmp_path, "wj_b")["status"] == "queued"


def test_schema_v2_columns_are_present(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    durable.init(tmp_path)
    with durable.connect(tmp_path) as conn:
        columns = {
            str(row["name"]) for row in conn.execute(
                "PRAGMA table_info(worker_jobs)",
            ).fetchall()
        }
        version = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'",
        ).fetchone()["value"]
    assert {"worker_id", "heartbeat_at_utc", "deadline_at"} <= columns
    assert version == str(durable.SCHEMA_VERSION)


def test_ai_message_job_is_workspace_bound_idempotent_and_runs_outside_http(
    tmp_path: Path, monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    from app.ai_lab import chief_agent

    calls = []

    def fake_handle(message, **kwargs):
        calls.append((message, kwargs))
        kwargs["on_thinking"]("progress")
        return {
            "ok": True,
            "reply": "ready",
            "conversation_id": kwargs["conversation_id"],
            "request_id": kwargs["request_id"],
        }

    monkeypatch.setattr(chief_agent, "handle_message", fake_handle)
    scope = {"user_id": 42, "workspace_id": "ws_ai", "membership_role": "owner"}
    first = local_worker.enqueue_ai_message(
        "hello", request_id="req-one", conversation_id="C-AI",
        agent="vitek", scope=scope, mirror_to_telegram=False,
    )
    replay = local_worker.enqueue_ai_message(
        "hello", request_id="req-one", conversation_id="C-AI",
        agent="vitek", scope=scope, mirror_to_telegram=False,
    )

    assert replay["worker_job_id"] == first["worker_job_id"]
    done = local_worker.run_once(worker_id="ai-worker")
    assert done["status"] == "succeeded"
    assert done["result"]["reply"] == "ready"
    assert len(calls) == 1
    assert calls[0][1]["scope"]["workspace_id"] == "ws_ai"
    assert local_worker.get(first["worker_job_id"], workspace_id="ws_other") is None


def test_ai_worker_rejects_payload_scope_tampering(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    local_worker.enqueue(
        "ai_orchestrator",
        {
            "message": "hello",
            "request_id": "req-tampered",
            "scope": {"user_id": 8, "workspace_id": "ws_b"},
        },
        user_id=7,
        workspace_id="ws_a",
        job_id="wj_ai_tampered",
    )

    result = local_worker.run_once(worker_id="ai-worker")
    assert result["status"] == "failed"
    assert "scope" in result["error"].lower()


def test_public_ai_worker_shape_never_exposes_payload_or_tenant_identity() -> None:
    from app import server as server_mod

    public = server_mod.Handler._public_ai_worker_job({
        "worker_job_id": "wj_ai_public", "status": "running",
        "attempts": 1, "max_attempts": 2,
        "user_id": "42", "workspace_id": "ws_private",
        "payload": {"message": "private prompt", "scope": {"is_owner": True}},
    })

    assert public["worker_job_id"] == "wj_ai_public"
    assert "payload" not in public
    assert "user_id" not in public
    assert "workspace_id" not in public


def test_large_chart_batch_runs_in_worker_and_is_workspace_bound(
    tmp_path: Path, monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    from app import server as server_mod

    calls = []
    monkeypatch.setattr(
        server_mod,
        "_market_bars_payload",
        lambda instrument, timeframe, limit, *args, **kwargs: calls.append(
            (instrument, timeframe, limit, kwargs)
        ) or {"instrument": instrument, "timeframe": timeframe, "bars": [{"c": 101}]},
    )
    job = local_worker.enqueue_chart_batch(
        [{"instrument": "MNQ", "timeframe": "5m", "limit": 20000,
          "max_points": 12000}],
        scope={"user_id": 42, "workspace_id": "ws_chart"},
    )

    done = local_worker.run_once(worker_id="chart-worker")
    assert done["worker_job_id"] == job["worker_job_id"]
    assert done["status"] == "succeeded"
    assert done["result"]["series"][0]["bars"][0]["c"] == 101
    assert calls[0][3]["workspace_id"] == "ws_chart"
    assert local_worker.get(job["worker_job_id"], workspace_id="ws_other") is None
