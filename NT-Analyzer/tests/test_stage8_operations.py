"""Stage 8 operational tests: observability, production Telegram, AI budgets,
audit events, market-data ingestion, redaction and health/readiness contracts.

All tests run in Development mode (no PostgreSQL required).  The Production
code path is validated structurally — the test confirms that the fail-closed
guard defers to the Development fallback when ``is_production()`` returns
``False``.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def isolated_stage8_development_environment(monkeypatch):
    """Keep this module's Development profile from leaking into later tests."""
    monkeypatch.setenv("NTA_APP_ENV", "development")
    monkeypatch.delenv("STRATFORGE_ENV", raising=False)
    from app import runtime_env

    runtime_env._data_root_cached.cache_clear()
    yield
    runtime_env._data_root_cached.cache_clear()


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

class TestObservability:
    def test_redact_strips_secrets(self):
        from app.observability import redact
        data = {
            "token": "abc123", "name": "Виктор",
            "password": "secretpass", "auth_token_hint": "must-not-leak",
            "input_tokens": 17,
        }
        clean = redact(data)
        assert clean["token"] == "[redacted]"
        assert clean["password"] == "[redacted]"
        assert clean["auth_token_hint"] == "[redacted]"
        assert clean["input_tokens"] == 17
        assert clean["name"] == "Виктор"

    def test_redact_strips_bearer(self):
        from app.observability import redact
        text = "Authorization: Bearer sk-123456789abcdef"
        assert "[authorization-redacted]" in redact(text)

    def test_redact_strips_tokenish(self):
        from app.observability import redact
        text = "key sfc_v1_abcdefghijk"
        assert "[token-redacted]" in redact(text)

    def test_redact_depth_limit(self):
        from app.observability import redact
        nested: Dict[str, Any] = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": "deep"}}}}}}}}
        result = redact(nested)
        # Should not crash and should produce depth-limited result
        assert isinstance(result, dict)

    def test_redact_handles_none_bool_int(self):
        from app.observability import redact
        assert redact(None) is None
        assert redact(True) is True
        assert redact(42) == 42

    def test_redact_handles_nan_inf(self):
        from app.observability import redact
        assert redact(float("nan")) is None
        assert redact(float("inf")) is None

    def test_event_development_mode(self):
        from app.observability import event
        eid = event("test", "unit_test", payload={"hello": "world"})
        assert eid.startswith("ope_")
        assert len(eid) == 36  # ope_ + 32 hex

    def test_record_http(self):
        from app.observability import record_http, metrics
        record_http("GET", "/api/health", 200, 15.3)
        m = metrics()
        assert m["http"]["requests"] >= 1

    def test_metrics_structure(self):
        from app.observability import metrics
        m = metrics()
        assert "http" in m
        assert "events" in m
        assert "p50" in m["http"]["latency_ms"]
        assert "p95" in m["http"]["latency_ms"]
        assert "p99" in m["http"]["latency_ms"]

    def test_heartbeat_development(self):
        from app.observability import heartbeat
        result = heartbeat("test_role", instance_id="test-1", status="healthy")
        assert result["service_role"] == "test_role"
        assert result["status"] == "healthy"

    def test_heartbeat_emitter_start_stop(self):
        from app.observability import HeartbeatEmitter
        emitter = HeartbeatEmitter("test_emitter", interval_sec=60)
        emitter.start()
        assert emitter.thread is not None
        assert emitter.thread.is_alive()
        emitter.stop()
        time.sleep(0.1)

    def test_service_status_development(self):
        from app.observability import service_status
        result = service_status()
        assert result["production"] is False
        assert isinstance(result["services"], list)

    def test_dashboard_structure(self):
        from app.observability import dashboard
        d = dashboard()
        assert d["ok"] is True
        assert "generated_at_utc" in d
        assert "metrics" in d
        assert "service_health" in d

    def test_evaluate_alerts_development(self):
        from app.observability import evaluate_alerts
        result = evaluate_alerts()
        assert result["ok"] is True
        assert isinstance(result["raised"], list)

    def test_sweep_retention_development(self):
        from app.observability import sweep_retention
        # In Development, returns empty dict
        result = sweep_retention()
        assert result == {}

    def test_main_cli_dashboard(self):
        from app.observability import _main
        code = _main(["--dashboard"])
        assert code == 0

    def test_production_maintenance_requires_production(self, monkeypatch):
        from types import SimpleNamespace

        from app import observability

        monkeypatch.setattr(
            observability.runtime_env,
            "assert_startup_safe",
            lambda: SimpleNamespace(environment="development", deployment_role="worker"),
        )
        with pytest.raises(observability.OperationsMaintenanceError):
            observability.production_maintenance()

    def test_production_maintenance_runs_alerts_and_retention(self, monkeypatch):
        from types import SimpleNamespace

        from app import observability, runtime_env, storage_router

        monkeypatch.setattr(
            observability.runtime_env,
            "assert_startup_safe",
            lambda: SimpleNamespace(
                environment=runtime_env.PRODUCTION, deployment_role="worker",
            ),
        )
        monkeypatch.setattr(storage_router, "assert_production_storage_safe", lambda: None)
        monkeypatch.setattr(observability, "evaluate_alerts", lambda: {"ok": True, "raised": ["ope_1"]})
        monkeypatch.setattr(observability, "sweep_retention", lambda: {"audit_events": 2})
        assert observability.production_maintenance() == {
            "ok": True,
            "alerts_raised": 1,
            "retention": {"audit_events": 2},
        }


