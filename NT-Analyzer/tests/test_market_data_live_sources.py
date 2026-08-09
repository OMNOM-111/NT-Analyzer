"""Tests for parallel live-source adapters (no vendor network required)."""
from __future__ import annotations

from app import market_data_live_adapters as la
from app import market_data_live_supervisor as sup
from app import market_data_router


def test_databento_raw_symbol_mapping() -> None:
    assert la.databento_raw_symbol("MNQ 09-26") == "MNQU6"
    assert la.databento_raw_symbol("MES 12-26") == "MESZ6"
    assert la.databento_raw_symbol("MGC 08-26") == "MGCQ6"


def test_databento_without_key_is_entitlement_missing(monkeypatch) -> None:
    monkeypatch.delenv("NTA_DATABENTO_API_KEY", raising=False)
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    adapter = la.DatabentoLiveAdapter()
    health = adapter.connect()
    assert health["runtime_state"] == "ENTITLEMENT_MISSING"
    caps = adapter.capabilities()
    assert caps["REALTIME_PRODUCTION"] is False
    assert caps["capability"] in {"ENTITLEMENT_MISSING", "DEPENDENCY_MISSING", "OPTIONAL_ENTERPRISE_PROVIDER"}


def test_yahoo_not_in_live_adapters() -> None:
    names = {a.name for a in la.default_live_adapters()}
    assert "yahoo" not in names and "yahoo_chart" not in names
    assert "databento_live" in names
    assert "dxfeed_live" in names
    assert "cqg_live" in names
    assert "cme_websocket" in names


def test_fixture_trade_feeds_shadow_router(monkeypatch) -> None:
    market_data_router.reset_router_for_tests()
    adapter = la.DatabentoLiveAdapter()
    seen = []

    def sink(event):
        seen.append(event)
        market_data_router.get_router().ingest_shadow(adapter.name, event)

    adapter.set_sink(sink, mode="shadow")
    event = la.inject_fixture_trade(adapter, exact_contract="MNQ 09-26", price=21001.25)
    assert event["provider"] == "databento_live"
    assert seen and seen[0]["price"] == 21001.25
    assert market_data_router.get_router().can_auto_failover("databento_live") is False


def test_supervisor_status_production_blocked_without_key(monkeypatch) -> None:
    monkeypatch.delenv("NTA_DATABENTO_API_KEY", raising=False)
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    monkeypatch.delenv("NTA_DXFEED_TOKEN", raising=False)
    monkeypatch.delenv("NTA_CQG_USERNAME", raising=False)
    monkeypatch.delenv("NTA_CME_WS_TOKEN", raising=False)
    sup.stop()
    st = sup.start(force=True)
    assert st["production_blocked"] is True
    assert st["live_providers_connected"] == 0
    assert st["backup_live_providers_available"] == 0
    databento = next(a for a in st["adapters"] if a["name"] == "databento_live")
    assert databento["credentials_present"] is False
    sup.stop()


def test_dxfeed_cqg_cme_subscribe_not_fake_connected(monkeypatch) -> None:
    monkeypatch.delenv("NTA_DXFEED_TOKEN", raising=False)
    monkeypatch.delenv("NTA_CQG_USERNAME", raising=False)
    monkeypatch.delenv("NTA_CME_WS_TOKEN", raising=False)
    for cls in (la.DxFeedLiveAdapter, la.CqgLiveAdapter, la.CmeWebsocketReferenceAdapter):
        adapter = cls()
        assert adapter.implementation_state() in {"NOT_IMPLEMENTED", "ADAPTER_READY"}
        try:
            adapter.subscribe("MNQ 09-26")
            raise AssertionError("subscribe must raise until fully implemented")
        except NotImplementedError:
            pass


def test_mock_simulation_mode_connect_and_emit(monkeypatch) -> None:
    # Set mock credentials in environment
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "db-mock-test")
    monkeypatch.setenv("NTA_DXFEED_TOKEN", "dx-mock-test")
    monkeypatch.setenv("NTA_CQG_USERNAME", "cqg-mock-test")
    monkeypatch.setenv("NTA_CQG_PASSWORD", "cqg-mock-test")
    monkeypatch.setenv("NTA_CME_WS_TOKEN", "cme-mock-test")

    market_data_router.reset_router_for_tests()

    # Test DatabentoMockAdapter mock loop
    adapter = la.DatabentoMockAdapter()
    assert adapter.credentials_present() is False

    events_received = []
    adapter.set_sink(lambda e: events_received.append(e), mode="shadow")

    health = adapter.connect()
    assert health["runtime_state"] in {"CONNECTING", "SIMULATION"}

    sub_id = adapter.subscribe("MNQ 09-26")
    assert sub_id.startswith("databento_live_mock:")
    assert adapter.health()["runtime_state"] == "SIMULATION"

    # Wait for mock event
    import time
    for _ in range(20):
        if events_received:
            break
        time.sleep(0.1)

    adapter.disconnect()

    assert len(events_received) > 0
    event = events_received[0]
    assert event["provider"] == "databento_live"
    assert event["exact_contract"] == "MNQ 09-26"
    assert event["data_plane"] == "analytics"


