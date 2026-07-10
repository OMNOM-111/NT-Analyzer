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

from app import (account_auth, market_data, secure_store, server as server_mod,
                 telegram_remote, telegram_service, workspaces)


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
        return exc.code, None


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
    monkeypatch.setattr(telegram_remote, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    _write_snapshot(tmp_path, close=100, high=101, low=99)

    # Production posture: remote Mini App enabled, desktop auth off.
    telegram_remote._write({
        "remote_enabled": True, "desktop_auth_required": False,
        "public_url": "https://app.stratforges.com", "users": [], "pairings": [],
    })
    assert account_auth.auth_required() is False
    # A whitelisted read-only viewer (charts are read-only observation).
    account_auth._write_doc({
        "version": 1,
        "users": [{"user_id": 42, "first_name": "View", "last_name": "Er", "email": "v@e.com",
                   "role": "read_only", "status": "active", "is_owner": False}],
        "challenges": [], "sessions": [],
    })
    viewer = _init_data(42, token=token)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        status, out = _batch_status(base, origin="https://app.stratforges.com",
                                    host="app.stratforges.com", xfh="app.stratforges.com",
                                    init_data=viewer)
        assert status == 200
        assert out["series"][0]["bars"]

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
