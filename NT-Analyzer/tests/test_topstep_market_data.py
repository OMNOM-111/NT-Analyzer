from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from datetime import timedelta
import json
import threading
import time
import urllib.error

from app import integrations, market_data_failover as failover
from app import market_data_live_adapters as live_adapters


def _local_topstep_env(monkeypatch) -> None:
    failover.TopstepXProvider._adapter_instance = None
    failover.TopstepXProvider._credential_fingerprint = ""
    live_adapters.topstepx_session_manager().reset_for_tests()
    monkeypatch.setattr(live_adapters.secure_store, "available", lambda: False)
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TOPSTEPX_MARKET_DATA", "1")
    monkeypatch.setenv("NTA_TOPSTEPX_USERNAME", "owner_user")
    monkeypatch.setenv("NTA_TOPSTEPX_API_KEY", "real-projectx-key")
    monkeypatch.setenv("NTA_TOPSTEPX_DATA_MODE", "sim")
    monkeypatch.delenv("NTA_ENABLE_TOPSTEPX_LIVE", raising=False)
    monkeypatch.delenv("NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED", raising=False)
    monkeypatch.delenv("NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED", raising=False)


def test_topstep_provider_auth_search_and_bars_contract(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    calls = []
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    def post(url, payload, **_kwargs):
        calls.append((url, None if payload is None else dict(payload)))
        if url.endswith("/Auth/loginKey"):
            assert payload == {"userName": "owner_user", "apiKey": "real-projectx-key"}
            return {"success": True, "token": "session-token"}
        if url.endswith("/Contract/search"):
            assert payload == {"searchText": "MNQ", "live": False}
            return {"success": True, "contracts": [
                {"id": "CON.F.US.ENQ.U26", "name": "NQU6", "symbolId": "F.US.ENQ", "activeContract": True},
                {"id": "CON.F.US.MNQ.U26", "name": "MNQU6", "symbolId": "F.US.MNQ", "activeContract": True},
            ]}
        if url.endswith("/History/retrieveBars"):
            assert payload["contractId"] == "CON.F.US.MNQ.U26"
            assert payload["live"] is False
            assert payload["includePartialBar"] is True
            return {"success": True, "bars": [{
                "t": now.isoformat().replace("+00:00", "Z"),
                "o": 21000.0, "h": 21002.0, "l": 20999.0, "c": 21001.0, "v": 12,
            }]}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    monkeypatch.setattr(live_adapters.TopstepXProjectXAdapter, "connect", lambda self: self.health())
    provider = failover.TopstepXProvider()
    payload = provider.fetch("MNQ", "1m", 20)

    assert provider.configured() is True
    # A fresh historical 1m bar is not proof that the market socket itself has
    # begun streaming.  The initial response is honest CONNECTING until a
    # GatewayQuote/heartbeat arrives.
    assert payload["live"] is False
    assert payload["status"] == "external_connecting"
    assert payload["freshness"]["bar_fresh"] is True
    assert payload["freshness"]["market_feed_fresh"] is False
    assert payload["instrument"] == "MNQ 09-26"
    assert payload["source"]["provider"] == "topstepx"
    assert payload["source"]["read_only"] is True
    assert payload["source"]["trade_routing"] is False
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["loginKey", "search", "retrieveBars"]


def test_topstep_session_reuses_login_and_validates_before_reauth(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    calls = []

    def post(url, payload, **_kwargs):
        calls.append((url, None if payload is None else dict(payload)))
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": "first-session"}
        if url.endswith("/Auth/validate"):
            return {"success": True, "newToken": "rotated-session"}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    adapter = live_adapters.TopstepXProjectXAdapter()
    assert adapter._authenticate() is True
    assert adapter._authenticate() is True
    manager = live_adapters.topstepx_session_manager()
    assert [url for url, _ in calls if url.endswith("/Auth/loginKey")] == ["https://api.topstepx.com/api/Auth/loginKey"]

    # Simulate the documented pre-expiry rotation window.  The manager must
    # validate and use newToken, never call loginKey again.
    manager._expires_at = 0.0
    assert adapter._authenticate() is True
    assert len([url for url, _ in calls if url.endswith("/Auth/loginKey")]) == 1
    assert len([url for url, _ in calls if url.endswith("/Auth/validate")]) == 1
    assert [payload for url, payload in calls if url.endswith("/Auth/validate")] == [None]
    audit = manager.audit()
    assert audit["login_key_calls"] == 1
    assert audit["validate_successes"] == 1
    assert audit["jwt_issued"] == 2


def test_topstep_validate_request_has_no_body(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b'{"success":true,"newToken":"rotated"}'

    def urlopen(request, **_kwargs):
        captured["method"] = request.get_method()
        captured["data"] = request.data
        captured["accept"] = request.get_header("Accept")
        captured["content_type"] = request.get_header("Content-type")
        return Response()

    monkeypatch.setattr(live_adapters.urllib.request, "urlopen", urlopen)
    result = live_adapters._post_json(
        "https://api.topstepx.com/api/Auth/validate",
        None,
        headers={"Accept": "text/plain", "Content-Type": "application/json"},
    )

    assert result["newToken"] == "rotated"
    assert captured == {
        "method": "POST",
        "data": None,
        "accept": "text/plain",
        "content_type": "application/json",
    }


def test_topstep_session_restores_dpapi_token_after_runtime_restart(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    vault = {}
    calls = []

    monkeypatch.setattr(live_adapters.secure_store, "available", lambda: True)
    monkeypatch.setattr(live_adapters.runtime_env, "is_development", lambda: True)
    monkeypatch.setattr(live_adapters.secure_store, "get_secret", lambda key: vault.get(key))
    monkeypatch.setattr(live_adapters.secure_store, "set_secret", lambda key, value: vault.__setitem__(key, value))
    monkeypatch.setattr(live_adapters.secure_store, "delete_secret", lambda key: vault.pop(key, None) is not None)

    def post(url, _payload, **_kwargs):
        calls.append(url)
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": "first-runtime-token"}
        if url.endswith("/Auth/validate"):
            return {"success": True, "newToken": "validated-runtime-token"}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    manager = live_adapters.topstepx_session_manager()
    first = live_adapters.TopstepXProjectXAdapter()
    assert first._authenticate() is True
    assert len(calls) == 1

    # Simulate a Development backend restart.  The JWT is DPAPI-protected,
    # never stored in local_secrets or Git, and the next runtime reuses it.
    manager.reset_for_tests()
    second = live_adapters.TopstepXProjectXAdapter()
    assert second._authenticate() is True
    assert len([url for url in calls if url.endswith("/Auth/loginKey")]) == 1
    assert len([url for url in calls if url.endswith("/Auth/validate")]) == 1
    record = json.loads(vault[manager._SESSION_STORE_KEY])
    assert record["token"] == "validated-runtime-token"
    assert float(record["expires_at"]) > time.time()
    assert manager.audit()["persisted_token_restores"] == 1
    assert manager.audit()["token_source"] == "VALIDATE"


def test_topstep_rejected_restored_token_falls_back_to_one_loginkey(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    manager = live_adapters.topstepx_session_manager()
    cfg = live_adapters.TopstepXProjectXAdapter.settings()
    fingerprint = manager._fingerprint_for(cfg)
    vault = {
        manager._SESSION_STORE_KEY: json.dumps({
            "v": 1,
            "fingerprint": fingerprint,
            "token": "persisted-session-token",
            "expires_at": time.time() + 3600,
        }),
    }
    calls = []

    monkeypatch.setattr(live_adapters.secure_store, "available", lambda: True)
    monkeypatch.setattr(live_adapters.runtime_env, "is_development", lambda: True)
    monkeypatch.setattr(live_adapters.secure_store, "get_secret", lambda key: vault.get(key))
    monkeypatch.setattr(live_adapters.secure_store, "set_secret", lambda key, value: vault.__setitem__(key, value))
    monkeypatch.setattr(live_adapters.secure_store, "delete_secret", lambda key: vault.pop(key, None) is not None)

    def post(url, payload, **_kwargs):
        calls.append((url, payload))
        if url.endswith("/Auth/validate"):
            assert payload is None
            return {"success": False, "errorCode": 2, "errorMessage": "not logged"}
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": "replacement-session-token"}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    for _ in range(2):
        assert manager.authenticate(cfg) == "replacement-session-token"

    assert len([url for url, _ in calls if url.endswith("/Auth/validate")]) == 1
    assert len([url for url, _ in calls if url.endswith("/Auth/loginKey")]) == 1
    assert manager._SESSION_STORE_KEY in vault
    assert json.loads(vault[manager._SESSION_STORE_KEY])["token"] == "replacement-session-token"
    audit = manager.audit()
    assert audit["last_validate_outcome"] == "API_SESSION_NOT_FOUND"
    assert audit["last_validate_error_code"] == 2
    assert audit["validate_api_rejections"] == 1
    assert audit["login_key_calls"] == 1
    assert audit["login_key_after_rejected_token"] == 1
    assert audit["persisted_token_invalidations"] == 1
    assert audit["automatic_reauth_is_blocked"] is False
    assert audit["token_source"] == "LOGIN_KEY"


def test_topstep_expired_dpapi_token_is_validated_before_any_loginkey(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    manager = live_adapters.topstepx_session_manager()
    cfg = live_adapters.TopstepXProjectXAdapter.settings()
    fingerprint = manager._fingerprint_for(cfg)
    vault = {
        manager._SESSION_STORE_KEY: json.dumps({
            "v": 1,
            "fingerprint": fingerprint,
            "token": "expired-local-token",
            "expires_at": time.time() - 60,
        }),
    }
    calls = []

    monkeypatch.setattr(live_adapters.secure_store, "available", lambda: True)
    monkeypatch.setattr(live_adapters.runtime_env, "is_development", lambda: True)
    monkeypatch.setattr(live_adapters.secure_store, "get_secret", lambda key: vault.get(key))
    monkeypatch.setattr(live_adapters.secure_store, "set_secret", lambda key, value: vault.__setitem__(key, value))

    def post(url, payload, **_kwargs):
        calls.append((url, payload))
        if url.endswith("/Auth/validate"):
            return {"success": True, "newToken": "rotated-expired-token"}
        if url.endswith("/Auth/loginKey"):
            raise AssertionError("an expired persisted token must be validated first")
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    assert manager.authenticate(cfg) == "rotated-expired-token"
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["validate"]
    assert manager.audit()["login_key_calls"] == 0


def test_topstep_failed_loginkey_is_cooled_down_for_a_large_layout(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    calls = []

    def post(url, _payload, **_kwargs):
        calls.append(url)
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(live_adapters, "_post_json", post)
    manager = live_adapters.topstepx_session_manager()
    cfg = live_adapters.TopstepXProjectXAdapter.settings()
    try:
        manager.authenticate(cfg)
    except urllib.error.URLError:
        pass
    else:  # pragma: no cover - regression guard
        raise AssertionError("first loginKey failure should reach the caller")
    try:
        manager.authenticate(cfg)
    except RuntimeError as exc:
        assert "cooldown" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("second loginKey attempt should be suppressed")

    assert len(calls) == 1
    assert manager.audit()["login_key_cooldown_suppressed"] == 1


def test_topstep_cached_auth_does_not_downgrade_an_active_market_socket(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)

    def post(url, _payload, **_kwargs):
        assert url.endswith("/Auth/loginKey")
        return {"success": True, "token": "shared-session"}

    monkeypatch.setattr(live_adapters, "_post_json", post)
    adapter = live_adapters.TopstepXProjectXAdapter()
    assert adapter._authenticate() is True
    adapter._runtime_state = "LIVE"
    adapter._ws_client = object()

    # A history or subscription caller reuses the cached JWT.  It must not
    # momentarily downgrade an independently healthy SignalR socket to
    # CONNECTING and make the chart price line gray.
    assert adapter._authenticate() is True
    assert adapter.health()["runtime_state"] == "LIVE"


def test_topstep_history_401_revalidates_before_any_new_loginkey(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    calls = []
    history_attempts = 0

    def post(url, payload, **_kwargs):
        nonlocal history_attempts
        calls.append((url, None if payload is None else dict(payload)))
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": "initial-session"}
        if url.endswith("/Auth/validate"):
            return {"success": True, "newToken": "validated-session"}
        if url.endswith("/History/retrieveBars"):
            history_attempts += 1
            if history_attempts == 1:
                raise urllib.error.HTTPError(url, 401, "unauthorized", None, None)
            return {"success": True, "bars": []}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    adapter = live_adapters.TopstepXProjectXAdapter()
    assert adapter._authenticate() is True
    assert adapter._history_request({"contractId": "CON.F.US.MNQ.U26"}) == {
        "success": True, "bars": [],
    }

    assert history_attempts == 2
    assert len([url for url, _ in calls if url.endswith("/Auth/loginKey")]) == 1
    assert len([url for url, _ in calls if url.endswith("/Auth/validate")]) == 1


def test_topstep_concurrent_unauthorized_recovery_reuses_one_validate(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    calls = []

    def post(url, _payload, **_kwargs):
        calls.append(url)
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": "initial-session"}
        if url.endswith("/Auth/validate"):
            return {"success": True, "newToken": "rotated-session"}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    manager = live_adapters.topstepx_session_manager()
    cfg = live_adapters.TopstepXProjectXAdapter.settings()
    assert manager.authenticate(cfg) == "initial-session"
    failed_token, failed_epoch = manager.token_snapshot()

    assert manager.recover_after_unauthorized(
        cfg, failed_token=failed_token, failed_epoch=failed_epoch,
    ) == "rotated-session"
    # This represents a second chart receiving 401 for the old in-flight
    # request after the first chart has already recovered the shared JWT.
    assert manager.recover_after_unauthorized(
        cfg, failed_token=failed_token, failed_epoch=failed_epoch,
    ) == "rotated-session"

    assert len([url for url in calls if url.endswith("/Auth/loginKey")]) == 1
    assert len([url for url in calls if url.endswith("/Auth/validate")]) == 1
    assert manager.audit()["authorization_recovery_cache_hits"] == 1


def test_topstep_signalr_session_close_recovers_once_and_cools_relogin(monkeypatch) -> None:
    """ProjectX type=7 must validate/login once, never reconnect on a dead JWT."""
    _local_topstep_env(monkeypatch)
    calls = []
    login_tokens = iter(("initial-session", "replacement-session"))

    def post(url, _payload, **_kwargs):
        calls.append(url)
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": next(login_tokens)}
        if url.endswith("/Auth/validate"):
            return {"success": False, "errorCode": 2, "errorMessage": "not logged"}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    adapter = live_adapters.TopstepXProjectXAdapter()
    manager = live_adapters.topstepx_session_manager()
    assert adapter._authenticate() is True
    failed_token, failed_epoch = manager.token_snapshot()

    # The unit test compresses time; the real incident occurred long after
    # the initial-login cooldown had elapsed.
    manager._login_key_cooldown_until = 0.0
    assert adapter._recover_realtime_session(failed_token, failed_epoch) is True
    assert manager.token_snapshot()[0] == "replacement-session"
    assert len([url for url in calls if url.endswith("/Auth/validate")]) == 1
    assert len([url for url in calls if url.endswith("/Auth/loginKey")]) == 2

    # If ProjectX rejects the replacement immediately, validation is allowed
    # but another loginKey is suppressed for the shared 60-second cooldown.
    replacement_token, replacement_epoch = manager.token_snapshot()
    assert adapter._recover_realtime_session(
        replacement_token, replacement_epoch,
    ) is False
    assert len([url for url in calls if url.endswith("/Auth/loginKey")]) == 2
    audit = manager.audit()
    assert audit["signalr_auth_recovery_attempts"] == 2
    assert audit["signalr_auth_recovery_successes"] == 1
    assert audit["signalr_auth_recovery_failures"] == 1
    assert audit["login_key_cooldown_suppressed"] == 1


def test_topstep_transient_validate_failure_never_falls_through_to_loginkey(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    calls = []

    def post(url, _payload, **_kwargs):
        calls.append(url)
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": "initial-session"}
        if url.endswith("/Auth/validate"):
            raise urllib.error.URLError("temporary network failure")
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    manager = live_adapters.topstepx_session_manager()
    cfg = live_adapters.TopstepXProjectXAdapter.settings()
    assert manager.authenticate(cfg) == "initial-session"
    manager._expires_at = 0.0

    try:
        manager.authenticate(cfg)
    except urllib.error.URLError:
        pass
    else:  # pragma: no cover - regression guard
        raise AssertionError("transient validation failure must be returned")

    assert len([url for url in calls if url.endswith("/Auth/loginKey")]) == 1
    assert len([url for url in calls if url.endswith("/Auth/validate")]) == 1


def test_topstep_logical_chart_refs_share_one_session_and_wire_contract(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    calls = []

    def post(url, payload, **_kwargs):
        calls.append((url, dict(payload)))
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": "shared-session"}
        if url.endswith("/Contract/search"):
            return {"success": True, "contracts": [{
                "id": "CON.F.US.MNQ.U26", "name": "MNQU6", "symbolId": "F.US.MNQ", "activeContract": True,
            }]}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    adapter = live_adapters.TopstepXProjectXAdapter()
    adapter.subscribe("MNQ 09-26", "quotes", timeframe="5m", consumer_id="browser-a")
    adapter.subscribe("MNQ 09-26", "quotes", timeframe="5m", consumer_id="browser-b")
    adapter.subscribe("MNQ 09-26", "quotes", timeframe="5m", consumer_id="browser-a")

    health = adapter.health()
    assert health["session_audit"]["login_key_calls"] == 1
    assert health["logical_subscription_refcount"] == 2
    assert len([url for url, _ in calls if url.endswith("/Contract/search")]) == 1
    assert adapter.release_subscription("MNQ 09-26", "quotes", timeframe="5m", consumer_id="browser-a") is True
    assert adapter.health()["logical_subscription_refcount"] == 1


def test_topstep_reconnect_gap_fill_is_nonblocking_singleflight(monkeypatch) -> None:
    """A large REST gap-fill must never starve the shared Market Hub reader."""
    _local_topstep_env(monkeypatch)
    adapter = live_adapters.TopstepXProjectXAdapter()
    entered = threading.Event()
    release = threading.Event()

    def slow_gap_fill() -> None:
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(adapter, "_gap_fill_subscriptions", slow_gap_fill)
    started_at = time.monotonic()
    assert adapter._start_gap_fill_subscriptions() is True
    assert time.monotonic() - started_at < 0.25
    assert entered.wait(1)
    assert adapter._start_gap_fill_subscriptions() is False
    release.set()
    deadline = time.monotonic() + 2
    while adapter._gap_fill_lock.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert adapter._gap_fill_lock.locked() is False


def test_topstep_reconnect_resubscribe_multiplexes_unique_contracts(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    adapter = live_adapters.TopstepXProjectXAdapter()
    ws = object()
    adapter._ws_client = ws
    adapter._subs = {
        "mnq-quotes": {"raw_symbol": "MNQU6"},
        "mnq-trades": {"raw_symbol": "MNQU6"},
        "mes-quotes": {"raw_symbol": "MESU6"},
    }
    subscribed = []

    async def record_subscribe(actual_ws, raw_symbol) -> None:
        assert actual_ws is ws
        subscribed.append(raw_symbol)

    monkeypatch.setattr(adapter, "_subscribe_ws", record_subscribe)
    asyncio.run(adapter._resubscribe_ws(ws))
    assert subscribed == ["MNQU6", "MESU6"]


def test_topstep_market_freshness_does_not_depend_on_last_trade_change(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    adapter = live_adapters.TopstepXProjectXAdapter()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    adapter._runtime_state = "LIVE"
    adapter._ws_client = object()
    adapter._connected_at = now
    adapter._contract_symbol_map["CON.F.US.MNQ.U26"] = "MNQ 09-26"

    adapter._on_ws_message("GatewayQuote", ["CON.F.US.MNQ.U26", {
        "symbol": "MNQU6", "lastPrice": 21000.0, "bestBid": 20999.75,
        "bestAsk": 21000.25, "timestamp": now,
    }])
    # The price is deliberately the same on the next quote; fresh bid/ask and
    # receive time keep the chart LIVE without manufacturing a new trade.
    adapter._on_ws_message("GatewayQuote", ["CON.F.US.MNQ.U26", {
        "symbol": "MNQU6", "lastPrice": 21000.0, "bestBid": 20999.75,
        "bestAsk": 21000.25, "timestamp": now,
    }])
    feed = adapter.market_feed_freshness("MNQ 09-26")
    assert feed["fresh"] is True
    assert feed["quote_age_sec"] is not None and feed["quote_age_sec"] < 2
    assert feed["last_trade_age_sec"] is not None and feed["last_trade_age_sec"] < 2

    # A quiet last trade is also normal.  Fresh bid/ask-only GatewayQuote
    # traffic proves the exact market feed is alive and must not gray the
    # current price line merely because no new lastPrice was supplied.
    old_trade = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
    adapter._last_trade_receive_utc["MNQ 09-26"] = old_trade
    adapter._on_ws_message("GatewayQuote", ["CON.F.US.MNQ.U26", {
        "symbol": "MNQU6", "bestBid": 20999.75, "bestAsk": 21000.25,
        "timestamp": now,
    }])
    quiet_trade_feed = adapter.market_feed_freshness("MNQ 09-26")
    assert quiet_trade_feed["fresh"] is True
    assert quiet_trade_feed["quote_age_sec"] is not None and quiet_trade_feed["quote_age_sec"] < 2
    assert quiet_trade_feed["last_trade_age_sec"] is not None and quiet_trade_feed["last_trade_age_sec"] >= 170


def test_topstep_status_reports_exact_configuration(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    status = integrations.topstep_status()
    assert status["configured"] is True
    assert status["username_configured"] is True
    assert status["api_key_configured"] is True
    assert status["read_only"] is True
    assert status["trade_routing_enabled"] is False
    assert status["status"] == "ready_to_initialize"


def test_topstep_signalr_events_use_display_router_path(monkeypatch) -> None:
    """A read-only TopstepX tick must reach the same browser path as an NT tick."""
    _local_topstep_env(monkeypatch)
    from app import market_data_ipc

    received = []
    monkeypatch.setattr(market_data_ipc, "ingest_event", lambda event: received.append(dict(event)) or True)
    provider = failover.TopstepXProvider()
    adapter = provider._adapter()

    assert adapter.health()["mode"] == "authoritative"
    adapter._emit({"type": "trade", "provider": "topstep_live", "exact_contract": "MNQ 09-26", "price": 21000.0})
    assert received == [{"type": "trade", "provider": "topstepx", "exact_contract": "MNQ 09-26", "price": 21000.0}]


def test_topstep_history_range_chunks_maps_timeframes_and_reuses_cache(monkeypatch) -> None:
    _local_topstep_env(monkeypatch)
    calls = []
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(minutes=40_001)

    assert live_adapters.topstep_timeframe_spec("15s")[:2] == (1, 15)
    assert live_adapters.topstep_timeframe_spec("5m")[:2] == (2, 5)
    assert live_adapters.topstep_timeframe_spec("4h")[:2] == (3, 4)
    assert live_adapters.topstep_timeframe_spec("1D")[:2] == (4, 1)
    assert live_adapters.topstep_timeframe_spec("1w")[:2] == (5, 1)
    assert live_adapters.topstep_timeframe_spec("1M")[:2] == (6, 1)

    def post(url, payload, **_kwargs):
        calls.append((url, dict(payload)))
        if url.endswith("/Auth/loginKey"):
            return {"success": True, "token": "session-token"}
        if url.endswith("/Contract/search"):
            return {"success": True, "contracts": [{
                "id": "CON.F.US.MNQ.U26", "name": "MNQU6", "symbolId": "F.US.MNQ", "activeContract": True,
            }]}
        if url.endswith("/History/retrieveBars"):
            assert payload["limit"] <= 20_000
            stamp = payload["startTime"]
            return {"success": True, "bars": [{"t": stamp, "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 1}]}
        raise AssertionError(url)

    monkeypatch.setattr(live_adapters, "_post_json", post)
    adapter = live_adapters.TopstepXProjectXAdapter()
    first = adapter.history_range("MNQ", "1m", start_time=start, end_time=end, limit=20_000)
    history_calls = [payload for url, payload in calls if url.endswith("/History/retrieveBars")]
    assert len(history_calls) == 3
    assert first["cache_hit"] is False
    assert first["bars"] == sorted(first["bars"], key=lambda row: row["t"])

    before = len(history_calls)
    second = adapter.history_range("MNQ", "1m", start_time=start, end_time=end, limit=20_000)
    after = len([payload for url, payload in calls if url.endswith("/History/retrieveBars")])
    assert second["cache_hit"] is True
    assert after == before
