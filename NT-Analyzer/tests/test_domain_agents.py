from __future__ import annotations

import json

from app import account_ledger
from app.ai_lab import chief_agent, domain_agents


def test_named_personas_require_explicit_address() -> None:
    assert domain_agents.resolve_persona("Марина, отчёт за неделю")["id"] == "marina"
    assert domain_agents.resolve_persona("Толик, что по стратегиям?")["id"] == "tolik"
    assert domain_agents.resolve_persona("В стратегии нужна финансовая проверка") is None
    assert domain_agents.resolve_persona("любой текст", "marina")["name"] == "Марина"
    assert domain_agents.resolve_persona("Никита, что произошло на рынке?")["id"] == "nikita"


def test_chart_operator_ivan_addressing_and_intent() -> None:
    assert domain_agents.resolve_persona("Иван, поставь линию на MNQ 21500")["id"] == "ivan"
    assert domain_agents.resolve_persona("любой текст", "ivan")["name"] == "Иван"

    intent = domain_agents.parse_chart_intent(
        "поставь линию на MNQ 21500, если дойдёт за 60 минут сделай снимок и отчитайся")
    assert intent["action"] == "draw"
    assert intent["root"] == "MNQ"
    assert intent["price"] == 21500.0
    assert intent["duration_minutes"] == 60
    assert intent["rule"] == "snapshot"
    assert intent["report_mode"] == "both"

    assert domain_agents.parse_chart_intent("сделай снимок нэсдак")["action"] == "snapshot"
    assert domain_agents.parse_chart_intent("убери отметки с MES")["action"] == "clear"
    down = domain_agents.parse_chart_intent("поставь стрелку вниз на золото 4200")
    assert down["type"] == "arrow_down" and down["root"] == "MGC"


def test_chart_operator_answer_enqueues_command(monkeypatch) -> None:
    from app import market_data

    captured = {}
    monkeypatch.setattr(market_data, "enqueue_chart_command",
                        lambda cmd: captured.setdefault("cmd", cmd) or {"command": cmd})
    out = domain_agents.chart_operator_answer(
        "поставь линию на MNQ 21500 если дойдёт за 60 минут снимок в чат",
        conversation_id="c-42")
    assert out["ok"] and out["agent"]["id"] == "ivan"
    assert "draw" in out["actions"]
    cmd = captured["cmd"]
    assert cmd["type"] == "draw" and cmd["instrument"] == "MNQ"
    assert cmd["conversation_id"] == "c-42"
    assert cmd["payload"]["drawing"]["price"] == 21500.0
    assert cmd["payload"]["drawing"]["snapshot"] is True


def test_chart_operator_delayed_snapshot_and_active_chart(monkeypatch) -> None:
    from app import market_data

    # "через минуту" → delayed snapshot of the active (unnamed) chart.
    it = domain_agents.parse_chart_intent("Пришли снимок графика через минуту")
    assert it["action"] == "snapshot" and it["root"] == "" and it["delay_seconds"] == 60

    it2 = domain_agents.parse_chart_intent("сделай снимок MES через 30 секунд")
    assert it2["action"] == "snapshot" and it2["root"] == "MES" and it2["delay_seconds"] == 30
    assert it2.get("price") is None

    assert domain_agents.parse_chart_intent("открой график золото")["action"] == "open"

    captured = {}
    monkeypatch.setattr(market_data, "enqueue_chart_command",
                        lambda cmd: captured.setdefault("cmd", cmd) or {"command": cmd})
    out = domain_agents.chart_operator_answer("Пришли снимок графика через минуту", conversation_id="cX")
    assert "snapshot" in out["actions"]
    assert captured["cmd"]["type"] == "snapshot"
    assert captured["cmd"]["instrument"] == ""       # active chart
    assert captured["cmd"]["delay_seconds"] == 60
    assert captured["cmd"]["conversation_id"] == "cX"


def test_persona_diminutive_aliases_resolve() -> None:
    assert domain_agents.resolve_persona("Ваня, поставь линию на MNQ 21500")["id"] == "ivan"
    assert domain_agents.resolve_persona("Вань, сделай снимок MES")["id"] == "ivan"
    assert domain_agents.resolve_persona("Толя, что по стратегиям?")["id"] == "tolik"
    assert domain_agents.resolve_persona("Марин, сверь комиссии")["id"] == "marina"
    assert domain_agents.resolve_persona("Никит, что на рынке?")["id"] == "nikita"


def test_chart_command_persona_is_conservative() -> None:
    assert domain_agents.chart_command_persona("поставь линию на MNQ 21500") == "ivan"
    assert domain_agents.chart_command_persona("сделай снимок нэсдак") == "ivan"
    assert domain_agents.chart_command_persona("убери отметки с графиков") == "ivan"
    # A bare number / account id is not a chart command (must not hijack ops).
    assert domain_agents.chart_command_persona("включи моделирование на DEMO3369390") == ""
    assert domain_agents.chart_command_persona("посчитай прибыль за месяц") == ""


