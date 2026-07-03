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