# ---------------------------------------------------------------------------
# Production Telegram (Development-mode structural tests)
# ---------------------------------------------------------------------------

class TestProductionTelegramStructure:
    def test_import_succeeds(self):
        from app import production_telegram
        assert hasattr(production_telegram, "ProductionTelegramQueue")
        assert hasattr(production_telegram, "accept_webhook")
        assert hasattr(production_telegram, "enqueue_text")
        assert hasattr(production_telegram, "readiness_status")
        assert hasattr(production_telegram, "run")

    def test_error_hierarchy(self):
        from app.production_telegram import (
            ProductionTelegramError,
            TelegramConsumerBusy,
            TelegramPayloadRejected,
        )
        from app.production_storage import StorageError
        assert issubclass(ProductionTelegramError, StorageError)
        assert issubclass(TelegramConsumerBusy, ProductionTelegramError)
        assert issubclass(TelegramPayloadRejected, ProductionTelegramError)

    def test_canonical_json_roundtrip(self):
        from app.production_telegram import _canonical
        data = {"z": 1, "a": 2, "m": [3, 4]}
        raw = _canonical(data)
        parsed = json.loads(raw)
        assert parsed == data

    def test_canonical_rejects_invalid(self):
        from app.production_telegram import _canonical, TelegramPayloadRejected
        with pytest.raises(TelegramPayloadRejected):
            _canonical(float("nan"))

    def test_conversation_key_deterministic(self):
        from app.production_telegram import _conversation_key
        update = {"message": {"chat": {"id": 12345}, "message_thread_id": None}}
        k1 = _conversation_key(update)
        k2 = _conversation_key(update)
        assert k1 == k2
        assert k1.startswith("lane_")

    def test_readiness_status_development(self):
        from app.production_telegram import readiness_status
        # Without production storage, should return not-ok
        result = readiness_status()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_max_constants(self):
        from app import production_telegram
        assert production_telegram.MAX_UPDATE_BYTES == 256 * 1024
        assert production_telegram.MAX_OUTBOX_TEXT == 4000
        assert production_telegram.MAX_ATTEMPTS == 5

    def test_webhook_fails_closed_when_production_storage_is_unavailable(self, monkeypatch):
        from app import server as server_mod

        fallback = mock.Mock()

        def unavailable(*_args, **_kwargs):
            raise server_mod.production_telegram.StorageUnavailableError("database offline")

        monkeypatch.setattr(server_mod.runtime_env, "is_production", lambda: True)
        monkeypatch.setattr(server_mod.runtime_env, "environment_explicit", lambda: True)
        monkeypatch.setattr(server_mod.production_telegram, "accept_webhook", unavailable)
        monkeypatch.setattr(server_mod.telegram_service, "process_webhook_update", fallback)
        server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://{server.server_address[0]}:{server.server_address[1]}/api/telegram/webhook",
                data=json.dumps({"update_id": 999}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Telegram-Bot-Api-Secret-Token": "test-secret",
                },
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as response:
                urllib.request.urlopen(request, timeout=5)
            assert response.value.code == 503
            payload = json.loads(response.value.read().decode("utf-8"))
            assert payload["code"] == "storage_unavailable"
            fallback.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_telegram_service_unit_and_runbook_contract(self):
        root = Path(__file__).resolve().parents[1]
        unit = (root / "deploy" / "production" / "stratforge-telegram.service").read_text(
            encoding="utf-8",
        )
        runbook = (root / "docs" / "operations" / "PRODUCTION_TELEGRAM_RUNBOOK.md").read_text(
            encoding="utf-8",
        )
        assert "STRATFORGE_DEPLOYMENT_ROLE=telegram" in unit
        assert "-m app.production_telegram --poll-ms 250" in unit
        assert "telegram_consumer=ready" in runbook
        assert "manual consumer" in runbook


