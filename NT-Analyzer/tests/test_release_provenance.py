"""A build may reach Production only from approved main.

An artifact built from an unmerged branch passed Canary acceptance and was one
enabled button away from Production. Acceptance says the environment is
healthy; it says nothing about where the code came from, and neither does the
version string. These pin the gate that does.
"""
from __future__ import annotations

import pytest

from app import pipeline_view, release_center, release_provenance


def _checks(names_ok):
    return [{"name": name, "label": name, "ok": ok, "detail": ""}
            for name, ok in names_ok]


def test_every_required_condition_is_asked(monkeypatch) -> None:
    monkeypatch.setattr(release_provenance, "_git", lambda *a, **k: (0, ""))
    out = release_provenance.evaluate("a" * 40, ci=lambda sha: {"ok": True, "detail": ""})
    asked = {row["name"] for row in out["checks"]}
    assert asked == {
        "commit_known", "branch_is_main", "worktree_clean",
        "in_sync_with_origin_main", "commit_on_origin_main", "ci_green",
    }


def test_a_branch_build_is_refused(monkeypatch) -> None:
    """The beta.82 case: a real commit, on a branch, never merged."""
    def fake_git(*args, **kwargs):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return 0, "feat/some-branch"
        if args[0] == "merge-base":
            return 1, ""            # not an ancestor of origin/main
        if args[0] == "rev-parse":
            return 0, "d" * 40
        if args[0] == "status":
            return 0, ""
        if args[0] == "rev-list":
            return 0, "0\t3"
        return 0, ""

    monkeypatch.setattr(release_provenance, "_git", fake_git)
    out = release_provenance.evaluate("d" * 40, ci=lambda sha: {"ok": True, "detail": ""})
    assert out["eligible"] is False
    assert "branch_is_main" in out["blocking"]
    assert "commit_on_origin_main" in out["blocking"]
    assert "не создана из утверждённого main" in out["reason"]


def test_a_dirty_worktree_is_refused(monkeypatch) -> None:
    def fake_git(*args, **kwargs):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return 0, "main"
        if args[0] == "status":
            return 0, " M app/server.py"
        if args[0] == "rev-list":
            return 0, "0\t0"
        return 0, "e" * 40

    monkeypatch.setattr(release_provenance, "_git", fake_git)
    out = release_provenance.evaluate("e" * 40, ci=lambda sha: {"ok": True, "detail": ""})
    assert out["eligible"] is False
    assert "worktree_clean" in out["blocking"]


def test_being_ahead_of_origin_main_is_refused(monkeypatch) -> None:
    """A local main that was never pushed is not approved main."""
    def fake_git(*args, **kwargs):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return 0, "main"
        if args[0] == "status":
            return 0, ""
        if args[0] == "rev-list":
            return 0, "0\t2"
        return 0, "f" * 40

    monkeypatch.setattr(release_provenance, "_git", fake_git)
    out = release_provenance.evaluate("f" * 40, ci=lambda sha: {"ok": True, "detail": ""})
    assert out["eligible"] is False
    assert "in_sync_with_origin_main" in out["blocking"]


def test_ci_that_cannot_be_confirmed_is_refused(monkeypatch) -> None:
    """A check that could not run is not a check that passed."""
    monkeypatch.setattr(release_provenance, "_git", lambda *a, **k: (0, "main")
                        if a[:2] == ("rev-parse", "--abbrev-ref") else (0, ""))
    out = release_provenance.evaluate(
        "a" * 40, ci=lambda sha: {"known": False, "ok": False, "detail": "gh недоступен"})
    assert out["eligible"] is False
    assert "ci_green" in out["blocking"]


def test_a_pending_or_failed_run_is_not_success() -> None:
    for conclusion in ("pending", "failure", "cancelled", ""):
        assert conclusion != release_provenance.REQUIRED_CONCLUSION


# --------------------------------------------------------------------------- #
# The gate is on the backend; the panel only reflects it.
# --------------------------------------------------------------------------- #
def test_approval_refuses_a_build_that_is_not_from_approved_main(monkeypatch) -> None:
    """canary_passed is not enough, and this is enforced where it cannot be
    bypassed by whatever the page last rendered."""
    monkeypatch.setattr(release_provenance, "eligibility", lambda sha: {
        "eligible": False, "reason": "Эта сборка не создана из утверждённого main: X",
        "checks": [], "blocking": ["commit_on_origin_main"], "commit": sha,
    })
    source = (release_center.__file__)
    body = open(source, encoding="utf-8").read()
    block = body[body.index("def approve_production("):body.index("def schedule_production(")]
    assert "release_provenance" in block
    assert "provenance_not_approved" in block
    # Placed after the canary_passed check, so a healthy Canary cannot carry it.
    assert block.index("STATE_CANARY_PASSED") < block.index("release_provenance")


def test_the_panel_reflects_the_backend_verdict() -> None:
    gates = pipeline_view.promotion_gates(
        {"state": "canary_passed", "git_commit_sha": "c" * 40,
         "manifest_sha256": "a" * 64},
        {"environments": []},
        provenance_check=lambda sha: {
            "eligible": False, "reason": "Эта сборка не создана из утверждённого main",
            "checks": [], "blocking": ["branch_is_main"], "commit": sha},
    )
    row = next(g for g in gates["gates"] if g["id"] == "approved_main")
    assert row["ok"] is False
    assert "утверждённого main" in row["detail"]
    assert gates["allowed"] is False


