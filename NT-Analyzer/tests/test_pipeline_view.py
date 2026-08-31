"""Environments and releases as one view, with gates that actually hold.

The Environment Switcher knew what each environment ran; the Release Center
knew how a candidate moves. Neither knew the other, so the owner carried the
workflow in their head -- which candidate is on Canary, and whether it is the
same artifact Production would receive.

The gates below are the part worth testing. A promotion is permitted only when
the artifact Canary reports running is the one being promoted, which is a
stronger statement than the release record agreeing with itself.
"""
from __future__ import annotations

import pytest

from app import pipeline_view, release_provenance, runtime_env

ARTIFACT = "a" * 64
OTHER = "b" * 64


@pytest.fixture(autouse=True)
def approved_provenance(monkeypatch):
    """These tests are about artifact identity, not where the code came from.

    Provenance is a separate gate with its own tests; left real it would reach
    for git and CI on every synthetic candidate here.
    """
    monkeypatch.setattr(release_provenance, "eligibility", lambda sha: {
        "eligible": True, "checks": [], "blocking": [], "reason": "", "commit": sha,
    })


def _candidate(state, artifact=ARTIFACT):
    return {"state": state, "artifact_sha256": artifact}


def _registry(canary_artifact=ARTIFACT, **extra):
    row = {"environment": runtime_env.CANARY, "artifact_sha256": canary_artifact}
    row.update(extra)
    return {"environments": [row]}


# --------------------------------------------------------------------------- #
# Stage progress speaks the owner's language.
# --------------------------------------------------------------------------- #
def test_the_stages_are_the_ones_an_owner_watches():
    ids = [s["id"] for s in pipeline_view.stage_progress(_candidate("draft"))]
    assert ids == ["ci", "build", "sign", "migrate", "canary",
                   "acceptance", "production"]


def test_a_signed_candidate_shows_build_and_sign_done():
    stages = {s["id"]: s["state"] for s in pipeline_view.stage_progress(_candidate("signed"))}
    assert stages["build"] == "done"
    assert stages["sign"] == "done"
    assert stages["canary"] == "pending"
    assert stages["production"] == "pending"


def test_reaching_canary_implies_migrations_ran():
    stages = {s["id"]: s["state"]
              for s in pipeline_view.stage_progress(_candidate("canary_checking"))}
    assert stages["migrate"] == "done"


def test_a_failed_build_is_shown_as_failed_not_pending():
    """Pending reads as "not yet"; this is "it went wrong", and the difference
    is the whole reason someone is looking at the page."""
    stages = {s["id"]: s["state"]
              for s in pipeline_view.stage_progress(_candidate("build_failed"))}
    assert stages["build"] == "failed"


def test_a_failed_canary_is_shown_as_failed():
    stages = {s["id"]: s["state"]
              for s in pipeline_view.stage_progress(_candidate("canary_failed"))}
    assert stages["canary"] == "failed"


def test_a_live_production_release_shows_every_stage_done():
    stages = {s["id"]: s["state"]
              for s in pipeline_view.stage_progress(_candidate("production_live"))}
    assert set(stages.values()) == {"done"}


# --------------------------------------------------------------------------- #
# Promotion gates.
# --------------------------------------------------------------------------- #
def test_promotion_is_allowed_only_when_every_gate_holds():
    out = pipeline_view.promotion_gates(_candidate("canary_passed"), _registry())
    assert out["allowed"] is True
    assert out["blocking"] == []


def test_promotion_compares_runtime_manifest_not_transport_archive():
    candidate = _candidate("canary_passed", artifact=OTHER)
    candidate["manifest_sha256"] = ARTIFACT
    out = pipeline_view.promotion_gates(candidate, _registry(canary_artifact=ARTIFACT))
    assert out["allowed"] is True
    assert out["blocking"] == []


def test_a_candidate_that_never_reached_canary_cannot_be_promoted():
    out = pipeline_view.promotion_gates(_candidate("signed"), _registry())
    assert out["allowed"] is False
    assert "canary_deployed" in out["blocking"]
    assert "acceptance" in out["blocking"]


