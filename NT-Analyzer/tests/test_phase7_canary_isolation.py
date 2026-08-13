"""Phase 7 — Canary environment isolation invariants.

These tests exercise the fail-closed guarantees that keep the Canary contour
fully separated from Production: identity/DSN/data-root/host collision guards,
per-environment session cookie and local-storage namespaces, the Telegram
environment marker, Connector environment binding, the readiness contract and
the secret-free deploy templates. They never touch a real database, tunnel,
Telegram bot or Connector.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import (
    connector_protocol,
    connector_releases,
    observability,
    production_workers,
    runtime_env,
    server as server_mod,
    service_readiness,
    storage_router,
    worker_router,
)
from app.production_storage import StorageConfigurationError
from tools import canary_isolation_provision


REPO_ROOT = Path(__file__).resolve().parent.parent
CANARY_DEPLOY = REPO_ROOT / "deploy" / "canary"


_ENV_KEYS = (
    "DEPLOYMENT_ENV",
    "STRATFORGE_ENV",
    "NTA_APP_ENV",
    "NTA_ENV",
    "STRATFORGE_INSTANCE_ID",
    "STRATFORGE_DEPLOYMENT_ROLE",
    "STRATFORGE_CONFIG_PROFILE",
    "APP_VERSION",
    "BUILD_TIMESTAMP_UTC",
    "RELEASE_CHANNEL",
    "BUILD_ID",
    "GIT_COMMIT_SHA",
    "ARTIFACT_SHA256",
    "DIRTY",
    "STRATFORGE_REGION",
    "STRATFORGE_BIND_HOST",
    "STRATFORGE_ALLOWED_HOSTS",
    "STRATFORGE_PUBLIC_ORIGIN",
    "STRATFORGE_EDGE_MODE",
    "STRATFORGE_TRUSTED_PROXY_IPS",
    "STRATFORGE_DATA_ROOT",
    "STRATFORGE_CANARY_DATA_ROOT",
    "STRATFORGE_DEVELOPMENT_DATA_ROOT",
    "STRATFORGE_DATABASE_ID",
    "STRATFORGE_QUEUE_ID",
    "STRATFORGE_OBJECT_STORAGE_ID",
    "STRATFORGE_TELEGRAM_BOT_ID",
    "STRATFORGE_COOKIE_NAMESPACE",
    "STRATFORGE_SIGNING_KEY_ID",
    "STRATFORGE_LOG_NAMESPACE",
    "STRATFORGE_DATABASE_URL",
    "STRATFORGE_STORAGE_MODE",
    "STRATFORGE_DATABASE_APP_ROLE",
    "STRATFORGE_PRODUCTION_DATABASE_ID",
    "STRATFORGE_PRODUCTION_QUEUE_ID",
    "STRATFORGE_PRODUCTION_OBJECT_STORAGE_ID",
    "STRATFORGE_PRODUCTION_TELEGRAM_BOT_ID",
    "STRATFORGE_PRODUCTION_COOKIE_NAMESPACE",
    "STRATFORGE_PRODUCTION_SIGNING_KEY_ID",
    "STRATFORGE_PRODUCTION_LOG_NAMESPACE",
    "STRATFORGE_PRODUCTION_INSTANCE_ID",
    "STRATFORGE_PRODUCTION_PUBLIC_ORIGIN",
    "STRATFORGE_PRODUCTION_ALLOWED_HOSTS",
    "STRATFORGE_PRODUCTION_DATA_ROOT",
    "STRATFORGE_PRODUCTION_DATABASE_URL",
    "STRATFORGE_CANARY_TELEGRAM_BOT_ID",
    "STRATFORGE_LIVE_TRADING_ALLOWED",
    "STRATFORGE_REAL_PAYMENTS_ALLOWED",
    "STRATFORGE_PRIVATE_BIND_CONFIRMED",
    "NTA_ALLOW_LIVE_ORDERS",
    "NTA_ALLOW_REAL_PAYMENTS",
    "NTA_ENABLE_TEST_AUTH",
    "NTA_ENABLE_IMPERSONATION",
    "NTA_DISABLE_RATE_LIMIT",
    "NTA_TEST_BYPASS_AUTH",
    "NTA_TELEGRAM_BOT_TOKEN",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _build_identity(monkeypatch) -> None:
    monkeypatch.setenv("APP_VERSION", "1.0.0-test")
    monkeypatch.setenv("BUILD_TIMESTAMP_UTC", "2026-07-21T12:34:56Z")
    monkeypatch.setenv("BUILD_ID", "sf-1.0.0-test-20260721")
    monkeypatch.setenv("GIT_COMMIT_SHA", "a" * 40)
    monkeypatch.setenv("ARTIFACT_SHA256", "B" * 64)
    monkeypatch.setenv("DIRTY", "0")


def _production_reference(monkeypatch) -> None:
    monkeypatch.setenv("STRATFORGE_PRODUCTION_DATABASE_ID", "postgres-primary")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_QUEUE_ID", "production-jobs")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_OBJECT_STORAGE_ID", "production-artifacts")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_TELEGRAM_BOT_ID", "production-main")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_COOKIE_NAMESPACE", "sf-prod")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_SIGNING_KEY_ID", "production-key-v1")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_LOG_NAMESPACE", "production")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_INSTANCE_ID", "stratforge-prod-01")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_PUBLIC_ORIGIN", "https://app.stratforges.com")
    monkeypatch.setenv("STRATFORGE_PRODUCTION_ALLOWED_HOSTS", "app.stratforges.com")


def _canary_env(monkeypatch, tmp_path: Path, **overrides) -> Path:
    _build_identity(monkeypatch)
    _production_reference(monkeypatch)
    data_root = tmp_path / "canary"
    data_root.mkdir(parents=True, exist_ok=True)
    values = {
        "DEPLOYMENT_ENV": "canary",
        "STRATFORGE_INSTANCE_ID": "stratforge-canary-01",
        "STRATFORGE_DEPLOYMENT_ROLE": "all-in-one",
        "STRATFORGE_CONFIG_PROFILE": "canary-primary",
        "RELEASE_CHANNEL": "beta",
        "STRATFORGE_REGION": "canary",
        "STRATFORGE_BIND_HOST": "127.0.0.1",
        "STRATFORGE_ALLOWED_HOSTS": "canary.stratforges.com",
        "STRATFORGE_PUBLIC_ORIGIN": "https://canary.stratforges.com",
        "STRATFORGE_EDGE_MODE": "cloudflare-tunnel",
        "STRATFORGE_TRUSTED_PROXY_IPS": "127.0.0.1,::1",
        "STRATFORGE_CANARY_DATA_ROOT": str(data_root),
        "STRATFORGE_DATABASE_ID": "postgres-canary",
        "STRATFORGE_QUEUE_ID": "canary-jobs",
        "STRATFORGE_OBJECT_STORAGE_ID": "canary-artifacts",
        "STRATFORGE_TELEGRAM_BOT_ID": "canary-main",
        "STRATFORGE_COOKIE_NAMESPACE": "sf-canary",
        "STRATFORGE_SIGNING_KEY_ID": "canary-key-v1",
        "STRATFORGE_LOG_NAMESPACE": "canary",
        "STRATFORGE_LIVE_TRADING_ALLOWED": "0",
        "STRATFORGE_REAL_PAYMENTS_ALLOWED": "0",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return data_root


def _production_env(monkeypatch, tmp_path: Path, **overrides) -> None:
    _build_identity(monkeypatch)
    data_root = tmp_path / "production"
    data_root.mkdir(parents=True, exist_ok=True)
    values = {
        "DEPLOYMENT_ENV": "production",
        "STRATFORGE_INSTANCE_ID": "stratforge-prod-01",
        "STRATFORGE_DEPLOYMENT_ROLE": "all-in-one",
        "STRATFORGE_CONFIG_PROFILE": "production-primary",
        "RELEASE_CHANNEL": "stable",
        "STRATFORGE_REGION": "primary",
        "STRATFORGE_BIND_HOST": "127.0.0.1",
        "STRATFORGE_ALLOWED_HOSTS": "app.stratforges.com",
        "STRATFORGE_PUBLIC_ORIGIN": "https://app.stratforges.com",
        "STRATFORGE_EDGE_MODE": "cloudflare-tunnel",
        "STRATFORGE_TRUSTED_PROXY_IPS": "127.0.0.1,::1",
        "STRATFORGE_DATA_ROOT": str(data_root),
        "STRATFORGE_DATABASE_ID": "postgres-primary",
        "STRATFORGE_QUEUE_ID": "production-jobs",
        "STRATFORGE_OBJECT_STORAGE_ID": "production-artifacts",
        "STRATFORGE_TELEGRAM_BOT_ID": "production-main",
        "STRATFORGE_COOKIE_NAMESPACE": "sf-prod",
        "STRATFORGE_SIGNING_KEY_ID": "production-key-v1",
        "STRATFORGE_LOG_NAMESPACE": "production",
        "STRATFORGE_LIVE_TRADING_ALLOWED": "0",
        "STRATFORGE_REAL_PAYMENTS_ALLOWED": "0",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


# --------------------------------------------------------------------------- #
# Per-environment namespaces.
# --------------------------------------------------------------------------- #
def test_session_cookie_name_is_isolated_for_canary(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    assert runtime_env.session_cookie_name() == "sf_canary_session"


def test_session_cookie_name_unchanged_for_development(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    assert runtime_env.session_cookie_name() == "sf_session"


def test_session_cookie_name_is_isolated_for_production(monkeypatch, tmp_path):
    # Phase 11: Production has its own distinct cookie name, not the dev default.
    _production_env(monkeypatch, tmp_path)
    assert runtime_env.session_cookie_name() == "sf_production_session"


def test_local_storage_namespace_distinct_per_environment(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    assert runtime_env.local_storage_namespace() == "canary"
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    assert runtime_env.local_storage_namespace() == ""


def test_telegram_environment_marker(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    assert runtime_env.telegram_environment_marker() == "[CANARY] "
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    assert runtime_env.telegram_environment_marker() == "[DEV] "
    _production_env(monkeypatch, tmp_path)
    assert runtime_env.telegram_environment_marker() == ""


# --------------------------------------------------------------------------- #
# Isolation guard.
# --------------------------------------------------------------------------- #
def test_isolated_canary_startup_is_accepted(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    config = runtime_env.assert_startup_safe()
    assert config.environment == "canary"
    assert config.public_origin == "https://canary.stratforges.com"
    # An isolated Canary passes the dedicated guard without raising.
    runtime_env.assert_environment_isolation(config)


@pytest.mark.parametrize(
    "override_key, override_value",
    [
        ("STRATFORGE_DATABASE_ID", "postgres-primary"),
        ("STRATFORGE_QUEUE_ID", "production-jobs"),
        ("STRATFORGE_OBJECT_STORAGE_ID", "production-artifacts"),
        ("STRATFORGE_TELEGRAM_BOT_ID", "production-main"),
        ("STRATFORGE_COOKIE_NAMESPACE", "sf-prod"),
        ("STRATFORGE_SIGNING_KEY_ID", "production-key-v1"),
        ("STRATFORGE_LOG_NAMESPACE", "production"),
        ("STRATFORGE_INSTANCE_ID", "stratforge-prod-01"),
        ("STRATFORGE_PUBLIC_ORIGIN", "https://app.stratforges.com"),
    ],
)
def test_canary_identity_collision_is_rejected(monkeypatch, tmp_path, override_key, override_value):
    overrides = {override_key: override_value}
    # public_origin collision also needs the host to match to build a config,
    # but the guard fires on the origin field before host validation matters.
    if override_key == "STRATFORGE_PUBLIC_ORIGIN":
        overrides["STRATFORGE_ALLOWED_HOSTS"] = "app.stratforges.com"
    _canary_env(monkeypatch, tmp_path, **overrides)
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_startup_safe()


def test_canary_shared_production_dsn_is_rejected(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    dsn = "postgresql://stratforge_app@db.internal:5432/stratforge"
    monkeypatch.setenv("STRATFORGE_DATABASE_URL", dsn)
    monkeypatch.setenv("STRATFORGE_PRODUCTION_DATABASE_URL", dsn)
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_environment_isolation()


def test_canary_shared_data_root_is_rejected(monkeypatch, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    _canary_env(monkeypatch, tmp_path, STRATFORGE_CANARY_DATA_ROOT=str(shared))
    monkeypatch.setenv("STRATFORGE_PRODUCTION_DATA_ROOT", str(shared))
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_environment_isolation()


def test_canary_shared_allowed_hosts_is_rejected(monkeypatch, tmp_path):
    # A Canary that declares the Production host is rejected by the guard.
    _canary_env(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_PRODUCTION_ALLOWED_HOSTS", "canary.stratforges.com")
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_environment_isolation()


def test_production_guard_rejects_declared_canary_bot(monkeypatch, tmp_path):
    _production_env(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_CANARY_TELEGRAM_BOT_ID", "production-main")
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_environment_isolation()


def test_production_guard_allows_isolated_bot(monkeypatch, tmp_path):
    _production_env(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_CANARY_TELEGRAM_BOT_ID", "canary-main")
    runtime_env.assert_environment_isolation()


# --------------------------------------------------------------------------- #
# Connector environment binding.
# --------------------------------------------------------------------------- #
def test_connector_rejects_cross_environment_installation(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    production_record = {"deployment_environment": "production"}
    with pytest.raises(connector_protocol.ConnectorProtocolError) as excinfo:
        connector_protocol._assert_environment(production_record)
    assert excinfo.value.code == "connector_environment_mismatch"


def test_connector_accepts_same_environment_installation(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    connector_protocol._assert_environment({"deployment_environment": "canary"})


def test_connector_grandfathers_unstamped_installation(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    # A pre-existing installation without the field is not rejected.
    connector_protocol._assert_environment({})


def test_canary_connector_repository_uses_server_storage_not_local_secure_store(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    monkeypatch.setattr(connector_protocol.secure_store, "available", lambda: False)
    monkeypatch.setattr(
        storage_router, "document_repository_readiness",
        lambda _name: {"ok": True, "code": "ok"},
    )
    monkeypatch.setattr(
        storage_router, "read_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("readiness must not load the connectors document")
        ),
    )

    assert connector_protocol.readiness_status() == {"ok": True, "code": "ok"}


# --------------------------------------------------------------------------- #
# Readiness contract.
# --------------------------------------------------------------------------- #
def test_canary_readiness_requires_control_plane_probes(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    config = runtime_env.deployment_config(strict=False)
    payload = service_readiness.readiness_payload(config)
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"]["ok"] is False


def test_canary_readiness_discloses_disabled_telegram_without_blocking(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    config = runtime_env.deployment_config(strict=False)
    probes = {
        name: (lambda: True)
        for name in service_readiness.PRODUCTION_COMPONENTS
        if name != "telegram_consumer"
    }

    payload = service_readiness.readiness_payload(
        config,
        probes=probes,
        minimum_free_mb=1,
        optional_components={
            "telegram_consumer": "disabled_pending_canary_bot_provisioning",
        },
    )

    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["checks"]["telegram_consumer"] == {
        "ok": False,
        "code": "disabled_pending_canary_bot_provisioning",
    }


def test_optional_readiness_component_cannot_hide_registered_failure(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    config = runtime_env.deployment_config(strict=False)
    probes = {name: (lambda: True) for name in service_readiness.PRODUCTION_COMPONENTS}
    probes["telegram_consumer"] = lambda: {"ok": False, "code": "consumer_missing"}

    payload = service_readiness.readiness_payload(
        config,
        probes=probes,
        minimum_free_mb=1,
        optional_components={
            "telegram_consumer": "disabled_pending_canary_bot_provisioning",
        },
    )

    assert payload["ok"] is False
    assert payload["checks"]["telegram_consumer"] == {
        "ok": False,
        "code": "consumer_missing",
    }


def test_canary_http_server_marks_missing_telegram_consumer_optional(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    config = runtime_env.assert_startup_safe()
    srv = server_mod.create_http_server(config, bind_port=0)
    try:
        assert "telegram_consumer" not in srv.readiness_probes
        assert srv.readiness_optional_components == {
            "telegram_consumer": "disabled_pending_canary_bot_provisioning",
        }
    finally:
        srv.server_close()


def test_canary_http_server_requires_telegram_probe_once_token_exists(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    monkeypatch.setenv("NTA_TELEGRAM_BOT_TOKEN", "placeholder-test-token")
    config = runtime_env.assert_startup_safe()
    srv = server_mod.create_http_server(config, bind_port=0)
    try:
        assert "telegram_consumer" in srv.readiness_probes
        assert srv.readiness_optional_components == {}
    finally:
        srv.server_close()


def test_canary_run_does_not_start_development_local_worker_or_notifier(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path, STRATFORGE_DEPLOYMENT_ROLE="api")
    monkeypatch.setattr(storage_router, "assert_production_storage_safe", lambda: None)

    class FakeEmitter:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    class FakeServer:
        server_address = ("127.0.0.1", 0)

        def admission_metrics(self):
            return {}

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            pass

        def server_close(self):
            pass

    unexpected = []

    def unexpected_start(name):
        def _start(*args, **kwargs):
            unexpected.append(name)
            return True
        return _start

    monkeypatch.setattr(server_mod.observability, "HeartbeatEmitter", FakeEmitter)
    monkeypatch.setattr(server_mod, "create_http_server", lambda deployment, bind_port: FakeServer())
    monkeypatch.setattr(server_mod.ai_stale_sweep, "start_background_sweeper", lambda **kwargs: None)
    monkeypatch.setattr(server_mod.news_refresh, "start_background_refresher", lambda: None)
    monkeypatch.setattr(server_mod.ai_chief_agent, "start_background_worker", lambda **kwargs: None)
    monkeypatch.setattr(server_mod.vitek, "start_background_worker", lambda **kwargs: None)
    monkeypatch.setattr(server_mod.market_data, "start_chart_worker", lambda **kwargs: None)
    monkeypatch.setattr(server_mod.market_data_ipc, "start_server", lambda: (_ for _ in ()).throw(RuntimeError("disabled")))
    monkeypatch.setattr(server_mod.market_data_gap_recovery, "start_background_worker", lambda **kwargs: None)
    monkeypatch.setattr(server_mod.market_data_live_supervisor, "start", lambda: {})
    monkeypatch.setattr(server_mod.local_worker, "start_background_worker", unexpected_start("local_worker"))
    monkeypatch.setattr(server_mod.telegram_service, "start_background_notifier", unexpected_start("telegram_notifier"))
    for module, name in (
        (server_mod.ai_stale_sweep, "stop_background_sweeper"),
        (server_mod.news_refresh, "stop_background_refresher"),
        (server_mod.ai_chief_agent, "stop_background_worker"),
        (server_mod.vitek, "stop_background_worker"),
        (server_mod.local_worker, "stop_background_worker"),
        (server_mod.telegram_service, "stop_background_notifier"),
        (server_mod.market_data, "stop_chart_worker"),
        (server_mod.market_data_gap_recovery, "stop_background_worker"),
        (server_mod.market_data_ipc, "stop_server"),
        (server_mod.market_data_live_supervisor, "stop"),
    ):
        monkeypatch.setattr(module, name, lambda: None)

    server_mod.run(0)

    assert unexpected == []


def test_canary_routes_storage_and_workers_to_authoritative_backends(monkeypatch, tmp_path):
    artifact_root = tmp_path / "objects"
    artifact_root.mkdir()
    _canary_env(
        monkeypatch,
        tmp_path,
        STRATFORGE_STORAGE_MODE="postgresql",
        STRATFORGE_DATABASE_URL="postgresql://stratforge_app@db.internal/stratforge_canary",
        STRATFORGE_ARTIFACT_ROOT=str(artifact_root),
    )
    with pytest.raises(StorageConfigurationError, match="stratforge_canary_app"):
        storage_router.assert_production_storage_safe()

    monkeypatch.setenv("STRATFORGE_DATABASE_APP_ROLE", "stratforge_canary_app")
    monkeypatch.setenv(
        "STRATFORGE_DATABASE_URL",
        "postgresql://stratforge_canary_app@db.internal/stratforge_canary",
    )
    monkeypatch.setattr(storage_router, "get_client", lambda production=False: object())

    assert storage_router.production_enabled() is True
    assert worker_router._production() is True
    storage_router.assert_production_storage_safe()


def test_canary_heartbeat_role_matrix_excludes_production_only_processes(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)

    assert observability._expected_service_roles() == ("api", "worker")
    assert production_workers._required_heartbeat_roles() == ("worker",)


def test_canary_operations_maintenance_is_allowed(monkeypatch):
    monkeypatch.setattr(
        observability.runtime_env,
        "assert_startup_safe",
        lambda: SimpleNamespace(environment=runtime_env.CANARY, deployment_role="worker"),
    )
    monkeypatch.setattr(storage_router, "assert_production_storage_safe", lambda: None)
    monkeypatch.setattr(observability, "evaluate_alerts", lambda: {"ok": True, "raised": []})
    monkeypatch.setattr(observability, "sweep_retention", lambda: {"audit_events": 1})

    assert observability.production_maintenance() == {
        "ok": True,
        "alerts_raised": 0,
        "retention": {"audit_events": 1},
    }


def test_development_readiness_has_no_control_plane_probes(monkeypatch, tmp_path):
    development = tmp_path / "development"
    development.mkdir()
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(development))
    config = runtime_env.deployment_config(strict=False)
    payload = service_readiness.readiness_payload(config)
    assert "database" not in payload["checks"]


# --------------------------------------------------------------------------- #
# Deploy templates carry no secrets.
# --------------------------------------------------------------------------- #
def test_canary_deploy_assets_exist():
    for name in (
        "canary.env.example",
        "cloudflared.yml.example",
        "cloudflared.service",
        "connector-releases.example.json",
        "README.md",
        "stratforge-canary.service",
        "stratforge-canary-worker.service",
        "stratforge-canary-telegram.service",
        "stratforge-canary-operations.service",
        "stratforge-canary-operations.timer",
        "run-api-canary.sh.example",
        "run-worker-canary.sh.example",
        "run-telegram-canary.sh.example",
        "run-operations-canary.sh.example",
        "supervisor-canary-programs.conf.example",
    ):
        assert (CANARY_DEPLOY / name).is_file(), name


def test_canary_env_declares_isolated_identity():
    text = (CANARY_DEPLOY / "canary.env.example").read_text(encoding="utf-8")
    assert "DEPLOYMENT_ENV=canary" in text
    assert "STRATFORGE_DEPLOYMENT_ROLE=api" in text
    assert "STRATFORGE_CANARY_DATA_ROOT=" in text
    assert "STRATFORGE_CANARY_ORIGIN=https://canary.stratforges.com" in text
    assert "STRATFORGE_PRODUCTION_ORIGIN=https://app.stratforges.com" in text
    assert "STRATFORGE_DATABASE_APP_ROLE=stratforge_canary_app" in text
    # Production reference identifiers must be present for the collision guard.
    assert "STRATFORGE_PRODUCTION_DATABASE_ID=" in text
    assert "STRATFORGE_PRODUCTION_TELEGRAM_BOT_ID=" in text
    assert "STRATFORGE_MIGRATION_DATABASE_URL" not in text
    assert "STRATFORGE_BACKUP_DATABASE_URL" not in text


def test_canary_supervisor_templates_declare_split_worker_topology():
    supervisor = (CANARY_DEPLOY / "supervisor-canary-programs.conf.example").read_text(encoding="utf-8")
    api = (CANARY_DEPLOY / "run-api-canary.sh.example").read_text(encoding="utf-8")
    worker = (CANARY_DEPLOY / "run-worker-canary.sh.example").read_text(encoding="utf-8")
    telegram = (CANARY_DEPLOY / "run-telegram-canary.sh.example").read_text(encoding="utf-8")
    operations = (CANARY_DEPLOY / "run-operations-canary.sh.example").read_text(encoding="utf-8")

    assert "[program:api]" in supervisor
    assert "[program:worker-canary]" in supervisor
    assert "[program:operations-canary]" in supervisor
    assert "[program:telegram-canary]" in supervisor
    assert "--init-system supervisor" in api
    assert "--init-system supervisor" in worker
    assert "--init-system supervisor" in telegram
    assert "--init-system supervisor" in operations
    assert "exec .venv/bin/python -m app.production_workers" in worker
    assert "exec .venv/bin/python -m app.production_telegram" in telegram
    assert "--classes interactive_ai,chart,telemetry,maintenance" in worker
    assert ".venv/bin/python -m app.observability --maintenance" in operations


def test_canary_promotion_requires_lockdown_marker_and_full_topology():
    promote = (REPO_ROOT / "tools" / "canary_blue_green_promote.sh").read_text(encoding="utf-8")

    assert "LOCKDOWN_MARKER_PATH" in promote
    assert "canary-privilege-lockdown.ok.json" in promote
    assert "canary_telegram_configured" in promote
    assert "NTA_TELEGRAM_BOT_TOKEN" in promote
    assert promote.index('canary_env="$config/canary.env"') < promote.index("canary_telegram_configured=false")
    assert "ensure_canary_telegram_supervisor_program" in promote
    assert "run-telegram-canary.sh.example" in promote
    assert "required Canary Supervisor program(s) missing" in promote
    assert "canary-current must exist before blue-green promotion" in promote
    assert "missing_targets" in promote
    assert "supervisorctl -c \"$conf\" reread" in promote
    assert "supervisorctl -c \"$conf\" update" in promote
    assert "LIVE_URL" in promote
    assert "new runtime identity was not observed on /live" in promote
    assert "--max-time \"$LIVE_CURL_MAX_SEC\"" in promote
    assert "--max-time \"$READY_CURL_MAX_SEC\"" in promote
    assert '"status": "ready"' in promote
    assert "Do not use curl -f" in promote
    assert "--max-time 5" not in promote


def test_canary_connector_catalog_template_matches_strict_schema(monkeypatch, tmp_path):
    template = json.loads((CANARY_DEPLOY / "connector-releases.example.json").read_text(encoding="utf-8"))
    placeholder_hash = "0" * 64
    for channel in ("stable", "canary"):
        template["channels"][channel]["version"] = "0.0.1"
        template["channels"][channel]["archive_sha256"] = placeholder_hash
        template["channels"][channel]["manifest_sha256"] = placeholder_hash
        template["channels"][channel]["minimum_version"] = "0.0.1"
        template["channels"][channel]["published_at_utc"] = "2026-08-11T00:00:00Z"
    path = tmp_path / "connector-releases-canary.json"
    path.write_text(json.dumps(template), encoding="utf-8")
    monkeypatch.setenv("STRATFORGE_CONNECTOR_RELEASE_CATALOG", str(path))

    catalog = connector_releases.load_catalog()

    assert set(catalog["channels"]) == {"stable", "canary"}


def test_canary_provision_refreshes_stale_connector_catalog_on_force(tmp_path):
    path = tmp_path / "connector-releases-canary.json"
    path.write_text(json.dumps({"schema_version": 1, "channel": "beta", "installations": []}), encoding="utf-8")

    assert canary_isolation_provision._connector_catalog_needs_refresh(path) is True
    path.write_text(json.dumps(canary_isolation_provision.default_connector_catalog()), encoding="utf-8")
    assert canary_isolation_provision._connector_catalog_needs_refresh(path) is False


def test_canary_deploy_templates_have_no_real_secrets():
    for path in CANARY_DEPLOY.glob("*"):
        if not path.is_file() or path.suffix == ".md":
            # README prose intentionally discusses secrets; only config
            # templates are scanned for real secret-bearing assignments.
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lowered = line.lower()
            if any(marker in lowered for marker in ("token", "secret", "database_url", "credentials-file")):
                # Any secret-bearing assignment must be a placeholder only.
                assert (
                    "__" in line
                    or "from_protected" in lowered
                    or line.endswith("=")
                    or ".json" in lowered
                ), f"potential real secret in {path.name}: {line}"


def _provision_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    production_env = tmp_path / "production-app.env"
    production_env.write_text(
        "\n".join((
            "STRATFORGE_DATABASE_URL=postgresql://stratforge_app@db.internal/stratforge",
            "STRATFORGE_INSTANCE_ID=stratforge-prod-01",
            f"STRATFORGE_DATA_ROOT={tmp_path / 'production'}",
            "STRATFORGE_DATABASE_ID=postgres-primary",
            "STRATFORGE_QUEUE_ID=production-jobs",
            "STRATFORGE_OBJECT_STORAGE_ID=production-artifacts",
            "STRATFORGE_TELEGRAM_BOT_ID=production-main",
            "STRATFORGE_COOKIE_NAMESPACE=sf-prod",
            "STRATFORGE_SIGNING_KEY_ID=production-key-v1",
            "STRATFORGE_LOG_NAMESPACE=production",
            "STRATFORGE_PUBLIC_ORIGIN=https://app.stratforges.com",
            "STRATFORGE_ALLOWED_HOSTS=app.stratforges.com",
        )) + "\n",
        encoding="utf-8",
    )
    values = {
        "canary_app_role": "stratforge_canary_app",
        "canary_migration_role": "stratforge_canary_migration",
        "canary_db_name": "stratforge_canary",
        "instance_id": "stratforge-canary-01",
        "canary_data_root": str(tmp_path / "canary" / "var"),
        "canary_artifact_root": str(tmp_path / "canary" / "artifacts"),
        "production_env_path": str(production_env),
        "connector_catalog_path": str(tmp_path / "connector-releases-canary.json"),
        "config_profile": "production-canary",
        "pg_socket": str(tmp_path / "run" / "postgresql"),
        "pg_port": 5432,
        "pg_ca_cert": str(tmp_path / "postgresql-ca.crt"),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_canary_provision_env_is_api_only_and_least_privilege(tmp_path):
    args = _provision_args(tmp_path)
    dsn = {
        "app_url": "postgresql://stratforge_canary_app:app_pw@localhost/stratforge_canary",
        "migration_url": "postgresql://stratforge_canary_migration:migration_pw@localhost/stratforge_canary",
    }

    content = canary_isolation_provision.build_canary_env(args, dsn, "test-signing-key")
    maintenance = canary_isolation_provision.build_canary_maintenance_env(args, dsn)

    assert "STRATFORGE_DEPLOYMENT_ROLE=api" in content
    assert "STRATFORGE_DATABASE_APP_ROLE=stratforge_canary_app" in content
    assert "STRATFORGE_DATABASE_URL=postgresql://stratforge_canary_app:" in content
    assert "\nSTRATFORGE_MIGRATION_DATABASE_URL=" not in content
    assert "\nSTRATFORGE_BACKUP_DATABASE_URL=" not in content
    assert "STRATFORGE_MIGRATION_DATABASE_URL=postgresql://stratforge_canary_migration:" in maintenance
    assert "STRATFORGE_BACKUP_DATABASE_URL=postgresql://stratforge_canary_migration:" in maintenance


def test_canary_provision_guard_rejects_unsafe_sql_identifiers(tmp_path):
    args = _provision_args(tmp_path, canary_app_role="stratforge_canary_app;drop")
    production = canary_isolation_provision._read_env_file(Path(args.production_env_path))

    with pytest.raises(canary_isolation_provision.ProvisionGuardError, match="PostgreSQL identifier"):
        canary_isolation_provision._preflight_collision_guard(args, production)


def test_canary_privilege_lockdown_revokes_production_and_public(tmp_path):
    args = _provision_args(tmp_path)
    production = canary_isolation_provision._read_env_file(Path(args.production_env_path))
    canary_isolation_provision._preflight_collision_guard(args, production)

    sql = canary_isolation_provision.lockdown_privileges_sql(args, "stratforge_app")

    assert "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM stratforge_app" in sql
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC" in sql
    assert "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO stratforge_canary_app" in sql
    assert "GRANT USAGE,SELECT ON SEQUENCES TO stratforge_canary_app" in sql


def test_canary_lockdown_psql_script_is_readable_by_postgres_user(monkeypatch):
    observed = {}

    def fake_run(command, *, check, capture_output, text):
        assert command[:4] == ["sudo", "-n", "-u", "postgres"]
        script_path = Path(command[-1])
        observed["mode"] = os.stat(script_path).st_mode & 0o777
        observed["text"] = script_path.read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(canary_isolation_provision.subprocess, "run", fake_run)

    canary_isolation_provision._run_psql_script(
        "/tmp/postgresql", 5432, "stratforge_canary", "SELECT 1;",
    )

    assert observed["mode"] & 0o044
    assert observed["text"] == "BEGIN;\nSELECT 1;\nCOMMIT;\n"


def test_canary_lockdown_marker_is_secret_free_and_required_by_promotion(tmp_path):
    marker_path = tmp_path / "config" / "canary-privilege-lockdown.ok.json"
    result = {
        "ok": True,
        "canary_database_name": "stratforge_canary",
        "canary_app_role": "stratforge_canary_app",
        "revoked_from": ["stratforge_app", "PUBLIC"],
        "granted_to": "stratforge_canary_app",
    }

    canary_isolation_provision.write_lockdown_marker(marker_path, result)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))

    assert marker["schema_version"] == 1
    assert marker["ok"] is True
    assert marker["canary_database_name"] == "stratforge_canary"
    assert marker["canary_app_role"] == "stratforge_canary_app"
    assert marker["revoked_from"] == ["stratforge_app", "PUBLIC"]
    assert "password" not in json.dumps(marker).lower()
