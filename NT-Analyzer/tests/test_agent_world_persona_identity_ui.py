"""Shipped selectors/transports: executable handlers, not a browser QA claim."""
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_agent_world_ui import evaluate, ROOT, SCRIPT, AURORA


def run(kind, mode=""):
    result = subprocess.run(["node", str(Path(__file__).with_name("persona_identity_ui_harness.cjs"))],
        input=json.dumps({"kind": kind, "mode": mode}), capture_output=True, text=True,
        encoding="utf-8", cwd=ROOT, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "PASS"


@pytest.mark.parametrize("mode", ["selected", "main", "missing", "suspended", "invalid", "human", "failure", "rejected", "ambiguous"])
def test_actual_send_uses_uuid_metadata_preserves_text_and_never_falls_back(mode):
    run("send", mode)


@pytest.mark.parametrize("mode", ["select", "human", "sending"])
def test_actual_picker_has_no_submit_side_effect_and_keeps_human_threads_separate(mode):
    run("picker", mode)


@pytest.mark.parametrize("mode", ["pagination", "revoked", "malformed", "loop"])
def test_catalog_is_complete_scoped_and_drops_late_replies_after_auth_loss(mode):
    run("catalog", mode)


@pytest.mark.parametrize("mode", ["selected", "legacy", "invalid", "recovery"])
def test_real_stream_transport_has_only_optional_persona_uuid(mode):
    run("transport", mode)


def test_pending_uuid_avatar_never_falls_back_to_a_different_named_agent():
    run("face")


def test_reused_drawer_accessible_name_tracks_current_visible_heading():
    run("drawer")


def test_closed_drawer_is_inert_and_pending_frame_cannot_reopen_it():
    run("drawer", "close-before-frame")


@pytest.mark.parametrize("mode", ["known", "private", "uncertain"])
def test_chat_error_is_readable_bounded_and_never_resends_or_exposes_payload(mode):
    run("error", mode)


def test_persona_form_round_trips_aliases_main_and_preserves_old_client_payloads():
    result = evaluate("ui.domainPayload('personas','update',{name:'Марина',aliases:'Маруся\\nLead',main_assistant:'true',avatar_key:'marina'})")
    assert result["aliases"] == ["Маруся", "Lead"] and result["main_assistant"] is True
    cleared = evaluate("ui.domainPayload('personas','update',{name:'Марина',aliases:'',main_assistant:'false'})")
    assert cleared["aliases"] == [] and cleared["main_assistant"] is False
    old = evaluate("ui.domainPayload('personas','update',{name:'Марина'})")
    assert "aliases" not in old and "main_assistant" not in old


def test_main_conflict_has_actionable_instruction_not_a_raw_code():
    message = evaluate("ui.domainError({code:'persona_main_already_assigned'})")
    assert "Сначала" in message and "сохраните" in message and "persona_main" not in message


def test_assistant_response_is_only_a_single_task_option_with_human_review():
    for domain, action, allowed in (("models", "task", True), ("experiments", "create", False), ("automation", "propose", False)):
        fields = evaluate(f"ui.domainFormFields('{domain}','{action}')")
        rubric = next(field for field in fields if field["key"] == "rubric_key")
        assert any(option[0] == "assistant_response" for option in rubric["options"]) is allowed
    assert "ручная проверка" in evaluate("ui.rubricLabel('assistant_response')")


def test_external_protocol_is_read_only_server_evidence_not_a_ui_grant():
    model = {"protocol": "chat_completions_v1", "capabilities": {"text": True,
        **{key: False for key in ("remote_tools", "remote_tasks", "mcp", "a2a", "artifacts")}}}
    value = evaluate(f"ui.modelProtocolCard({json.dumps(model)})")
    assert "Текстовый HTTPS-исполнитель" in value and "не поддерживаются" in value
    assert "<input" not in value and "<select" not in value
    for changes in ({"protocol": "mcp"}, {"capabilities": {"text": "true"}}):
        value = evaluate(f"ui.modelProtocolCard({json.dumps({**model, **changes})})")
        assert "не подтверждены" in value and "<input" not in value
    source = SCRIPT.read_text(encoding="utf-8")
    assert "domainState.key === 'models' ? modelProtocolCard(item)" in source
    assert "key === 'models' ? modelProtocolCard(item)" in source


def test_persona_picker_uses_existing_compose_not_new_navigation_or_storage():
    source = (AURORA / "assets/ui.js").read_text(encoding="utf-8")
    selector = source.split("function orchPersonaOptions(", 1)[1].split("function orchLoadLastId(", 1)[0]
    assert "#orch-model-picker" in selector and "localStorage" not in selector
    assert "personaOptions" in source.split("async function orchSend()", 1)[1]
    assert "...personaChatOptions(options)" in (AURORA / "assets/api.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("classification", [{"task_class": "assistant_response"},
    {"rubric_key": "assistant_response"}, {"verification_scope": "transport_only"}])
def test_transport_receipt_cannot_be_presented_as_professional_quality(classification):
    # Even a malformed old/client score cannot override the server's class.
    value = {"sample_size": 3, "passed": 3, "score_pct": 100, "observed_score_pct": 100,
             "confidence": "high", **classification}
    result = evaluate(f"ui.evaluationMeta({json.dumps({'evaluation': value})})")
    assert result["score"] is None and result["observed"] is None
    assert result["confidence"] == "не оценена" and "без рейтинга" in result["label"]
    assert "100" not in result["label"]


@pytest.mark.parametrize("review", ["pending", "accepted", "rejected"])
def test_actual_chat_card_distinguishes_transport_from_human_decision(review):
    from tests.test_agent_world_result_presentation import chat_render
    identity = "11111111-1111-1111-1111-111111111111"
    row = {"role": "assistant", "source": "agent_world_local", "content": "Ответ помощника",
        "actions": [{"task_id": identity, "source_kind": "real_model_response", "status": "completed"}],
        "_awLatest": True, "_awTask": {"id": identity, "task_class": "assistant_response",
            "verification_status": "passed", "display_status": "awaiting_review" if review == "pending" else "completed",
            "human_review": {"status": review}, "actions": ["review_result"] if review == "pending" else []}}
    output = chat_render(row)
    assert output["unchanged"]
    assert "Техническая проверка получения ответа: пройдена" in output["html"]
    assert "Содержание автоматически не оценено" in output["html"]
    assert "В профессиональный рейтинг не входит" in output["html"]
    assert ('data-aw-chat-review="accept"' in output["html"]) is (review == "pending")


@pytest.mark.parametrize("latest", [True, False])
def test_saved_nested_transport_proof_is_readable_without_claiming_current_acceptance(latest):
    from tests.test_agent_world_result_presentation import chat_render
    row = {"role": "assistant", "source": "agent_world_local", "content": "Сохранённый текст",
        "actions": [{"task_id": "11111111-1111-1111-1111-111111111111", "status": "completed",
            "source_kind": "real_model_response", "verification": {"scope": "transport_only", "passed": True}}],
        "_awLatest": latest}
    result = chat_render(row)
    assert result["unchanged"] and "Содержание автоматически не оценено" in result["html"]
    assert 'data-aw-chat-review=' not in result["html"]
    if latest:
        assert "Текущее состояние задачи недоступно" in result["html"]
