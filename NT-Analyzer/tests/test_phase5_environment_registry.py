"""Phase 5: the environment registry.

The registry replaces "ask the environment right now" with "the environment
told us, and here is when". Two behaviours carry the whole design and most of
these tests are about them:

* reachability is derived from time alone, never from the metadata, so an
  environment going quiet never blanks out what it last reported;
* every reading is stamped, so a stale fact can never be mistaken for a
  current one.

The rest is input validation and authentication, because a heartbeat is data
from another host: being authenticated says who sent it, not that what they
sent is well formed.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import environment_registry as registry
from app import server as server_mod


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    registry.reset_for_tests()
    monkeypatch.delenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", raising=False)
    monkeypatch.delenv("STRATFORGE_ENVIRONMENT_REGISTRY_PEERS", raising=False)
    # Development: the registry stays in memory, which is what these tests want.
    monkeypatch.setattr(registry, "_authoritative", lambda: False)
    yield
    registry.reset_for_tests()


def beat(environment="canary", **overrides):
    payload = {
        "environment": environment,
        "app_version": "0.10.0-beta.16",
        "git_commit_sha": "04bef4049866",
        "build_id": "build-1",
        "artifact_sha256": "a" * 64,
        "release_channel": "beta",
        "schema_version": 16,
        "readiness": "ready",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Liveness is a function of time, and of nothing else.
# --------------------------------------------------------------------------- #
def test_never_reported_is_distinct_from_gone_quiet():
    """"We have never heard from it" and "it stopped answering" are different
    facts, and an operator needs to tell them apart."""
    assert registry.liveness(None)["state"] == "never_seen"
    assert registry.liveness(1000.0, now=1000.0)["state"] == "live"


def test_liveness_thresholds():
    now = 10_000.0
    assert registry.liveness(now - 10, now=now)["state"] == "live"
    assert registry.liveness(now - registry.LIVE_WINDOW_SEC - 1, now=now)["state"] == "stale"
    assert registry.liveness(now - registry.STALE_WINDOW_SEC - 1, now=now)["state"] == "offline"


def test_offline_environment_keeps_its_last_known_build():
    """The point of the registry. Going quiet must not turn a known version into
    a row of dashes -- the last reported build is still the best information
    anyone has, and it is stamped so nobody mistakes it for current."""
    registry.record(beat())
    row = registry._LOCAL["canary"]
    row["last_seen_at"] = row["last_seen_at"] - registry.STALE_WINDOW_SEC - 60

    public = registry.snapshot()["environments"]
    canary = next(r for r in public if r["environment"] == "canary")
    assert canary["state"] == "offline"
    assert canary["app_version"] == "0.10.0-beta.16"
    assert canary["artifact_sha256"] == "a" * 64
    assert canary["metadata_known"] is True
    assert canary["metadata_is_current"] is False
    assert canary["last_seen_at_utc"], "a stale reading must say when it was taken"


def test_snapshot_lists_every_environment_even_unheard_ones():
    """Omitting an environment would read as "there is no such environment"
    rather than "we have not heard from it"."""
    registry.record(beat("canary"))
    names = [r["environment"] for r in registry.snapshot()["environments"]]
    assert names == list(registry.ENVIRONMENTS)
    development = next(
        r for r in registry.snapshot()["environments"] if r["environment"] == "development"
    )
    assert development["state"] == "never_seen"
    assert development["metadata_known"] is False


def test_first_seen_survives_later_heartbeats():
    registry.record(beat())
    first = registry._LOCAL["canary"]["first_seen_at"]
    registry.record(beat(app_version="0.10.0-beta.17"))
    assert registry._LOCAL["canary"]["first_seen_at"] == first
    assert registry._LOCAL["canary"]["heartbeat_count"] == 2
    assert registry._LOCAL["canary"]["app_version"] == "0.10.0-beta.17"


# --------------------------------------------------------------------------- #
# Validation. Authenticated is not the same as well formed.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload, code", [
    ("not-an-object", "heartbeat_invalid"),
    ({"environment": "staging"}, "environment_unknown"),
    ({"environment": "canary", "artifact_sha256": "nope"}, "artifact_invalid"),
    ({"environment": "canary", "readiness": "probably"}, "readiness_invalid"),
    ({"environment": "canary", "schema_version": -3}, "schema_version_invalid"),
])
def test_malformed_heartbeats_are_rejected(payload, code):
    with pytest.raises(registry.EnvironmentRegistryError) as exc:
        registry.record(payload)
    assert exc.value.code == code


def test_oversized_fields_are_truncated_not_rejected():
    """A long build id is a cosmetic problem, not an attack. Truncate and keep
    the heartbeat rather than losing the whole reading over it."""
    registry.record(beat(build_id="b" * 500, app_version="v" * 500))
    row = registry._LOCAL["canary"]
    assert len(row["build_id"]) == 128
    assert len(row["app_version"]) == 64


def test_details_are_bounded():
    registry.record(beat(details={f"k{i}": "v" * 500 for i in range(50)}))
    details = registry._LOCAL["canary"]["details"]
    assert len(details) <= registry._DETAILS_MAX_KEYS
    assert all(len(v) <= registry._DETAILS_MAX_VALUE for v in details.values())


def test_details_that_are_not_an_object_are_dropped():
    registry.record(beat(details=["a", "b"]))
    assert registry._LOCAL["canary"]["details"] == {}


# --------------------------------------------------------------------------- #
# Authentication.
# --------------------------------------------------------------------------- #
def test_token_must_be_configured_and_long_enough(monkeypatch):
    assert registry.token_configured() is False
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "short")
    assert registry.token_configured() is False
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    assert registry.token_configured() is True


def test_unconfigured_token_matches_nothing(monkeypatch):
    """An empty token must not mean "everything is authorized"."""
    assert registry.token_matches("") is False
    assert registry.token_matches("anything") is False


def test_token_comparison_rejects_a_prefix(monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    assert registry.token_matches("t" * 39) is False
    assert registry.token_matches("t" * 41) is False
    assert registry.token_matches("t" * 40) is True


# --------------------------------------------------------------------------- #
# Publishing targets come from configuration only.
# --------------------------------------------------------------------------- #
def test_peer_origins_require_https_or_loopback(monkeypatch):
    monkeypatch.setenv(
        "STRATFORGE_ENVIRONMENT_REGISTRY_PEERS",
        "https://canary.example.com, http://evil.example.com, http://127.0.0.1:8765",
    )
    assert registry.peer_origins() == [
        "https://canary.example.com", "http://127.0.0.1:8765",
    ]


def test_peer_origins_are_deduplicated(monkeypatch):
    monkeypatch.setenv(
        "STRATFORGE_ENVIRONMENT_REGISTRY_PEERS",
        "https://a.example.com https://a.example.com/ https://b.example.com",
    )
    assert registry.peer_origins() == ["https://a.example.com", "https://b.example.com"]


def test_publishing_without_a_token_declines_rather_than_sending(monkeypatch):
    sent = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: sent.append(a))
    out = registry.publish_to("https://canary.example.com", force=True)
    assert out == {"ok": False, "code": "token_not_configured"}
    assert sent == [], "an unauthenticated heartbeat must never leave the process"


def test_publish_round_survives_an_unreachable_peer(monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    monkeypatch.setenv(
        "STRATFORGE_ENVIRONMENT_REGISTRY_PEERS",
        "https://down.example.com https://up.example.com",
    )
    monkeypatch.setattr(registry, "self_heartbeat",
                        lambda **_: registry.normalize_heartbeat(beat()))

    calls = []

    def urlopen(request, timeout=None):
        calls.append(request.full_url)
        if "down" in request.full_url:
            raise OSError("connection refused")

        class _Response:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *args):
                return False

            def read(self_inner, _n=0):
                return b"{}"

        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    out = registry.publish_round(force=True)
    assert len(calls) == 2, "one dead peer must not stop the others being told"
    assert out["peers"]["https://down.example.com"]["ok"] is False
    assert out["peers"]["https://up.example.com"]["ok"] is True


def test_token_travels_in_a_header_not_the_url(monkeypatch):
    """A token in a query string ends up in access logs and proxy caches."""
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    monkeypatch.setattr(registry, "self_heartbeat",
                        lambda **_: registry.normalize_heartbeat(beat()))
    captured = {}

    def urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())

        class _Response:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *args):
                return False

            def read(self_inner, _n=0):
                return b"{}"

        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    registry.publish_to("https://canary.example.com", force=True)
    assert "t" * 40 not in captured["url"]
    assert captured["headers"].get("X-stratforge-registry-token") == "t" * 40


def test_publishing_is_throttled(monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    monkeypatch.setattr(registry, "self_heartbeat",
                        lambda **_: registry.normalize_heartbeat(beat()))
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("throttled"))
    registry._PUBLISH_STATE["peer:https://canary.example.com"] = registry._now()
    out = registry.publish_to("https://canary.example.com")
    assert out["code"] == "throttled"


# --------------------------------------------------------------------------- #
# Compare.
# --------------------------------------------------------------------------- #
def test_compare_flags_a_real_disagreement():
    registry.record(beat("canary", artifact_sha256="a" * 64))
    registry.record(beat("production", artifact_sha256="b" * 64))
    fields = {f["field"]: f for f in registry.snapshot()["compare"]["fields"]}
    assert fields["artifact_sha256"]["differs"] is True
    assert fields["app_version"]["differs"] is False


def test_compare_ignores_environments_nobody_has_heard_from():
    """An unheard environment contributing an empty string would make every
    field look like a mismatch, which trains the reader to ignore the panel."""
    registry.record(beat("canary"))
    registry.record(beat("production"))
    compare = registry.snapshot()["compare"]
    assert compare["environments"] == ["canary", "production"]
    assert all(not field["differs"] for field in compare["fields"])


def test_missing_value_is_reported_as_missing_not_as_a_mismatch():
    registry.record(beat("canary", schema_version=16))
    registry.record(beat("production", schema_version=0))
    fields = {f["field"]: f for f in registry.snapshot()["compare"]["fields"]}
    assert fields["schema_version"]["differs"] is False
    assert fields["schema_version"]["missing"] == ["production"]


def test_parity_is_answered_directly():
    registry.record(beat("canary", artifact_sha256="c" * 64))
    registry.record(beat("production", artifact_sha256="c" * 64))
    parity = registry.snapshot()["compare"]["canary_production_parity"]
    assert parity["known"] is True and parity["match"] is True
    assert parity["both_current"] is True


def test_parity_between_two_stale_reports_says_so():
    """Parity is only as fresh as the two readings behind it."""
    registry.record(beat("canary", artifact_sha256="c" * 64))
    registry.record(beat("production", artifact_sha256="c" * 64))
    for row in registry._LOCAL.values():
        row["last_seen_at"] = row["last_seen_at"] - registry.LIVE_WINDOW_SEC - 10

    parity = registry.snapshot()["compare"]["canary_production_parity"]
    assert parity["known"] is True and parity["match"] is True
    assert parity["both_current"] is False
    assert parity["canary_as_of_utc"] and parity["production_as_of_utc"]


def test_parity_is_unknown_when_only_one_side_reported():
    registry.record(beat("canary"))
    parity = registry.snapshot()["compare"]["canary_production_parity"]
    assert parity["known"] is False
    assert parity["reason"] == "not_both_reported"


def test_parity_is_unknown_when_the_artifact_was_not_reported():
    registry.record(beat("canary", artifact_sha256=""))
    registry.record(beat("production", artifact_sha256="c" * 64))
    parity = registry.snapshot()["compare"]["canary_production_parity"]
    assert parity["known"] is False
    assert parity["reason"] == "artifact_not_reported"


# --------------------------------------------------------------------------- #
# HTTP contract.
#
# The route sits ahead of the session/CSRF gate because its caller is another
# server process with no browser session. That placement is exactly the sort of
# thing that is easy to get subtly wrong, so it is tested through a real server
# rather than by calling the module.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def http_server():
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        yield base
    finally:
        server.shutdown()


def _heartbeat(base, payload, token):
    headers = {"Content-Type": "application/json", "Origin": base}
    if token is not None:
        headers["X-StratForge-Registry-Token"] = token
    request = urllib.request.Request(
        base + registry.HEARTBEAT_PATH,
        data=json.dumps(payload).encode("utf-8"),
        method="POST", headers=headers,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def test_heartbeat_requires_the_token(http_server, monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    for token in (None, "", "w" * 40):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _heartbeat(http_server, beat(), token)
        assert exc.value.code == 401


def test_heartbeat_401_says_nothing_about_the_token(http_server, monkeypatch):
    """A refusal must not reveal whether the token was absent, wrong or how
    long the real one is."""
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _heartbeat(http_server, beat(), "w" * 40)
    body = exc.value.read().decode("utf-8")
    assert "t" * 40 not in body
    assert json.loads(body)["code"] == "registry_unauthorized"


def test_heartbeat_without_a_configured_token_is_unavailable_not_open(http_server):
    """No token configured must mean "closed", never "anyone may write"."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _heartbeat(http_server, beat(), "anything")
    assert exc.value.code == 503
    assert json.loads(exc.value.read().decode("utf-8"))["code"] == "registry_not_configured"