def test_dxfeed_adapter_message_contract() -> None:
    adapter = la.DxFeedLiveAdapter()
    events = []
    adapter.set_sink(lambda e: events.append(e), mode="shadow")

    # Mock a dxFeed Trade message contract
    raw_trade = '[{"event": "Trade", "eventSymbol": "MNQ 09-26", "price": 21000.50, "size": 3, "sequence": 98765, "time": 1721100000000}]'
    adapter._parse_dxfeed_message(raw_trade)

    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "trade"
    assert ev["provider"] == "dxfeed_live"
    assert ev["exact_contract"] == "MNQ 09-26"
    assert ev["price"] == 21000.50
    assert ev["volume"] == 3
    assert ev["exchange_sequence"] == 98765
    assert ev["data_plane"] == "analytics"

    # Mock a dxFeed Quote message contract
    raw_quote = '[{"event": "Quote", "eventSymbol": "MES 12-26", "bidPrice": 5500.0, "askPrice": 5500.25, "bidSize": 10, "askSize": 15, "time": 1721100001000}]'
    adapter._parse_dxfeed_message(raw_quote)
    assert len(events) == 2
    ev2 = events[1]
    assert ev2["type"] == "quote"
    assert ev2["provider"] == "dxfeed_live"
    assert ev2["exact_contract"] == "MES 12-26"
    assert ev2["bid"] == 5500.0
    assert ev2["ask"] == 5500.25
    assert ev2["volume"] == 10


def test_cqg_adapter_message_contract() -> None:
    adapter = la.CqgLiveAdapter()
    events = []
    adapter.set_sink(lambda e: events.append(e), mode="shadow")

    # Mock a CQG WebAPI Quote/Trade message contract
    raw_msg = '{"CQGInstant": {"MarketData": {"Quotes": [{"Symbol": "MNQ 09-26", "Last": 21005.25, "LastVolume": 2, "Bid": 21005.0, "Ask": 21005.50, "Timestamp": 1721100002000}]}}}'
    adapter._parse_cqg_message(raw_msg)

    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "trade"
    assert ev["provider"] == "cqg_live"
    assert ev["exact_contract"] == "MNQ 09-26"
    assert ev["price"] == 21005.25
    assert ev["volume"] == 2
    assert ev["bid"] == 21005.0
    assert ev["ask"] == 21005.50


def test_cme_ws_adapter_message_contract() -> None:
    adapter = la.CmeWebsocketReferenceAdapter()
    events = []
    adapter.set_sink(lambda e: events.append(e), mode="shadow")

    # Mock a CME cloud WebSocket TOB message contract
    raw_msg = '{"symbol": "MNQ 09-26", "trade": {"price": 21010.75, "size": 5}, "timestamp": 1721100003000}'
    adapter._parse_cme_message(raw_msg)

    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "trade"
    assert ev["provider"] == "cme_websocket"
    assert ev["exact_contract"] == "MNQ 09-26"
    assert ev["price"] == 21010.75
    assert ev["volume"] == 5


