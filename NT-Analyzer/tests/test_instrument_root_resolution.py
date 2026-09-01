"""A bare root must resolve to the same contract for the selector and a backtest.

The selector turned "MNQ" into the current contract long before the backtest
existed; the backtest refused the same input. These tests pin the two to one
rule and to one another.
"""
from datetime import datetime

import pytest

from app import jobqueue


NOW = datetime(2026, 9, 1)


def c(instrument, data_first, data_last, **extra):
    root, _, expiry = instrument.partition(" ")
    row = {
        "instrument": instrument, "root": root, "expiry": expiry,
        "data_first": data_first, "data_last": data_last,
        "tick_size": 0.25, "point_value": 2, "tick_value": 0.5,
    }
    row.update(extra)
    return row


CATALOG = [
    # MNQ: the live front month plus older, expired quarters.
    c("MNQ 09-26", "2026-06-11", "2026-08-31"),
    c("MNQ 06-26", "2026-03-15", "2026-06-11"),
    c("MNQ 03-26", "2025-12-14", "2026-03-13"),
    c("MNQ 12-25", "2025-09-14", "2025-12-12"),
    # MES: one contract, still trading.
    c("MES 09-26", "2026-07-15", "2026-09-01"),
    # 6M: current month still trading, next quarter already listed.
    c("6M 09-26", "2026-06-10", "2026-08-20"),
    c("6M 12-26", "2026-08-25", ""),
    # MCL: the energy case the rule was written for -- the contract whose month
    # has already passed still has bars inside the 30-day window, and the next
    # month is listed with no history yet.
    c("MCL 08-26", "2026-05-20", "2026-08-28"),
    c("MCL 10-26", "2026-08-29", ""),
    # Spot pairs: a data range, no contract month.
    {"instrument": "BTCUSD", "root": "BTCUSD", "expiry": "",
     "data_first": "2024-01-01", "data_last": "2026-09-01"},
    {"instrument": "BCHEUR", "root": "BCHEUR", "expiry": "",
     "data_first": "2024-01-01", "data_last": "2026-08-30"},
    # A root the device knows about but holds no history for.
    {"instrument": "6A", "root": "6A", "expiry": "", "data_first": "", "data_last": ""},
]


def selector_choice(root):
    """What /api/ops/runtime/instruments would show as front_month."""
    rows = [r for r in CATALOG if (r.get("root") or "") == root]
    front = jobqueue.resolve_front_month(rows, now=NOW)
    return front and front.get("instrument")


def backtest_choice(root):
    """What a backtest resolves the same root to."""
    return jobqueue.resolve_root_instrument(root, CATALOG, now=NOW)


@pytest.mark.parametrize("root,expected", [
    ("MNQ", "MNQ 09-26"),
    ("MES", "MES 09-26"),
    ("6M", "6M 09-26"),
    ("MCL", "MCL 10-26"),
])
def test_root_resolves_to_current_contract(root, expected):
    assert backtest_choice(root) == expected


@pytest.mark.parametrize("root", ["MNQ", "MES", "6M", "MCL"])
def test_selector_and_backtest_agree(root):
    assert selector_choice(root) == backtest_choice(root)


@pytest.mark.parametrize("spot", ["BTCUSD", "BCHEUR"])
def test_spot_instrument_never_gets_a_contract_month(spot):
    # Already runnable, so resolution declines to touch it.
    assert jobqueue.resolve_root_instrument(spot, CATALOG, now=NOW) is None
    assert selector_choice(spot) == spot


def test_root_without_history_does_not_resolve():
    assert jobqueue.resolve_root_instrument("6A", CATALOG, now=NOW) is None


def test_concrete_instrument_is_left_alone():
    assert jobqueue.resolve_root_instrument("MNQ 03-26", CATALOG, now=NOW) is None


def test_unknown_root_does_not_resolve():
    assert jobqueue.resolve_root_instrument("ZZZ", CATALOG, now=NOW) is None


def test_expired_month_with_recent_bars_yields_to_the_listed_future_month():
    # MCL 08-26 still has bars inside the 30-day window but its month is gone,
    # so the still-listed MCL 10-26 wins -- rule step 2.
    assert backtest_choice("MCL") == "MCL 10-26"


def test_current_month_is_not_treated_as_expired():
    # 6M 09-26 is the current month on 2026-09-01 and keeps the slot even though
    # 6M 12-26 is listed.
    assert backtest_choice("6M") == "6M 09-26"


def test_freshest_wins_among_unexpired_contracts():
    assert backtest_choice("MNQ") == "MNQ 09-26"
