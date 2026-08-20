"""Promotion is driven from LOCAL and decided on the server.

The gates need facts from two places. The release ledger -- candidate state,
artifact digest, signature, acceptance -- belongs to whoever cut the candidate.
Whether Canary is alive *now* and running that exact artifact belongs to the
environment registry, which is authoritative only on a server: on LOCAL,
snapshot() returns nothing but LOCAL's own row.

So promoting from LOCAL used to be impossible, and the tempting repair -- let
LOCAL skip the artifact gate -- would have removed the one check that stops
Production receiving something nobody verified. LOCAL asks instead, over the
same signed channel the heartbeats use, and the server rules.

Everything below is about the same property: there is no path to `allowed`
that does not run through a server saying so.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from app import pipeline_view, release_control, runtime_env

ARTIFACT = "a" * 64
OTHER = "b" * 64


def _claim(**over: Any) -> Dict[str, Any]:
    claim = {
        "candidate_id": "rc_1", "artifact_sha256": ARTIFACT,
        "signature_status": "verified", "state": "canary_passed",
        "acceptance_passed": True, "migrations_applied": True, "ci_green": True,
    }
    claim.update(over)
    return claim


def _registry(**over: Any) -> Dict[str, Any]:
    row = {"environment": runtime_env.CANARY, "state": "live",
           "artifact_sha256": ARTIFACT, "app_version": "0.10.0-beta.27"}
    row.update(over)
    return {"environments": [row]}


# --------------------------------------------------------------------------- #
# The server's decision.
# --------------------------------------------------------------------------- #
def test_a_complete_claim_against_a_live_matching_canary_is_allowed():
    out = release_control.decide(_claim(), registry=_registry())
    assert out["allowed"] is True
    assert out["blocking"] == []
    assert out["decided_by"]


def test_a_silent_canary_is_refused_however_good_the_claim_is():
    """The registry, not the requester, answers for Canary."""
    out = release_control.decide(_claim(), registry=_registry(state="never_seen"))
    assert out["allowed"] is False
    assert "canary_live" in out["blocking"]


def test_a_stale_canary_is_refused():
    out = release_control.decide(_claim(), registry=_registry(state="stale"))
    assert out["allowed"] is False
    assert "canary_live" in out["blocking"]


def test_canary_running_a_different_artifact_is_refused():
    out = release_control.decide(_claim(), registry=_registry(artifact_sha256=OTHER))
    assert out["allowed"] is False
    assert "canary_runs_candidate" in out["blocking"]


def test_a_requester_cannot_assert_canary_state_itself():
    """A claim that tries to answer the registry's questions is ignored: those
    keys are not read, so asserting them changes nothing."""
    out = release_control.decide(
        _claim(canary_live=True, canary_runs_candidate=True, allowed=True),
        registry=_registry(state="offline"))
    assert out["allowed"] is False


@pytest.mark.parametrize("field,value,gate", [
    ("state", "canary_checking", "candidate_state"),
    ("acceptance_passed", False, "acceptance"),
    ("ci_green", False, "ci_green"),
    ("migrations_applied", False, "migrations"),
    ("signature_status", "invalid", "artifact_signed"),
    ("artifact_sha256", "", "artifact_signed"),
])
def test_each_ledger_fact_is_still_required(field, value, gate):
    out = release_control.decide(_claim(**{field: value}), registry=_registry())
    assert out["allowed"] is False
    assert gate in out["blocking"]


def test_the_decision_names_the_artifact_it_is_about():
    """So a decision cannot be replayed against a different candidate."""
    out = release_control.decide(_claim(), registry=_registry())
    assert out["artifact_sha256"] == ARTIFACT
    assert out["candidate_id"] == "rc_1"
    assert out["expires_at_epoch"] > out["decided_at_epoch"]


def test_only_an_authoritative_environment_may_decide(monkeypatch):
    from app import storage_router

    monkeypatch.setattr(storage_router, "production_enabled", lambda: False)
    assert release_control.authoritative() is False
    monkeypatch.setattr(storage_router, "production_enabled", lambda: True)
    assert release_control.authoritative() is True


# --------------------------------------------------------------------------- #
# The request, and every way it can fail.
# --------------------------------------------------------------------------- #
def test_no_configured_peer_is_a_refusal_not_a_pass(monkeypatch):
    monkeypatch.setattr(release_control.environment_registry, "peer_origins", lambda: [])
    out = release_control.request_decision(_claim())
    assert out["allowed"] is False
    assert out["available"] is False
    assert out["reason"]


def test_a_missing_signing_key_is_a_refusal(monkeypatch):
    monkeypatch.setattr(release_control.environment_registry, "peer_origins",
                        lambda: ["https://example.invalid"])
    monkeypatch.setattr(release_control.environment_registry, "token_configured",
                        lambda: False)
    out = release_control.request_decision(_claim())
    assert out["allowed"] is False
    assert out["code"] == "control_plane_key_missing"


def test_an_unreachable_control_plane_is_a_refusal(monkeypatch):
    monkeypatch.setattr(release_control.environment_registry, "peer_origins",
                        lambda: ["http://127.0.0.1:9"])
    monkeypatch.setattr(release_control.environment_registry, "token_configured",
                        lambda: True)
    monkeypatch.setattr(release_control.environment_registry, "token", lambda: "k" * 32)
    out = release_control.request_decision(_claim(), timeout=0.5)
    assert out["allowed"] is False
    assert out["available"] is False


def test_a_fresh_exact_server_decision_is_accepted(monkeypatch):
    monkeypatch.setattr(release_control.environment_registry, "peer_origins",
                        lambda: ["https://example.invalid"])
    monkeypatch.setattr(release_control.environment_registry, "token_configured",
                        lambda: True)
    monkeypatch.setattr(release_control.environment_registry, "token", lambda: "k" * 32)
    monkeypatch.setattr(release_control.environment_registry, "_now", lambda: 1_000.0)

    import io
    import json as _json
    import urllib.request

    payload = {
        "ok": True, "allowed": True, "decided_by": "canary",
        "artifact_sha256": ARTIFACT, "candidate_id": "rc_1",
        "decided_at_epoch": 1_000, "expires_at_epoch": 1_120,
    }

    class Fake(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: Fake(_json.dumps(payload).encode("utf-8")))
    out = release_control.request_decision(_claim())
    assert out["allowed"] is True
    assert out["available"] is True
    assert out["candidate_id"] == "rc_1"


def test_an_answer_about_another_artifact_is_discarded(monkeypatch):
    """Otherwise a captured yes for one release authorises the next one."""
    monkeypatch.setattr(release_control.environment_registry, "peer_origins",
                        lambda: ["https://example.invalid"])
    monkeypatch.setattr(release_control.environment_registry, "token_configured",
                        lambda: True)
    monkeypatch.setattr(release_control.environment_registry, "token", lambda: "k" * 32)

    import io
    import json as _json
    import urllib.request

    payload = {"allowed": True, "decided_by": "production", "artifact_sha256": OTHER}

    class Fake(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: Fake(_json.dumps(payload).encode("utf-8")))
    out = release_control.request_decision(_claim())
    assert out["allowed"] is False
    assert out["code"] == "control_plane_artifact_mismatch"


def test_an_answer_about_another_candidate_is_discarded(monkeypatch):
    monkeypatch.setattr(release_control.environment_registry, "peer_origins",
                        lambda: ["https://example.invalid"])
    monkeypatch.setattr(release_control.environment_registry, "token_configured",
                        lambda: True)
    monkeypatch.setattr(release_control.environment_registry, "token", lambda: "k" * 32)
    monkeypatch.setattr(release_control.environment_registry, "_now", lambda: 1_000.0)

    import io
    import json as _json
    import urllib.request

    payload = {
        "allowed": True, "decided_by": "production",
        "artifact_sha256": ARTIFACT, "candidate_id": "rc_other",
        "decided_at_epoch": 1_000, "expires_at_epoch": 1_120,
    }

    class Fake(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: Fake(_json.dumps(payload).encode("utf-8")))
    out = release_control.request_decision(_claim())
    assert out["allowed"] is False
    assert out["code"] == "control_plane_candidate_mismatch"


@pytest.mark.parametrize("decided,expires", [
    (800, 920),       # already expired
    (1_000, 1_000),  # empty validity window
    (1_000, 1_121),  # responder tried to extend the fixed TTL
    (1_121, 1_241),  # decision timestamp outside the clock-skew window
])
def test_a_stale_or_invalid_decision_is_discarded(monkeypatch, decided, expires):
    monkeypatch.setattr(release_control.environment_registry, "peer_origins",
                        lambda: ["https://example.invalid"])
    monkeypatch.setattr(release_control.environment_registry, "token_configured",
                        lambda: True)
    monkeypatch.setattr(release_control.environment_registry, "token", lambda: "k" * 32)
    monkeypatch.setattr(release_control.environment_registry, "_now", lambda: 1_000.0)

    import io
    import json as _json
    import urllib.request

    payload = {
        "allowed": True, "decided_by": "production",
        "artifact_sha256": ARTIFACT, "candidate_id": "rc_1",
        "decided_at_epoch": decided, "expires_at_epoch": expires,
    }

    class Fake(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: Fake(_json.dumps(payload).encode("utf-8")))
    out = release_control.request_decision(_claim())
    assert out["allowed"] is False
    assert out["code"] == "control_plane_decision_stale"


def test_a_development_responder_is_not_authoritative(monkeypatch):
    monkeypatch.setattr(release_control.environment_registry, "peer_origins",
                        lambda: ["https://example.invalid"])
    monkeypatch.setattr(release_control.environment_registry, "token_configured",
                        lambda: True)
    monkeypatch.setattr(release_control.environment_registry, "token", lambda: "k" * 32)

    import io
    import json as _json
    import urllib.request

    payload = {
        "allowed": True, "decided_by": "development",
        "artifact_sha256": ARTIFACT, "candidate_id": "rc_1",
    }

    class Fake(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: Fake(_json.dumps(payload).encode("utf-8")))
    out = release_control.request_decision(_claim())
    assert out["allowed"] is False
    assert out["code"] == "control_plane_answer_not_authoritative"


def test_an_answer_from_nobody_in_particular_is_discarded(monkeypatch):
    monkeypatch.setattr(release_control.environment_registry, "peer_origins",
                        lambda: ["https://example.invalid"])
    monkeypatch.setattr(release_control.environment_registry, "token_configured",
                        lambda: True)
    monkeypatch.setattr(release_control.environment_registry, "token", lambda: "k" * 32)

    import io
    import json as _json
    import urllib.request

    class Fake(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    payload = {"allowed": True, "artifact_sha256": ARTIFACT}  # no decided_by
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: Fake(_json.dumps(payload).encode("utf-8")))
    out = release_control.request_decision(_claim())
    assert out["allowed"] is False


# --------------------------------------------------------------------------- #
# What LOCAL shows, and what it refuses to decide for itself.
# --------------------------------------------------------------------------- #
def test_local_does_not_answer_the_canary_gates_from_its_own_snapshot():
    """LOCAL's snapshot has no Canary row at all. Deciding from it would mean
    deciding from ignorance."""
    out = pipeline_view.promotion_gates(
        {"state": "canary_passed", "artifact_sha256": ARTIFACT},
        {"environments": []},
        control={"allowed": True, "available": True, "decided_by": "production"},
        registry_is_authoritative=False)
    ids = {g["id"] for g in out["gates"]}
    assert "artifact_unchanged" not in ids
    assert "canary_deployed" not in ids
    assert "server_authorised" in ids
    assert out["allowed"] is True
    assert out["decided_by"] == "production"


def test_local_without_a_decision_refuses():
    out = pipeline_view.promotion_gates(
        {"state": "canary_passed", "artifact_sha256": ARTIFACT},
        {"environments": []},
        control=None, registry_is_authoritative=False)
    assert out["allowed"] is False
    assert out["control_available"] is False
    assert out["reason"]


def test_local_still_checks_everything_the_ledger_knows():
    """Delegating the Canary gates does not delegate the rest."""
    out = pipeline_view.promotion_gates(
        {"state": "signed", "artifact_sha256": ""},
        {"environments": []},
        control={"allowed": True, "available": True, "decided_by": "production"},
        registry_is_authoritative=False)
    assert out["allowed"] is False
    assert "artifact_exists" in out["blocking"]


def test_a_server_keeps_deciding_locally():
    """Where the registry is real, nothing is delegated."""
    out = pipeline_view.promotion_gates(
        {"state": "canary_passed", "artifact_sha256": ARTIFACT},
        _registry(), registry_is_authoritative=True)
    ids = {g["id"] for g in out["gates"]}
    assert "artifact_unchanged" in ids
    assert out["allowed"] is True


def test_a_finished_release_is_still_reported_as_finished():
    out = pipeline_view.promotion_gates(
        {"state": "production_live", "artifact_sha256": ARTIFACT},
        {"environments": []},
        control={"allowed": True, "available": True, "decided_by": "production"},
        registry_is_authoritative=False)
    assert out["complete"] is True
    assert out["allowed"] is False


# --------------------------------------------------------------------------- #
# The endpoint.
# --------------------------------------------------------------------------- #
def test_the_endpoint_authenticates_before_it_decides():
    """Same signed channel as the heartbeat, and the rejection collapses to one
    generic 401 so a prober learns nothing from the difference."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(
        encoding="utf-8")
    block = source[source.index("def _release_control_post"):]
    block = block[:block.index("def _environment_heartbeat_post")]
    assert "verify_publisher" in block
    assert block.index("verify_publisher") < block.index("release_control.decide")
    assert "release_control_unauthorized" in block


