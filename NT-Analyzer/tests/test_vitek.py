from __future__ import annotations

import json
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

from app import jobqueue, vitek


def _isolate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vitek, "_state_path", lambda: tmp_path / "vitek.json")
    monkeypatch.setattr(vitek, "_service_marker_path", lambda: tmp_path / "background.json")


def test_time_windows_use_locked_parameters_days_and_local_session() -> None:
    profiles = [
        {
            "profile_id": "mgc-a", "name": "MGC Morning", "instrument": "MGC 08-26",
            "status": "ready", "cell_id": "CELL-001", "timeframe": "5 Minute",
            "locked_parameters": {"TradeStartTime": 600, "TradeEndTime": 1000},
        },
        {
            "profile_id": "mgc-b", "name": "MGC Mon Fri", "instrument": "MGC 08-26",
            "status": "paper_ready", "cell_id": "CELL-002", "trade_window_pt": "Mon+Fri 10:00-12:00",
            "locked_parameters": {"TradeStartTime": 1000, "TradeEndTime": 1200, "AllowedWeekdayMask": 17},
        },
        {
            "profile_id": "mgc-old", "name": "Archived", "instrument": "MGC 08-26",
            "status": "archived", "trade_window_pt": "12:00-14:00",
        },
    ]
    registry = {"roots": [{"root": "MGC"}]}

    doc = vitek.build_time_windows(profiles=profiles, registry=registry)
    mgc = doc["roots"][0]

    assert doc["timezone"] == "America/Los_Angeles"
    assert mgc["strategy_count"] == 2
    assert [(row["start"], row["end"]) for row in mgc["strategies"]] == [
        ("06:00", "10:00"), ("10:00", "12:00"),
    ]
    assert mgc["strategies"][0]["start_minute"] == 30 * 60  # 06:00 inside 15:00 -> 14:00 session
    assert mgc["strategies"][1]["days"] == ["mon", "fri"]
    assert [row["day"] for row in mgc["gaps_by_day"]] == ["mon", "tue", "wed", "thu", "fri"]
    monday = next(row for row in mgc["gaps_by_day"] if row["day"] == "mon")
    tuesday = next(row for row in mgc["gaps_by_day"] if row["day"] == "tue")
    assert any(gap["start"] == "12:00" for gap in monday["gaps"])
    assert any(gap["start"] == "10:00" for gap in tuesday["gaps"])


