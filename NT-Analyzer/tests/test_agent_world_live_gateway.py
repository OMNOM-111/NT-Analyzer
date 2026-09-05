"""Local owner admission and existing SF Chat contracts, never real owner IO."""
from __future__ import annotations

import copy
import hashlib
import socket
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.ai_control_center import live_backtests, live_gateway as gateway
from app.ai_control_center.contracts import ActorKind, Environment, TenantScope
from app.ai_control_center.flags import Flag, REGISTRY, resolve
from app.ai_control_center.states import ContractError


USER_ID = 112233
USER_UUID = "12000000-0000-4000-8000-000000000001"
OTHER_UUID = "12000000-0000-4000-8000-000000000002"
WORKSPACE = "ws_live_gateway_owner"
OTHER_WORKSPACE = "ws_live_gateway_other"
CONVERSATION = "live-gateway-contract"


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path):
    # Override the high-priority roots too: never inherit a launched Local or
    # Preview environment, and restore every change when this test finishes.
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "development"))
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production-disabled"))
    monkeypatch.setenv("STRATFORGE_CANARY_DATA_ROOT", str(tmp_path / "canary-disabled"))
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(tmp_path / "durable.sqlite3"))
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "0")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "")
    monkeypatch.delenv(gateway.WORKSPACES_ENV, raising=False)
    monkeypatch.setattr(gateway, "_SNAPSHOTS", {})

    def no_connection(*args, **kwargs):
        pytest.fail("Live-gateway contracts must not open network connections")

    monkeypatch.setattr(socket, "create_connection", no_connection)


@pytest.fixture()
def owner(monkeypatch, tmp_path):
    monkeypatch.setenv(gateway.WORKSPACES_ENV, WORKSPACE)
    scope = {
        "user_id": USER_ID, "user_uuid": USER_UUID, "workspace_id": WORKSPACE,
        "is_owner": True, "uses_owner_runtime": True, "display_name": "Test owner",
    }
    workspace = {
        "workspace_id": WORKSPACE, "owner_user_id": USER_ID, "status": "active",
        "uses_owner_runtime": True, "kind": "personal", "membership": {"role": "owner"},
    }
    state = {
        "user": {"user_id": USER_ID, "user_uuid": USER_UUID, "is_owner": True, "status": "active"},
        "workspaces": {WORKSPACE: workspace},
        "permissions": {"role": "owner", "capabilities": {"ai_lab": True, "backtesting": True}},
        "budget_ok": True, "permission_denied": False,
    }
    calls = {"users": [], "writers": [], "permissions": [], "enforce": [], "budget": [], "audit": []}

    def find_user(uid):
        calls["users"].append(uid)
        return copy.deepcopy(state["user"]) if uid == USER_ID else None

    def writer(uid, *, workspace_id):
        calls["writers"].append((uid, workspace_id))
        if uid != USER_ID or workspace_id not in state["workspaces"]:
            raise gateway.workspaces.WorkspaceError("Writer membership revoked", 403)
        return copy.deepcopy(state["workspaces"][workspace_id])

    def permissions(uid, user):
        calls["permissions"].append((uid, copy.deepcopy(user)))
        return copy.deepcopy(state["permissions"])

    def enforce(path, raw):
        calls["enforce"].append((path, copy.deepcopy(raw)))
        if state["permission_denied"]:
            raise gateway.permissions.PermissionError("Permission revoked")

    def budget(workspace_id, amount):
        calls["budget"].append((workspace_id, amount))
        return {"ok": state["budget_ok"]}

    def audit(*args, **kwargs):
        calls["audit"].append((args, copy.deepcopy(kwargs)))
        return "aud_12000000-0000-4000-8000-000000000099"

    monkeypatch.setattr(gateway.account_auth, "find_active_user", find_user)
    monkeypatch.setattr(gateway.workspaces, "require_workspace_writer", writer)
    monkeypatch.setattr(gateway.permissions, "resolve_for_user_id", permissions)
    monkeypatch.setattr(gateway.permissions, "enforce", enforce)
    monkeypatch.setattr(gateway.ai_budgets, "check_budget", budget)
    monkeypatch.setattr(gateway.audit_events, "record", audit)
    return SimpleNamespace(scope=scope, state=state, calls=calls, root=tmp_path)


