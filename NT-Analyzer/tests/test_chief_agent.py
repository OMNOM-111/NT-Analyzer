from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app import durable
from app.ai_lab import chief_agent


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(chief_agent, "_state_path", lambda: tmp_path / "chief.json")
    monkeypatch.setattr(chief_agent, "_tasks_path", lambda: tmp_path / "tasks.jsonl")
    monkeypatch.setattr(chief_agent, "_reports_dir", lambda: tmp_path)
    monkeypatch.setattr(chief_agent, "_conversation_path", lambda: tmp_path / "conversation.jsonl")
    convs = tmp_path / "convs"
    monkeypatch.setattr(chief_agent, "_conversations_index_path", lambda: tmp_path / "conv_index.json")
    monkeypatch.setattr(chief_agent, "_conversations_dir", lambda: (convs.mkdir(parents=True, exist_ok=True) or convs))
    monkeypatch.setattr(chief_agent, "_user_memory_path", lambda scope: tmp_path / "memory.jsonl")
    monkeypatch.setattr(chief_agent, "_conversation_memory_archive_path", lambda scope: tmp_path / "memory_archive.jsonl")
    monkeypatch.setattr(chief_agent, "_usage_stats", lambda agent_id="": {
        "requests": 0, "successful_requests": 0, "input_tokens": 0,
        "cached_input_tokens": 0, "cache_hit_pct": 0, "output_tokens": 0, "cost_usd": 0,
    })


def _complete_strategy_reply() -> str:
    return (
        "Дмитрий Сергеевич, основной вариант — ORB с подтверждением стороны VWAP на MNQ 15m. "
        "Я выбрал его по REF-021 и PATTERN_EFFECTIVENESS.md: это гипотеза, а не уже доказанная доходность. "
        "Предыдущие WEX-проверки показывают главный риск — комиссия уничтожает частые входы, поэтому здесь "
        "нужны максимум две сделки в день и только выраженный режим открытия.\n\n"
        "Вход: после формирования 30-минутного opening range цена выходит из диапазона, остаётся по правильную "
        "сторону VWAP и подтверждает импульс объёмом. Ложный пробой без закрытия за границей сигнала не даёт. "
        "Выход: защитный стоп возвращается внутрь диапазона, первая цель покрывает минимум двукратный риск, "
        "после чего позиция закрывается до конца сессии. Риск ограничивается одной позицией и дневным лимитом.\n\n"
        "Альтернатива — liquidity sweep reversal REF-017, но она сложнее для однозначной формализации; EMA pullback "
        "ниже в рейтинге из-за смены режима и слабых прошлых результатов. Если вы скажете «начинай», сначала проверю "
        "signal sanity, затем smoke, IS/OOS и walk-forward после комиссии; при провале изменю подтверждение или режим, "
        "а не буду бесконечно перебирать параметры."
    )


