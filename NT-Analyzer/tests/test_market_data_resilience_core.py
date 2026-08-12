"""Tests for canonical event, registry, bar engine, providers, router, gaps."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import (
    canonical_bar_engine,
    canonical_event,
    instrument_registry,
    market_data_gap_recovery,
    market_data_providers,
    market_data_router,
)


def test_generated_sequence_not_exchange() -> None:
    ev = canonical_event.make_canonical_event(
        event_type="trade",
        provider="ninjatrader",
        raw_symbol="MNQ 09-26",
        exact_contract="MNQ 09-26",
        price=21000.25,
        generated_sequence=99,
        exchange_sequence=None,
        connection_sequence=5,
    )
    assert ev["generated_sequence"] == 99
    assert ev["exchange_sequence"] is None
    assert ev["connection_sequence"] == 5


def test_dedupe_prefers_exchange_sequence() -> None:
    cache = canonical_event.EventDedupeCache()
    a = canonical_event.make_canonical_event(
        event_type="trade", provider="x", raw_symbol="MNQ 09-26",
        exact_contract="MNQ 09-26", price=1, exchange_sequence=10,
        generated_sequence=1,
    )
    b = canonical_event.make_canonical_event(
        event_type="trade", provider="x", raw_symbol="MNQ 09-26",
        exact_contract="MNQ 09-26", price=1, exchange_sequence=10,
        generated_sequence=2,
    )
    assert cache.seen(a) is False
    assert cache.seen(b) is True


def test_instrument_registry_no_silent_continuous() -> None:
    instrument_registry.reset_registry_for_tests()
    reg = instrument_registry.get_registry()
    out = reg.resolve_exact("MNQ", allow_continuous=False)
    assert out["allow_continuous"] is False
    assert out.get("is_continuous") is not True
    cont = reg.resolve_exact("MNQ", allow_continuous=True, data_plane="analytics")
    assert cont["is_continuous"] is True
    assert cont["resolved"].endswith(".v.0")
    exact = reg.resolve_exact("MNQ 09-26")
    assert exact["resolved"] == "MNQ 09-26"
    assert exact["is_exact"] is True


def test_bar_engine_builds_multiple_timeframes() -> None:
    engine = canonical_bar_engine.CanonicalBarEngine("MNQ 09-26", timeframes=["1s", "1m", "5m"])
    base = datetime(2026, 7, 16, 14, 0, 0, tzinfo=timezone.utc)
    for i in range(130):
        ts = (base + timedelta(seconds=i)).isoformat().replace("+00:00", "Z")
        engine.on_trade({
            "type": "trade",
            "price": 100 + (i % 5) * 0.25,
            "volume": 1,
            "ts_event": ts,
            "exact_contract": "MNQ 09-26",
            "provider": "recorded",
        })
    assert len(engine.series("1s", 0)) >= 100
    assert len(engine.series("1m", 0)) >= 2
    assert engine.series("5m", 0)
    assert engine.series("1m", 1)[0]["state"] in {"provisional", "final", "corrected"}


def test_default_bar_engine_includes_live_one_hour_bucket() -> None:
    engine = canonical_bar_engine.CanonicalBarEngine("MNQ 09-26")
    engine.on_trade({"type": "trade", "price": 100.0, "volume": 1,
                     "ts_event": "2026-07-16T14:00:01Z", "exact_contract": "MNQ 09-26"})
    bars = engine.series("1h", 1)
    assert bars and bars[-1]["timeframe"] == "1h"
    assert bars[-1]["t"] == "2026-07-16T14:00:00Z"


def test_bar_engine_late_event_marks_corrected() -> None:
    engine = canonical_bar_engine.CanonicalBarEngine("MGC 08-26", timeframes=["1m"])
    t0 = datetime(2026, 7, 16, 15, 0, 10, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 16, 15, 1, 10, tzinfo=timezone.utc)
    t_late = datetime(2026, 7, 16, 15, 0, 40, tzinfo=timezone.utc)
    engine.on_trade({"type": "trade", "price": 2400.0, "volume": 1,
                     "ts_event": t0.isoformat().replace("+00:00", "Z")})
    engine.on_trade({"type": "trade", "price": 2401.0, "volume": 1,
                     "ts_event": t1.isoformat().replace("+00:00", "Z")})
    updates = engine.on_trade({"type": "trade", "price": 2405.0, "volume": 1,
                               "ts_event": t_late.isoformat().replace("+00:00", "Z")})
    assert any(u.get("action") == "correction" for u in updates)
    assert engine.stats()["late_events"] >= 1


def test_recorded_and_fault_injection() -> None:
    recorded = market_data_providers.RecordedProvider(events=[
        {"type": "trade", "exact_contract": "MNQ 09-26", "price": 1, "volume": 1,
         "ts_event": "2026-07-16T12:00:00Z"},
        {"type": "trade", "exact_contract": "MNQ 09-26", "price": 2, "volume": 1,
         "ts_event": "2026-07-16T12:00:01Z"},
        {"type": "trade", "exact_contract": "MNQ 09-26", "price": 3, "volume": 1,
         "ts_event": "2026-07-16T12:00:02Z"},
    ])
    rows = recorded.replay("MNQ 09-26")
    assert len(rows) == 3
    assert rows[0]["provider"] == "recorded"
    assert recorded.production_failover_eligible is False
    fault = market_data_providers.FaultInjectionProvider(
        recorded, drop_every=2, duplicate_every=3, bad_price_every=0)
    transformed = fault.transform(rows)
    assert len(transformed) >= 2
    assert fault.production_failover_eligible is False


def test_router_shadow_blocks_auto_failover() -> None:
    market_data_router.reset_router_for_tests()
    router = market_data_router.get_router()
    contract = "MNQ 09-26"
    base = datetime(2026, 7, 16, 16, 0, 0, tzinfo=timezone.utc)
    for i in range(30):
        ev = canonical_event.make_canonical_event(
            event_type="trade", provider="ninjatrader",
            raw_symbol=contract, exact_contract=contract,
            price=20000 + i * 0.25, volume=1, generated_sequence=i + 1,
            ts_event=(base + timedelta(seconds=i)).isoformat().replace("+00:00", "Z"),
        )
        router.ingest_primary("ws1", ev)
        shadow = dict(ev)
        shadow["provider"] = "databento"
        shadow["generated_sequence"] = 1000 + i
        router.ingest_shadow("databento", shadow)
    report = router.compare_shadow("databento", contract, tolerance_price=1.0)
    assert report.passed
    assert report.automatic_failover_allowed is False
    assert router.can_auto_failover("databento") is False
    with pytest.raises(ValueError):
        router.allow_automatic_failover("yahoo")
    router.allow_automatic_failover("databento", True)
    report2 = router.compare_shadow("databento", contract, tolerance_price=1.0)
    assert report2.automatic_failover_allowed is True
    result = router.try_failover("ws1", contract, "databento", market_session_state="open")
    assert result["ok"] is True
    assert result["source_epoch"] >= 1


def test_gap_recovery_worker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(market_data_gap_recovery, "_runtime_dir", lambda: tmp_path)
    worker = market_data_gap_recovery.GapRecoveryWorker(interval_sec=0.05)
    worker._run_job({
        "job_id": "job-1",
        "exact_contract": "MNQ 09-26",
        "fixture_bars": [{"t": "2026-07-16T12:00:00Z", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 1}],
    })
    assert worker.completed[-1]["status"] == "completed"
    assert worker.completed[-1]["recovered_bars"] == 1
    worker._run_job({"job_id": "job-2", "exact_contract": "MGC 08-26"})
    assert worker.completed[-1]["status"] == "blocked_no_provider"
