from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import server as server_mod
from app.ai_lab import paths, research_catalog


def _redirect(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths, "AI_LAB_DIR", tmp_path / "ai_lab")
    monkeypatch.setattr(paths, "REGISTRY_DIR", tmp_path / "ai_lab" / "registry")
    monkeypatch.setattr(paths, "USER_RESEARCH_DIR", tmp_path / "ai_lab" / "user_research")
    monkeypatch.setattr(paths, "INDEX_PATH", tmp_path / "ai_lab" / "registry" / "index.json")
    monkeypatch.setattr(paths, "EXPERIMENTS_DIR", tmp_path / "ai_lab" / "registry" / "experiments")


def test_create_research_builds_ai_ready_knowledge_and_family(monkeypatch, tmp_path: Path) -> None:
    _redirect(monkeypatch, tmp_path)
    created = research_catalog.create({
        "source_type": "personal_idea",
        "title": "Возврат к VWAP после импульса",
        "content": "После сильного открытия цена часто возвращается к VWAP.\n\nПроверить MNQ и MES.",
        "objectives": "Проверить результат после комиссии\nСравнить MNQ и MES",
        "hypotheses": ["Возврат происходит в первые 90 минут"],
    })

    assert created["research_id"].startswith("RES-")
    assert created["family_name"] == "Возврат к VWAP после импульса"
    assert created["family_key"].startswith("VozvratKVwap")
    assert created["evaluation"]["status"] == "new"
    knowledge = paths.USER_RESEARCH_DIR / created["knowledge_rel_path"]
    assert knowledge.exists()
    text = knowledge.read_text(encoding="utf-8")
    assert "## Протокол остановки" in text
    assert "Минимум стратегий до предварительного решения: 5" in text
    assert "После сильного открытия" in text

    run = research_catalog.run_context(created["research_id"])
    assert run["family_key"] == created["family_key"]
    assert "ACTIVE RESEARCH" in run["context"]
    assert "Do not silently switch" in run["context"]


def _result(research_id: str, index: int, *, profitable: bool = False) -> dict:
    return {
        "experiment_id": f"EXP-{index:04d}",
        "research_id": research_id,
        "class_name": f"Strategy{index}",
        "family": "TestFamily",
        "status": "candidate" if profitable else "rejected",
        "target_root": "MNQ",
        "analysis": {
            "pf_after_commission": 1.4 if profitable else 0.8,
            "trades_total": 150,
            "years_tested": 3,
            "net_profit_after_commission": 500 if profitable else -200,
            "dd_after_commission": -120.5,
        },
        "iteration_history": [{"iteration": n} for n in range(1, 4)],
        "backtests": [{
            "instrument": "MNQ 12-26", "timeframe": "5m",
            "period": {"from_utc": "2023-01-01T00:00:00Z", "to_utc": "2026-01-01T00:00:00Z"},
        }],
    }


def test_negative_evidence_moves_from_at_risk_to_exhausted() -> None:
    row = {
        "research_id": "RES-TEST",
        "family_name": "Test family",
        "family_key": "TestFamily",
        "evaluation_policy": dict(research_catalog.DEFAULT_POLICY),
    }
    five = [_result("RES-TEST", index) for index in range(5)]
    preliminary = research_catalog.evaluate(row, five)
    assert preliminary["status"] == "at_risk"
    assert preliminary["non_profitable_strategies"] == 5
    assert preliminary["parameter_variants"] == 15
    assert "Продолжить до 8" in preliminary["automatic_conclusion"]

    eight = [_result("RES-TEST", index) for index in range(8)]
    final = research_catalog.evaluate(row, eight)
    assert final["status"] == "exhausted"
    assert "неактуально" in final["automatic_conclusion"]


def test_profitable_family_is_validated_only_after_minimum_sample() -> None:
    row = {
        "research_id": "RES-WIN",
        "family_name": "Winning family",
        "family_key": "WinningFamily",
        "evaluation_policy": dict(research_catalog.DEFAULT_POLICY),
    }
    early = research_catalog.evaluate(row, [_result("RES-WIN", 1, profitable=True)])
    assert early["status"] == "promising"

    sample = [_result("RES-WIN", index, profitable=index == 0) for index in range(5)]
    final = research_catalog.evaluate(row, sample)
    assert final["status"] == "validated"
    assert final["best_variant"]["class_name"] == "Strategy0"
    assert final["best_variant"]["best_window"]["timeframe"] == "5m"
    assert final["best_variant"]["max_drawdown"] == -120.5


