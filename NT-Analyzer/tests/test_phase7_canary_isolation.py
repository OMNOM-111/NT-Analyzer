"""Phase 7 — Canary environment isolation invariants.

These tests exercise the fail-closed guarantees that keep the Canary contour
fully separated from Production: identity/DSN/data-root/host collision guards,
per-environment session cookie and local-storage namespaces, the Telegram
environment marker, Connector environment binding, the readiness contract and
the secret-free deploy templates. They never touch a real database, tunnel,
Telegram bot or Connector.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import connector_protocol, runtime_env, service_readiness


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


# --------------------------------------------------------------------------- #
# Readiness contract.
# --------------------------------------------------------------------------- #
def test_canary_readiness_requires_control_plane_probes(monkeypatch, tmp_path):
    _canary_env(monkeypatch, tmp_path)
    config = runtime_env.deployment_config(strict=False)
    payload = service_readiness.readiness_payload(config)
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"]["ok"] is False


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
    ):
        assert (CANARY_DEPLOY / name).is_file(), name


def test_canary_env_declares_isolated_identity():
    text = (CANARY_DEPLOY / "canary.env.example").read_text(encoding="utf-8")
    assert "DEPLOYMENT_ENV=canary" in text
    assert "STRATFORGE_CANARY_DATA_ROOT=" in text
    # Production reference identifiers must be present for the collision guard.
    assert "STRATFORGE_PRODUCTION_DATABASE_ID=" in text
    assert "STRATFORGE_PRODUCTION_TELEGRAM_BOT_ID=" in text


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