def test_specialist_handoff_routes_to_responsible_agent() -> None:
    # A chart command addressed to the accountant is handled by the chart operator.
    assert domain_agents.route_specialist("marina", "поставь линию на MNQ 21500") == ("ivan", "marina")
    # An accounting request addressed to the chart operator goes to the accountant.
    assert domain_agents.route_specialist("ivan", "сверь комиссии за месяц") == ("marina", "ivan")
    # A request that touches the addressed agent's own domain stays with them.
    assert domain_agents.route_specialist("ivan", "поставь линию на MNQ 21500") == ("ivan", "")
    assert domain_agents.route_specialist("marina", "посчитай прибыль и комиссии") == ("marina", "")
    # No clear domain signal keeps the addressed agent.
    assert domain_agents.route_specialist("tolik", "как дела?") == ("tolik", "")


def test_answer_hands_off_chart_command_to_ivan(monkeypatch) -> None:
    from app import market_data

    captured = {}
    monkeypatch.setattr(market_data, "enqueue_chart_command",
                        lambda cmd: captured.setdefault("cmd", cmd) or {"command": cmd})
    out = domain_agents.answer("marina", "поставь линию на MNQ 21500 сделай снимок в чат",
                               conversation_id="cZ")
    assert out["agent"]["id"] == "ivan"
    assert out["handoff_from"] == "marina"
    assert out["reply"].startswith("Дмитрий Сергеевич, это не Марина")
    assert captured["cmd"]["instrument"] == "MNQ"


def test_chart_task_acknowledgement_describes_schedule() -> None:
    ack = domain_agents.chart_task_acknowledgement(
        instrument="MNQ", price=21500, drawing_type="line", label="цель",
        duration_minutes=60, report_mode="both", action="snapshot")
    assert "MNQ" in ack and "21500" in ack
    assert "снимок" in ack.lower()
    delayed = domain_agents.chart_task_acknowledgement(
        instrument="MES", price=5000, delay_seconds=60, action="snapshot")
    assert "через" in delayed.lower()


def test_time_alert_and_snapshot_gallery(tmp_path, monkeypatch) -> None:
    import base64
    import time as _time
    from app import market_data as md

    monkeypatch.setattr(md, "_runtime_dir", lambda: tmp_path)

    # time-based alert triggers on the clock, not on price.
    alert = md.create_alert({"instrument": "MNQ", "timeframe": "5m", "price": 25000, "type": "point",
                             "trigger": "time", "delay_seconds": 1, "action": "snapshot",
                             "report_mode": "touch", "conversation_id": "c1", "label": "t"})["alert"]
    assert alert["trigger"] == "time" and alert["due_at_utc"]
    _time.sleep(1.2)
    triggered = md.evaluate_alerts()
    assert any(t["id"] == alert["id"] for t in triggered)

    # snapshot gallery: save → list → favorite → survives clear → delete.
    png = base64.b64encode(bytes([137, 80, 78, 71, 13, 10, 26, 10] + [0] * 32)).decode()
    saved = md.save_snapshot("data:image/png;base64," + png,
                             meta={"instrument": "MNQ", "timeframe": "5m", "outcome": "manual"})
    sid = saved["id"]
    assert md.list_snapshots()["total"] == 1
    md.update_snapshot(sid, favorite=True, pattern="голова и плечи")
    listing = md.list_snapshots()
    assert listing["snapshots"][0]["favorite"] is True
    assert any(p["name"] == "голова и плечи" for p in listing["patterns"])
    md.clear_snapshots(keep_favorites=True)
    assert md.list_snapshots()["total"] == 1     # favorite kept
    md.delete_snapshot(sid)
    assert md.list_snapshots()["total"] == 0



def test_management_tiers_force_model_complexity() -> None:
    assert domain_agents.resolve_management("secretary")["forced_complexity"] == "light"
    assert domain_agents.resolve_management("deputy")["forced_complexity"] == "standard"
    assert domain_agents.resolve_management("manager")["forced_complexity"] == "critical"
    assert domain_agents.resolve_management("управляющий")["id"] == "manager"
    # Named specialists and unknown ids are not management tiers.
    assert domain_agents.resolve_management("nikita") is None
    assert domain_agents.resolve_management("") is None
    listing = domain_agents.list_personas()
    assert {row["id"] for row in listing["management"]} == {"secretary", "deputy", "manager"}
    assert all(row["name"] == "" for row in listing["management"])