def test_technical_failures_do_not_make_research_unprofitable() -> None:
    row = {
        "research_id": "RES-INFRA",
        "family_name": "Infra family",
        "family_key": "InfraFamily",
        "evaluation_policy": dict(research_catalog.DEFAULT_POLICY),
    }
    failures = [{
        "experiment_id": f"EXP-F-{index}", "research_id": "RES-INFRA",
        "status": "compile_failed", "family": "InfraFamily",
    } for index in range(10)]
    evaluation = research_catalog.evaluate(row, failures)
    assert evaluation["status"] == "active"
    assert evaluation["evaluated_strategies"] == 0
    assert evaluation["technical_failures"] == 10


def test_ai_lab_ui_exposes_research_hierarchy_and_api() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "aurora" / "ai-lab.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "aurora" / "assets" / "pages" / "ai-lab.js").read_text(encoding="utf-8")
    api = (root / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    assert 'id="research-add"' in html and 'id="research-list"' in html and 'id="research-detail"' in html
    assert 'id="ai-research"' in html
    assert "researchTreeHtml" in js and "Работать в этом исследовании" in js
    assert "research_id: UI.qs('#ai-research').value" in js
    assert "/api/ai-lab/researches" in api


def test_bootstrap_existing_materials_and_strategies_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    _redirect(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    incoming = paths.USER_RESEARCH_DIR / "incoming"
    incoming.mkdir(parents=True)
    (incoming / "Глубокое исследование тест.md").write_text(
        "# Исследование VWAP\n\nПроверить возврат после открытия.", encoding="utf-8"
    )
    profiles = tmp_path / "data" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "strategies.json").write_text(
        '{"profiles":[{"profile_id":"p1","name":"VWAP Active","strategy_class":"VwapActive","strategy_family":"vwap_family"}]}',
        encoding="utf-8",
    )
    (profiles / "archived_strategies.json").write_text(
        '{"entries":[{"profile_id":"p2","name":"VWAP Old","strategy_class":"VwapOld","strategy_family":"vwap_family","reason":"нет edge"}]}',
        encoding="utf-8",
    )
    evidence = tmp_path / "data" / "research" / "old_run"
    evidence.mkdir(parents=True)

    first = research_catalog.bootstrap_existing()
    second = research_catalog.bootstrap_existing()
    catalog = research_catalog.list_researches()

    assert first["created"] == 3
    assert second == {"created": 0, "updated": 0}
    assert catalog["migration"] == {"created": 0, "updated": 0}
    assert len(catalog["researches"]) == 3
    family = next(row for row in catalog["researches"] if row["source_type"] == "personal_idea")
    assert family["evaluation"]["working_strategies"] == 1
    assert family["evaluation"]["archived_strategies"] == 1
    source = next(row for row in catalog["researches"] if row["source_type"] == "research")
    assert family["research_id"] in source["linked_research_ids"]


def test_research_http_create_list_detail_and_update(monkeypatch, tmp_path: Path) -> None:
    _redirect(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(server_mod.account_auth, "auth_required", lambda: False)
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"

    def request(path: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            base + path, data=raw, method=method,
            headers={"Content-Type": "application/json"} if raw else {},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    try:
        status, created = request("/api/ai-lab/researches", method="POST", body={
            "source_type": "personal_idea",
            "title": "HTTP research",
            "content": "Проверить гипотезу через несколько независимых стратегий.",
        })
        research_id = created["research"]["research_id"]
        assert status == 201 and created["created"] is True

        status, listed = request("/api/ai-lab/researches")
        assert status == 200 and listed["total"] == 1
        status, detailed = request(f"/api/ai-lab/researches/{research_id}")
        assert status == 200 and detailed["title"] == "HTTP research"

        status, updated = request(
            f"/api/ai-lab/researches/{research_id}", method="POST",
            body={"owner_conclusion": "Продолжить до целевого числа стратегий."},
        )
        assert status == 200 and updated["research"]["owner_conclusion"].startswith("Продолжить")
    finally:
        server.shutdown()
        server.server_close()
