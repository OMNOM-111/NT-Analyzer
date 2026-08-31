"""Release summary from real metadata, and publication as staged operation."""
from __future__ import annotations

import pytest

from app import release_center, release_publish, release_summary


# ---- summary ---------------------------------------------------------------

CHANGELOG = """# beta.80 — юридический пакет и pre-auth документы

Период: 2026-08-30 → 2026-08-31.

## Что вошло

- Единый юридический пакет.
- Девять документов до регистрации.
- AI Provenance Policy.
- Четвёртый пункт, который не должен попасть в карточку.

## Решения и почему

- Это уже другой раздел.
"""


def test_summary_takes_title_and_at_most_three_points() -> None:
    parsed = release_summary.parse(CHANGELOG)
    assert parsed["title"] == "юридический пакет и pre-auth документы"
    assert parsed["points"] == [
        "Единый юридический пакет.",
        "Девять документов до регистрации.",
        "AI Provenance Policy.",
    ]
    assert len(parsed["points"]) <= release_summary.MAX_POINTS


def test_summary_reads_the_shipped_changelog(tmp_path) -> None:
    (tmp_path / "2026-08-31-beta80-legal.md").write_text(CHANGELOG, encoding="utf-8")
    out = release_summary.summary_for("0.10.0-beta.80", directory=tmp_path)
    assert out["title"].startswith("юридический пакет")
    assert out["source"] == "2026-08-31-beta80-legal.md"


def test_summary_is_empty_rather_than_invented(tmp_path) -> None:
    """No changelog entry must produce no summary, never a guess."""
    out = release_summary.summary_for("0.10.0-beta.99", directory=tmp_path)
    assert out == {"title": "", "points": [], "source": ""}
    assert release_summary.summary_for("", directory=tmp_path)["points"] == []


def test_real_repository_changelog_is_parseable() -> None:
    out = release_summary.summary_for("0.10.0-beta.80")
    assert out["title"], "the shipped beta.80 changelog must yield a title"
    assert 1 <= len(out["points"]) <= release_summary.MAX_POINTS


# ---- publication -----------------------------------------------------------

def _summary(state: str) -> dict:
    return {"summary": {"state": state, "build_id": "sf-test-build"}}


def _labels(stages):
    return [(row["stage"], row["state"]) for row in stages]


def test_publish_refuses_a_candidate_that_did_not_pass_canary(monkeypatch) -> None:
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: _summary(release_center.STATE_CANARY_CHECKING))
    called = []
    out = release_publish.publish(
        actor={"is_owner": True}, candidate_id="rc_x", idempotency_key="k" * 20,
        production_origin="https://example.invalid",
        approve=lambda **kw: called.append("approve"),
        promote=lambda **kw: called.append("promote"),
    )
    assert out["ok"] is False
    assert out["failed_stage"] == release_publish.STAGE_APPROVE
    assert out["code"] == "invalid_transition"
    assert called == [], "nothing may run for a candidate that did not pass Canary"


def test_publish_runs_every_stage_in_order(monkeypatch) -> None:
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: _summary(release_center.STATE_CANARY_PASSED))
    order = []
    out = release_publish.publish(
        actor={"is_owner": True}, candidate_id="rc_x", idempotency_key="k" * 20,
        production_origin="https://example.invalid",
        approve=lambda **kw: order.append("approve"),
        promote=lambda **kw: order.append("promote"),
        smoke=lambda origin, build: {"ok": True},
    )
    # Readiness is probed for real, so this run stops there unless stubbed.
    assert order == ["approve", "promote"]
    assert out["failed_stage"] == release_publish.STAGE_READINESS


def test_publish_stops_at_the_failing_stage_with_a_reason(monkeypatch) -> None:
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: _summary(release_center.STATE_CANARY_PASSED))
    monkeypatch.setattr(release_publish, "_readiness", lambda origin: {"ok": True, "deployment": {}})
    out = release_publish.publish(
        actor={"is_owner": True}, candidate_id="rc_x", idempotency_key="k" * 20,
        production_origin="https://example.invalid",
        approve=lambda **kw: None, promote=lambda **kw: None,
        smoke=lambda origin, build: {"ok": False, "reason": "/ui/ вернул 502."},
    )
    assert out["ok"] is False
    assert out["failed_stage"] == release_publish.STAGE_SMOKE
    assert "502" in out["reason"]
    states = dict(_labels(out["stages"]))
    assert states[release_publish.STAGE_APPROVE] == "passed"
    assert states[release_publish.STAGE_DEPLOY] == "passed"
    assert states[release_publish.STAGE_READINESS] == "passed"
    assert states[release_publish.STAGE_SMOKE] == "failed"
    # A stage after the failure must read as not started, never as passed.
    assert states[release_publish.STAGE_DONE] == "not_started"


def test_publish_surfaces_a_release_center_refusal(monkeypatch) -> None:
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: _summary(release_center.STATE_CANARY_PASSED))

    def refuse(**kwargs):
        raise release_center.ReleaseCenterError(
            "Production approval доступен только владельцу.", 403, code="owner_required")

    out = release_publish.publish(
        actor={"is_owner": False}, candidate_id="rc_x", idempotency_key="k" * 20,
        production_origin="https://example.invalid", approve=refuse,
        promote=lambda **kw: pytest.fail("promotion must not run after a refusal"),
    )
    assert out["ok"] is False
    assert out["status"] == 403
    assert out["code"] == "owner_required"
    assert out["failed_stage"] == release_publish.STAGE_APPROVE