def test_mission_is_historical_only_and_capped(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    mission = chief_agent.start_mission({
        "goal": "robust MNQ research", "duration_hours": 999,
        "paid_budget_usd": 99, "target_root": "mnq",
    })

    assert mission["status"] == "active"
    assert mission["historical_only"] is True
    assert mission["paper_live_authority"] is False
    assert mission["paid_budget_usd"] == 5.0
    start = datetime.fromisoformat(mission["started_at_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(mission["ends_at_utc"].replace("Z", "+00:00"))
    assert (end - start).total_seconds() == 168 * 3600


def test_complexity_classifier_keeps_critical_decision_deterministic() -> None:
    assert chief_agent.classify_complexity("кратко переформатировать", "telegram_assistant") == "light"
    assert chief_agent.classify_complexity("final portfolio risk audit", "final_judge") == "critical"
    assert chief_agent.classify_complexity("analyze ordinary metrics", "backtest_analyst") == "standard"


def test_one_star_comment_becomes_user_scoped_memory(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    scope = {
        "user_id": 11, "workspace_id": "ws-shared", "membership_role": "owner",
        "is_owner": True, "display_name": "Test Owner", "uses_owner_runtime": True,
    }
    path = chief_agent._conversation_file("C-FEEDBACK", scope=scope)
    user = chief_agent._append_conversation("user", "покажи график", source="app", path=path, scope=scope)
    assistant = chief_agent._append_conversation("assistant", "не могу", source="app", path=path, scope=scope)

    chief_agent.rate_message("C-FEEDBACK", assistant["message_id"], 1, "Сначала запроси бары", scope=scope)

    memories = chief_agent._user_memories(scope)
    assert memories[-1]["kind"] == "negative_feedback"
    assert memories[-1]["text"] == "Сначала запроси бары"
    assert "покажи график" in memories[-1]["context"]


def test_closed_dialogue_is_archived_into_one_shared_memory_bundle(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    scope = {
        "user_id": 11, "workspace_id": "ws-memory", "membership_role": "owner",
        "is_owner": True, "display_name": "Test Owner", "uses_owner_runtime": True,
    }
    chief_agent.create_conversation("Проверка стратегии", conversation_id="C-MEMORY", scope=scope)
    path = chief_agent._conversation_file("C-MEMORY", scope=scope)
    chief_agent._append_conversation("user", "Не менять торговые параметры", source="app", path=path, scope=scope)
    chief_agent._append_conversation(
        "assistant", "Принял правило", source="app", agent_name="Толик", path=path, scope=scope,
    )

    chief_agent.set_conversation_closed("C-MEMORY", True, scope=scope)
    bundle = chief_agent._shared_memory_bundle(scope)

    assert bundle["loaded_at_once"] is True
    archived = [row for row in bundle["entries"] if row.get("kind") == "conversation_archive"]
    assert len(archived) == 1
    assert archived[0]["conversation_id"] == "C-MEMORY"
    assert any("Не менять торговые параметры" in row["content"] for row in archived[0]["dialogue"])


def test_default_system_chat_is_shared_only_inside_workspace(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    a = {"user_id": 1, "workspace_id": "ws-one", "membership_role": "owner", "is_owner": True}
    b = {"user_id": 2, "workspace_id": "ws-one", "membership_role": "viewer", "is_owner": False}
    other = {"user_id": 3, "workspace_id": "ws-two", "membership_role": "owner", "is_owner": True}

    assert chief_agent._conversation_file("default", scope=a) == chief_agent._conversation_file("default", scope=b)
    assert chief_agent._conversation_file("default", scope=a) != chief_agent._conversation_file("default", scope=other)


def test_runtime_heartbeat_transitions_emit_workspace_service_events(tmp_path, monkeypatch) -> None:
    from app import runtime

    _isolate(tmp_path, monkeypatch)
    scope = {"user_id": 7, "workspace_id": "ws-heartbeat", "membership_role": "owner", "is_owner": True}
    states = iter([
        {"present": True, "fresh": True, "age_sec": 1},
        {"present": True, "fresh": False, "age_sec": 40},
        {"present": True, "fresh": True, "age_sec": 1},
    ])
    events = []
    monkeypatch.setattr(runtime, "read_heartbeat", lambda: next(states))
    monkeypatch.setattr(runtime, "read_strategies_raw", lambda: [])
    monkeypatch.setattr(runtime, "read_accounts", lambda: [])
    monkeypatch.setattr(chief_agent, "analyze_event", lambda event_type, payload, **kwargs: events.append((event_type, kwargs.get("scope"))))

    chief_agent._runtime_monitor_tick(scope)
    chief_agent._runtime_monitor_tick(scope)
    chief_agent._runtime_monitor_tick(scope)

    assert [row[0] for row in events] == ["connection_lost", "connection_restored"]
    assert all(row[1]["workspace_id"] == "ws-heartbeat" for row in events)


def test_daily_audit_flags_missing_oos_and_attributes_model(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(chief_agent.registry, "list_experiments", lambda limit=1000: [{
        "experiment_id": "EXP-1", "class_name": "S1", "created_at_utc": now,
        "status": "rejected", "backtests": [{"job_id": "J1"}],
        "analysis": {"years_tested": 1, "trades_total": 20, "stress_pass_flag": False},
    }])
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "agent_name": "DeepSeek Chief", "actual_model": "deepseek-v4-pro",
        "content": "Есть сомнения: нужен OOS.", "input_tokens": 100,
        "cached_input_tokens": 80, "output_tokens": 20, "cost_usd": 0.001,
    })

    report = chief_agent.audit_recent_backtests(use_llm=True)

    assert report["experiments_checked"] == 1
    assert "oos_evidence_missing" in report["findings"][0]["flags"]
    assert report["model_review"]["model"] == "deepseek-v4-pro"
    assert report["model_review"]["cached_input_tokens"] == 80


def test_live_action_cannot_be_proposed(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    try:
        chief_agent.propose_action("place_order", {}, "LLM suggestion")
    except chief_agent.ChiefAgentError as exc:
        assert "только enable/disable" in str(exc)
    else:
        raise AssertionError("live/order action must be rejected")


def test_orchestrator_can_directly_reconnect_modeling(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_extract_account_name_from_message", lambda _msg: "DEMO3369390")
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("direct reconnect request should not need an LLM")
    ))
    queued = []
    monkeypatch.setattr(
        chief_agent,
        "_queue_runtime_reconnect",
        lambda account_name="", **kwargs: queued.append({"account_name": account_name, **kwargs}) or {
            "account_name": account_name or "DEMO3369390",
            "command_id": "cmd-reconnect-1",
        },
    )

    result = chief_agent.handle_message("Включи моделирование на DEMO3369390", mirror_to_telegram=False)

    assert result["actions"][0]["name"] == "reconnect_runtime_connection"
    assert result["actions"][0]["status"] == "completed"
    assert queued[0]["account_name"] == "DEMO3369390"


def test_orchestrator_chat_uses_auto_model_and_executes_allowlisted_plan(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {"active_run": None})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Запускаю historical цикл.","confidence":0.94,"doubts":[],"actions":[{"name":"start_research","arguments":{"goal":"MNQ robustness","duration_hours":24,"target_roots":["MNQ"],"strategy_count_per_cycle":1,"iterations_per_strategy":1,"paid_budget_usd":0},"reason":"explicit"}]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
        "input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 50, "cost_usd": 0,
    })
    started = []
    monkeypatch.setattr(chief_agent, "start_mission", lambda args: started.append(args) or {
        "mission_id": "MISSION-TEST", "ends_at_utc": "2026-07-02T00:00:00Z",
    })

    result = chief_agent.handle_message(
        "Запусти разработку одной MNQ стратегии", source="app", mirror_to_telegram=False,
    )

    assert result["model"] == "gemini-2.5-flash"
    assert result["actions"][0]["status"] == "completed"
    assert started[0]["strategy_count_per_cycle"] == 1
    history = chief_agent._read_conversation(10)
    assert [row["role"] for row in history] == ["user", "assistant"]


def test_orchestrator_message_rating_updates_assistant_row(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    user = chief_agent._append_conversation("user", "Вопрос", source="test")
    assistant = chief_agent._append_conversation("assistant", "Ответ", source="test")

    result = chief_agent.rate_message("default", assistant["message_id"], 1, "Нужны факты", source="owner")

    assert result["message"]["rating"] == 1
    assert result["message"]["feedback_comment"] == "Нужны факты"
    assert result["message"]["feedback_source"] == "owner"
    assert result["message"]["feedback_timestamp_utc"]
    rows = chief_agent._read_conversation(10)
    assert rows[-1]["rating"] == 1
    assert rows[-1]["feedback_comment"] == "Нужны факты"
    try:
        chief_agent.rate_message("default", user["message_id"], 3, "")
    except chief_agent.ChiefAgentError as exc:
        assert "только ответы" in str(exc)
    else:
        raise AssertionError("user message rating must fail")


def test_scoped_conversation_metadata_is_indexed_in_sqlite(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(tmp_path / "durable.sqlite3"))
    scope = {
        "user_id": 101,
        "workspace_id": "ws_personal_AAAAAAAA",
        "membership_role": "owner",
        "is_owner": True,
    }

    chief_agent.create_conversation("Risk review", conversation_id="C-META", scope=scope)
    scope_id = chief_agent._conversation_scope_key(scope)
    row = durable.get_chat_conversation(None, "C-META", scope_id=scope_id)

    assert row is not None
    assert row["workspace_id"] == "ws_personal_AAAAAAAA"
    assert row["user_id"] == "101"
    assert row["title"] == "Risk review"

    chief_agent.rename_conversation("C-META", "Renamed", scope=scope)
    assert durable.get_chat_conversation(None, "C-META", scope_id=scope_id)["title"] == "Renamed"
    chief_agent.delete_conversation("C-META", scope=scope)
    assert durable.get_chat_conversation(None, "C-META", scope_id=scope_id) is None


def test_manager_tier_forces_strong_model_complexity(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    captured = {}
    complete_reply = (
        "Дмитрий Сергеевич, вот мой разбор и рекомендация — почему я выбрал именно этот "
        "подход и на чём он основан. Вход планирую по подтверждению сигнала на одном "
        "инструменте, выход — защитный стоп и цель по риску, комиссия и просадка учтены и "
        "ограничены. Проверку проведу через signal sanity, IS/OOS и walk-forward. "
        "Альтернативу пока не выбрал, она ниже по приоритету. Скажите «Запускай», когда всё "
        "готово, и только тогда я начну процесс."
    )
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: captured.update(kwargs) or {
        "content": complete_reply, "provider": "deepseek", "actual_model": "deepseek-v4-pro",
    })

    result = chief_agent.handle_message("Как дела?", agent="manager", mirror_to_telegram=False)

    # Управляющий always deliberates with the strong model and never executes.
    assert captured["complexity"] == "critical"
    assert result["complexity"] == "critical"
    assert result["agent"] == "manager"
    assert result["actions"] == []


def test_management_role_can_be_addressed_by_name_in_message(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    complete_reply = (
        "Дмитрий Сергеевич, вот мой полный разбор ситуации и рекомендация. "
        "Сначала проверим исходные факты и риски, затем согласуем безопасное действие. "
        "Пока ничего не запускаю: скажите, если поручаете приступить к выполнению. "
        "Так решение останется управляемым, проверяемым и обратимым."
    )
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": complete_reply, "provider": "deepseek", "actual_model": "deepseek-v4-pro",
    })

    result = chief_agent.handle_message("Управляющий, как дела?", mirror_to_telegram=False)

    assert result["agent"] == "manager"
    assert result["message"]["agent_name"] == "Управляющий"


def test_manager_tier_plan_request_does_not_auto_execute(tmp_path, monkeypatch) -> None:
    """Regression: asking the Управляющий to *form a plan* must only present the
    plan and never launch research, even if the model proposes start_research."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    started: list = []
    monkeypatch.setattr(chief_agent, "start_mission", lambda args: started.append(args) or {
        "mission_id": "SHOULD-NOT-START", "ends_at_utc": "2026-07-03T00:00:00Z",
    })
    # Even if the model returns a JSON plan with actions, the deliberative lane
    # strips them: the manager talks, it does not dispatch.
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Запускаю исследование.","confidence":0.95,"actions":[{"name":"start_research","arguments":{"goal":"MGC","duration_minutes":300,"target_roots":["MGC"]}}]}',
        "provider": "deepseek", "actual_model": "deepseek-v4-pro",
    })

    result = chief_agent.handle_message(
        "Сформируй план на реализацию следующей стратегии, я дам тебе 5 часов на реализацию",
        agent="manager", mirror_to_telegram=False,
    )

    assert started == [], "a plan-formation request must never launch a mission"
    assert result["actions"] == []
    assert result["agent"] == "manager"


def test_plan_request_is_discussion_only_across_tiers() -> None:
    assert chief_agent._is_plan_request("Сформируй план на реализацию стратегии")
    assert chief_agent._is_plan_request("составь план по разработке")
    assert chief_agent._is_plan_request("предложи план действий")
    # Running an already-agreed plan is not a plan-formation request.
    assert not chief_agent._is_plan_request("Запусти по плану")
    assert not chief_agent._is_plan_request("выполни план")
    assert not chief_agent._is_plan_request("Как дела?")


def test_secretary_tier_forces_light_model_complexity(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    captured = {}
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: captured.update(kwargs) or {
        "content": '{"reply":"Готово.","confidence":0.2,"doubts":[],"actions":[]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })

    result = chief_agent.handle_message("Как дела?", agent="secretary", mirror_to_telegram=False)

    assert captured["complexity"] == "light"
    assert result["complexity"] == "light"
    assert result["agent"] == "secretary"


def test_explicit_specialist_agent_routes_persona_without_name(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    from app.ai_lab import domain_agents
    called = {}

    def fake_answer(agent_id, message, **kwargs):
        called["agent_id"] = agent_id
        return {
            "reply": "Никита на связи.", "model": "gemini-x", "provider": "gemini",
            "complexity": "standard",
            "agent": {"id": "nikita", "name": "Никита", "title": "AI-новостной аналитик", "page": "news.html"},
        }

    monkeypatch.setattr(domain_agents, "answer", fake_answer)

    result = chief_agent.handle_message("Что там по рынку?", agent="nikita", mirror_to_telegram=False)

    assert called["agent_id"] == "nikita"
    assert result["domain_agent"] == "nikita"
    assert result["message"]["agent_name"] == "Никита"


def test_chart_command_routes_to_ivan_even_with_management_tier(tmp_path, monkeypatch) -> None:
    """Regression: a chart command (снимок/линия) must reach the chart operator
    Иван even when a model-strength tier (Секретарь/Заместитель/Управляющий) is
    selected. Previously picking a tier set ``requested_agent`` and suppressed
    the chart handoff, so the orchestrator wrongly refused with "нет функции"."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    from app.ai_lab import domain_agents
    from app import market_data
    captured = {}
    monkeypatch.setattr(market_data, "chart_runtime_status", lambda *a, **k: {"ready": True})
    monkeypatch.setattr(market_data, "render_chart_snapshot", lambda *a, **k: (_ for _ in ()).throw(
        market_data.MarketDataError("canvas fallback")))
    monkeypatch.setattr(market_data, "enqueue_chart_command",
                            lambda cmd: captured.update({"cmd": cmd}) or {"command": cmd})
    # The orchestrator LLM must never be consulted for a chart command.
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("chart command must not reach the orchestrator LLM")))

    for tier in ("secretary", "deputy", "manager"):
        captured.clear()
        result = chief_agent.handle_message(
            "сделай скриншот золота", agent=tier, conversation_id="default", mirror_to_telegram=False,
        )
        assert result["domain_agent"] == "ivan", f"tier={tier} must route to Иван"
        assert captured["cmd"]["type"] == "snapshot"
        assert captured["cmd"]["instrument"] == "MGC"


def test_chart_command_routes_to_ivan_in_auto_mode(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    from app import market_data
    captured = {}
    monkeypatch.setattr(market_data, "chart_runtime_status", lambda *a, **k: {"ready": True})
    monkeypatch.setattr(market_data, "render_chart_snapshot", lambda *a, **k: (_ for _ in ()).throw(
        market_data.MarketDataError("canvas fallback")))
    monkeypatch.setattr(market_data, "enqueue_chart_command",
                        lambda cmd: captured.update({"cmd": cmd}) or {"command": cmd})
    result = chief_agent.handle_message("сделай снимок MNQ", mirror_to_telegram=False)
    assert result["domain_agent"] == "ivan"
    assert captured["cmd"]["type"] == "snapshot" and captured["cmd"]["instrument"] == "MNQ"


def test_auto_mode_routes_reports_news_and_backtest_by_capability(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    from app.ai_lab import capability_map, domain_agents

    expected = {
        "пришли финансовый отчёт за месяц": ("accounting_report", "marina"),
        "покажи статус стратегий": ("strategy_report", "tolik"),
        "последние новости": ("news_report", "nikita"),
        "запусти бэктест MNQ": ("start_backtest", "tolik"),
    }
    called = []

    def fake_execute(name, message, **kwargs):
        called.append(name)
        agent_id = expected[message][1]
        profile = domain_agents.PERSONAS[agent_id]
        return {
            "ok": True, "reply": f"Выполнено: {name}",
            "model": "capability dispatcher", "provider": "local", "complexity": "light",
            "agent": {key: profile[key] for key in ("id", "name", "title", "page")},
            "actions": [{"name": name, "status": "completed"}],
        }

    monkeypatch.setattr(capability_map, "execute", fake_execute)
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("known capability must not reach the orchestrator LLM")))

    for message, (capability, agent_id) in expected.items():
        result = chief_agent.handle_message(message, mirror_to_telegram=False)
        assert result["domain_agent"] == agent_id
        assert result["actions"][0]["status"] == "completed"
        assert "нет полномочий" not in result["reply"].lower()
        assert called[-1] == capability

    # Even a deliberately misaddressed operational request is handed to the
    # capability owner instead of being refused by the selected persona.
    result = chief_agent.handle_message(
        "запусти бэктест MNQ", agent="marina", mirror_to_telegram=False,
    )
    assert result["domain_agent"] == "tolik"
    assert called[-1] == "start_backtest"


def test_chart_show_rule_is_saved_deterministically(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    saved = []
    monkeypatch.setattr(chief_agent, "add_note",
                        lambda text, priority="normal": saved.append((text, priority)) or {"ts_utc": "now"})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("explicit permanent rule must not depend on an LLM")))

    result = chief_agent.handle_message(
        "запомни: всегда, когда я говорю покажи график, делай снимок и пришли в чат",
        mirror_to_telegram=False,
    )

    assert result["actions"][0]["name"] == "save_rule"
    assert result["actions"][0]["status"] == "completed"
    assert saved and saved[0][1] == "high"
    assert "всегда означает реальный снимок" in result["reply"]


