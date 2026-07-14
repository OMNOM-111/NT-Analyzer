from __future__ import annotations

from app.ai_lab import capability_map, chief_agent, domain_agents, intent_classifier


def test_intent_classifier_covers_owner_operations() -> None:
    cases = {
        "пришли скрин золота": "chart_snapshot",
        "запусти бэктест MNQ": "start_backtest",
        "пришли финансовый отчёт за месяц": "accounting_report",
        "покажи статус стратегий": "strategy_report",
        "последние новости": "news_report",
        "пришли сводку": "deliver_report",
    }
    for message, expected in cases.items():
        assert intent_classifier.classify(message)["capability"] == expected


def test_capability_map_contains_every_first_class_operation() -> None:
    expected = {
        "chart_snapshot", "chart_draw", "chart_open", "chart_clear",
        "accounting_report", "strategy_report", "news_report",
        "deliver_report", "start_backtest",
    }
    assert expected <= set(capability_map.CAPABILITY_MAP)
    assert all(capability_map.CAPABILITY_MAP[name]["safe"] for name in expected)


def test_capability_chain_dispatches_without_llm(monkeypatch) -> None:
    calls = []

    def fake_answer(agent_id, message, **kwargs):
        calls.append((agent_id, message))
        profile = domain_agents.PERSONAS[agent_id]
        return {
            "ok": True, "reply": f"handled:{agent_id}",
            "model": "deterministic", "provider": "local", "complexity": "light",
            "agent": {key: profile[key] for key in ("id", "name", "title", "page")},
            "actions": [],
        }

    monkeypatch.setattr(domain_agents, "answer", fake_answer)
    for message, agent in (
        ("пришли скрин золота", "ivan"),
        ("пришли финансовый отчёт", "marina"),
        ("покажи статус стратегий", "tolik"),
        ("последние новости", "nikita"),
    ):
        intent = intent_classifier.classify(message)
        result = capability_map.execute(intent["capability"], message, intent=intent)
        assert result["agent"]["id"] == agent
    assert [row[0] for row in calls] == ["ivan", "marina", "tolik", "nikita"]


def test_start_backtest_without_target_requests_only_missing_input(monkeypatch) -> None:
    monkeypatch.setattr(capability_map, "_find_experiment", lambda *args, **kwargs: None)
    intent = intent_classifier.classify("запусти бэктест")
    result = capability_map.execute("start_backtest", "запусти бэктест", intent=intent)
    assert result["needs_input"] is True
    assert result["actions"][0]["status"] == "needs_input"
    assert "не могу" not in result["reply"].lower()


def test_anti_refusal_guard_recovers_known_capability(monkeypatch) -> None:
    monkeypatch.setattr(capability_map, "execute", lambda name, message, **kwargs: {
        "ok": True, "reply": "Отчёт подготовлен.", "capability": name,
    })
    result = capability_map.recover_refusal("пришли финансовый отчёт")
    assert result and result["capability"] == "accounting_report"


def test_short_followup_retries_last_failed_chart_task() -> None:
    history = [
        {"role": "user", "content": "покажи график нефть"},
        {"role": "assistant", "content": "Bridge ещё не передал бары MCL.",
         "actions": [{"name": "chart_snapshot", "status": "blocked"}]},
    ]

    resolved = intent_classifier.resolve_followup("а сейчас?", history)

    assert resolved["capability"] == "chart_snapshot"
    assert resolved["target_root"] == "MCL"
    assert resolved["followup_retry"] is True


def test_classifier_normalizes_mixed_keyboard_futures_symbol() -> None:
    intent = intent_classifier.classify("покажи график 6с")
    assert intent["capability"] == "chart_snapshot"
    assert intent["target_root"] == "6C"
    assert intent["normalized_message"].endswith("6c")


def test_chart_dispatch_does_not_borrow_stale_instrument_from_history(monkeypatch) -> None:
    captured = {}

    def fake_answer(agent_id, message, **kwargs):
        captured.update({"agent_id": agent_id, "message": message})
        return {"ok": True, "reply": "ok", "agent": domain_agents.PERSONAS["ivan"]}

    monkeypatch.setattr(domain_agents, "answer", fake_answer)
    intent = intent_classifier.classify("покажи график 6с")
    capability_map.execute(
        "chart_snapshot", "покажи график 6с", intent=intent,
        history=[{"role": "user", "content": "покажи график MGC"}],
    )
    assert captured["agent_id"] == "ivan"
    assert "6c" in captured["message"].lower()
    assert "mgc" not in captured["message"].lower()


def test_uncertain_natural_command_uses_allowlisted_semantic_resolver(monkeypatch) -> None:
    from app.ai_lab import agent_router
    calls = []
    monkeypatch.setattr(agent_router, "invoke_role", lambda role, prompt, **kwargs: calls.append({
        "role": role, "prompt": prompt, **kwargs,
    }) or {
        "content": '{"capability":"chart_snapshot","target_root":"6C","confidence":0.96}',
        "model": "gpt-4o-mini", "provider": "github_models",
    })

    intent = intent_classifier.resolve_intent("скинь мне картинку по канадцу", [], use_model=True)

    assert intent["capability"] == "chart_snapshot"
    assert intent["target_root"] == "6C"
    assert intent["resolver"] == "semantic_model"
    assert calls and calls[0]["role"] == "telegram_assistant"
    assert calls[0]["allow_paid"] is False