def test_publish_without_a_production_origin_does_not_claim_success(monkeypatch) -> None:
    """An unverifiable deployment must not render as a green run.

    Promotion has already happened by this point, so the run reports a deployed
    Production that could not be validated -- not a publication that never took
    place.
    """
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: _summary(release_center.STATE_CANARY_PASSED))
    out = release_publish.publish(
        actor={"is_owner": True}, candidate_id="rc_x", idempotency_key="k" * 20,
        production_origin="", approve=lambda **kw: None, promote=lambda **kw: None,
    )
    assert out["ok"] is False
    assert out["failed_stage"] == release_publish.STAGE_READINESS
    assert out["production_deployed"] is True
    assert out["outcome"] == "deployed_validation_failed"
    assert out["closeout_blocked"] is True
    assert "Origin Production не настроен" in out["reason"]


def test_smoke_rejects_a_different_build_than_the_one_published(monkeypatch) -> None:
    monkeypatch.setattr(release_publish, "_readiness",
                        lambda origin: {"ok": True, "deployment": {"build_id": "other-build"}})
    out = release_publish._smoke("https://example.invalid", "sf-test-build")
    assert out["ok"] is False
    assert "other-build" in out["reason"]


def test_ui_offers_publication_only_for_a_canary_passed_candidate() -> None:
    from pathlib import Path

    ui = (Path(release_publish.__file__).resolve().parents[1]
          / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "data-pipe-publish" in ui
    assert "state === 'canary_passed'" in ui
    assert "Доступно только для кандидата, прошедшего Canary" in ui
    # The confirmation must state that the same artifact moves, without rebuild.
    assert "Пересборки не будет" in ui
    for label in ("Подтверждение", "Развёртывание", "Readiness", "Smoke", "Готово"):
        assert label in ui or label in str(release_publish.STAGES)


def test_validation_failure_after_deploy_is_not_reported_as_not_published(monkeypatch) -> None:
    """Production is already switched over; saying otherwise misdirects the owner."""
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: _summary(release_center.STATE_CANARY_PASSED))
    monkeypatch.setattr(release_publish, "_readiness", lambda origin: {"ok": True, "deployment": {}})
    out = release_publish.publish(
        actor={"is_owner": True}, candidate_id="rc_x", idempotency_key="k" * 20,
        production_origin="https://example.invalid",
        approve=lambda **kw: None, promote=lambda **kw: None,
        smoke=lambda origin, build: {"ok": False, "reason": "/ui/ вернул 502."},
    )
    assert out["ok"] is False
    assert out["production_deployed"] is True
    assert out["outcome"] == "deployed_validation_failed"
    assert out["code"] == "validation_failed_after_deploy"
    assert out["reason"].startswith("Production развёрнут, validation failed")
    assert "502" in out["reason"]
    assert out["failed_stage"] == release_publish.STAGE_SMOKE
    assert out["closeout_blocked"] is True
    # Recovery points at the existing contract rather than a new mechanism.
    assert out["rollback"]["action"] == "rollback-production"
    assert "step_up" in out["rollback"]["requires"]


def test_failure_before_deploy_still_reports_nothing_was_published(monkeypatch) -> None:
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: _summary(release_center.STATE_CANARY_PASSED))

    def refuse(**kwargs):
        raise release_center.ReleaseCenterError("нет прав", 403, code="owner_required")

    out = release_publish.publish(
        actor={"is_owner": False}, candidate_id="rc_x", idempotency_key="k" * 20,
        production_origin="https://example.invalid", approve=refuse,
        promote=lambda **kw: pytest.fail("must not deploy"),
    )
    assert out["production_deployed"] is False
    assert out["outcome"] == "not_published"
    assert out["closeout_blocked"] is True
    assert "rollback" not in out
    assert not out["reason"].startswith("Production развёрнут")


def test_successful_publication_does_not_block_closeout(monkeypatch) -> None:
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: _summary(release_center.STATE_CANARY_PASSED))
    monkeypatch.setattr(release_publish, "_readiness", lambda origin: {"ok": True, "deployment": {}})
    out = release_publish.publish(
        actor={"is_owner": True}, candidate_id="rc_x", idempotency_key="k" * 20,
        production_origin="https://example.invalid",
        approve=lambda **kw: None, promote=lambda **kw: None,
        smoke=lambda origin, build: {"ok": True},
    )
    assert out["ok"] is True
    assert out["outcome"] == "published"
    assert out["closeout_blocked"] is False


def test_ui_distinguishes_a_deployed_but_unvalidated_run() -> None:
    from pathlib import Path

    ui = (Path(release_publish.__file__).resolve().parents[1]
          / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "Production развёрнут, validation failed" in ui
    assert "Публикация не выполнена" in ui
    assert "production_deployed" in ui
    assert "Closeout заблокирован" in ui
    assert "rollback-production" in ui