def test_legacy_telegram_transcript_migrates_into_scoped_chat(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    scope = {"user_id": 42, "workspace_id": "ws_owner", "membership_role": "owner", "is_owner": True}
    cid = "C-SCOPE-MERGE"
    chief_agent._append_conversation(
        "user", "из Telegram", source="telegram",
        path=chief_agent._conversation_file(cid),
    )
    chief_agent._append_conversation(
        "user", "из приложения", source="app",
        path=chief_agent._conversation_file(cid, scope=scope), scope=scope,
    )

    first = chief_agent.migrate_legacy_conversation_to_scope(cid, scope)
    second = chief_agent.migrate_legacy_conversation_to_scope(cid, scope)
    rows = chief_agent._read_conversation(10, path=chief_agent._conversation_file(cid, scope=scope))

    assert first["migrated"] == 1
    assert second["migrated"] == 0
    assert {row["content"] for row in rows} == {"из Telegram", "из приложения"}
    assert all(row.get("conversation_scope_id") == "u42__ws_owner" for row in rows)


def test_owner_workspace_restores_complete_legacy_chat_list_once(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    scope = {
        "user_id": 42, "workspace_id": "ws_owner", "membership_role": "owner",
        "is_owner": True, "uses_owner_runtime": True,
    }
    chief_agent._append_conversation(
        "assistant", "старый основной отчёт", source="app",
        path=chief_agent._conversation_file(chief_agent.DEFAULT_CONVERSATION_ID),
    )
    legacy = chief_agent.create_conversation(
        "Старый диалог", conversation_id="C-LEGACY-OWNER",
    )
    chief_agent._append_conversation(
        "user", "старое поручение", source="app",
        path=chief_agent._conversation_file(legacy["conversation_id"]),
    )
    current = chief_agent.create_conversation(
        "Новый scoped диалог", conversation_id="C-SCOPED-OWNER", scope=scope,
    )
    chief_agent._append_conversation(
        "user", "новое поручение", source="app",
        path=chief_agent._conversation_file(current["conversation_id"], scope=scope),
        scope=scope,
    )

    first = chief_agent.list_conversations(scope=scope)
    second = chief_agent.list_conversations(scope=scope)
    ids = {row["conversation_id"] for row in first}
    default_messages = chief_agent.conversation_messages(
        chief_agent.DEFAULT_CONVERSATION_ID, scope=scope,
    )
    legacy_messages = chief_agent.conversation_messages("C-LEGACY-OWNER", scope=scope)

    assert ids == {chief_agent.DEFAULT_CONVERSATION_ID, "C-LEGACY-OWNER", "C-SCOPED-OWNER"}
    assert next(row for row in first if row["conversation_id"] == "C-LEGACY-OWNER")["title"] == "Старый диалог"
    assert [row["content"] for row in default_messages] == ["старый основной отчёт"]
    assert [row["content"] for row in legacy_messages] == ["старое поручение"]
    assert len(second) == len(first)
    assert len(chief_agent.conversation_messages("C-LEGACY-OWNER", scope=scope)) == 1
    marker = chief_agent._read_index(scope)[chief_agent._OWNER_LEGACY_MIGRATION_KEY]
    assert marker["completed"] is True


def test_non_owner_workspace_never_inherits_owner_legacy_chats(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    chief_agent.create_conversation("Личный чат владельца", conversation_id="C-OWNER-ONLY")
    scope = {
        "user_id": 77, "workspace_id": "ws_tenant", "membership_role": "member",
        "is_owner": False, "uses_owner_runtime": False,
    }

    rows = chief_agent.list_conversations(scope=scope)

    assert {row["conversation_id"] for row in rows} == {chief_agent.DEFAULT_CONVERSATION_ID}
    assert chief_agent._OWNER_LEGACY_MIGRATION_KEY not in chief_agent._read_index(scope)


def test_system_chat_cannot_be_closed_and_is_always_pinned(tmp_path, monkeypatch) -> None:
    """The main/system chat holds service reports: it can never be closed and is
    always pinned at the top so it stays reachable."""
    _isolate(tmp_path, monkeypatch)
    # Closing the default chat is refused.
    try:
        chief_agent.set_conversation_closed(chief_agent.DEFAULT_CONVERSATION_ID, True)
    except chief_agent.ChiefAgentError as exc:
        assert "нельзя закрыть" in str(exc)
    else:
        raise AssertionError("the system chat must not be closable")
    # It never reports itself as closed and stays usable.
    assert chief_agent._conversation_is_closed(chief_agent.DEFAULT_CONVERSATION_ID) is False
    # Unpinning is a no-op: it remains pinned.
    chief_agent.pin_conversation(chief_agent.DEFAULT_CONVERSATION_ID, False)
    rows = chief_agent.list_conversations()
    default_row = next(r for r in rows if r.get("is_default"))
    assert default_row["pinned"] is True and default_row["closed"] is False
    assert rows[0].get("is_default"), "the system chat must float to the top"


def test_orchestrator_blocks_unknown_model_action(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Попытка","confidence":0.99,"doubts":[],"actions":[{"name":"edit_source_code","arguments":{},"reason":"bad"}]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })

    result = chief_agent.handle_message("Перепиши код", mirror_to_telegram=False)

    assert result["actions"][0]["status"] == "blocked"
    assert result["actions"][0]["reason"] == "capability_not_allowed"


def test_unknown_model_label_routes_supported_owner_capability(tmp_path, monkeypatch) -> None:
    """An invented model label must not block an operation the app supports."""
    _isolate(tmp_path, monkeypatch)
    from app.ai_lab import capability_map

    monkeypatch.setattr(capability_map, "execute", lambda name, message, **kwargs: {
        "ok": True,
        "reply": "Финансовый отчёт подготовлен.",
        "actions": [{"name": name, "status": "completed"}],
    })

    result = chief_agent._execute_action(
        {"name": "make_finance_packet", "arguments": {}},
        "пришли финансовый отчёт",
    )

    assert result["name"] == "accounting_report"
    assert result["requested_action"] == "make_finance_packet"
    assert result["status"] == "completed"
    assert "Финансовый отчёт подготовлен" in result["summary"]


def test_orchestrator_redacts_accidentally_pasted_secret(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    captured = {}
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda _role, prompt, **kwargs: captured.update({"prompt": prompt}) or {
        "content": '{"reply":"Ключ скрыт.","confidence":1,"doubts":[],"actions":[]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })
    secret = "sk-this-is-a-real-looking-secret-123456"

    chief_agent.handle_message(f"проверь {secret}", mirror_to_telegram=False)

    assert secret not in captured["prompt"]
    assert secret not in chief_agent._conversation_path().read_text(encoding="utf-8")


def test_orchestrator_does_not_reuse_previous_research_action_for_lm_command(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Запускаю.","confidence":0.99,"doubts":[],"actions":[{"name":"start_research","arguments":{"target_roots":["MNQ"]},"reason":"wrong context carry-over"}]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })

    result = chief_agent.handle_message(
        "Если LM Studio недоступна, запусти её", mirror_to_telegram=False,
    )

    assert result["actions"][0]["status"] == "blocked"
    assert result["actions"][0]["reason"] == "current_message_does_not_authorize_action"


def test_strategy_question_is_discussion_only_even_if_model_requests_start(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {"recent_experiments": []})
    monkeypatch.setattr(chief_agent, "_manager_strategy_context", lambda _msg: {"source_files_read": ["lessons.md"]})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": _complete_strategy_reply(),
        "provider": "deepseek", "actual_model": "deepseek-v4-pro",
    })
    monkeypatch.setattr(chief_agent, "start_mission", lambda _args: (_ for _ in ()).throw(
        AssertionError("discussion must not start research")
    ))

    result = chief_agent.handle_message(
        "Какую стратегию в этот раз разработаешь? Что можешь предложить?",
        mirror_to_telegram=False,
    )

    assert result["actions"] == []
    assert "VWAP" in result["reply"]
    assert result["complexity"] == "critical"
    assert result["model"] == "deepseek-v4-pro"


def test_strategy_discussion_uses_strong_lane_and_research_packet(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {
        "north_star": {"target_usd": 100000}, "research_mission": None,
        "lm_studio": {"run_allowed": True},
    })
    monkeypatch.setattr(chief_agent, "_manager_strategy_context", lambda _msg: {
        "source_files_read": ["ai_lessons/LESSONS_SUMMARY.md"],
        "reference_results": [{"id": "WEX-007", "pf_after_commission": "0.914"}],
    })
    captured = {}

    def invoke(role, prompt, **kwargs):
        captured.update({"role": role, "prompt": prompt, **kwargs})
        return {
            "content": _complete_strategy_reply(), "provider": "deepseek",
            "actual_model": "deepseek-v4-pro",
        }

    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", invoke)

    result = chief_agent.handle_message(
        "Какую стратегию предложишь исходя из наших документов и исследований?",
        mirror_to_telegram=False,
    )

    assert captured["role"] == "chief_agent"
    assert captured["complexity"] == "critical"
    assert captured["allow_paid"] is True
    assert "LESSONS_SUMMARY.md" in captured["prompt"]
    assert "WEX-007" in captured["prompt"]
    assert len(result["reply"]) >= 650
    assert result["actions"] == []


def test_incomplete_strategy_discussion_is_replaced_by_second_strong_answer(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent, "_manager_strategy_context", lambda _msg: {})
    calls = []

    def invoke(role, prompt, **kwargs):
        calls.append((role, kwargs.get("purpose")))
        content = "Предложу следующую гипотезу." if len(calls) == 1 else _complete_strategy_reply()
        return {"content": content, "provider": "deepseek", "actual_model": "deepseek-v4-pro"}

    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", invoke)

    result = chief_agent.handle_message(
        "Какую стратегию нам лучше разработать?", mirror_to_telegram=False,
    )

    assert calls == [
        ("chief_agent", "orchestrator_strategic_dialogue"),
        ("final_judge", "orchestrator_strategic_dialogue_repair"),
    ]
    assert result["reply"] == _complete_strategy_reply()


def test_general_discussion_uses_strong_plain_dialogue_without_actions(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {
        "research_mission": None, "recent_experiments": [], "accounts": [],
    })
    reply = (
        "Дмитрий Сергеевич, причина в том, что прежняя схема принимала короткий технический ответ за завершённое "
        "управленческое решение. Факт: проверка полноты отсутствовала. Предлагаю разделить обсуждение и исполнение: "
        "сначала дать вывод, основания и варианты, затем дождаться вашей команды. Альтернатива — оставить единый "
        "маршрут, но он снова будет смешивать разговор с запуском. Следующий шаг после вашего подтверждения — "
        "применить раздельную маршрутизацию и проверить её на реальном диалоге."
    )
    captured = {}
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda role, prompt, **kwargs: (
        captured.update({"role": role, **kwargs}) or {
            "content": reply, "provider": "deepseek", "actual_model": "deepseek-v4-pro",
        }
    ))

    result = chief_agent.handle_message(
        "Почему этот подход не работает и как лучше его перестроить?",
        mirror_to_telegram=False,
    )

    assert captured["role"] == "chief_agent"
    assert captured["complexity"] == "critical"
    assert result["reply"] == reply
    assert result["actions"] == []


def test_simple_status_question_stays_deterministic(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("simple status question must not spend model tokens")
    ))

    result = chief_agent.handle_message("Всё работает?", mirror_to_telegram=False)

    assert result["model"] == "deterministic dispatcher"
    assert result["actions"] == []


def test_short_start_approval_can_continue_previous_strategy_dialogue() -> None:
    assert chief_agent._action_grounded_in_message("start_research", "Начинай") is True
    assert chief_agent._extract_root("Основная рекомендация MGC; MNQ ниже") == "MGC"


def test_short_start_approval_executes_plan_from_same_conversation(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    chief_agent._append_conversation(
        "assistant",
        "Основная рекомендация — стратегия отката для MGC. MNQ и MES являются альтернативами.",
        source="app",
    )
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("approved concrete plan should not require another planning call")
    ))
    monkeypatch.setattr(chief_agent, "_kick_mission_start", lambda: None)
    monkeypatch.setattr(chief_agent, "_lm_status_snapshot", lambda: {"run_allowed": True})
    started = []
    monkeypatch.setattr(chief_agent, "start_mission", lambda args: started.append(args) or {
        "mission_id": "M1", "ends_at_utc": None, "target_roots": args["target_roots"],
        "allow_local_models": args["allow_local_models"],
    })

    result = chief_agent.handle_message("Начинай", mirror_to_telegram=False)

    assert result["model"] == "deterministic dispatcher"
    assert result["actions"][0]["status"] == "completed"
    assert started[0]["target_roots"] == ["MGC"]
    assert started[0]["strategy_count_per_cycle"] == 1
    assert started[0]["iterations_per_strategy"] == chief_agent.DEFAULT_STRATEGY_ITERATIONS


def test_start_research_forces_local_model_unless_current_message_opts_out(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_kick_mission_start", lambda: None)
    monkeypatch.setattr(chief_agent, "_lm_status_snapshot", lambda: {"run_allowed": True})
    started = []
    monkeypatch.setattr(chief_agent, "start_mission", lambda args: started.append(args) or {
        "mission_id": "M1", "ends_at_utc": None, "target_roots": ["MNQ"],
        "allow_local_models": args["allow_local_models"],
    })
    action = {"name": "start_research", "arguments": {"allow_local_models": False}}

    chief_agent._execute_action(action, "Начинай разработку стратегии MNQ")

    assert started[0]["allow_local_models"] is True


def test_bounded_mission_completes_after_requested_cycle_count(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)
    mission = chief_agent.start_mission({
        "target_root": "MNQ", "duration_hours": 24, "max_cycles": 1,
        "strategy_count_per_cycle": 1, "paid_budget_usd": 0,
    })
    doc = chief_agent._load()
    doc["mission"]["cycles_started"] = 1
    chief_agent._save(doc)
    completed = []
    monkeypatch.setattr(chief_agent, "_complete_mission", lambda value, reason: completed.append((value, reason)))

    chief_agent._mission_tick()

    assert completed[0][1] == "requested_cycles_completed"


def test_active_mission_cannot_be_silently_overwritten(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)
    chief_agent.start_mission({"target_root": "MNQ"})

    try:
        chief_agent.start_mission({"target_root": "MGC"})
    except chief_agent.ChiefAgentError as exc:
        assert "уже активна" in str(exc)
    else:
        raise AssertionError("active mission must not be overwritten")


def test_zero_paid_budget_is_propagated_to_research_router(tmp_path, monkeypatch) -> None:
    from app.ai_lab import lm_studio

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)
    monkeypatch.setattr(lm_studio, "lm_status", lambda allow_probe=False: {"run_allowed": True})
    started = []
    monkeypatch.setattr(chief_agent.runner, "start", lambda args: started.append(args) or {"run_id": "R1"})
    chief_agent.start_mission({
        "target_root": "MNQ", "duration_hours": 1, "paid_budget_usd": 0,
        "strategy_count_per_cycle": 1,
    })

    chief_agent._mission_tick()

    assert started[0]["allow_paid_agents"] is False


def test_mission_retries_lm_studio_before_any_research_fallback(tmp_path, monkeypatch) -> None:
    from app.ai_lab import bootstrap, lm_studio

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)
    monkeypatch.setattr(lm_studio, "lm_status", lambda allow_probe=False: {"run_allowed": False})
    attempts = []
    monkeypatch.setattr(bootstrap, "start", lambda **kwargs: attempts.append(kwargs) or {
        "readiness": {"run_allowed": False, "message_ru": "server unavailable"},
    })
    started = []
    monkeypatch.setattr(chief_agent.runner, "start", lambda args: started.append(args) or {"experiment_id": "EXP-1"})
    monkeypatch.setattr(chief_agent, "_post_mission_update", lambda *args, **kwargs: None)
    chief_agent.start_mission({"target_root": "MNQ", "duration_hours": 1, "paid_budget_usd": 0})

    chief_agent._mission_tick()
    chief_agent._mission_tick()
    assert started == []
    chief_agent._mission_tick()

    assert len(attempts) == 3
    assert started[0]["allow_template_fallback"] is True
    assert chief_agent._load()["mission"]["local_model_fallback_authorized"] is True


def test_connection_loss_without_active_strategies_uses_light_tier(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(
        chief_agent, "_maybe_auto_reconnect_connection",
        lambda payload: {"attempted": False, "reason": "test_stub"},
    )
    monkeypatch.setattr(
        chief_agent.agent_router, "invoke_role",
        lambda *args, **kwargs: captured.update(kwargs) or {
            "content": "Проверьте соединение.", "provider": "gemini",
            "actual_model": "gemini-2.5-flash", "cost_usd": 0,
        },
    )

    chief_agent.analyze_event(
        "connection_lost", {"heartbeat_age_sec": 90, "enabled_strategies": 0},
        send_telegram=False,
    )

    assert captured["complexity"] == "light"


def test_auto_reconnect_helper_uses_cooldown(tmp_path, monkeypatch) -> None:
    from app import runtime as runtime_mod

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_runtime_reconnect_accounts", lambda: [{
        "account_name": "DEMO3369390",
        "account_mode": "demo",
        "connection_status": "Disconnected",
        "_connected": False,
        "_has_enabled_strategy": True,
    }])
    command_rows = []
    monkeypatch.setattr(runtime_mod, "read_commands", lambda limit=200: list(command_rows))
    monkeypatch.setattr(runtime_mod, "read_command_results", lambda limit=500: [])
    monkeypatch.setattr(runtime_mod, "read_heartbeat", lambda: {"present": True, "fresh": True})
    monkeypatch.setattr(
        chief_agent,
        "_queue_runtime_reconnect",
        lambda account_name="", **kwargs: command_rows.append({
            "command": "reconnect_account",
            "account_name": account_name or "DEMO3369390",
            "timestamp_utc": chief_agent._now(),
        }) or {
            "account_name": account_name or "DEMO3369390",
            "command_id": "cmd-reconnect-1",
            "state": "waiting_for_bridge",
        },
    )

    first = chief_agent._maybe_auto_reconnect_connection({"enabled_strategies": 1})
    second = chief_agent._maybe_auto_reconnect_connection({"enabled_strategies": 1})

    assert first["queued"] is True
    assert second["attempted"] is False
    assert second["reason"] == "cooldown"