def test_default_is_off_without_reading_owner_or_creating_storage():
    assert gateway.configured() is False
    assert gateway.configured(WORKSPACE) is False
    with pytest.raises(ContractError, match="agent_world_local_disabled"):
        gateway.access({"workspace_id": WORKSPACE})
    assert not gateway.runtime_env.data_root().exists()


@pytest.mark.parametrize("value", ["*", f"{WORKSPACE},*", "ws_a", "ws_owner/path", "not_a_workspace", "ws_" + "x" * 94])
def test_invalid_allowlist_fails_closed_including_mixed_valid_entry(monkeypatch, value):
    monkeypatch.setenv(gateway.WORKSPACES_ENV, value)
    assert gateway.configured() is False
    assert gateway.configured(WORKSPACE) is False


def test_allowlist_matches_exact_workspaces_only(monkeypatch):
    monkeypatch.setenv(gateway.WORKSPACES_ENV, f" {WORKSPACE}, {OTHER_WORKSPACE}, ")
    assert gateway.configured() is True
    assert gateway.configured(WORKSPACE) is True
    assert gateway.configured(OTHER_WORKSPACE) is True
    assert gateway.configured(WORKSPACE + "_suffix") is False
    assert gateway.configured(WORKSPACE.upper()) is False


@pytest.mark.parametrize("environment", ["canary", "production"])
def test_allowlist_never_enables_other_environments(owner, monkeypatch, environment):
    monkeypatch.setenv("DEPLOYMENT_ENV", environment)
    monkeypatch.setenv("STRATFORGE_ENV", environment)
    assert gateway.configured() is False
    with pytest.raises(ContractError, match="agent_world_local_disabled"):
        gateway.access(owner.scope)
    assert owner.calls["users"] == []


def test_live_gateway_cannot_activate_inside_preview(owner, monkeypatch):
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "1")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "ab" * 12)
    assert gateway.preview_sandbox.enabled() is True
    assert gateway.configured(WORKSPACE) is False
    with pytest.raises(ContractError, match="agent_world_local_disabled"):
        gateway.access(owner.scope)
    assert owner.calls["users"] == []


def test_access_normalizes_authority_from_existing_sources_and_exact_scope(owner):
    authorized = gateway.access({**owner.scope, "capabilities": {"trade": True}, "runtime_dir": "ignored"})
    context = authorized["context"]
    assert context.scope == TenantScope(environment=Environment.DEVELOPMENT, workspace_id=WORKSPACE)
    assert context.user_uuid == UUID(USER_UUID)
    assert context.actor.kind is ActorKind.HUMAN and context.actor.actor_id == context.user_uuid
    assert authorized["source_scope"] == {"workspace_id": WORKSPACE, "user_id": USER_ID, "allow_legacy": False}
    assert authorized["chat_scope"]["capabilities"] == {"ai_lab": True, "backtesting": True}
    assert "runtime_dir" not in authorized["chat_scope"]
    assert owner.calls["writers"] == [(USER_ID, WORKSPACE)] * 2
    assert [path for path, _ in owner.calls["enforce"]] == [gateway.PREFIX + "backtests", "/api/jobs"] * 2
    assert all(raw["_request_method"] == "POST" for _, raw in owner.calls["enforce"])
    assert owner.calls["budget"] == [(WORKSPACE, 0.0)]


@pytest.mark.parametrize("change,code", [
    ({"is_owner": False}, "agent_world_local_owner_required"),
    ({"is_owner": 1}, "agent_world_local_owner_required"),
    ({"uses_owner_runtime": False}, "agent_world_local_owner_required"),
    ({"user_uuid": "not-a-uuid"}, "agent_world_identity_required"),
    ({"user_uuid": OTHER_UUID}, "agent_world_local_owner_required"),
    ({"user_id": "bad"}, "agent_world_identity_required"),
    ({"workspace_id": OTHER_WORKSPACE}, "agent_world_local_disabled"),
])
def test_untrusted_or_stale_scope_is_not_authority(owner, change, code):
    with pytest.raises(ContractError, match=code):
        gateway.access({**owner.scope, **change})


@pytest.mark.parametrize("change", [{"is_owner": False}, {"is_preview_user": True}, {"is_service_account": True}, {"user_uuid": OTHER_UUID}])
def test_active_owner_is_fetched_again_for_admission(owner, change):
    authorized = gateway.access(owner.scope)
    owner.state["user"].update(change)
    with pytest.raises(ContractError, match="agent_world_local_owner_required"):
        authorized["admit"]()
    assert len(owner.calls["users"]) == 3


