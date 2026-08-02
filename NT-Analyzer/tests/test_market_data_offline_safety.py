"""Offline/stale safety when NinjaTrader is down and no live backup exists."""
from __future__ import annotations

from app import market_data_failover as mdf


def test_yahoo_never_claims_live() -> None:
    provider = mdf.YahooChartProvider()
    # Use a synthetic fetch path by monkeypatching would need network;
    # assert policy helpers instead when offline.
    assert mdf.production_live_failover_eligible("yahoo_chart") is False
    assert mdf.production_live_failover_eligible("yahoo") is False
    assert mdf.production_live_failover_eligible("recorded") is False
    assert mdf.production_live_failover_eligible("databento") is True


def test_offline_snapshot_never_live() -> None:
    payload = {
        "bars": [{"t": "2026-07-16T20:00:00Z", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 1}],
        "live": True,
        "status": "live",
        "source": {"kind": "ninjatrader_runtime", "provider": "ninjatrader"},
        "freshness": {"fresh": True, "stale": False, "age_sec": 600, "data_as_of_utc": "2026-07-16T20:00:00Z"},
    }
    out = mdf.mark_offline_snapshot(payload, reason="test", last_source="ninjatrader", backup_providers_available=0)
    assert out["live"] is False
    assert out["status"] == "offline"
    assert out["market_data_available"] is False
    assert out["strategy_blocked"] is True
    assert out["execution_blocked"] is True
    assert out["price_marker_live"] is False
    assert out["offline_banner"]["backup_providers_available"] == 0
    assert out["freshness"]["offline"] is True


def test_apply_failover_offline_when_primary_unhealthy(monkeypatch) -> None:
    monkeypatch.delenv("NTA_DATABENTO_API_KEY", raising=False)
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    primary = {
        "instrument": "MNQ 09-26",
        "bars": [
            {"t": "2026-07-16T20:00:00Z", "o": 21000, "h": 21001, "l": 20999, "c": 21000.5, "v": 1},
            {"t": "2026-07-16T20:05:00Z", "o": 21000.5, "h": 21002, "l": 20998, "c": 21001, "v": 2},
        ],
        "status": "live",
        "live": True,
        "source": {"kind": "ninjatrader_runtime"},
    }

    def boom(*args, **kwargs):
        raise AssertionError("must not call delayed/Yahoo providers when NT offline and no live backup")

    monkeypatch.setattr(mdf, "fetch_external_series", boom)
    out = mdf.apply_failover(primary, "MNQ 09-26", "5m", 50, primary_healthy=False)
    assert out is not None
    assert out["live"] is False
    assert out["status"] == "offline"
    assert out["offline_banner"]["title"].startswith("OFFLINE")
    assert out["bars"], "history must still be available"
    assert (out.get("gap_recovery") or {}).get("skipped_delayed_providers") is True


def test_live_backup_candidates_exclude_yahoo(monkeypatch) -> None:
    monkeypatch.delenv("NTA_DATABENTO_API_KEY", raising=False)
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    cands = mdf.live_backup_candidates([mdf.YahooChartProvider(), mdf.DatabentoProvider()])
    assert all(p.name != "yahoo_chart" for p in cands)
    # Databento without key is not configured → empty
    assert cands == []

