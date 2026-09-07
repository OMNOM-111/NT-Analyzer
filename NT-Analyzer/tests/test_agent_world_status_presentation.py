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
import re
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
            "display_title": "Иван · Голос Court",
            "status": "review", "display_status": "awaiting_review",
            "display_status_label": "Ожидает вашей проверки",
            "is_active": False, "needs_attention": True,
            "stage": "provider_receipt", "stage_label": "Ответ модели получен",
            "task_class": "court_vote", "task_class_label": "Голос Court",
            "progress_pct": None, "synthetic": False, "updated_at": "2026-09-05T03:37:00Z"}
    return {**base, **overrides}


def workspace(tasks, agents=(), attention=None, stats=None) -> dict:
    rows = list(tasks)
    computed = presentation.counters(row.get("display_status") for row in rows)
    alerts = [row for row in rows
              if presentation.task_phase(row.get("display_status")) in presentation.ATTENTION_PHASES]
    return {"enabled": True, "scope": {"synthetic": False, "workspace_id": "ws"},
            "capabilities": {"can_run_demo": False}, "tasks": rows, "agents": list(agents),
            "outcomes": [], "activity": [],
            "attention": list(alerts if attention is None else attention),
            "stats": {**computed, "agents": len(agents), "attention": len(alerts),
                      "active_tasks": computed["executing"], "completed_tasks": computed["done"],
                      "results_received": computed["done"] + computed["result_unconfirmed"],
                      "failed": computed["failed"],
                      **(stats or {})}}


# --- server contract ---------------------------------------------------------


def test_phase_split_never_folds_review_or_blocked_into_execution():
    """The live Local reported active_tasks=0 while two review tasks were open."""
    counters = presentation.counters(
        ["awaiting_review", "awaiting_review", "failed", "completed",
         "verified_automatically", "blocked"])
    assert counters == {"executing": 0, "awaiting_review": 2, "awaiting_decision": 1,
                        "result_unconfirmed": 0, "done": 2, "failed": 1, "cancelled": 0}


def test_every_display_state_is_classified_exactly_once():
    """A new state in the single projection cannot slip through unplaced."""
    from app.ai_control_center.task_presentation import STATES
    for state in STATES:
        assert presentation.task_phase(state) in presentation.PHASE_LABELS, state
    # A received-but-unaccepted result is its own group: not finished, and not
    # blocked on anybody either.
    assert presentation.task_phase("result_received") == presentation.PHASE_RESULT_UNCONFIRMED
    assert presentation.task_phase("verified_automatically") == presentation.PHASE_DONE


def test_only_a_finished_task_reports_a_completion_percentage():
    """A failed/review task used to render a full 100 % bar beside its badge.

    Nothing measures partial completion here, so an unfinished task reports no
    number at all rather than a made-up one; the card shows its state instead.
    A result that arrived but was never accepted is explicitly not 100 %.
    """
    assert presentation.progress_pct("completed") == 100
    assert presentation.progress_pct("verified_automatically") == 100
    for state in ["running", "queued", "waiting_result", "awaiting_review",
                  "result_received", "failed", "rejected", "cancelled", "blocked", "planned"]:
        assert presentation.progress_pct(state) is None, state


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
    assert "Ожидают проверки" in result["html"]
    assert "В работе" in result["html"]


def test_awaiting_a_check_is_never_announced_as_awaiting_the_owner_decision():
    """Human confirmation is required only where the process provides for it.

    Folding both waiting phases under one heading would re-create the original
    conflation one level up: a task whose independent verification is simply
    outstanding would be announced as blocked on the owner.
    """
    review_only = render(workspace([task()]))
    assert "Ожидают проверки" in review_only["html"]
    assert "Ожидают вашего решения" not in review_only["html"]

    decision = render(workspace([task(status="blocked", display_status="blocked",
                                      display_status_label="Приостановлено: нужно решение")]))
    assert "Ожидают вашего решения" in decision["html"]

    # With both present the decision leads, because that one cannot proceed at all.
    both = render(workspace([task(),
                             task(id="33333333-3333-3333-3333-333333333333", status="blocked",
                                  display_status="blocked",
                                  display_status_label="Приостановлено: нужно решение")]))
    assert "Ожидают вашего решения" in both["html"]


