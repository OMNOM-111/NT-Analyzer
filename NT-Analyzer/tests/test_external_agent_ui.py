"""What the external-agent card puts in front of a person.

It is drawn by the shipped page module, from the shape the API actually
returns. The cases exist to stop three specific misreadings: an external agent
presented as a Model, a diagnostic run presented as a track record, and a task
history that silently renders nothing because the card reads a field the server
never sends.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "static" / "aurora" / "assets" / "pages" / "ai-command-center.js"


def render(function, payload):
    script = (f"const ui = require({json.dumps(str(SCRIPT))});\n"
              f"process.stdout.write(JSON.stringify(ui.{function}({json.dumps(payload)})));")
    done = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding="utf-8", timeout=20)
    return json.loads(done.stdout)


def connection(**overrides):
    item = {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "display_name": "Development · внешний агент",
        "status": "active", "revision": 3, "protocol": "a2a-0.3-jsonrpc-bounded",
        "endpoint": "https://development-agent.invalid/a2a",
        "last_verification": "2026-09-11T10:00:00Z", "last_latency_ms": 12,
        "allowed_capabilities": ["stratforge.json_arithmetic.v1"],
        "advertised_capabilities": ["stratforge.json_arithmetic.v1"],
        "synthetic": True, "model_id": None, "model": "unknown / externally managed",
        "current_task": None, "tasks": [],
        "statistics": {"tasks_completed": 0, "sample_size": 0},
        "performance": {"scope": "external_agent_performance",
            "subject": {"kind": "external_agent_connection", "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
            "task_class": "json_arithmetic", "sample_size": 0, "confidence": "insufficient",
            "status": "new", "basis": "none", "quality": {"passed": 0, "observed_pct": None},
            "evidence_refs": [], "window": {"days": 30, "newest_observation": None},
            "provenance": {"evaluator": "independent_local_evidence_verifier", "self_scored": False,
                           "synthetic_observations": 0, "measured_observations": 0,
                           "professional_quality_assessed": False},
            "limitation": "Недостаточно наблюдений для оценки."}}
    item.update(overrides)
    return item


def measured(basis, synthetic, sample=3, pct=100.0):
    view = connection()["performance"]
    view.update(sample_size=sample, status="measured", basis=basis, confidence="low",
                quality={"passed": sample, "observed_pct": pct},
                evidence_refs=[{} for _ in range(sample)])
    view["provenance"].update(synthetic_observations=synthetic, measured_observations=sample - synthetic)
    return view


def test_it_is_presented_as_its_own_kind_and_never_as_a_model():
    html = render("externalAgentCard", connection())
    assert "External Agent · отдельно от Model" in html
    assert "unknown / externally managed" in html
    assert "не записываются как Model Performance" in html
    assert "a2a-0.3-jsonrpc-bounded" in html
    assert "Проверено и доступно" in html


def test_a_diagnostic_record_never_wears_the_observed_performance_style():
    """The whole point of the shared panel: one honest renderer, not two."""
    html = render("externalAgentCard", connection(performance=measured("diagnostic", 3),
                                                  statistics={"tasks_completed": 3, "sample_size": 3}))
    panel = html[html.index("Наблюдаемые оценки"):]
    head = panel.split("</div>")[0]
    assert "диагностика" in head and "aw-good" not in head
    assert "100" not in head
    assert "Уверенность" in panel and "из них диагностических" in panel


def test_field_evidence_would_show_the_rate():
    html = render("externalAgentCard", connection(synthetic=False, performance=measured("field", 0)))
    panel = html[html.index("Наблюдаемые оценки"):]
    head = panel.split("</div>")[0]
    assert "aw-good" in head and "100" in head


def test_the_history_it_shows_is_the_history_the_server_sent():
    """The card used to read a field the API never sends, and showed nothing."""
    rows = [{"id": "11111111-2222-3333-4444-555555555555", "status": "review", "synthetic": True,
             "error_code": None, "evaluation_id": "e1"},
            {"id": "66666666-2222-3333-4444-555555555555", "status": "blocked", "synthetic": True,
             "error_code": "external_agent_timeout", "evaluation_id": None}]
    html = render("externalAgentCard", connection(tasks=rows,
                                                  statistics={"tasks_completed": 1, "sample_size": 1}))
    assert html.count("data-aw-task=") == 2
    assert "11111111" in html and "66666666" in html
    assert "оценка записана" in html and "без оценки" in html
    assert "external_agent_timeout" in html


def test_an_error_says_what_happened_rather_than_only_a_code():
    html = render("externalAgentCard", connection(status="disabled",
                  last_error="external_agent_reverification_required", allowed_capabilities=[]))
    assert "Секрет заменён" in html
    assert "external_agent_reverification_required" in html
    assert "Выключено" in html
    assert "Подтверждённые возможности: Нет" in html


def test_a_pending_credential_cleanup_is_stated_rather_than_hidden():
    html = render("externalAgentCard", connection(status="revoked", credential_cleanup="pending",
                                                  allowed_capabilities=[]))
    assert "Доступ отозван" in html and "будет повторено" in html
    assert "Отозвано" in html


def test_the_current_task_is_visible_while_it_runs():
    html = render("externalAgentCard", connection(
        current_task={"id": "99999999-2222-3333-4444-555555555555", "status": "running"}))
    assert "99999999" in html
