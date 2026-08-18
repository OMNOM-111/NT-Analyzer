"""The journal answers "what happened, and when" -- so it needs a when.

Without a period filter the journal returned the newest 300 events, which on a
quiet week is a month of history and on a busy day is the last hour. The same
control meant two different things depending on when it was read, and a capped
list that says nothing about being capped reads as "this is everything".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import admin_journal


def _stamp(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def test_a_period_bounds_the_window():
    floor = admin_journal._period_floor("7d")
    assert floor
    assert floor < _stamp(6)
    assert floor > _stamp(8)


def test_all_means_no_bound():
    assert admin_journal._period_floor("all") == ""


def test_an_unknown_period_does_not_silently_hide_history():
    """A typo in the query string must not quietly narrow the window; falling
    back to no bound shows more, never less."""
    assert admin_journal._period_floor("last-tuesday") == ""
    assert admin_journal._period_floor("") == ""


def test_today_is_narrower_than_a_week():
    assert admin_journal._period_floor("today") > admin_journal._period_floor("7d")


def test_the_reader_is_told_which_periods_exist():
    out = admin_journal.read_journal(limit=1, period="7d")
    ids = {p["id"] for p in out["periods"]}
    assert {"today", "7d", "30d", "all"} <= ids
    assert all(p["label"] for p in out["periods"])
    assert out["period"] == "7d"


def test_a_capped_list_says_it_is_capped():
    """A list cut off at the limit and presented as complete is how a reader
    concludes nothing happened."""
    out = admin_journal.read_journal(limit=1)
    assert "truncated" in out
    assert out["truncated"] == (out["count"] >= 1)


def test_the_period_reaches_the_endpoint():
    """The handler must forward it; a filter the UI sends and the server drops
    looks like the filter does not work."""
    from pathlib import Path

    source = (Path(admin_journal.__file__).parent / "server.py").read_text(encoding="utf-8")
    block = source[source.index('if path == "/api/owner/journal":'):]
    block = block[:block.index("return")]
    assert 'period=(qs.get("period")' in block
