"""Canonical live mirror admission and disposable chart transport boundaries."""
from types import SimpleNamespace
import threading
import time

import pytest

from app import dev_preview, preview_shared_models, runtime_env, preview_sandbox, server
from app.ai_control_center.states import ContractError
from tests.test_market_data_access import _context, _resolve, NOW
from datetime import timedelta


def test_paid_trial_and_denied_access_use_one_mirror_contract():
    for plan in ("trial_full", "professional"):
        row = {"user_id": 42, "status": "active", "plan_id": plan,
               "expires_at_utc": (NOW + timedelta(hours=5)).isoformat()}
        decision = _resolve(_context(), subscription_lookup=lambda _: row)
        assert decision.allowed and decision.source == "shared_trial"
        assert decision.reason == "active_shared_mirror"
        for change in ({"status": "revoked"}, {"active": False}, {"user_id": 99},
                       {"expires_at_utc": (NOW - timedelta(seconds=1)).isoformat()},
                       {"features": {"charts_realtime": False}}):
            assert not _resolve(_context(), subscription_lookup=lambda _: {**row, **change}).allowed
        denied = _context()
        denied["capabilities"]["charts_realtime"] = False
        assert not _resolve(denied, subscription_lookup=lambda _: row).allowed


def test_personal_ninjatrader_precedes_other_owned_providers():
    row = {"workspace_id": "ws-42", "owner_user_id": 42, "status": "online",
           "capabilities": ["live_read"], "installation_id": "own-nt", "last_heartbeat_utc": NOW.isoformat()}
    decision = _resolve(_context(), personal_connector_probe=lambda *a: row,
                        owned_provider_probe=lambda *a: pytest.fail("personal NT must be first"))
    assert decision.source == "personal_connector"


def _bridge(monkeypatch):
    bridge = object.__new__(preview_shared_models.Bridge)
    bridge.closed = False
    bridge.started = time.monotonic()
    bridge.token = "disposable-capability"
    bridge.preview_id = "preview-id"
    monkeypatch.setattr(runtime_env, "is_development", lambda: True)
    monkeypatch.setattr(preview_sandbox, "enabled", lambda: False)
    monkeypatch.setattr(dev_preview, "_validated_preview_container", lambda _: True)
    monkeypatch.setattr(dev_preview, "_ACTIVE_SANDBOX", {
        "preview_id": bridge.preview_id, "model_bridge": bridge,
        "process": SimpleNamespace(poll=lambda: None),
    })
    return bridge


def test_chart_capability_is_local_active_preview_and_exact_path_only(monkeypatch):
    bridge = _bridge(monkeypatch)
    bridge.authorize_chart(bridge.token, "/api/ops/runtime/bars")
    bridge.authorize_chart(bridge.token, "/ws/market-data")
    for path in ("/api/auth/me", "/api/ops/runtime/accounts", "/api/ops/runtime/bars/status", "/catalog"):
        with pytest.raises(ContractError):
            bridge.authorize_chart(bridge.token, path)
    with pytest.raises(ContractError):
        bridge.authorize_chart("wrong", "/ws/market-data")
    monkeypatch.setattr(runtime_env, "is_development", lambda: False)
    with pytest.raises(ContractError):
        bridge.authorize_chart(bridge.token, "/ws/market-data")
    monkeypatch.setattr(runtime_env, "is_development", lambda: True)
    dev_preview._ACTIVE_SANDBOX["preview_id"] = "other-preview"
    with pytest.raises(ContractError):
        bridge.authorize_chart(bridge.token, "/ws/market-data")
    dev_preview._ACTIVE_SANDBOX["preview_id"] = bridge.preview_id
    bridge.closed = True
    with pytest.raises(ContractError):
        bridge.authorize_chart(bridge.token, "/ws/market-data")


def test_chart_history_projects_only_market_fields(monkeypatch):
    def payload(*args, **kwargs):
        assert kwargs["alerts_index"] == {} and not kwargs["register"]
        return {"instrument": "MES 12-26", "live": True, "bars": [{"t": "now", "c": 6, "owner_id": 42}],
                "alerts": ["private"], "account": "private", "source": {"runtime_state": "LIVE", "key": "secret"}}
    monkeypatch.setattr(server, "_market_bars_payload", payload)
    result = preview_shared_models.Bridge.chart_history({"instrument": ["MES"]})
    assert result == {"instrument": "MES 12-26", "live": True, "bars": [{"t": "now", "c": 6}],
                      "source": {"runtime_state": "LIVE"}, "history": {}, "freshness": {}}


def test_closing_preview_disconnects_chart_leases(monkeypatch):
    bridge = _bridge(monkeypatch)
    events = []
    connection = SimpleNamespace(shutdown=lambda _: events.append("shutdown"), close=lambda: events.append("close"))
    bridge.chart_lock = threading.Lock()
    bridge.chart_connections = [connection]
    bridge.server = SimpleNamespace(shutdown=lambda: None, server_close=lambda: None)
    bridge.results = {}
    bridge.close()
    assert bridge.closed and events == ["shutdown", "close"] and not bridge.chart_connections
