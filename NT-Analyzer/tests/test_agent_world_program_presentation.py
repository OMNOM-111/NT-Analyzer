"""Program review read projections; fixtures are not live provider evidence."""
import json

from tests.test_agent_world_ui import evaluate


def application_agent(**change):
    return {"display_name": "Researcher", "synthetic": False, "application_observations": [{
        "model": "Example", "connection_status": "active", "mode": "real_application_execution_conformance",
        "classes": [{"application_kind": "backtest", "sample_size": 1, "receipt_count": 2,
                     "passed": 1, "failed": 0, "score_pct": None, "confidence": "insufficient"}]}], **change}


def test_real_application_rows_are_distinct_from_arithmetic_and_synthetic():
    agent = application_agent()
    result = evaluate(f"ui.applicationRows({json.dumps(agent)})")
    assert result[0]["label"] == "NEW" and result[0]["sample_size"] == 1
    assert result[0]["receipt_count"] == 2
    assert evaluate(f"ui.applicationRows({json.dumps({**agent, 'synthetic': True})})") == []
    assert evaluate("ui.applicationRows({synthetic:false,model_observations:[{score_pct:100}]})") == []


def test_table_escapes_labels_and_explains_denominator():
    agent = application_agent(display_name="<script>bad</script>")
    html = evaluate(f"ui.applicationTable([{json.dumps(agent)}])")
    assert "<script>bad" not in html and "&lt;script&gt;" in html
    assert "Бэктест" in html and "NEW" in html
    assert "повтор одного входа" in html.lower() and "не усредняются" in html


def test_latest_votes_do_not_hide_verified_application_evidence_or_rewrite_history():
    values = [
        {"task_id": "vote", "synthetic": False, "source_kind": "real_model_response", "status": "succeeded"},
        {"task_id": "nt", "synthetic": False, "source_kind": "real_model_response", "status": "succeeded",
         "application_result": {"verified": True, "source_kind": "ninjatrader_report", "source_id": "actual-source"}},
        {"task_id": "fixture", "synthetic": True, "status": "succeeded",
         "application_result": {"verified": True, "source_kind": "desktop_chart"}},
    ]
    result = evaluate("(() => { const values=" + json.dumps(values) +
                      ";return {sorted:ui.overviewOutcomes({outcomes:values}), original:values};})()")
    assert [value["task_id"] for value in result["sorted"]] == ["nt", "vote", "fixture"]
    assert result["original"] == values


def test_no_verified_application_does_not_invent_a_score():
    html = evaluate("ui.applicationTable([{synthetic:false}])")
    assert "ещё не проверены" in html and "100%" not in html


def test_followup_only_claims_delivery_after_actual_receipt_and_is_not_an_agent_score():
    value = {"synthetic": False, "automation_enabled": False, "status": "queued",
             "conversation_id": "AW-FU-" + "a" * 28, "source_revision": 2}
    queued = evaluate("ui.followupCard(" + json.dumps({"followup_chat": value}) + ")")
    assert "data-aw-followup-chat" not in queued and "Автоматизация выключена" in queued
    delivered = evaluate("ui.followupCard(" + json.dumps({"followup_chat": {**value,
        "status": "delivered", "message_id": "actual-message"}}) + ")")
    assert "data-aw-followup-chat" in delivered and "не выполненное задание модели" in delivered
    assert "data-orch-rate" not in delivered


def test_handoff_form_accepts_only_a_selected_model_not_client_authority():
    target = "12345678-1234-1234-1234-123456789abc"
    values = {"target_model_id": target, "budget": 1000, "facts": {"private": "no"}}
    for domain in ("tasks", "model_tasks"):
        assert evaluate(f"ui.domainPayload('{domain}','handoff'," + json.dumps(values) + ")") == {"target_model_id": target}
    fields = evaluate("ui.domainFormFields('tasks','handoff')")
    assert fields[0]["type"] == "model"
    assert "не анализ стратегии" in fields[0]["hint"]


def test_connect_guide_names_the_actual_secret_field_without_any_secret():
    guide = evaluate("ui.modelConnectionGuide()")
    assert "openrouter.ai/settings/keys" in guide and "openrouter/free" in guide
    assert "Ключ подключения" in guide and "Owner-ключи не копируются" in guide
    assert "MCP" in guide and "chat-completions" in guide