def test_acceptance_is_required():
    out = pipeline_view.promotion_gates(_candidate("canary_checking"), _registry())
    assert out["allowed"] is False
    assert "acceptance" in out["blocking"]


def test_a_rebuilt_artifact_blocks_promotion():
    """The gate that matters most. Canary accepted one artifact; if the
    candidate now names a different one, Production would receive something
    nobody verified."""
    out = pipeline_view.promotion_gates(
        _candidate("canary_passed", artifact=OTHER), _registry(canary_artifact=ARTIFACT))
    assert out["allowed"] is False
    assert "artifact_unchanged" in out["blocking"]


def test_a_silent_canary_blocks_promotion():
    """If Canary has not reported what it is running, nothing confirms it holds
    the artifact being promoted -- and an unverified assumption is exactly what
    this gate exists to refuse."""
    out = pipeline_view.promotion_gates(
        _candidate("canary_passed"), _registry(canary_artifact=""))
    assert out["allowed"] is False
    assert "artifact_unchanged" in out["blocking"]


def test_an_unbuilt_candidate_blocks_promotion():
    out = pipeline_view.promotion_gates(
        {"state": "draft", "artifact_sha256": ""}, _registry())
    assert out["allowed"] is False
    assert "artifact_exists" in out["blocking"]


def test_the_block_reason_is_readable():
    """A blocked promotion should read as a checklist, not a refusal code."""
    out = pipeline_view.promotion_gates(_candidate("signed"), _registry())
    assert out["reason"]
    assert "Приёмка" in out["reason"] or "Canary" in out["reason"]
    for gate in out["gates"]:
        assert gate["label"] and not gate["label"].startswith("gate_")


def test_artifact_comparison_ignores_case():
    out = pipeline_view.promotion_gates(
        _candidate("canary_passed", artifact=ARTIFACT.upper()), _registry(ARTIFACT))
    assert out["allowed"] is True


# --------------------------------------------------------------------------- #
# Cards.
# --------------------------------------------------------------------------- #
def test_the_development_card_carries_the_sync_state():
    """A release cut from a checkout LOCAL is not running is the failure the
    whole pipeline exists to prevent, so it belongs on the card."""
    card = pipeline_view.development_card(
        {"state": "stale", "running_version": "0.10.0-beta.20",
         "running_commit_short": "aaaaaaaaaaaa", "head_commit_short": "bbbbbbbbbbbb",
         "message": "перезапустите LOCAL", "dirty_count": 0},
        {"state": "live", "schema_version": 0},
    )
    assert card["sync_state"] == "stale"
    assert card["running_commit"] != card["head_commit"]
    assert card["sync_message"]
    assert card["online"] is True


def test_accepted_release_marks_a_registry_reported_old_development_as_behind():
    accepted = {
        "state": "production_live", "app_version": "0.10.0-beta.48",
        "git_commit_sha": "a" * 40, "artifact_sha256": ARTIFACT,
    }
    card = pipeline_view.development_card(
        {"state": "not_applicable"},
        {"state": "live", "app_version": "0.10.0-beta.47",
         "git_commit_sha": "b" * 40, "build_id": "dev-beta47"},
        accepted,
    )
    assert card["version"] == "0.10.0-beta.47"
    assert card["running_commit"] == "b" * 12
    assert card["sync_state"] == "behind"
    assert card["release_consistent"] is False
    assert "ALL ENVIRONMENTS PASS" in card["sync_message"]


def test_a_never_seen_environment_is_not_reported_as_online():
    card = pipeline_view.development_card({"state": "current"}, {"state": "never_seen"})
    assert card["online"] is False


def test_a_server_card_reports_what_the_environment_says():
    card = pipeline_view.server_card(
        runtime_env.CANARY,
        {"state": "live", "app_version": "0.10.0-beta.26",
         "artifact_sha256": ARTIFACT, "schema_version": 18, "readiness": "ready"},
        {"state": "deployed", "updated_at_utc": "2026-08-18T00:00:00Z"},
    )
    assert card["version"] == "0.10.0-beta.26"
    assert card["schema_version"] == 18
    assert card["last_deploy_at_utc"]


