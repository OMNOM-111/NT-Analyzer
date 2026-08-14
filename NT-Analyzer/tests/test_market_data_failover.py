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


def test_scoped_failover_hysteresis_returns_preferred_without_mixing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(failover, "_root", lambda: tmp_path)
    failover.reset_runtime_state()
    preferred = StaticProvider([_bar(_iso(1), 100)], fail=True)
    preferred.name = "topstepx"
    backup = StaticProvider([_bar(_iso(1), 101)])
    backup.name = "databento"

    first = failover.fetch_external_series("MNQ 09-26", "1m", 20, providers=[preferred, backup])
    assert first and first["source"]["provider"] == "databento"
    assert first["source"]["failover_from"] == ""

    preferred.fail = False
    scope = failover._provider_scope("MNQ 09-26", "1m")
    failover._LAST_SELECTION[scope]["next_primary_probe_at"] = 0
    holding = failover.fetch_external_series("MNQ 09-26", "1m", 20, providers=[preferred, backup])
    # First successful probe is deliberately held: the active backup remains
    # the complete response range and no cross-provider bars are merged.
    assert holding and holding["source"]["provider"] == "databento"
    assert {row["c"] for row in holding["bars"]} == {101}

    failover._LAST_SELECTION[scope]["next_primary_probe_at"] = 0
    restored = failover.fetch_external_series("MNQ 09-26", "1m", 20, providers=[preferred, backup])
    assert restored and restored["source"]["provider"] == "topstepx"
    assert restored["source"]["failover_from"] == "databento"
    assert {row["c"] for row in restored["bars"]} == {100}


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
    class DisabledTopstep:
        name = "topstepx"

        @staticmethod
        def configured() -> bool:
            return False

    failover.reset_runtime_state()
    provider = StaticProvider([_bar(_iso(1), 123.25)])
    monkeypatch.setattr(failover, "_root", lambda: tmp_path)
    # This contract exercises the generic independent-provider fallback.  It
    # must not inherit credentialed TopstepX state from the developer machine.
    monkeypatch.setattr(failover, "TopstepXProvider", DisabledTopstep)
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


def test_cached_topstep_payload_is_not_invalidated_by_ninjatrader_state(monkeypatch) -> None:
    """TopstepX cache freshness comes from its shared SignalR state, not NT."""
    class FakeTopstep:
        def refresh_payload_liveness(self, payload):
            payload = dict(payload)
            payload["live"] = True
            payload["status"] = "external_live"
            payload["market_data_available"] = True
            payload["price_marker_live"] = True
            fresh = dict(payload.get("freshness") or {})
            fresh.update({"fresh": True, "market_feed_fresh": True, "offline": False})
            payload["freshness"] = fresh
            return payload

    monkeypatch.setattr(failover, "TopstepXProvider", FakeTopstep)
    payload = {
        "live": True,
        "status": "external_live",
        "market_data_available": True,
        "source": {"provider": "topstepx", "updated_at_utc": _iso(0)},
        "freshness": {"fresh": True, "offline": False},
    }
    result = server._refresh_market_payload_age(payload)
    assert result["live"] is True
    assert result["status"] == "external_live"
    assert result["price_marker_live"] is True


def test_root_managed_chart_resolves_current_topstep_contract(tmp_path: Path, monkeypatch) -> None:
    class RootResolvingTopstep(StaticProvider):
        name = "topstepx"

        def __init__(self) -> None:
            super().__init__([_bar(_iso(1), 777)])
            self.requested = []

        def fetch_range(self, instrument, timeframe, limit, **_kwargs):
            self.requested.append(instrument)
            assert instrument == "MBT"  # root-managed request, never stale MBT 07-26
            payload = super().fetch(instrument, timeframe, limit)
            payload["instrument"] = "MBT 08-26"
            payload["source"]["provider"] = "topstepx"
            return payload

        def fetch(self, instrument, timeframe, limit):
            return self.fetch_range(instrument, timeframe, limit)

    failover.reset_runtime_state()
    provider = RootResolvingTopstep()
    monkeypatch.setattr(failover, "_root", lambda: tmp_path)
    monkeypatch.setattr(failover, "TopstepXProvider", lambda: provider)
    monkeypatch.setattr(market_data, "resolve_chart_instrument", lambda _value: "MBT 07-26")
    monkeypatch.setattr(market_data, "snapshot_source_signature", lambda: "root-auto")
    monkeypatch.setattr(market_data, "alerts_source_signature", lambda: "alerts-none")
    monkeypatch.setattr(market_data, "list_alerts", lambda **_kwargs: {"alerts": []})
    monkeypatch.setattr(server, "_market_payload_cache_get", lambda _key: None)
    monkeypatch.setattr(server, "_market_payload_cache_put", lambda _key, _payload: None)

    result = server._market_bars_payload("MBT", "1m", 20)

    assert provider.requested == ["MBT"]
    assert result["resolved_instrument"] == "MBT 08-26"
    assert result["source"]["provider"] == "topstepx"


def test_server_environment_uses_topstepx_when_connector_snapshot_is_missing(tmp_path: Path, monkeypatch) -> None:
    class ProductionTopstep(StaticProvider):
        name = "topstepx"

        def __init__(self) -> None:
            super().__init__([_bar(_iso(1), 21450.25)])
            self.requested = []

        @staticmethod
        def configured() -> bool:
            return True

        def fetch_range(self, instrument, timeframe, limit, **_kwargs):
            self.requested.append(instrument)
            payload = super().fetch(instrument, timeframe, limit)
            payload["source"]["provider"] = "topstepx"
            payload["instrument"] = "MNQ 09-26"
            return payload

        def fetch(self, instrument, timeframe, limit):
            return self.fetch_range(instrument, timeframe, limit)

    failover.reset_runtime_state()
    provider = ProductionTopstep()
    monkeypatch.setattr(server, "_server_environment_explicit", lambda: True)
    monkeypatch.setattr(failover, "_root", lambda: tmp_path)
    monkeypatch.setattr(failover, "TopstepXProvider", lambda: provider)
    monkeypatch.setattr(server.market_data_ingestion, "workspace_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_market_payload_cache_get", lambda _key: None)
    monkeypatch.setattr(server, "_market_payload_cache_put", lambda _key, _payload: None)
    monkeypatch.setattr(market_data, "list_alerts", lambda **_kwargs: {"alerts": []})

    result = server._market_bars_payload("MNQ", "5m", 40, workspace_id="ws_personal_TEST1234")

    assert provider.requested == ["MNQ"]
    assert result["bars"][-1]["c"] == 21450.25
    assert result["source"]["provider"] == "topstepx"
    assert result["resolved_instrument"] == "MNQ 09-26"
    assert result.get("source", {}).get("kind") != "workspace_runtime_not_connected"


def test_requirements_declares_websockets_for_topstepx_signalr() -> None:
    text = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    assert "websockets" in text
