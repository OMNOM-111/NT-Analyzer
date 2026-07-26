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
    "STRATFORGE_BUILD_DATE",
    "STRATFORGE_RELEASE_CHANNEL",
    "STRATFORGE_REGION",
    "STRATFORGE_BIND_HOST",
    "STRATFORGE_ALLOWED_HOSTS",
    "STRATFORGE_PUBLIC_ORIGIN",
    "STRATFORGE_EDGE_MODE",
    "STRATFORGE_TRUSTED_PROXY_IPS",
    "STRATFORGE_READINESS_MIN_FREE_MB",
    "STRATFORGE_API_MAX_INFLIGHT",
    "STRATFORGE_API_BACKLOG",
    "STRATFORGE_API_MAX_BODY_BYTES",
    "STRATFORGE_WORKER_POLL_MS",
    "STRATFORGE_WORKER_SHUTDOWN_GRACE_SEC",
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
        "STRATFORGE_BUILD_VERSION": "1.0.0-test",
        "STRATFORGE_BUILD_DATE": "2026-07-21",
        "STRATFORGE_RELEASE_CHANNEL": "stable",
        "STRATFORGE_REGION": "primary",
        "STRATFORGE_BIND_HOST": "127.0.0.1",
        "STRATFORGE_ALLOWED_HOSTS": "app.stratforges.com",
        "STRATFORGE_PUBLIC_ORIGIN": "https://app.stratforges.com",
        "STRATFORGE_EDGE_MODE": "cloudflare-tunnel",
        "STRATFORGE_TRUSTED_PROXY_IPS": "127.0.0.1,::1",
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
    assert config.api_max_inflight == 48
    assert config.api_backlog == 96
    assert config.api_max_body_bytes == 1048576
    assert config.allowed_hosts == ("127.0.0.1", "localhost")
    assert config.public_origin == "http://127.0.0.1"
    assert config.edge_mode == "direct-local"
    assert config.live_trading_allowed is False
    assert config.real_payments_allowed is False
    assert config.build_version == "0.9.0-dev.7"
    assert config.release_channel == "development"
    assert config.release_status == "in_development"
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

    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "nested"))
    monkeypatch.setenv(
        "STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "nested" / "development"),
    )
    with pytest.raises(runtime_env.RuntimeEnvError, match="вложен"):
        runtime_env.assert_startup_safe()


def test_staging_implicit_roots_keep_legacy_data_path_isolated(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NTA_APP_ENV", "staging")

    assert runtime_env.data_root(tmp_path) == (tmp_path / "data" / "staging").resolve()


def test_api_admission_backlog_cannot_be_smaller_than_inflight(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    monkeypatch.setenv("STRATFORGE_API_MAX_INFLIGHT", "32")
    monkeypatch.setenv("STRATFORGE_API_BACKLOG", "16")

    with pytest.raises(runtime_env.RuntimeEnvError, match="API_BACKLOG"):
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
    assert config.public_origin == "https://app.stratforges.com"
    assert config.edge_mode == "cloudflare-tunnel"
    assert config.trusted_proxy_ips == ("127.0.0.1", "::1")
    assert config.readiness_min_free_mb == 4096
    assert config.database_id == "postgres-primary"
    assert config.build_version == "1.0.0-test"
    assert config.build_date == "2026-07-21"
    assert config.release_channel == "stable"
    assert config.release_status == "ready"
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


def test_production_requires_exact_https_canonical_origin(
    tmp_path, monkeypatch,
) -> None:
    _production_config(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_PUBLIC_ORIGIN", "http://app.stratforges.com")
    with pytest.raises(runtime_env.RuntimeEnvError, match="https"):
        runtime_env.assert_startup_safe()

    monkeypatch.setenv("STRATFORGE_PUBLIC_ORIGIN", "https://app.stratforges.com/path")
    with pytest.raises(runtime_env.RuntimeEnvError, match="origin"):
        runtime_env.assert_startup_safe()

    monkeypatch.setenv("STRATFORGE_PUBLIC_ORIGIN", "https://app.stratforges.com")
    monkeypatch.setenv(
        "STRATFORGE_ALLOWED_HOSTS",
        "app.stratforges.com,www.stratforges.com",
    )
    with pytest.raises(runtime_env.RuntimeEnvError, match="canonical host"):
        runtime_env.assert_startup_safe()


def test_production_requires_nonlocal_edge_and_exact_proxy_ips(
    tmp_path, monkeypatch,
) -> None:
    _production_config(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_EDGE_MODE", "direct-local")
    with pytest.raises(runtime_env.RuntimeEnvError, match="direct-local"):
        runtime_env.assert_startup_safe()

    monkeypatch.setenv("STRATFORGE_EDGE_MODE", "cloudflare-tunnel")
    monkeypatch.setenv("STRATFORGE_TRUSTED_PROXY_IPS", "127.0.0.0/8")
    with pytest.raises(runtime_env.RuntimeEnvError, match="точные IP"):
        runtime_env.assert_startup_safe()

    monkeypatch.setenv("STRATFORGE_TRUSTED_PROXY_IPS", "127.0.0.1")
    monkeypatch.setenv("STRATFORGE_READINESS_MIN_FREE_MB", "zero")
    with pytest.raises(runtime_env.RuntimeEnvError, match="целым числом"):
        runtime_env.assert_startup_safe()


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
    assert public["build_version"] == "1.0.0-test"
    assert public["build_date"] == "2026-07-21"
    assert public["release_channel"] == "stable"
    assert "data_root" not in public
    assert "database_id" not in public
    assert "signing_key_id" not in public


def test_release_identity_cannot_mislabel_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "prod"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    monkeypatch.setenv("STRATFORGE_BUILD_VERSION", "1.0.0")
    monkeypatch.setenv("STRATFORGE_BUILD_DATE", "2026-07-21")
    monkeypatch.setenv("STRATFORGE_RELEASE_CHANNEL", "stable")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Development"):
        runtime_env.assert_startup_safe()

    _production_config(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_RELEASE_CHANNEL", "development")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Production"):
        runtime_env.assert_startup_safe()


def test_release_identity_rejects_invalid_semver(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "prod"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    monkeypatch.setenv("STRATFORGE_BUILD_VERSION", "0.9.0-dev.01")
    monkeypatch.setenv("STRATFORGE_BUILD_DATE", "2026-07-21")
    monkeypatch.setenv("STRATFORGE_RELEASE_CHANNEL", "development")
    with pytest.raises(runtime_env.RuntimeEnvError, match="SemVer"):
        runtime_env.assert_startup_safe()


def test_run_mode_launchers_are_unambiguous() -> None:
    root = Path(__file__).resolve().parents[1]
    start = (root / "start.ps1").read_text(encoding="utf-8")
    open_server = (root / "open-server.ps1").read_text(encoding="utf-8")
    guide = (root / "README-RUN-MODES.md").read_text(encoding="utf-8")

    assert (root / "START-DEVELOPMENT.cmd").is_file()
    assert (root / "OPEN-SERVER.cmd").is_file()
    assert not (root / "OPEN-STABLE.cmd").exists()
    assert "$env:STRATFORGE_RELEASE_CHANNEL = 'development'" in start
    assert "VERSION.json channel=development" in start
    assert "/api/runtime/env" in open_server
    assert "this is not the stable release" in open_server
    assert "START-DEVELOPMENT.cmd" in guide
    assert "OPEN-SERVER.cmd" in guide
    assert "РАЗРАБОТКА" in guide and "ПРЕДРЕЛИЗ" in guide and "СТАБИЛЬНАЯ" in guide
