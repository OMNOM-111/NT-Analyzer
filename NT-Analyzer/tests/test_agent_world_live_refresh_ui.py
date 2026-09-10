"""Read-only refresh contracts; browser acceptance is recorded separately."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", ["navigation", "form", "hidden", "audio", "selection", "search",
    "singleflight", "disposed", "task", "profile", "closed-while-reading", "scope-change", "read-denied",
    "profile-removed", "late-form-success", "late-form-error", "late-form-denied", "late-search", "late-selection",
    "pages", "cursor-cycle", "quiet-drawer-focus", "selection-while-reading-task"])
def test_shipped_refresh_keeps_shared_state_without_mutations_or_focus_interruptions(case):
    result = subprocess.run(["node", "tests/agent_world_refresh_ui_harness.cjs", case],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert '"ok":true' in result.stdout


def test_refresh_reuses_existing_aurora_poll_lifecycle_and_keeps_words_readable():
    source = (ROOT / "app/static/aurora/assets/pages/ai-command-center.js").read_text(encoding="utf-8")
    style = (ROOT / "app/static/aurora/assets/pages/ai-command-center.css").read_text(encoding="utf-8")
    assert "UI.poll?.(() => refresh({ background: true }), 5000)" in source
    assert "setInterval(" not in source
    assert ".aw-table td { overflow-wrap: break-word; }" in style
    assert ".aw-table td:nth-child(4) { min-width: 125px; }" in style
    assert "overflow-x: auto" in style