def test_deleted_user_revokes_existing_admission(owner):
    authorized = gateway.access(owner.scope)
    owner.state["user"] = None
    with pytest.raises(ContractError, match="agent_world_local_owner_required"):
        authorized["admit"]()


@pytest.mark.parametrize("change", [
    {"status": "archived"}, {"uses_owner_runtime": False},
    {"owner_user_id": USER_ID + 1}, {"membership": {"role": "admin"}},
    {"membership": {"role": "viewer"}}, {"membership": {}},
])
def test_workspace_ownership_is_revalidated_not_just_writer_role(owner, change):
    authorized = gateway.access(owner.scope)
    owner.state["workspaces"][WORKSPACE].update(change)
    with pytest.raises(ContractError, match="agent_world_owner_workspace_required"):
        authorized["admit"]()


def test_membership_and_server_opt_in_revocation(owner, monkeypatch):
    authorized = gateway.access(owner.scope)
    owner.state["workspaces"].pop(WORKSPACE)
    with pytest.raises(gateway.workspaces.WorkspaceError):
        authorized["admit"]()
    # No cached allow result may survive the trusted server opt-in removal.
    monkeypatch.delenv(gateway.WORKSPACES_ENV)
    with pytest.raises(ContractError, match="agent_world_local_disabled"):
        authorized["admit"]()


@pytest.mark.parametrize("capability", ["ai_lab", "backtesting"])
def test_current_capabilities_are_mandatory(owner, capability):
    authorized = gateway.access(owner.scope)
    owner.state["permissions"]["capabilities"][capability] = False
    with pytest.raises(ContractError, match="agent_world_capability_required"):
        authorized["admit"]()


def test_existing_permission_authority_can_deny_after_admission(owner):
    authorized = gateway.access(owner.scope)
    owner.state["permission_denied"] = True
    with pytest.raises(gateway.permissions.PermissionError):
        authorized["admit"]()


def test_existing_budget_can_deny_after_admission(owner):
    authorized = gateway.access(owner.scope)
    owner.state["budget_ok"] = False
    with pytest.raises(ContractError, match="agent_world_budget_denied"):
        authorized["admit"]()


def test_only_three_local_flags_enabled_and_snapshot_is_workspace_scoped(owner, monkeypatch):
    authorized = gateway.access(owner.scope)
    snapshot = authorized["snapshot"]
    enabled = {flag for flag in REGISTRY if resolve(flag, scope=authorized["context"].scope, snapshot=snapshot).enabled}
    assert enabled == {Flag.AI_CONTROL_CENTER_READ_MODEL, Flag.AI_COMMAND_CENTER_UI, Flag.AI_TASK_GRAPH_V2}
    assert not resolve(Flag.AI_EVALUATION_SHADOW, scope=authorized["context"].scope, snapshot=snapshot).enabled
    foreign = TenantScope(environment=Environment.DEVELOPMENT, workspace_id=OTHER_WORKSPACE)
    assert not any(resolve(flag, scope=foreign, snapshot=snapshot).enabled for flag in REGISTRY)
    assert gateway.flag_snapshot(authorized["context"]) is snapshot
    assert len(owner.calls["audit"]) == 1
    assert owner.calls["audit"][0][1]["details"]["synthetic"] is False
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(owner.root / "another-runtime"))
    assert gateway.flag_snapshot(authorized["context"]) is not snapshot
    assert len(owner.calls["audit"]) == 2


@pytest.mark.parametrize("raw,allowed", [
    ({"is_owner": True, "role": "owner", "source": "local"}, True),
    ({"is_owner": True, "role": "owner", "source": "browser", "device_confirmation_state": "active"}, True),
    ({"is_owner": True, "role": "owner", "device_confirmation_state": "pending"}, False),
    ({"is_owner": True, "role": "owner"}, False),
    ({"is_owner": True, "role": "read_only", "source": "local"}, False),
    ({"is_owner": False, "role": "owner", "source": "local"}, False),
])
def test_handler_requires_real_local_entry_or_confirmed_owner_session(owner, raw, allowed):
    handler = SimpleNamespace(_remote_context=raw, _ai_conversation_scope=lambda: owner.scope)
    if allowed:
        assert gateway.from_handler(handler)["context"].user_uuid == UUID(USER_UUID)
    else:
        with pytest.raises(ContractError, match="agent_world_confirmed_owner_required"):
            gateway.from_handler(handler)
    assert gateway.navigation(handler)["enabled"] is allowed
    assert gateway.navigation(handler)["synthetic"] is False