def test_auto_reconnect_requires_actual_realtime_strategy(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_runtime_reconnect_accounts", lambda: [{
        "account_name": "DEMO3369390",
        "account_mode": "demo",
        "connection_status": "Disconnected",
        "_connected": False,
        "_has_enabled_strategy": False,
    }])
    monkeypatch.setattr(
        chief_agent, "_queue_runtime_reconnect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("historical research must never reconnect an account")
        ),
    )

    result = chief_agent._maybe_auto_reconnect_connection({"enabled_strategies": 8})

    assert result == {
        "attempted": False,
        "reason": "no_active_realtime_paper_strategy",
    }
    assert chief_agent._active_runtime_strategy({
        "enabled": True, "state": "Historical",
    }) is False
    assert chief_agent._active_runtime_strategy({
        "enabled": True, "state": "Configure",
    }) is False
    assert chief_agent._active_runtime_strategy({
        "enabled": True, "state": "Realtime",
    }) is True


def test_auto_reconnect_does_not_queue_when_bridge_heartbeat_is_stale(tmp_path, monkeypatch) -> None:
    from app import runtime as runtime_mod

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_runtime_reconnect_accounts", lambda: [{
        "account_name": "DEMO3369390",
        "account_mode": "demo",
        "connection_status": "Disconnected",
        "_connected": False,
        "_has_enabled_strategy": True,
    }])
    monkeypatch.setattr(runtime_mod, "read_heartbeat", lambda: {
        "present": True, "fresh": False, "age_sec": 600,
    })
    monkeypatch.setattr(
        chief_agent, "_queue_runtime_reconnect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("offline bridge must not receive queued reconnects")
        ),
    )

    result = chief_agent._maybe_auto_reconnect_connection({"enabled_strategies": 1})

    assert result["attempted"] is False
    assert result["reason"] == "bridge_offline_or_stale"


