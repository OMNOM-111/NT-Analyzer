"""Item 9: Monitoring KPIs, Subscriptions placement, Owner Journal.

The Journal had the right filters and no shape: three hundred rows in one
column, each repeating a full timestamp, so "what happened yesterday evening"
meant reading every line. Monitoring showed three counters, two of which are
the same number most of the time, and none of which answered the question an
operator actually opens the page with.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "aurora" / "assets" / "theme.css").read_text(encoding="utf-8")
SERVER = (ROOT / "app" / "server.py").read_text(encoding="utf-8")


def _fn(name: str, end: str) -> str:
    start = UI.index(name)
    return UI[start:UI.index(end, start)]


# --------------------------------------------------------------------------- #
# Owner Journal: a filterable timeline.
# --------------------------------------------------------------------------- #
def test_the_journal_groups_entries_by_day():
    assert "function journalTimelineHtml" in UI
    source = _fn("function journalTimelineHtml", "async function renderJournalInto")
    assert "byDay" in source and "jday" in source


def test_a_journal_row_shows_a_time_not_a_full_timestamp():
    """The day heading carries the date. Repeating it on every row is what made
    the list read as an undifferentiated wall."""
    source = _fn("function journalRowHtml", "function journalTimelineHtml")
    assert "jrow-time" in source
    assert "shortDt" not in source, "the date belongs to the day heading"


def test_the_journal_keeps_all_three_filters():
    source = _fn("async function renderJournalInto", "function wireCabinetHeader")
    for control in ("jr-cat", "jr-q", "jr-sus"):
        assert control in source
    assert "JOURNAL_STATE.category" in source
    assert "JOURNAL_STATE.suspicious" in source


def test_the_journal_says_how_many_entries_are_shown():
    source = _fn("async function renderJournalInto", "function wireCabinetHeader")
    assert "Показано записей" in source
    assert "с учётом фильтров" in source


def test_a_flagged_day_is_countable_without_reading_it():
    source = _fn("function journalTimelineHtml", "async function renderJournalInto")
    assert "flagged" in source and "внимание" in source


def test_an_empty_result_is_stated_rather_than_blank():
    source = _fn("function journalTimelineHtml", "async function renderJournalInto")
    assert "Записей нет" in source


def test_the_timeline_has_a_visual_spine():
    assert ".jtimeline" in CSS
    assert ".jday-rows" in CSS
    assert ".jrow::before" in CSS, "each entry needs its marker on the spine"
    assert ".jrow-warn::before" in CSS, "a flagged entry must stand out on it"


# --------------------------------------------------------------------------- #
# Monitoring KPIs.
# --------------------------------------------------------------------------- #
def test_every_kpi_says_what_it_is_out_of():
    """A bare number makes the reader guess the denominator."""
    source = _fn("async function renderMonitoringInto", "async function renderConnectorsInto")
    assert source.count("kpi-sub") >= 4
    assert ".kpi-sub" in CSS


def test_the_attention_kpi_is_named_for_the_question_it_answers():
    source = _fn("async function renderMonitoringInto", "async function renderConnectorsInto")
    assert "Требуют внимания" in source
    assert "kpi-warn" in source and ".kpi-warn" in CSS


def test_monitoring_reports_impersonation_and_account_spread():
    source = _fn("async function renderMonitoringInto", "async function renderConnectorsInto")
    assert "impersonating" in source
    assert "accountsWithSession" in source
    assert "Аккаунтов с сессией" in source


def test_the_derived_counts_come_from_the_page_data():
    """Not from a second endpoint: another source for the same facts is another
    thing to keep in step."""
    source = _fn("async function renderMonitoringInto", "async function renderConnectorsInto")
    assert "sessions.filter(s => s.impersonating)" in source
    assert "new Set(sessions.map" in source


# --------------------------------------------------------------------------- #
# Subscriptions placement.
# --------------------------------------------------------------------------- #
def test_the_cabinet_uses_the_self_service_plans_endpoint():
    """/api/owner/plans returns the same list behind an owner gate, so the old
    branch bought nothing and put an owner-scoped call in a personal surface."""
    source = _fn("async function renderPlansInto", "function buildPlanOptions")
    assert "API.http.billingPlans()" in source
    assert "API.http.ownerPlans()" not in source


def test_subscription_management_stays_in_the_admin_panel():
    """Read the registry, not its formatting: an entry that wraps onto a second
    line is the same entry."""
    from app import server as server_mod

    assert "moduleId === 'subscriptions'" in UI
    entry = next(m for m in server_mod._ADMIN_MODULES if m["id"] == "subscriptions")
    assert entry.get("owner_only") is True


def test_the_cabinet_has_no_subscription_management_controls():
    cabinet = _fn("function renderCabinet", "async function renderAiRatingsInto")
    for admin_only in ("['subscriptions',", "['users',", "['monitoring',", "['journal',"):
        assert admin_only not in cabinet
    # Deciding what a plan grants is an administrative act. The owner opening
    # their own cabinet should see their account, not the switchboard for
    # everyone's, so the cabinet asks for the self scope explicitly.
    assert "renderPlansInto(cb, me, 'self')" in cabinet