def test_service_args_excludes_internal_flags_and_preserves_scope(owner):
    authorized = gateway.access(owner.scope)
    args = gateway.service_args({**authorized, "unsafe": "ignored"})
    assert set(args) == {"context", "source_scope", "chat_scope", "admit"}
    assert args["admit"] is authorized["admit"]
    assert args["source_scope"]["allow_legacy"] is False
    assert args["context"].scope.workspace_id == args["chat_scope"]["workspace_id"] == WORKSPACE


def test_overview_uses_authorized_service_scope_and_only_terminal_outcomes(owner, monkeypatch):
    from app.ai_control_center import live_charts

    authorized = gateway.access(owner.scope)
    tasks = [{"id": f"task-{status}", "title": status, "source_status": status,
              "status": "succeeded" if status == "done" else status, "evidence_count": 1 if status == "done" else 0,
              "source_job_id": f"job-{status}", "updated_at": "2026-09-05T00:00:00Z"}
             for status in ("queued", "running", "done", "failed")]
    calls = []

    class ExistingService:
        def overview(self, **kwargs):
            calls.append(("overview", kwargs))
            return {"work": {"items": tasks}, "agents": {"items": [{"id": "tolik", "rating_state": "NEW"}]},
                    "stats": {"running": 2, "completed": 1, "failed": 1}}

        def get(self, **kwargs):
            calls.append(("get", kwargs))
            return {"result_text": "Actual report including negative PnL"}

    monkeypatch.setattr(live_backtests, "LiveBacktestService", ExistingService)
    monkeypatch.setattr(live_charts, "details", lambda actual: [] if actual is authorized else pytest.fail("Wrong chart scope"))
    result = gateway.overview(authorized)
    assert [item["source_job_id"] for item in result["outcomes"]] == ["job-done", "job-failed"]
    assert result["stats"]["active_tasks"] == 2 and result["stats"]["completed_tasks"] == 1
    assert result["scope"] == {"environment": "development", "workspace_id": WORKSPACE, "synthetic": False}
    assert result["flags"][Flag.AI_EVALUATION_SHADOW.value] is False
    assert result["capabilities"]["can_run_demo"] is False
    for method, kwargs in calls:
        assert kwargs["source_scope"] == authorized["source_scope"]
        assert kwargs["context"] == authorized["context"]
        assert set(kwargs) == set(gateway.service_args(authorized)) | ({"job_id"} if method == "get" else set())


def test_parser_preserves_negative_parameters_and_exact_period():
    spec = gateway.parse_backtest(gateway.BACKTEST_EXAMPLE + ", Offset=-3, Threshold=-0.25, Enabled=false, Guard=true")
    assert spec["class_name"] == "SampleMACrossOver" and spec["instrument"] == "MNQ 09-26"
    assert spec["bars_period_type"] == "Minute" and spec["bars_period_value"] == 5
    assert spec["from_utc"] == "2026-08-24T00:00:00Z" and spec["to_utc"] == "2026-08-29T00:00:00Z"
    assert spec["parameters"] == {"Fast": 10, "Slow": 25, "Offset": -3, "Threshold": -0.25, "Enabled": False, "Guard": True}
    assert spec["slippage_ticks"] == 1


@pytest.mark.parametrize("text", [
    "Толик, запусти бэктест SampleMACrossOver на MNQ 09-26, 5m",
    "Толик, запусти бэктест SampleMACrossOver, 5m, с 2026-08-24 по 2026-08-29",
    "Толик, запусти бэктест SampleMACrossOver на MNQ 09-26, с 2026-08-24 по 2026-08-29",
    "Толик, запусти бэктест на MNQ 09-26, 5m, с 2026-08-24 по 2026-08-29",
    "Толик, запусти бэктест SampleMACrossOver на MNQ 09-26, 5m, с 2026/08/24 по 2026/08/29",
])
def test_parser_never_invents_missing_dates_strategy_instrument_or_timeframe(text):
    with pytest.raises(ContractError, match="live_backtest_explicit_spec_required"):
        gateway.parse_backtest(text)


def test_duplicate_parameter_is_rejected():
    with pytest.raises(ContractError, match="live_backtest_duplicate_parameter"):
        gateway.parse_backtest(gateway.BACKTEST_EXAMPLE + ", Fast=99")


