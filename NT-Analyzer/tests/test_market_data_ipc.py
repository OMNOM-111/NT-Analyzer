"""Targeted tests for Phase 0 baseline + Phase 1–3 secured IPC."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from app import market_data_baseline, market_data_ipc


@pytest.fixture()
def ipc_runtime(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NTA_DATA_ROOT", str(tmp_path))
    # Force runtime paths under tmp.
    monkeypatch.setattr(market_data_ipc, "_runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr(market_data_baseline, "_runtime_dir", lambda: tmp_path / "runtime")
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    market_data_ipc.reset_runtime_state()
    market_data_baseline.reset()
    market_data_ipc.ensure_auth_token(force_new=True)
    yield tmp_path
    market_data_ipc.stop_server()
    market_data_ipc.reset_runtime_state()


def test_baseline_percentile_and_persist(ipc_runtime: Path) -> None:
    for value in (1.0, 2.0, 3.0, 4.0, 100.0):
        market_data_baseline.mark("unit.stage", value)
    stats = market_data_baseline.stage_stats("unit.stage")
    assert stats["samples"] == 5
    assert stats["p50_ms"] == 3.0
    assert stats["p95_ms"] >= 4.0
    path = market_data_baseline.persist()
    assert path.is_file()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["stages"]
    assert "desktop.js LIVE_POLL_MS=350" in " ".join(doc["known_bottlenecks_code_audit"])


def test_baseline_file_io_measurement(ipc_runtime: Path, monkeypatch) -> None:
    snap = ipc_runtime / "runtime" / "market_bars.json"
    monkeypatch.setattr(
        "app.market_data._snapshot_path",
        lambda: snap,
    )
    result = market_data_baseline.measure_file_snapshot_io(path=snap, iterations=5)
    assert result["bytes"] > 100
    assert result["write"]["p50_ms"] is not None
    assert result["read"]["p50_ms"] is not None


def test_ipc_rejects_missing_token(ipc_runtime: Path) -> None:
    server = market_data_ipc.IpcServer(port=18771, token=market_data_ipc.auth_token())
    server.start()
    try:
        client = market_data_ipc.IpcClient(port=18771, token="wrong-token")
        with pytest.raises(PermissionError):
            client.connect()
        assert market_data_ipc.metrics()["rejected_auth"] >= 1
    finally:
        server.stop()


def test_ipc_rejects_bad_protocol_version(ipc_runtime: Path) -> None:
    server = market_data_ipc.IpcServer(port=18772, token=market_data_ipc.auth_token())
    server.start()
    try:
        import socket
        sock = socket.create_connection(("127.0.0.1", 18772), timeout=3)
        sock.sendall(market_data_ipc.encode_frame({
            "type": "hello",
            "protocol_version": 999,
            "auth_token": market_data_ipc.auth_token(),
            "connection_id": "x",
            "transport": "tcp",
        }))
        reply = market_data_ipc.read_frame(sock, timeout=3)
        sock.close()
        assert reply["type"] == "error"
        assert reply["reason"] == "unsupported_protocol_version"
    finally:
        server.stop()


def test_ipc_authenticated_event_roundtrip(ipc_runtime: Path) -> None:
    server = market_data_ipc.IpcServer(port=18773, token=market_data_ipc.auth_token())
    server.start()
    try:
        client = market_data_ipc.IpcClient(port=18773, token=market_data_ipc.auth_token())
        welcome = client.connect(bridge_version="unit-test")
        assert welcome["type"] == "welcome"
        assert welcome["protocol_version"] == market_data_ipc.PROTOCOL_VERSION
        client.send_event({
            "type": "trade",
            "exact_contract": "MNQ 09-26",
            "raw_symbol": "MNQ 09-26",
            "price": 21012.5,
            "bid": 21012.25,
            "ask": 21012.75,
            "volume": 2,
            "generated_sequence": 7,
            "exchange_sequence": None,
            "ts_event": "2026-07-16T20:00:00Z",
        })
        deadline = time.time() + 2.0
        events = []
        while time.time() < deadline:
            events = market_data_ipc.recent_events(10)
            if events:
                break
            time.sleep(0.02)
        assert events, "expected ingested event"
        event = events[-1]
        assert event["exact_contract"] == "MNQ 09-26"
        assert event["generated_sequence"] == 7
        assert event["exchange_sequence"] is None
        assert event["provider"] == "ninjatrader"
        assert event["data_plane"] == "display"
        ack = client.heartbeat()
        assert ack["type"] == "heartbeat_ack"
        client.close()
    finally:
        server.stop()


def test_ipc_backpressure_drops(ipc_runtime: Path) -> None:
    market_data_ipc.reset_runtime_state()
    with market_data_ipc._LOCK:
        market_data_ipc._METRICS["queue_capacity"] = 3
    for i in range(5):
        ok = market_data_ipc.ingest_event({
            "type": "trade",
            "exact_contract": "MGC 08-26",
            "generated_sequence": i,
            "ts_receive": market_data_ipc._iso(),
        })
        if i < 3:
            assert ok
        else:
            assert not ok
    assert market_data_ipc.metrics()["dropped"] >= 2


def test_generated_sequence_not_promoted_to_exchange() -> None:
    event = market_data_ipc.normalize_bridge_event(
        {
            "type": "trade",
            "exact_contract": "MNQ 09-26",
            "generated_sequence": 42,
            "price": 1,
        },
        connection_id="c1",
        connection_sequence=9,
    )
    assert event["generated_sequence"] == 42
    assert event["connection_sequence"] == 9
    assert event["exchange_sequence"] is None


def test_ipc_transport_benchmark_selects_tcp(ipc_runtime: Path) -> None:
    # The benchmark asks the OS for a free ephemeral port.
    market_data_ipc.reset_runtime_state()
    result = market_data_ipc.benchmark_transports(iterations=50, payload_bytes=64)
    assert result["selected_default"] == "tcp"
    assert "tcp_length_prefixed_json" in result["transports"]
    assert result["transports"]["tcp_length_prefixed_json"]["events_per_sec"] > 0


def test_non_localhost_bind_rejected() -> None:
    with pytest.raises(ValueError):
        market_data_ipc.IpcServer(host="0.0.0.0", port=18774, token="x")


def test_csharp_exporter_static_checks() -> None:
    bridge_dir = Path(__file__).resolve().parent.parent / "bridge" / "src" / "Runtime"
    exporter_path = bridge_dir / "RuntimeMarketDataExporter.cs"
    assert exporter_path.is_file()
    text = exporter_path.read_text(encoding="utf-8")

    # 1. Verify CheckIpcReconnect null check order
    # it must have "if (_ipcClient == null) return;" before calling "_ipcClient.ConnectionId"
    check_func_idx = text.find("void CheckIpcReconnect()")
    assert check_func_idx != -1

    # Extract the CheckIpcReconnect method content
    method_text = text[check_func_idx:check_func_idx+1000]

    null_check_idx = method_text.find("if (_ipcClient == null)")
    conn_id_idx = method_text.find("_ipcClient.ConnectionId")

    assert null_check_idx != -1, "null check not found in CheckIpcReconnect"
    assert conn_id_idx != -1, "ConnectionId read not found in CheckIpcReconnect"
    assert null_check_idx < conn_id_idx, "Null check must be executed before ConnectionId read"

    # 2. Verify ResubscribeInstrument removes the old subscription, disposes it, and atomically adds new one
    resub_idx = text.find("void ResubscribeInstrument(string instrument)")
    assert resub_idx != -1
    resub_method = text[resub_idx:resub_idx+2500]

    assert "_subscriptions.Remove(keyToRecreate)" in resub_method
    assert "DisposeSubscription(oldSub)" in resub_method
    assert "Subscription newSub = new Subscription" in resub_method
    assert "StartSubscription(newSub)" in resub_method
    assert "_subscriptions.Add(keyToRecreate, newSub)" in resub_method
