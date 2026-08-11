"""Cache-key collision and subscription fan-in tests."""
from __future__ import annotations

from app import data_platform, market_data_cache_keys, market_data_subscriptions, market_data_ws_http


def test_cache_keys_distinct_for_index_family() -> None:
    symbols = [
        ("RTY 09-26", "5m"),
        ("M2K 09-26", "5m"),
        ("MES 09-26", "5m"),
        ("MNQ 09-26", "5m"),
        ("MYM 09-26", "5m"),
        ("MGC 08-26", "5m"),
    ]
    keys = [
        market_data_cache_keys.market_cache_key(
            provider="ninjatrader",
            exchange="CME",
            exact_contract=sym,
            channel="trades",
            timeframe=tf,
        )
        for sym, tf in symbols
    ]
    assert len(keys) == len(set(keys))
    assert all("MNQ 09-26" in k or "MES 09-26" in k or "RTY" in k or "M2K" in k or "MYM" in k or "MGC" in k for k in keys)


def test_series_hash_differs_for_different_prices() -> None:
    mes = [{"t": "2026-07-16T12:00:00Z", "o": 7500, "h": 7510, "l": 7490, "c": 7505, "v": 1}]
    mnq = [{"t": "2026-07-16T12:00:00Z", "o": 21000, "h": 21010, "l": 20990, "c": 21005, "v": 1}]
    rty = [{"t": "2026-07-16T12:00:00Z", "o": 2200, "h": 2201, "l": 2199, "c": 2200.5, "v": 1}]
    m2k = [{"t": "2026-07-16T12:00:00Z", "o": 2200, "h": 2201, "l": 2199, "c": 2200.5, "v": 1}]
    assert market_data_cache_keys.series_hash(mes) != market_data_cache_keys.series_hash(mnq)
    # RTY/M2K may share shape/prices in synthetic fixture — hashes can match;
    # cache keys must still differ (tested above). Document expected closeness:
    assert market_data_cache_keys.series_hash(rty) == market_data_cache_keys.series_hash(m2k)


def test_cache_keys_isolate_workspaces_and_private_accounts() -> None:
    common = {
        "provider": "topstep_live",
        "exchange": "CME",
        "exact_contract": "MNQ 09-26",
        "channel": "trades",
        "timeframe": "1m",
    }
    ws_a = market_data_cache_keys.market_cache_key(
        **common, sharing_scope="workspace", workspace_id="ws-a",
    )
    ws_b = market_data_cache_keys.market_cache_key(
        **common, sharing_scope="workspace", workspace_id="ws-b",
    )
    private_a = market_data_cache_keys.market_cache_key(
        **common, sharing_scope="private", workspace_id="ws-a",
        user_id="user-1", account_id="account-1",
    )
    private_b = market_data_cache_keys.market_cache_key(
        **common, sharing_scope="private", workspace_id="ws-a",
        user_id="user-1", account_id="account-2",
    )
    assert len({ws_a, ws_b, private_a, private_b}) == 4


def test_subscription_refcount_fan_in() -> None:
    market_data_subscriptions.reset_subscription_registry_for_tests()
    reg = market_data_subscriptions.get_subscription_registry()
    a = reg.acquire("ninjatrader", "MNQ 09-26", "trades")
    b = reg.acquire("ninjatrader", "MNQ 09-26", "trades")
    assert a.subscription_id == b.subscription_id
    assert b.refcount == 2
    snap = reg.snapshot()
    assert snap["upstream_count"] == 1
    reg.release("ninjatrader", "MNQ 09-26", "trades")
    assert reg.snapshot()["upstream_count"] == 1
    reg.release("ninjatrader", "MNQ 09-26", "trades")
    assert reg.snapshot()["upstream_count"] == 0


def test_ws_accept_key_stable() -> None:
    # RFC6455 example
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    assert market_data_ws_http.accept_key(key) == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_browser_ws_topstep_subscription_is_refcounted_per_client(monkeypatch) -> None:
    """A browser chart lease must not create a separate ProjectX session/socket."""
    from app import market_data_failover

    class FakeTopstep:
        acquired = []
        released = []

        def configured(self):
            return True

        def acquire_chart_subscription(self, contract, timeframe, consumer):
            self.__class__.acquired.append((contract, timeframe, consumer))
            return True

        def release_chart_subscription(self, contract, timeframe, consumer):
            self.__class__.released.append((contract, timeframe, consumer))
            return True

    monkeypatch.setattr(market_data_failover, "TopstepXProvider", FakeTopstep)
    client = market_data_ws_http.WsClient(request_handler=None)
    market_data_ws_http._on_client_message(client, {
        "type": "subscribe", "exact_contract": "MNQ 09-26", "timeframe": "5m",
    })
    # Browser reconnect/resend for the same window joins the existing lease.
    market_data_ws_http._on_client_message(client, {
        "type": "subscribe", "exact_contract": "MNQ 09-26", "timeframe": "5m",
    })
    assert len(FakeTopstep.acquired) == 1
    market_data_ws_http._on_client_message(client, {
        "type": "unsubscribe", "exact_contract": "MNQ 09-26", "timeframe": "5m",
    })
    assert len(FakeTopstep.released) == 1


def test_data_platform_memory_default() -> None:
    data_platform.reset_platform_for_tests()
    plat = data_platform.get_platform()
    assert "memory" in plat.mode or plat.mode == "memory"
    plat.cache.set("md:test", {"ok": 1}, ttl_sec=10)
    assert plat.cache.get("md:test")["ok"] == 1
    assert plat.cache.stats()["hits"] >= 1