@pytest.mark.parametrize("period", ["с 2026-99-24 по 2026-08-29", "с 2026-08-29 по 2026-08-24", "с 2026-08-24 по 2026-10-29"])
def test_parser_output_still_obeys_authoritative_date_validation(period):
    text = gateway.BACKTEST_EXAMPLE.replace("с 2026-08-24 по 2026-08-29", period)
    with pytest.raises(ContractError):
        live_backtests._spec(gateway.parse_backtest(text))


@pytest.mark.parametrize("source,message", [("telegram", gateway.BACKTEST_EXAMPLE), ("app", "Объясни, что такое бэктест")])
def test_only_explicit_app_command_enters_live_path(owner, monkeypatch, source, message):
    monkeypatch.setattr(gateway, "access", lambda *a, **k: pytest.fail("Non-command must retain existing router"))
    assert gateway.try_chat(message, scope=owner.scope, conversation_id=CONVERSATION, request_id="request-1", source=source) is None


def test_disabled_live_path_never_touches_legacy_chat_or_service(owner, monkeypatch):
    monkeypatch.delenv(gateway.WORKSPACES_ENV)
    monkeypatch.setattr(gateway, "access", lambda *a, **k: pytest.fail("Disabled path must not authenticate or mutate"))
    monkeypatch.setattr(live_backtests, "LiveBacktestService", lambda: pytest.fail("Disabled path must not instantiate service"))
    assert gateway.try_chat(gateway.BACKTEST_EXAMPLE, scope=owner.scope, conversation_id=CONVERSATION,
                            request_id="disabled-request", source="app") is None
    assert gateway.poll_once() == {"enabled": False}


@pytest.fixture()
def chat(owner, monkeypatch):
    from app import telegram_service
    from app.ai_lab import chief_agent

    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", owner.root / "chat-registry")
    monkeypatch.setattr(chief_agent.paths, "ensure_dirs", lambda: None)
    # The tested adapter must not send or even schedule Telegram effects when
    # the machine's existing owner mirror happens to be enabled.
    telegram_calls = []
    monkeypatch.setattr(chief_agent, "_can_mirror_to_telegram", lambda scope: True)
    monkeypatch.setattr(chief_agent, "_sync_telegram_topic_title_async", lambda *a, **k: telegram_calls.append("topic"))
    monkeypatch.setattr(telegram_service, "send_chief_report", lambda *a, **k: telegram_calls.append("report"))
    return SimpleNamespace(chief=chief_agent, telegram_calls=telegram_calls, owner=owner)


def envelope(owner, *, request_id="live-request-1", status="queued", conversation_id=CONVERSATION):
    return {
        "scope": copy.deepcopy(owner.scope), "conversation_id": conversation_id, "request_id": request_id,
        "agent_id": "tolik", "agent_name": "Толик", "text": "Queued is not a verified result",
        "task_id": "live-task-1", "source_job_id": "ui_live_gateway_test", "status": status,
        "source_kind": "ninjatrader_report", "synthetic": False,
        "verification": {"passed": status == "completed"},
    }


def transcript(chat, *, scope=None, conversation_id=CONVERSATION):
    return chat.chief.read_jsonl(chat.chief._conversation_file(conversation_id, scope=scope or chat.owner.scope))


def conversation_row(chat):
    return next(row for row in chat.chief.list_conversations(scope=chat.owner.scope) if row["conversation_id"] == CONVERSATION)


def test_explicit_chat_command_calls_existing_service_with_scoped_admission(chat, monkeypatch):
    calls = []

    class ExistingService:
        def start(self, **kwargs):
            kwargs["admit"]()
            calls.append(kwargs)
            return {"job_id": "ui_live_gateway_test", "task_id": "live-task-1"}

    monkeypatch.setattr(live_backtests, "LiveBacktestService", ExistingService)
    result = gateway.try_chat(gateway.BACKTEST_EXAMPLE, scope=chat.owner.scope, conversation_id=CONVERSATION,
                              request_id="service-request", source="app")
    assert len(calls) == 1
    assert calls[0]["source_scope"] == {"workspace_id": WORKSPACE, "user_id": USER_ID, "allow_legacy": False}
    assert calls[0]["chat_scope"]["user_uuid"] == USER_UUID
    assert calls[0]["idempotency_key"] == "service-request"
    assert calls[0]["conversation_id"] == CONVERSATION
    assert result["message"]["fulfillment"] == "unset" and result["actions"][0]["status"] == "queued"
    assert "Это ещё не результат" in result["reply"]
    assert len(transcript(chat)) == 2


