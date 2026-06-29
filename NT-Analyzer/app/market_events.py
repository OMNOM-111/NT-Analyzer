"""Trading-relevant US economic calendar with explicit source trust.

Critical events are taken from published 2026 schedules from the Federal
Reserve, BLS, BEA, Census and EIA.  A small number of recurring weekly events
are generated only when no machine-readable calendar exists; those rows are
clearly marked as estimates and never qualify for a critical stop alert.

The module is network-independent so the operator still has a useful calendar
after a restart.  Dates are intentionally curated instead of guessed from
"nth weekday" rules: official release dates move around holidays and can be
rescheduled.
"""
from __future__ import annotations

import json
import os
from calendar import THURSDAY, WEDNESDAY
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

try:  # Python 3.9+; tzdata supplies this on Windows.
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
    _PT = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - last-resort fixed offsets
    _ET = timezone(timedelta(hours=-5))
    _PT = timezone(timedelta(hours=-8))


FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_URLS = {
    "NFP / Employment Situation": "https://www.bls.gov/schedule/news_release/empsit.htm",
    "CPI (индекс потребцен)": "https://www.bls.gov/schedule/news_release/cpi.htm",
    "PPI (цены производителей)": "https://www.bls.gov/schedule/news_release/ppi.htm",
    "JOLTS (вакансии)": "https://www.bls.gov/schedule/news_release/jolts.htm",
}
BEA_URL = "https://www.bea.gov/news/schedule/full"
CENSUS_URL = "https://www.census.gov/economic-indicators/"
EIA_URL = "https://www.eia.gov/petroleum/supply/weekly/schedule.php"
DOL_URL = "https://www.dol.gov/newsroom/releases?topic=132"

# Affected futures by category (micros first, then full size where relevant).
_MARKETS = {
    "central_bank": ["MNQ", "MES", "MYM", "MGC", "MCL", "USD"],
    "inflation": ["MNQ", "MES", "MYM", "MGC", "USD"],
    "labor": ["MNQ", "MES", "MYM", "MGC", "USD"],
    "growth": ["MNQ", "MES", "MYM", "MGC", "USD"],
    "energy": ["MCL", "CL", "MGC"],
}

# Published FOMC decision days (statement at 14:00 ET).
SEEDED_FOMC = {
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
    date(2027, 1, 27), date(2027, 3, 17),
}

# Official BLS schedules as published for 2026. BLS blocks many automated
# clients, so these curated dates are the reliable offline fallback.
_BLS_2026: Dict[str, Sequence[Tuple[int, int]]] = {
    "NFP / Employment Situation": (
        (1, 9), (2, 11), (3, 6), (4, 3), (5, 8), (6, 5),
        (7, 2), (8, 7), (9, 4), (10, 2), (11, 6), (12, 4),
    ),
    "CPI (индекс потребцен)": (
        (1, 13), (2, 13), (3, 11), (4, 10), (5, 12), (6, 10),
        (7, 14), (8, 12), (9, 11), (10, 14), (11, 10), (12, 10),
    ),
    "PPI (цены производителей)": (
        (1, 14), (1, 30), (2, 27), (3, 18), (4, 14), (5, 13),
        (6, 11), (7, 15), (8, 13), (9, 10), (10, 15), (11, 13), (12, 15),
    ),
    "JOLTS (вакансии)": (
        (1, 7), (2, 5), (3, 13), (3, 31), (5, 5), (6, 2),
        (6, 30), (8, 4), (9, 1), (9, 29), (11, 3), (12, 1),
    ),
}

# BEA's machine-readable schedule currently publishes these 2026 dates for
# the two releases that most directly affect index/rates futures.
_BEA_2026: Dict[str, Sequence[Tuple[int, int]]] = {
    "GDP (ВВП)": (
        (1, 22), (2, 20), (3, 13), (4, 9), (4, 30), (5, 28),
        (6, 25), (7, 30), (8, 26), (9, 30), (10, 29), (11, 25), (12, 23),
    ),
    "PCE / Personal Income": (
        (1, 22), (2, 20), (3, 13), (4, 9), (4, 30), (5, 28),
        (6, 25), (7, 30), (8, 26), (9, 30), (10, 29), (11, 25), (12, 23),
    ),
}

