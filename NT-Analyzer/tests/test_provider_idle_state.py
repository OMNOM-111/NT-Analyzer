"""A provider with nothing to do is idle, not connecting, and not a fault.

TopstepX is a failover source: it holds a shared chart-provider session and
subscribes only when a chart asks for a contract. With no subscribers it never
receives a record, and the adapter kept reporting CONNECTING -- describing a
connection attempt that was never started. The dashboard then read "no provider
is LIVE" as degraded and painted market data red on a server whose primary was
serving bars the whole time. A panel that cries wolf about a healthy system is
worse than no panel.

None of this changes routing, source priority or which provider serves a chart.
It changes what the system says about itself.
"""
from __future__ import annotations

import pytest

from app import market_data_live_adapters as adapters
from app import server as server_mod


@pytest.fixture()
def provider():
    """Only the reporting rule is under test, so the transport is left unbuilt."""
    import threading

    instance = adapters.TopstepXProjectXAdapter.__new__(
        adapters.TopstepXProjectXAdapter)
    instance._lock = threading.RLock()
    instance._subs = {}
    instance._last_error = ""
    instance._wire_subscribed_contract_ids = set()
    instance._pending_signal_invocations = {}
    instance._connected_at = ""
    instance._connect_requested = False
    return instance


def test_a_configured_provider_with_no_subscribers_is_idle(provider):
    """The exact case: credentials fine, no error, nobody asking."""
    provider._runtime_state = "CONNECTING"
    assert provider.reported_runtime_state() == "IDLE"


def test_an_asked_for_connection_is_connecting_even_with_no_subscribers(provider):
    """connect() is an attempt in flight, which is what CONNECTING is for.

    The resting state the server actually showed had never had one asked for:
    connected_at_utc was empty, which is the difference between the two.
    """
    provider._runtime_state = "CONNECTING"
    provider._connect_requested = True
    assert provider.reported_runtime_state() == "CONNECTING"


def test_a_provider_with_a_wire_subscription_is_connecting(provider):
    """Once something has actually been subscribed, CONNECTING is the truth."""
    provider._runtime_state = "CONNECTING"
    provider._wire_subscribed_contract_ids = {"CON.F.US.MNQ.U26"}
    assert provider.reported_runtime_state() == "CONNECTING"


def test_a_logical_subscriber_alone_is_enough_to_be_connecting(provider):
    provider._runtime_state = "CONNECTING"
    provider._subs = {"sub-1": {"consumers": {"chart-a"}}}
    assert provider.reported_runtime_state() == "CONNECTING"


def test_an_error_is_never_relabelled_as_idle(provider):
    """Idle is the absence of demand, never the absence of a working socket."""
    provider._runtime_state = "CONNECTING"
    provider._last_error = "handshake refused"
    assert provider.reported_runtime_state() == "CONNECTING"


@pytest.mark.parametrize("state", [
    "LIVE", "DEGRADED", "ERROR", "AUTH_FAILED", "ENTITLEMENT_MISSING",
    "OFFLINE", "DISABLED", "AUTHENTICATED",
])
def test_every_other_state_is_passed_through_untouched(provider, state):
    provider._runtime_state = state
    assert provider.reported_runtime_state() == state


# --------------------------------------------------------------------------- #
# What the dashboard makes of it.
# --------------------------------------------------------------------------- #
def _row(name, state, *, configured=True, eligible=True, blocking=()):
    return {
        "name": name, "runtime_state": state, "configured": configured,
        "live_eligible": eligible, "blocking_reasons": list(blocking),
    }


def test_the_panel_uses_this_rule_and_not_a_copy_of_it():
    """_section below restates the verdict; this pins it to the real code.

    Without this the rule tests would keep passing while the panel drifted
    back to "no provider is LIVE means degraded".
    """
    from pathlib import Path

    text = Path(server_mod.__file__).read_text(encoding="utf-8")
    body = text[text.index("def providers() -> Dict[str, Any]:"):]
    body = body[: body.index("def connector_installations()")]
    assert '"state": "healthy" if live else "degraded"' not in body
    assert "_PROVIDER_FAULT_STATES" in body
    assert 'row.get("configured") and row.get("live_eligible")' in body
    assert '"idle"' in body and '"faulted"' in body


def _section(rows):
    """Rebuild the dashboard verdict from the same rule the panel uses."""
    eligible = [r for r in rows if r["configured"] and r["live_eligible"]]
    faulted = [
        r["name"] for r in eligible
        if r["blocking_reasons"]
        or str(r["runtime_state"]).upper() in server_mod._PROVIDER_FAULT_STATES
    ]
    if faulted:
        return "degraded"
    return "healthy" if eligible else "not_configured"


def test_an_idle_failover_provider_does_not_make_market_data_degraded():
    assert _section([
        _row("topstepx", "IDLE"),
        _row("databento", "DISABLED", configured=False, eligible=False),
        _row("yahoo_chart", "STALE", eligible=False),
    ]) == "healthy"


def test_a_live_provider_is_healthy():
    assert _section([_row("topstepx", "LIVE")]) == "healthy"


@pytest.mark.parametrize("state", ["ERROR", "AUTH_FAILED", "ENTITLEMENT_MISSING", "OFFLINE"])
def test_a_genuinely_broken_provider_is_still_degraded(state):
    """The point is to stop crying wolf, not to stop reporting."""
    assert _section([_row("topstepx", state)]) == "degraded"


def test_a_blocking_reason_is_degraded_whatever_the_state_says():
    assert _section([_row("topstepx", "IDLE", blocking=("redistribution_denied",))]) == "degraded"


def test_a_degraded_live_provider_is_still_degraded():
    """DEGRADED means a connected feed that fell behind -- a real fault."""
    assert _section([_row("topstepx", "DEGRADED")]) == "degraded"


def test_only_eligible_providers_are_judged():
    """A provider nobody may use live cannot make the panel red."""
    assert _section([
        _row("yahoo_chart", "STALE", eligible=False),
        _row("topstepx", "IDLE"),
    ]) == "healthy"


def test_idle_is_not_a_live_state_so_routing_is_unchanged():
    """Naming the resting state must not make it eligible to serve data."""
    from app import market_data_access

    assert "IDLE" not in market_data_access._LIVE_STATES
    assert "CONNECTING" not in market_data_access._LIVE_STATES