def test_databento_live_adapter_client_mocked_connection(monkeypatch) -> None:
    # 1. Setup mock keys in environment so credentials_present() returns True for the real adapter
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    # 2. Define mock Databento record & client classes
    class MockRecord:
        def __init__(self) -> None:
            self.price = 21001250000000  # 21001.25 * 10^9
            self.size = 5
            self.symbol = "MNQU6"
            self.ts_event = 1721100000000000000  # epoch ns
            self.sequence = 9988
            self.index = 2

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            self.key = args[0] if args else kwargs.get("key", "")
            self.reconnect_policy = kwargs.get("reconnect_policy", "none")
            self.slow_reader_behavior = kwargs.get("slow_reader_behavior", "none")
            self.callbacks = []
            self.reconnect_callbacks = []
            self.subscriptions = []

        def add_callback(self, cb) -> None:
            self.callbacks.append(cb)

        def add_reconnect_callback(self, cb) -> None:
            self.reconnect_callbacks.append(cb)

        def start(self) -> None:
            # Synchronously trigger reconnect
            for cb in self.reconnect_callbacks:
                cb()

        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            self.subscriptions.append((dataset, schema, symbols, stype_in))

        def stop(self) -> None:
            pass

        def trigger_record(self, record) -> None:
            for cb in self.callbacks:
                cb(record)

    # Mock databento package inside sys.modules
    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    # 3. Instantiate and run real DatabentoLiveAdapter
    adapter = la.DatabentoLiveAdapter()
    assert adapter.credentials_present() is True

    events_received = []
    adapter.set_sink(lambda e: events_received.append(e), mode="shadow")

    # Connect
    health = adapter.connect()
    assert health["runtime_state"] == "CONNECTING"

    # Subscribe and verify mock callbacks are invoked
    sub_id = adapter.subscribe("MNQ 09-26", "trades")
    assert sub_id == "databento:MNQ 09-26:trades"
    assert adapter.health()["runtime_state"] == "AUTHENTICATED"

    # Manually trigger callback now that subscription is registered
    adapter._client.trigger_record(MockRecord())

    assert len(events_received) == 1
    ev = events_received[0]
    assert ev["type"] == "trade"
    assert ev["provider"] == "databento_live"
    assert ev["exact_contract"] == "MNQ 09-26"
    assert ev["price"] == 21001.25
    assert ev["volume"] == 5


