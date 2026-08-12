from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import runtime_env


_ENV_KEYS = (
    "DEPLOYMENT_ENV",
    "STRATFORGE_ENV",
    "NTA_APP_ENV",
    "NTA_ENV",
    "STRATFORGE_INSTANCE_ID",
    "STRATFORGE_DEPLOYMENT_ROLE",
    "STRATFORGE_CONFIG_PROFILE",
    "APP_VERSION",
    "STRATFORGE_BUILD_VERSION",
    "STRATFORGE_BUILD_DATE",
    "BUILD_TIMESTAMP_UTC",
    "STRATFORGE_BUILD_TIMESTAMP_UTC",
    "RELEASE_CHANNEL",
    "STRATFORGE_RELEASE_CHANNEL",
    "BUILD_ID",
    "STRATFORGE_BUILD_ID",
    "GIT_COMMIT_SHA",
    "STRATFORGE_GIT_COMMIT_SHA",
    "ARTIFACT_SHA256",
    "STRATFORGE_ARTIFACT_SHA256",
    "DIRTY",
    "STRATFORGE_BUILD_DIRTY",
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
    "STRATFORGE_CANARY_DATA_ROOT",
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
        "DEPLOYMENT_ENV": "production",
        "STRATFORGE_INSTANCE_ID": "stratforge-prod-01",
        "STRATFORGE_DEPLOYMENT_ROLE": "all-in-one",
        "STRATFORGE_CONFIG_PROFILE": "production-primary",
        "APP_VERSION": "1.0.0-test",
        "BUILD_TIMESTAMP_UTC": "2026-07-21T12:34:56Z",
        "RELEASE_CHANNEL": "stable",
        "BUILD_ID": "sf-1.0.0-test-20260721",
        "GIT_COMMIT_SHA": "a" * 40,
        "ARTIFACT_SHA256": "B" * 64,
        "DIRTY": "0",
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


def _canary_config(monkeypatch, tmp_path: Path) -> None:
    _production_config(monkeypatch, tmp_path)
    values = {
        "DEPLOYMENT_ENV": "canary",
        "STRATFORGE_INSTANCE_ID": "stratforge-canary-01",
        "STRATFORGE_CONFIG_PROFILE": "canary-primary",
        "RELEASE_CHANNEL": "beta",
        "STRATFORGE_ALLOWED_HOSTS": "canary.stratforges.com",
        "STRATFORGE_PUBLIC_ORIGIN": "https://canary.stratforges.com",
        "STRATFORGE_CANARY_DATA_ROOT": str(tmp_path / "canary"),
        "STRATFORGE_DATABASE_ID": "postgres-canary",
        "STRATFORGE_QUEUE_ID": "canary-jobs",
        "STRATFORGE_OBJECT_STORAGE_ID": "canary-artifacts",
        "STRATFORGE_TELEGRAM_BOT_ID": "canary-main",
        "STRATFORGE_COOKIE_NAMESPACE": "sf-canary",
        "STRATFORGE_SIGNING_KEY_ID": "canary-key-v1",
        "STRATFORGE_LOG_NAMESPACE": "canary",
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
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
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
    assert config.build_version == "0.10.0-beta.1"
    assert config.release_channel == "dev"
    assert config.release_status == "in_development"
    assert len(config.git_commit_sha) == 40
    assert config.build_id.startswith("dev-0.10.0-beta.1-")
    assert config.build_timestamp_utc == "2026-08-11T18:35:00Z"
    assert config.artifact_sha256 == ""
    assert runtime_env.impersonation_enabled() is True
    status = runtime_env.status()
    assert status["deployment_environment"] == "development"
    assert status["app_version"] == "0.10.0-beta.1"
    assert status["release_channel"] == "dev"
    assert status["build_id"] == config.build_id
    assert status["git_commit_sha"] == config.git_commit_sha
    assert status["dirty"] is config.dirty
    assert status["deployment"]["app_version"] == "0.10.0-beta.1"


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
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
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
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
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


def test_development_honors_launcher_dirty_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    monkeypatch.setenv("DIRTY", "0")

    assert runtime_env.assert_startup_safe().dirty is False


def test_local_git_state_uses_utf8_replacement_and_tolerates_empty_stdout(
    monkeypatch,
) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[1:] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(stdout="a" * 40)
        return SimpleNamespace(stdout=None)

    monkeypatch.setattr(runtime_env.subprocess, "run", fake_run)
    runtime_env._local_git_state.cache_clear()
    try:
        assert runtime_env._local_git_state() == ("a" * 40, False)
    finally:
        runtime_env._local_git_state.cache_clear()

    assert len(calls) == 2
    assert all(kwargs["encoding"] == "utf-8" for _, kwargs in calls)
    assert all(kwargs["errors"] == "replace" for _, kwargs in calls)


def test_api_admission_backlog_cannot_be_smaller_than_inflight(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    monkeypatch.setenv("STRATFORGE_API_MAX_INFLIGHT", "32")
    monkeypatch.setenv("STRATFORGE_API_BACKLOG", "16")

    with pytest.raises(runtime_env.RuntimeEnvError, match="API_BACKLOG"):
        runtime_env.assert_startup_safe()


def test_production_startup_requires_the_complete_resource_matrix(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
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
    assert config.build_timestamp_utc == "2026-07-21T12:34:56Z"
    assert config.build_id == "sf-1.0.0-test-20260721"
    assert config.git_commit_sha == "a" * 40
    assert config.artifact_sha256 == "B" * 64
    assert config.dirty is False
    assert config.release_channel == "stable"
    assert config.release_status == "ready"
    assert config.live_trading_allowed is False
    assert config.real_payments_allowed is False


def test_canary_is_a_distinct_clean_remote_environment(tmp_path, monkeypatch) -> None:
    _canary_config(monkeypatch, tmp_path)

    config = runtime_env.assert_startup_safe()
    public = runtime_env.public_status()

    assert runtime_env.is_canary() is True
    assert runtime_env.is_development() is False
    assert runtime_env.is_production() is False
    assert config.environment == "canary"
    assert config.release_channel == "beta"
    assert Path(config.data_root) == (tmp_path / "canary").resolve()
    assert config.database_id == "postgres-canary"
    assert config.readiness_min_free_mb == 4096
    assert config.api_backlog == 128
    assert config.live_trading_allowed is False
    assert config.real_payments_allowed is False
    assert runtime_env.allow_owner_telegram_mirror() is False
    assert public["deployment_environment"] == "canary"


def test_canary_cannot_share_production_root_or_run_dirty(
    tmp_path, monkeypatch,
) -> None:
    _canary_config(monkeypatch, tmp_path)
    monkeypatch.setenv("STRATFORGE_CANARY_DATA_ROOT", str(tmp_path / "production"))
    with pytest.raises(runtime_env.RuntimeEnvError, match="совпадает"):
        runtime_env.assert_startup_safe()

    monkeypatch.setenv("STRATFORGE_CANARY_DATA_ROOT", str(tmp_path / "canary"))
    monkeypatch.setenv("DIRTY", "1")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Dirty build"):
        runtime_env.assert_startup_safe()


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
    assert public["app_version"] == "1.0.0-test"
    assert public["deployment_environment"] == "production"
    assert public["build_id"] == "sf-1.0.0-test-20260721"
    assert public["git_commit_sha"] == "a" * 40
    assert public["artifact_sha256"] == "B" * 64
    assert public["dirty"] is False
    assert public["release_channel"] == "stable"
    assert "data_root" not in public
    assert "database_id" not in public
    assert "signing_key_id" not in public


def test_release_identity_cannot_mislabel_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "prod"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    monkeypatch.setenv("APP_VERSION", "1.0.0")
    monkeypatch.setenv("BUILD_TIMESTAMP_UTC", "2026-07-21T00:00:00Z")
    monkeypatch.setenv("RELEASE_CHANNEL", "stable")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Development"):
        runtime_env.assert_startup_safe()

    _production_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RELEASE_CHANNEL", "dev")
    with pytest.raises(runtime_env.RuntimeEnvError, match="Canary/Production"):
        runtime_env.assert_startup_safe()


def test_release_identity_rejects_invalid_semver(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "prod"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "dev"))
    monkeypatch.setenv("APP_VERSION", "0.9.0-dev.01")
    monkeypatch.setenv("BUILD_TIMESTAMP_UTC", "2026-07-21T00:00:00Z")
    monkeypatch.setenv("RELEASE_CHANNEL", "dev")
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
    assert "$env:DEPLOYMENT_ENV = 'development'" in start
    assert "$env:RELEASE_CHANNEL = 'dev'" in start
    assert "next release candidate" in start
    assert "the local launcher requires VERSION.json channel=dev" not in start
    assert "$buildTimestampValue -is [DateTime]" in start
    assert "yyyy-MM-ddTHH:mm:ssZ" in start
    assert "InvariantCulture" in start
    assert "/api/runtime/env" in open_server
    assert "this is not the stable release" in open_server
    assert "START-DEVELOPMENT.cmd" in guide
    assert "OPEN-SERVER.cmd" in guide
    assert "`DEV`" in guide and "`CANARY`" in guide and "`BETA`" in guide
    assert "`STABLE` пользователю не показывается" in guide
