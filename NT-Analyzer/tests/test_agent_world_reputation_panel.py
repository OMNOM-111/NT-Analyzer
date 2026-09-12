"""What the two new panels actually put in front of a person.

The scopes themselves are covered in `test_agent_world_reputation_scopes.py`.
These run the shipped page module and read the HTML it produces, because the
defect that reached a running build was not in the measurement: the model scope
was correct, and the panel still printed a green «100%» for a sample that was
entirely local diagnostics.

No browser and no application. The payloads are the shape `task_detail` returns.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "static" / "aurora" / "assets" / "pages" / "ai-command-center.js"


def render(function: str, payload) -> str:
    script = (
        f"const ui = require({json.dumps(str(SCRIPT))});\n"
        f"process.stdout.write(JSON.stringify(ui.{function}({json.dumps(payload)})));"
    )
    done = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding="utf-8", timeout=20)
    return json.loads(done.stdout)


def _scope(name, kind, subject_id, *, sample, synthetic, basis, pct=None, status="measured"):
    return {
        "version": "reputation-scopes-v1", "scope": name,
        "subject": {"kind": kind, "id": subject_id},
        "task_class": "connection_exact", "sample_size": sample,
        "confidence": "low", "status": status, "basis": basis,
        "quality": {"passed": sample, "observed_pct": pct},
        "evidence_refs": [{"evaluation_id": f"{index:032x}", "outcome_id": f"{index:032x}",
                           "evidence_sha256": "0" * 64} for index in range(sample)],
        "window": {"days": 30, "newest_observation": "2026-09-11T18:24:36+00:00"},
        "provenance": {"evaluator": "independent_local_evidence_verifier", "self_scored": False,
                       "synthetic_observations": synthetic, "measured_observations": sample - synthetic,
                       "professional_quality_assessed": False},
        "limitation": "…",
    }


def test_a_diagnostic_only_sample_is_never_headlined_as_an_observed_percentage():
    """Four runs of the local test executor are not a model scoring 100%."""
    html = render("reputationPanel", {"model_performance": _scope(
        "model_performance", "model", "a" * 32, sample=4, synthetic=4, basis="diagnostic", pct=100.0)})
    head = html.split("</div>")[0]
    assert "диагностика" in head and "4" in head
    assert "aw-good" not in head, "a diagnostic sample is wearing the observed-performance style"
    assert "100" not in head, "a diagnostic rate is being presented as observed performance"
    # The number is not hidden either — it is still in the card, named as what it is.
    assert "из них диагностических" in html


def test_field_evidence_keeps_the_observed_percentage():
    html = render("reputationPanel", {"model_performance": _scope(
        "model_performance", "model", "a" * 32, sample=12, synthetic=0, basis="field", pct=75.0)})
    head = html.split("</div>")[0]
    assert "aw-good" in head and "75" in head
    assert "диагностика" not in head
    assert "из них диагностических" not in html


def test_a_mixed_sample_says_so_beside_the_number():
    html = render("reputationPanel", {"model_performance": _scope(
        "model_performance", "model", "a" * 32, sample=10, synthetic=4, basis="mixed", pct=80.0)})
    head = html.split("</div>")[0]
    assert "80" in head and "частично диагностика" in head
    assert "aw-good" not in head


def test_a_scope_with_too_few_observations_shows_no_number_at_all():
    html = render("reputationPanel", {"agent_role_performance": _scope(
        "agent_role_performance", "agent_role", "b" * 32, sample=1, synthetic=0,
        basis="field", pct=None, status="new")})
    assert "NEW" in html and "%" not in html.split("</div>")[0]


def test_two_scopes_are_two_cards_and_neither_number_sits_under_the_other_heading():
    html = render("reputationPanel", {
        "model_performance": _scope("model_performance", "model", "a" * 32,
                                    sample=12, synthetic=0, basis="field", pct=75.0),
        "agent_role_performance": _scope("agent_role_performance", "agent_role", "b" * 32,
                                         sample=1, synthetic=0, basis="field", pct=None, status="new")})
    cards = html.split('<article class="aw-domain-card">')[1:]
    assert len(cards) == 2
    model_card = next(card for card in cards if "aaaaaaaa" in card)
    role_card = next(card for card in cards if "bbbbbbbb" in card)
    assert "Модель" in model_card and "75" in model_card
    assert "Рабочая роль" in role_card and "75" not in role_card
    assert "bbbbbbbb" not in model_card and "aaaaaaaa" not in role_card
    # Said once, in the panel itself, not left for the reader to infer.
    assert "не складываются" in html


def test_the_intent_panel_shows_the_commitment_and_says_it_is_not_editable():
    html = render("intentPanel", {
        "id": "c" * 32, "revision": 3, "status": "ready",
        "goal": {"text": "Проверка подключения", "request": None,
                 "persona_name": "Ариадна", "conversation_id": "AW-1", "message_id": "MSG-1"},
        "constraints": {"risk": "low", "deadline": "2026-09-11T19:24:31+00:00",
                        "budget_key": "ai_budgets.model.x", "max_output_tokens": 512},
        "required_evidence": {"rubric_key": "connection_exact", "rubric_label": "Проверка подключения",
                              "verified_by": "independent_local_evidence_verifier",
                              "human_review": "separate decision, never a quality claim"},
        "approval_mode": "advice", "scope": {"workspace_id": "w-1", "environment": "development"},
        "amendable": False, "actions": [], "created_at": "2026-09-11T18:00:00+00:00",
        "updated_at": "2026-09-11T18:00:00+00:00"})
    assert "Поручение" in html and "Проверка подключения" in html
    assert "только совет, исполнение не разрешено" in html
    assert "ревизия" in html and "3" in html
    assert "не редактируется после создания задачи" in html
    # Human acceptance is never presented as a statement about quality.
    assert "не является оценкой качества" in html