def test_the_endpoint_refuses_to_answer_when_it_is_not_authoritative():
    """A development box replying here would be quoting itself back to itself."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(
        encoding="utf-8")
    block = source[source.index("def _release_control_post"):]
    block = block[:block.index("def _environment_heartbeat_post")]
    assert "release_control.authoritative()" in block
    assert block.index("release_control.authoritative()") < block.index("release_control.decide")


def test_the_endpoint_sits_before_the_session_gate():
    """The caller is a server process with a shared key, not a browser.

    Scoped to the POST routing block: _authorize_api is called from several
    places, so a whole-file index would compare against the wrong one.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(
        encoding="utf-8")
    start = source.index("if path == environment_registry.HEARTBEAT_PATH:")
    block = source[start:start + 1500]
    assert "release_control.CONTROL_PATH" in block
    assert block.index("release_control.CONTROL_PATH") < block.index(
        "if not self._authorize_api(path):")


def test_promoting_asks_the_server_at_the_moment_of_the_act():
    """A disabled button is a courtesy. The check that matters runs when the
    action is taken, not from whatever the page last rendered."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(
        encoding="utf-8")
    block = source[source.index('elif action == "promote-production":'):]
    block = block[:block.index('elif action == "mark-production-live":')]
    assert "release_control.request_decision" in block
    assert "promotion_not_authorised" in block
    assert block.index("request_decision") < block.index("promote_production(")
