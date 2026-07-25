"""Stage 7 PostgreSQL worker load/failure acceptance probe (test DB only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import production_workers
from app.production_storage import MigrationRunner, Scope
from app.production_storage.core import PostgresClient, _jsonb, _psycopg


def _percentiles(values: list[float]) -> Dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    ordered = sorted(values)

    def pick(fraction: float) -> float:
        index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
        return float(ordered[index])

    return {
        "p50": pick(0.50), "p95": pick(0.95), "p99": pick(0.99),
        "max": float(ordered[-1]),
    }


def _rss_bytes() -> int:
    try:
        import psutil  # type: ignore
        return int(psutil.Process().memory_info().rss)
    except Exception:
        try:
            import resource
            value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return value if sys.platform == "darwin" else value * 1024
        except Exception:
            return 0


def _assert_test_target(url: str, *, allow_non_loopback: bool) -> None:
    parsed = urlparse(url)
    host = str(parsed.hostname or "").lower()
    database = str(parsed.path or "").strip("/").lower()
    if not allow_non_loopback and host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("load probe refuses a non-loopback PostgreSQL target")
    if not any(token in database for token in ("stage", "test", "load")):
        raise SystemExit("load probe requires a database name containing stage/test/load")


class Probe:
    def __init__(self, admin_url: str, app_url: str) -> None:
        self.admin_url = admin_url
        self.client = PostgresClient(app_url, production=False)
        self.queue = production_workers.ProductionQueue(self.client)
        self.psycopg = _psycopg()
        self.run_id = uuid.uuid4().hex[:8]
        self.workspace_ids = [f"ws_load_{self.run_id}_{index:03d}" for index in range(100)]
        self.user_ids = [880000 + index for index in range(100)]

    def admin(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(sql, params)

    def scalar(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.psycopg.connect(self.admin_url, autocommit=True) as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0)

    def setup(self) -> None:
        MigrationRunner(self.admin_url).apply()
        self.queue.ensure_defaults()
        with self.psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(
                "DELETE FROM sf_workspaces WHERE workspace_id = ANY(%s)",
                (self.workspace_ids,),
            )
            conn.execute("DELETE FROM sf_users WHERE user_id = ANY(%s)", (self.user_ids,))
            for workspace_id, user_id in zip(self.workspace_ids, self.user_ids):
                conn.execute(
                    """INSERT INTO sf_users(user_id,status,is_owner,document)
                       VALUES(%s,'active',FALSE,%s)""",
                    (
                        user_id,
                        _jsonb({"user_id": user_id, "role": "full_control"}),
                    ),
                )
                conn.execute(
                    """INSERT INTO sf_workspaces(
                         workspace_id,owner_user_id,status,kind,document
                       ) VALUES(%s,%s,'active','load_test',%s)""",
                    (
                        workspace_id, user_id,
                        _jsonb({"workspace_id": workspace_id, "load_test": True}),
                    ),
                )
                conn.execute(
                    """INSERT INTO sf_workspace_memberships(
                         workspace_id,user_id,role,document
                       ) VALUES(%s,%s,'owner',%s)""",
                    (
                        workspace_id, user_id,
                        _jsonb({
                            "workspace_id": workspace_id,
                            "user_id": user_id,
                            "role": "owner",
                            "load_test": True,
                        }),
                    ),
                )

    def reset_jobs(self) -> None:
        with self.psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute("DELETE FROM sf_jobs WHERE workspace_id = ANY(%s)", (self.workspace_ids,))
            conn.execute(
                "DELETE FROM sf_idempotency_keys WHERE workspace_id = ANY(%s)",
                (self.workspace_ids,),
            )
            conn.execute(
                "DELETE FROM sf_queue_workspace_state WHERE workspace_id = ANY(%s)",
                (self.workspace_ids,),
            )
            conn.execute(
                "DELETE FROM sf_workspace_queue_quotas WHERE workspace_id = ANY(%s)",
                (self.workspace_ids,),
            )

    def cleanup(self) -> None:
        with self.psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute("DELETE FROM sf_workspaces WHERE workspace_id = ANY(%s)", (self.workspace_ids,))
            conn.execute("DELETE FROM sf_users WHERE user_id = ANY(%s)", (self.user_ids,))

    def scope(self, index: int) -> Scope:
        return Scope(user_id=self.user_ids[index], workspace_id=self.workspace_ids[index])

    def profile(self, users: int, jobs_per_user: int, worker_threads: int) -> Dict[str, Any]:
        self.reset_jobs()
        total = users * jobs_per_user
        rss_before = _rss_bytes()
        cpu_before = time.process_time()
        wall_started = time.perf_counter()
        enqueue_ms: list[float] = []
        errors: list[str] = []

        def submit(index: int, sequence: int) -> None:
            started = time.perf_counter()
            self.queue.enqueue(
                "chart_batch",
                {"profile": users, "workspace_index": index, "sequence": sequence},
                scope=self.scope(index), idempotency_key=f"load:{users}:{index}:{sequence}",
                max_attempts=2, timeout_sec=30,
            )
            enqueue_ms.append((time.perf_counter() - started) * 1000.0)

        with ThreadPoolExecutor(max_workers=min(32, users)) as pool:
            futures = [
                pool.submit(submit, index, sequence)
                for index in range(users) for sequence in range(jobs_per_user)
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001 - evidence captures class only
                    errors.append(type(exc).__name__)

        completed: list[Dict[str, Any]] = []
        completed_lock = threading.Lock()
        stop = threading.Event()
        rss_samples: list[int] = []

        def sample_resources() -> None:
            while not stop.wait(0.02):
                rss_samples.append(_rss_bytes())

        sampler = threading.Thread(target=sample_resources, daemon=True)
        sampler.start()

        def drain(slot: int) -> None:
            worker_id = f"load-{users}-{slot}"
            idle = 0
            while True:
                with completed_lock:
                    if len(completed) >= total:
                        return
                row = self.queue.claim("chart", worker_id=worker_id)
                if row is None:
                    idle += 1
                    if idle > 2000:
                        errors.append("drain_timeout")
                        return
                    time.sleep(0.002)
                    continue
                idle = 0
                # 10% slow downstream calls exercise class concurrency/fairness.
                slow_marker = int(
                    hashlib.sha256(row["job_id"].encode("utf-8")).hexdigest()[:8],
                    16,
                )
                if slow_marker % 10 == 0:
                    time.sleep(0.025)
                done = self.queue.complete(
                    row["job_id"], {"ok": True}, worker_id=worker_id,
                    lease_token=row["lease_token"],
                )
                if done and done["status"] == "succeeded":
                    with completed_lock:
                        completed.append(done)
                else:
                    errors.append("completion_failed")

        with ThreadPoolExecutor(max_workers=max(1, worker_threads)) as pool:
            list(pool.map(drain, range(max(1, worker_threads))))
        stop.set()
        sampler.join(timeout=1)

        wall = time.perf_counter() - wall_started
        cpu = time.process_time() - cpu_before
        rss_after = _rss_bytes()
        e2e_ms = [
            (row["finished_at"] - row["created_at"]).total_seconds() * 1000.0
            for row in completed if row.get("finished_at") and row.get("created_at")
        ]
        counts_by_workspace: Dict[str, int] = {}
        for row in completed:
            key = str(row["workspace_id"])
            counts_by_workspace[key] = counts_by_workspace.get(key, 0) + 1
        fairness_ok = (
            len(counts_by_workspace) == users
            and set(counts_by_workspace.values()) == {jobs_per_user}
        )
        metrics = self.queue.metrics()
        return {
            "users": users,
            "jobs": total,
            "completed": len(completed),
            "errors": errors,
            "enqueue_ms": _percentiles(enqueue_ms),
            "end_to_end_ms": _percentiles(e2e_ms),
            "throughput_jobs_per_sec": total / wall if wall > 0 else 0.0,
            "wall_seconds": wall,
            "cpu_seconds": cpu,
            "cpu_one_core_percent": (cpu / wall * 100.0) if wall > 0 else 0.0,
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_peak_bytes": max(rss_samples or [rss_before, rss_after]),
            "fairness_ok": fairness_ok,
            "queue_metrics": metrics,
            "ok": not errors and len(completed) == total and fairness_ok,
        }

    def failure_acceptance(self) -> Dict[str, Any]:
        self.reset_jobs()
        scope = self.scope(0)
        queue = self.queue

        provider = queue.enqueue(
            "noop", {"provider": "forced_outage"}, scope=scope,
            idempotency_key="failure:provider:0001", max_attempts=2,
        )
        first = queue.claim("maintenance", worker_id="provider-worker-1")
        retry = queue.fail(
            provider["job_id"], "provider unavailable",
            worker_id="provider-worker-1", lease_token=first["lease_token"],
            error_class="provider_outage",
        )
        self.admin(
            "UPDATE sf_jobs SET available_at=clock_timestamp() WHERE job_id=%s",
            (provider["job_id"],),
        )
        second = queue.claim("maintenance", worker_id="provider-worker-2")
        recovered = queue.complete(
            provider["job_id"], {"provider_recovered": True},
            worker_id="provider-worker-2", lease_token=second["lease_token"],
        )

        crash = queue.enqueue(
            "noop", {"crash": True}, scope=scope,
            idempotency_key="failure:crash:0001", max_attempts=2,
        )
        crashed = queue.claim("maintenance", worker_id="crashed-worker")
        crash_started = time.perf_counter()
        self.admin(
            "UPDATE sf_jobs SET leased_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",
            (crash["job_id"],),
        )
        swept = queue.sweep_stale()
        self.admin(
            "UPDATE sf_jobs SET available_at=clock_timestamp() WHERE job_id=%s",
            (crash["job_id"],),
        )
        replacement = queue.claim("maintenance", worker_id="replacement-worker")
        restarted = queue.complete(
            crash["job_id"], {"restarted": True},
            worker_id="replacement-worker", lease_token=replacement["lease_token"],
        )
        recovery_ms = (time.perf_counter() - crash_started) * 1000.0

        dangerous_results: list[Dict[str, Any]] = []

        def dangerous_enqueue(_number: int) -> Dict[str, Any]:
            return queue.enqueue(
                "noop", {"command": "paper_only"}, scope=scope,
                idempotency_key="dangerous:dedupe:0001",
                max_attempts=10, dangerous=True,
            )

        with ThreadPoolExecutor(max_workers=24) as pool:
            dangerous_results = list(pool.map(dangerous_enqueue, range(24)))
        dangerous_id = dangerous_results[0]["job_id"]
        count = self.scalar(
            "SELECT count(*) FROM sf_jobs WHERE workspace_id=%s AND idempotency_key=%s",
            (scope.workspace_id, "dangerous:dedupe:0001"),
        )
        return {
            "provider_retry_status": retry["status"],
            "provider_recovered": recovered["status"] == "succeeded",
            "crash_swept": swept,
            "crash_old_lease": crashed["lease_token"],
            "crash_new_lease": replacement["lease_token"],
            "crash_recovered": restarted["status"] == "succeeded",
            "recovery_ms": recovery_ms,
            "dangerous_requests": len(dangerous_results),
            "dangerous_unique_rows": count,
            "dangerous_job_id": dangerous_id,
            "dangerous_replays": sum(
                1 for row in dangerous_results if row.get("idempotent_replay")
            ),
            "ok": bool(
                retry["status"] == "queued"
                and recovered["status"] == "succeeded"
                and swept == 1
                and replacement["lease_token"] != crashed["lease_token"]
                and restarted["status"] == "succeeded"
                and count == 1
                and sum(1 for row in dangerous_results if row.get("idempotent_replay")) == 23
            ),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-url", default=os.environ.get("STRATFORGE_TEST_POSTGRES_ADMIN_URL", ""),
    )
    parser.add_argument(
        "--app-url", default=os.environ.get("STRATFORGE_TEST_POSTGRES_URL", ""),
    )
    parser.add_argument("--profiles", default="10,50,100")
    parser.add_argument("--jobs-per-user", type=int, default=2)
    parser.add_argument("--worker-threads", type=int, default=8)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--allow-non-loopback", action="store_true")
    args = parser.parse_args(argv)
    if not args.admin_url or not args.app_url:
        raise SystemExit("admin/app PostgreSQL URLs are required")
    _assert_test_target(args.admin_url, allow_non_loopback=args.allow_non_loopback)
    _assert_test_target(args.app_url, allow_non_loopback=args.allow_non_loopback)
    profiles = [int(value.strip()) for value in args.profiles.split(",") if value.strip()]
    if not profiles or min(profiles) < 1 or max(profiles) > 100:
        raise SystemExit("profiles must contain values from 1 to 100")

    probe = Probe(args.admin_url, args.app_url)
    started = time.time()
    output: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": probe.run_id,
        "started_at_epoch": started,
        "profiles": [],
    }
    try:
        probe.setup()
        output["database_size_before_bytes"] = probe.scalar(
            "SELECT pg_database_size(current_database())"
        )
        for users in profiles:
            output["profiles"].append(probe.profile(
                users, max(1, min(10, args.jobs_per_user)),
                max(1, min(64, args.worker_threads)),
            ))
        output["failure_acceptance"] = probe.failure_acceptance()
        output["database_size_after_bytes"] = probe.scalar(
            "SELECT pg_database_size(current_database())"
        )
    finally:
        probe.cleanup()
    output["duration_seconds"] = time.time() - started
    output["ok"] = bool(
        all(row.get("ok") for row in output["profiles"])
        and output.get("failure_acceptance", {}).get("ok")
    )
    rendered = json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
    if args.json_out:
        output_path = Path(args.json_out).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if output["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
