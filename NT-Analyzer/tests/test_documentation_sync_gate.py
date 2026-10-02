"""Regression coverage for the repository-root documentation contract."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_documentation_sync as gate  # noqa: E402


def test_current_timeline_and_ai_context_agree():
    assert gate.validate() == []


def test_code_change_requires_timeline_and_current_handoff(monkeypatch):
    monkeypatch.setattr(gate, "_changed", lambda _base: ["NT-Analyzer/app/server.py"])
    errors = gate.validate("main-parent")
    assert any("Timeline + AI_CONTEXT sync" in error for error in errors)


def test_done_card_cannot_keep_unresolved_blocker(monkeypatch, tmp_path):
    html = gate.TIMELINE.read_text(encoding="utf-8")
    html = html.replace("current:true,workStatus:'in_progress'", "current:true,workStatus:'done',unresolvedBlockers:['unverified']", 1)
    candidate = tmp_path / "timeline.html"
    candidate.write_text(html, encoding="utf-8")
    monkeypatch.setattr(gate, "TIMELINE", candidate)
    errors = gate.validate()
    assert any("Done current card has unresolved blockers" in error for error in errors)
