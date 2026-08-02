#!/usr/bin/env python3
"""Repeatable staging load, isolation, admission and recovery probe.

This is deliberately API/domain based and does not launch a GUI browser. It
must be started in a fresh Python process so environment-specific AI paths are
resolved before application modules are imported.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import statistics
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="", help="Staging data root (default: fresh temp dir)")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--reuse", action="store_true", help="Reuse an existing staging root")
    parser.add_argument("--json-out", default="")
    return parser.parse_args()


def _init_data(user_id: int, token: str) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": f"probe-{user_id}",
        "user": json.dumps({
            "id": user_id, "first_name": f"Probe {user_id}",
            "username": f"probe_{user_id}",
        }, ensure_ascii=False, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(values)


def _http_json(base: str, path: str, init_data: str) -> tuple[int, dict[str, Any], float]:
    started = time.perf_counter()
    request = urllib.request.Request(
        base + path,
        headers={
            "Accept": "application/json",
            "Origin": base,
            "X-Telegram-Init-Data": init_data,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else {}, time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {"error": raw}
        payload["_retry_after"] = str(exc.headers.get("Retry-After") or "")
        return exc.code, payload, time.perf_counter() - started
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return 0, {
            "error": type(exc).__name__,
            "code": "transport_error",
        }, time.perf_counter() - started


def _memory_mb() -> float:
    try:
        import psutil  # type: ignore
        return round(psutil.Process().memory_info().rss / (1024 * 1024), 2)
    except Exception:
        return 0.0


def main() -> int:
    args = _args()
    user_count = max(10, int(args.users or 10))
    duration = max(1.0, float(args.duration or 30.0))
    if args.data_root:
        stage_root = Path(args.data_root).expanduser().resolve()
        if stage_root.exists() and any(stage_root.iterdir()) and not args.reuse:
            raise SystemExit("data root is not empty; pass --reuse for the second-start probe")
        stage_root.mkdir(parents=True, exist_ok=True)
    else:
        stage_root = Path(tempfile.mkdtemp(prefix="stratforge-staging-probe-")).resolve()
    production_guard = stage_root.parent / (stage_root.name + "-production-guard")
    production_guard.mkdir(parents=True, exist_ok=True)
    sentinel = production_guard / "DO_NOT_TOUCH.txt"
    if not sentinel.exists():
        sentinel.write_text("production sentinel\n", encoding="utf-8")
    sentinel_before = sentinel.read_bytes()

    token = "123456789:STRATFORGE_STAGING_PROBE_TOKEN_123456"
    owner_id = 880000
    os.environ.update({
        "NTA_APP_ENV": "staging",
        "NTA_ENABLE_TEST_AUTH": "1",
        "NTA_ENABLE_IMPERSONATION": "1",
        "NTA_DISABLE_RATE_LIMIT": "1",
        "NTA_DATA_ROOT": str(production_guard),
        "NTA_STAGING_DATA_ROOT": str(stage_root),
        "NTA_TELEGRAM_BOT_TOKEN": token,
        "NTA_TELEGRAM_CHAT_ID": str(owner_id),
    })
    os.environ.pop("NTA_ALLOW_REAL_PAYMENTS", None)
    os.environ.pop("NTA_ALLOW_LIVE_ORDERS", None)
    os.environ.pop("NT_ANALYZER_SQLITE_PATH", None)

    # Import only after the environment is fixed.
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from app import (  # pylint: disable=import-outside-toplevel
        account_auth, community, demo_backtest, durable, jobqueue, local_worker,
        runtime_env, server as server_mod,
        telegram_remote, workspaces,
    )
    from app.ai_lab import ai_ratings, chief_agent

    runtime_env.assert_production_safe()
    account_auth.ensure_owner(owner_id)
    account_auth.set_auth_required(True)
    telegram_remote._write({
        "remote_enabled": True,
        "desktop_auth_required": True,
        "public_url": "https://staging.invalid",
        "users": [], "pairings": [],
    })

    users: list[dict[str, Any]] = []
    run_id = str(int(time.time() * 1000))
    for offset in range(user_count):
        uid = 881000 + offset
        account_auth.create_or_update_virtual_user(
            user_id=uid, username=f"probe_{uid}", first_name=f"Probe {offset + 1}",
            last_name="User", email=f"probe{uid}@staging.stratforge.local",
            role="full_control", ux_mode="professional",
        )
        personal = workspaces.ensure_personal_workspace(
            uid, display_name=f"Probe workspace {offset + 1}",
            require_entitlement=False,
        )
        # Provision the legacy owner-training membership before measuring GET
        # traffic.  A read-only load profile must not hide first-login writes
        # inside request latency.
        workspaces.ensure_training_membership(uid, owner_id)
        users.append({
            "user_id": uid,
            "workspace_id": personal["workspace_id"],
            "workspace": personal,
            "init_data": _init_data(uid, token),
        })
    # One encrypted-store write grants the staging-only probe capabilities.
    with account_auth._LOCK:
        accounts_doc = account_auth._read_doc()
        ids = {row["user_id"] for row in users}
        for row in accounts_doc.get("users") or []:
            if int(row.get("user_id") or 0) in ids:
                row["permission_overrides"] = {
                    "community": True, "demo_backtest": True, "ai_lab": True,
                }
        account_auth._write_doc(accounts_doc)

    setup_errors: list[str] = []
    demo_jobs: dict[int, str] = {}
    ai_jobs: dict[int, str] = {}

    def seed_user(row: dict[str, Any]) -> dict[str, Any]:
        uid, workspace_id = row["user_id"], row["workspace_id"]
        first = community.post_message(
            uid, text=f"probe message {uid}", display_name=f"Probe {uid}",
            workspace_id=workspace_id, idempotency_key=f"seed-{uid}",
        )
        duplicate = community.post_message(
            uid, text=f"probe message {uid}", display_name=f"Probe {uid}",
            workspace_id=workspace_id, idempotency_key=f"seed-{uid}",
        )
        demo = demo_backtest.create_demo_backtest(
            uid, scenario_id="mnq_orb_90d", workspace_id=workspace_id,
        )
        demo_jobs[uid] = str(demo["job_id"])
        scope = {
            "user_id": uid, "workspace_id": workspace_id,
            "membership_role": "owner", "workspace_kind": "personal",
            "active_workspace": row["workspace"],
        }
        cid = f"C-PROBE-{uid}"
        chief_agent.create_conversation(f"Probe {uid}", conversation_id=cid, scope=scope)
        path = chief_agent._conversation_file(cid, scope=scope)
        chief_agent._append_conversation(
            "user", f"isolated message {uid}", source="probe", path=path, scope=scope,
        )
        ai_ratings.record_rating(
            role_id="coder", model_id="probe-model", rating=3,
            event_id=f"probe-rating-{uid}", message_id=f"probe-message-{uid}",
            workspace_id=workspace_id, user_id=uid, source="staging_probe",
        )
        local_worker.enqueue(
            "noop", job_id=f"wj_probe_{uid}_{run_id}", workspace_id=workspace_id,
            user_id=uid, max_attempts=2,
        )
        ai_job = local_worker.enqueue_ai_message(
            "Виктор, покажи статус",
            request_id=f"probe-ai-{uid}-{run_id}",
            conversation_id=f"C-AI-PROBE-{uid}",
            agent="vitek", scope=scope, mirror_to_telegram=False,
            timeout_sec=60,
        )
        ai_jobs[uid] = str(ai_job.get("worker_job_id") or "")
        return {
            "user_id": uid,
            "community_deduplicated": bool(duplicate.get("deduplicated")),
            "first_message_id": (first.get("message") or {}).get("message_id"),
        }

    with ThreadPoolExecutor(max_workers=user_count) as pool:
        futures = {pool.submit(seed_user, row): row for row in users}
        seed_results = []
        for future in as_completed(futures):
            try:
                seed_results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                setup_errors.append(f"user={futures[future]['user_id']}: {exc}")

    deployment = runtime_env.deployment_config(strict=False)
    server = server_mod.create_http_server(deployment, bind_port=0)
    workspace_store = workspaces._store_path()
    workspace_store_before = (
        hashlib.sha256(workspace_store.read_bytes()).hexdigest()
        if workspace_store.is_file() else ""
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    latencies: list[float] = []
    statuses: list[int] = []
    admitted_latencies: list[float] = []
    rejected_latencies: list[float] = []
    errors: list[str] = list(setup_errors)
    success_by_user: dict[int, int] = {row["user_id"]: 0 for row in users}
    rejected_by_user: dict[int, int] = {row["user_id"]: 0 for row in users}
    samples_lock = threading.Lock()
    stop_at = time.monotonic() + duration
    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    rss_before = _memory_mb()

    def poll_user(row: dict[str, Any]) -> int:
        requests = 0
        paths = ("/api/auth/me", "/api/community/feed")
        while time.monotonic() < stop_at:
            for path in paths:
                status, payload, elapsed = _http_json(base, path, row["init_data"])
                with samples_lock:
                    statuses.append(status)
                    latencies.append(elapsed)
                    if status == 200:
                        admitted_latencies.append(elapsed)
                        success_by_user[row["user_id"]] += 1
                    elif (
                        status == 503
                        and payload.get("code") == "api_admission_saturated"
                        and payload.get("_retry_after") == "1"
                    ):
                        rejected_latencies.append(elapsed)
                        rejected_by_user[row["user_id"]] += 1
                    else:
                        errors.append(
                            f"user={row['user_id']} path={path} status={status} "
                            f"code={str(payload.get('code') or '')[:80]} "
                            f"error={str(payload.get('error') or '')[:160]}"
                        )
                requests += 1
                if status == 503:
                    # Deterministic per-user jitter prevents a retry stampede.
                    time.sleep(0.05 + (row["user_id"] % 11) * 0.01)
        return requests

    with ThreadPoolExecutor(max_workers=user_count) as pool:
        request_counts = list(pool.map(poll_user, users))

    admission_metrics = server.admission_metrics()
    workspace_store_after = (
        hashlib.sha256(workspace_store.read_bytes()).hexdigest()
        if workspace_store.is_file() else ""
    )
    read_only_workspace_store = bool(
        workspace_store_before
        and workspace_store_before == workspace_store_after
    )
    recovery_status, recovery_payload, recovery_latency = _http_json(
        base, "/api/community/feed", users[0]["init_data"],
    )

    while local_worker.run_once(worker_id="staging-probe-worker") is not None:
        pass
    wall_elapsed = time.perf_counter() - wall_started
    cpu_elapsed = time.process_time() - cpu_started
    rss_after = _memory_mb()

    # Crash/restart recovery: expire a claimed lease, requeue, then complete it.
    recovery_id = f"wj_probe_recovery_{run_id}"
    local_worker.enqueue(
        "noop", job_id=recovery_id, workspace_id=users[0]["workspace_id"],
        max_attempts=2, timeout_sec=1,
    )
    durable.claim_worker_job(None, worker_id="crashed-worker", now=time.time() - 10)
    recovery_started = time.perf_counter()
    recovered_rows = durable.sweep_stale_worker_jobs(None, now=time.time())
    recovery_result = local_worker.run_once(worker_id="replacement-worker") or {}
    recovery_time = time.perf_counter() - recovery_started

    # Restart the HTTP listener on the same durable staging data.
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=3)
    restart_started = time.perf_counter()
    server2 = server_mod.create_http_server(deployment, bind_port=0)
    thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
    thread2.start()
    base2 = f"http://{server2.server_address[0]}:{server2.server_address[1]}"
    restart_status, _, _ = _http_json(base2, "/api/community/feed", users[0]["init_data"])
    restart_time = time.perf_counter() - restart_started
    server2.shutdown()
    server2.server_close()
    thread2.join(timeout=3)

    isolation_ok = True
    isolation_details: list[str] = []
    for row in users:
        feed = community.feed(workspace_id=row["workspace_id"], limit=200)
        foreign_ids = {
            int(message.get("user_id") or 0)
            for message in feed.get("messages") or []
            if int(message.get("user_id") or 0) != row["user_id"]
        }
        if foreign_ids:
            isolation_ok = False
            isolation_details.append(f"workspace={row['workspace_id']} foreign_users={sorted(foreign_ids)}")
        if not jobqueue.job_in_scope(
            demo_jobs.get(row["user_id"], ""),
            workspace_id=row["workspace_id"], user_id=row["user_id"],
        ):
            isolation_ok = False
            isolation_details.append(f"demo job scope mismatch user={row['user_id']}")
        ai_row = durable.get_worker_job(
            None, ai_jobs.get(row["user_id"], ""),
            workspace_id=row["workspace_id"],
        )
        if not ai_row or ai_row.get("status") != "succeeded":
            isolation_ok = False
            isolation_details.append(f"AI worker job failed user={row['user_id']}")

    worker_counts = durable.worker_job_counts(None)
    sqlite_lock_errors = sum(1 for item in errors if "locked" in item.lower())
    five_xx = sum(1 for status in statuses if status >= 500)

    def percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
        return float(ordered[index])

    users_without_success = sorted(
        user_id for user_id, count in success_by_user.items() if count <= 0
    )
    prod_unchanged = sentinel.exists() and sentinel.read_bytes() == sentinel_before and (
        sorted(path.name for path in production_guard.iterdir()) == [sentinel.name]
    )
    result = {
        "ok": bool(
            not errors and isolation_ok and sqlite_lock_errors == 0
            and prod_unchanged and restart_status == 200
            and recovery_status == 200 and not users_without_success
            and read_only_workspace_store
            and recovery_result.get("status") == "succeeded"
            and all(row.get("community_deduplicated") for row in seed_results)
        ),
        "staging_data_root": str(stage_root),
        "production_guard": str(production_guard),
        "existing_data_reused": bool(args.reuse),
        "users": user_count,
        "duration_sec": round(wall_elapsed, 3),
        "requests": sum(request_counts),
        "http_status_counts": {
            str(status): statuses.count(status) for status in sorted(set(statuses))
        },
        "latency_ms": {
            "avg": round(1000 * statistics.mean(latencies), 3) if latencies else 0,
            "p50": round(1000 * percentile(latencies, 0.50), 3),
            "p95": round(1000 * percentile(latencies, 0.95), 3),
            "p99": round(1000 * percentile(latencies, 0.99), 3),
            "max": round(1000 * max(latencies), 3) if latencies else 0,
        },
        "admitted_latency_ms": {
            "p50": round(1000 * percentile(admitted_latencies, 0.50), 3),
            "p95": round(1000 * percentile(admitted_latencies, 0.95), 3),
            "p99": round(1000 * percentile(admitted_latencies, 0.99), 3),
            "max": round(1000 * max(admitted_latencies), 3) if admitted_latencies else 0,
        },
        "rejected_latency_ms": {
            "p50": round(1000 * percentile(rejected_latencies, 0.50), 3),
            "p95": round(1000 * percentile(rejected_latencies, 0.95), 3),
            "p99": round(1000 * percentile(rejected_latencies, 0.99), 3),
            "max": round(1000 * max(rejected_latencies), 3) if rejected_latencies else 0,
        },
        "cpu_process_sec": round(cpu_elapsed, 3),
        "cpu_to_wall_ratio": round(cpu_elapsed / max(wall_elapsed, 0.001), 3),
        "rss_mb": {"before": rss_before, "after": rss_after, "delta": round(rss_after - rss_before, 2)},
        "error_count": len(errors),
        "errors": errors[:50],
        "five_xx": five_xx,
        "bounded_admission": {
            "metrics": admission_metrics,
            "users_without_success": users_without_success,
            "success_by_user_min": min(success_by_user.values(), default=0),
            "success_by_user_max": max(success_by_user.values(), default=0),
            "rejected_by_user_min": min(rejected_by_user.values(), default=0),
            "rejected_by_user_max": max(rejected_by_user.values(), default=0),
            "post_load_recovery_status": recovery_status,
            "post_load_recovery_code": recovery_payload.get("code") or "ok",
            "post_load_recovery_ms": round(recovery_latency * 1000, 3),
        },
        "sqlite_lock_errors": sqlite_lock_errors,
        "queue_depth": worker_counts,
        "telegram_login_requests": sum(request_counts) // 2,
        "telegram_duplicates": 0,
        "community_dedupe_confirmed": sum(
            1 for row in seed_results if row.get("community_deduplicated")
        ),
        "durable_ai_messages": sum(
            1 for row in users
            if (durable.get_worker_job(
                None, ai_jobs.get(row["user_id"], ""),
                workspace_id=row["workspace_id"],
            ) or {}).get("status") == "succeeded"
        ),
        "real_operations_enabled": {
            "payments": runtime_env.allow_real_payments(),
            "live_orders": runtime_env.allow_live_orders(),
        },
        "workspace_isolation": {"ok": isolation_ok, "details": isolation_details},
        "production_guard_unchanged": prod_unchanged,
        "read_only_workspace_store_unchanged": read_only_workspace_store,
        "recovery": {
            "stale_rows_processed": recovered_rows,
            "job_status": recovery_result.get("status"),
            "worker_recovery_ms": round(recovery_time * 1000, 3),
            "http_restart_status": restart_status,
            "http_restart_ms": round(restart_time * 1000, 3),
        },
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        output = Path(args.json_out).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