def test_auto_reconnect_does_not_repeat_terminal_failure_every_five_minutes(tmp_path, monkeypatch) -> None:
    from app import runtime as runtime_mod

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_runtime_reconnect_accounts", lambda: [{
        "account_name": "Backtest", "account_mode": "paper",
        "connection_status": "Disconnected", "_connected": False,
        "_has_enabled_strategy": True,
    }])
    now = chief_agent._now()
    monkeypatch.setattr(runtime_mod, "read_commands", lambda limit=200: [{
        "command": "reconnect_account", "command_id": "cmd-1",
        "account_name": "Backtest", "timestamp_utc": now,
    }])
    monkeypatch.setattr(runtime_mod, "read_command_results", lambda limit=500: [{
        "command_id": "cmd-1", "status": "rejected", "timestamp_utc": now,
    }])
    monkeypatch.setattr(runtime_mod, "read_heartbeat", lambda: {"present": True, "fresh": True})
    monkeypatch.setattr(chief_agent, "AUTO_RECONNECT_COOLDOWN_SEC", 0)
    monkeypatch.setattr(chief_agent, "_queue_runtime_reconnect", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("terminal failure must not be immediately retried")
    ))

    result = chief_agent._maybe_auto_reconnect_connection({"enabled_strategies": 1})

    assert result["attempted"] is False
    assert result["reason"] == "previous_attempt_failed"


def test_runtime_reconnect_accounts_exclude_system_accounts(tmp_path, monkeypatch) -> None:
    from app import ops, runtime as runtime_mod

    _isolate(tmp_path, monkeypatch)
    rdir = tmp_path / "data" / "runtime"
    rdir.mkdir(parents=True)
    accounts = {
        "accounts": [
            {"account_name": "Backtest", "account_mode": "paper", "connection_status": "Disconnected"},
            {"account_name": "Sim101", "account_mode": "paper", "connection_status": "Connected"},
            {"account_name": "DEMO3369390", "account_mode": "demo", "connection_status": "Connected"},
        ]
    }
    (rdir / "accounts.json").write_text(
        __import__("json").dumps(accounts), encoding="utf-8",
    )
    monkeypatch.setattr(ops, "_project_root", lambda: tmp_path)
    names = [row["account_name"] for row in chief_agent._runtime_reconnect_accounts()]
    assert names == ["DEMO3369390"]
    assert "Backtest" not in names
    assert "Sim101" not in names


def test_auto_reconnect_skips_disconnected_account_without_realtime_strategy(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_runtime_reconnect_accounts", lambda: [
        {
            "account_name": "DEMO3369390", "account_mode": "demo",
            "connection_status": "Connected", "_connected": True,
            "_has_enabled_strategy": False,
        },
        {
            "account_name": "Playback101", "account_mode": "playback",
            "connection_status": "Disconnected", "_connected": False,
            "_has_enabled_strategy": False,
        },
    ])
    monkeypatch.setattr(
        chief_agent, "_queue_runtime_reconnect",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not queue")),
    )

    result = chief_agent._maybe_auto_reconnect_connection({"enabled_strategies": 0})

    assert result["attempted"] is False
    assert result["reason"] == "no_active_realtime_paper_strategy"


def test_failed_mission_archives_only_its_sandbox_sources(tmp_path, monkeypatch) -> None:
    from app.ai_lab import compile_pipeline

    _isolate(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    experiment = {
        "experiment_id": "EXP-20260702-0001", "ai_cell_id": "AI-CELL-MNQ-001",
        "lab_namespace": "AI_SANDBOX", "class_name": "FailedSandbox", "target_root": "MNQ",
        "created_at_utc": now, "status": "rejected", "analysis": {},
        "compile": {"last_status": "ok"},
        "verdict": {"outcome": "reject", "rejection_code": "NO_EDGE", "reasons": ["no edge"]},
    }
    monkeypatch.setattr(chief_agent.registry, "list_experiments", lambda limit=1000: [experiment])
    monkeypatch.setattr(chief_agent.registry, "read_experiment", lambda _eid: dict(experiment))
    saved = []
    monkeypatch.setattr(chief_agent.registry, "write_experiment", lambda row: saved.append(dict(row)))
    monkeypatch.setattr(compile_pipeline, "quarantine_source", lambda **kwargs: {
        "ok": True, "quarantine_path": str(tmp_path / "archive" / "FailedSandbox.cs"),
    })
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": "Миссия завершена, исходник перенесён в архив.",
        "actual_model": "gemini-2.5-flash", "provider": "gemini", "cost_usd": 0,
    })
    monkeypatch.setattr(chief_agent, "_append_conversation", lambda *args, **kwargs: {})

    chief_agent._complete_mission({
        "mission_id": "M1", "started_at_utc": now, "target_roots": ["MNQ"],
        "cycles_started": 1, "paid_spend_at_start_usd": 0, "paid_budget_usd": 0,
    }, "deadline_reached")

    assert saved[-1]["status"] == "archived"
    assert saved[-1]["status_before_archive"] == "rejected"
    assert saved[-1]["failed_mission_cleanup"]["ok"] is True


def test_simple_operational_commands_use_cheapest_tier() -> None:
    # Pressing a button / launching a quick or template strategy is a simple
    # dispatch for the orchestrator, so it must route to the cheap tier even
    # though the text mentions "strategy".
    assert chief_agent.classify_complexity("Разработай простую стратегию максимально быстро", "orchestrator") == "light"
    assert chief_agent.classify_complexity("запусти цикл", "orchestrator") == "light"
    assert chief_agent.classify_complexity("покажи отчёт", "orchestrator") == "light"
    # Genuine deep reasoning still uses the powerful tier.
    assert chief_agent.classify_complexity("обоснуй методологию walk-forward для портфеля", "orchestrator") == "critical"
    assert chief_agent.classify_complexity(
        "Какую стратегию предложишь исходя из наших исследований?", "orchestrator",
    ) == "critical"
    assert chief_agent.classify_complexity(
        "Давай разработаем стратегию на основании документов", "orchestrator",
    ) == "critical"


