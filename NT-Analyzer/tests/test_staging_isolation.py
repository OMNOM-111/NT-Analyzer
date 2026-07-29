from __future__ import annotations

import json
from pathlib import Path

from app import (
    account_auth, admin_journal, community, demo_backtest, durable, google_auth,
    governance, in_app_notifications, integrations, jobqueue, local_secrets,
    marginrefresh, market_data, market_events, market_news, ops, portfolio_registry,
    practice_trading, runtime, runtime_env, strategy_recovery, tunnel_manager,
    secure_store, subscriptions, telegram_remote, telegram_service, user_support,
    vitek, workspaces,
)
from app.ai_lab import agent_tts, ai_ratings, compile_errors, compile_pipeline, paths


def _resolved(paths):
    return {name: Path(path).resolve() for name, path in paths.items()}


def test_all_mutable_core_paths_switch_to_staging_root(tmp_path, monkeypatch) -> None:
    production = (tmp_path / "production-data").resolve()
    staging = (tmp_path / "staging-data").resolve()
    monkeypatch.setenv("NTA_DATA_ROOT", str(production))
    monkeypatch.setenv("NTA_STAGING_DATA_ROOT", str(staging))
    monkeypatch.delenv("NT_ANALYZER_SQLITE_PATH", raising=False)

    def capture() -> dict[str, Path]:
        return _resolved({
            "accounts": account_auth._store_path(),
            "account_audit": account_auth._audit_path(),
            "entitlements": subscriptions._store_path(),
            "google": google_auth._secrets_path(),
            "remote": telegram_remote._access_path(),
            "workspace": workspaces._store_path(),
            "tenant": workspaces._tenant_root("ws_test0000"),
            "telegram_settings": telegram_service._settings_path(),
            "telegram_state": telegram_service._state_path(),
            "community": community._store_path(),
            "practice": practice_trading._store_path(),
            "demo": demo_backtest._quota_path(),
            "notifications": in_app_notifications._path(),
            "support": user_support._store_path(),
            "journal": admin_journal._audit_dir(),
            "secrets": local_secrets.secrets_path(),
            "agent_keys": secure_store.store_path(),
            "durable": durable.db_path(Path(__file__).resolve().parents[1]),
            "jobs": jobqueue.jobs_dir(),
            "catalog": jobqueue.catalog_dir(),
            "runtime": runtime.runtime_dir(),
            "ops": ops._ops_dir(),
            "ratings": ai_ratings._store_path(),
            "portfolio": portfolio_registry._registry_path(),
            "market_runtime": market_data._runtime_dir(),
            "market_calendar": market_events._news_path(),
            "market_news": market_news._live_news_path(),
            "tunnel": tunnel_manager._state_path(),
            "vitek_state": vitek._state_path(),
            "vitek_marker": vitek._service_marker_path(),
            "vitek_events": vitek._bridge_event_path(),
            "tts_voices": agent_tts.voices_store_path(),
            "tts_cache": agent_tts.cache_dir(),
            "compile_errors": compile_errors._runtime_dir(),
            "compile_commands": compile_pipeline._commands_dir(),
            "strategy_recovery_audit": strategy_recovery._audit_path("probe"),
            "ai_nt_custom": paths.nt_custom_dir(),
            "governance_data": governance.data_dir(),
            "governance_docs": governance.docs_dir(),
            "margins": marginrefresh.margins_json_path(),
        })

    monkeypatch.setenv("NTA_APP_ENV", "production")
    prod_paths = capture()
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    stage_paths = capture()

    assert set(prod_paths) == set(stage_paths)
    for name, prod_path in prod_paths.items():
        assert prod_path == production or production in prod_path.parents, (name, prod_path)
    for name, stage_path in stage_paths.items():
        assert stage_path != prod_paths[name], name
        assert stage_path == staging or staging in stage_path.parents, (name, stage_path)
        assert production not in stage_path.parents, (name, stage_path)

    assert integrations._root().is_dir()  # code root remains code; only data paths move
    assert runtime_env.allow_real_payments() is False
    assert runtime_env.allow_live_orders() is False
    assert runtime_env.impersonation_enabled() is True


def test_staging_cannot_restore_sources_into_ninjatrader(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("NTA_STAGING_DATA_ROOT", str(tmp_path / "staging"))
    try:
        strategy_recovery.begin({}, {}, task_id="staging-probe")
    except strategy_recovery.StrategyRecoveryError as exc:
        assert "запрещено" in str(exc)
    else:  # pragma: no cover - safety regression
        raise AssertionError("staging was allowed to restore NinjaTrader sources")


def test_explicit_production_cannot_restore_sources_into_ninjatrader(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("STRATFORGE_ENV", "production")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production"))
    try:
        strategy_recovery.begin({}, {}, task_id="production-probe")
    except strategy_recovery.StrategyRecoveryError as exc:
        assert "запрещено" in str(exc)
    else:  # pragma: no cover - safety regression
        raise AssertionError("production was allowed to restore NinjaTrader sources")


def test_clean_staging_reads_safe_catalog_baseline_but_writes_copy_on_write(
    tmp_path, monkeypatch,
) -> None:
    baseline_catalog = tmp_path / "data" / "catalog" / "strategies.json"
    baseline_profiles = tmp_path / "data" / "profiles" / "strategies.json"
    baseline_catalog.parent.mkdir(parents=True, exist_ok=True)
    baseline_profiles.parent.mkdir(parents=True, exist_ok=True)
    baseline_catalog.write_text(
        json.dumps({"strategies": [{"class_name": "BaselineStrategy"}]}),
        encoding="utf-8",
    )
    original_profiles = {"schema_version": "1.1", "profiles": [{"profile_id": "baseline"}]}
    baseline_profiles.write_text(json.dumps(original_profiles), encoding="utf-8")
    staging = tmp_path / "staging"
    monkeypatch.setattr(jobqueue, "project_root", lambda: tmp_path)
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("NTA_STAGING_DATA_ROOT", str(staging))

    assert jobqueue.read_strategies_catalog()["strategies"][0]["class_name"] == "BaselineStrategy"
    assert jobqueue.read_strategy_profiles()["profiles"][0]["profile_id"] == "baseline"
    copied = jobqueue._read_strategy_profiles_raw()
    copied["profiles"].append({"profile_id": "staging-only"})
    jobqueue._write_json_atomic(jobqueue._strategy_profiles_path(), copied)

    assert json.loads(baseline_profiles.read_text(encoding="utf-8")) == original_profiles
    staging_profiles = staging / "profiles" / "strategies.json"
    assert staging_profiles.is_file()
    assert len(json.loads(staging_profiles.read_text(encoding="utf-8"))["profiles"]) == 2


def test_staging_root_collision_and_production_danger_flags_fail_closed(
    tmp_path, monkeypatch,
) -> None:
    shared = (tmp_path / "shared").resolve()
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_DATA_ROOT", str(shared))
    monkeypatch.setenv("NTA_STAGING_DATA_ROOT", str(shared))
    try:
        runtime_env.assert_production_safe()
    except runtime_env.RuntimeEnvError:
        pass
    else:  # pragma: no cover - safety regression
        raise AssertionError("staging/production data-root collision was accepted")

    monkeypatch.setenv("NTA_APP_ENV", "production")
    monkeypatch.setenv("NTA_ENABLE_IMPERSONATION", "1")
    try:
        runtime_env.assert_production_safe()
    except runtime_env.RuntimeEnvError:
        pass
    else:  # pragma: no cover - safety regression
        raise AssertionError("production impersonation flag was accepted")