# --------------------------------------------------------------------------- #
# Compare.
# --------------------------------------------------------------------------- #
def test_compare_flags_a_real_disagreement():
    cards = [
        pipeline_view.server_card(runtime_env.CANARY,
                                  {"state": "live", "artifact_sha256": ARTIFACT}),
        pipeline_view.server_card(runtime_env.PRODUCTION,
                                  {"state": "live", "artifact_sha256": OTHER}),
    ]
    fields = {f["field"]: f for f in pipeline_view.compare(cards)["fields"]}
    assert fields["artifact_sha256"]["differs"] is True


def test_compare_reports_a_blank_as_missing_not_as_a_mismatch():
    cards = [
        pipeline_view.server_card(runtime_env.CANARY,
                                  {"state": "live", "schema_version": 18}),
        pipeline_view.server_card(runtime_env.PRODUCTION, {"state": "live"}),
    ]
    fields = {f["field"]: f for f in pipeline_view.compare(cards)["fields"]}
    assert fields["schema_version"]["differs"] is False
    assert runtime_env.PRODUCTION in fields["schema_version"]["missing"]


def test_compare_ignores_environments_that_never_reported():
    cards = [
        pipeline_view.server_card(runtime_env.CANARY, {"state": "live", "app_version": "x"}),
        pipeline_view.server_card(runtime_env.PRODUCTION, {"state": "never_seen"}),
    ]
    assert pipeline_view.compare(cards)["environments"] == [runtime_env.CANARY]


# --------------------------------------------------------------------------- #
# Development access.
# --------------------------------------------------------------------------- #
def test_development_opens_only_from_the_development_machine():
    allowed = pipeline_view.development_access(True)
    assert allowed["allowed"] is True
    assert allowed["origin"].startswith("http://127.0.0.1")


def test_a_remote_browser_is_refused_with_an_explanation():
    """No proxy through Production. A convenience tunnel to a development box
    outlives the convenience."""
    refused = pipeline_view.development_access(False)
    assert refused["allowed"] is False
    assert not refused["origin"]
    assert "development" in refused["reason"].lower()


def test_the_only_origin_ever_offered_is_loopback():
    """Whatever the caller is, the module never hands back a routable address:
    the development server is not published outward under any condition."""
    import ipaddress
    import urllib.parse

    for is_local in (True, False):
        origin = pipeline_view.development_access(is_local)["origin"]
        if not origin:
            continue
        host = urllib.parse.urlsplit(origin).hostname or ""
        assert ipaddress.ip_address(host).is_loopback, origin


# --------------------------------------------------------------------------- #
# assemble: the join between the release centre and the environment registry.
# This is where the mistakes are. The release centre publishes its candidate
# summaries under "releases"; reading any other key silently produces a view
# that reports "no candidate" forever, and nothing else in the payload looks
# wrong while it does.
# --------------------------------------------------------------------------- #
def test_the_candidate_is_read_from_the_key_the_release_centre_publishes():
    from app import release_center

    out = pipeline_view.assemble(
        registry=_registry(),
        releases={"releases": [{"candidate_id": "rc_1", "state": "canary_passed",
                                "artifact_sha256": ARTIFACT}]},
        sync={"state": "current"},
    )
    assert out["candidate"]["candidate_id"] == "rc_1"
    # And that key is the one release_center actually produces, so a rename on
    # either side fails here instead of in a browser.
    assert "releases" in release_center.list_releases()


def test_an_empty_release_centre_yields_a_view_that_still_renders():
    out = pipeline_view.assemble(registry=None, releases=None, sync=None)
    assert out["candidate"] == {}
    assert out["promotion"]["allowed"] is False
    assert [s["id"] for s in out["stages"]]
    assert set(out["environments"]) == {"development", "canary", "production"}


def test_assemble_carries_the_promotion_gates_of_the_active_candidate():
    out = pipeline_view.assemble(
        registry=_registry(canary_artifact=ARTIFACT),
        releases={"releases": [{"candidate_id": "rc_1", "state": "canary_passed",
                                "artifact_sha256": ARTIFACT}]},
        sync={"state": "current"},
    )
    assert out["promotion"]["allowed"] is True


