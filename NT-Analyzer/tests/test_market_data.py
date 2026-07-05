from __future__ import annotations

import json
from pathlib import Path

from app import market_data


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