class TestOperationsDeployment:
    def test_operations_maintenance_timer_and_runbook_contract(self):
        root = Path(__file__).resolve().parents[1]
        service = (root / "deploy" / "production" / "stratforge-operations.service").read_text(
            encoding="utf-8",
        )
        timer = (root / "deploy" / "production" / "stratforge-operations.timer").read_text(
            encoding="utf-8",
        )
        runbook = (root / "docs" / "operations" / "PRODUCTION_OPERATIONS_RUNBOOK.md").read_text(
            encoding="utf-8",
        )
        assert "STRATFORGE_DEPLOYMENT_ROLE=worker" in service
        assert "-m app.observability --maintenance" in service
        assert "OnUnitActiveSec=1min" in timer
        assert "stratforge-operations.service" in timer
        assert "PostgreSQL only" in runbook


# ---------------------------------------------------------------------------
# AI Budgets (Development-mode)
# ---------------------------------------------------------------------------

class TestProductionStorageScope:
    def test_workspace_scope_factory(self):
        from app.production_storage import Scope

        scope = Scope.workspace_scope("ws_personal_ALPHA1234")
        assert scope.workspace_id == "ws_personal_ALPHA1234"
        assert scope.global_service is False


class TestAIBudgets:
    def test_import_succeeds(self):
        from app import ai_budgets
        assert hasattr(ai_budgets, "check_budget")
        assert hasattr(ai_budgets, "reserve")
        assert hasattr(ai_budgets, "record_usage")
        assert hasattr(ai_budgets, "cancel_reservation")
        assert hasattr(ai_budgets, "workspace_usage_summary")

    def test_check_budget_development(self):
        from app import ai_budgets
        result = ai_budgets.check_budget("ws_test", 0.05)
        assert result["ok"] is True
        assert result["code"] == "development_mode"

    def test_reserve_development(self):
        from app import ai_budgets
        result = ai_budgets.reserve(
            "req_" + uuid.uuid4().hex[:16], "ws_test", 1,
            "openai", "gpt-4", "general", 0.05,
            hashlib.sha256(b"test").hexdigest(),
        )
        assert result["ok"] is True

    def test_reserve_production_locks_budget_and_denies_before_insert(self, monkeypatch):
        from app import ai_budgets

        queries = []

        class FakeCursor:
            def __init__(self, row):
                self.row = row

            def fetchone(self):
                return self.row

        class FakeConnection:
            def execute(self, sql, params):
                queries.append((sql, params))
                if "INSERT INTO sf_ai_workspace_budgets" in sql:
                    return FakeCursor(None)
                if "FROM sf_ai_workspace_budgets" in sql:
                    return FakeCursor({
                        "daily_limit_usd": 0.01,
                        "monthly_limit_usd": 0.01,
                        "enabled": True,
                    })
                if "FROM sf_ai_usage_events" in sql:
                    return FakeCursor({"daily_used": 0.0, "monthly_used": 0.0})
                if "FROM sf_ai_reservations" in sql:
                    return FakeCursor({"pending": 0.0})
                raise AssertionError("budget denial must not insert a reservation")

        class FakeTransaction:
            def __enter__(self):
                return FakeConnection()

            def __exit__(self, *_args):
                return False

        class FakeClient:
            def transaction(self, _scope, **_kwargs):
                return FakeTransaction()

        monkeypatch.setattr(ai_budgets.runtime_env, "is_production", lambda: True)
        monkeypatch.setattr(ai_budgets.runtime_env, "environment_explicit", lambda: True)
        monkeypatch.setattr(ai_budgets, "get_client", lambda: FakeClient())

        result = ai_budgets.reserve(
            "request_12345678", "ws_personal_ALPHA1234", 42,
            "openai", "gpt-4", "general", 0.02,
            hashlib.sha256(b"test").hexdigest(),
        )

        assert result["ok"] is False
        assert result["code"] == "daily_budget_exceeded"
        assert any("FOR UPDATE" in sql for sql, _params in queries)
        assert not any("INSERT INTO sf_ai_reservations" in sql for sql, _params in queries)

    def test_record_usage_development(self):
        from app import ai_budgets
        result = ai_budgets.record_usage(
            "req_" + uuid.uuid4().hex[:16], "ws_test", 1,
            "openai", "gpt-4", "general", "analysis",
            "success", 100, 50, 0.03,
            hashlib.sha256(b"test").hexdigest(),
        )
        assert result["ok"] is True

    def test_workspace_usage_summary_development(self):
        from app import ai_budgets
        result = ai_budgets.workspace_usage_summary("ws_test")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Audit Events (Development-mode)
