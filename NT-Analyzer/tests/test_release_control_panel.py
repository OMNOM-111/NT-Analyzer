"""The Environment Switcher is the release control panel.

It used to lead with probe and "просмотреть переход" buttons and an engineering
comparison table, so the owner had to assemble the workflow themselves. These
tests pin the shape the panel must keep: three stages in order, one action per
stage, identifiers behind a disclosure.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import release_publish

AURORA = Path(release_publish.__file__).resolve().parents[1] / "app" / "static" / "aurora" / "assets"
UI = (AURORA / "ui.js").read_text(encoding="utf-8")
CSS = (AURORA / "theme.css").read_text(encoding="utf-8")


def _panel() -> str:
    start = UI.index("function renderEnvironmentTargets(")
    return UI[start:UI.index("\n  }\n", UI.index("admin-env-compare", start))]


def test_stages_render_in_release_order() -> None:
    assert "const RELEASE_ORDER = ['development', 'canary', 'production'];" in UI
    panel = _panel()
    assert "RELEASE_ORDER.indexOf(a.environment) - RELEASE_ORDER.indexOf(b.environment)" in panel
    assert "stage-arrow" in panel, "the flow between stages must be visible"
    assert ".stage-flow" in CSS


@pytest.mark.parametrize("removed", [
    "Просмотреть переход",
    "Сравнить Canary / Production в отдельных вкладках",
])
def test_retired_first_level_actions_are_gone(removed: str) -> None:
    """Retired everywhere: these strings existed only on this panel."""
    assert removed not in UI


def test_no_per_environment_refresh_button_on_the_first_level() -> None:
    """Scoped to this panel: other screens keep their own refresh controls."""
    panel = _panel()
    first_level = panel[:panel.index("env-diagnostics")]
    assert "data-env-probe" not in first_level
    assert ">Обновить<" not in first_level


def test_manual_refresh_survives_only_as_a_secondary_action() -> None:
    panel = _panel()
    diagnostics = panel[panel.index("env-diagnostics"):]
    assert "env-refresh" in diagnostics
    assert "Технические данные / Диагностика" in panel
    # The comparison table must not sit on the first level any more.
    assert panel.index("data-env-compare") > panel.index("env-diagnostics")


def test_panel_refreshes_itself() -> None:
    assert "ENV_PANEL_TIMER" in UI
    assert "renderEnvironmentSwitcherInto(node)" in UI
    assert "document.body.contains(node)" in UI, "a closed panel must stop polling"


def test_each_stage_offers_exactly_one_action() -> None:
    assert "function stageActionHtml(" in UI
    action = UI[UI.index("function stageActionHtml("):UI.index("function stageCardHtml(")]
    # Development deploys, Canary accepts then publishes, Production is a
    # destination and offers nothing.
    assert "data-stage-deploy" in action
    assert "data-stage-accept" in action
    assert "data-stage-publish" in action
    assert action.count("data-stage-publish") == 1


def test_publish_button_requires_canary_passed() -> None:
    action = UI[UI.index("function stageActionHtml("):UI.index("function stageCardHtml(")]
    publish = action[action.index("data-stage-publish") - 400:action.index("data-stage-publish")]
    assert "state === 'canary_passed'" in publish
    assert "releases.promote_production" in publish


def test_canary_card_states_pass_explicitly() -> None:
    status = UI[UI.index("function stageStatusHtml("):UI.index("function stageActionHtml(")]
    assert "Canary PASS" in status
    assert "canary_passed" in status
    assert "Локальный сервер не запущен" in status


def test_publication_stages_render_inside_the_card_that_started_them() -> None:
    panel = _panel()
    assert "data-stage-progress" in panel
    assert "button.closest('[data-stage-env]')" in panel
    assert "Production развёрнут, validation failed" in panel
    assert "Пересборки не будет" in panel


def test_the_panel_does_not_send_the_owner_to_another_screen() -> None:
    panel = _panel()
    for row in ("releasePublish", "pipeRunStep"):
        assert row in panel, f"{row} must run from the panel itself"


def test_probe_refreshes_the_status_line_it_can_change() -> None:
    """A card must not show a known version beside "Состояние неизвестно".

    The status line sits outside the metadata block, so a probe that changes
    reachability has to re-render it as well.
    """
    panel = _panel()
    assert "const restate = ()" in panel
    assert "probeEnvironmentTarget(target, card).then(restate)" in panel
    assert "restate();" in panel, "a failed probe must restate too"


def test_blocked_publication_states_its_reason_on_the_card() -> None:
    """A disabled button whose reason lives only in a tooltip reads as broken."""
    action = UI[UI.index("function stageActionHtml("):UI.index("function stageCardHtml(")]
    assert "stage-blocked" in action
    assert "Недоступно: " in action
    assert ".stage-blocked" in CSS