def test_an_approved_build_clears_the_gate() -> None:
    gates = pipeline_view.promotion_gates(
        {"state": "canary_passed", "git_commit_sha": "c" * 40,
         "manifest_sha256": "a" * 64},
        {"environments": []},
        provenance_check=lambda sha: {
            "eligible": True, "reason": "", "checks": [], "blocking": [], "commit": sha},
    )
    row = next(g for g in gates["gates"] if g["id"] == "approved_main")
    assert row["ok"] is True


def test_diagnosing_on_canary_stays_possible() -> None:
    """Provenance blocks Production, not Canary: a branch build must still be
    deployable for diagnosis."""
    body = open(release_center.__file__, encoding="utf-8").read()
    deploy = body[body.index("def deploy_canary("):body.index("def record_canary_check(")]
    assert "release_provenance" not in deploy


# --------------------------------------------------------------------------- #
# Publishing moves Production forward. Going back is a rollback.
# --------------------------------------------------------------------------- #
def test_a_candidate_behind_production_cannot_be_published(monkeypatch) -> None:
    """The audit case: Production on a new main SHA, a canary_passed candidate
    from an older main SHA. It passes provenance — an old commit on main is as
    approved as a new one — and must still be refused."""
    old, new = "a" * 40, "b" * 40

    def ancestry(*args, **kwargs):
        # `is-ancestor <live> <candidate>` is false: live is newer.
        if args[0] == "merge-base":
            return 1, ""
        return 0, ""

    monkeypatch.setattr(release_provenance, "_git", ancestry)
    verdict = release_provenance.forward_only(
        old, {"state": "known", "commit": new})
    assert verdict["ok"] is False
    assert verdict["code"] == "candidate_not_ahead_of_production"
    assert "старее текущего Production" in verdict["reason"]
    assert "Rollback" in verdict["reason"]


def test_a_candidate_ahead_of_production_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(release_provenance, "_git", lambda *a, **k: (0, ""))
    assert release_provenance.forward_only(
        "b" * 40, {"state": "known", "commit": "a" * 40})["ok"] is True


def test_the_same_commit_is_allowed_without_asking_git(monkeypatch) -> None:
    """Re-publishing the live release is not a rollback."""
    def refuse(*args, **kwargs):
        raise AssertionError("git must not be consulted for an identical commit")

    monkeypatch.setattr(release_provenance, "_git", refuse)
    assert release_provenance.forward_only(
        "a" * 40, {"state": "known", "commit": "a" * 40})["ok"] is True


def test_no_production_at_all_permits_a_first_publication(monkeypatch) -> None:
    monkeypatch.setattr(release_provenance, "_git", lambda *a, **k: (1, ""))
    identity = release_provenance.production_identity({}, {})
    assert identity["state"] == release_provenance.PRODUCTION_ABSENT
    assert release_provenance.forward_only("a" * 40, identity)["ok"] is True


def test_a_production_whose_identity_cannot_be_read_blocks_publication() -> None:
    """Absent and undeterminable are different states, and only one of them is
    safe to publish into without comparing. A Production that exists but cannot
    be identified is a question that failed, not an empty slot."""
    from_environment = release_provenance.production_identity(
        {"environments": [{"environment": "production", "git_commit_sha": ""}]}, {})
    assert from_environment["state"] == release_provenance.PRODUCTION_UNKNOWN
    refused = release_provenance.forward_only("a" * 40, from_environment)
    assert refused["ok"] is False
    assert refused["code"] == "production_identity_unknown"
    assert "до восстановления identity" in refused["reason"]

    # Deployment history alone is enough evidence that Production exists.
    from_ledger = release_provenance.production_identity(
        {}, {"releases": [{"state": "production_live", "git_commit_sha": ""}]})
    assert from_ledger["state"] == release_provenance.PRODUCTION_UNKNOWN
    assert release_provenance.forward_only("a" * 40, from_ledger)["ok"] is False


def test_approval_enforces_it_and_rollback_is_untouched() -> None:
    body = open(release_center.__file__, encoding="utf-8").read()
    approve = body[body.index("def approve_production("):body.index("def schedule_production(")]
    assert "forward_only" in approve
    assert "candidate_not_ahead_of_production" in approve
    # Ordered after provenance, which is itself after the canary_passed check.
    assert approve.index("release_provenance.eligibility") < approve.index("forward_only")
    rollback = body[body.index("def rollback_production("):]
    assert "forward_only" not in rollback, (
        "going back is what rollback is for and must not be gated by this")


def test_the_panel_renders_the_refusal_it_did_not_decide() -> None:
    gates = pipeline_view.promotion_gates(
        {"state": "canary_passed", "git_commit_sha": "a" * 40,
         "manifest_sha256": "a" * 64},
        {"environments": [{"environment": "production", "git_commit_sha": "b" * 40}]},
        provenance_check=lambda sha: {
            "eligible": True, "reason": "", "checks": [], "blocking": [], "commit": sha},
        identity_check=lambda registry, releases: {
            "state": "known", "commit": "b" * 40, "source": "environment"},
        forward_check=lambda candidate, live: {
            "ok": False, "code": "candidate_not_ahead_of_production",
            "reason": "Эта сборка старее текущего Production (bbbbbbbbbbbb). "
                      "Для возврата используй Rollback."},
    )
    row = next(g for g in gates["gates"] if g["id"] == "forward_only")
    assert row["ok"] is False
    assert "Rollback" in row["detail"]
    assert gates["allowed"] is False