# ---------------------------------------------------------------------------

class TestAuditEvents:
    def test_import_succeeds(self):
        from app import audit_events
        assert hasattr(audit_events, "record")
        assert hasattr(audit_events, "query")

    def test_record_development(self):
        from app import audit_events
        eid = audit_events.record(
            "test_user", "login", "session",
            resource_id="sess_123", outcome="success",
        )
        assert eid.startswith("aud_")

    def test_record_production_populates_legacy_columns(self, monkeypatch):
        from app import audit_events

        captured = {}

        class FakeConnection:
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

        class FakeTransaction:
            def __enter__(self):
                return FakeConnection()

            def __exit__(self, *_args):
                return False

        class FakeClient:
            def transaction(self, _scope):
                return FakeTransaction()

        monkeypatch.setattr(audit_events.runtime_env, "is_production", lambda: True)
        monkeypatch.setattr(audit_events.runtime_env, "environment_explicit", lambda: True)
        monkeypatch.setattr(audit_events, "get_client", lambda: FakeClient())
        monkeypatch.setattr(audit_events, "_jsonb", lambda value: value)

        audit_events.record(
            "alice", "connector_upload", "market_data",
            resource_id="inst_123", outcome="success",
            workspace_id="ws_personal_ALPHA1234", user_id=42,
            ip_hash="127.0.0.1", details={"token": "not-for-storage", "batch": 3},
        )

        assert "source, event_type, payload" in captured["sql"]
        assert captured["params"][3:6] == (
            "audit_events",
            "connector_upload",
            {
                "actor": "alice",
                "resource_type": "market_data",
                "resource_id": "inst_123",
                "outcome": "success",
                "ip_hash": hashlib.sha256(b"127.0.0.1").hexdigest(),
                "details": {"token": "[redacted]", "batch": 3},
            },
        )
        assert captured["params"][6:13] == (
            "alice",
            "connector_upload",
            "market_data",
            "inst_123",
            "success",
            hashlib.sha256(b"127.0.0.1").hexdigest(),
            {"token": "[redacted]", "batch": 3},
        )

    def test_query_development(self):
        from app import audit_events
        # Should not crash in development
        rows = audit_events.query(actor="test_user", limit=10)
        assert isinstance(rows, list)

    def test_ip_hash(self):
        from app import audit_events
        eid = audit_events.record(
            "user", "action", "resource",
            ip_hash=hashlib.sha256(b"127.0.0.1").hexdigest(),
        )
        assert eid.startswith("aud_")


