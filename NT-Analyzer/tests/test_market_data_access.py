"""Fail-closed market-data entitlement and browser fan-out regressions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import market_data_access, market_data_ws_http, server as server_mod


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _context(user_id: int = 42, user_uuid: str = "user-a") -> dict:
    return {
        "user_id": user_id,
        "user_uuid": user_uuid,
        "is_owner": False,
        "capabilities": {"charts_realtime": True},
        "workspace_id": f"ws-{user_id}",
        "active_workspace": {
            "workspace_id": f"ws-{user_id}",
            "kind": "personal",
            "owner_user_id": user_id,
            "uses_owner_runtime": False,
        },
    }


def _resolve(context: dict, **kwargs):
    defaults = {
        "exact_contract": "MNQ 09-26",
        "timeframe": "5m",
        "now": NOW,
        "owned_provider_probe": lambda *_args: None,
        "personal_connector_probe": lambda *_args: None,
        "subscription_lookup": lambda _user_id: {},
        "policy_flags": {
            "remote_server_authorized": False,
            "redistribution_authorized": False,
        },
    }
    defaults.update(kwargs)
    return market_data_access.resolve_market_data_access(context, **defaults)


def test_market_data_access_requires_authenticated_subject_but_owner_is_authoritative() -> None:
    denied = _resolve({})
    assert denied.allowed is False
    assert denied.reason == "authentication_required"

    owner = _resolve({"is_owner": True, "source": "local"})
    assert owner.allowed is True
    assert owner.source == "owner"
    assert owner.scope_id == market_data_access.OWNER_SHARED_SCOPE


def test_shared_registration_trial_requires_both_redistribution_flags() -> None:
    context = _context()
    trial = {
        "user_id": 42,
        "user_uuid": "user-a",
        "status": "active",
        "source": "verified_registration",
        "provider": "registration",
        "plan_id": "trial_full",
        "access_kind": "initial_trial",
        "expires_at_utc": (NOW + timedelta(days=7)).isoformat(),
    }

    one_flag = _resolve(
        context,
        subscription_lookup=lambda _user_id: trial,
        policy_flags={
            "remote_server_authorized": True,
            "redistribution_authorized": False,
        },
    )
    assert one_flag.allowed is False
    assert one_flag.reason == "redistribution_not_authorized"

    allowed = _resolve(
        context,
        subscription_lookup=lambda _user_id: trial,
        policy_flags={
            "remote_server_authorized": True,
            "redistribution_authorized": True,
        },
    )
    assert allowed.allowed is True
    assert allowed.source == "shared_trial"
    assert allowed.scope_id == market_data_access.OWNER_SHARED_SCOPE
    assert 0 < allowed.revalidate_after_sec <= 5


def test_shared_trial_missing_or_expired_expiry_fails_closed() -> None:
    context = _context()
    for expires in ("", "not-a-date", (NOW - timedelta(seconds=1)).isoformat()):
        decision = _resolve(
            context,
            subscription_lookup=lambda _user_id, value=expires: {
                "user_id": 42,
                "status": "trial",
                "source": "registration_trial",
                "expires_at_utc": value,
            },
            policy_flags={
                "remote_server_authorized": True,
                "redistribution_authorized": True,
            },
        )
        assert decision.allowed is False
        assert decision.reason == "market_data_entitlement_required"


def test_expired_trial_message_does_not_promise_unauthorized_shared_feed() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(
        encoding="utf-8"
    )

    assert "Продление владельцем открывает общий trial-feed" in source
    assert "только там, где подтверждено разрешение на redistribution" in source


def test_verified_owned_provider_is_private_and_unverified_provider_is_denied() -> None:
    context = _context()
    connector = object()
    entitlement = {
        "workspace_id": "ws-42",
        "user_id": 42,
        "user_uuid": "user-a",
        "provider": "topstep",
        "account_id": "acct-a",
        "live_eligible": True,
        "API_access_enabled": True,
        "sharing_scope": "private",
        "runtime_state": "LIVE",
        "channels": ["trades", "quotes"],
        "expiration": (NOW + timedelta(days=30)).isoformat(),
        "connector": connector,
    }
    allowed = _resolve(
        context,
        owned_provider_probe=lambda *_args: entitlement,
    )
    assert allowed.allowed is True
    assert allowed.source == "owned_provider"
    assert allowed.connector is connector
    assert allowed.scope_id.startswith("private:")
    assert "user-a" not in allowed.scope_id

    unverified = dict(entitlement, runtime_state="CONFIGURED_UNVERIFIED")
    denied = _resolve(
        context,
        owned_provider_probe=lambda *_args: unverified,
    )
    assert denied.allowed is False


def test_online_personal_connector_requires_own_fresh_live_read_heartbeat() -> None:
    context = _context()
    connector = {
        "installation_id": "inst-a",
        "workspace_id": "ws-42",
        "owner_user_id": 42,
        "status": "online",
        "capabilities": ["telemetry", "live_read"],
        "last_heartbeat_utc": (NOW - timedelta(seconds=10)).isoformat(),
        "revoked_at_utc": "",
    }
    allowed = _resolve(
        context,
        personal_connector_probe=lambda *_args: connector,
    )
    assert allowed.allowed is True
    assert allowed.source == "personal_connector"
    assert allowed.scope_id.startswith("workspace:")

    stale = dict(
        connector,
        last_heartbeat_utc=(NOW - timedelta(seconds=46)).isoformat(),
    )
    denied = _resolve(
        context,
        personal_connector_probe=lambda *_args: stale,
    )
    assert denied.allowed is False


def test_private_scope_never_accepts_owner_or_another_users_event() -> None:
    context_a = _context(42, "user-a")
    context_b = _context(43, "user-b")
    row_a = {
        "workspace_id": "ws-42", "user_uuid": "user-a",
        "provider": "topstep", "account_id": "acct-a",
        "live_eligible": True, "API_access_enabled": True,
        "sharing_scope": "private", "runtime_state": "LIVE",
        "connector": object(),
    }
    row_b = {
        **row_a,
        "workspace_id": "ws-43", "user_uuid": "user-b", "account_id": "acct-b",
    }
    access_a = _resolve(context_a, owned_provider_probe=lambda *_args: row_a)
    access_b = _resolve(context_b, owned_provider_probe=lambda *_args: row_b)
    event_a = {
        "type": "market_event",
        "market_data_scope": {
            "sharing_scope": "private",
            "workspace_id": "ws-42",
            "user_uuid": "user-a",
            "provider": "topstep",
            "account_id": "acct-a",
        },
    }
    assert market_data_access.decision_allows_message(access_a, event_a) is True
    assert market_data_access.decision_allows_message(access_b, event_a) is False
    assert market_data_access.decision_allows_message(access_a, {"type": "market_event"}) is False


def test_ws_denies_subscribe_without_market_data_decision() -> None:
    denied = market_data_access.MarketDataAccessDecision(
        allowed=False, reason="market_data_entitlement_required",
    )
    client = market_data_ws_http.WsClient(
        request_handler=None,
        context=_context(),
        access_resolver=lambda *_args, **_kwargs: denied,
    )
    market_data_ws_http._on_client_message(client, {
        "type": "subscribe", "exact_contract": "MNQ 09-26", "timeframe": "5m",
    })
    assert client.subscriptions == set()
    assert client.upstream_refs == {}
    assert client.outbound[-1]["type"] == "subscribe_nack"
    assert client.outbound[-1]["code"] == "market_data_entitlement_required"


def test_ws_broadcast_filters_same_contract_by_private_access_scope() -> None:
    decision_a = market_data_access.MarketDataAccessDecision(
        allowed=True, reason="verified_owned_provider", source="owned_provider",
        sharing_scope="private",
        scope_id=market_data_access.private_scope_id("ws-a", "user-a", "topstep", "acct-a"),
    )
    decision_b = market_data_access.MarketDataAccessDecision(
        allowed=True, reason="verified_owned_provider", source="owned_provider",
        sharing_scope="private",
        scope_id=market_data_access.private_scope_id("ws-b", "user-b", "topstep", "acct-b"),
    )
    client_a = market_data_ws_http.WsClient(None, context={"user_id": 1})
    client_b = market_data_ws_http.WsClient(None, context={"user_id": 2})
    key = "MNQ 09-26|5m"
    for client, decision in ((client_a, decision_a), (client_b, decision_b)):
        client.subscriptions.add(key)
        client.access_decisions[key] = decision
    event = {
        "type": "market_event",
        "market_data_scope": {"scope_id": decision_a.scope_id},
        "bar_updates": [{
            "action": "close",
            "bar": {"exact_contract": "MNQ 09-26", "timeframe": "5m", "c": 20000},
        }],
    }
    with market_data_ws_http._LOCK:
        market_data_ws_http._CLIENTS.update({client_a, client_b})
    try:
        market_data_ws_http.broadcast(event)
        assert len(client_a.outbound) == 1
        assert len(client_b.outbound) == 0
    finally:
        with market_data_ws_http._LOCK:
            market_data_ws_http._CLIENTS.discard(client_a)
            market_data_ws_http._CLIENTS.discard(client_b)


def test_ws_periodic_revalidation_revokes_and_purges_queued_live_data(monkeypatch) -> None:
    allowed = market_data_access.MarketDataAccessDecision(
        allowed=True, reason="authorized_shared_trial", source="shared_trial",
        sharing_scope="shared", scope_id=market_data_access.OWNER_SHARED_SCOPE,
    )
    denied = market_data_access.MarketDataAccessDecision(
        allowed=False, reason="market_data_entitlement_required",
    )
    current = {"decision": denied}
    client = market_data_ws_http.WsClient(
        None,
        context=_context(),
        access_resolver=lambda *_args, **_kwargs: current["decision"],
    )
    key = "MNQ 09-26|5m"
    client.subscriptions.add(key)
    client.access_decisions[key] = allowed
    client.upstream_refs[key] = {"provider": "test"}
    client.outbound.append({"type": "market_event", "bar_updates": []})
    released = []

    def fake_release(target, target_key):
        released.append(target_key)
        target.upstream_refs.pop(target_key, None)

    monkeypatch.setattr(market_data_ws_http, "_release_client_upstream", fake_release)
    market_data_ws_http._revalidate_client_access(client, force=True)

    assert key not in client.subscriptions
    assert key not in client.access_decisions
    assert released == [key]
    assert [row["type"] for row in client.outbound] == ["access_revoked"]


def test_ws_metrics_never_expose_raw_user_or_device_ids() -> None:
    client = market_data_ws_http.WsClient(
        None,
        context={"user_id": 77, "user_uuid": "secret-user", "device_id": "secret-device"},
    )
    with market_data_ws_http._LOCK:
        market_data_ws_http._CLIENTS.add(client)
    try:
        payload = market_data_ws_http.metrics()
        serialized = str(payload)
        assert "secret-user" not in serialized
        assert "secret-device" not in serialized
        assert payload["unique_subjects"] >= 1
        assert payload["unique_devices"] >= 1
    finally:
        with market_data_ws_http._LOCK:
            market_data_ws_http._CLIENTS.discard(client)


def test_http_personal_connector_never_falls_through_to_owner_topstep(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    remote = {
        "instrument": "MNQ 09-26",
        "bars": [{"t": (now - timedelta(seconds=10)).isoformat(), "o": 100, "h": 102, "l": 99, "c": 101, "v": 10}],
        "total": 1, "live": True, "status": "live",
        "freshness": {"fresh": True, "age_sec": 10},
        "source": {"kind": "connector_remote", "provider": "ninjatrader", "source_sequence": 7},
    }
    decision = market_data_access.MarketDataAccessDecision(
        allowed=True, reason="online_personal_connector", source="personal_connector",
        sharing_scope="workspace", scope_id=market_data_access.workspace_scope_id("ws-42", "inst-a"),
        user_id="user-a", workspace_id="ws-42", provider="ninjatrader", account_id="inst-a",
    )
    monkeypatch.setattr(
        server_mod.market_data_ingestion, "workspace_series",
        lambda *args, **kwargs: dict(remote),
    )
    monkeypatch.setattr(
        server_mod.market_data_failover, "fetch_external_series",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("global provider fallback leaked")),
    )
    with server_mod._MARKET_BARS_PAYLOAD_CACHE_LOCK:
        server_mod._MARKET_BARS_PAYLOAD_CACHE.clear()
    out = server_mod._market_bars_payload(
        "MNQ 09-26", "5m", 10, register=False, alerts_index={},
        workspace_id="ws-42", access_decision=decision,
    )
    assert out["source"]["provider"] == "ninjatrader"
    assert out["access"]["source"] == "personal_connector"
    assert out["access"]["sharing_scope"] == "workspace"


def test_http_private_provider_uses_only_private_backfill_and_redacts_cache_identity(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)

    class PrivateConnector:
        def backfill(self, exact_contract, timeframe, limit):
            assert exact_contract == "MNQ 09-26"
            return [{
                "t": (now - timedelta(seconds=10)).isoformat(),
                "o": 200, "h": 203, "l": 199, "c": 202, "v": 11,
            }]

    decision = market_data_access.MarketDataAccessDecision(
        allowed=True, reason="verified_owned_provider", source="owned_provider",
        sharing_scope="private",
        scope_id=market_data_access.private_scope_id("ws-42", "secret-user", "topstep", "secret-account"),
        user_id="secret-user", workspace_id="ws-42", provider="topstep",
        account_id="secret-account", connector=PrivateConnector(),
    )
    monkeypatch.setattr(
        server_mod.market_data_failover, "fetch_external_series",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("owner/shared provider leaked")),
    )
    monkeypatch.setattr(
        server_mod.market_data_ingestion, "workspace_series",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("another workspace source leaked")),
    )
    with server_mod._MARKET_BARS_PAYLOAD_CACHE_LOCK:
        server_mod._MARKET_BARS_PAYLOAD_CACHE.clear()
    out = server_mod._market_bars_payload(
        "MNQ 09-26", "5m", 10, register=False, alerts_index={},
        workspace_id="ws-42", access_decision=decision,
    )
    assert out["bars"][-1]["c"] == 202
    assert out["source"]["kind"] == "owned_provider"
    serialized = str(out)
    assert "secret-user" not in serialized
    assert "secret-account" not in serialized
    assert out["diagnostics"]["cache_key"].startswith("md:private:")