def test_accounting_snapshot_uses_decimal_authoritative_totals(monkeypatch) -> None:
    monkeypatch.setattr(domain_agents.performance, "build_performance_response", lambda **kwargs: {
        "period": {"from": "2026-07-01", "to": "2026-07-31", "label": "Месяц"},
        "strategy_summary": {"pnl": 0.1 + 0.2, "gross_pnl": 0.4, "commission": 0.1, "trades": 2, "wins": 1, "losses": 1},
        "strategies": [],
    })
    monkeypatch.setattr(domain_agents.account_ledger, "account_history", lambda *args, **kwargs: {
        "accounts": [{"account_name": "SIM", "snapshots": [], "events": [
            {"at_utc": "2026-07-02T00:00:00Z", "kind": "deposit", "amount": 0.1, "classification_status": "classified"},
            {"at_utc": "2026-07-03T00:00:00Z", "kind": "deposit", "amount": 0.2, "classification_status": "classified"},
        ]}]
    })
    monkeypatch.setattr(domain_agents.account_ledger, "audit_integrity", lambda *args, **kwargs: {"issues": [], "repaired": []})

    report = domain_agents.accounting_snapshot("month")

    assert report["calculation_authority"] == "deterministic_decimal_code"
    assert report["summary"]["trading_pnl"] == "0.30"
    assert report["summary"]["deposits"] == "0.30"


def test_ledger_integrity_repairs_only_exact_duplicates(tmp_path, monkeypatch) -> None:
    path = tmp_path / "ledger.json"
    monkeypatch.setattr(account_ledger, "LEDGER_PATH", path)
    path.write_text(json.dumps({
        "schema_version": 1,
        "accounts": {"SIM": {
            "snapshots": [
                {"at_utc": "2026-07-01T00:00:00Z", "source": "runtime", "net_liquidation": 100, "cash_value": 100, "realized_pnl": 0, "unrealized_pnl": 0},
                {"at_utc": "2026-07-01T00:00:00Z", "source": "runtime", "net_liquidation": 100, "cash_value": 100, "realized_pnl": 0, "unrealized_pnl": 0},
            ],
            "events": [
                {"event_id": "E1", "at_utc": "2026-07-01T00:00:00Z", "kind": "deposit", "amount": 10, "source_id": "broker-1", "provenance": "statement", "classification_status": "classified"},
                {"event_id": "E2", "at_utc": "2026-07-01T00:00:00Z", "kind": "deposit", "amount": 10, "source_id": "broker-1", "provenance": "statement", "classification_status": "classified"},
                {"event_id": "E3", "at_utc": "2026-07-02T00:00:00Z", "kind": "fee", "amount": "bad", "classification_status": "classified"},
            ],
        }},
    }), encoding="utf-8")

    report = account_ledger.audit_integrity("SIM", repair_safe=True)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert {row["code"] for row in report["repaired"]} == {"duplicate_snapshot", "duplicate_source_id"}
    assert any(row["code"] == "invalid_amount" and not row["safe_to_repair"] for row in report["issues"])
    assert len(saved["accounts"]["SIM"]["snapshots"]) == 1
    assert [row["event_id"] for row in saved["accounts"]["SIM"]["events"]] == ["E1", "E3"]


def test_domain_answer_reports_selected_model_and_keeps_fact_block(monkeypatch) -> None:
    monkeypatch.setattr(domain_agents, "accounting_snapshot", lambda *args, **kwargs: {
        "summary": {"trading_pnl": "12.34", "commission": "0.56", "trades": 4, "needs_review": 0, "integrity_issues": 0},
    })
    monkeypatch.setattr(domain_agents.agent_router, "invoke_role", lambda *args, **kwargs: {
        "content": "Результат сверки устойчив.", "actual_model": "gemini-test", "provider": "gemini", "cost_usd": 0,
    })

    out = domain_agents.answer("marina", "Марина, отчёт за неделю")

    assert "P&L после комиссий $12.34" in out["reply"]
    assert out["model"] == "gemini-test"
    assert out["agent"]["name"] == "Марина"


def test_orchestrator_dispatches_addressed_domain_agent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(chief_agent, "_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(chief_agent, "_conversation_path", lambda: tmp_path / "conversation.jsonl")
    monkeypatch.setattr(chief_agent, "_conversations_index_path", lambda: tmp_path / "index.json")
    monkeypatch.setattr(chief_agent, "_conversations_dir", lambda: tmp_path)
    monkeypatch.setattr(domain_agents, "answer", lambda *args, **kwargs: {
        "ok": True, "agent": {"id": "tolik", "name": "Толик", "title": "AI-аналитик стратегий", "page": "strategies.html"},
        "reply": "Проверил стратегии.", "model": "deepseek-test", "provider": "deepseek", "complexity": "standard",
    })

    out = chief_agent.handle_message("Толик, что у нас по стратегиям?", mirror_to_telegram=False)

    assert out["domain_agent"] == "tolik"
    assert out["model"] == "deepseek-test"
    assert out["reply"] == "Проверил стратегии."