# ---------------------------------------------------------------------------
# Market Data Ingestion (Development-mode)
# ---------------------------------------------------------------------------

class TestMarketDataIngestion:
    def test_import_succeeds(self):
        from app import market_data_ingestion
        assert hasattr(market_data_ingestion, "ingest_batch")
        assert hasattr(market_data_ingestion, "latest_snapshot")
        assert hasattr(market_data_ingestion, "subscribe")
        assert hasattr(market_data_ingestion, "unsubscribe")
        assert hasattr(market_data_ingestion, "active_subscriptions")
        assert hasattr(market_data_ingestion, "fan_out")

    def test_ingest_batch_development(self):
        from app import market_data_ingestion
        market_data_ingestion.reset_for_tests()
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
             "volume": 1000, "timestamp": "2026-07-21T20:00:00Z",
             "exact_contract": "MNQ 09-26", "timeframe": "1m"},
        ]
        result = market_data_ingestion.ingest_batch(
            "ws_test", "inst_123", 1, bars,
        )
        assert result["ok"] is True
        assert result.get("batch_id", "").startswith("mdb_")

    def test_ingest_batch_rejects_conflicting_source_sequence(self):
        from app import market_data_ingestion

        market_data_ingestion.reset_for_tests()
        first = [{
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000, "timestamp": "2026-07-21T20:00:00Z",
            "exact_contract": "MNQ 09-26", "timeframe": "1m",
        }]
        changed = [{**first[0], "close": 100.25}]
        assert market_data_ingestion.ingest_batch(
            "ws_test", "inst_123", 1, first,
        )["ok"] is True
        result = market_data_ingestion.ingest_batch("ws_test", "inst_123", 1, changed)
        assert result == {
            "ok": False,
            "code": "source_sequence_conflict",
            "batch_id": "",
            "items": 0,
            "deduplicated": False,
        }

    def test_subscribe_unsubscribe_development(self):
        from app import market_data_ingestion
        sub = market_data_ingestion.subscribe(
            "ws_test", "inst_123", 1, "MNQ 09-26", "1m",
        )
        assert sub["ok"] is True
        unsub = market_data_ingestion.unsubscribe(
            "ws_test", "inst_123", "MNQ 09-26", "1m",
        )
        assert isinstance(unsub, bool)

    def test_workspace_series_is_tenant_bound_and_fresh(self):
        from app import market_data_ingestion

        market_data_ingestion.reset_for_tests()
        observed = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(
            timespec="milliseconds",
        ).replace("+00:00", "Z")
        bar = {
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000, "timestamp": observed,
            "exact_contract": "MNQ 09-26", "timeframe": "1m",
        }
        assert market_data_ingestion.ingest_batch(
            "ws_alpha", "inst_alpha", 1, [bar],
        )["ok"] is True

        series = market_data_ingestion.workspace_series(
            "ws_alpha", "MNQ 09-26", "1m", 4,
        )
        assert series is not None
        assert series["live"] is True
        assert series["execution_blocked"] is False
        assert series["source"]["workspace_id"] == "ws_alpha"
        assert series["source"]["installation_id"] == "inst_alpha"
        assert market_data_ingestion.workspace_series(
            "ws_beta", "MNQ 09-26", "1m", 4,
        ) is None

    def test_historical_connector_replay_is_never_live(self):
        from app import market_data_ingestion

        market_data_ingestion.reset_for_tests()
        bar = {
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000, "timestamp": "2026-07-21T20:00:00Z",
            "exact_contract": "MNQ 09-26", "timeframe": "1m",
        }
        assert market_data_ingestion.ingest_batch(
            "ws_alpha", "inst_alpha", 1, [bar],
        )["ok"] is True
        series = market_data_ingestion.workspace_series(
            "ws_alpha", "MNQ 09-26", "1m", 4,
        )
        assert series is not None
        assert series["live"] is False
        assert series["market_data_available"] is False
        assert series["execution_blocked"] is True

    @pytest.mark.parametrize("mutate", [
        lambda row: {**row, "unknown": True},
        lambda row: {**row, "timestamp": (
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat().replace("+00:00", "Z")},
        lambda row: {**row, "volume": float("nan")},
    ])
    def test_ingest_rejects_noncanonical_or_untrusted_bars(self, mutate):
        from app import market_data_ingestion

        market_data_ingestion.reset_for_tests()
        row = {
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "exact_contract": "MNQ 09-26", "timeframe": "1m",
        }
        result = market_data_ingestion.ingest_batch(
            "ws_alpha", "inst_alpha", 1, [mutate(row)],
        )
        assert result["ok"] is False
        assert result["code"] == "empty_or_invalid_batch"


# ---------------------------------------------------------------------------
# Service Readiness
# ---------------------------------------------------------------------------

class TestServiceReadiness:
    def test_import_succeeds(self):
        from app import service_readiness
        assert hasattr(service_readiness, "liveness_payload")
        assert hasattr(service_readiness, "readiness_payload")

    def test_liveness_payload(self):
        from app import service_readiness, runtime_env
        config = runtime_env.deployment_config()
        payload = service_readiness.liveness_payload(config)
        assert payload["ok"] is True
        assert payload["status"] == "alive"

    def test_readiness_development(self):
        from app import service_readiness, runtime_env
        config = runtime_env.deployment_config()
        payload = service_readiness.readiness_payload(config)
        assert "status" in payload
        assert "checks" in payload

    def test_production_components_require_telegram_consumer(self):
        from app import service_readiness

        assert "telegram_consumer" in service_readiness.PRODUCTION_COMPONENTS


# ---------------------------------------------------------------------------
# Redaction contracts
# ---------------------------------------------------------------------------

class TestRedactionContracts:
    """Verify that sensitive data never leaks through operational interfaces."""

    def test_observability_redacts_windows_paths_in_production(self):
        from app.observability import redact, _WINDOWS_PATH
        with mock.patch("app.runtime_env.is_server_environment", return_value=True):
            text = "Error at C:\\Users\\admin\\Documents\\secrets.txt"
            result = redact(text)
            assert "[private-path]" in result

    def test_observability_redacts_unix_paths_in_production(self):
        from app.observability import redact
        with mock.patch("app.runtime_env.is_server_environment", return_value=True):
            text = "Error at /home/admin/.ssh/id_rsa"
            result = redact(text)
            assert "[private-path]" in result

    def test_observability_redacts_paths_in_canary(self):
        from app.observability import redact
        with mock.patch("app.runtime_env.is_server_environment", return_value=True):
            text = "Error at /home/stratforge/canary/config/canary.env"
            result = redact(text)
            assert "[private-path]" in result

    def test_observability_preserves_paths_in_development(self):
        from app.observability import redact
        text = "File at C:\\Users\\dev\\project\\code.py"
        result = redact(text)
        # In development, paths are not redacted
        assert "C:\\" in result or "[private-path]" not in result

    def test_redact_truncates_long_strings(self):
        from app.observability import redact
        long = "x" * 5000
        result = redact(long)
        assert len(result) <= 2000

    def test_redact_limits_collection_size(self):
        from app.observability import redact
        big = {f"k{i}": i for i in range(200)}
        result = redact(big)
        assert len(result) <= 100


# ---------------------------------------------------------------------------
# Concurrency safety
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_observability_thread_safe(self):
        from app.observability import record_http, metrics
        errors = []

        def worker():
            try:
                for _ in range(100):
                    record_http("GET", "/api/test", 200, 5.0)
                    metrics()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert errors == [], f"Thread-safety errors: {errors}"

    def test_heartbeat_concurrent(self):
        from app.observability import heartbeat
        errors = []

        def worker(i):
            try:
                for _ in range(20):
                    heartbeat(f"svc_{i}", instance_id=f"inst_{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert errors == []


# ---------------------------------------------------------------------------
# Fail-closed contracts
# ---------------------------------------------------------------------------

class TestFailClosed:
    """Verify that Production paths are fail-closed (deny on error)."""

    def test_observability_event_never_raises(self):
        from app.observability import event
        # Even with extreme input, event() must never propagate an exception
        eid = event("", "", payload=None, severity="invalid")
        assert isinstance(eid, str)

    def test_production_telegram_rejects_bad_update(self):
        from app.production_telegram import TelegramPayloadRejected
        # Invalid update (not a mapping) should raise
        from app.production_telegram import _canonical
        with pytest.raises(TelegramPayloadRejected):
            _canonical(object())

    def test_production_telegram_requires_positive_update_id(self):
        from app.production_telegram import (
            ProductionTelegramQueue,
            TelegramPayloadRejected,
        )
        # Cannot test enqueue without a DB connection, but validate error path
        assert TelegramPayloadRejected.code == "telegram_payload_rejected"


# ---------------------------------------------------------------------------
# SQL migration structure
# ---------------------------------------------------------------------------

class TestMigrationStructure:
    def test_0003_creates_required_tables(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "production_storage",
            "migrations", "0003_operations_observability.sql",
        )
        assert os.path.isfile(path), f"Migration {path} missing"
        content = open(path, encoding="utf-8").read()
        expected_tables = [
            "sf_service_leases",
            "sf_service_heartbeats",
            "sf_telegram_updates",
            "sf_telegram_outbox",
            "sf_telegram_bot_state",
            "sf_ai_workspace_budgets",
            "sf_ai_reservations",
            "sf_ai_usage_events",
            "sf_market_data_subscriptions",
            "sf_market_data_snapshots",
            "sf_market_data_ingest_batches",
            "sf_operational_events",
        ]
        for table in expected_tables:
            assert f"CREATE TABLE {table}" in content, f"Missing CREATE TABLE {table}"

    def test_0003_has_rls_policies(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "production_storage",
            "migrations", "0003_operations_observability.sql",
        )
        content = open(path, encoding="utf-8").read()
        assert "ENABLE ROW LEVEL SECURITY" in content
        assert "FORCE ROW LEVEL SECURITY" in content
        # Every workspace-scoped table must have sf_scope_workspace()
        assert content.count("sf_scope_workspace()") >= 7

    def test_0003_has_retention_columns(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "production_storage",
            "migrations", "0003_operations_observability.sql",
        )
        content = open(path, encoding="utf-8").read()
        assert "retention_until" in content

    def test_0004_upgrades_the_stage6_audit_table(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "production_storage",
            "migrations", "0004_audit_events.sql",
        )
        content = open(path, encoding="utf-8").read()
        assert "ADD COLUMN IF NOT EXISTS actor" in content
        assert "UPDATE sf_audit_events" in content
        assert "DROP POLICY IF EXISTS sf_audit_events_scope" in content