def test_the_review_warning_does_not_demand_a_decision():
    reason, action = presentation.attention_reason(presentation.PHASE_AWAITING_REVIEW)
    decision_reason, decision_action = presentation.attention_reason(presentation.PHASE_AWAITING_DECISION)
    assert "решите" not in action and "Подтверждение требуется не везде." in action
    assert action != decision_action and reason != decision_reason


def test_executing_work_still_uses_the_in_progress_heading():
    result = render(workspace([task(status="running", display_status="running",
                                    display_status_label="Выполняется", is_active=True,
                                    needs_attention=False, progress_pct=None)]))
    assert "Сейчас в работе" in result["html"]


def test_truncated_attention_list_offers_a_route_to_the_remaining_items():
    """The counter said 4; only three cards were rendered and nothing linked on."""
    rows = [task(id=f"{n}{n}{n}{n}{n}{n}{n}{n}-1111-1111-1111-111111111111",
                 status="failed" if n % 2 else "review",
                 display_status="failed" if n % 2 else "awaiting_review") for n in range(1, 5)]
    result = render(workspace(rows))
    assert result["html"].count("aw-alert\"") == 3
    assert "Показать все (4)" in result["html"]
    assert 'data-aw-filter="attention"' in result["html"]


def test_attention_card_shows_why_and_what_to_do():
    reason, action = presentation.attention_reason(presentation.PHASE_AWAITING_REVIEW)
    rows = [task(reason=reason, action_hint=action, since="2026-09-05T03:37:00Z")]
    result = render(workspace(rows))
    assert reason in result["html"] and action in result["html"]


def test_unfinished_task_card_shows_its_state_instead_of_a_full_bar():
    result = render(workspace([task()]))
    assert "<progress" not in result["html"]
    # The card prints the projection's own label for the state it is in.
    assert "Ожидает вашей проверки" in result["html"]


def test_finished_task_card_still_shows_measured_progress():
    result = render(workspace([task(status="succeeded", display_status="completed",
                                    display_status_label="Проверка завершена",
                                    needs_attention=False, progress_pct=100)]))
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
    assert evaluate("ui.stageName('some_internal_stage')") == "См. состояние задачи"
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


# --- technical evidence placement --------------------------------------------


def test_long_hash_moves_out_of_the_sentence_but_is_still_available():
    """Evidence is relocated, never removed."""
    digest = "45ba864f7ccb06c9fba8655a4839378e1e9fd049d0d5f3d350567ae3081e9c40"
    split = evaluate("ui.technicalSplit(" + json.dumps(
        "Снимок рабочего стола: MNQ 09-26. SHA256: " + digest + " Это снимок Desktop.") + ")")
    assert digest not in split["prose"]
    assert any(digest in entry for entry in split["technical"])
    assert "Снимок рабочего стола" in split["prose"] and "Это снимок Desktop." in split["prose"]


def test_embedded_json_payload_moves_into_technical_details():
    split = evaluate("ui.technicalSplit(" + json.dumps(
        'Точность передачи фактов. {"trades":"64","strategy":"SampleMACrossOver"} Конец.') + ")")
    assert "{" not in split["prose"] and "SampleMACrossOver" not in split["prose"]
    assert "SampleMACrossOver" in "".join(split["technical"])
    assert split["prose"] == "Точность передачи фактов. Конец."


def test_plain_summary_is_left_untouched_and_gains_no_details_block():
    split = evaluate("ui.technicalSplit('Отчёт проверен. Сделок: 64.')")
    assert split == {"prose": "Отчёт проверен. Сделок: 64.", "technical": []}
    assert evaluate("ui.technicalDetails([], 'x')") == ""