def test_incomplete_explicit_chat_command_is_blocked_without_submitting_job(chat, monkeypatch):
    monkeypatch.setattr(live_backtests, "LiveBacktestService", lambda: SimpleNamespace(
        start=lambda **kwargs: pytest.fail("Missing period must not create a canonical job")))
    result = gateway.try_chat("Толик, запусти бэктест SampleMACrossOver на MNQ 09-26, 5m", scope=chat.owner.scope,
                              conversation_id=CONVERSATION, request_id="missing-dates", source="app")
    assert result["actions"][0]["status"] == "blocked"
    assert result["message"]["fulfillment"] == "failed"
    assert "live_backtest_explicit_spec_required" in result["reply"]


def test_chat_request_hashes_complete_identity_before_storage_limit(chat):
    ids = ["report." + "a" * 130 + suffix for suffix in (".revision-one", ".revision-two")]
    for request_id in ids:
        chat.chief.report_agent_world_live_update(envelope(chat.owner, request_id=request_id))
    rows = transcript(chat)
    assert len(rows) == 2
    expected = ["aw.live." + hashlib.sha256(value.encode()).hexdigest() for value in ids]
    assert [row["request_id"] for row in rows] == expected
    assert len(set(expected)) == 2 and all(len(key) <= 120 for key in expected)


@pytest.mark.parametrize("status,fulfillment,state", [
    ("queued", "unset", "in_progress"), ("running", "unset", "in_progress"),
    ("completed", "done", "completed"), ("failed", "failed", "blocked"),
])
def test_chat_distinguishes_pending_from_verified_result(chat, status, fulfillment, state):
    result = chat.chief.report_agent_world_live_update(envelope(chat.owner, status=status))
    assert result["message"]["fulfillment"] == fulfillment
    assert result["actions"][0]["synthetic"] is False
    row = conversation_row(chat)
    assert row["work_state"] == state and not row.get("closed", False)
    assert chat.telegram_calls == []


@pytest.mark.parametrize("change", [
    {"synthetic": True}, {"source_kind": "invented"},
    {"status": "completed", "verification": {"passed": False}},
])
def test_chat_rejects_synthetic_or_unverified_completion_before_append(chat, change):
    with pytest.raises(chat.chief.ChiefAgentError):
        chat.chief.report_agent_world_live_update({**envelope(chat.owner), **change})
    assert transcript(chat) == []


@pytest.mark.parametrize("scope", [None, {}, {"is_owner": True}, {"is_owner": False, "uses_owner_runtime": True, "workspace_id": WORKSPACE}])
def test_chat_ingress_denies_invalid_or_nonowner_scope_before_callback(chat, scope):
    with pytest.raises(ContractError):
        chat.chief.run_agent_world_live_request(message="No unsafe fallback", request_id="denied-request",
            conversation_id=CONVERSATION, scope=scope, execute=lambda: pytest.fail("Unauthorized callback"))
    assert not (chat.owner.root / "chat-registry").exists()


def test_chat_result_replay_scans_full_history_and_repairs_post_append_crash(chat, monkeypatch):
    update = envelope(chat.owner, status="completed")
    original = chat.chief._touch_conversation

    def fail_touch(*args, **kwargs):
        raise OSError("injected post-append failure")

    monkeypatch.setattr(chat.chief, "_touch_conversation", fail_touch)
    with pytest.raises(OSError, match="injected"):
        chat.chief.report_agent_world_live_update(update)
    monkeypatch.setattr(chat.chief, "_touch_conversation", original)
    path = chat.chief._conversation_file(CONVERSATION, scope=chat.owner.scope)
    for number in range(501):
        chat.chief.append_jsonl(path, {"role": "user", "content": "Later message", "request_id": f"later.{number}"})
    result = chat.chief.report_agent_world_live_update(update)
    assert result["idempotent_replay"] is True and len(transcript(chat)) == 502
    assert conversation_row(chat)["message_count"] == 502
    assert conversation_row(chat)["work_state"] == "completed"


