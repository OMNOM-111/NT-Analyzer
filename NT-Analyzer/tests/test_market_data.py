from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app import (account_auth, market_data, runtime, secure_store, server as server_mod,
                 subscriptions, telegram_remote, telegram_service, workspaces)


def _init_data(user_id: int, *, token: str) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "AAE-test",
        "user": json.dumps({"id": user_id, "first_name": "Test", "username": "tester"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(values)


def _write_snapshot(root: Path, *, close: float, high: float, low: float) -> None:
    path = root / "data" / "runtime" / "market_bars.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "series": [{
            "key": "MNQ 09-26|5m", "instrument": "MNQ 09-26", "timeframe": "5m",
            "status": "live", "updated_at_utc": "2026-07-04T20:00:00Z",
            "bars": [{"t": "2026-07-04T19:55:00Z", "o": 100, "h": high,
                      "l": low, "c": close, "v": 10}],
        }],
    }), encoding="utf-8")


def test_runtime_request_and_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    out = market_data.register_request("mnq 09-26", "5m", 9000)
    assert out["key"] == "MNQ 09-26|5m"
    req = json.loads((tmp_path / "data/runtime/market_data_requests.json").read_text(encoding="utf-8"))
    assert req["requests"][0]["limit"] == 9000
    market_data.register_requests([
        {"instrument": "MNQ 09-26", "timeframe": "5m", "limit": 12000, "range_days": 31},
        {"instrument": "MGC 08-26", "timeframe": "1h", "limit": 2000, "range_days": 366},
    ])
    req = json.loads((tmp_path / "data/runtime/market_data_requests.json").read_text(encoding="utf-8"))
    assert len(req["requests"]) == 2
    assert next(row for row in req["requests"] if row["key"] == "MNQ 09-26|5m")["limit"] == 12000

    _write_snapshot(tmp_path, close=100, high=101, low=99)
    series = market_data.read_runtime_series("MNQ 09-26", "5m", 10)
    assert series and series["live"] is True
    assert series["bars"][0]["c"] == 100
    assert market_data.latest_close("MNQ") == 100


def test_corrupt_market_snapshot_degrades_to_empty_and_recovers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    snapshot = tmp_path / "data" / "runtime" / "market_bars.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text('{"series": [broken', encoding="utf-8")

    assert market_data.read_runtime_series("MNQ 09-26", "5m", 10) is None

    _write_snapshot(tmp_path, close=101, high=102, low=100)
    recovered = market_data.read_runtime_series("MNQ 09-26", "5m", 10)
    assert recovered and recovered["bars"][0]["c"] == 101


def test_chart_queues_follow_runtime_workspace_override(tmp_path: Path) -> None:
    tenant_a = tmp_path / "tenant-a" / "runtime"
    tenant_b = tmp_path / "tenant-b" / "runtime"

    with runtime.runtime_dir_override(tenant_a):
        market_data.enqueue_chart_command({"type": "open", "instrument": "MNQ"})
        assert market_data.list_chart_commands()["total"] == 1
    with runtime.runtime_dir_override(tenant_b):
        assert market_data.list_chart_commands()["commands"] == []
        market_data.enqueue_chart_command({"type": "open", "instrument": "MGC"})
    with runtime.runtime_dir_override(tenant_a):
        commands = market_data.list_chart_commands()["commands"]
        assert [row["instrument"] for row in commands] == ["MNQ"]
    with runtime.runtime_dir_override(tenant_b):
        commands = market_data.list_chart_commands()["commands"]
        assert [row["instrument"] for row in commands] == ["MGC"]


def test_headless_chart_snapshot_renders_png_without_desktop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    monkeypatch.setattr(market_data, "chart_runtime_status", lambda *a, **k: {"ready": True})
    _write_snapshot(tmp_path, close=100, high=101, low=99)

    saved = market_data.render_chart_snapshot("MNQ", "5m", meta={"conversation_id": "C-HEADLESS"})
    found = market_data.read_snapshot(saved["file"])

    assert saved["instrument"] == "MNQ 09-26"
    assert saved["timeframe"] == "5m"
    assert saved["bars_rendered"] == 1
    assert found and found[1] == "image/png"
    assert found[0].startswith(b"\x89PNG\r\n\x1a\n")
    assert saved["url"].startswith("/api/ops/runtime/snapshots/")


