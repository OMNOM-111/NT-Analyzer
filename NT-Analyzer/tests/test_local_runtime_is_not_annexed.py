"""LOCAL keeps its own NinjaTrader, its own data, and its own answers.

Development runs beside NinjaTrader: it reads the runtime directory that the
AddOn writes, and it asks the operating system whether NinjaTrader is running.
That arrangement worked long before the signed Connector protocol existed and
is not improved by routing it over a network to the same machine.

The Connector work broke it anyway. A stricter definition of "functional" was
introduced for the server -- heartbeat alone stopped counting as healthy, which
was right -- but the switch was decided at each call site as "is a Connector
installation enrolled?" rather than "is there no local NinjaTrader to read?".
Development has an enrolled installation, so LOCAL began answering from the
Connector: NinjaTrader read as inactive on a machine where it was running, and
every account vanished from a runtime directory where they were still on disk.

These tests hold the boundary. Server Connector work, release identity work and
promotion work may all change; none of them may reach across and answer for a
local NinjaTrader, move the data root, change the active workspace, or hide
local data that exists.
"""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import runtime as ops_runtime
from app import runtime_env
from app import server as server_mod


# --------------------------------------------------------------------------- #
# The rule itself, stated once and asserted here.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def development(monkeypatch):
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: False)
    monkeypatch.setattr(runtime_env, "is_production", lambda: False)


@pytest.fixture()
def production(monkeypatch):
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(runtime_env, "is_production", lambda: True)


def test_development_does_not_route_runtime_through_the_connector(development):
    assert server_mod._connector_is_the_runtime_transport() is False
    assert server_mod._connector_is_the_runtime_transport({}) is False


def test_production_routes_runtime_through_the_connector(production):
    assert server_mod._connector_is_the_runtime_transport() is True


def test_an_explicit_transport_request_is_still_honoured(development):
    """The Connector view stays reachable from LOCAL -- by asking for it."""
    assert server_mod._connector_is_the_runtime_transport(
        {"transport": ["production_connector"]}) is True


def test_an_enrolled_installation_alone_does_not_switch_the_transport(development):
    """The trigger is "no local NinjaTrader to read", never "a Connector exists".

    Development has an enrolled installation of its own. Treating that as the
    signal is precisely what took LOCAL's data path away.
    """
    assert server_mod._connector_is_the_runtime_transport() is False


# --------------------------------------------------------------------------- #
# What the rule protects.
# --------------------------------------------------------------------------- #
def _health(monkeypatch, *, running: bool, connector: dict) -> dict:
    monkeypatch.setenv("NTA_TEST_BYPASS_AUTH", "1")
    monkeypatch.setattr(server_mod.jobqueue, "ninjatrader_running", lambda: running)
    monkeypatch.setattr(server_mod, "_connector_runtime_status",
                        lambda _context: connector)
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()


def test_a_running_local_ninjatrader_is_reported_running(development, monkeypatch):
    """The regression, exactly: NinjaTrader was running and read as inactive."""
    health = _health(monkeypatch, running=True, connector={
        "present": True, "fresh": True, "functional_live": False,
    })
    assert health["ninjatrader_running"] is True


def test_a_stopped_local_ninjatrader_is_not_rescued_by_a_connector(development, monkeypatch):
    """The boundary holds in both directions, or it is not a boundary."""
    health = _health(monkeypatch, running=False, connector={
        "present": True, "fresh": True, "functional_live": True,
    })
    assert health["ninjatrader_running"] is False


def test_on_a_server_the_connector_is_the_only_evidence(production, monkeypatch):
    """A server has no NinjaTrader of its own, so the local check is noise.

    Asserted on the handler rather than over HTTP: a production server demands
    a real session, and faking one would test the fake.
    """
    handler = object.__new__(server_mod.Handler)
    handler._remote_context = {"user_id": 42}
    monkeypatch.setattr(server_mod.jobqueue, "ninjatrader_running", lambda: True)
    monkeypatch.setattr(server_mod, "_connector_runtime_status", lambda _context: {
        "present": True, "fresh": True, "functional_live": False, "accounts": [],
    })
    replies = []
    handler._json = lambda status, payload: replies.append((status, payload))
    assert handler._ops_get("/api/ops/runtime/accounts", {}) is True
    assert replies[0][1]["source"] == "production_connector"
    assert replies[0][1]["accounts"] == []


# --------------------------------------------------------------------------- #
# Local data stays local, stays put, and stays visible.
# --------------------------------------------------------------------------- #
def test_local_accounts_are_read_from_the_runtime_directory(development, tmp_path):
    """Accounts on disk must reach the caller, not be replaced by an empty
    Connector payload that says the AddOn never sent a snapshot."""
    (tmp_path / "accounts.json").write_text(json.dumps({
        "generated_at_utc": "2026-08-27T00:48:35Z",
        "exporter_version": "1.3.0",
        "accounts": [
            {"account_name": "DEMO3369390", "account_mode": "paper",
             "cash_value": 11017.42, "net_liquidation": 11017.42,
             "connection_status": "Connected"},
            {"account_name": "Sim101", "account_mode": "paper",
             "cash_value": 100000, "net_liquidation": 100000,
             "connection_status": "Connected"},
        ],
    }), encoding="utf-8")
    with ops_runtime.runtime_dir_override(str(tmp_path)):
        payload = ops_runtime.read_accounts_with_source()
    names = [row.get("account_name") for row in payload.get("accounts") or []]
    assert "DEMO3369390" in names
    assert payload.get("source") != "production_connector"


def test_the_local_runtime_directory_is_not_taken_from_an_owner_workspace():
    """An owner workspace runs on the owner's own runtime directory.

    Returning a per-workspace path here would silently move LOCAL's data root
    and make existing strategies and accounts look deleted.
    """
    from app import workspaces
    assert workspaces.runtime_dir_for_context({
        "active_workspace": {"workspace_id": "ws_owner_training_x",
                             "uses_owner_runtime": True,
                             "default_runtime_connection_id": "owner_local"},
    }) == ""


def test_an_owner_workspace_is_never_answered_with_a_not_connected_stub():
    """The stub is for a tenant with no bridge yet. Handing it to the owner
    would blank out a working local NinjaTrader and everything under it."""
    from app import workspaces
    assert workspaces.runtime_stub("/api/ops/runtime/accounts", {}, {
        "active_workspace": {"workspace_id": "ws_owner_training_x",
                             "uses_owner_runtime": True},
    }) is None