# Census principal economic indicator: Advance Monthly Retail Sales, 08:30 ET.
_RETAIL_SALES_2026: Sequence[Tuple[int, int]] = (
    (1, 15), (2, 17), (3, 16), (4, 16), (5, 14), (6, 17),
    (7, 16), (8, 14), (9, 16), (10, 15), (11, 17), (12, 16),
)

# EIA holiday weeks where the normal Wednesday 10:30 ET release moves.
_EIA_EXCEPTIONS_2026: Dict[date, Tuple[date, time]] = {
    date(2026, 1, 21): (date(2026, 1, 22), time(12, 0)),
    date(2026, 2, 18): (date(2026, 2, 19), time(12, 0)),
    date(2026, 5, 27): (date(2026, 5, 28), time(12, 0)),
    date(2026, 9, 9): (date(2026, 9, 10), time(12, 0)),
    date(2026, 10, 14): (date(2026, 10, 15), time(12, 0)),
    date(2026, 11, 11): (date(2026, 11, 12), time(12, 0)),
}


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _et_to_utc(day: date, hhmm: time) -> datetime:
    return datetime.combine(day, hhmm, tzinfo=_ET).astimezone(timezone.utc)


def _make(
    day: date,
    hhmm: time,
    title: str,
    category: str,
    severity: str,
    source: str,
    confirmed: bool,
    *,
    source_url: str = "",
    source_type: str | None = None,
) -> Dict[str, Any]:
    block = {"high": (30, 15), "medium": (15, 10), "low": (5, 5)}.get(severity, (10, 5))
    utc = _et_to_utc(day, hhmm)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_type = source_type or ("official_schedule" if confirmed else "estimated_schedule")
    return {
        "id": f"{day.isoformat()}-{category}-{hhmm.strftime('%H%M')}-{title.split()[0].lower()}",
        "item_type": "calendar_event",
        "title": title,
        "source": source,
        "category": category,
        "severity": severity,
        "impact": severity,
        "instruments": list(_MARKETS.get(category, [])),
        "affected_instruments": list(_MARKETS.get(category, [])),
        "event_time_utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_time_et": utc.astimezone(_ET).strftime("%Y-%m-%d %H:%M ET"),
        "event_time_pt": utc.astimezone(_PT).strftime("%Y-%m-%d %H:%M PT"),
        "published_at_utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_utc": now,
        "block_before_min": block[0],
        "block_after_min": block[1],
        "is_confirmed": bool(confirmed),
        "schedule_status": "confirmed" if confirmed else "estimated",
        "risk_action": "stop_and_review" if confirmed and severity == "high" else "monitor",
        "source_type": source_type,
        "url": source_url,
        "source_url": source_url,
        "summary": (
            "Дата и время опубликованы официальным источником."
            if confirmed else
            "Оценка по стандартному расписанию; проверьте источник перед торговым решением."
        ),
    }


def _in_range(day: date, start: date, end: date) -> bool:
    return start <= day <= end


def _weekdays(start: date, end: date, weekday: int) -> List[date]:
    day = start + timedelta(days=(weekday - start.weekday()) % 7)
    out: List[date] = []
    while day <= end:
        out.append(day)
        day += timedelta(days=7)
    return out