def test_unparseable_brace_text_is_not_silently_swallowed():
    split = evaluate("ui.technicalSplit('Ошибка формата {не json Конец.')")
    assert "не json" in split["prose"] and split["technical"] == []


def test_inline_report_link_moves_to_details_without_a_dangling_label():
    split = evaluate("ui.technicalSplit(" + json.dumps(
        "Отчёт проверен. Сделок: 64. Оригинальный отчёт: "
        "/ui/backtesting.html?job=awnt_7ed6b329cead Это результат NinjaTrader.") + ")")
    assert "Оригинальный отчёт" not in split["prose"] and "/ui/" not in split["prose"]
    assert split["prose"] == "Отчёт проверен. Сделок: 64. Это результат NinjaTrader."
    assert split["technical"] == ["/ui/backtesting.html?job=awnt_7ed6b329cead"]


# --- Persona, role, provider account and model stay four separate records ----




def test_agent_face_is_an_explicit_stored_choice_not_the_name():
    agent = {"id": "aaaaaaaa-4444-1111-1111-111111111111", "display_name": "Толик",
             "availability": "active", "occupancy": "free", "synthetic": False,
             "evaluation": {"sample_size": 0}}
    without = render(workspace([], agents=[agent]))
    assert "Т" in without["html"]
    # An unapproved key must not resolve to a shipped agent asset either.
    assert render(workspace([], agents=[{**agent, "avatar_key": "../vitek"}]))["html"].count("aw-avatar") \
        == without["html"].count("aw-avatar")


def test_stage_text_already_written_for_a_reader_is_not_replaced():
    """The NinjaTrader and Desktop adapters send written stages, not enum keys."""
    for written in ["Ожидание NinjaTrader", "Выполняется в NinjaTrader",
                    "Изображение проверено", "Ожидание/проверка снимка Desktop"]:
        assert presentation.stage_label(written) == written
        assert evaluate("ui.stageName(" + json.dumps(written) + ")") == written
    assert presentation.stage_label("some_internal_stage") == "Этап: технические детали"
    assert presentation.stage_label("") == "Этап не указан"


def test_legacy_adapter_task_classes_have_labels_too():
    assert presentation.rubric_label("ninjatrader_historical_backtest") == "Исторический бэктест NinjaTrader"
    assert evaluate("ui.rubricLabel('ninjatrader_historical_backtest')") == "Исторический бэктест NinjaTrader"
    # An unknown machine key yields nothing so the caller can fall back; text
    # written for a reader is passed straight through.
    assert evaluate("ui.rubricLabel('unknown_machine_key')") == ""
    assert evaluate("ui.rubricLabel('Проверка соединения')") == "Проверка соединения"


def test_a_free_agent_shows_what_waits_on_the_owner_without_conflating_it():
    """Being free is not the same as having nothing outstanding.

    Found in the isolated Aurora run: a single chip covering both waiting
    phases announced a review task as «ждут решения», putting the owner on the
    hook for work that only needed looking at.
    """
    agent = {"id": "aaaaaaaa-5555-1111-1111-111111111111", "display_name": "Иван",
             "availability": "active", "occupancy": "free",
             "open_review": 1, "open_decision": 0,
             "synthetic": False, "evaluation": {"sample_size": 0}}
    def chips(state):
        """Only the agent-state chips; page copy elsewhere mentions both words."""
        html = render(workspace([], agents=[state]))["html"]
        found = re.findall(r'<span class="aw-agent-state">(.*?)</span></span>', html, re.S)
        return " ".join(found)

    review_only = chips(agent)
    assert "Свободен" in review_only and "1 на проверке" in review_only
    assert "решения" not in review_only

    deciding = chips({**agent, "open_review": 0, "open_decision": 2})
    assert "2 ждёт вашего решения" in deciding and "на проверке" not in deciding

    both = chips({**agent, "open_review": 1, "open_decision": 1})
    assert "1 ждёт вашего решения" in both and "1 на проверке" in both

    quiet = chips({**agent, "open_review": 0, "open_decision": 0})
    assert "на проверке" not in quiet and "решения" not in quiet


