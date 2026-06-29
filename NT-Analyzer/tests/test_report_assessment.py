from __future__ import annotations

from app import report_assessment


def _period(days: int) -> dict:
    return {
        "from_utc": "2026-01-01T00:00:00Z",
        "to_utc": f"2026-01-{1 + days:02d}T00:00:00Z" if days < 28 else "2026-04-01T00:00:00Z",
    }


def test_frequency_boundaries_match_product_policy() -> None:
    seven_days = _period(7)
    assert report_assessment.frequency_assessment(1, seven_days)["key"] == "rare"
    assert report_assessment.frequency_assessment(2, seven_days)["key"] == "normal"
    assert report_assessment.frequency_assessment(7, seven_days)["key"] == "normal"
    assert report_assessment.frequency_assessment(8, seven_days)["key"] == "frequent"


def test_confidence_is_independent_from_profitability() -> None:
    period = {"from_utc": "2026-01-01T00:00:00Z", "to_utc": "2026-04-01T00:00:00Z"}
    shared = {"winning_pct": 50, "profit_factor": 1, "max_drawdown": 100}
    profitable = report_assessment.confidence_assessment(100, period, {**shared, "net_profit": 50_000})
    losing = report_assessment.confidence_assessment(100, period, {**shared, "net_profit": -50_000})
    assert profitable == losing


def test_small_sample_confidence_is_capped() -> None:
    period = {"from_utc": "2025-01-01T00:00:00Z", "to_utc": "2026-01-01T00:00:00Z"}
    assessment = report_assessment.confidence_assessment(
        4,
        period,
        {"winning_pct": 100, "profit_factor": 99, "max_drawdown": 0},
    )
    assert assessment["score"] <= 18
    assert assessment["level"] == "very_low"