def official_events(start: date, end: date) -> List[Dict[str, Any]]:
    """Rows backed by explicitly published agency schedules."""
    out: List[Dict[str, Any]] = []
    for day in sorted(SEEDED_FOMC):
        if _in_range(day, start, end):
            out.append(_make(
                day, time(14, 0), "FOMC: решение по ставке", "central_bank", "high",
                "Federal Reserve", True, source_url=FED_URL,
            ))

    if start.year <= 2026 <= end.year:
        for title, dates in _BLS_2026.items():
            category = "inflation" if title.startswith(("CPI", "PPI")) else "labor"
            severity = "medium" if title.startswith("JOLTS") else "high"
            for month, day_num in dates:
                day = date(2026, month, day_num)
                if _in_range(day, start, end):
                    out.append(_make(
                        day, time(10, 0) if title.startswith("JOLTS") else time(8, 30),
                        title, category, severity, "BLS", True, source_url=BLS_URLS[title],
                    ))

        for title, dates in _BEA_2026.items():
            category = "growth" if title.startswith("GDP") else "inflation"
            for month, day_num in dates:
                day = date(2026, month, day_num)
                if _in_range(day, start, end):
                    out.append(_make(
                        day, time(8, 30), title, category, "high", "BEA", True,
                        source_url=BEA_URL,
                    ))

        for month, day_num in _RETAIL_SALES_2026:
            day = date(2026, month, day_num)
            if _in_range(day, start, end):
                out.append(_make(
                    day, time(8, 30), "Retail Sales (розничные продажи)", "growth", "high",
                    "U.S. Census Bureau", True, source_url=CENSUS_URL,
                ))
    return out


def standard_schedule_events(start: date, end: date) -> List[Dict[str, Any]]:
    """Recurring weekly releases; trust is explicit per source."""
    out: List[Dict[str, Any]] = []
    for thu in _weekdays(start, end, THURSDAY):
        out.append(_make(
            thu, time(8, 30), "Initial Jobless Claims (заявки)", "labor", "medium",
            "U.S. Department of Labor", False, source_url=DOL_URL,
        ))

    for wed in _weekdays(start, end, WEDNESDAY):
        release_day, release_time = (wed, time(10, 30))
        if wed.year == 2026 and wed in _EIA_EXCEPTIONS_2026:
            release_day, release_time = _EIA_EXCEPTIONS_2026[wed]
        if _in_range(release_day, start, end):
            out.append(_make(
                release_day, release_time, "EIA Weekly Petroleum Status", "energy", "medium",
                "EIA", True, source_url=EIA_URL, source_type="official_standard_schedule",
            ))
    return out


# Kept as a public provider seam for tests and future official adapters.
PROVIDERS: List[Callable[[date, date], List[Dict[str, Any]]]] = [
    official_events,
    standard_schedule_events,
]


def generated_events(start: date, end: date) -> List[Dict[str, Any]]:
    """Backward-compatible alias for the complete scheduled event set."""
    rows: List[Dict[str, Any]] = []
    for provider in PROVIDERS:
        rows.extend(provider(start, end))
    return rows


def build_calendar(days_back: int = 2, days_ahead: int = 60) -> List[Dict[str, Any]]:
    """Aggregate providers; confirmed events win if an id collides."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(0, days_back))
    end = today + timedelta(days=max(1, days_ahead))
    by_id: Dict[str, Dict[str, Any]] = {}
    for provider in PROVIDERS:
        for event in provider(start, end):
            current = by_id.get(event["id"])
            if current is None or (event.get("is_confirmed") and not current.get("is_confirmed")):
                by_id[event["id"]] = event
    return sorted(by_id.values(), key=lambda row: (row["event_time_utc"], row["title"]))


def _atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def write_news_json(days_back: int = 2, days_ahead: int = 60) -> Path:
    path = _root() / "data" / "integrations" / "news.json"
    rows = build_calendar(days_back, days_ahead)
    doc = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "calendar_kind": "official_and_explicit_estimates",
        "items": rows,
        "sources": sorted({row["source"] for row in rows}),
    }
    _atomic_json(path, doc)
    return path


if __name__ == "__main__":
    written = write_news_json()
    print(f"wrote {written}")