def test_every_agent_row_answers_both_questions_not_just_domain_ones():
    """The compatibility row is drawn by the same card as a domain agent.

    Found in the isolated Aurora run: legacy rows arrived without the new
    fields and rendered «Доступность не указана», because only the domain
    projection had been given them.
    """
    from app.ai_control_center import live_gateway
    source = Path(live_gateway.__file__).read_text(encoding="utf-8", errors="ignore")
    assert '"availability": "active"' in source and '"occupancy":' in source

    # And the page must still degrade honestly if a row somehow lacks them.
    bare = {"id": "aaaaaaaa-6666-1111-1111-111111111111", "display_name": "Legacy",
            "synthetic": False, "evaluation": {"sample_size": 0}}
    html = render(workspace([], agents=[bare]))["html"]
    assert "Доступность не указана" in html and "Свободен" in html


# --- adapter rows: evidence, not type, decides completion --------------------


def _display(row):
    from app.ai_control_center.task_presentation import project
    return project(row)["display_status"]


def test_a_finished_adapter_result_does_not_stay_in_progress():
    """A verified NinjaTrader report or Desktop snapshot is finished work.

    Before this, project() judged every row by the model-task fields, so an
    adapter row — which carries no provider receipt because its own executor
    verified it — came out as waiting_result and the owner saw a completed
    backtest reported as still running.
    """
    assert _display({"status": "succeeded", "source_kind": "ninjatrader_report",
                     "evidence_count": 3}) == "verified_automatically"
    assert _display({"status": "succeeded", "source_kind": "desktop_chart",
                     "evidence_count": 1}) == "verified_automatically"


def test_missing_or_broken_evidence_never_completes_on_the_strength_of_a_type():
    """Being an adapter row is not itself a result.

    live_backtests reports evidence_count as the number of verified source
    checksums and live_charts as 1 only when the snapshot verified, so zero
    means the executor could not confirm its own output. That is something a
    human has to look at — neither finished nor still running.
    """
    assert _display({"status": "succeeded", "source_kind": "ninjatrader_report",
                     "evidence_count": 0}) == "awaiting_review"
    assert _display({"status": "succeeded", "source_kind": "desktop_chart",
                     "evidence_count": 0}) == "awaiting_review"
    assert _display({"status": "succeeded", "source_kind": "desktop_chart"}) == "awaiting_review"


def test_an_unfinished_adapter_row_is_still_reported_as_running():
    assert _display({"status": "running", "source_kind": "ninjatrader_report",
                     "evidence_count": 0}) == "running"
    assert _display({"status": "failed", "source_kind": "ninjatrader_report",
                     "evidence_count": 3}) == "failed"


def test_a_model_result_is_not_completed_by_its_own_automatic_check():
    """Execution, automatic verification and owner acceptance stay distinct."""
    model = {"status": "succeeded", "source_kind": "real_model_response",
             "task_class": "json_arithmetic", "evaluation_id": "e1"}
    assert _display(model) == "result_received"
    from app.ai_control_center.task_presentation import project
    assert project(model, human_review={"status": "pending"})["display_status"] == "awaiting_review"
    assert project(model, human_review={"status": "accepted"})["display_status"] == "completed"
    assert project(model, human_review={"status": "rejected"})["display_status"] == "rejected"


