"""The Environment Switcher is the release control panel.

These pin the shape the panel must keep: three stages in order, one action per
stage that runs the whole workflow, identity and diagnostics behind
disclosures, and an auto-refresh that updates the screen without resetting what
the reader is looking at.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import release_publish

AURORA = Path(release_publish.__file__).resolve().parents[1] / "app" / "static" / "aurora" / "assets"
UI = (AURORA / "ui.js").read_text(encoding="utf-8")
CSS = (AURORA / "theme.css").read_text(encoding="utf-8")


def _slice(start: str, end: str) -> str:
    return UI[UI.index(start):UI.index(end)]


def _panel() -> str:
    return _slice("function renderEnvironmentTargets(",
                  "  // ---- Environments and releases (one module)")


def test_stages_render_in_release_order() -> None:
    assert "const RELEASE_ORDER = ['development', 'canary', 'production'];" in UI
    panel = _panel()
    assert "RELEASE_ORDER.indexOf(a.environment) - RELEASE_ORDER.indexOf(b.environment)" in panel
    assert "stage-arrow" in panel
    assert ".stage-flow" in CSS


@pytest.mark.parametrize("removed", [
    "Просмотреть переход",
    "Сравнить Canary / Production в отдельных вкладках",
    "Открыть Canary и Production во вкладках",
])
def test_retired_controls_are_gone(removed: str) -> None:
    """Moving between environments lives in the top navigation now."""
    assert removed not in UI


def test_this_panel_has_no_manual_refresh_button() -> None:
    """Scoped to this panel: the registry drawer keeps its own control."""
    panel = _panel()
    assert "env-refresh" not in panel
    assert "Обновить данные" not in panel


# --------------------------------------------------------------------------- #
# The refresh must not reset the screen.
# --------------------------------------------------------------------------- #
def test_refresh_updates_in_place_instead_of_rebuilding() -> None:
    panel = _panel()
    # The skeleton is built once; after that only slots are patched.
    assert "if (!qs('.stage-flow', node))" in panel
    assert "patchCard(card, target" in panel
    patch = _slice("function patchSlot(", "function patchCard(")
    assert "if (slot && slot.innerHTML !== html)" in patch, (
        "an unchanged slot must not be rewritten")


def test_open_disclosures_survive_a_refresh() -> None:
    """The details element itself is never replaced, only its contents."""
    skeleton = _slice("function stageCardSkeleton(", "function patchSlot(")
    assert "<details class=\"env-tech\">" in skeleton
    assert "data-slot=\"tech\"" in skeleton
    patch = _slice("function patchCard(", "function renderEnvironmentTargets(")
    assert "patchSlot(card, 'tech'" in patch
    assert "<details" not in patch, "patching must not recreate the disclosure"


def test_a_running_operation_is_not_overwritten_by_a_poll() -> None:
    patch = _slice("function patchCard(", "function renderEnvironmentTargets(")
    assert "if (!card.dataset.busy)" in patch


# --------------------------------------------------------------------------- #
# One action per stage, with visible progress.
# --------------------------------------------------------------------------- #
def test_each_card_explains_its_own_version() -> None:
    summary = _slice("function summaryHtml(", "function statusHtml(")
    assert "summary_title" in summary
    assert "env-summary" in summary
    skeleton = _slice("function stageCardSkeleton(", "function patchSlot(")
    assert "data-slot=\"summary\"" in skeleton, "the summary belongs inside the card"
    assert "stage-shared" not in UI, "a single block above the flow is not enough"


def test_candidate_visibly_identifies_what_is_being_released() -> None:
    record = _slice("function pipeReleaseRecordHtml(", "function pipeCandidateHtml(")
    for field in (
        "release_record", "change_summary", "prs", "source_sha", "current_stage",
        "status", "build_id", "artifact_id", "duration_seconds",
        "verification_checks", "Development → Canary", "Canary → Production",
        "тот же artifact без rebuild",
    ):
        assert field in record
    assert "Production BLOCKED" in record
    assert "pipeReleaseRecordHtml(doc)" in _slice(
        "function pipeCandidateHtml(", "function pipeNotificationsHtml(")


def test_delivery_and_publication_are_each_one_action() -> None:
    actions = _slice("function actionsHtml(", "function checksHtml(")
    assert "data-stage-deliver" in actions
    assert "data-stage-publish" in actions
    # The internal steps must not be offered as separate buttons.
    for retired in ("data-stage-deploy", "data-stage-accept", "Принять Canary"):
        assert retired not in UI


def test_progress_shows_which_step_is_running() -> None:
    assert "const DELIVER_STAGES" in UI
    assert "const PUBLISH_STAGES" in UI
    for label in ("Создание кандидата", "Сборка", "Проверка", "Развёртывание",
                  "Canary checks / acceptance", "Готово"):
        assert label in UI
    for label in ("Подтверждение", "Readiness", "Smoke"):
        assert label in UI
    progress = _slice("function progressHtml(", "function finalStagesHtml(")
    assert "'running'" in progress
    assert "spinner" in progress, "a step that takes time needs a visible running state"
    assert ".pub-stage.is-running" in CSS


def test_the_button_is_locked_while_the_operation_runs() -> None:
    runner = _slice("async function runStagedAction(", "function wireStageActions(")
    assert "card.dataset.busy = '1'" in runner
    assert "button.disabled = true" in runner
    # Progress is derived from the ledger rather than assumed.
    assert "API.http.adminPipeline()" in runner
    assert "row.running.indexOf(state) >= 0" in runner


def test_handlers_are_bound_once_so_a_refresh_cannot_double_fire() -> None:
    wiring = _slice("function wireStageActions(", "  const RELEASE_ORDER")
    assert "if (button.dataset.wired) return;" in wiring


def test_both_actions_state_what_they_will_do_before_running() -> None:
    wiring = _slice("function wireStageActions(", "  const RELEASE_ORDER")
    assert "Отправить в Canary?" in wiring
    assert "Пересборки не будет" in wiring


# --------------------------------------------------------------------------- #
# Identity, not the version string.
# --------------------------------------------------------------------------- #
def test_publication_is_hidden_when_production_holds_the_same_artifact() -> None:
    same = _slice("function sameArtifact(", "function actionsHtml(")
    assert "build_id" in same
    assert "artifact_sha256" in same
    assert "app_version" not in same, "a matching version string is not a matching artifact"
    actions = _slice("function actionsHtml(", "function checksHtml(")
    assert "sameArtifact(target, production)" in actions
    assert "Уже опубликовано" in actions


def test_canary_states_its_verdict_and_production_its_role() -> None:
    status = _slice("function statusHtml(", "function sameArtifact(")
    assert "Canary PASS" in status
    assert "Активная версия" in status
    assert "Локальный сервер не запущен" in status


def test_acceptance_says_what_it_checked() -> None:
    checks = _slice("function checksHtml(", "function stageCardSkeleton(")
    assert "stage-check" in checks
    assert "Детали проверки" in checks, "the detail belongs behind a disclosure"
    assert ".stage-check.ok" in CSS


def test_blocked_publication_states_its_reason_on_the_card() -> None:
    actions = _slice("function actionsHtml(", "function checksHtml(")
    assert "stage-blocked" in actions
    assert "Недоступно: " in actions
    assert ".stage-blocked" in CSS


def test_the_panel_does_not_send_the_owner_to_another_screen() -> None:
    wiring = _slice("function wireStageActions(", "  const RELEASE_ORDER")
    assert "releaseDeliverCanary" in wiring
    assert "releasePublish" in wiring