def test_chat_request_replay_does_not_execute_or_append_again_after_full_history(chat):
    update = envelope(chat.owner)
    args = dict(message="Owner explicit backtest", request_id=update["request_id"], conversation_id=CONVERSATION,
                scope=chat.owner.scope)
    chat.chief.run_agent_world_live_request(**args, execute=lambda: update)
    path = chat.chief._conversation_file(CONVERSATION, scope=chat.owner.scope)
    for number in range(501):
        chat.chief.append_jsonl(path, {"role": "user", "content": "Later message", "request_id": f"later.{number}"})
    result = chat.chief.run_agent_world_live_request(**args, execute=lambda: pytest.fail("Replay must not submit a second job"))
    assert result["idempotent_replay"] is True and len(transcript(chat)) == 503
    assert conversation_row(chat)["message_count"] == 503


def test_chat_request_repairs_projection_state_after_assistant_append_crash(chat, monkeypatch):
    update = envelope(chat.owner)
    args = dict(message="Owner explicit backtest", request_id=update["request_id"], conversation_id=CONVERSATION,
                scope=chat.owner.scope)
    original = chat.chief._touch_conversation

    def fail_after_assistant(*call_args, **kwargs):
        if any(row.get("role") == "assistant" for row in transcript(chat)):
            raise OSError("injected assistant index failure")
        return original(*call_args, **kwargs)

    monkeypatch.setattr(chat.chief, "_touch_conversation", fail_after_assistant)
    with pytest.raises(OSError, match="injected"):
        chat.chief.run_agent_world_live_request(**args, execute=lambda: update)
    monkeypatch.setattr(chat.chief, "_touch_conversation", original)
    result = chat.chief.run_agent_world_live_request(**args, execute=lambda: pytest.fail("Already appended result"))
    assert result["idempotent_replay"] is True and len(transcript(chat)) == 2
    assert conversation_row(chat)["message_count"] == 2
    assert conversation_row(chat)["work_state"] == "in_progress"


def test_live_request_never_sends_or_schedules_telegram(chat):
    update = envelope(chat.owner)
    chat.chief.run_agent_world_live_request(message="Explicit local request", request_id=update["request_id"],
        conversation_id=CONVERSATION, scope=chat.owner.scope, execute=lambda: update)
    assert chat.telegram_calls == []


def test_identical_live_request_keys_do_not_cross_workspace(chat, monkeypatch):
    other = copy.deepcopy(chat.owner.state["workspaces"][WORKSPACE])
    other["workspace_id"] = OTHER_WORKSPACE
    chat.owner.state["workspaces"][OTHER_WORKSPACE] = other
    monkeypatch.setenv(gateway.WORKSPACES_ENV, f"{WORKSPACE},{OTHER_WORKSPACE}")
    first = envelope(chat.owner)
    second = {**envelope(chat.owner), "scope": {**chat.owner.scope, "workspace_id": OTHER_WORKSPACE}, "text": "Other workspace"}
    assert chat.chief.report_agent_world_live_update(first)["idempotent_replay"] is False
    assert chat.chief.report_agent_world_live_update(second)["idempotent_replay"] is False
    assert transcript(chat)[0]["content"] != transcript(chat, scope=second["scope"])[0]["content"]
    assert len(transcript(chat)) == len(transcript(chat, scope=second["scope"])) == 1


def test_existing_monitor_revalidates_and_reconciles_only_opted_in_owner_scope(chat, monkeypatch):
    calls = []
    monkeypatch.setattr(gateway.workspaces, "runtime_monitor_scopes", lambda: [
        {**chat.owner.scope, "user_uuid": "stale-monitor-value"},
        {**chat.owner.scope, "workspace_id": OTHER_WORKSPACE},
    ])

    class ExistingService:
        def reconcile(self, **kwargs):
            kwargs["admit"]()
            calls.append(kwargs)
            return {"delivered": 1, "errors": []}

    monkeypatch.setattr(live_backtests, "LiveBacktestService", ExistingService)
    assert gateway.poll_once() == {"enabled": True, "delivered": 1, "errors": []}
    assert len(calls) == 1
    assert calls[0]["context"].user_uuid == UUID(USER_UUID)
    assert calls[0]["source_scope"]["workspace_id"] == WORKSPACE
    assert calls[0]["publish"] is chat.chief.report_agent_world_live_update
    chat.owner.state["user"]["is_owner"] = False
    assert gateway.poll_once() == {"enabled": True, "delivered": 0, "errors": [{"code": "agent_world_local_admission_denied"}]}
    assert len(calls) == 1