def test_headless_chart_snapshot_http_endpoint_returns_png(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    monkeypatch.setattr(market_data, "chart_runtime_status", lambda *a, **k: {"ready": True})
    _write_snapshot(tmp_path, close=100, high=101, low=99)
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/chart/snapshot?root=MNQ&timeframe=5m", timeout=5) as response:
            blob = response.read()
            assert response.status == 200
            assert response.headers.get_content_type() == "image/png"
            assert blob.startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        server.shutdown()
        server.server_close()


def test_chart_runtime_allows_closed_market_bars_when_bridge_is_alive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    monkeypatch.setattr("app.jobqueue.ninjatrader_running", lambda: True)
    monkeypatch.setattr(runtime, "read_heartbeat", lambda: {"fresh": True, "age_sec": 1})
    _write_snapshot(tmp_path, close=100, high=101, low=99)

    status = market_data.chart_runtime_status("MNQ", "5m")

    assert status["ready"] is True
    assert status["data_available"] is True
    assert status["stale_data"] is True


def test_ensure_chart_runtime_subscribes_before_reporting_unavailable(monkeypatch) -> None:
    states = iter([
        {"ready": False, "nt_running": True, "heartbeat_fresh": True, "reason": "no bars"},
        {"ready": True, "nt_running": True, "heartbeat_fresh": True, "instrument": "MCL 08-26"},
    ])
    requested = []
    monkeypatch.setattr(market_data, "resolve_chart_instrument", lambda _value: "MCL 08-26")
    monkeypatch.setattr(market_data, "chart_runtime_status", lambda *_a, **_k: next(states))
    monkeypatch.setattr(market_data, "register_request", lambda *args, **kwargs: requested.append((args, kwargs)))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    status = market_data.ensure_chart_runtime("MCL", "5m", wait_seconds=1)

    assert status["ready"] is True
    assert status["subscription_requested"] is True
    assert requested[0][0][:2] == ("MCL 08-26", "5m")


def test_contract_resolution_ignores_bridge_error_row_for_bare_root(monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_read", lambda _path: {"series": [{
        "instrument": "MNQ", "timeframe": "1m", "status": "error", "bars": [],
        "updated_at_utc": "2026-07-16T16:20:37Z",
    }]})
    monkeypatch.setattr("app.jobqueue.read_instruments_catalog", lambda: {"instruments": [{
        "root": "MNQ", "instrument": "MNQ 09-26", "expiry": "09-26",
        "data_last": "2026-07-16",
    }]})

    assert market_data.resolve_chart_instrument("MNQ") == "MNQ 09-26"


