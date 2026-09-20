"""Actual shared SF Chat handlers with local in-memory DOM/audio, no browser proof."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = ["binding_is_silent", "hover_is_silent", "saved_message_metadata_not_dom_text_or_model",
    "model_independent_identity", "renamed_persona_preserves_old_label", "missing_persona_is_not_vitek_or_technical_uuid",
    "unconfigured_or_suspended_has_no_action", "legacy_uses_local_preset_not_owner_transport", "human_no_persona_speech",
    "explicit_stop_during_pending_transport", "shared_playback_stops_other_persona_surface", "module_loading_cancel_is_safe",
    "module_failure_is_text_fallback", "navigate_during_module_load", "pagehide_stops_audio", "hashchange_stops_audio",
    "hidden_stops_audio", "revoked_voice_never_falls_back_with_client_text", "network_failure_does_not_claim_saved_source",
    "mismatched_server_receipt_denies_local_voice", "missing_device_voice_is_text", "domain_fetches_uuid_once_not_model",
    "foreign_dto_and_fetch_failure_are_not_cached_as_persona", "stop_before_transport_microtask",
    "canonical_review_readonly_history", "canonical_review_current_state_not_legacy_marks",
    "canonical_review_ordinary_legacy_message_unchanged", "canonical_review_marker_matches_backend_not_lookalike_payload",
    "late_face_asset_stays_stopped"]


@pytest.mark.parametrize("mode", CASES)
def test_shipped_persona_chat_handler(mode):
    result = subprocess.run(["node", str(Path(__file__).with_name("persona_chat_ui_harness.cjs"))],
        cwd=ROOT, input=json.dumps({"mode": mode}), text=True, encoding="utf-8", capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "PASS"


def test_shared_chat_loads_persona_state_before_render_and_binds_explicit_action():
    source = (ROOT / "app/static/aurora/assets/ui.js").read_text(encoding="utf-8")
    load = source.split("async function orchLoadMessages(cid, silent)", 1)[1].split("async function orchSend()", 1)[0]
    assert load.index("await orchPersonaViews(messages, cid)") < load.index("orchMessagesHtml(messages)")
    assert "row._persona" in load and "wireOrchSpeech(box, messages, cid)" in load
    assert "agentSpeakStop();" in load
    faces = source.split("function wireAgentFaces(root)", 1)[1].split("const NAV =", 1)[0]
    assert "agentSpeakFromFace(" not in faces
    assert "speechSynthesis.speak(" not in faces


def test_same_persona_audio_module_is_cache_coherent_with_page_and_shared_lazy_loader():
    root = ROOT / "app/static/aurora"
    version = "20260908-agent-world-persona-chat1"
    assert f'assets/persona-audio.js?v={version}' in (root / "ai-command-center.html").read_text(encoding="utf-8")
    assert f'/ui/assets/persona-audio.js?v={version}' in (root / "assets/ui.js").read_text(encoding="utf-8")