def test_heartbeat_is_accepted_and_reaches_the_snapshot(http_server, monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    out = _heartbeat(http_server, beat(), "t" * 40)
    assert out["ok"] is True
    canary = next(
        row for row in registry.snapshot()["environments"] if row["environment"] == "canary"
    )
    assert canary["state"] == "live"
    assert canary["app_version"] == "0.10.0-beta.16"


def test_heartbeat_payload_is_validated_even_when_authenticated(http_server, monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENVIRONMENT_REGISTRY_TOKEN", "t" * 40)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _heartbeat(http_server, {"environment": "nowhere"}, "t" * 40)
    assert exc.value.code == 400
    assert json.loads(exc.value.read().decode("utf-8"))["code"] == "environment_unknown"


# --------------------------------------------------------------------------- #
# Self-report.
# --------------------------------------------------------------------------- #
def test_self_heartbeat_describes_this_process_only(monkeypatch):
    """Built from the deployment config the process started with, so nothing
    arriving over the network can make an environment misreport itself."""
    from app import runtime_env

    monkeypatch.setattr(runtime_env, "deployment_environment", lambda: "canary")
    monkeypatch.setattr(runtime_env, "public_status", lambda: {
        "app_version": "0.10.0-beta.16",
        "git_commit_sha": "04bef4049866",
        "build_id": "build-9",
        "artifact_sha256": "d" * 64,
        "release_channel": "beta",
        "runtime_profile": "server",
        "region": "eu",
        "build_timestamp_utc": "2026-08-17T02:00:00Z",
    })
    monkeypatch.setattr(registry, "_schema_version", lambda: 16)

    out = registry.self_heartbeat(readiness=lambda: {"status": "ready"})
    assert out["environment"] == "canary"
    assert out["artifact_sha256"] == "d" * 64
    assert out["schema_version"] == 16
    assert out["readiness"] == "ready"
    assert out["details"]["region"] == "eu"


def test_readiness_without_a_supplier_is_unreported_not_failing():
    """Computing readiness without the server's registered component probes
    made a healthy Production report not_ready. Reporting nothing is honest;
    reporting a fault that does not exist is not."""
    assert registry._readiness(None) == ""
    assert registry._readiness(lambda: {"status": "ready"}) == "ready"
    assert registry._readiness(lambda: {"status": "not_ready"}) == "not_ready"


def test_readiness_supplier_failure_is_unreported_not_failing():
    def boom():
        raise RuntimeError("probe exploded")

    assert registry._readiness(boom) == ""


def test_unknown_readiness_value_is_dropped():
    assert registry._readiness(lambda: {"status": "probably fine"}) == ""


def test_the_publisher_uses_the_readiness_supplier_it_was_given(monkeypatch):
    monkeypatch.setattr(registry, "_schema_version", lambda: 16)
    monkeypatch.setattr(
        registry, "peer_origins", lambda: [],
    )
    publisher = registry.HeartbeatPublisher(readiness=lambda: {"status": "ready"})
    seen = {}

    def capture_then_stop(*, force=False, readiness=None):
        seen["readiness"] = readiness
        publisher._stop.set()
        return {}

    monkeypatch.setattr(registry, "publish_round", capture_then_stop)
    publisher._loop()
    assert seen["readiness"] is not None
    assert seen["readiness"]() == {"status": "ready"}