def test_coverage_goal_requires_all_active_slots(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(jobqueue, "project_root", lambda: tmp_path)
    jobqueue.reset_caches()
    profiles_dir = tmp_path / "data" / "profiles"
    catalog_dir = tmp_path / "data" / "catalog"
    portfolio_dir = tmp_path / "data" / "portfolio"
    profiles_dir.mkdir(parents=True)
    catalog_dir.mkdir(parents=True)
    portfolio_dir.mkdir(parents=True)
    profiles = [
        {"profile_id": f"mgc-{index}", "name": f"MGC {index}", "strategy_class": f"Mgc{index}",
         "instrument": "MGC 08-26", "status": "ready", "cell_id": f"CELL-{index:03d}"}
        for index in range(1, 4)
    ]
    (profiles_dir / "strategies.json").write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    (profiles_dir / "instrument_strategy_coverage.json").write_text(json.dumps({
        "summary": {"ready": 1, "in_progress": 0, "total_micros": 1},
        "micros": [{"root": "MGC", "status": "ready", "strategy_count": 8, "best_profile_id": "mgc-1"}],
    }), encoding="utf-8")
    (catalog_dir / "strategies.json").write_text(json.dumps({
        "strategies": [{"class_name": f"Mgc{index}"} for index in range(1, 4)],
    }), encoding="utf-8")
    (portfolio_dir / "cells.json").write_text(json.dumps({
        "cells": [{"root": "MGC", "status": "active", "cell_id": f"CELL-{index:03d}"} for index in range(1, 17)],
    }), encoding="utf-8")

    out = jobqueue.read_instrument_coverage()
    mgc = out["instruments"][0]

    assert mgc["ready_count"] == 3
    assert mgc["target_slots"] == 16
    assert mgc["remaining_slots"] == 13
    assert mgc["best_status"] == "in_progress"
    assert mgc["status_label"] == "В работе"
    assert out["summary"]["ready"] == 0
    assert out["summary"]["approved_slots"] == 3


def test_incident_decision_creates_tracked_task_and_free_state(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vitek, "_maybe_notify_idle", lambda: False)
    with vitek._LOCK:
        doc = vitek._read()
        incident, created = vitek._record_incident(
            doc, category="runtime_error", key="E1", severity="error",
            title="Bridge error", details="failed", recommendation="repair",
        )
        vitek._write(doc)
    assert created is True

    decided = vitek.decide_incident(incident["incident_id"], "create_task", note="проверить лог")
    assert decided["status"] == "in_progress"
    assert decided["task"]["incident_id"] == incident["incident_id"]
    current = vitek.status()
    assert current["mode"] == "awaiting_decision" or current["mode"] == "busy"
    task = decided["task"]
    vitek.update_task(task["task_id"], {"status": "completed", "result": "fixed"}, notify=False)
    vitek.decide_incident(incident["incident_id"], "resolve")
    assert vitek.status()["mode"] == "free"
    assert vitek.status()["message"] == "Активных задач нет. Я свободен."


def test_rest_mode_keeps_explicit_critical_policy(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    rest = vitek.set_rest(duration_minutes=120, reason="owner")
    assert rest["active"] is True
    assert vitek.status()["mode"] == "resting"
    assert "Критические события" in vitek.status()["message"]
    resumed = vitek.resume()
    assert resumed["active"] is False
    assert vitek.status()["mode"] == "free"


def test_day_week_plan_persists_and_creates_tasks(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    plan = vitek.set_plan({
        "scope": "week", "focus": "Золото",
        "goals": ["Проверить MGC", "Закрыть пробел 10-12"],
    })

    current = vitek.status()
    assert plan["scope"] == "week"
    assert len(plan["task_ids"]) == 2
    assert current["plans"]["week"]["focus"] == "Золото"
    assert {row["title"] for row in current["tasks"]} == {"Проверить MGC", "Закрыть пробел 10-12"}
    assert all(row["plan_id"] == plan["plan_id"] for row in current["tasks"])
    assert current["mode"] == "busy"


def test_scan_deduplicates_incidents_and_separates_quality_errors(tmp_path, monkeypatch) -> None:
    from app import account_ledger, runtime
    from app.ai_lab import domain_agents

    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(jobqueue, "read_instrument_coverage", lambda: {
        "summary": {}, "instruments": [{"root": "MGC", "ready_count": 3, "target_slots": 16}],
    })
    monkeypatch.setattr(vitek, "build_time_windows", lambda: {"roots": []})
    monkeypatch.setattr(jobqueue, "read_strategy_profiles", lambda: {"profiles": []})
    monkeypatch.setattr(account_ledger, "account_history", lambda account="", limit=5000: {"accounts": []})
    monkeypatch.setattr(account_ledger, "audit_integrity", lambda account="", repair_safe=False: {
        "issues": [], "requires_review": 0,
    })
    monkeypatch.setattr(runtime, "read_heartbeat", lambda: {"fresh": False, "age_sec": 99})
    monkeypatch.setattr(runtime, "read_strategies_raw", lambda: [{"enabled": True}])
    monkeypatch.setattr(runtime, "read_errors", lambda limit=20: [])
    monkeypatch.setattr(domain_agents, "strategy_snapshot", lambda period="month": {
        "summary": {
            "technical_failures": 2, "quality_warnings": 4,
            "finding_counts": {"technical_failure": 2, "small_trade_sample": 4},
        },
    })
    sent = []
    monkeypatch.setattr(vitek, "_notify_incidents", lambda rows, resting: sent.append(list(rows)) or True)

    first = vitek.scan(notify=False)
    second = vitek.scan(notify=True)
    third = vitek.scan(notify=True)

    assert len(first["new_incidents"]) == 4  # heartbeat, technical, warning, MGC slots
    assert second["new_incidents"] == []
    assert second["notified"] is True
    assert third["new_incidents"] == []
    assert third["notified"] is False
    assert len(sent) == 1
    severities = {row["severity"] for row in vitek.status()["incidents"] if row["status"] in vitek.OPEN_INCIDENT_STATUSES}
    assert {"critical", "error", "warning", "task"}.issubset(severities)


def test_plan_prompt_is_sent_once_per_local_day_and_week(tmp_path, monkeypatch) -> None:
    from app import telegram_service

    _isolate(monkeypatch, tmp_path)
    fixed = datetime(2026, 7, 13, 15, 0, tzinfo=timezone.utc)  # Monday 08:00 Pacific
    monkeypatch.setattr(vitek, "_now_dt", lambda: fixed)
    sent = []
    monkeypatch.setattr(
        telegram_service, "send_chief_report",
        lambda title, lines, **kwargs: sent.append((title, lines, kwargs)) or True,
    )

    assert vitek._maybe_notify_plan_prompt(resting=False) is True
    assert vitek._maybe_notify_plan_prompt(resting=False) is False
    assert len(sent) == 1
    assert "нужен план" in sent[0][0]
    assert any("сегодня" in line for line in sent[0][1])
    assert any("недели" in line for line in sent[0][1])


def test_scan_finds_finance_and_misplaced_archive_issues(tmp_path, monkeypatch) -> None:
    from app import account_ledger, runtime
    from app.ai_lab import domain_agents

    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(jobqueue, "read_instrument_coverage", lambda: {"summary": {}, "instruments": []})
    monkeypatch.setattr(vitek, "build_time_windows", lambda: {"roots": []})
    monkeypatch.setattr(jobqueue, "read_strategy_profiles", lambda: {
        "profiles": [{"profile_id": "P-FAIL", "status": "archived"}],
    })
    monkeypatch.setattr(runtime, "read_heartbeat", lambda: {"fresh": True})
    monkeypatch.setattr(runtime, "read_strategies_raw", lambda: [])
    monkeypatch.setattr(runtime, "read_errors", lambda limit=20: [])
    monkeypatch.setattr(domain_agents, "strategy_snapshot", lambda period="month": {"summary": {}})
    monkeypatch.setattr(account_ledger, "account_history", lambda account="", limit=5000: {
        "accounts": [{"summary": {"needs_review": 2}}],
    })
    monkeypatch.setattr(account_ledger, "audit_integrity", lambda account="", repair_safe=False: {
        "issues": [{"account_name": "Sim101", "code": "duplicate_source_id", "safe_to_repair": False}],
        "requires_review": 1,
    })

    result = vitek.scan(notify=False)
    categories = {row["category"] for row in result["new_incidents"]}

    assert categories == {"strategy_lifecycle", "financial_integrity", "financial_classification"}
    assert result["findings"] == 3


def test_vitek_http_status_windows_and_plan_routes(tmp_path, monkeypatch) -> None:
    from app import server as server_mod

    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(server_mod.account_auth, "auth_required", lambda: False)
    monkeypatch.setattr(vitek, "build_time_windows", lambda: {
        "ok": True, "timezone": vitek.LOCAL_TIMEZONE, "roots": [{"root": "MGC"}],
    })
    with vitek._LOCK:
        doc = vitek._read()
        yes_incident, _ = vitek._record_incident(
            doc, category="runtime", key="yes-route", severity="warning",
            title="Нужна проверка", details="Тест кнопки Да", recommendation="Создать задачу",
        )
        no_incident, _ = vitek._record_incident(
            doc, category="runtime", key="no-route", severity="warning",
            title="Можно пропустить", details="Тест кнопки Нет", recommendation="Игнорировать",
        )
        vitek._write(doc)
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"

    def request(path: str, *, body=None):
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            base + path, data=raw, method="POST" if raw is not None else "GET",
            headers={"Content-Type": "application/json"} if raw is not None else {},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    try:
        code, current = request("/api/vitek/status")
        assert code == 200 and current["mode"] == "free"
        code, windows = request("/api/vitek/time-windows")
        assert code == 200 and windows["roots"][0]["root"] == "MGC"
        code, created = request("/api/vitek/plans", body={
            "scope": "day", "focus": "MGC", "goals": ["Проверить окно 06:00-10:00"],
        })
        assert code == 200 and len(created["plan"]["task_ids"]) == 1
        _, after = request("/api/vitek/status")
        assert after["plans"]["day"]["focus"] == "MGC"
        assert after["task_counts"]["active"] == 1
        code, signaled = request("/api/vitek/events", body={
            "event_type": "job_completed", "payload": {"job_id": "HTTP-JOB-1"},
        })
        assert code == 200 and signaled["queued"] is True
        code, yes = request(
            f"/api/vitek/incidents/{yes_incident['incident_id']}/decision",
            body={"decision": "create_task", "note": "Да из интерфейса"},
        )
        assert code == 200 and yes["incident"]["task"]["incident_id"] == yes_incident["incident_id"]
        code, no = request(
            f"/api/vitek/incidents/{no_incident['incident_id']}/decision",
            body={"decision": "ignore", "note": "Нет из интерфейса"},
        )
        assert code == 200 and no["incident"]["status"] == "ignored"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_telegram_style_commands_control_rest_and_latest_incident(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vitek, "_maybe_notify_idle", lambda: False)
    with vitek._LOCK:
        doc = vitek._read()
        incident, _ = vitek._record_incident(
            doc, category="financial_classification", key="Q1", severity="warning",
            title="Financial review", details="review", recommendation="review",
            context={"needs_review": 1},
        )
        vitek._write(doc)
    vitek._remember_owner_question(incident, "default")

    accepted = vitek.handle_text_command("да")
    assert accepted["handled"] is True
    assert "Передал работу Управляющему" in accepted["reply"]
    resting = vitek.handle_text_command("Витёк, отдыхай 2 часа")
    assert "Ухожу на указанный срок" in resting["reply"]
    resumed = vitek.handle_text_command("Витёк, вернись к работе")
    assert "Вернулся к работе" in resumed["reply"]


def test_pending_question_does_not_swallow_a_new_owner_command(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    with vitek._LOCK:
        doc = vitek._read()
        incident, _ = vitek._record_incident(
            doc, category="financial_classification", key="pending", severity="warning",
            title="Нужна классификация", details="x", recommendation="уточнить",
            context={"needs_review": 1},
        )
        vitek._write(doc)
    vitek._remember_owner_question(incident, "default")

    for command in (
        "Включи моделирование на DEMO3369390",
        "Управляющий, как дела?",
        "Марина, покажи финансовый отчёт",
    ):
        result = vitek.handle_text_command(command)
        assert result["handled"] is False, command
        assert result.get("kind") != "incident_decision", command


def test_vitek_name_variants_all_return_the_same_operational_status(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    with vitek._LOCK:
        doc = vitek._read()
        first, _ = vitek._record_incident(
            doc, category="financial_classification", key="one", severity="critical",
            title="Финансовая проверка", details="x", recommendation="решить",
            context={"needs_review": 2},
        )
        second, _ = vitek._record_incident(
            doc, category="test", key="two", severity="warning",
            title="Нужно проверить качество", details="x", recommendation="решить",
        )
        vitek._write(doc)

    phrases = (
        "Витя перечисли список задач, которые у тебя не решенные",
        "Витёк, что у тебя осталось?",
        "Витек статус",
        "Витька, какие задачи?",
        "Виктор, какие задачи остались?",
        "Эй, Витенька, чем занят?",
        "/vitek status",
        "Vitek, unfinished tasks",
        "Дежурный контролёр, список задач",
        "витя какие задания отсались у тебя на сеголня?",
        "Витя какие на сегодня задания у тебя остались?",
        "Витёк, какие сегодня задания у тебя остались?",
    )
    for phrase in phrases:
        result = vitek.handle_text_command(phrase, source="test")
        assert result["handled"] is True, phrase
        assert result["kind"] == "status", phrase
        assert "активных поручений сейчас нет" in result["reply"], phrase
        assert "финансов" in result["reply"].lower(), phrase
        assert first["incident_id"] not in result["reply"]
        assert second["incident_id"] not in result["reply"]
        assert "[CRITICAL]" not in result["reply"]


def test_vitek_explicit_work_becomes_routed_task_but_general_reference_does_not(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)

    accepted = vitek.handle_text_command(
        "Витя, исправь критическую ошибку стратегии NinjaTrader", source="telegram",
    )
    referenced = vitek.handle_text_command("Расскажи, что вчера говорил Витя", source="app")
    delegated_news = vitek.handle_text_command("Витя, перечисли важные новости", source="app")

    assert accepted["handled"] is True
    assert accepted["kind"] == "task"
    assert accepted["action"]["status"] == "queued"
    task = accepted["task"]
    assert task["source"] == "telegram"
    assert task["priority"] == "critical"
    assert "Управляющему" in accepted["reply"]
    assert "модел" not in accepted["reply"].lower()
    assert referenced["handled"] is False
    assert delegated_news["handled"] is False and delegated_news["delegate"] is True


def test_event_queue_is_durable_deduplicated_and_wakes_worker(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    vitek._WAKE.clear()

    first = vitek.emit_event("runtime_error", {"message": "boom", "timestamp_utc": "one"})
    second = vitek.emit_event("runtime_error", {"message": "boom", "timestamp_utc": "two"})

    assert first["queued"] is True
    assert second["queued"] is False and second["reason"] == "duplicate"
    assert vitek._WAKE.is_set()
    current = vitek.status()
    assert current["event_engine"]["mode"] == "event_driven"
    assert current["event_engine"]["queued"] == 1


def test_connection_outage_stays_single_and_uses_no_model(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vitek, "_notify_event_result", lambda *args, **kwargs: False)
    event = {
        "event_id": "VE-OUTAGE", "event_type": "connection_lost",
        "payload": {"enabled_strategies": 2}, "source": "test",
    }

    analyzed = vitek._analyze_system_event(event)
    repeated = vitek.emit_event("connection_lost", {"enabled_strategies": 2})

    assert analyzed["model"] == "deterministic controller"
    assert "связь с NinjaTrader потеряна" in analyzed["content"]
    assert repeated["queued"] is False
    assert repeated["reason"] == "open_incident"


def test_bridge_spool_is_ingested_once_by_cursor(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    spool = tmp_path / "vitek_events.jsonl"
    monkeypatch.setattr(vitek, "_bridge_event_path", lambda: spool)
    spool.write_text(
        json.dumps({
            "event_type": "job_completed", "source": "ninjatrader_bridge",
            "payload": {"job_id": "JOB-1", "status": "done"},
        }) + "\n",
        encoding="utf-8",
    )

    first = vitek.ingest_bridge_events()
    second = vitek.ingest_bridge_events()

    assert first["ingested"] == 1
    assert second["ingested"] == 0
    assert vitek.status()["event_engine"]["queued"] == 1


def test_task_event_selects_strong_model_and_records_real_completion(tmp_path, monkeypatch) -> None:
    from app.ai_lab import chief_agent

    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vitek, "_maybe_notify_idle", lambda: False)
    calls = []

    def fake_handle(message, **kwargs):
        calls.append((message, kwargs))
        return {
            "ok": True, "reply": "Фактическая проверка выполнена.",
            "model": "deepseek-v4-pro", "provider": "test", "complexity": "critical",
            "actions": [{"name": "audit_recent_backtests", "status": "completed"}],
        }

    monkeypatch.setattr(chief_agent, "handle_message", fake_handle)
    task = vitek.add_task({
        "title": "Исправить критическую ошибку стратегии NinjaTrader",
        "description": "Проверить и исправить сбой.", "priority": "critical",
    })
    processed = vitek.process_next_event()
    stored = next(row for row in vitek.status()["tasks"] if row["task_id"] == task["task_id"])

    assert processed and processed["ok"] is True
    assert calls[0][1]["agent"] == "manager"
    assert stored["assigned_agent"] == "tolik"
    assert stored["complexity"] == "critical"
    assert stored["status"] == "completed"
    assert stored["execution_model"] == "deepseek-v4-pro"


def test_context_assignment_activates_once_and_reports_to_same_conversation(tmp_path, monkeypatch) -> None:
    from app.ai_lab import chief_agent

    _isolate(monkeypatch, tmp_path)
    reports = []
    closed = []
    monkeypatch.setattr(vitek, "_maybe_notify_idle", lambda: False)
    monkeypatch.setattr(chief_agent, "handle_message", lambda *args, **kwargs: {
        "ok": True, "reply": "Проверка исследования завершена.",
        "model": "test-strong-model", "provider": "test",
        "actions": [{"name": "audit_recent_backtests", "status": "completed"}],
    })
    monkeypatch.setattr(chief_agent, "report_chart_snapshot", lambda **kwargs: reports.append(kwargs) or {"ok": True})
    monkeypatch.setattr(chief_agent, "set_conversation_closed", lambda cid, closed_state, **kwargs: closed.append((cid, closed_state, kwargs)) or {"ok": True})
    doc = vitek._read()
    doc["incidents"] = [{
        "incident_id": "VI-RESEARCH", "category": "strategy_lifecycle",
        "status": "awaiting_decision", "owner_decision_required": True,
        "title": "Нужно разобрать исследование",
    }]
    vitek._write(doc)
    task = vitek.add_task({
        "title": "Разобраться с исследованием MGC Morning",
        "description": "Проверить гипотезы и бэктест.",
        "source": "victor_ui", "status": "planned", "auto_execute": False,
        "incident_id": "VI-RESEARCH",
        "conversation_id": "victor-mgc",
        "context": {"entity_type": "research", "entity_id": "EXP-1", "entity_label": "MGC Morning"},
        "budget": {"amount": 25, "currency": "usd"},
        "control": {"condition": "следить до завершения бэктеста", "report_frequency": "по событию"},
    })
    assert vitek._read()["events"] == []

    accepted = vitek.handle_text_command(
        "Виктор, приступай к поручению: разобраться с исследованием MGC Morning.",
        conversation_id="victor-mgc", source="app",
        scope={"user_id": "owner", "workspace_id": "owner-ws", "runtime_dir": str(tmp_path), "is_owner": True},
    )
    current = vitek._read()
    stored = next(row for row in current["tasks"] if row["task_id"] == task["task_id"])

    assert accepted["handled"] is True and accepted["kind"] == "task"
    assert "Сейчас разберусь" in accepted["reply"]
    assert len(current["tasks"]) == 1
    assert stored["auto_execute"] is True and stored["status"] == "new"
    assert stored["conversation_scope"]["workspace_id"] == "owner-ws"
    assert stored["budget"] == {"amount": 25.0, "currency": "USD"}
    assert current["events"][0]["event_type"] == "task_created"
    incident = next(row for row in current["incidents"] if row["incident_id"] == "VI-RESEARCH")
    assert incident["status"] == "in_progress" and incident["owner_decision_required"] is False

    processed = vitek.process_next_event()
    stored = next(row for row in vitek.status()["tasks"] if row["task_id"] == task["task_id"])
    assert processed and stored["status"] == "completed"
    assert reports and reports[0]["conversation_id"] == "victor-mgc"
    assert reports[0]["agent_name"] == "Виктор"
    assert reports[0]["scope"]["workspace_id"] == "owner-ws"
    assert closed and closed[0][0:2] == ("victor-mgc", True)


def test_task_is_not_claimed_complete_without_executed_action(tmp_path, monkeypatch) -> None:
    from app.ai_lab import chief_agent

    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vitek, "_notify_incidents", lambda rows, resting: True)
    monkeypatch.setattr(chief_agent, "handle_message", lambda *args, **kwargs: {
        "ok": True, "reply": "Можно было бы изменить настройку.",
        "model": "test-model", "provider": "test", "actions": [],
    })
    task = vitek.add_task({"title": "Измени настройку стратегии", "priority": "high"})

    vitek.process_next_event()
    current = vitek.status()
    stored = next(row for row in current["tasks"] if row["task_id"] == task["task_id"])

    assert stored["status"] == "waiting_review"
    assert current["incident_counts"]["open"] == 1


def test_connection_restore_retires_linked_task_and_queued_event(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    doc = vitek._read()
    doc["incidents"] = [{
        "incident_id": "VI-CONNECTION", "category": "runtime_connection",
        "status": "in_progress", "task_id": "VT-RESTORE",
    }]
    doc["tasks"] = [{
        "task_id": "VT-RESTORE", "incident_id": "VI-CONNECTION",
        "status": "planned", "title": "Восстановить связь",
    }]
    doc["events"] = [{
        "event_id": "VE-TASK", "event_type": "task_created", "status": "queued",
        "payload": {"task_id": "VT-RESTORE"},
    }]
    vitek._write(doc)

    assert vitek._resolve_connection_incidents() == {"VI-CONNECTION"}
    current = vitek._read()
    assert current["incidents"][0]["status"] == "resolved"
    assert current["tasks"][0]["status"] == "completed"
    assert current["events"] == []
    assert current["event_history"][-1]["result"]["already_restored"] is True

    late = vitek._set_task_execution(
        "VT-RESTORE", status="waiting_review", execution_event_id="VE-TASK",
        result="late worker result",
    )
    assert late["status"] == "completed"
    assert late["result"] != "late worker result"


def test_status_auto_retires_stale_connection_question_when_heartbeat_is_fresh(tmp_path, monkeypatch) -> None:
    from app import runtime

    _isolate(monkeypatch, tmp_path)
    doc = vitek._read()
    doc["incidents"] = [{
        "incident_id": "VI-STALE", "category": "runtime_connection",
        "status": "awaiting_decision", "owner_decision_required": True,
        "title": "Связь потеряна", "details": "old", "recommendation": "restore",
    }]
    vitek._write(doc)
    monkeypatch.setattr(runtime, "read_heartbeat", lambda: {"fresh": True})

    current = vitek.status()

    assert current["incident_counts"]["awaiting_owner"] == 0
    assert next(row for row in current["incidents"] if row["incident_id"] == "VI-STALE")["status"] == "resolved"


def test_poll_once_consumes_events_without_legacy_full_scan(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vitek, "_bridge_event_path", lambda: tmp_path / "missing.jsonl")
    monkeypatch.setattr(vitek, "scan", lambda **kwargs: (_ for _ in ()).throw(AssertionError("full scan called")))

    result = vitek.poll_once()

    assert result["ok"] is True
    assert result["processed"] == []


def test_vitek_ui_and_background_install_contracts() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    aurora = root / "app" / "static" / "aurora"
    html = (aurora / "strategies.html").read_text(encoding="utf-8")
    overview = (aurora / "index.html").read_text(encoding="utf-8")
    ai_lab = (aurora / "assets" / "pages" / "ai-lab.js").read_text(encoding="utf-8")
    victor = (aurora / "assets" / "victor.js").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "aurora" / "assets" / "pages" / "strategies.js").read_text(encoding="utf-8")
    server = (root / "app" / "server.py").read_text(encoding="utf-8")
    installer = (root / "tools" / "install-vitek-background.ps1").read_text(encoding="utf-8")

    assert "Виктор · правая рука руководителя" in html
    assert "Виктор · ваша правая рука" in overview
    assert 'data-victor-center' in overview
    assert "Создать отдельный чат и поручить Виктору" in victor
    assert "aiOrchestratorCreateConversation" in victor
    assert "aiOrchestratorMessage" in victor
    assert "Поручить Виктору разобраться" in js and "Поручить Виктору разобраться" in ai_lab
    for page in aurora.glob("*.html"):
        assert "assets/victor.js" in page.read_text(encoding="utf-8"), page.name
    assert 'id="vitek-agents"' in html
    assert "Временные окна стратегий" in html
    assert "vitekIncidentDecision" in js
    assert "vitekPlan" in js
    assert "setInterval(refreshVitekStatus, 3000)" in js
    assert "получает события автоматически" in js
    assert '"/api/vitek/time-windows"' in server
    assert '"/api/vitek/events"' in server
    legacy_domain_block = server.split('if path == "/api/ai-lab/domain-agents/message":', 1)[1].split("return", 1)[0]
    assert "ai_chief_agent.handle_message" in legacy_domain_block
    assert "ai_domain_agents.answer" not in legacy_domain_block
    assert "New-ScheduledTaskTrigger -AtLogOn" in installer
    assert "RestartCount 999" in installer


def test_owner_dialogue_hides_internal_codes_and_uses_verified_strategy_threshold(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    with vitek._LOCK:
        doc = vitek._read()
        incident, _ = vitek._record_incident(
            doc, category="strategy_lifecycle", key="failed", severity="warning",
            title="failed_not_hidden", details="P-SECRET", recommendation="archive",
            context={
                "count": 3,
                "rehabilitation": {"confidence_pct": 68, "rehabilitation_supported": True,
                                   "best_candidate": "MGC Morning"},
            },
        )
        vitek._write(doc)

    reply = vitek.handle_text_command("Витёк, что осталось?", conversation_id="owner-chat")["reply"]

    assert "68%" in reply and "выше 50%" not in reply
    assert "OOS" in reply and "стресс" in reply
    assert incident["incident_id"] not in reply
    assert "failed_not_hidden" not in reply
    assert "Можно ответить просто «да» или «нет»" in reply


def test_agent_lanes_run_independently_in_parallel(tmp_path, monkeypatch) -> None:
    import time

    _isolate(monkeypatch, tmp_path)
    release = threading.Event()
    started = []

    def fake_dispatch(event):
        started.append(event["event_type"])
        release.wait(2)
        return {"ok": True}

    monkeypatch.setattr(vitek, "_dispatch_event", fake_dispatch)
    with vitek._AGENT_RUN_LOCK:
        vitek._ACTIVE_AGENT_RUNS.clear()
    vitek.emit_event("job_completed", {"job_id": "J1"}, dedupe_seconds=0)
    vitek.emit_event("financial_event_changed", {"event_id": "F1"}, dedupe_seconds=0)

    assert vitek._dispatch_parallel_events() == 2
    current = vitek.status()
    working = {row["agent_id"] for row in current["agent_activity"] if row["working"]}
    assert {"tolik", "marina"}.issubset(working)
    assert current["event_engine"]["parallel_limit"] == 6
    release.set()
    deadline = time.time() + 3
    while time.time() < deadline:
        with vitek._AGENT_RUN_LOCK:
            if not vitek._ACTIVE_AGENT_RUNS:
                break
        time.sleep(0.02)
    with vitek._AGENT_RUN_LOCK:
        assert vitek._ACTIVE_AGENT_RUNS == {}


def test_running_events_are_requeued_after_backend_restart(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    with vitek._LOCK:
        doc = vitek._read()
        doc["events"] = [{
            "event_id": "VE-INTERRUPTED", "event_type": "task_created",
            "payload": {"task_id": "VT-1"}, "status": "running",
            "attempts": 1, "started_at_utc": "2026-07-13T01:00:00Z",
        }]
        vitek._write(doc)

    assert vitek.recover_interrupted_events() == 1
    recovered = vitek._read()["events"][0]
    assert recovered["status"] == "queued"
    assert "started_at_utc" not in recovered
    assert recovered["recovered_at_utc"]


def test_startup_audit_resolves_stale_connection_question_when_heartbeat_is_fresh(tmp_path, monkeypatch) -> None:
    from app import runtime

    _isolate(monkeypatch, tmp_path)
    with vitek._LOCK:
        doc = vitek._read()
        incident, _ = vitek._record_incident(
            doc, category="vitek_execution", key="lost", severity="critical",
            title="connection_lost", details="lost", recommendation="repair",
            context={"event_type": "connection_lost"},
        )
        doc.setdefault("dialogue", {}).setdefault("awaiting_by_conversation", {})["default"] = {
            "incident_id": incident["incident_id"],
        }
        vitek._write(doc)
    monkeypatch.setattr(vitek, "scan", lambda **kwargs: {"findings": 0})
    monkeypatch.setattr(runtime, "read_heartbeat", lambda: {"fresh": True})

    result = vitek._analyze_system_event({"event_type": "startup_audit", "payload": {}})

    assert result["resolved_connection_incidents"] == 1
    current = next(row for row in vitek._read()["incidents"] if row["incident_id"] == incident["incident_id"])
    assert current["status"] == "resolved"
    assert vitek._read()["dialogue"]["awaiting_by_conversation"] == {}
