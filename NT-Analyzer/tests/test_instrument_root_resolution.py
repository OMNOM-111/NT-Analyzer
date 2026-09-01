"""Picking a root gives you the current contract, and NinjaTrader decides the rest.

The flow beside NinjaTrader is: /api/ops/runtime/instruments groups the catalog
by root and publishes a front_month per root; the UI puts that concrete contract
into the instrument field; the bridge hands the string to
`NinjaTrader.Cbi.Instrument.GetInstrument` and NinjaTrader runs it. The server
holds no separate opinion about which instruments exist or have history -- when
history is missing NinjaTrader says so itself, as `variant1_no_historical_bars`.

These tests pin the selector rule and pin the server to *not* gating on it.
"""
from datetime import datetime

import pytest

from app import jobqueue


NOW = datetime(2026, 9, 1)


def c(instrument, data_first, data_last):
    root, _, expiry = instrument.partition(" ")
    return {
        "instrument": instrument, "root": root, "expiry": expiry,
        "data_first": data_first, "data_last": data_last,
        "tick_size": 0.25, "point_value": 2, "tick_value": 0.5,
    }


CATALOG = [
    c("MNQ 09-26", "2026-06-11", "2026-08-31"),
    c("MNQ 06-26", "2026-03-15", "2026-06-11"),
    c("MNQ 03-26", "2025-12-14", "2026-03-13"),
    c("MNQ 12-25", "2025-09-14", "2025-12-12"),
    c("MES 09-26", "2026-07-15", "2026-09-01"),
    c("6M 09-26", "2026-06-10", "2026-08-20"),
    c("6M 12-26", "2026-08-25", ""),
    # The energy shape the rule exists for: the month has passed but bars are
    # still inside the 30-day window, and the next month is already listed.
    c("MCL 08-26", "2026-05-20", "2026-08-28"),
    c("MCL 10-26", "2026-08-29", ""),
    {"instrument": "BTCUSD", "root": "BTCUSD", "expiry": "",
     "data_first": "2024-01-01", "data_last": "2026-09-01"},
]


def front_month(root):
    """What the selector publishes for a root, and so what the UI submits."""
    rows = [r for r in CATALOG if r.get("root") == root]
    picked = jobqueue.resolve_front_month(rows, now=NOW)
    return picked and picked.get("instrument")


@pytest.mark.parametrize("root,expected", [
    ("MNQ", "MNQ 09-26"),
    ("MES", "MES 09-26"),
    ("6M", "6M 09-26"),
])
def test_root_publishes_the_current_contract(root, expected):
    assert front_month(root) == expected


def test_passed_month_with_recent_bars_yields_to_the_listed_future_month():
    assert front_month("MCL") == "MCL 10-26"


def test_current_month_is_not_treated_as_expired():
    # On 2026-09-01 the 09-26 month is current, so it keeps the slot even though
    # 6M 12-26 is listed.
    assert front_month("6M") == "6M 09-26"


def test_spot_instrument_resolves_to_itself_without_a_contract_month():
    assert front_month("BTCUSD") == "BTCUSD"


def test_no_contracts_yields_no_front_month():
    assert jobqueue.resolve_front_month([], now=NOW) is None


def _request(instrument):
    return jobqueue.CreateJobRequest(
        class_name="SampleMACrossOver", instrument=instrument,
        bars_period_type="Minute", bars_period_value=5,
        from_utc="2026-08-20T00:00:00Z", to_utc="2026-08-22T00:00:00Z",
        parameters={}, role="research",
    )


@pytest.mark.parametrize("instrument", ["MNQ 09-26", "MNQ SEP26", "6M", "BTCUSD", "10YR 10-25"])
def test_the_server_does_not_gate_the_instrument(instrument, monkeypatch):
    """NinjaTrader resolves the name and reports missing history itself.

    A server-side allowlist would refuse instruments NinjaTrader can run --
    `MNQ SEP26` and `10YR 10-25` are both shapes it has accepted -- and would be
    a second source of truth about a machine the server cannot see.
    """
    monkeypatch.setattr(jobqueue, "whitelisted_strategies", lambda: ["SampleMACrossOver"])
    jobqueue._validate(_request(instrument))


def test_an_empty_instrument_is_still_refused(monkeypatch):
    monkeypatch.setattr(jobqueue, "whitelisted_strategies", lambda: ["SampleMACrossOver"])
    with pytest.raises(jobqueue.JobValidationError):
        jobqueue._validate(_request(""))