def test_register_requests_does_not_downgrade_existing_subscription(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    market_data.register_request("MNQ 09-26", "5m", 12000, range_days=31)
    market_data.register_request("MNQ 09-26", "5m", 500, range_days=1)

    req = json.loads((tmp_path / "data/runtime/market_data_requests.json").read_text(encoding="utf-8"))
    row = req["requests"][0]
    assert row["key"] == "MNQ 09-26|5m"
    assert row["limit"] == 12000
    assert row["range_days"] == 31


def test_alert_arms_then_triggers_on_new_touch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    _write_snapshot(tmp_path, close=100, high=101, low=99)
    created = market_data.create_alert({
        "instrument": "MNQ 09-26", "timeframe": "5m", "type": "line",
        "price": 102, "label": "Пробой", "current_price": 100, "telegram": True,
    })["alert"]

    assert market_data.evaluate_alerts() == []
    _write_snapshot(tmp_path, close=101.5, high=102.25, low=99)
    fired = market_data.evaluate_alerts()
    assert [row["id"] for row in fired] == [created["id"]]
    assert market_data.pending_telegram_alerts()[0]["label"] == "Пробой"
    assert market_data.mark_telegram_notified(created["id"]) is True
    assert market_data.pending_telegram_alerts() == []


def test_alert_validation_and_delete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    try:
        market_data.create_alert({"instrument": "MNQ", "timeframe": "2m", "price": 1})
        assert False, "invalid timeframe must fail"
    except market_data.MarketDataError:
        pass
    alert = market_data.create_alert({"instrument": "MNQ", "timeframe": "1m", "price": 1})["alert"]
    assert market_data.delete_alert(alert["id"])["deleted"] is True
    assert market_data.list_alerts()["total"] == 0


def test_agent_rule_becomes_dispatchable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    _write_snapshot(tmp_path, close=100, high=101, low=99)
    alert = market_data.create_alert({
        "instrument": "MNQ 09-26", "timeframe": "5m", "price": 102,
        "action": "agent", "telegram": False, "agent_id": "secretary",
        "agent_message": "Подготовь отчёт", "current_price": 100,
    })["alert"]
    _write_snapshot(tmp_path, close=102, high=102.2, low=99)
    market_data.evaluate_alerts()
    pending = market_data.pending_agent_alerts()
    assert pending[0]["agent_id"] == "secretary"
    assert pending[0]["agent_message"] == "Подготовь отчёт"
    assert market_data.mark_agent_dispatched(alert["id"])
    assert market_data.pending_agent_alerts() == []


def test_snapshot_index_matches_read_runtime_series(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    _write_snapshot(tmp_path, close=100, high=101, low=99)
    index = market_data.read_snapshot_index()
    assert set(index) == {"MNQ 09-26|5m"}
    direct = market_data.read_runtime_series("MNQ 09-26", "5m", 10)
    cached = market_data.series_from_index(index, "MNQ 09-26", "5m", 10)

    # source.age_sec is computed from "now" on each call, so drop it before
    # comparing — every other field must be identical between the two paths.
    def _stable(payload):
        clone = dict(payload)
        clone["source"] = {k: v for k, v in clone["source"].items() if k != "age_sec"}
        return clone

    assert _stable(cached) == _stable(direct)
    assert cached["bars"] == direct["bars"]
    assert cached["live"] is True
    # A key that is not present returns None from both paths.
    assert market_data.series_from_index(index, "ES 09-26", "5m", 10) is None
    assert market_data.series_from_index({}, "MNQ 09-26", "5m", 10) is None


def test_alerts_index_groups_by_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    _write_snapshot(tmp_path, close=100, high=101, low=99)
    market_data.create_alert({"instrument": "MNQ 09-26", "timeframe": "5m", "price": 105})
    market_data.create_alert({"instrument": "MCL 08-26", "timeframe": "5m", "price": 70})
    index = market_data.read_alerts_index()
    assert [row["price"] for row in index.get("MNQ 09-26", [])] == [105]
    assert [row["price"] for row in index.get("MCL 08-26", [])] == [70]
    # Equivalent to per-instrument list_alerts(include_inactive=True).
    assert index.get("MNQ 09-26") == market_data.list_alerts(
        instrument="MNQ 09-26", include_inactive=True)["alerts"]


def test_snapshot_and_alert_indexes_reuse_signature_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    _write_snapshot(tmp_path, close=100, high=101, low=99)
    market_data.create_alert({"instrument": "MNQ 09-26", "timeframe": "5m", "price": 105})
    real_read = market_data._read
    calls: list[str] = []

    def counted(path: Path):
        calls.append(path.name)
        return real_read(path)

    monkeypatch.setattr(market_data, "_read", counted)

    assert market_data.read_snapshot_index()
    assert market_data.read_snapshot_index()
    assert calls.count("market_bars.json") == 1

    assert market_data.read_alerts_index()
    assert market_data.read_alerts_index()
    assert calls.count("price_alerts.json") == 1


def test_lttb_downsample_preserves_edges_and_visible_extreme() -> None:
    bars = [
        {"t": f"2026-07-04T10:{i:02d}:00Z", "o": i, "h": i + 1, "l": i - 1, "c": i}
        for i in range(120)
    ]
    bars[60] = {"t": "2026-07-04T11:00:00Z", "o": 60, "h": 5000, "l": 59, "c": 60}

    sampled = market_data.downsample_bars(bars, 24)

    assert len(sampled) <= 24
    assert sampled[0] == bars[0]
    assert sampled[-1] == bars[-1]
    assert any(row.get("h") == 5000 for row in sampled)


def test_runtime_series_quarantines_impossible_bars(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    path = tmp_path / "data" / "runtime" / "market_bars.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "series": [{
            "key": "MNQ 09-26|5m", "instrument": "MNQ 09-26", "timeframe": "5m",
            "status": "live", "updated_at_utc": "2026-07-04T20:00:00Z",
            "bars": [
                {"t": "2026-07-04T19:50:00Z", "o": 100, "h": 101, "l": 99, "c": 100, "v": 10},
                {"t": "2026-07-04T19:55:00Z", "o": 100, "h": 1_000_000_000, "l": 99, "c": 100, "v": 10},
                {"t": "2026-07-04T20:00:00Z", "o": 101, "h": 102, "l": 100, "c": 101, "v": 10},
            ],
        }],
    }), encoding="utf-8")

    series = market_data.read_runtime_series("MNQ 09-26", "5m", 10)

    assert series["total"] == 2
    assert series["raw_total"] == 3
    assert series["diagnostics"]["rejected_bars"] == 1
    assert series["diagnostics"]["reasons"]["range_explosion"] == 1


