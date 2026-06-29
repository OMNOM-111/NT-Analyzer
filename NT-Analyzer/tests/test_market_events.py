from __future__ import annotations

from datetime import date, time

from app import integrations, market_events


def test_calendar_has_high_impact_events() -> None:
    events = market_events.build_calendar(days_back=1, days_ahead=40)
    assert events
    titles = " ".join(e["title"] for e in events)
    for needle in ("NFP", "CPI", "PPI", "EIA", "Jobless", "GDP", "PCE", "JOLTS"):
        assert needle in titles
    assert all(e["severity"] in {"high", "medium", "low"} for e in events)
    assert all(e["schedule_status"] in {"confirmed", "estimated"} for e in events)
    assert any(e["source_type"] == "official_schedule" for e in events)


def test_events_are_sorted_and_have_block_windows() -> None:
    events = market_events.build_calendar(days_ahead=30)
    times = [e["event_time_utc"] for e in events]
    assert times == sorted(times)
    high = [e for e in events if e["severity"] == "high"]
    assert high and all(e["block_before_min"] == 30 and e["block_after_min"] == 15 for e in high)


def test_fomc_is_confirmed_and_et_converts_to_utc() -> None:
    fomc = market_events._make(date(2026, 7, 29), time(14, 0), "FOMC", "central_bank", "high", "Federal Reserve", True)
    assert fomc["is_confirmed"] is True
    assert fomc["event_time_utc"] == "2026-07-29T18:00:00Z"  # 14:00 ET (EDT) -> 18:00 UTC


def test_official_july_schedule_does_not_use_weekday_guesses() -> None:
    rows = market_events.official_events(date(2026, 6, 29), date(2026, 8, 1))
    by_title = {}
    for row in rows:
        by_title.setdefault(row["title"], []).append(row)
    assert by_title["NFP / Employment Situation"][0]["event_time_et"] == "2026-07-02 08:30 ET"
    assert by_title["CPI (индекс потребцен)"][0]["event_time_et"] == "2026-07-14 08:30 ET"
    assert by_title["PPI (цены производителей)"][0]["event_time_et"] == "2026-07-15 08:30 ET"
    assert by_title["GDP (ВВП)"][0]["event_time_et"] == "2026-07-30 08:30 ET"
    assert by_title["PCE / Personal Income"][0]["event_time_et"] == "2026-07-30 08:30 ET"
    assert all(row["is_confirmed"] for row in rows)


def test_news_passthrough_keeps_enriched_fields(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(market_events, "_root", lambda: tmp_path)
    monkeypatch.setattr(integrations, "_root", lambda: tmp_path)
    market_events.write_news_json()
    doc = integrations.news(200)
    assert doc["configured"] is True
    item = doc["items"][0]
    assert item["item_type"] == "calendar_event"
    for key in ("severity", "category", "affected_instruments", "block_before_min", "is_confirmed", "schedule_status", "risk_action", "event_time_pt", "fetched_at_utc", "source_url"):
        assert key in item