def test_the_attention_filter_the_overview_links_to_is_actually_offered():
    """The overflow link on the warning panel targets this filter by name.

    Lost once during integration when the page module was rebased onto the
    other branch's filter set: taskMatches still understood 'attention' but the
    Работа tab no longer listed it, so the link led to a filter the owner could
    not see or clear.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "attention: 'Требуют внимания'" in source
    assert 'data-aw-filter="attention"' in source
    assert evaluate("ui.taskMatches({display_status:'awaiting_review'},'attention','')") is True
    assert evaluate("ui.taskMatches({display_status:'completed'},'attention','')") is False

def _adapter_row(**changes):
    """The shape live_backtests hands over: source status and its own progress."""
    return {"id": "a1", "status": "succeeded", "source_kind": "ninjatrader_report",
            "task_class": "ninjatrader_historical_backtest", "source_status": "done",
            "evidence_count": 3, "progress_pct": 100, **changes}


def test_an_adapter_row_reports_progress_from_its_state_not_its_source_status():
    """A full bar under a card that says the work is not finished.

    live_backtests derives progress from the source status alone, so a report
    that reached `done` but failed verification arrived carrying 100% while the
    projection put it in awaiting_review. The panel renders a progress element
    whenever the number is present, so the owner saw a completed bar on work
    that still needed a check. Failed and cancelled rows had the same problem.
    """
    from app.ai_control_center.domain_gateway import projected_task

    verified = projected_task(_adapter_row())
    assert verified["display_status"] == "verified_automatically"
    assert verified["progress_pct"] == 100

    for row, expected in ((_adapter_row(evidence_count=0), "awaiting_review"),
                          (_adapter_row(status="failed", source_status="failed"), "failed"),
                          (_adapter_row(status="cancelled", source_status="cancelled"), "cancelled"),
                          (_adapter_row(status="running", source_status="running",
                                        evidence_count=0, progress_pct=None), "running")):
        projected = projected_task(row)
        assert projected["display_status"] == expected
        assert projected["progress_pct"] is None, expected


def test_a_row_that_already_carries_a_computed_state_is_not_re_projected():
    """Model rows arrive projected; the seam must not form a second opinion."""
    from app.ai_control_center.domain_gateway import projected_task

    row = {"id": "m1", "status": "succeeded", "display_status": "awaiting_review",
           "display_status_label": "Ожидает вашей проверки", "progress_pct": 100}
    projected = projected_task(row)
    assert projected["display_status"] == "awaiting_review"
    assert projected["display_status_label"] == "Ожидает вашей проверки"
    assert projected["progress_pct"] is None

    accepted = projected_task({**row, "display_status": "completed", "progress_pct": None})
    assert accepted["progress_pct"] == 100

def test_a_row_that_needs_a_check_is_never_left_without_a_route():
    """The panel must not ask for a check and then offer nothing to do.

    An adapter row whose evidence failed verification is projected as awaiting
    review, but it carries no human-review record, so no accept or reject action
    exists for it. It used to render with no action, no link and no reason at
    all. It now says why acceptance is unavailable and points at the source it
    came from.
    """
    from app.ai_control_center.domain_gateway import projected_task

    stuck = projected_task(_adapter_row(evidence_count=0, actions=[],
                                        report_url="/ui/backtesting.html?job=awnt_x"))
    assert stuck["display_status"] == "awaiting_review"
    assert stuck["progress_pct"] is None
    assert any("принять" in line.lower() for line in stuck["limitations"])
    assert stuck["source_url"] == "/ui/backtesting.html?job=awnt_x"

    # A verified row is not annotated, and an off-site link is never surfaced.
    verified = projected_task(_adapter_row(report_url="/ui/backtesting.html?job=awnt_y"))
    assert "limitations" not in verified and "source_url" not in verified
    foreign = projected_task(_adapter_row(evidence_count=0, actions=[],
                                          report_url="https://example.invalid/report"))
    assert "source_url" not in foreign and foreign["limitations"]


def test_the_inspector_renders_the_reason_and_the_source_link():
    source = SCRIPT.read_text(encoding="utf-8")
    # The summary tab reads both fields the server now supplies, and only ever
    # links to an in-app path.
    assert "rows(task.limitations)" in source
    assert "aw-limitations" in source
    assert "String(task.source_url || '').startsWith('/ui/')" in source
    assert "Открыть исходный отчёт" in source