def test_quick_simple_strategy_request_is_executed_not_refused(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)
    monkeypatch.setattr(chief_agent, "_kick_mission_start", lambda: None)

    def _no_llm(*args, **kwargs):
        raise AssertionError("a simple quick-strategy request must not call an LLM")
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", _no_llm)

    result = chief_agent.handle_message(
        "Разработай простую стратегию максимально быстро. Даю тебе 5 минут.",
        mirror_to_telegram=False,
    )

    assert result["actions"][0]["name"] == "start_research"
    assert result["actions"][0]["status"] == "completed"
    mission = chief_agent._load()["mission"]
    assert mission["strategy_count_per_cycle"] == 1
    assert mission["iterations_per_strategy"] == 1
    assert mission["max_cycles"] == 1
    start = datetime.fromisoformat(mission["started_at_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(mission["ends_at_utc"].replace("Z", "+00:00"))
    assert 4 * 60 <= (end - start).total_seconds() <= 6 * 60


def test_mission_supports_short_minute_deadline(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)

    mission = chief_agent.start_mission({"target_root": "MNQ", "duration_minutes": 5})

    start = datetime.fromisoformat(mission["started_at_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(mission["ends_at_utc"].replace("Z", "+00:00"))
    assert 4 * 60 <= (end - start).total_seconds() <= 6 * 60


def test_conversations_keep_isolated_context(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    convs = tmp_path / "convs"
    monkeypatch.setattr(chief_agent, "_conversations_index_path", lambda: tmp_path / "conv_index.json")
    monkeypatch.setattr(chief_agent, "_conversations_dir", lambda: (convs.mkdir(parents=True, exist_ok=True) or convs))
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"принято","confidence":1,"doubts":[],"actions":[]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })

    cid_a = chief_agent.create_conversation("Стратегия А")["conversation_id"]
    cid_b = chief_agent.create_conversation("Идея Б")["conversation_id"]
    chief_agent.handle_message("контекст только для А", conversation_id=cid_a, mirror_to_telegram=False)
    chief_agent.handle_message("контекст только для Б", conversation_id=cid_b, mirror_to_telegram=False)

    msgs_a = chief_agent.conversation_messages(cid_a)
    msgs_b = chief_agent.conversation_messages(cid_b)
    assert any("контекст только для А" in row["content"] for row in msgs_a)
    assert not any("контекст только для А" in row["content"] for row in msgs_b)
    assert any("контекст только для Б" in row["content"] for row in msgs_b)
    titles = {row["conversation_id"]: row["title"] for row in chief_agent.list_conversations()}
    assert titles[cid_a] == "Стратегия А"


def test_new_conversation_title_is_fixed_by_first_owner_request(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    _isolate_conversations(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"принято","confidence":1,"doubts":[],"actions":[]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })
    synced = []
    monkeypatch.setattr(
        chief_agent, "_sync_telegram_topic_title_async",
        lambda conversation_id, title: synced.append((conversation_id, title)),
    )

    conversation = chief_agent.create_conversation()
    cid = conversation["conversation_id"]
    assert conversation["title"] == "Новый чат"
    assert synced == []  # no Telegram topic with a placeholder name

    first = "Проверь поток сообщений между приложением и Telegram"
    chief_agent.handle_message(first, conversation_id=cid, mirror_to_telegram=False)
    chief_agent.handle_message("Это второе сообщение не должно менять название", conversation_id=cid,
                               mirror_to_telegram=False)

    saved = next(row for row in chief_agent.list_conversations() if row["conversation_id"] == cid)
    expected = chief_agent._title_from_message(first)
    assert saved["title"] == expected
    assert saved["auto_title"] is False
    assert saved["title_source"] == "first_request"
    assert synced == [(cid, expected)]


def test_listing_repairs_legacy_rolling_title_and_telegram_topic(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    _isolate_conversations(tmp_path, monkeypatch)
    synced = []
    monkeypatch.setattr(
        chief_agent, "_sync_telegram_topic_title_async",
        lambda conversation_id, title: synced.append((conversation_id, title)),
    )
    conversation = chief_agent.create_conversation()
    cid = conversation["conversation_id"]
    path = chief_agent._conversation_file(cid)
    first = "Первый запрос задаёт постоянное название"
    chief_agent._append_conversation("user", first, source="app", path=path)
    chief_agent._append_conversation("user", "Последнее сообщение не является названием", source="app", path=path)

    saved = next(row for row in chief_agent.list_conversations() if row["conversation_id"] == cid)

    expected = chief_agent._title_from_message(first)
    assert saved["title"] == expected
    assert saved["auto_title"] is False
    assert synced == [(cid, expected)]
    chief_agent.list_conversations()
    assert synced == [(cid, expected)]  # migration and remote rename run once


def _isolate_conversations(tmp_path, monkeypatch):
    convs = tmp_path / "convs"
    monkeypatch.setattr(chief_agent, "_conversations_index_path", lambda: tmp_path / "conv_index.json")
    monkeypatch.setattr(chief_agent, "_conversations_dir", lambda: (convs.mkdir(parents=True, exist_ok=True) or convs))


def test_ensure_local_models_is_not_blocked_by_grounding(tmp_path, monkeypatch) -> None:
    from app.ai_lab import bootstrap, lm_studio

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent, "_manager_strategy_context", lambda _msg: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Готовлю окружение.","confidence":0.9,"doubts":[],"actions":[{"name":"ensure_local_models","arguments":{},"reason":"self-heal"}]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })
    monkeypatch.setattr(bootstrap, "start", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(lm_studio, "lm_status", lambda allow_probe=False: {
        "available": True, "ready": False, "run_allowed": False, "message_ru": "up",
    })

    # An explicit execution command does not need to mention LM Studio; its
    # dependency self-heal must still run. Collaborative "давай разработаем"
    # wording is intentionally discussion-only and is covered separately.
    result = chief_agent.handle_message(
        "Разработай стратегию согласно исследованиям", mirror_to_telegram=False,
    )
    ensure = [row for row in result["actions"] if row["name"] == "ensure_local_models"]
    assert ensure and ensure[0]["status"] == "completed"
    assert "current_message_does_not_authorize_action" not in str(result["actions"])


def test_start_research_records_conversation_and_reports_launch(tmp_path, monkeypatch) -> None:
    from app.ai_lab import lm_studio

    _isolate(tmp_path, monkeypatch)
    _isolate_conversations(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)
    monkeypatch.setattr(chief_agent, "_kick_mission_start", lambda: None)
    monkeypatch.setattr(lm_studio, "lm_status", lambda allow_probe=False: {
        "available": False, "ready": False, "run_allowed": False,
    })

    result = chief_agent.handle_message(
        "Разработай простую стратегию быстро", conversation_id="C-TEST", mirror_to_telegram=False,
    )

    assert result["actions"][0]["name"] == "start_research"
    assert result["actions"][0]["status"] == "completed"
    assert "работу запустил" in result["reply"]
    assert "цикл" not in result["reply"].lower()
    assert "модел" not in result["reply"].lower()
    mission = chief_agent._load()["mission"]
    assert mission["conversation_id"] == "C-TEST"


def test_ok_launch_approves_previous_plan_and_resumes_matching_mission(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    chief_agent.create_conversation("MGC completion", conversation_id="C-MGC")
    chief_agent._append_conversation(
        "assistant",
        "План: продолжить стратегию MGC и получить итоговый бэктест. Подтвердите — сразу запущу.",
        source="test", path=chief_agent._conversation_file("C-MGC"),
    )
    chief_agent._save({"mission": {
        "mission_id": "M-MGC", "status": "stopped", "control_revision": 4,
        "target_roots": ["MGC"], "goal": "VWAP Pullback MGC",
        "active_strategy_experiment_id": "EXP-CANCELLED", "conversation_id": "C-MGC",
    }})
    monkeypatch.setattr(chief_agent, "_kick_mission_start", lambda: None)
    monkeypatch.setattr(
        chief_agent.agent_router, "invoke_role",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("follow-up approval must be deterministic")),
    )

    result = chief_agent.handle_message(
        "ок запускай", conversation_id="C-MGC", agent="tolik", mirror_to_telegram=False,
    )

    assert result["model"] == "deterministic dispatcher"
    assert result["actions"] == [{
        "name": "resume_research", "status": "completed", "mission_status": "active",
    }]
    assert chief_agent._load()["mission"]["status"] == "active"
    assert "Не выполнено" not in result["reply"]
    conversation = next(row for row in chief_agent.list_conversations() if row["conversation_id"] == "C-MGC")
    assert conversation["work_state"] == "in_progress"


def test_cancelled_experiment_is_cleared_without_false_rejection_report(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    mission = {
        "mission_id": "M1", "status": "active", "control_revision": 2,
        "active_strategy_experiment_id": "EXP-CANCELLED",
        "active_strategy_started_at_utc": "2026-07-03T18:00:00Z",
    }
    chief_agent._save({"mission": mission})
    monkeypatch.setattr(chief_agent.registry, "read_experiment", lambda _eid: {
        "experiment_id": "EXP-CANCELLED", "status": "cancelled",
    })
    monkeypatch.setattr(chief_agent.registry, "is_terminal", lambda status: status == "cancelled")
    monkeypatch.setattr(
        chief_agent, "_post_mission_update",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cancel is not a rejection result")),
    )

    updated = chief_agent._report_completed_strategy(dict(mission))

    assert updated["active_strategy_experiment_id"] == ""
    assert updated["cancelled_experiment_ids"] == ["EXP-CANCELLED"]


def test_conversation_can_close_reopen_and_reject_messages_while_closed(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    chief_agent.create_conversation("Finished", conversation_id="C-DONE")
    chief_agent._set_conversation_work_state("C-DONE", "completed", "Готово")

    closed = chief_agent.set_conversation_closed("C-DONE", True)

    assert closed["closed"] is True
    try:
        chief_agent.handle_message("новое сообщение", conversation_id="C-DONE", mirror_to_telegram=False)
    except chief_agent.ChiefAgentError as exc:
        assert "Тема закрыта" in str(exc)
    else:
        raise AssertionError("closed conversation must reject new messages")
    reopened = chief_agent.set_conversation_closed("C-DONE", False)
    assert reopened["closed"] is False
    assert reopened["work_state"] == "open"


def test_continuous_profit_request_focuses_one_strategy_and_stays_quiet(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)
    monkeypatch.setattr(chief_agent, "_kick_mission_start", lambda: None)
    monkeypatch.setattr(
        chief_agent.agent_router, "invoke_role",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("deterministic dispatch expected")),
    )

    result = chief_agent.handle_message(
        "Разрабатывай прибыльную стратегию MNQ до конца без ограничений, пока я не скажу остановись",
        mirror_to_telegram=False,
    )

    mission = chief_agent._load()["mission"]
    assert mission["until_stopped"] is True
    assert mission["ends_at_utc"] is None
    assert mission["strategy_count_per_cycle"] == 1
    assert mission["iterations_per_strategy"] == chief_agent.DEFAULT_STRATEGY_ITERATIONS
    assert mission["notification_policy"] == "result_only"
    assert "MISSION-" not in result["reply"]
    assert "цикл" not in result["reply"].lower()


def test_conditional_stop_with_typo_starts_instead_of_stopping(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: None)
    monkeypatch.setattr(chief_agent.runner, "current", lambda: None)
    monkeypatch.setattr(chief_agent, "_kick_mission_start", lambda: None)
    monkeypatch.setattr(
        chief_agent.agent_router, "invoke_role",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("conditional stop is a deterministic start command")
        ),
    )

    result = chief_agent.handle_message(
        "Начинай и усовершенствуй каждую стратегию. С каждым разом лучше и лучше. "
        "До тех пор, пока мисси я не скажу, остановись.",
        mirror_to_telegram=False,
    )

    mission = chief_agent._load()["mission"]
    assert mission["status"] == "active"
    assert mission["until_stopped"] is True
    assert result["actions"][0]["name"] == "start_research"
    assert chief_agent._stop_requested("стоп, остановись") is True


def test_stop_intent_requires_an_immediate_command_not_a_keyword() -> None:
    assert chief_agent._stop_requested("Остановись прямо сейчас") is True
    assert chief_agent._stop_requested("Прекрати работу") is True
    assert chief_agent._stop_requested("Работай, пока я не скажу остановись. А сейчас остановись") is True
    assert chief_agent._stop_requested("Продолжай и остановись в 11:00") is False
    assert chief_agent._stop_requested("Остановись через 15 минут") is False
    assert chief_agent._stop_requested("Остановись потом") is False
    assert chief_agent._stop_requested("Не останавливайся") is False
    assert chief_agent._stop_requested("Если я скажу остановись, тогда завершай") is False
    assert chief_agent._stop_requested("В предложении было слово «остановись»") is False
    assert chief_agent._stop_requested("Почему ты остановился?") is False


def test_scheduled_stop_keeps_active_mission_running_until_owner_time(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    fixed_utc = datetime(2026, 7, 3, 17, 45, tzinfo=timezone.utc)
    fixed_pt = fixed_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    monkeypatch.setattr(chief_agent, "_now_dt", lambda: fixed_utc)
    monkeypatch.setattr(chief_agent, "_pt_now", lambda: fixed_pt)
    monkeypatch.setattr(
        chief_agent.agent_router, "invoke_role",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scheduled stop is deterministic")),
    )
    chief_agent._save({"mission": {
        "mission_id": "M-SCHEDULED", "status": "active", "control_revision": 2,
        "target_roots": ["MGC"], "until_stopped": True, "ends_at_utc": None,
    }})

    result = chief_agent.handle_message(
        "Хорошо продолжай и остановись в 11:00. Через 15 минут я проверю, что получилось, пришлёшь отчёт.",
        mirror_to_telegram=False,
    )

    mission = chief_agent._load()["mission"]
    assert result["model"] == "deterministic dispatcher"
    assert result["actions"][0]["name"] == "schedule_research_stop"
    assert result["actions"][0]["status"] == "completed"
    assert mission["status"] == "active"
    assert mission["until_stopped"] is False
    assert mission["ends_at_utc"] == "2026-07-03T18:00:00Z"
    assert "11:00" in result["reply"]


def test_announce_chart_task_opens_conversation_with_owner_and_ivan(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    conv = chief_agent.create_conversation("Иван · MNQ · цель")
    cid = conv["conversation_id"]

    out = chief_agent.announce_chart_task(
        conversation_id=cid, instruction="Ваня, следи за 21500 на MNQ 60 минут и пришли снимок",
        agent_id="ivan", instrument="MNQ", price=21500, drawing_type="line", label="цель",
        duration_minutes=60, report_mode="both", action="snapshot", mirror_to_telegram=False,
    )

    assert out["ok"] and out["conversation_id"] == cid
    rows = chief_agent._read_conversation(50, path=chief_agent._conversation_file(cid))
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["content"].startswith("Ваня")
    assert rows[1]["agent_name"] == "Иван"
    assert "MNQ" in rows[1]["content"] and "снимок" in rows[1]["content"].lower()


def test_announce_chart_task_generates_instruction_when_note_blank(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    conv = chief_agent.create_conversation("Иван · MES · снимок")
    cid = conv["conversation_id"]

    chief_agent.announce_chart_task(
        conversation_id=cid, instruction="", agent_id="ivan", instrument="MES",
        price=5000, delay_seconds=60, action="snapshot", mirror_to_telegram=False,
    )

    rows = chief_agent._read_conversation(50, path=chief_agent._conversation_file(cid))
    assert rows[0]["role"] == "user" and "MES" in rows[0]["content"]
    assert "через" in rows[1]["content"].lower()


def test_explicit_agent_name_is_preserved_and_generic_reply_defaults_to_vitek(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    path = chief_agent._conversation_file("C-PUBLIC-ACTOR")

    row = chief_agent._append_conversation(
        "assistant", "Отчёт профильного агента", source="agent",
        agent_name="Марина", path=path,
    )

    assert row["agent_name"] == "Марина"
    generic = chief_agent._append_conversation(
        "assistant", "Общий управленческий ответ", source="agent", path=path,
    )
    assert generic["agent_name"] == "Витёк"


def test_model_cannot_turn_ambiguous_future_stop_into_immediate_stop(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": (
            '{"reply":"Останавливаю.","confidence":0.99,"doubts":[],'
            '"actions":[{"name":"stop_research","arguments":{},"reason":"bad keyword match"}]}'
        ),
        "provider": "test", "actual_model": "test-model",
    })
    chief_agent._save({"mission": {
        "mission_id": "M-ACTIVE", "status": "active", "control_revision": 1,
        "target_roots": ["MNQ"],
    }})

    result = chief_agent.handle_message("Продолжай, а остановись потом", mirror_to_telegram=False)

    assert result["actions"][0]["name"] == "stop_research"
    assert result["actions"][0]["status"] == "blocked"
    assert result["actions"][0]["reason"] == "current_message_does_not_authorize_action"
    assert chief_agent._load()["mission"]["status"] == "active"


def test_stop_is_deterministic_and_cancels_every_future_start(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent.runner, "run_status", lambda: {"run_id": "RUN-1"})
    monkeypatch.setattr(chief_agent.runner, "current", lambda: {"run_id": "RUN-1"})
    cancelled = []
    monkeypatch.setattr(chief_agent.runner, "request_run_cancel", lambda run_id=None: cancelled.append(run_id) or {"ok": True})
    monkeypatch.setattr(
        chief_agent.agent_router, "invoke_role",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stop must not call a model")),
    )
    chief_agent._save({"mission": {
        "mission_id": "M1", "status": "active", "control_revision": 4,
        "target_roots": ["MNQ"],
    }, "pending_mission": {"target_roots": ["MGC"]}})

    result = chief_agent.handle_message("Стоп, остановись", mirror_to_telegram=False)

    saved = chief_agent._load()
    assert saved["mission"]["status"] == "stopped"
    assert saved["mission"]["control_revision"] == 5
    assert "pending_mission" not in saved
    assert cancelled == ["RUN-1"]
    assert "останавливаю" in result["reply"].lower()


def test_stale_mission_copy_cannot_resurrect_stopped_state(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    mission = {
        "mission_id": "M1", "status": "active", "control_revision": 2,
        "target_roots": ["MNQ"],
    }
    chief_agent._save({"mission": mission})
    stale = dict(mission)
    chief_agent.set_mission_state("stop")

    assert chief_agent._mission_control_is_current(stale) is False


def test_strategy_report_contains_evidence_not_internal_orchestration(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    exp = {
        "experiment_id": "EXP-1", "class_name": "MNQTest", "status": "rejected",
        "current_iteration": 4,
        "verdict": {"outcome": "reject", "rejection_code": "SMOKE_NO_EDGE", "reasons": ["edge failed after costs"]},
        "backtests": [{"trades": 19, "net_after_commission": -125.6, "pf_after_commission": 0.325}],
    }
    text = chief_agent._strategy_result_text({"active_strategy_started_at_utc": now}, exp)

    assert "19" in text and "$-125.60" in text and "0.325" in text
    assert "стратегия отклонена" in text.lower()
    assert "mission" not in text.lower()
    assert "цикл" not in text.lower()


def test_completed_strategy_report_is_claimed_once_across_stale_ticks(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    mission = {
        "mission_id": "M1", "status": "active", "control_revision": 1,
        "active_strategy_experiment_id": "EXP-1", "reported_experiment_ids": [],
    }
    chief_agent._save({"mission": mission})
    exp = {
        "experiment_id": "EXP-1", "class_name": "MNQTest", "status": "rejected",
        "verdict": {"outcome": "reject", "rejection_code": "SMOKE_NO_EDGE"},
        "model_chain": [{"selected_model": "openai/gpt-oss-20b"}],
    }
    monkeypatch.setattr(chief_agent.registry, "read_experiment", lambda _eid: exp)
    sent = []
    monkeypatch.setattr(chief_agent, "_post_mission_update", lambda *args, **kwargs: sent.append(kwargs))

    chief_agent._report_completed_strategy(dict(mission))
    chief_agent._report_completed_strategy(dict(mission))

    assert len(sent) == 1
    saved = chief_agent._load()["mission"]
    assert saved["reported_experiment_ids"] == ["EXP-1"]
    assert saved["last_strategy_model"] == "openai/gpt-oss-20b"


def test_owner_address_varies_and_is_deterministic_by_seed() -> None:
    # Same seed always renders the same address (keeps rendered reports stable);
    # across many seeds more than one form is used (no monotonous spam).
    assert chief_agent._owner_address("MNQTest") == chief_agent._owner_address("MNQTest")
    forms = {chief_agent._owner_address(f"seed-{i}") for i in range(40)}
    assert forms.issubset(set(chief_agent._OWNER_ADDRESSES))
    assert len(forms) > 1
    # The vocative-less "вы" form capitalizes the sentence instead of prefixing.
    seed_plain = next(f"seed-{i}" for i in range(500) if chief_agent._owner_address(f"seed-{i}") == "")
    assert chief_agent._greet("проверил MNQ.", seed=seed_plain) == "Проверил MNQ."


def test_repeated_identical_rejections_are_suppressed_then_escalate(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    mission = {"mission_id": "M1", "status": "active", "control_revision": 1,
               "reported_experiment_ids": []}

    def _rejected(exp_id: str) -> dict:
        return {
            "experiment_id": exp_id, "class_name": exp_id, "status": "rejected",
            "family": "trend_pullback",
            "verdict": {"outcome": "reject", "rejection_code": "OVERTRADING_RISK"},
        }

    experiments = {eid: _rejected(eid) for eid in ("E1", "E2", "E3")}
    monkeypatch.setattr(chief_agent.registry, "read_experiment", lambda eid: experiments.get(eid))

    posts: list = []
    monkeypatch.setattr(
        chief_agent, "_post_mission_update",
        lambda mission, text, **kw: posts.append((kw.get("action_name"), kw.get("notify_telegram"), text)),
    )

    for eid in ("E1", "E2", "E3"):
        mission["active_strategy_experiment_id"] = eid
        chief_agent._save({"mission": mission})
        mission = chief_agent._report_completed_strategy(mission)

    routine = [p for p in posts if p[0] == "strategy_result"]
    escalations = [p for p in posts if p[0] == "approach_change"]
    # First repeat pushes to Telegram once; further identical repeats are muted.
    assert [notify for _name, notify, _text in routine] == [True, False, False]
    # The third identical failure triggers exactly one escalation message.
    assert len(escalations) == 1
    assert escalations[0][1] is True
    saved = chief_agent._load()["mission"]
    assert saved.get("approach_escalation", {}).get("active") is True
    assert saved["approach_escalation"]["family"] == "trend_pullback"


def test_new_rejection_reason_is_reported_again(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    mission = {"mission_id": "M1", "status": "active", "control_revision": 1,
               "reported_experiment_ids": []}
    experiments = {
        "E1": {"experiment_id": "E1", "class_name": "E1", "status": "rejected",
               "family": "trend_pullback",
               "verdict": {"outcome": "reject", "rejection_code": "OVERTRADING_RISK"}},
        "E2": {"experiment_id": "E2", "class_name": "E2", "status": "rejected",
               "family": "trend_pullback",
               "verdict": {"outcome": "reject", "rejection_code": "SMOKE_ZERO_TRADES"}},
    }
    monkeypatch.setattr(chief_agent.registry, "read_experiment", lambda eid: experiments.get(eid))
    posts: list = []
    monkeypatch.setattr(
        chief_agent, "_post_mission_update",
        lambda mission, text, **kw: posts.append((kw.get("action_name"), kw.get("notify_telegram"))),
    )

    for eid in ("E1", "E2"):
        mission["active_strategy_experiment_id"] = eid
        chief_agent._save({"mission": mission})
        mission = chief_agent._report_completed_strategy(mission)

    # A different rejection reason is genuinely new information → pushed again.
    assert [notify for name, notify in posts if name == "strategy_result"] == [True, True]


def test_pin_conversation_floats_to_top(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    _isolate_conversations(tmp_path, monkeypatch)
    cid_a = chief_agent.create_conversation("A")["conversation_id"]
    cid_b = chief_agent.create_conversation("B")["conversation_id"]

    chief_agent.pin_conversation(cid_a, True)

    order = [row["conversation_id"] for row in chief_agent.list_conversations()]
    # The system chat is always pinned at the very top; a pinned user chat floats
    # above other user chats but below the system chat.
    assert order[0] == chief_agent.DEFAULT_CONVERSATION_ID
    assert order[1] == cid_a
    assert order.index(cid_a) < order.index(cid_b)


def test_scoped_default_conversations_do_not_share_history(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Дмитрий Сергеевич, готово.","confidence":0.9,"doubts":[],"actions":[]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })
    scope_a = {
        "user_id": 101, "workspace_id": "ws_personal_AAAAAAAA",
        "membership_role": "owner", "display_name": "Alice",
        "is_owner": False,
    }
    scope_b = {
        "user_id": 202, "workspace_id": "ws_personal_BBBBBBBB",
        "membership_role": "owner", "display_name": "Bob",
        "is_owner": False,
    }

    chief_agent.handle_message("одинаковый текст", conversation_id="default",
                               mirror_to_telegram=False, scope=scope_a)
    chief_agent.handle_message("одинаковый текст", conversation_id="default",
                               mirror_to_telegram=False, scope=scope_b)

    history_a = chief_agent.conversation_messages("default", scope=scope_a)
    history_b = chief_agent.conversation_messages("default", scope=scope_b)
    legacy = chief_agent._read_conversation(10)

    assert [row["user_id"] for row in history_a] == [101, 101]
    assert [row["workspace_id"] for row in history_a] == ["ws_personal_AAAAAAAA"] * 2
    assert history_a[-1]["content"] == "Готово."
    assert [row["user_id"] for row in history_b] == [202, 202]
    assert [row["workspace_id"] for row in history_b] == ["ws_personal_BBBBBBBB"] * 2
    assert legacy == []


def test_non_owner_prompt_snapshot_hides_owner_control_plane_data() -> None:
    snapshot = {
        "recent_experiments": [
            {"experiment_id": "OWNER", "workspace_id": "ws_owner_training_12345678"},
            {"experiment_id": "MINE", "workspace_id": "ws_personal_AAAAAAAA"},
        ],
        "research_mission": {"mission_id": "OWNER-MISSION", "conversation_scope": {"workspace_id": "ws_owner_training_12345678"}},
        "agents": [{"agent_id": "paid", "remaining_monthly_budget_usd": 50}],
        "owner_rules": [{"text": "private"}],
        "north_star": {"configured": True, "target": "private"},
        "open_tasks": [{"task_id": "A", "workspace_id": "ws_owner_training_12345678"}],
        "pending_proposals": [{"proposal_id": "P", "workspace_id": "ws_owner_training_12345678"}],
    }
    scope = {"user_id": 101, "workspace_id": "ws_personal_AAAAAAAA", "is_owner": False}

    scoped = chief_agent._scope_application_snapshot(snapshot, scope)

    assert [row["experiment_id"] for row in scoped["recent_experiments"]] == ["MINE"]
    assert scoped["research_mission"] is None
    assert scoped["agents"] == [] and scoped["owner_rules"] == []
    assert scoped["open_tasks"] == [] and scoped["pending_proposals"] == []


def test_viewer_cannot_mutate_owner_training_workspace(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    from app.ai_lab import capability_map

    monkeypatch.setattr(capability_map, "execute", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("read-only workspace must be denied before dispatch")
    ))
    scope = {
        "user_id": 202,
        "workspace_id": "ws_owner_training_12345678",
        "workspace_kind": "owner_training",
        "uses_owner_runtime": True,
        "membership_role": "viewer",
        "is_owner": False,
    }

    result = chief_agent.handle_message(
        "поставь линию на MNQ 21500", mirror_to_telegram=False, scope=scope,
    )

    assert result["ok"] is False
    assert result["actions"] == [{
        "name": "chart_draw", "status": "blocked", "reason": "workspace_role_read_only",
    }]
    assert "только для просмотра" in result["reply"]


def test_native_thinking_is_not_mirrored_to_telegram(tmp_path, monkeypatch) -> None:
    """Native reasoning is shown in the app chat + stored in history, but only
    the final reply is mirrored to Telegram — the thinking channel never is."""
    from app import telegram_service

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    secret_thinking = "СКРЫТОЕ_РАЗМЫШЛЕНИЕ_модели_шаг_за_шагом"
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Итоговый ответ владельцу.","confidence":0.2,"doubts":[],"actions":[]}',
        "provider": "deepseek", "actual_model": "deepseek-v4-pro",
        "reasoning": secret_thinking,
    })
    sent = []
    monkeypatch.setattr(telegram_service, "send_chief_report",
                        lambda *args, **kwargs: sent.append((args, kwargs)))

    result = chief_agent.handle_message("Как дела?", agent="manager", mirror_to_telegram=True)

    # The reasoning is returned to the app and persisted for the chat history…
    assert result["thinking"] == secret_thinking
    stored = chief_agent._conversation_path().read_text(encoding="utf-8")
    assert secret_thinking in stored
    # …but Telegram received only the final reply, never the thinking.
    assert sent, "Telegram mirror should have been called"
    telegram_payload = repr(sent)
    assert secret_thinking not in telegram_payload
    assert "Итоговый ответ владельцу." in telegram_payload


def test_handle_message_streams_thinking_to_callback(tmp_path, monkeypatch) -> None:
    """handle_message forwards its on_thinking callback down to the model layer
    so the SSE endpoint receives live reasoning deltas."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})

    def fake_invoke_role(role, prompt, **kwargs):
        cb = kwargs.get("on_reasoning")
        if cb:
            cb("думаю… ")
            cb("почти готово")
        return {
            "content": '{"reply":"Готово.","confidence":0.2,"doubts":[],"actions":[]}',
            "provider": "deepseek", "actual_model": "deepseek-v4-pro",
            "reasoning": "думаю… почти готово",
        }

    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", fake_invoke_role)
    deltas = []

    result = chief_agent.handle_message(
        "Как дела?", agent="manager", mirror_to_telegram=False,
        on_thinking=deltas.append,
    )

    assert deltas == ["думаю… ", "почти готово"]
    assert result["thinking"] == "думаю… почти готово"


def test_orchestrator_is_single_gateway_to_vitek_in_app_and_telegram(tmp_path, monkeypatch) -> None:
    from app import vitek

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(vitek, "_state_path", lambda: tmp_path / "vitek.json")
    monkeypatch.setattr(vitek, "_service_marker_path", lambda: tmp_path / "vitek-background.json")
    with vitek._LOCK:
        doc = vitek._read()
        incident, _ = vitek._record_incident(
            doc, category="financial_classification", key="open", severity="warning",
            title="Открытая проверка", details="x", recommendation="решить",
            context={"needs_review": 1},
        )
        vitek._write(doc)
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Vitek status must not call an LLM")
    ))

    for source, phrase in (
        ("app", "витя какие задания отсались у тебя на сеголня?"),
        ("telegram", "Витёк, что осталось?"),
    ):
        result = chief_agent.handle_message(
            phrase, source=source, mirror_to_telegram=False,
            conversation_id=f"C-VITEK-{source}",
        )
        assert result["domain_agent"] == "vitek"
        assert result["agent"] == "vitek"
        assert result["gateway"] == {
            "ingress": "stratforge_orchestrator", "source": source,
            "target": "vitek", "outcome": "awaiting_owner", "single_response": True,
        }
        assert "активных поручений сейчас нет" in result["reply"]
        assert "финансов" in result["reply"].lower()
        assert incident["incident_id"] not in result["reply"]
        assert result["message"]["agent_name"] == "Витёк"


def test_orchestrator_gateway_blocks_vitek_owner_state_for_non_owner(tmp_path, monkeypatch) -> None:
    from app import vitek

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(vitek, "_state_path", lambda: tmp_path / "vitek.json")
    monkeypatch.setattr(vitek, "_service_marker_path", lambda: tmp_path / "vitek-background.json")
    with vitek._LOCK:
        doc = vitek._read()
        incident, _ = vitek._record_incident(
            doc, category="private", key="owner", severity="critical",
            title="Секрет владельца", details="x", recommendation="x",
        )
        vitek._write(doc)
    scope = {
        "user_id": 22, "workspace_id": "ws-shared", "membership_role": "viewer",
        "is_owner": False, "display_name": "Viewer", "uses_owner_runtime": True,
    }

    result = chief_agent.handle_message(
        "Витя, покажи нерешённые задачи", mirror_to_telegram=False,
        conversation_id="C-VITEK-NONOWNER", scope=scope,
    )

    assert result["domain_agent"] == "vitek"
    assert result["gateway"]["outcome"] == "blocked"
    assert "не могу показывать вам личные задачи" in result["reply"]
    assert incident["incident_id"] not in result["reply"]


def test_every_orchestrator_turn_has_auditable_gateway_metadata(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Понял вопрос.","confidence":0.9,"doubts":[],"actions":[]}',
        "provider": "test", "actual_model": "test-model",
    })

    result = chief_agent.handle_message("Обычный вопрос без имени агента", mirror_to_telegram=False)

    assert result["gateway"]["ingress"] == "stratforge_orchestrator"
    assert result["gateway"]["target"] == "orchestrator"
    assert result["gateway"]["outcome"] == "answered"
    assert result["gateway"]["single_response"] is True