def test_a_silent_canary_still_blocks_promotion_through_assemble():
    """The gate that matters, checked end to end: Canary has not said what it
    runs, so nothing confirms Production would receive the verified artifact."""
    out = pipeline_view.assemble(
        registry={"environments": []},
        releases={"releases": [{"candidate_id": "rc_1", "state": "canary_passed",
                                "artifact_sha256": ARTIFACT}]},
        sync={"state": "current"},
    )
    assert out["promotion"]["allowed"] is False
    assert "artifact_unchanged" in out["promotion"]["blocking"]
    assert out["promotion"]["reason"]


def test_deployment_timestamps_reach_the_environment_cards():
    out = pipeline_view.assemble(
        registry=_registry(),
        releases={"releases": [{"candidate_id": "rc_1", "state": "canary_passed",
                                "artifact_sha256": ARTIFACT}]},
        sync={"state": "current"},
        deployments={runtime_env.CANARY: {"state": "deployed",
                                          "updated_at_utc": "2026-08-18T09:00:00Z"}},
    )
    assert out["environments"]["canary"]["last_deploy_at_utc"] == "2026-08-18T09:00:00Z"


def test_the_history_is_bounded():
    """Ten is a history; every candidate ever cut is a scroll bar."""
    rows = [{"candidate_id": "rc_%d" % i, "state": "superseded"} for i in range(40)]
    out = pipeline_view.assemble(registry=None, releases={"releases": rows}, sync=None)
    assert len(out["candidates"]) == 10
    assert out["candidate"]["candidate_id"] == "rc_0"


def test_assemble_never_hands_a_remote_browser_a_development_origin():
    out = pipeline_view.assemble(registry=None, releases=None, sync=None,
                                 is_local_request=False)
    assert out["development_access"]["allowed"] is False
    assert not out["development_access"]["origin"]


def test_overall_pass_is_blocked_until_development_matches_the_accepted_release():
    accepted = {
        "candidate_id": "rc_48", "state": "production_live",
        "app_version": "0.10.0-beta.48", "git_commit_sha": "a" * 40,
        "artifact_sha256": OTHER, "manifest_sha256": ARTIFACT,
    }
    rows = [
        {"environment": runtime_env.DEVELOPMENT, "state": "live",
         "app_version": "0.10.0-beta.47", "git_commit_sha": "b" * 40},
        {"environment": runtime_env.CANARY, "state": "live",
         "app_version": "0.10.0-beta.48", "git_commit_sha": "a" * 40,
         "artifact_sha256": ARTIFACT},
        {"environment": runtime_env.PRODUCTION, "state": "live",
         "app_version": "0.10.0-beta.48", "git_commit_sha": "a" * 40,
         "artifact_sha256": ARTIFACT},
    ]
    blocked = pipeline_view.assemble(
        registry={"environments": rows}, releases={"releases": [accepted]},
        sync={"state": "not_applicable"},
    )
    assert blocked["overall"]["ok"] is False
    assert "development_identity" in blocked["overall"]["blocking"]

    rows[0].update({
        "app_version": "0.10.0-beta.48", "git_commit_sha": "a" * 40,
    })
    reconciled = pipeline_view.assemble(
        registry={"environments": rows}, releases={"releases": [accepted]},
        sync={"state": "not_applicable"},
    )
    assert reconciled["overall"]["ok"] is True
    assert reconciled["overall"]["state"] == "pass"


def test_the_adapter_status_travels_with_the_buttons_it_qualifies():
    """A dry-run deploy and a real one must not look identical to whoever is
    about to click Deploy."""
    out = pipeline_view.assemble(
        registry=None, sync=None,
        releases={"releases": [], "adapter": {"real_available": False}},
    )
    assert out["adapter"] == {"real_available": False}


# --------------------------------------------------------------------------- #
# A finished release is not a blocked one.
# --------------------------------------------------------------------------- #
def test_a_live_production_release_is_reported_as_complete_not_blocked():
    """Marking every finished release with a promotion warning is how a warning
    stops meaning anything."""
    out = pipeline_view.promotion_gates(_candidate("production_live"), _registry())
    assert out["complete"] is True
    assert out["allowed"] is False
    assert out["blocking"] == []
    assert not out["reason"]
    assert out["note"]


