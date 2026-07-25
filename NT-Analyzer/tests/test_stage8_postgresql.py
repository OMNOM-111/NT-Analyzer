"""Real PostgreSQL acceptance for the Stage 8 production control/data plane."""
from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

import app.production_storage as production_storage_package
from app import (
    ai_budgets,
    audit_events,
    market_data_ingestion,
    observability,
    production_telegram,
    runtime_env,
    server,
)
from app.production_storage import (
    MigrationRunner,
    Scope,
    StorageConstraintError,
    StorageUnavailableError,
)
from app.production_storage.core import PostgresClient


ADMIN_URL = os.environ.get("STRATFORGE_TEST_POSTGRES_ADMIN_URL", "")
APP_URL = os.environ.get("STRATFORGE_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_URL,
    reason="real PostgreSQL Stage 8 acceptance DSNs were not provided",
)

WS_A = "ws_personal_STAGE8AAA"
WS_B = "ws_personal_STAGE8BBB"
USER_A = 8101
USER_B = 8202
INST_A1 = "inst_stage8_alpha_01"
INST_A2 = "inst_stage8_alpha_02"
INST_B = "inst_stage8_beta_001"


def _truncate_stage8(admin_url: str) -> None:
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(
            """
            TRUNCATE sf_service_leases, sf_service_heartbeats,
              sf_telegram_updates, sf_telegram_outbox, sf_telegram_bot_state,
              sf_operational_events, sf_audit_events, sf_rate_limit_buckets,
              sf_repository_documents, sf_migration_runs, sf_users
            RESTART IDENTITY CASCADE
            """
        )


