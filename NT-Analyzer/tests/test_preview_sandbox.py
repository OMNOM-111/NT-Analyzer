"""System contracts for the isolated, mutable owner Preview sandbox."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import (
    account_auth,
    dev_preview,
    preview_sandbox,
    runtime_env,
    security_devices,
    workspaces,
)


@pytest.fixture()
def preview_env(tmp_path, monkeypatch):
    preview_id = "a1b2c3d4e5f60718293a4b5c"
    base = tmp_path / "stratforge-preview-sandboxes"
    root = base / "parent" / preview_id / "data"
    root.mkdir(parents=True)
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "1")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", preview_id)
    monkeypatch.setenv("STRATFORGE_PREVIEW_SCENARIO", "new_user")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ENTRY_TOKEN", "e" * 64)
    monkeypatch.setenv("STRATFORGE_PREVIEW_CONTROL_TOKEN", "c" * 64)
    monkeypatch.setenv("STRATFORGE_PREVIEW_PARENT_ORIGIN", "http://127.0.0.1:8877")
    monkeypatch.setenv("STRATFORGE_PREVIEW_BASE_ROOT", str(base))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(root))
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda value: value)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda value: value)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    runtime_env._data_root_cached.cache_clear()
    # app.ai_lab.paths freezes its directories at import time. Inside the real
    # Preview child the environment is set before that import; the test process
    # imports first, so point the same constants at this sandbox instead of the
    # repository's own ai_lab tree.
    from app.ai_lab import paths as ai_lab_paths

    mutable = root / "ai_lab"
    monkeypatch.setattr(ai_lab_paths, "MUTABLE_AI_LAB_DIR", mutable)
    # Every path the module exposes, including the ones ``ensure_dirs`` touches:
    # a partially redirected module still creates files in the repository tree.
    for name, relative in (
        ("AI_LAB_DIR", ""),
        ("REGISTRY_DIR", "registry"),
        ("EXPERIMENTS_DIR", "registry/experiments"),
        ("POSTMORTEMS_DIR", "registry/strategy_postmortems"),
        ("KNOWLEDGE_CARDS_DIR", "registry/knowledge_cards"),
        ("RUNS_DIR", "registry/runs"),
        ("PROMPTS_LOG_DIR", "registry/prompts_log"),
        ("ACTIVITY_DIR", "registry/activity"),
        ("USER_RESEARCH_DIR", "user_research"),
        ("PROMPTS_DIR", "prompts"),
        ("SCHEMAS_DIR", "schemas"),
        ("REFERENCE_STRATEGIES_DIR", "reference_strategies"),
        ("MIRRORS_DIR", "mirrors"),
        ("SOURCE_SNAPSHOTS_DIR", "mirrors/source_snapshots"),
        ("QUARANTINE_DIR", "quarantine/compile_failed"),
        ("INDEX_PATH", "registry/index.json"),
        ("MODEL_BENCHMARK_PATH", "registry/model_benchmark_latest.json"),
        ("ERROR_LOG_PATH", "registry/error_log.jsonl"),
        ("ERROR_PATTERNS_PATH", "registry/error_patterns.json"),
        ("LESSON_LOG_PATH", "registry/lesson_log.jsonl"),
        ("REJECTED_HYPOTHESES_PATH", "registry/rejected_hypotheses.jsonl"),
        ("DEMO_MISMATCH_PATH", "registry/demo_mismatch_registry.jsonl"),
        ("COMPILE_FAIL_PATH", "registry/compile_fail_registry.jsonl"),
        ("INFRA_FAIL_PATH", "registry/infra_fail_registry.jsonl"),
    ):
        target = mutable.joinpath(*relative.split("/")) if relative else mutable
        monkeypatch.setattr(ai_lab_paths, name, target)
    account_auth._clear_doc_cache()
    security_devices._CHALLENGE_RATE.clear()
    preview_sandbox._ENTRY_CONSUMED = False
    preview_sandbox._STATE.clear()
    preview_sandbox._STATE.update({
        "scenario": "",
        "generation": 1,
        "current_user_id": 0,
        "current_user_uuid": "",
        "current_session_id": "",
        "dataset_ready": False,
        "dataset_errors": [],
    })
    yield {"id": preview_id, "base": base, "root": root}
    account_auth._clear_doc_cache()
    runtime_env._data_root_cached.cache_clear()


def test_preview_runtime_identity_and_cookie_names_are_isolated(preview_env):
    assert runtime_env.preview_sandbox_enabled() is True
    assert runtime_env.data_root() == preview_env["root"].resolve()
    assert runtime_env.session_cookie_name() == f"sf_preview_{preview_env['id']}_session"
    assert runtime_env.local_storage_namespace() == f"preview-{preview_env['id']}"
    public = runtime_env.public_status()["preview_sandbox"]
    assert public == {
        "enabled": True,
        "id": preview_env["id"],
        "scenario": "new_user",
        "label": "PREVIEW / TEST USER",
        "synthetic": True,
        "external_side_effects": "blocked",
    }


def test_full_product_preview_access_requires_current_non_owner_synthetic_identity(preview_env):
    matching = {
        "is_owner": False,
        "user": {
            "is_owner": False,
            "is_preview_user": True,
            "preview_sandbox_id": preview_env["id"],
        },
    }
    assert preview_sandbox.synthetic_product_access_allowed(matching) is True
    assert preview_sandbox.synthetic_product_access_allowed({
        **matching, "is_owner": True,
    }) is False
    assert preview_sandbox.synthetic_product_access_allowed({
        **matching,
        "user": {**matching["user"], "preview_sandbox_id": "f" * 24},
    }) is False


@pytest.mark.parametrize("environment", ["canary", "production"])
def test_preview_flag_fails_closed_outside_development(preview_env, monkeypatch, environment):
    monkeypatch.setenv("DEPLOYMENT_ENV", environment)
    assert runtime_env.preview_sandbox_enabled() is False
    with pytest.raises(runtime_env.RuntimeEnvError):
        runtime_env.assert_production_safe()


def test_entry_token_is_single_use_and_control_token_is_constant_time_checked(preview_env):
    preview_sandbox.consume_entry_token("e" * 64)
    with pytest.raises(preview_sandbox.PreviewSandboxError) as reused:
        preview_sandbox.consume_entry_token("e" * 64)
    assert reused.value.code == "preview_entry_used"
    assert preview_sandbox.control_authorized("c" * 64) is True
    assert preview_sandbox.control_authorized("x" * 64) is False


def test_new_user_uses_real_registration_then_real_pending_device_gate(preview_env):
    opened = preview_sandbox.activate_scenario(
        "new_user", device_credential="preview-browser-credential",
    )
    assert opened["authenticated"] is False

    started = account_auth.start_email_auth(
        "preview.person@sandbox.stratforge.local",
        ip="127.0.0.1", user_agent="Preview Browser",
    )
    assert started["delivery"] == "preview_synthetic"
    verified = account_auth.verify_email_auth(
        started["challenge_id"],
        code=started["test_code"],
        profile={"first_name": "Preview", "last_name": "Person", "accept_terms": True},
        ip="127.0.0.1", user_agent="Preview Browser",
        device_credential="preview-browser-credential",
    )
    preview_sandbox.after_public_auth(verified)
    context = account_auth.authenticate_session(verified["session_token"])
    assert context["device_access"]["required"] is True
    assert context["device_confirmation_state"] == "pending"
    assert context["user"]["is_preview_user"] is True
    assert context["user"]["is_owner"] is False
    assert not any(user.get("is_owner") for user in account_auth._read_doc()["users"])
    state = preview_sandbox.status()["state"]
    assert state["dataset_ready"] is True
    assert state["dataset_errors"] == []
    assert (preview_env["root"] / "preview-manifest.json").is_file()


def test_seeded_scenarios_cover_session_permanent_and_new_client(preview_env):
    expected = {
        "active_user": (False, "active", "session"),
        "trusted_device": (False, "active", "permanent"),
        "pending_access": (True, "pending", ""),
    }
    for scenario, wanted in expected.items():
        result = preview_sandbox.reset(
            scenario, device_credential=f"preview-browser-{scenario}",
        )
        context = account_auth.authenticate_session(result["session_token"])
        assert (
            bool(context["device_access"]["required"]),
            context["device_access"]["state"],
            context["device_access"]["trust_mode"],
        ) == wanted
        assert context["user"]["is_preview_user"] is True
        assert all(context["user"]["features"].values())
        assert preview_sandbox.status()["state"]["dataset_errors"] == []


def test_security_seed_groups_only_proven_clients_with_physical_machine(preview_env):
    result = preview_sandbox.activate_scenario(
        "trusted_device", device_credential="preview-browser-trusted",
    )
    context = account_auth.authenticate_session(result["session_token"])
    catalog = security_devices.account_security(
        context["user_id"], current_session_id=context["session_id"],
    )
    assert len(catalog["machines"]) == 1
    grouped = catalog["machines"][0]["clients"]
    assert {client["bound_via"] for client in grouped} == {
        "connector_self", "attested_pairing",
    }
    assert len(catalog["standalone_clients"]) >= 2
    assert all(not client["physical_device_id"] for client in catalog["standalone_clients"])
    assert catalog["grouping_policy"]["ip_or_user_agent_is_identity"] is False


def test_external_effects_are_blocked_but_local_product_mutations_remain(preview_env):
    for method, path in (
        ("POST", "/api/telegram/webhook"),
        ("POST", "/api/connector/v1/hello"),
        ("POST", "/api/billing/paypal/webhook"),
        ("POST", "/api/admin/releases/deliver-canary"),
        ("POST", "/api/ai-lab/cloud/run"),
    ):
        assert preview_sandbox.external_side_effect_blocked(method, path) is True
    assert preview_sandbox.external_side_effect_blocked("GET", "/api/account/security") is False
    assert preview_sandbox.external_side_effect_blocked("POST", "/api/practice/order") is False


def test_child_environment_drops_parent_credentials_and_uses_unique_root(preview_env, monkeypatch):
    monkeypatch.setenv("TOPSTEP_API_TOKEN", "real-token-must-not-cross")
    monkeypatch.setenv("DATABASE_URL", "postgresql://real")
    child_root = preview_env["base"] / "parent" / "feedfacecafebeef12345678" / "data"
    env = dev_preview._sandbox_environment(
        preview_id="feedfacecafebeef12345678",
        scenario="pending_access",
        parent_origin="http://127.0.0.1:8877",
        root=child_root,
        base=preview_env["base"],
        entry_token="a" * 64,
        control_token="b" * 64,
        port=45678,
    )
    assert "TOPSTEP_API_TOKEN" not in env
    assert "DATABASE_URL" not in env
    assert env["NTA_TELEGRAM_BOT_TOKEN"] == ""
    assert env["NTA_RESEND_API_KEY"] == ""
    assert Path(env["STRATFORGE_DEVELOPMENT_DATA_ROOT"]) == child_root
    assert env["STRATFORGE_PREVIEW_SANDBOX"] == "1"


def test_owner_preview_status_advertises_isolated_scenarios(preview_env):
    account_auth._write_doc({
        "version": 3,
        "users": [{
            "user_id": 999,
            "user_uuid": "00000000-0000-4000-8000-000000000999",
            "first_name": "Owner",
            "role": "owner",
            "status": "active",
            "is_owner": True,
        }],
        "sessions": [],
        "challenges": [],
    })
    status = dev_preview.status(999)
    assert status["architecture"] == "isolated_process"
    assert {row["id"] for row in status["sandbox_scenarios"]} == {
        "new_user", "active_user", "trusted_device", "pending_access",
    }
    assert status["active_sandbox"] == {"running": False}


def test_reset_does_not_accept_a_root_outside_the_preview_base(preview_env, monkeypatch):
    outside = preview_env["base"].parent / "real-owner-data"
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(outside))
    runtime_env._data_root_cached.cache_clear()
    with pytest.raises(preview_sandbox.PreviewSandboxError) as unsafe:
        preview_sandbox.isolated_root()
    assert unsafe.value.code == "preview_root_not_isolated"


def test_mode_entry_keeps_preview_identity_and_controls_visible():
    root = Path(__file__).resolve().parents[1]
    script = (root / "app" / "static" / "aurora" / "assets" / "pages" / "mode-entry.js").read_text(encoding="utf-8")
    assert "PREVIEW / TEST USER" in script
    assert "previewSandboxReset" in script
    assert "previewSandboxNewUser" in script
    assert "previewSandboxSimulateClient" in script
    assert "previewSandboxExit" in script


def test_preview_dataset_fills_runtime_research_and_calendar_surfaces(preview_env):
    """Every product page the owner opens must have something real to show."""
    result = preview_sandbox.activate_scenario(
        "trusted_device", device_credential="preview-browser-dataset",
    )
    assert preview_sandbox.status()["state"]["dataset_errors"] == []
    context = account_auth.authenticate_session(result["session_token"])
    workspace = workspaces.ensure_personal_workspace(
        context["user_id"],
        display_name="Preview Personal Workspace",
        require_entitlement=False,
    )
    runtime_dirs = preview_sandbox._runtime_dirs(workspace)
    # The workspace bridge store and the process-global runtime store are two
    # different readers (Trading Online vs Финансы/Обзор); both must be seeded.
    assert len(runtime_dirs) >= 2
    assert Path(runtime_env.data_path("runtime")).resolve() in {
        path.resolve() for path in runtime_dirs
    }
    for runtime_dir in runtime_dirs:
        assert (runtime_dir / "heartbeat.json").is_file()
        assert (runtime_dir / "accounts.json").is_file()
        assert (runtime_dir / "executions.jsonl").read_text(encoding="utf-8").strip()
    from app.ai_lab import paths as ai_lab_paths

    catalog_path = ai_lab_paths.REGISTRY_DIR / "research_catalog.json"
    researches = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert researches.get("researches"), "AI Lab must not open on an empty catalog"
    assert (runtime_env.data_path("integrations", "news.json")).is_file()


def test_runtime_heartbeat_clock_keeps_the_synthetic_bridge_fresh(preview_env):
    from app import runtime as ops_runtime

    preview_sandbox.activate_scenario(
        "trusted_device", device_credential="preview-browser-clock",
    )
    runtime_dir = Path(runtime_env.data_path("runtime"))
    stale = json.loads((runtime_dir / "heartbeat.json").read_text(encoding="utf-8"))
    stale["timestamp_utc"] = "2020-01-01T00:00:00Z"
    (runtime_dir / "heartbeat.json").write_text(
        json.dumps(stale, ensure_ascii=False), encoding="utf-8",
    )
    preview_sandbox._touch_runtime_heartbeat([runtime_dir])
    with ops_runtime.runtime_dir_override(str(runtime_dir)):
        heartbeat = ops_runtime.read_heartbeat()
    assert heartbeat["present"] is True
    assert heartbeat["fresh"] is True


def test_reset_parks_the_runtime_clock_before_wiping_the_root(preview_env):
    preview_sandbox.activate_scenario(
        "trusted_device", device_credential="preview-browser-reset-clock",
    )
    assert preview_sandbox._RUNTIME_CLOCK_DIRS
    preview_sandbox._wipe_isolated_root()
    assert preview_sandbox._RUNTIME_CLOCK_DIRS == []


def test_seeding_refuses_a_target_outside_the_isolated_root(preview_env, monkeypatch, tmp_path):
    """A module whose paths were frozen before Preview started must not be written."""
    from app.ai_lab import paths as ai_lab_paths

    outside = tmp_path / "repository-ai-lab" / "registry"
    monkeypatch.setattr(ai_lab_paths, "REGISTRY_DIR", outside)
    with pytest.raises(preview_sandbox.PreviewSandboxError) as blocked:
        preview_sandbox._seed_ai_lab_research()
    assert blocked.value.code == "preview_target_not_isolated"
    assert not outside.exists()

    result = preview_sandbox.activate_scenario(
        "trusted_device", device_credential="preview-browser-guard",
    )
    assert result["authenticated"] is True
    errors = preview_sandbox.status()["state"]["dataset_errors"]
    assert any(row.startswith("ai_lab_research:") for row in errors)
    assert any(row.startswith("chat:") for row in errors)
    assert not outside.exists()


def test_preview_logout_cannot_sign_the_owner_out_of_the_real_contour(preview_env):
    """Cookies are not port-scoped: the sandbox needs its own logout marker."""
    from app import server

    handler = object.__new__(server.Handler)
    assert handler._dev_preview_mode_cookie_name() == (
        f"sf_preview_{preview_env['id']}_dev_preview_mode"
    )
    assert handler._dev_preview_mode_cookie_name() != server._DEV_PREVIEW_MODE_COOKIE

    handler._extra_headers = []
    handler._hold_local_logout()
    assert handler._extra_headers, "Preview logout must still record its own marker"
    assert all(
        server._DEV_PREVIEW_MODE_COOKIE + "=" not in value
        for _name, value in handler._extra_headers
    )
    # The parent Development contour keeps the shared name, so its own owner
    # bypass is unaffected by anything the sandbox writes.
    handler._cookie_value = lambda name: (
        "unauthenticated" if name == server._DEV_PREVIEW_MODE_COOKIE else ""
    )
    assert handler._dev_preview_mode_cookie_name() not in {server._DEV_PREVIEW_MODE_COOKIE}


def test_scenario_users_carry_a_stratforge_handle(preview_env):
    """A scenario member must look like a registered one in Social and Chat."""
    result = preview_sandbox.activate_scenario(
        "trusted_device", device_credential="preview-browser-handle",
    )
    context = account_auth.authenticate_session(result["session_token"])
    assert context["user"]["handle"], "synthetic scenario user has no handle"
    assert account_auth.normalize_handle(context["user"]["handle"])