def test_a_rolled_back_candidate_is_not_promotable_however_the_gates_read():
    out = pipeline_view.promotion_gates(_candidate("rolled_back"), _registry())
    assert out["allowed"] is False
    assert out["complete"] is True


def test_a_pending_candidate_is_not_marked_complete():
    out = pipeline_view.promotion_gates(_candidate("canary_passed"), _registry())
    assert out["complete"] is False
    assert out["allowed"] is True


def _accepted():
    return {
        "candidate_id": "rc_49", "state": "production_live",
        "app_version": "0.10.0-beta.49", "git_commit_sha": "c" * 40,
        "artifact_sha256": OTHER, "manifest_sha256": ARTIFACT,
    }


def _agreeing_rows():
    server = {"state": "live", "app_version": "0.10.0-beta.49",
              "git_commit_sha": "c" * 40, "artifact_sha256": ARTIFACT}
    return [
        {"environment": runtime_env.DEVELOPMENT, "state": "live",
         "app_version": "0.10.0-beta.49", "git_commit_sha": "c" * 40},
        dict(server, environment=runtime_env.CANARY),
        dict(server, environment=runtime_env.PRODUCTION),
    ]


def test_an_unread_registry_is_unknown_rather_than_a_reported_mismatch():
    """LOCAL could not read the peer, so it has no basis to accuse it.

    Reporting fail here was the bug: Development sat behind a permanently red
    banner naming environments it had never actually observed, which trains an
    owner to ignore the one gate that is supposed to stop a bad promotion.
    """
    out = pipeline_view.assemble(
        registry={"environments": []}, releases={"releases": [_accepted()]},
        sync={"state": "not_applicable"},
        registry_known=False,
        registry_source={"source": "peer", "origin": "", "ok": False},
    )
    overall = out["overall"]
    assert overall["state"] == "unknown"
    assert overall["ok"] is False
    assert overall["failing"] == []
    assert "canary_identity" in overall["unknown"]
    assert "immutable_server_artifact" in overall["unknown"]


def test_an_unknown_gate_never_reads_as_a_pass():
    out = pipeline_view.assemble(
        registry={"environments": _agreeing_rows()[:1]},
        releases={"releases": [_accepted()]},
        sync={"state": "not_applicable"},
    )
    overall = out["overall"]
    assert overall["ok"] is False
    assert overall["state"] == "unknown"


def test_a_read_back_peer_registry_proves_the_pass_from_development():
    """The rows came from the peer, and that is enough to decide.

    They arrived over the channel this environment signs its own heartbeats
    with, so they are not weaker evidence than a local row -- and the whole
    point of reading them is that Development can now prove the pass instead
    of an operator checking two servers by hand.
    """
    out = pipeline_view.assemble(
        registry={"environments": _agreeing_rows()},
        releases={"releases": [_accepted()]},
        sync={"state": "not_applicable"},
        registry_is_authoritative=False,
        registry_known=True,
        registry_source={"source": "peer", "ok": True,
                         "origin": "https://app.stratforges.com"},
    )
    overall = out["overall"]
    assert overall["state"] == "pass"
    assert overall["ok"] is True
    assert overall["registry_source"] == "peer"
    assert overall["registry_origin"] == "https://app.stratforges.com"


def test_a_genuine_artifact_split_is_a_failure_not_an_unknown():
    rows = _agreeing_rows()
    rows[2]["artifact_sha256"] = OTHER
    overall = pipeline_view.assemble(
        registry={"environments": rows}, releases={"releases": [_accepted()]},
        sync={"state": "not_applicable"},
    )["overall"]
    assert overall["state"] == "fail"
    assert overall["failing"] == ["immutable_server_artifact"]


def test_without_an_accepted_release_no_environment_is_accused():
    overall = pipeline_view.assemble(
        registry={"environments": _agreeing_rows()}, releases={"releases": []},
        sync={"state": "not_applicable"},
    )["overall"]
    assert overall["state"] == "unknown"
    assert overall["failing"] == []
