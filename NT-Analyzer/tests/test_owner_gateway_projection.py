"""Canary sees the Production NinjaTrader without being able to touch it.

There is one NinjaTrader beside the Linux server and it is enrolled to
Production. Canary still has to be acceptance-tested against the same live
device, and the two dishonest ways to arrange that are a second enrollment
competing for the device, or Canary quietly answering from its own empty
registry and showing NO DATA as though that were a fact about NinjaTrader.

The honest arrangement is a mirror: Canary consumes what Production already
accepted, over the owner gateway that already carries owner market data, on a
list of reads that contains nothing capable of acting. Production remains the
only environment that can command the device.
"""
from __future__ import annotations

import pytest

from app import owner_market_data_gateway as gateway


def test_only_read_paths_are_projectable():
    assert gateway.is_projection_path("/api/ops/runtime/heartbeat")
    assert gateway.is_projection_path("/api/ops/runtime/accounts")
    assert gateway.is_projection_path("/api/ops/runtime/accounts?workspace_id=x")


@pytest.mark.parametrize("path", [
    "/api/bridge/commands",
    "/api/ops/runtime/command",
    "/api/connector/v1/heartbeat",
    "/api/connector/v1/commands/poll",
    "/api/bridge/connections/abc/revoke",
    "/api/admin/releases/rc_1/promote-production",
])
def test_nothing_that_acts_is_projectable(path):
    """A consumer that could command the device would be a second authority."""
    assert gateway.is_projection_path(path) is False
    assert gateway.is_gateway_path(path) is False


def test_chart_paths_are_still_gateway_paths():
    """The projection is added beside chart fan-out, not instead of it."""
    for path in gateway.CHART_PATHS:
        assert gateway.is_gateway_path(path)


def test_a_projection_says_it_is_a_projection(monkeypatch):
    """A mirror that does not admit it is a mirror is how a consumer gets
    mistaken for the environment that owns the device."""
    monkeypatch.setattr(gateway, "fetch_gateway_json",
                        lambda path, query=None, timeout=20.0: {
                            "ok": True, "functional_live": True, "account_count": 4,
                        })
    monkeypatch.setattr(gateway, "gateway_url", lambda: "https://app.stratforges.com")
    out = gateway.projected_runtime("/api/ops/runtime/heartbeat")
    assert out["functional_live"] is True
    assert out["projection_read_only"] is True
    assert out["projected_from"] == "production"
    assert out["projected_at_utc"]


def test_an_unprojectable_path_is_refused_before_any_request(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("must not reach the hub for a non-projectable path")

    monkeypatch.setattr(gateway, "fetch_gateway_json", explode)
    with pytest.raises(RuntimeError):
        gateway.projected_runtime("/api/bridge/commands")


def test_the_consumer_answers_locally_when_the_hub_is_silent():
    """A hub that cannot be reached is not evidence about NinjaTrader.

    The route falls through to the local answer rather than reporting a state
    it never observed -- the same rule the environment registry follows.
    """
    from pathlib import Path
    source = Path(gateway.__file__).resolve().parent / "server.py"
    text = source.read_text(encoding="utf-8")
    block = text[text.index("owner_market_data_gateway.should_consume()"):]
    block = block[: block.index("_connector_is_the_runtime_transport(qs)")]
    assert "except Exception:" in block
    assert "pass" in block


# --------------------------------------------------------------------------- #
# The hub has to know whose Connector it is answering about.
# --------------------------------------------------------------------------- #
def test_a_gateway_request_is_scoped_to_the_owner(monkeypatch):
    """Otherwise the hub answers from its own runtime directory.

    On a Linux server that directory is empty, so the consumer faithfully
    mirrored "no NinjaTrader" from the environment that had one -- the exact
    failure the projection exists to remove.
    """
    from app import account_auth

    monkeypatch.setattr(account_auth, "primary_owner_id", lambda: 1647145559)
    out = gateway.owner_scoped_context(gateway.service_context())
    assert out["user_id"] == 1647145559
    assert out["is_owner"] is True


def test_a_request_that_already_names_a_user_is_left_alone(monkeypatch):
    """A real session must never be re-pointed at the owner's data."""
    from app import account_auth

    monkeypatch.setattr(account_auth, "primary_owner_id", lambda: 1647145559)
    context = {"owner_market_gateway": True, "user_id": 42}
    assert gateway.owner_scoped_context(context)["user_id"] == 42


def test_an_ordinary_request_is_not_promoted_to_the_owner(monkeypatch):
    """Only the gateway's own authenticated context gets this."""
    from app import account_auth

    monkeypatch.setattr(account_auth, "primary_owner_id", lambda: 1647145559)
    assert gateway.owner_scoped_context({}) == {}
    assert gateway.owner_scoped_context({"is_owner": True}) == {"is_owner": True}


def test_no_owner_configured_leaves_the_context_unchanged(monkeypatch):
    from app import account_auth

    monkeypatch.setattr(account_auth, "primary_owner_id", lambda: 0)
    context = gateway.service_context()
    assert gateway.owner_scoped_context(context) == context