def test_databento_disconnect_reconnect_resubscribe(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    class MockRecord:
        def __init__(self, symbol: str) -> None:
            self.price = 21000_000_000_000
            self.size = 1
            self.symbol = symbol
            self.ts_event = 1721100000000000000
            self.sequence = 1

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            self.key = args[0] if args else kwargs.get("key", "")
            self.reconnect_policy = kwargs.get("reconnect_policy", "none")
            self.slow_reader_behavior = kwargs.get("slow_reader_behavior", "none")
            self.callbacks = []
            self.reconnect_callbacks = []
            self.subscriptions = []
            self.started = False
            self.stopped = False

        def add_callback(self, cb) -> None:
            self.callbacks.append(cb)

        def add_reconnect_callback(self, cb) -> None:
            self.reconnect_callbacks.append(cb)

        def start(self) -> None:
            self.started = True

        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            self.subscriptions.append((dataset, schema, symbols, stype_in))

        def stop(self) -> None:
            self.stopped = True

        def trigger_reconnect(self) -> None:
            for cb in self.reconnect_callbacks:
                cb()

        def trigger_record(self, record) -> None:
            for cb in self.callbacks:
                cb(record)

    # Mock databento package inside sys.modules
    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    adapter = la.DatabentoLiveAdapter()
    adapter.connect()

    # Subscribe to a contract
    sub_id = adapter.subscribe("MNQ 09-26", "trades")
    assert adapter._client.reconnect_policy == "reconnect"
    assert len(adapter._client.subscriptions) == 1

    # 1. Disconnect (simulation of connection drop)
    adapter.disconnect()
    assert adapter._client is None
    assert adapter.health()["runtime_state"] == "DISABLED"

    # 2. Connect again
    adapter.connect()
    assert adapter._client.started is True
    assert adapter.health()["runtime_state"] == "CONNECTING"

    # 3. Re-subscribe
    sub_id2 = adapter.subscribe("MNQ 09-26", "trades")
    assert len(adapter._client.subscriptions) == 1


def test_databento_unsubscribe_lifecycle_filters_events(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    class MockRecord:
        def __init__(self, symbol: str) -> None:
            self.price = 21000_000_000_000
            self.size = 1
            self.symbol = symbol
            self.ts_event = 1721100000000000000
            self.sequence = 1

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            self.key = args[0] if args else kwargs.get("key", "")
            self.reconnect_policy = kwargs.get("reconnect_policy", "none")
            self.slow_reader_behavior = kwargs.get("slow_reader_behavior", "none")
            self.callbacks = []
            self.reconnect_callbacks = []
            self.subscriptions = []
            self.started = False
            self.stopped = False

        def add_callback(self, cb) -> None:
            self.callbacks.append(cb)

        def add_reconnect_callback(self, cb) -> None:
            self.reconnect_callbacks.append(cb)

        def start(self) -> None:
            self.started = True

        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            self.subscriptions.append((dataset, schema, symbols, stype_in))

        def stop(self) -> None:
            self.stopped = True

        def wait_for_close(self, timeout: float | None = None) -> None:
            pass

        def trigger_record(self, record) -> None:
            for cb in self.callbacks:
                cb(record)

    # Mock databento package inside sys.modules
    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    adapter = la.DatabentoLiveAdapter()
    events = []
    adapter.set_sink(lambda e: events.append(e), mode="shadow")

    adapter.connect()

    sub1 = adapter.subscribe("MNQ 09-26", "trades")
    sub2 = adapter.subscribe("MES 12-26", "trades")

    # Check that client has both subscriptions
    assert len(adapter._client.subscriptions) == 2

    # Trigger record for MNQ
    adapter._client.trigger_record(MockRecord("MNQU6"))
    assert len(events) == 1
    assert events[-1]["exact_contract"] == "MNQ 09-26"

    # Unsubscribe from MNQ 09-26
    # This must recreate the client and only resubscribe MES 12-26
    old_client = adapter._client
    assert old_client.stopped is False

    adapter.unsubscribe(sub1)
    assert old_client.stopped is True
    assert adapter._client is not old_client

    # Check that new client only has MES 12-26 subscribed
    assert len(adapter._client.subscriptions) == 1
    assert adapter._client.subscriptions[0][2] == "MESZ6"

    # Trigger record for MNQ (should be filtered out)
    adapter._client.trigger_record(MockRecord("MNQU6"))
    assert len(events) == 1  # No new event emitted for MNQ!

    # Trigger record for MES (should succeed)
    adapter._client.trigger_record(MockRecord("MESZ6"))
    assert len(events) == 2
    assert events[-1]["exact_contract"] == "MES 12-26"


def test_databento_stop_timeout_calls_terminate(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            self.key = args[0] if args else kwargs.get("key", "")
            self.reconnect_policy = kwargs.get("reconnect_policy", "none")
            self.slow_reader_behavior = kwargs.get("slow_reader_behavior", "none")
            self.stopped = False
            self.terminated = False
            self.subscriptions = []

        def add_callback(self, cb) -> None: pass
        def add_reconnect_callback(self, cb) -> None: pass
        def start(self) -> None: pass
        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            self.subscriptions.append((dataset, schema, symbols, stype_in))

        def stop(self) -> None:
            self.stopped = True

        def wait_for_close(self, timeout: float | None = None) -> None:
            raise Exception("Timeout reached waiting for close")

        def terminate(self) -> None:
            self.terminated = True

    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    adapter = la.DatabentoLiveAdapter()
    adapter.connect()
    adapter.subscribe("MNQ 09-26")

    client = adapter._client
    adapter.unsubscribe("databento:MNQ 09-26:trades")

    assert client.stopped is True
    assert client.terminated is True


def test_databento_stale_generation_event_rejection(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    class MockRecord:
        def __init__(self, symbol: str) -> None:
            self.price = 21000_000_000_000
            self.size = 1
            self.symbol = symbol

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            self.callbacks = []
            self.subscriptions = []

        def add_callback(self, cb) -> None:
            self.callbacks.append(cb)
        def add_reconnect_callback(self, cb) -> None: pass
        def start(self) -> None: pass
        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            self.subscriptions.append((dataset, schema, symbols, stype_in))
        def stop(self) -> None: pass

    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    adapter = la.DatabentoLiveAdapter()
    events = []
    adapter.set_sink(lambda e: events.append(e))

    adapter.connect()
    adapter.subscribe("MNQ 09-26")

    first_client = adapter._client
    assert adapter._generation == 1

    adapter.unsubscribe("databento:MNQ 09-26:trades")
    assert adapter._generation == 2

    first_client.callbacks[0](MockRecord("MNQU6"))
    assert len(events) == 0


def test_databento_subscription_failure(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            pass
        def add_callback(self, cb) -> None: pass
        def add_reconnect_callback(self, cb) -> None: pass
        def start(self) -> None: pass
        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            raise ValueError("Invalid credentials or symbol lookup failed")

    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    adapter = la.DatabentoLiveAdapter()
    adapter.connect()

    try:
        adapter.subscribe("MNQ 09-26")
    except ValueError:
        pass

    assert adapter.health()["runtime_state"] == "AUTH_FAILED"


def test_databento_symbol_mapping_msg(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    class MockSymbolMappingMsg:
        def __init__(self, inst_id: int, symbol: str) -> None:
            self.instrument_id = inst_id
            self.stype_in_symbol = symbol

    class MockRecord:
        def __init__(self, inst_id: int) -> None:
            self.price = 21000_000_000_000
            self.size = 1
            self.instrument_id = inst_id
            self.ts_event = 1721100000000000000
            self.sequence = 1234

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            self.callbacks = []
            self.subscriptions = []

        def add_callback(self, cb) -> None:
            self.callbacks.append(cb)
        def add_reconnect_callback(self, cb) -> None: pass
        def start(self) -> None: pass
        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            self.subscriptions.append((dataset, schema, symbols, stype_in))
        def stop(self) -> None: pass

    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    adapter = la.DatabentoLiveAdapter()
    events = []
    adapter.set_sink(lambda e: events.append(e))

    adapter.connect()
    adapter.subscribe("MNQ 09-26")

    adapter._client.callbacks[0](MockRecord(999))
    assert len(events) == 1
    assert events[0]["quality"].get("SYMBOL_MAPPING_PENDING") is True

    adapter._client.callbacks[0](MockSymbolMappingMsg(999, "MNQU6"))

    adapter._client.callbacks[0](MockRecord(999))
    assert len(events) == 2
    assert events[1]["quality"].get("SYMBOL_MAPPING_PENDING") is None
    assert events[1]["raw_symbol"] == "MNQU6"
    assert events[1]["exact_contract"] == "MNQ 09-26"


def test_databento_error_msg_system_msg(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    class MockErrorMsg:
        def __init__(self, err: str) -> None:
            self.err = err

    class MockSystemMsg:
        def __init__(self, msg: str) -> None:
            self.msg = msg

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            self.callbacks = []
            self.subscriptions = []

        def add_callback(self, cb) -> None:
            self.callbacks.append(cb)
        def add_reconnect_callback(self, cb) -> None: pass
        def start(self) -> None: pass
        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            self.subscriptions.append((dataset, schema, symbols, stype_in))
        def stop(self) -> None: pass

    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    adapter = la.DatabentoLiveAdapter()
    adapter.connect()
    adapter.subscribe("MNQ 09-26")

    assert adapter.health()["last_event_utc"] == ""
    adapter._client.callbacks[0](MockSystemMsg("Heartbeat pulse"))
    assert adapter.health()["last_event_utc"] != ""

    adapter._client.callbacks[0](MockErrorMsg("Invalid subscription option"))
    assert adapter.health()["runtime_state"] == "ERROR"
    assert "Invalid subscription option" in adapter.health()["last_error"]


def test_databento_slow_reader_gap(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DATABENTO_API_KEY", "real-production-key-under-test")

    class MockErrorMsg:
        def __init__(self, err: str) -> None:
            self.err = err

    class MockLiveClient:
        def __init__(self, *args, **kwargs) -> None:
            self.callbacks = []
            self.subscriptions = []

        def add_callback(self, cb) -> None:
            self.callbacks.append(cb)
        def add_reconnect_callback(self, cb) -> None: pass
        def start(self) -> None: pass
        def subscribe(self, dataset, schema, symbols, stype_in) -> None:
            self.subscriptions.append((dataset, schema, symbols, stype_in))
        def stop(self) -> None: pass

    import sys
    from unittest.mock import MagicMock
    mock_db_module = MagicMock()
    mock_db_module.Live = MockLiveClient
    sys.modules["databento"] = mock_db_module

    adapter = la.DatabentoLiveAdapter()
    adapter.connect()
    adapter.subscribe("MNQ 09-26")

    adapter._client.callbacks[0](MockErrorMsg("Slow reader: client is falling behind"))
    assert adapter.health()["runtime_state"] == "DEGRADED"

    from app import market_data_gap_recovery
    worker = market_data_gap_recovery.get_worker()
    worker._queue.clear()

    adapter._client.callbacks[0](MockErrorMsg("Skipped 42 records due to slow reading"))
    assert adapter.health()["runtime_state"] == "DEGRADED"
    assert len(worker._queue) == 1
    assert worker._queue[0]["reason"] == "slow_reader_skip"
    assert worker._queue[0]["exact_contract"] == "MNQ 09-26"


def test_topstepx_projectx_connector(monkeypatch) -> None:
    # 1. Setup credentials
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TOPSTEPX_LIVE", "1")
    monkeypatch.setenv("NTA_TOPSTEPX_USERNAME", "test_owner")
    monkeypatch.setenv("NTA_TOPSTEPX_API_KEY", "real-api-key-here")

    # 2. Mock the stdlib JSON transport used by the adapter.
    def mock_post(url, payload, *args, **kwargs):
        if "loginKey" in url:
            return {"success": True, "token": "mocked_jwt_token_xyz"}
        elif "search" in url:
            assert payload["live"] is False
            return {
                "contracts": [
                    {"id": "CON.F.US.MNQ.U26", "name": "MNQU6", "symbolId": "F.US.MNQ"}
                ]
            }
        elif "retrieveBars" in url:
            assert payload["live"] is False
            assert payload["startTime"].endswith("Z")
            assert payload["endTime"].endswith("Z")
            assert payload["includePartialBar"] is True
            return {
                "bars": [
                    {"time": "2026-07-16T14:00:00Z", "open": 20000.0, "high": 20050.0, "low": 19990.0, "close": 20010.0, "volume": 100}
                ]
            }
        raise RuntimeError("HTTP Error")

    monkeypatch.setattr(la, "_post_json", mock_post)

    # Mock websockets connect
    class MockWebSocket:
        def __init__(self):
            self.sent = []
            self.closed = False
            self.recv_count = 0

        async def send(self, msg: str) -> None:
            self.sent.append(msg)

        async def recv(self) -> str:
            # Simulate SignalR protocol handshake reply on first recv
            self.recv_count += 1
            if self.recv_count == 1:
                return '{}'
            # Subsequent recvs block or return ping or market data
            import asyncio
            await asyncio.sleep(10.0)
            return '{"type":6}'

        async def close(self) -> None:
            self.closed = True

    class MockWebsocketsModule:
        def __init__(self):
            self.client = MockWebSocket()

        def connect(self, url, *args, **kwargs):
            class AsyncContext:
                def __init__(self, client):
                    self.client = client
                async def __aenter__(self):
                    return self.client
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    await self.client.close()
            return AsyncContext(self.client)

    mock_ws_mod = MockWebsocketsModule()
    import sys
    sys.modules["websockets"] = mock_ws_mod

    # 3. Instantiate and test TopstepXProjectXAdapter
    adapter = la.TopstepXProjectXAdapter()
    assert adapter.credentials_present() is True

    health = adapter.connect()
    assert health["runtime_state"] == "CONNECTING"
    assert adapter._token == "mocked_jwt_token_xyz"

    # Wait for websocket thread loop to initialize and authenticate
    import time
    for _ in range(20):
        if adapter._runtime_state == "AUTHENTICATED":
            break
        time.sleep(0.1)

    assert adapter._runtime_state == "AUTHENTICATED"

    # Subscribe to MNQ 09-26
    sub_id = adapter.subscribe("MNQ 09-26", "trades")
    assert sub_id == "topstep:MNQ 09-26:trades"

    # Trigger incoming WebSocket Quote message
    events = []
    adapter.set_sink(lambda e: events.append(e))

    # Trigger OnQuote manually via _on_ws_message
    quote_arg = {"symbol": "MNQU6", "bestBid": 20010.0, "bestAsk": 20012.0, "volume": 5, "timestamp": "2026-07-16T14:00:00Z"}
    adapter._on_ws_message("GatewayQuote", ["CON.F.US.MNQ.U26", quote_arg])

    assert adapter._runtime_state == "LIVE"
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "quote"
    assert ev["exact_contract"] == "MNQ 09-26"
    assert ev["price"] == 20010.0
    assert ev["volume"] == 5

    # The official (contractId, data) callback remains routable even when the
    # trade payload omits symbol/symbolId.
    adapter._on_ws_message("GatewayTrade", [
        "CON.F.US.MNQ.U26",
        {"price": 20011.0, "volume": 2, "timestamp": "2026-07-16T14:00:01Z"},
    ])
    assert len(events) == 2
    assert events[-1]["exact_contract"] == "MNQ 09-26"

    # Official ProjectX SignalR target and string contract id are used.
    for _ in range(20):
        if any("SubscribeContractTrades" in msg for msg in mock_ws_mod.client.sent):
            break
        time.sleep(0.05)
    assert any("SubscribeContractQuotes" in msg for msg in mock_ws_mod.client.sent)
    assert any("CON.F.US.MNQ.U26" in msg for msg in mock_ws_mod.client.sent)

    # Test backfill / retrieveBars
    bars = adapter.backfill("MNQ 09-26", "1m", 10)
    assert len(bars) == 1
    assert bars[0]["c"] == 20010.0
