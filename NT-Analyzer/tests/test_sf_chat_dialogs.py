"""Application-local decisions: shipped JS runs without real user data or providers."""
from pathlib import Path
import json
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app/static/aurora"
ACTIONS = ["orchNewConversation", "orchSelectConversation", "orchDelete", "orchRename",
           "orchToggleConversationState", "orchAddFolder", "orchMoveToFolder"]


def run_case(**scenario):
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("sf_chat_dialog_harness.cjs"))],
        input=json.dumps(scenario), capture_output=True, text=True, encoding="utf-8",
        cwd=ROOT, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "PASS"


@pytest.mark.parametrize("mode", ["accept", "cancel", "close_button", "escape", "native_cancel",
    "removed", "hashchange", "pagehide", "unsupported", "duplicate", "focus",
    "input_accept", "input_cancel", "input_empty", "input_empty_allowed"])
def test_application_dialog_lifecycle(mode):
    run_case(kind="helper", mode=mode)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("mode", ["accept", "cancel", "stale", "auth_stale", "sending"])
def test_chat_actions_await_explicit_consent_and_keep_cancelled_state(action, mode):
    run_case(kind="chat", action=action, mode=mode)


@pytest.mark.parametrize("mode", ["duplicate", "network_duplicate", "api_error", "finished"])
def test_new_conversation_is_single_dispatch_and_unlocks_after_response(mode):
    run_case(kind="chat", action="orchNewConversation", mode=mode)


@pytest.mark.parametrize("action", ["orchDelete", "orchRename", "orchToggleConversationState"])
def test_human_threads_cannot_use_ai_conversation_mutations(action):
    run_case(kind="chat", action=action, mode="human")


def test_empty_folder_is_different_from_cancelling():
    run_case(kind="chat", action="orchMoveToFolder", mode="empty_folder")


@pytest.mark.parametrize("mode", ["accept", "cancel"])
def test_inbox_clear_requires_consent_and_restores_cancelled_trigger_focus(mode):
    run_case(kind="inbox", mode=mode)


def test_no_native_browser_dialogs_in_sf_chat_or_ai_center():
    source = (AURORA / "assets/ui.js").read_text(encoding="utf-8")
    chat = source.split("// ---- global orchestrator chat widget", 1)[1]
    native = r"\b(?:confirm|prompt|alert)\s*\("
    assert not re.search(native, chat)
    assert not re.search(native, (AURORA / "assets/pages/ai-command-center.js").read_text(encoding="utf-8"))
    assert not re.search(r"window\.(?:confirm|prompt|alert)\s*=", source)
    assert "if (ORCH.sending || ORCH.dialogActionPending) return;" in chat
    inbox = source.split("const clearAll = qs('[data-inbox-clear-all]'", 1)[1].split("qsa('[data-inbox-open]'", 1)[0]
    assert "await confirmDialog(" in inbox and not re.search(native, inbox)
    assert "if (!confirmed && clearAll.isConnected) clearAll.focus" in inbox


def test_shared_shell_cache_and_dialog_style_are_shipped_together():
    for page in AURORA.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        if 'src="assets/ui.js?' in html:
            assert 'src="assets/ui.js?v=20260905-app-dialogs"' in html, page.name
            assert 'href="assets/theme.css?v=20260905-app-dialogs"' in html, page.name
    css = (AURORA / "assets/theme.css").read_text(encoding="utf-8")
    assert ".app-dialog::backdrop" in css and ".app-dialog :focus-visible" in css
