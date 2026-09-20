"""The previous architecture's screens leave the working path and stay read-only."""
from __future__ import annotations

from pathlib import Path

import pytest

AURORA = Path(__file__).resolve().parents[1] / "app" / "static" / "aurora"
# The screens kept only for сверка; nothing of the working path goes through them.
ARCHIVED = ("ai-agents.html", "ai-lab.html")
WORKING = ("index.html", "backtesting.html", "trading.html", "desktop.html", "performance.html",
           "strategies.html", "news.html", "community.html", "topstep.html", "practice-trading.html",
           "ai-command-center.html", "documents.html")


@pytest.mark.parametrize("page", WORKING)
def test_the_old_chief_of_staff_widget_is_not_loaded_on_a_working_page(page):
    assert "victor.js" not in (AURORA / page).read_text(encoding="utf-8")


@pytest.mark.parametrize("page", ARCHIVED)
def test_an_archived_screen_is_kept_whole_but_cannot_change_anything(page):
    text = (AURORA / page).read_text(encoding="utf-8")
    # Not renamed, not gutted: it still is the old screen, for reading.
    assert "legacy-guard.js" in text
    guard = (AURORA / "assets" / "legacy-guard.js").read_text(encoding="utf-8")
    assert "Действия отсюда отключены" in guard
    # Every write is refused before it leaves the page, however it is sent.
    assert "window.fetch = function" in guard and "XMLHttpRequest.prototype.open" in guard
    assert "SAFE = { GET: 1, HEAD: 1, OPTIONS: 1 }" in guard


def test_the_duty_panel_left_the_strategies_page_without_breaking_it():
    page = (AURORA / "strategies.html").read_text(encoding="utf-8")
    assert "vitek-panel" not in page and "vitek-incidents" not in page
    script = (AURORA / "assets" / "pages" / "strategies.js").read_text(encoding="utf-8")
    # The code stays, inert: it asks for the panel before it paints or polls.
    for guard in ("function renderVitek() {\n    if (!vitekDoc || !UI.qs('#vitek-panel')) return;",
                  "if (vitekLoading || !UI.qs('#vitek-panel')) return;",
                  "if (vitekLoading || document.hidden || !UI.qs('#vitek-panel')) return;"):
        assert guard in script
    assert "typeof Victor === 'undefined'" in script
    # The panel's own buttons are wired only while the panel exists.
    assert "if (UI.qs('#vitek-panel')) {" in script


def test_the_old_entries_leave_the_rail_once_the_agent_world_is_on():
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "const LEGACY_NAV_IDS = new Set(['agents']);" in ui
    assert "if (worldEnabled && LEGACY_NAV_IDS.has(id)) {" in ui


def test_the_documentation_section_stays_in_the_product():
    """«Документы» is the product's own documentation base, not a legacy screen."""
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    nav = ui.split("const NAV = [", 1)[1].split("];", 1)[0]
    lines = [line for line in nav.splitlines() if "data-nav" not in line and line.strip().startswith("{")]
    ids = [line.split("id: '", 1)[1].split("'", 1)[0] for line in lines]
    # Its own place in the rail, below TopStep, and nothing hides it.
    assert ids[-2:] == ["topstep", "docs"]
    assert "legacy-guard" not in (AURORA / "documents.html").read_text(encoding="utf-8")
    page = (AURORA / "assets" / "pages" / "ai-command-center.js").read_text(encoding="utf-8")
    assert "documents.html" not in page


def test_no_working_view_sends_anyone_to_an_archived_screen():
    """A link into the archive from a working view is a legacy dependency."""
    for name in ("assets/pages/ai-command-center.js", "assets/pages/strategies.js",
                 "assets/pages/documents.js", "assets/pages/desktop.js"):
        text = (AURORA / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "ai-lab.html" in line or "ai-agents.html" in line:
                # Only the archive listing may name them, and only with ?legacy=1.
                assert "legacy=1" in line, f"{name}: {line.strip()[:90]}"


def test_the_ai_center_says_where_the_old_screens_went():
    script = (AURORA / "assets" / "pages" / "ai-command-center.js").read_text(encoding="utf-8")
    listing = script.split("const LEGACY_SCREENS", 1)[1].split("function legacyCard()", 1)[0]
    for page in ARCHIVED:
        assert page in listing
    # The documentation base is not among them; it is a section of its own.
    assert "documents.html" not in listing
    assert "Убраны из рабочего пути" in script


def test_the_deputy_carries_the_duty_controllers_questions():
    script = (AURORA / "assets" / "pages" / "ai-command-center.js").read_text(encoding="utf-8")
    assert "API.aiControlCenterDutyDecide(" in script and "API.aiControlCenterDutyAnswer(" in script
    assert "data-aw-duty=\"pause\"" in script or "data-aw-duty='pause'" in script
    card = script.split("function dutyQuestions()", 1)[1].split("async function dutyDecide(", 1)[0]
    assert "Нужно ваше решение" in card and "принёс Заместитель" in card
