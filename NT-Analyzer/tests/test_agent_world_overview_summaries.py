"""The overview's brief of every view: what it counts and whom it shows the Lab to."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ai_control_center import overview_summaries
from app.ai_control_center.states import ContractError
from app.ai_lab import registry


def iso(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat().replace("+00:00", "Z")


def authorized(owner=True, runtime=True, role="owner"):
    return {"chat_scope": {"is_owner": owner, "uses_owner_runtime": runtime, "membership_role": role}}


@pytest.fixture
def domains(monkeypatch):
    lists = {"memory": [], "models": []}
    reads = []

    def list_domain(auth, domain, *, identity, limit, cursor):
        reads.append((domain, limit))
        value = lists[domain]
        if isinstance(value, Exception):
            raise value
        return {"items": value, "next_cursor": None}

    monkeypatch.setattr(overview_summaries.domain_gateway, "list_domain", list_domain)
    monkeypatch.setattr(registry, "list_experiments", lambda: [])
    return lists, reads


def test_memory_counts_only_live_records_and_lists_lessons_first(domains):
    lists, _ = domains
    lists["memory"] = [
        {"id": "a", "title": "Old lesson", "memory_class": "verified_lesson", "status": "active", "created_at": iso(days=3),
         "scope_binding": {"strategy_project_id": "S-1"}, "source_ids": ["x"], "provenance": [{"artifact_id": "y"}]},
        {"id": "b", "title": "Fresh lesson", "memory_class": "verified_lesson", "status": "active", "created_at": iso(hours=1),
         "scope_binding": {"strategy_project_id": "S-2"}, "source_ids": ["x"]},
        {"id": "c", "title": "Fresh note", "memory_class": "working", "status": "draft", "created_at": iso(hours=2)},
        {"id": "d", "title": "Revoked", "memory_class": "verified_lesson", "status": "revoked", "created_at": iso(hours=1),
         "scope_binding": {"strategy_project_id": "S-3"}, "source_ids": ["z"]},
    ]
    memory = overview_summaries.build(authorized())["memory"]
    assert memory["records"] == 3 and memory["records_day"] == 2
    assert memory["verified_lessons"] == 2 and memory["lessons_day"] == 1
    # Strategies and sources come only from memory agents still read.
    assert memory["strategies"] == 2 and memory["sources"] == 2
    assert [item["id"] for item in memory["latest"]] == ["b", "a"]
    assert memory["capped"] is False


def test_research_totals_are_the_owners_lab_only(domains):
    for scope in [authorized(owner=False), authorized(runtime=False), authorized(role="member")]:
        assert overview_summaries.build(scope)["research"] == {"unavailable": "owner_lab_only"}


def test_research_week_deltas_follow_creation_and_status_changes(domains, monkeypatch):
    monkeypatch.setattr(registry, "list_experiments", lambda: [
        {"status": "sandbox_candidate", "created_at_utc": iso(days=2), "updated_at_utc": iso(days=1)},
        {"status": "portfolio_contributor", "created_at_utc": iso(days=40), "updated_at_utc": iso(days=30)},
        {"status": "champion_candidate", "created_at_utc": iso(days=20), "updated_at_utc": iso(days=3)},
        {"status": "archived", "created_at_utc": iso(days=50), "updated_at_utc": iso(days=45)},
        {"status": "rejected", "created_at_utc": iso(days=1), "updated_at_utc": iso(days=1)},
    ])
    research = overview_summaries.build(authorized())["research"]
    assert research == {"experiments": 5, "experiments_week": 2, "candidates": 2, "candidates_week": 1,
                        "champions": 1, "champions_week": 1, "archived": 1, "archived_week": 0, "rejected": 1}


def test_an_unreadable_block_is_reported_without_hiding_the_others(domains):
    lists, _ = domains
    lists["memory"] = ContractError("memory_disabled")
    lists["models"] = [{"model": "deepseek-v4-flash", "provider": "deepseek", "status": "active"},
                       {"model": "deepseek-v4-flash", "provider": "deepseek", "status": "disabled"}]
    summaries = overview_summaries.build(authorized())
    assert summaries["memory"] == {"unavailable": "memory_disabled"}
    assert summaries["models"] == {"items": [{"model": "deepseek-v4-flash", "provider": "deepseek", "connections": 2, "active": 1}]}


def test_each_block_reads_one_bounded_page(domains):
    _, reads = domains
    overview_summaries.build(authorized())
    assert sorted(reads) == [("memory", overview_summaries.READ_LIMIT), ("models", overview_summaries.READ_LIMIT)]