def test_cached_series_payload_reuses_workspace_signature_entry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    _write_snapshot(tmp_path, close=100, high=101, low=99)
    index = market_data.read_snapshot_index()
    real_series_from_index = market_data.series_from_index
    calls = {"count": 0}

    def counted(*args, **kwargs):
        calls["count"] += 1
        return real_series_from_index(*args, **kwargs)

    monkeypatch.setattr(market_data, "series_from_index", counted)

    first = market_data.cached_series_from_index(
        index, "MNQ 09-26", "5m", 10, workspace_id="ws_1", max_points=8)
    second = market_data.cached_series_from_index(
        index, "MNQ 09-26", "5m", 10, workspace_id="ws_1", max_points=8)

    assert first and second
    assert first["bars"] == second["bars"]
    assert calls["count"] == 1


def _batch_status(base: str, *, origin: str, host: str = "", xfh: str = "", init_data: str = ""):
    body = json.dumps({"requests": [{"instrument": "MNQ 09-26", "timeframe": "5m", "limit": 50}]}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    if host:
        headers["Host"] = host
    if xfh:
        headers["X-Forwarded-Host"] = xfh
    if init_data:
        headers["X-Telegram-Init-Data"] = init_data
    req = urllib.request.Request(base + "/api/ops/runtime/bars/batch", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw else None
        except ValueError:
            return exc.code, {"error": raw}


def test_bars_batch_allows_https_tunnel_same_origin(tmp_path: Path, monkeypatch) -> None:
    # The Telegram Mini App reaches the backend over an HTTPS tunnel. Even when
    # desktop auth is disabled, a remote tunnel request must be authenticated
    # against the approved allowlist (never silently promoted to owner). A
    # whitelisted read-only viewer can poll charts over a *same-origin* HTTPS
    # POST, a genuine cross-site POST is rejected, and an unauthenticated remote
    # POST is denied — while a genuine local desktop POST still works.
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
    monkeypatch.setenv(telegram_service.TOKEN_ENV, token)
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(telegram_remote, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    monkeypatch.setenv("NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED", "1")
    monkeypatch.setenv("NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED", "1")
    _write_snapshot(tmp_path, close=100, high=101, low=99)

    # Stale Mini App state is ignored by the current desktop auth decision.
    telegram_remote._write({
        "remote_enabled": True, "desktop_auth_required": False,
        "public_url": "https://app.stratforges.com", "users": [], "pairings": [],
    })
    assert account_auth.auth_required() is False
    # A formerly whitelisted viewer cannot use the retired Mini App transport.
    account_auth._write_doc({
        "version": 1,
        "users": [{"user_id": 42, "first_name": "View", "last_name": "Er", "email": "v@e.com",
                   "role": "full_control", "status": "active", "is_owner": False,
                   "ux_mode": "professional"}],
        "challenges": [], "sessions": [],
    })
    subscriptions.ensure_initial_trial(42, source="test_verified_registration")
    viewer = _init_data(42, token=token)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        status, out = _batch_status(base, origin="https://app.stratforges.com",
                                    host="app.stratforges.com", xfh="app.stratforges.com",
                                    init_data=viewer)
        assert status == 410, out
        assert out["code"] == "telegram_mini_app_isolated"

        # Unauthenticated remote tunnel POST is denied — no owner bypass. This is
        # the core of the fix: with desktop auth disabled, a tunnel request with
        # no Telegram credentials must NOT inherit the local-owner context.
        status_anon, _ = _batch_status(base, origin="https://app.stratforges.com",
                                       host="app.stratforges.com", xfh="app.stratforges.com")
        assert status_anon in (401, 403)

        # Genuine local desktop POST still works.
        status_local, _ = _batch_status(base, origin=base)
        assert status_local == 200
    finally:
        server.shutdown()
        server.server_close()
