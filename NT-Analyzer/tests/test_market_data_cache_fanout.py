"""Cache-key collision and subscription fan-in tests."""
from __future__ import annotations

import threading
import time

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


def test_websocket_upgrade_uses_http_11_status_line() -> None:
    """Strict RFC6455 clients must not receive BaseHTTPRequestHandler HTTP/1.0."""
    observed = []

    class Reader:
        def read1(self, _size):
            return b""

    class Writer:
        def write(self, raw):
            assert raw
            return len(raw)

        def flush(self):
            return None

    class Handler:
        path = "/ws/market-data"
        headers = {
            "Upgrade": "websocket",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        }
        protocol_version = "HTTP/1.0"
        rfile = Reader()
        wfile = Writer()
        _remote_context = {"user_id": 1}

        def send_response(self, code, message):
            observed.append((self.protocol_version, code, message))

        def send_header(self, _name, _value):
            return None

        def end_headers(self):
            return None

    handler = Handler()
    assert market_data_ws_http.handle_websocket_upgrade(handler) is True
    assert observed == [("HTTP/1.1", 101, "Switching Protocols")]
    assert handler.protocol_version == "HTTP/1.0"


def test_browser_ws_tcp_reset_is_a_normal_disconnect() -> None:
    """Browser process exit must release the client without a server 500."""
    class Reader:
        def read1(self, _size):
            raise ConnectionResetError(10054, "connection reset by peer")

    class Writer:
        def write(self, raw):
            assert raw
            return len(raw)

        def flush(self):
            return None

    class Handler:
        path = "/ws/market-data"
        headers = {
            "Upgrade": "websocket",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        }
        protocol_version = "HTTP/1.0"
        rfile = Reader()
        wfile = Writer()
        _remote_context = {"user_id": 1}

        def send_response(self, _code, _message):
            return None

        def send_header(self, _name, _value):
            return None

        def end_headers(self):
            return None

    before = market_data_ws_http.metrics()["clients"]
    assert market_data_ws_http.handle_websocket_upgrade(Handler()) is True
    assert market_data_ws_http.metrics()["clients"] == before


def test_browser_ws_reader_returns_available_frame_without_waiting_for_buffer_fill() -> None:
    class Reader:
        def read1(self, size):
            assert size == 4096
            return b"small-websocket-frame"

        def read(self, _size):  # pragma: no cover - regression guard
            raise AssertionError("BufferedReader.read() can wait for the full requested size")

    handler = type("Handler", (), {"rfile": Reader()})()
    assert market_data_ws_http._read_client_chunk(handler) == b"small-websocket-frame"


def test_browser_ws_fanout_filters_updates_to_exact_subscribed_timeframe() -> None:
    message = {
        "type": "market_event",
        "event": {"exact_contract": "MNQ 09-26", "price": 29700.25},
        "bar_updates": [
            {
                "action": "close",
                "bar": {
                    "exact_contract": "MNQ 09-26",
                    "timeframe": "1s",
                    "c": 29700.0,
                },
            },
            {
                "action": "update",
                "bar": {
                    "exact_contract": "MNQ 09-26",
                    "timeframe": "5m",
                    "c": 29700.25,
                },
            },
            {
                "action": "update",
                "bar": {
                    "exact_contract": "MES 09-26",
                    "timeframe": "5m",
                    "c": 7765.25,
                },
            },
        ],
    }
    filtered = market_data_ws_http._message_for_subscriptions(
        message, {"MNQ 09-26|5m"},
    )
    assert filtered is not message
    assert [row["bar"]["timeframe"] for row in filtered["bar_updates"]] == ["5m"]
    assert [row["bar"]["exact_contract"] for row in filtered["bar_updates"]] == ["MNQ 09-26"]
    assert market_data_ws_http._message_for_subscriptions(
        message, {"MES 09-26|1m"},
    ) is None


def test_browser_ws_broadcast_does_not_block_provider_reader_on_slow_client() -> None:
    """A slow browser socket must never stall the upstream SignalR reader."""
    write_started = threading.Event()
    release_write = threading.Event()
    write_finished = threading.Event()
    writer_thread_ids = []

    class BlockingWriter:
        def write(self, raw):
            assert raw
            writer_thread_ids.append(threading.get_ident())
            write_started.set()
            assert release_write.wait(timeout=2.0)
            return len(raw)

        def flush(self):
            write_finished.set()

    class Connection:
        def shutdown(self, _how):
            release_write.set()

    handler = type("Handler", (), {
        "wfile": BlockingWriter(),
        "connection": Connection(),
    })()
    client = market_data_ws_http.WsClient(handler)
    client.subscriptions.add("MNQ 09-26|5m")
    market_data_ws_http.register_client(client)
    caller_thread_id = threading.get_ident()
    dropped_before = market_data_ws_http.metrics()["dropped"]
    filtered_before = market_data_ws_http.metrics()["non_bar_events_filtered"]
    try:
        started = time.monotonic()
        market_data_ws_http.broadcast({
            "type": "market_event",
            "event": {"exact_contract": "MNQ 09-26", "price": 29700.25},
            "bar_updates": [{
                "action": "update",
                "bar": {
                    "exact_contract": "MNQ 09-26",
                    "timeframe": "5m",
                    "c": 29700.25,
                },
            }],
        })
        elapsed = time.monotonic() - started
        assert elapsed < 0.25
        assert write_started.wait(timeout=1.0)
        assert writer_thread_ids == [client._writer_thread.ident]
        assert writer_thread_ids[0] != caller_thread_id
        # The desktop does not consume GatewayQuote bid/ask-only events. They
        # must be filtered before the slow socket, not evict reliable
        # close/correction/control messages from the bounded queue.
        for price in range(200):
            market_data_ws_http.broadcast({
                "type": "market_event",
                "event": {
                    "exact_contract": "MNQ 09-26",
                    "bestBid": 29700.0 + price / 100,
                },
            })
        with client._queue_lock:
            assert len(client.outbound) == 0
            assert len(client.coalesce_slot) == 0
        assert market_data_ws_http.metrics()["dropped"] == dropped_before
        assert market_data_ws_http.metrics()["non_bar_events_filtered"] == filtered_before + 200
    finally:
        release_write.set()
        assert write_finished.wait(timeout=1.0)
        market_data_ws_http.unregister_client(client)


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
