from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import market_data, market_data_failover as failover, server


def _iso(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _bar(stamp: str, close: float) -> dict:
    return {"t": stamp, "o": close, "h": close + 1, "l": close - 1, "c": close, "v": 10}


class StaticProvider(failover.MarketDataProvider):
    name = "independent_test"
    tier = "test"

    def __init__(self, bars, *, fail: bool = False):
        self.bars = bars
        self.fail = fail
        self.calls = 0

    def fetch(self, instrument: str, timeframe: str, limit: int):
        self.calls += 1
        if self.fail:
            raise failover.MarketDataProviderError("provider unavailable")
        bars = list(self.bars)[-limit:]
        freshness = failover.series_freshness(bars, timeframe)
        return {
            "instrument": instrument, "bars": bars, "total": len(bars),
            "live": freshness["fresh"], "status": "external_live",
            "requested_timeframe": timeframe, "matched_timeframe": timeframe,
            "source": {"kind": "external_provider", "provider": self.name,
                       "independent": True, "updated_at_utc": freshness["data_as_of_utc"]},
            "freshness": freshness,
            "quote": {"bid": 99, "ask": 101, "last": 100, "bid_ask_estimated": False},
        }


def test_independent_provider_keeps_chart_alive_without_ninjatrader(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(failover, "_root", lambda: tmp_path)
    failover.reset_runtime_state()
    provider = StaticProvider([_bar(_iso(1), 100)])

    result = failover.apply_failover(
        None, "MNQ", "1m", 100, primary_healthy=False, providers=[provider],
    )

    assert result and result["bars"][-1]["c"] == 100
    assert result["source"]["provider"] == "independent_test"
    assert result["source"]["independent"] is True
    assert result["gap_recovery"]["mode"] == "independent_failover"
    assert provider.calls == 1


def test_gap_recovery_fills_missing_bar_but_primary_wins_collision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(failover, "_root", lambda: tmp_path)
    failover.reset_runtime_state()
    t0 = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=3)
    stamps = [(t0 + timedelta(minutes=i)).isoformat().replace("+00:00", "Z") for i in range(4)]
    primary = {
        "instrument": "MNQ 09-26", "status": "live", "live": True,
        "source": {"kind": "ninjatrader_runtime"},
        "bars": [_bar(stamps[0], 100), _bar(stamps[2], 777), _bar(stamps[3], 103)],
    }
    provider = StaticProvider([
        _bar(stamps[0], 900), _bar(stamps[1], 101),
        _bar(stamps[2], 102), _bar(stamps[3], 103),
    ])

    result = failover.apply_failover(
        primary, "MNQ 09-26", "1m", 100,
        primary_healthy=True, providers=[provider], force_external=True,
    )

    by_time = {row["t"]: row for row in result["bars"]}
    assert by_time[stamps[1]]["c"] == 101
    assert by_time[stamps[2]]["c"] == 777  # bridge collision wins
    assert result["gap_recovery"]["recovered_bars"] == 1
    assert result["gap_recovery"]["unresolved_gaps"] == 0
    assert result["source"]["kind"] == "market_data_composite"


def test_provider_failure_automatically_switches_to_next(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(failover, "_root", lambda: tmp_path)
    failover.reset_runtime_state()
    broken = StaticProvider([], fail=True)
    broken.name = "broken_test"
    healthy = StaticProvider([_bar(_iso(1), 101)])

    result = failover.fetch_external_series(
        "MNQ", "1m", 20, providers=[broken, healthy], force=True,
    )

    assert result and result["source"]["provider"] == "independent_test"
    assert broken.calls == 1 and healthy.calls == 1
    state = failover.status()["last_selection"]
    assert state["selected"] == "independent_test"
    assert state["attempts"][0]["ok"] is False
    assert state["attempts"][1]["ok"] is True


def test_resample_and_gap_detection_never_invent_ohlcv() -> None:
    start = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    rows = []
    for offset in (0, 1, 2, 4):
        rows.append(_bar((start + timedelta(minutes=offset)).isoformat().replace("+00:00", "Z"), 100 + offset))

    gaps = failover.detect_gaps(rows, "1m")
    aggregated = failover.resample_bars(rows, "5m")

    assert gaps[0]["missing_intervals"] == 1
    assert len(aggregated) == 1
    assert aggregated[0]["o"] == 100
    assert aggregated[0]["c"] == 104
    assert aggregated[0]["v"] == 40


def test_actual_server_chain_uses_independent_provider_when_nt_is_off(tmp_path: Path, monkeypatch) -> None:
    failover.reset_runtime_state()
    provider = StaticProvider([_bar(_iso(1), 123.25)])
    monkeypatch.setattr(failover, "_root", lambda: tmp_path)
    monkeypatch.setattr(failover, "configured_providers", lambda: [provider])
    monkeypatch.setattr(market_data, "_root", lambda: tmp_path)
    monkeypatch.setattr(market_data, "register_request", lambda *a, **k: {})
    monkeypatch.setattr(market_data, "read_runtime_series", lambda *a, **k: None)
    monkeypatch.setattr(market_data, "snapshot_source_signature", lambda: "nt-off")
    monkeypatch.setattr(market_data, "alerts_source_signature", lambda: "alerts-none")
    monkeypatch.setattr(market_data, "list_alerts", lambda **k: {"alerts": []})
    monkeypatch.setattr(server.jobqueue, "ninjatrader_running", lambda: False)
    monkeypatch.setattr(server.ops_runtime, "read_heartbeat", lambda: {"fresh": False, "age_sec": 999})

    result = server._market_bars_payload("MNQ", "1m", 50)

    assert result["bars"][-1]["c"] == 123.25
    assert result["source"]["provider"] == "independent_test"
    assert result["gap_recovery"]["mode"] == "independent_failover"
    assert provider.calls == 1