@pytest.fixture()
def stage8_store(monkeypatch):
    import psycopg

    _truncate_stage8(ADMIN_URL)
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO sf_users(user_id,status,is_owner,document) VALUES
                 (%s,'active',TRUE,'{}'::jsonb),
                 (%s,'active',FALSE,'{}'::jsonb)""",
            (USER_A, USER_B),
        )
        conn.execute(
            """INSERT INTO sf_workspaces(
                 workspace_id,owner_user_id,status,kind,document
               ) VALUES
                 (%s,%s,'active','personal','{}'::jsonb),
                 (%s,%s,'active','personal','{}'::jsonb)""",
            (WS_A, USER_A, WS_B, USER_B),
        )
        conn.execute(
            """INSERT INTO sf_workspace_memberships(
                 workspace_id,user_id,role,document
               ) VALUES
                 (%s,%s,'owner','{}'::jsonb),
                 (%s,%s,'owner','{}'::jsonb)""",
            (WS_A, USER_A, WS_B, USER_B),
        )
        conn.execute(
            """INSERT INTO sf_active_workspaces(user_id,workspace_id) VALUES
                 (%s,%s),(%s,%s)""",
            (USER_A, WS_A, USER_B, WS_B),
        )
        conn.execute(
            """INSERT INTO sf_connector_installations(
                 installation_id,workspace_id,user_id,status,
                 public_key_fingerprint,document
               ) VALUES
                 (%s,%s,%s,'online',%s,'{}'::jsonb),
                 (%s,%s,%s,'online',%s,'{}'::jsonb),
                 (%s,%s,%s,'online',%s,'{}'::jsonb)""",
            (
                INST_A1, WS_A, USER_A, "a" * 64,
                INST_A2, WS_A, USER_A, "b" * 64,
                INST_B, WS_B, USER_B, "c" * 64,
            ),
        )

    app_client = PostgresClient(APP_URL, production=False)
    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(production_storage_package, "get_client", lambda: app_client)
    for module in (ai_budgets, audit_events, observability):
        monkeypatch.setattr(module, "get_client", lambda client=app_client: client)
    monkeypatch.setattr(production_telegram, "_bot_hash", lambda: "d" * 64)
    production_telegram.reset_for_tests()
    queue = production_telegram.ProductionTelegramQueue(app_client)
    monkeypatch.setattr(production_telegram, "_QUEUE", queue)
    with server._MARKET_BARS_PAYLOAD_CACHE_LOCK:
        server._MARKET_BARS_PAYLOAD_CACHE.clear()
    try:
        yield {"client": app_client, "queue": queue}
    finally:
        production_telegram.reset_for_tests()
        with server._MARKET_BARS_PAYLOAD_CACHE_LOCK:
            server._MARKET_BARS_PAYLOAD_CACHE.clear()
        _truncate_stage8(ADMIN_URL)


def _update(update_id: int, chat_id: int, text: str = "message") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def _bar(at: datetime, *, timeframe: str = "1m", close: float = 100.5) -> dict:
    return {
        "open": 100.0,
        "high": max(101.0, close),
        "low": min(99.0, close),
        "close": close,
        "volume": 1000,
        "timestamp": at.astimezone(timezone.utc).isoformat(
            timespec="milliseconds",
        ).replace("+00:00", "Z"),
        "exact_contract": "MNQ 09-26",
        "timeframe": timeframe,
    }


def test_stage8_migrations_and_relational_isolation_constraints(stage8_store) -> None:
    plan = MigrationRunner(ADMIN_URL).plan()
    assert plan["applied_versions"] == [1, 2, 3, 4]
    assert plan["pending"] == []
    expected = {
        "sf_connector_sessions_workspace_installation_fk",
        "sf_job_attempts_workspace_job_fk",
        "sf_ai_reservations_workspace_user_fk",
        "sf_ai_usage_events_workspace_user_fk",
        "sf_market_data_subscriptions_workspace_user_fk",
        "sf_market_data_subscriptions_workspace_installation_fk",
        "sf_market_data_snapshots_workspace_installation_fk",
        "sf_market_data_batches_workspace_installation_fk",
        "sf_operational_events_workspace_user_fk",
        "sf_audit_events_workspace_user_fk",
    }
    with stage8_store["client"].transaction(
        Scope.global_service_scope(), read_only=True,
    ) as conn:
        rows = conn.execute(
            """SELECT conname,convalidated FROM pg_constraint
               WHERE conname=ANY(%s)""",
            (list(expected),),
        ).fetchall()
    assert {str(row["conname"]) for row in rows} == expected
    assert all(bool(row["convalidated"]) for row in rows)

    with pytest.raises(StorageConstraintError):
        with stage8_store["client"].transaction(Scope.global_service_scope()) as conn:
            conn.execute(
                """INSERT INTO sf_operational_events(
                     event_id,workspace_id,user_id,component,event_type,
                     severity,fingerprint,payload
                   ) VALUES(%s,%s,%s,'isolation','cross_tenant','critical',%s,'{}')""",
                ("ope_" + "1" * 32, WS_A, USER_B, "1" * 64),
            )
    with pytest.raises(StorageConstraintError):
        with stage8_store["client"].transaction(Scope.global_service_scope()) as conn:
            conn.execute(
                """INSERT INTO sf_audit_events(
                     event_id,workspace_id,user_id,source,event_type,payload,
                     actor,action,resource_type,resource_id,outcome,ip_hash,document
                   ) VALUES(%s,%s,%s,'stage8','cross_tenant','{}','stage8',
                     'cross_tenant','workspace','x','denied','','{}')""",
                ("aud_" + "2" * 32, WS_A, USER_B),
            )


def test_stage8_telegram_single_consumer_order_dedupe_and_redaction(stage8_store) -> None:
    queue = stage8_store["queue"]
    assert queue.enqueue_update(_update(20, 111, "A later"), transport="poll") is True
    assert queue.enqueue_update(_update(15, 222, "B parallel"), transport="poll") is True
    assert queue.enqueue_update(_update(10, 111, "A first"), transport="poll") is True
    assert queue.enqueue_update(_update(10, 111, "duplicate"), transport="poll") is False

    first = queue.claim_update("telegram-worker-a")
    second = queue.claim_update("telegram-worker-b")
    assert first and first["update_id"] == 10
    assert second and second["update_id"] == 15
    assert queue.claim_update("telegram-worker-c") is None
    assert queue.finish_update(first["update_key"], str(uuid.uuid4())) is False
    assert queue.finish_update(first["update_key"], first["lease_token"]) is True
    third = queue.claim_update("telegram-worker-c")
    assert third and third["update_id"] == 20
    assert queue.finish_update(second["update_key"], second["lease_token"]) is True
    assert queue.finish_update(third["update_key"], third["lease_token"]) is True

    lease = queue.acquire_service_lease("telegram-consumer", "instance-alpha")
    assert lease
    assert queue.acquire_service_lease("telegram-consumer", "instance-beta") is None
    queue.release_service_lease("telegram-consumer", "instance-alpha", lease)
    assert queue.acquire_service_lease("telegram-consumer", "instance-beta")

    outgoing = queue.enqueue_text(
        "sensitive delivery body", dedupe_key="stage8-dedupe", chat_id="111",
    )
    replay = queue.enqueue_text(
        "changed body is ignored", dedupe_key="stage8-dedupe", chat_id="111",
    )
    assert replay["outbox_id"] == outgoing["outbox_id"]
    assert replay["deduplicated"] is True
    claimed = queue.claim_outbox("telegram-worker-a")
    assert claimed and claimed["payload"]["text"] == "sensitive delivery body"
    assert queue.finish_outbox(claimed["outbox_id"], claimed["lease_token"])

    doomed = queue.enqueue_text("will fail", dedupe_key="stage8-dead-letter")
    claimed_doomed = queue.claim_outbox("telegram-worker-a")
    assert claimed_doomed and claimed_doomed["outbox_id"] == doomed["outbox_id"]
    with stage8_store["client"].transaction(Scope.global_service_scope()) as conn:
        conn.execute(
            "UPDATE sf_telegram_outbox SET attempts=%s WHERE outbox_id=%s",
            (production_telegram.MAX_ATTEMPTS, doomed["outbox_id"]),
        )
    assert queue.finish_outbox(
        claimed_doomed["outbox_id"], claimed_doomed["lease_token"],
        error=r"Bearer SUPERSECRET123456 C:\\Users\\private\\token.txt sk-LEAK123456789",
    )

    with stage8_store["client"].transaction(
        Scope.global_service_scope(), read_only=True,
    ) as conn:
        updates = conn.execute(
            "SELECT status,document FROM sf_telegram_updates ORDER BY update_id"
        ).fetchall()
        sent = conn.execute(
            "SELECT status,document FROM sf_telegram_outbox WHERE outbox_id=%s",
            (outgoing["outbox_id"],),
        ).fetchone()
        dead = conn.execute(
            "SELECT status,document,last_error FROM sf_telegram_outbox WHERE outbox_id=%s",
            (doomed["outbox_id"],),
        ).fetchone()
    assert [row["status"] for row in updates] == ["completed"] * 3
    assert all(dict(row["document"] or {}) == {} for row in updates)
    assert sent["status"] == "sent"
    assert dict(sent["document"] or {}) == {"kind": "redacted_after_delivery"}
    assert dead["status"] == "dead_letter"
    assert dict(dead["document"] or {}) == {"kind": "redacted_after_delivery"}
    assert "SUPERSECRET" not in dead["last_error"]
    assert "LEAK123" not in dead["last_error"]
    assert "Users" not in dead["last_error"]


def test_stage8_ai_budget_atomicity_idempotency_and_rls(stage8_store) -> None:
    prompt_hash = hashlib.sha256(b"stage8 budget prompt").hexdigest()
    with stage8_store["client"].transaction(Scope.global_service_scope()) as conn:
        conn.execute(
            """UPDATE sf_ai_workspace_budgets
               SET daily_limit_usd=0.05,monthly_limit_usd=0.05
               WHERE workspace_id IN (%s,%s)""",
            (WS_A, WS_B),
        )

    request_ids = [f"request_stage8_{index:03d}" for index in range(12)]

    def reserve(request_id: str) -> tuple[str, dict]:
        return request_id, ai_budgets.reserve(
            request_id, WS_A, USER_A, "openai", "gpt-5-mini", "analysis",
            0.01, prompt_hash,
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(reserve, request_ids))
    admitted = [(request_id, row) for request_id, row in outcomes if row.get("ok")]
    denied = [row for _request_id, row in outcomes if not row.get("ok")]
    assert len(admitted) == 5
    assert len(denied) == 7
    assert {row["code"] for row in denied} == {"daily_budget_exceeded"}

    request_id, reservation = admitted[0]
    replay = ai_budgets.reserve(
        request_id, WS_A, USER_A, "openai", "gpt-5-mini", "analysis",
        0.01, prompt_hash,
    )
    assert replay["ok"] is True and replay["idempotent_replay"] is True
    assert replay["reservation_id"] == reservation["reservation_id"]
    conflict = ai_budgets.reserve(
        request_id, WS_A, USER_A, "openai", "different-model", "analysis",
        0.01, prompt_hash,
    )
    assert conflict == {"ok": False, "code": "idempotency_conflict"}

    cancel_request = "request_stage8_cancel_workspace_b"
    assert ai_budgets.reserve(
        cancel_request, WS_B, USER_B, "openai", "gpt-5-mini", "analysis",
        0.01, prompt_hash,
    )["ok"] is True
    assert ai_budgets.cancel_reservation(cancel_request, WS_A) is False
    assert ai_budgets.cancel_reservation(cancel_request, WS_B) is True

    usage = ai_budgets.record_usage(
        request_id, WS_A, USER_A, "openai", "gpt-5-mini", "analysis",
        "stage8_acceptance", "success", 100, 20, 0.01, prompt_hash,
        document={
            "api_key": "sk-NEVERSTORE123456789",
            "client_path": r"C:\\Users\\private\\prompt.txt",
        },
    )
    assert usage == {"ok": True, "code": "recorded"}
    assert ai_budgets.record_usage(
        request_id, WS_A, USER_A, "openai", "gpt-5-mini", "analysis",
        "stage8_acceptance", "success", 100, 20, 0.01, prompt_hash,
        document={
            "api_key": "sk-NEVERSTORE123456789",
            "client_path": r"C:\\Users\\private\\prompt.txt",
        },
    ) == {"ok": True, "code": "recorded"}
    assert ai_budgets.record_usage(
        request_id, WS_A, USER_A, "openai", "gpt-5-mini", "analysis",
        "stage8_acceptance", "success", 100, 20, 0.02, prompt_hash,
    ) == {"ok": False, "code": "idempotency_conflict"}
    assert ai_budgets.check_budget(WS_A, 0.01)["ok"] is False
    assert ai_budgets.check_budget(WS_B, 0.05)["ok"] is True

    with stage8_store["client"].transaction(
        Scope(user_id=USER_A, workspace_id=WS_A), read_only=True,
    ) as conn:
        own = conn.execute(
            "SELECT document,cost_usd FROM sf_ai_usage_events WHERE workspace_id=%s",
            (WS_A,),
        ).fetchone()
        foreign_count = conn.execute(
            "SELECT count(*) AS n FROM sf_ai_usage_events WHERE workspace_id=%s",
            (WS_B,),
        ).fetchone()["n"]
    assert float(own["cost_usd"]) == pytest.approx(0.01)
    assert own["document"]["api_key"] == "[redacted]"
    assert own["document"]["client_path"] == "[private-path]"
    assert foreign_count == 0

    with pytest.raises(StorageConstraintError):
        with stage8_store["client"].transaction(
            Scope(user_id=USER_A, workspace_id=WS_A),
        ) as conn:
            conn.execute(
                """INSERT INTO sf_ai_usage_events(
                     request_id,workspace_id,user_id,provider,model,role,purpose,
                     status,prompt_sha256,document
                   ) VALUES('request_cross_tenant',%s,%s,'openai','gpt','analysis',
                     'forbidden','success',%s,'{}'::jsonb)""",
                (WS_B, USER_B, prompt_hash),
            )


def test_stage8_market_data_connector_to_practice_e2e_and_isolation(stage8_store) -> None:
    now = datetime.now(timezone.utc)
    assert market_data_ingestion.ingest_batch(
        WS_A, INST_A1, 50, [_bar(now - timedelta(seconds=25), close=100.25)],
        user_id=USER_A,
    )["ok"] is True
    assert market_data_ingestion.ingest_batch(
        WS_A, INST_A2, 1, [_bar(now - timedelta(seconds=2), close=101.25)],
        user_id=USER_A,
    )["ok"] is True
    assert market_data_ingestion.ingest_batch(
        WS_A, INST_A2, 2, [_bar(now - timedelta(seconds=2), timeframe="1d")],
        user_id=USER_A,
    )["ok"] is True
    assert market_data_ingestion.ingest_batch(
        WS_B, INST_B, 1, [_bar(now - timedelta(minutes=10), close=88.0)],
        user_id=USER_B,
    )["ok"] is True

    index_a = market_data_ingestion.workspace_snapshot_index(WS_A)
    assert index_a["storage_available"] is True
    assert set(index_a["snapshots"]) == {"MNQ 09-26|1m", "MNQ 09-26|1D"}
    assert index_a["snapshots"]["MNQ 09-26|1m"]["installation_id"] == INST_A2
    series_a = market_data_ingestion.workspace_series(
        WS_A, "MNQ 09-26", "1m", 4, snapshot_index=index_a,
    )
    series_b = market_data_ingestion.workspace_series(WS_B, "MNQ 09-26", "1m", 4)
    assert series_a and series_a["quote"]["last"] == pytest.approx(101.25)
    assert series_a["live"] is True and series_a["execution_blocked"] is False
    assert series_b and series_b["live"] is False and series_b["execution_blocked"] is True
    assert market_data_ingestion.workspace_series(
        WS_B, "MNQ 09-26", "1m", 4, snapshot_index=index_a,
    ) is None

    assert market_data_ingestion.subscribe(
        WS_A, INST_A1, USER_A, "MNQ 09-26", "1d",
    ) == {"ok": True, "code": "subscribed"}
    active = market_data_ingestion.active_subscriptions(WS_A)
    assert active[0]["timeframe"] == "1D"
    assert market_data_ingestion.subscribe(
        WS_A, INST_B, USER_A, "MNQ 09-26", "1m",
    ) == {"ok": False, "code": "storage_unavailable"}
    assert market_data_ingestion.ingest_batch(
        WS_A, INST_B, 99, [_bar(now)], user_id=USER_A,
    ) == {
        "ok": False, "code": "storage_unavailable",
        "batch_id": "", "items": 0, "deduplicated": False,
    }
    assert market_data_ingestion.ingest_batch(
        WS_A, INST_A1, 51, [_bar(now, timeframe="241m")], user_id=USER_A,
    )["code"] == "empty_or_invalid_batch"

    quote_a = server._practice_market_quote("MNQ 09-26", workspace_id=WS_A)
    quote_b = server._practice_market_quote("MNQ 09-26", workspace_id=WS_B)
    quote_none = server._practice_market_quote(
        "MNQ 09-26", workspace_id="ws_personal_STAGE8CCC",
    )
    assert quote_a["tradable"] is True and quote_a["price"] == pytest.approx(101.25)
    assert quote_b["tradable"] is False and quote_b["price"] == 0.0
    assert quote_none["tradable"] is False and quote_none["price"] == 0.0


def test_stage8_dashboard_alert_dedupe_recovery_and_redaction(stage8_store) -> None:
    queue = stage8_store["queue"]
    for role in observability.REQUIRED_PRODUCTION_SERVICE_ROLES:
        observability.heartbeat(
            role, instance_id=f"stage8-{role}",
            details={"authorization": "Bearer TOPSECRET123456", "queue_depth": 0},
        )
    with stage8_store["client"].transaction(Scope.global_service_scope()) as conn:
        conn.execute(
            """INSERT INTO sf_connector_sessions(
                 session_id,installation_id,workspace_id,token_hash,expires_at,
                 document
               ) VALUES
                 ('session_stage8_active',%s,%s,%s,clock_timestamp()+interval '1 hour','{}'),
                 ('session_stage8_revoked',%s,%s,%s,clock_timestamp()+interval '1 hour','{}')""",
            (INST_A1, WS_A, "1" * 64, INST_B, WS_B, "2" * 64),
        )
        conn.execute(
            "UPDATE sf_connector_sessions SET revoked_at=clock_timestamp() WHERE session_id='session_stage8_revoked'"
        )
    dead = queue.enqueue_text("dead alert", dedupe_key="stage8-alert-dead")
    claimed = queue.claim_outbox("stage8-alert-worker")
    assert claimed and claimed["outbox_id"] == dead["outbox_id"]
    with stage8_store["client"].transaction(Scope.global_service_scope()) as conn:
        conn.execute(
            "UPDATE sf_telegram_outbox SET attempts=%s WHERE outbox_id=%s",
            (production_telegram.MAX_ATTEMPTS, dead["outbox_id"]),
        )
    assert queue.finish_outbox(
        claimed["outbox_id"], claimed["lease_token"], error="terminal send failure",
    )

    first = observability.evaluate_alerts(stale_after_sec=45)
    second = observability.evaluate_alerts(stale_after_sec=45)
    operation_fp = observability._alert_fingerprint(
        "operations", "telegram_outbox_dead_letter",
    )
    with stage8_store["client"].transaction(
        Scope.global_service_scope(), read_only=True,
    ) as conn:
        incidents = conn.execute(
            "SELECT event_id FROM sf_operational_events WHERE fingerprint=%s",
            (operation_fp,),
        ).fetchall()
    assert len(incidents) == 1
    assert incidents[0]["event_id"] in first["raised"]
    assert incidents[0]["event_id"] in second["raised"]

    dashboard = observability.dashboard()
    serialized = str(dashboard)
    assert dashboard["ok"] is True
    assert dashboard["queues"]["telegram_outbox_dead_letter"] == 1
    assert dashboard["connectors"]["online"] == 3
    assert dashboard["connector_sessions"] == {"active": 1, "expired": 0, "revoked": 1}
    assert dashboard["service_health"]["production"] is True
    assert "TOPSECRET" not in serialized
    assert "[redacted]" in serialized

    with stage8_store["client"].transaction(Scope.global_service_scope()) as conn:
        conn.execute("DELETE FROM sf_telegram_outbox WHERE outbox_id=%s", (dead["outbox_id"],))
    recovered = observability.evaluate_alerts(stale_after_sec=45)
    assert incidents[0]["event_id"] in recovered["resolved"]
    with stage8_store["client"].transaction(
        Scope.global_service_scope(), read_only=True,
    ) as conn:
        status = conn.execute(
            "SELECT status FROM sf_operational_events WHERE event_id=%s",
            (incidents[0]["event_id"],),
        ).fetchone()["status"]
    assert status == "resolved"


def test_stage8_retention_is_bounded_and_covers_sensitive_operational_state(stage8_store) -> None:
    queue = stage8_store["queue"]
    update = _update(101, 555, "terminal inbox content")
    assert queue.enqueue_update(update, transport="poll")
    claimed_update = queue.claim_update("stage8-retention")
    assert claimed_update
    assert queue.finish_update(claimed_update["update_key"], claimed_update["lease_token"])
    outgoing = queue.enqueue_text("terminal outbox content", dedupe_key="stage8-retention")
    claimed_outbox = queue.claim_outbox("stage8-retention")
    assert claimed_outbox
    assert queue.finish_outbox(claimed_outbox["outbox_id"], claimed_outbox["lease_token"])
    pending_update = _update(102, 555, "pending inbox must survive retention")
    assert queue.enqueue_update(pending_update, transport="poll")
    pending_outbox = queue.enqueue_text(
        "pending outbox must survive retention", dedupe_key="stage8-retention-pending",
    )

    prompt_hash = hashlib.sha256(b"retention").hexdigest()
    assert ai_budgets.reserve(
        "request_retention_pending", WS_A, USER_A, "openai", "gpt", "analysis",
        0.01, prompt_hash,
    )["ok"]
    assert ai_budgets.record_usage(
        "request_retention_usage", WS_A, USER_A, "openai", "gpt", "analysis",
        "retention", "success", 10, 5, 0.01, prompt_hash,
    )["ok"]
    now = datetime.now(timezone.utc)
    batch = market_data_ingestion.ingest_batch(
        WS_A, INST_A1, 1, [_bar(now)], user_id=USER_A,
    )
    assert batch["ok"]
    incident_id = observability.event(
        "retention", "expired", severity="warning", fingerprint="e" * 64,
    )
    open_incident_id = observability.event(
        "retention", "open_must_survive", severity="critical", fingerprint="f" * 64,
    )
    audit_id = audit_events.record(
        "stage8", "retention", "acceptance", workspace_id=WS_A,
        user_id=USER_A, details={"password": "must-redact"},
    )
    assert audit_id.startswith("aud_")

    with stage8_store["client"].transaction(Scope.global_service_scope()) as conn:
        conn.execute(
            "UPDATE sf_telegram_updates SET retention_until=clock_timestamp()-interval '1 second'"
        )
        conn.execute(
            "UPDATE sf_telegram_outbox SET retention_until=clock_timestamp()-interval '1 second'"
        )
        conn.execute(
            "UPDATE sf_ai_reservations SET expires_at=clock_timestamp()-interval '1 second'"
        )
        conn.execute(
            "UPDATE sf_ai_usage_events SET retention_until=clock_timestamp()-interval '1 second'"
        )
        conn.execute(
            "UPDATE sf_market_data_ingest_batches SET retention_until=clock_timestamp()-interval '1 second'"
        )
        conn.execute(
            "UPDATE sf_market_data_snapshots SET stale_after=clock_timestamp()-interval '8 days'"
        )
        conn.execute(
            """UPDATE sf_operational_events SET status='resolved',
                 retention_until=clock_timestamp()-interval '1 second'
               WHERE event_id=%s""",
            (incident_id,),
        )
        conn.execute(
            "UPDATE sf_audit_events SET retention_until=clock_timestamp()-interval '1 second' WHERE event_id=%s",
            (audit_id,),
        )
        conn.execute(
            "UPDATE sf_operational_events SET retention_until=clock_timestamp()-interval '1 second' WHERE event_id=%s",
            (open_incident_id,),
        )
        conn.execute(
            """INSERT INTO sf_connector_sessions(
                 session_id,installation_id,workspace_id,token_hash,expires_at,
                 revoked_at,document
               ) VALUES('session_retention_old',%s,%s,%s,
                 clock_timestamp()-interval '100 days',
                 clock_timestamp()-interval '100 days','{}')""",
            (INST_A1, WS_A, "3" * 64),
        )
        conn.execute(
            """INSERT INTO sf_service_heartbeats(
                 service_role,instance_id,status,heartbeat_at,document
               ) VALUES('retention','retention-instance','healthy',
                 clock_timestamp()-interval '31 days','{}')"""
        )
        conn.execute(
            """INSERT INTO sf_service_leases(
                 lease_name,owner_id,lease_token,leased_until,heartbeat_at
               ) VALUES('retention-lease','retention-instance',%s::uuid,
                 clock_timestamp()-interval '2 days',
                 clock_timestamp()-interval '2 days')""",
            (str(uuid.uuid4()),),
        )
        conn.execute(
            """INSERT INTO sf_rate_limit_buckets(
                 subject_hash,action_class,window_started_at,request_count,expires_at
               ) VALUES(%s,'retention.test',clock_timestamp()-interval '1 hour',1,
                 clock_timestamp()-interval '1 second')""",
            ("4" * 64,),
        )
        conn.execute(
            """INSERT INTO sf_idempotency_keys(
                 workspace_id,operation,key_hash,request_hash,state,expires_at
               ) VALUES(%s,'retention.test',%s,%s,'completed',
                 clock_timestamp()-interval '1 second')""",
            (WS_A, "5" * 64, "6" * 64),
        )

    removed = observability.sweep_retention(limit=1)
    assert removed == {
        "ai_reservations": 1,
        "telegram_updates": 1,
        "telegram_outbox": 1,
        "ai_usage": 1,
        "market_batches": 1,
        "operational_events": 1,
        "audit_events": 1,
        "market_snapshots": 1,
        "market_subscriptions": 0,
        "service_heartbeats": 1,
        "service_leases": 1,
        "connector_sessions": 1,
        "rate_limits": 1,
        "idempotency": 1,
    }
    with stage8_store["client"].transaction(
        Scope.global_service_scope(), read_only=True,
    ) as conn:
        assert conn.execute(
            "SELECT status FROM sf_telegram_updates WHERE update_id=%s",
            (102,),
        ).fetchone()["status"] == "queued"
        assert conn.execute(
            "SELECT status FROM sf_telegram_outbox WHERE outbox_id=%s",
            (pending_outbox["outbox_id"],),
        ).fetchone()["status"] == "queued"
        assert conn.execute(
            "SELECT status FROM sf_operational_events WHERE event_id=%s",
            (open_incident_id,),
        ).fetchone()["status"] == "open"


def test_stage8_storage_outage_fails_closed_before_processing(stage8_store, monkeypatch) -> None:
    bad_url = APP_URL.replace(":55432/", ":55433/")
    bad_client = PostgresClient(bad_url, production=False)
    monkeypatch.setattr(production_storage_package, "get_client", lambda: bad_client)
    monkeypatch.setattr(ai_budgets, "get_client", lambda: bad_client)
    monkeypatch.setattr(observability, "get_client", lambda: bad_client)
    prompt_hash = hashlib.sha256(b"outage").hexdigest()
    bar = _bar(datetime.now(timezone.utc))

    assert ai_budgets.reserve(
        "request_outage_stage8", WS_A, USER_A, "openai", "gpt", "analysis",
        0.01, prompt_hash,
    ) == {"ok": False, "code": "storage_unavailable"}
    assert market_data_ingestion.ingest_batch(
        WS_A, INST_A1, 777, [bar], user_id=USER_A,
    ) == {
        "ok": False, "code": "storage_unavailable",
        "batch_id": "", "items": 0, "deduplicated": False,
    }
    with pytest.raises(StorageUnavailableError):
        production_telegram.ProductionTelegramQueue(bad_client).enqueue_update(
            _update(777, 777), transport="poll",
        )
    dashboard = observability.dashboard()
    assert dashboard["ok"] is False
    assert dashboard["storage"] == {"ok": False, "code": "storage_unavailable"}


def test_stage8_outbox_parallel_load_is_lossless(stage8_store) -> None:
    queue = stage8_store["queue"]

    def enqueue(index: int) -> str:
        return queue.enqueue_text(
            f"load message {index}", dedupe_key=f"stage8-load-{index:03d}",
        )["outbox_id"]

    with ThreadPoolExecutor(max_workers=20) as pool:
        identifiers = list(pool.map(enqueue, range(100)))
    assert len(identifiers) == 100
    assert len(set(identifiers)) == 100
    with stage8_store["client"].transaction(
        Scope.global_service_scope(), read_only=True,
    ) as conn:
        row = conn.execute(
            """SELECT count(*) AS total,count(DISTINCT dedupe_hash) AS unique_dedupe
               FROM sf_telegram_outbox"""
        ).fetchone()
    assert row == {"total": 100, "unique_dedupe": 100}
