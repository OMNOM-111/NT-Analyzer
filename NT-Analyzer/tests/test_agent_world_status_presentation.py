"""Regressions for the owner-reported status/counter presentation defects.

Each test reproduces one observed contradiction on the integrated Local review
build: a metric that disagreed with the panel beside it, a truncated warning
list, a full progress bar on a task that had not finished, one green badge that
meant "enabled", "free" and "executing" at once, a score without its class of
check, and raw enum keys shown as user-facing sentences.

No running application, provider or browser profile is used here.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.ai_control_center import presentation


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "static" / "aurora" / "assets" / "pages" / "ai-command-center.js"


def evaluate(expression: str):
    script = (
        "const assert = require('node:assert/strict');\n"
        f"const ui = require({json.dumps(str(SCRIPT))});\n"
        "(async () => { const result = await ("
        + expression
        + "); process.stdout.write(JSON.stringify(result)); })()"
        ".catch(error => { process.stderr.write(String(error.stack)); process.exitCode = 1; });"
    )
    process = subprocess.run(
        ["node", "-e", script], cwd=ROOT, check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=20,
    )
    return json.loads(process.stdout)


def render(state: dict) -> dict:
    """Boot the real page module against a stubbed DOM and return its HTML."""
    harness = """(async () => {
      const fs = require('node:fs'), vm = require('node:vm');
      const nodes = new Map();
      const tabs = ['overview','work','agents'].map(key => ({dataset:{awTab:key},setAttribute(){}}));
      const node = key => {
        if (!nodes.has(key)) nodes.set(key,{innerHTML:'',textContent:'',hidden:false,
          setAttribute(){},addEventListener(){},classList:{toggle(){}},
          querySelectorAll(){return tabs;}});
        return nodes.get(key);
      };
      const document = {querySelector:node,addEventListener(){},removeEventListener(){}};
      const data = DATA;
      let started;
      const window = {UI:{ready(fn){started=fn();},signal(){},onLeave(){},wireAgentFaces(){}},
        API:{http:{async aiControlCenterOverview(){return data;}}},
        location:{hash:'',search:''}};
      const source = fs.readFileSync(SCRIPT_PATH,'utf8');
      vm.runInNewContext(source,{window,document,URLSearchParams,Date});
      await started;
      return {html:node('#aw-content').innerHTML, pulse:node('#aw-pulse').innerHTML};
    })()"""
    harness = harness.replace("DATA", json.dumps(state)).replace(
        "SCRIPT_PATH", json.dumps(str(SCRIPT)))
    return evaluate(harness)


def task(**overrides) -> dict:
    base = {"id": "11111111-1111-1111-1111-111111111111", "title": "Иван · Голос Court",
            "status": "review", "phase": "awaiting_review", "phase_label": "Ожидает проверки",
            "stage": "provider_receipt", "stage_label": "Ответ модели получен",
            "task_class": "court_vote", "task_class_label": "Голос Court",
            "progress_pct": None, "synthetic": False, "updated_at": "2026-09-05T03:37:00Z"}
    return {**base, **overrides}


def workspace(tasks, agents=(), attention=None, stats=None) -> dict:
    rows = list(tasks)
    computed = presentation.counters(row["status"] for row in rows)
    alerts = [row for row in rows
              if presentation.task_phase(row["status"]) in presentation.ATTENTION_PHASES]
    return {"enabled": True, "scope": {"synthetic": False, "workspace_id": "ws"},
            "capabilities": {"can_run_demo": False}, "tasks": rows, "agents": list(agents),
            "outcomes": [], "activity": [],
            "attention": list(alerts if attention is None else attention),
            "stats": {**computed, "agents": len(agents), "attention": len(alerts),
                      "active_tasks": computed["executing"], "completed_tasks": computed["done"],
                      **(stats or {})}}


# --- server contract ---------------------------------------------------------


def test_phase_split_never_folds_review_or_blocked_into_execution():
    """The live Local reported active_tasks=0 while two review tasks were open."""
    counters = presentation.counters(
        ["review", "review", "failed", "succeeded", "succeeded", "blocked"])
    assert counters == {"executing": 0, "awaiting_review": 2, "awaiting_decision": 1,
                        "done": 2, "failed": 1, "cancelled": 0}


def test_unfinished_task_reports_no_completion_percentage():
    """A failed/review task used to render a full 100 % bar beside its badge."""
    assert presentation.progress_pct("succeeded") == 100
    assert presentation.progress_pct("running") == 0
    assert presentation.progress_pct("review") is None
    assert presentation.progress_pct("failed") is None
    assert presentation.progress_pct("cancelled") is None


def test_unknown_status_is_never_counted_as_finished_work():
    assert presentation.task_phase("something_new") == presentation.PHASE_AWAITING_DECISION
    assert presentation.counters(["something_new"])["done"] == 0


@pytest.mark.parametrize("rubric", ["court_vote", "chart_spec", "backtest_spec",
                                    "connection_exact", "json_arithmetic", "extract_facts"])
def test_every_rubric_key_has_a_human_label(rubric):
    label = presentation.rubric_label(rubric)
    assert label and label != rubric and "_" not in label


@pytest.mark.parametrize("stage", ["provider_receipt", "awaiting_provider",
                                   "application_verified", "application_failed"])
def test_every_stage_has_a_human_label(stage):
    label = presentation.stage_label(stage)
    assert label and label != stage and "_" not in label


def test_each_attention_phase_states_a_reason_and_a_next_action():
    for phase in presentation.ATTENTION_PHASES:
        reason, action = presentation.attention_reason(phase)
        assert reason.endswith(".") and action.endswith(".")
        assert reason != action


# --- presentation ------------------------------------------------------------


def test_metric_and_panel_heading_cannot_contradict_each_other():
    """«В работе 0» was shown above a panel titled «Сейчас в работе»."""
    result = render(workspace([task(), task(id="22222222-2222-2222-2222-222222222222")]))
    assert "Сейчас в работе" not in result["html"]
    assert "Ожидают вашего решения" in result["html"]
    assert "Выполняется" in result["html"]


def test_executing_work_still_uses_the_in_progress_heading():
    result = render(workspace([task(status="running", phase="executing", progress_pct=0)]))
    assert "Сейчас в работе" in result["html"]


def test_truncated_attention_list_offers_a_route_to_the_remaining_items():
    """The counter said 4; only three cards were rendered and nothing linked on."""
    rows = [task(id=f"{n}{n}{n}{n}{n}{n}{n}{n}-1111-1111-1111-111111111111",
                 status="failed" if n % 2 else "review") for n in range(1, 5)]
    result = render(workspace(rows))
    assert result["html"].count("aw-alert\"") == 3
    assert "Показать все (4)" in result["html"]
    assert 'data-aw-filter="attention"' in result["html"]


def test_attention_card_shows_why_and_what_to_do():
    reason, action = presentation.attention_reason(presentation.PHASE_AWAITING_REVIEW)
    rows = [task(reason=reason, action_hint=action, since="2026-09-05T03:37:00Z")]
    result = render(workspace(rows))
    assert reason in result["html"] and action in result["html"]


def test_unfinished_task_card_shows_its_phase_instead_of_a_full_bar():
    result = render(workspace([task()]))
    assert "<progress" not in result["html"]
    assert "Ожидает проверки" in result["html"]


def test_finished_task_card_still_shows_measured_progress():
    result = render(workspace([task(status="succeeded", phase="done",
                                    phase_label="Завершено", progress_pct=100)]))
    assert "<progress" in result["html"]


def test_enabled_idle_agent_is_not_presented_as_working():
    """One green «Активен» badge stood for enabled, free and executing alike."""
    agent = {"id": "aaaaaaaa-1111-1111-1111-111111111111", "display_name": "Толик",
             "status": "active", "availability": "active", "occupancy": "free",
             "role": "Бэктестирование", "synthetic": False,
             "evaluation": {"sample_size": 3, "score_pct": 100, "confidence": "low",
                            "task_class": "json_arithmetic",
                            "mode": "real_model_bounded_capability"}}
    result = render(workspace([], agents=[agent]))
    assert "Включён" in result["html"] and "Свободен" in result["html"]
    assert "Активен" not in result["html"]


def test_executing_agent_is_shown_as_enabled_and_busy():
    agent = {"id": "aaaaaaaa-2222-1111-1111-111111111111", "display_name": "Иван",
             "status": "working", "availability": "active", "occupancy": "working",
             "role": "Графики", "synthetic": False, "evaluation": {"sample_size": 0}}
    result = render(workspace([], agents=[agent]))
    assert "Включён" in result["html"] and "Выполняет задачу" in result["html"]


def test_suspended_agent_is_not_rendered_with_the_success_style():
    meta = evaluate("ui.availabilityMeta({availability:'suspended'})")
    assert meta == ["Приостановлен", "warning"]
    assert evaluate("ui.occupancyMeta({occupancy:'free'})") == ["Свободен", "neutral"]


def test_score_always_carries_the_class_of_check_it_was_measured_on():
    """100 % over three json_arithmetic inputs must not read as proven quality."""
    meta = evaluate("ui.evaluationMeta({evaluation:{sample_size:3,score_pct:100,"
                    "confidence:'low',task_class:'json_arithmetic',"
                    "mode:'real_model_bounded_capability'}})")
    assert meta["classLabel"] == "Арифметика · JSON"
    assert meta["confidence"] == "низкая"
    assert meta["origin"] == "фактические ответы модели"
    agent = {"id": "aaaaaaaa-3333-1111-1111-111111111111", "display_name": "Толик",
             "availability": "active", "occupancy": "free", "synthetic": False,
             "evaluation": {"sample_size": 3, "score_pct": 100, "confidence": "low",
                            "task_class": "json_arithmetic",
                            "mode": "real_model_bounded_capability"}}
    result = render(workspace([], agents=[agent]))
    assert "Арифметика · JSON" in result["html"]


def test_raw_enum_keys_do_not_reach_the_owner_facing_card():
    result = render(workspace([task()]))
    for machine in ["court_vote", "provider_receipt", "chart_spec", "awaiting_provider"]:
        assert machine not in result["html"]


def test_unknown_stage_key_is_not_printed_verbatim():
    assert evaluate("ui.stageName('some_internal_stage')") == "Этап: технические детали"
    assert evaluate("ui.stageName('provider_receipt')") == "Ответ модели получен"


# --- system readiness --------------------------------------------------------


def test_system_reports_implementation_and_availability_separately():
    """A working legacy worker was presented as if Execution V2 were ready."""
    from app.ai_control_center.domain_gateway import _component
    worker = _component("worker", "Исполнение", "s", implemented=True, enabled=True,
                        mode="существующий Local worker", available=True)
    engine = _component("execution_v2", "Execution Engine V2", "s", implemented=False,
                        enabled=False, mode="не обслуживает запросы", available=False)
    assert worker["status"] == "active" and engine["status"] == "planned"
    assert engine["implemented"] is False and engine["available"] is False
    # The two are distinct records; neither inherits the other's readiness.
    assert worker["id"] != engine["id"] and worker["mode"] != engine["mode"]


def test_implemented_but_switched_off_component_is_not_reported_as_missing():
    from app.ai_control_center.domain_gateway import _component
    external = _component("external", "Внешние действия", "s", implemented=True,
                          enabled=False, mode="выключены", available=False)
    assert external["status"] == "disabled" and external["implemented"] is True


def test_readiness_grid_states_each_axis_for_the_owner():
    html = evaluate("ui.readinessGrid({implemented:false,enabled:false,available:false,"
                    "mode:'не обслуживает запросы',note:'Не реализован.'})")
    for label in ["Реализовано", "Включено", "Доступно сейчас", "Рабочий режим"]:
        assert label in html
    assert "Не отвечает" in html and "Не реализован." in html


def test_readiness_grid_is_omitted_for_records_without_those_facts():
    assert evaluate("ui.readinessGrid({title:'x'})") == ""
