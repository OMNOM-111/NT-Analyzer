from __future__ import annotations

from pathlib import Path

import pytest

from app import runtime_env


_ENV_KEYS = (
    "STRATFORGE_ENV",
    "NTA_APP_ENV",
    "NTA_ENV",
    "STRATFORGE_INSTANCE_ID",
    "STRATFORGE_DEPLOYMENT_ROLE",
    "STRATFORGE_CONFIG_PROFILE",
    "STRATFORGE_BUILD_VERSION",
    "STRATFORGE_REGION",
    "STRATFORGE_BIND_HOST",
    "STRATFORGE_ALLOWED_HOSTS",
    "STRATFORGE_DATA_ROOT",
    "NTA_DATA_ROOT",
    "STRATFORGE_DEVELOPMENT_DATA_ROOT",
    "NTA_STAGING_DATA_ROOT",
    "STRATFORGE_DATABASE_ID",
    "STRATFORGE_QUEUE_ID",
    "STRATFORGE_OBJECT_STORAGE_ID",
    "STRATFORGE_TELEGRAM_BOT_ID",
    "STRATFORGE_COOKIE_NAMESPACE",
    "STRATFORGE_SIGNING_KEY_ID",
    "STRATFORGE_LOG_NAMESPACE",
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
def clean_deployment_environment(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _production_config(monkeypatch, tmp_path: Path) -> None:
    values = {
        "STRATFORGE_ENV": "production",
        "STRATFORGE_INSTANCE_ID": "stratforge-prod-01",
        "STRATFORGE_DEPLOYMENT_ROLE": "all-in-one",
        "STRATFORGE_CONFIG_PROFILE": "production-primary",
        "STRATFORGE_BUILD_VERSION": "2026.07.21-test",
        "STRATFORGE_REGION": "primary",
        "STRATFORGE_BIND_HOST": "127.0.0.1",
        "STRATFORGE_ALLOWED_HOSTS": "app.stratforges.com",
        "STRATFORGE_DATA_ROOT": str(tmp_path / "production"),
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
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_real_startup_rejects_implicit_environment() -> None:
    # Library behavior remains compatible, but the executable entrypoint is
    # fail-closed.
    assert runtime_env.app_env() == "production"
    assert runtime_env.environment_explicit() is False
    with pytest.raises(runtime_env.RuntimeEnvError, match="Окружение не задано"):
        runtime_env.assert_startup_safe()


def test_development_profile_is_explicit_and_isolated(tmp_path, monkeypatch) -> None:
    production = tmp_path / "production"
    development = tmp_path / "development"
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(production))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(development))

    config = runtime_env.assert_startup_safe()

    assert config.environment == "development"
    assert config.runtime_profile == "development"
    assert config.environment_explicit is True
    assert Path(config.data_root) == development.resolve()
    assert config.allowed_hosts == ("127.0.0.1", "localhost")
    assert config.live_trading_allowed is False
    assert config.real_payments_allowed is False
    assert runtime_env.impersonation_enabled() is False


def test_legacy_staging_is_a_development_compatibility_profile(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("NTA_STAGING_DATA_ROOT", str(tmp_path / "staging"))

    config = runtime_env.assert_startup_safe()

    assert runtime_env.app_env() == "staging"
    assert config.environment == "development"
    assert runtime_env.is_staging() is True
    assert runtime_env.impersonation_enabled() is True


def test_environment_aliases_may_agree_but_may_not_conflict(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    assert runtime_env.assert_startup_safe().environment == "development"

    monkeypatch.setenv("NTA_APP_ENV", "production")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Конфликт"):
        runtime_env.app_env()


def test_development_and_production_roots_cannot_collide(
    tmp_path, monkeypatch,
) -> None:
    shared = tmp_path / "shared"
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(shared))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(shared))
    with pytest.raises(runtime_env.RuntimeEnvError, match="совпадает"):
        runtime_env.assert_startup_safe()


def test_production_startup_requires_the_complete_resource_matrix(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("STRATFORGE_ENV", "production")
    with pytest.raises(runtime_env.RuntimeEnvError, match="STRATFORGE_DATA_ROOT"):
        runtime_env.assert_startup_safe()

    _production_config(monkeypatch, tmp_path)
    config = runtime_env.assert_startup_safe()
    assert config.environment == "production"
    assert config.instance_id == "stratforge-prod-01"
    assert config.allowed_hosts == ("app.stratforges.com",)
    assert config.database_id == "postgres-primary"
    assert config.live_trading_allowed is False
    assert config.real_payments_allowed is False


def test_production_startup_rejects_auth_bypass(tmp_path, monkeypatch) -> None:
    _production_config(monkeypatch, tmp_path)
    monkeypatch.setenv("NTA_TEST_BYPASS_AUTH", "1")
    with pytest.raises(runtime_env.RuntimeEnvError, match="NTA_TEST_BYPASS_AUTH"):
        runtime_env.assert_startup_safe()


def test_production_rejects_wildcard_hosts_and_unconfirmed_all_interface_bind(
    tmp_path, monkeypatch,
) -> None:
    _production_config(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_ALLOWED_HOSTS", "*.stratforges.com")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Недопустимый host"):
        runtime_env.assert_startup_safe()

    monkeypatch.setenv("STRATFORGE_ALLOWED_HOSTS", "app.stratforges.com")
    monkeypatch.setenv("STRATFORGE_BIND_HOST", "0.0.0.0")
    with pytest.raises(runtime_env.RuntimeEnvError, match="все интерфейсы"):
        runtime_env.assert_startup_safe()

    monkeypatch.setenv("STRATFORGE_PRIVATE_BIND_CONFIRMED", "1")
    assert runtime_env.assert_startup_safe().bind_host == "0.0.0.0"


def test_production_rejects_conflicting_live_and_payment_flags(
    tmp_path, monkeypatch,
) -> None:
    _production_config(monkeypatch, tmp_path)
    monkeypatch.setenv("NTA_ALLOW_LIVE_ORDERS", "1")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Конфликт"):
        runtime_env.assert_startup_safe()

    monkeypatch.delenv("NTA_ALLOW_LIVE_ORDERS", raising=False)
    monkeypatch.setenv("NTA_ALLOW_REAL_PAYMENTS", "1")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Конфликт"):
        runtime_env.assert_startup_safe()


def test_public_deployment_status_contains_no_paths_or_resource_ids(
    tmp_path, monkeypatch,
) -> None:
    _production_config(monkeypatch, tmp_path)
    runtime_env.assert_startup_safe()
    public = runtime_env.public_status()

    assert public["environment"] == "production"
    assert public["instance_id"] == "stratforge-prod-01"
    assert "data_root" not in public
    assert "database_id" not in public
    assert "signing_key_id" not in public
