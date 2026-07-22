from __future__ import annotations

from pathlib import Path

from tools import production_preflight


def _environment(root: Path) -> str:
    return "\n".join((
        "STRATFORGE_ENV=production",
        "STRATFORGE_INSTANCE_ID=stratforge-prod-test",
        "STRATFORGE_DEPLOYMENT_ROLE=all-in-one",
        "STRATFORGE_CONFIG_PROFILE=production-primary",
        "STRATFORGE_BUILD_VERSION=1.0.0-test",
        "STRATFORGE_BUILD_DATE=2026-07-21",
        "STRATFORGE_RELEASE_CHANNEL=stable",
        "STRATFORGE_REGION=primary",
        "STRATFORGE_BIND_HOST=127.0.0.1",
        "STRATFORGE_ALLOWED_HOSTS=app.stratforges.com",
        "STRATFORGE_PUBLIC_ORIGIN=https://app.stratforges.com",
        "STRATFORGE_EDGE_MODE=cloudflare-tunnel",
        "STRATFORGE_TRUSTED_PROXY_IPS=127.0.0.1,::1",
        f"STRATFORGE_DATA_ROOT={root}",
        "STRATFORGE_DATABASE_ID=postgres-primary",
        "STRATFORGE_QUEUE_ID=production-jobs",
        "STRATFORGE_OBJECT_STORAGE_ID=production-artifacts",
        "STRATFORGE_TELEGRAM_BOT_ID=production-main",
        "STRATFORGE_COOKIE_NAMESPACE=sf-prod",
        "STRATFORGE_SIGNING_KEY_ID=production-key-v1",
        "STRATFORGE_LOG_NAMESPACE=production",
        "STRATFORGE_LIVE_TRADING_ALLOWED=0",
        "STRATFORGE_REAL_PAYMENTS_ALLOWED=0",
    )) + "\n"


def _clear_legacy_flags(monkeypatch) -> None:
    for key in (
        "NTA_APP_ENV",
        "NTA_ENV",
        "NTA_TEST_BYPASS_AUTH",
        "NTA_ENABLE_TEST_AUTH",
        "NTA_ENABLE_IMPERSONATION",
        "NTA_DISABLE_RATE_LIMIT",
        "NTA_ALLOW_LIVE_ORDERS",
        "NTA_ALLOW_REAL_PAYMENTS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_preflight_passes_a_complete_isolated_layout(tmp_path: Path, monkeypatch) -> None:
    _clear_legacy_flags(monkeypatch)
    app_root = tmp_path / "release"
    (app_root / "app").mkdir(parents=True)
    (app_root / "app" / "server.py").write_text("", encoding="utf-8")
    (app_root / "requirements.txt").write_text("", encoding="utf-8")
    data_root = tmp_path / "state"
    data_root.mkdir()
    env_file = tmp_path / "production.env"
    env_file.write_text(_environment(data_root), encoding="utf-8")

    result = production_preflight.run_preflight(
        app_root=app_root,
        environment_file=env_file,
        allow_non_linux=True,
        require_binaries=(),
    )

    assert result["ok"] is True
    assert all(item["ok"] for item in result["checks"])


def test_preflight_rejects_data_inside_release_and_bad_config(tmp_path: Path, monkeypatch) -> None:
    _clear_legacy_flags(monkeypatch)
    app_root = tmp_path / "release"
    (app_root / "app").mkdir(parents=True)
    (app_root / "app" / "server.py").write_text("", encoding="utf-8")
    (app_root / "requirements.txt").write_text("", encoding="utf-8")
    data_root = app_root / "data"
    data_root.mkdir()
    env_file = tmp_path / "production.env"
    env_file.write_text(_environment(data_root), encoding="utf-8")

    result = production_preflight.run_preflight(
        app_root=app_root,
        environment_file=env_file,
        allow_non_linux=True,
        require_binaries=(),
    )
    assert result["ok"] is False
    assert any(
        item["name"] == "release_data_separation" and not item["ok"]
        for item in result["checks"]
    )

    env_file.write_text("not-an-assignment\n", encoding="utf-8")
    invalid = production_preflight.run_preflight(
        app_root=app_root,
        environment_file=env_file,
        allow_non_linux=True,
        require_binaries=(),
    )
    assert invalid["ok"] is False
    assert invalid["checks"][0]["code"] == "invalid"


def test_deployment_templates_keep_secrets_out_and_routes_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    env_template = (root / "deploy" / "production" / "production.env.example").read_text(encoding="utf-8")
    tunnel = (root / "deploy" / "production" / "cloudflared.yml.example").read_text(encoding="utf-8")
    unit = (root / "deploy" / "production" / "stratforge.service").read_text(encoding="utf-8")

    assert "app.stratforges.com" in env_template
    assert "STRATFORGE_LIVE_TRADING_ALLOWED=0" in env_template
    assert "token=" not in env_template.lower()
    assert "password=" not in env_template.lower()
    assert "127.0.0.1:18765" in tunnel
    assert tunnel.rstrip().endswith("service: http_status:404")
    assert "0.0.0.0" not in tunnel
    assert "EnvironmentFile=%h/.config/stratforge/production.env" in unit
    assert "Restart=on-failure" in unit
