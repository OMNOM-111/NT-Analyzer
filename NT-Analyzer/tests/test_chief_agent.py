from __future__ import annotations

from datetime import datetime, timezone

from app.ai_lab import chief_agent


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(chief_agent, "_state_path", lambda: tmp_path / "chief.json")
    monkeypatch.setattr(chief_agent, "_tasks_path", lambda: tmp_path / "tasks.jsonl")
    monkeypatch.setattr(chief_agent, "_reports_dir", lambda: tmp_path)
    monkeypatch.setattr(chief_agent, "_conversation_path", lambda: tmp_path / "conversation.jsonl")
    monkeypatch.setattr(chief_agent, "_usage_stats", lambda agent_id="": {
        "requests": 0, "successful_requests": 0, "input_tokens": 0,
        "cached_input_tokens": 0, "cache_hit_pct": 0, "output_tokens": 0, "cost_usd": 0,
    })


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


def test_connection_loss_without_active_strategies_uses_light_tier(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    captured = {}
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


def _isolate_conversations(tmp_path, monkeypatch):
    convs = tmp_path / "convs"
    monkeypatch.setattr(chief_agent, "_conversations_index_path", lambda: tmp_path / "conv_index.json")
    monkeypatch.setattr(chief_agent, "_conversations_dir", lambda: (convs.mkdir(parents=True, exist_ok=True) or convs))


def test_ensure_local_models_is_not_blocked_by_grounding(tmp_path, monkeypatch) -> None:
    from app.ai_lab import bootstrap, lm_studio

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(chief_agent, "_application_snapshot", lambda: {})
    monkeypatch.setattr(chief_agent.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": '{"reply":"Готовлю окружение.","confidence":0.9,"doubts":[],"actions":[{"name":"ensure_local_models","arguments":{},"reason":"self-heal"}]}',
        "provider": "gemini", "actual_model": "gemini-2.5-flash",
    })
    monkeypatch.setattr(bootstrap, "start", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(lm_studio, "lm_status", lambda allow_probe=False: {
        "available": True, "ready": False, "run_allowed": False, "message_ru": "up",
    })

    # The owner message does NOT mention LM Studio; self-heal must still run.
    result = chief_agent.handle_message(
        "Давай разработаем стратегию согласно исследованиям", mirror_to_telegram=False,
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


def test_pin_conversation_floats_to_top(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    _isolate_conversations(tmp_path, monkeypatch)
    cid_a = chief_agent.create_conversation("A")["conversation_id"]
    cid_b = chief_agent.create_conversation("B")["conversation_id"]

    chief_agent.pin_conversation(cid_a, True)

    order = [row["conversation_id"] for row in chief_agent.list_conversations()]
    assert order[0] == cid_a
    assert order.index(cid_a) < order.index(cid_b)
