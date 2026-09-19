"""The overview's brief of every view: what it counts and whom it shows the Lab to."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ai_control_center import overview_summaries
from app.ai_control_center.states import ContractError
from app.ai_lab import agent_registry, knowledge_base, registry, research_catalog


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
    monkeypatch.setattr(research_catalog, "list_researches", lambda: {"researches": []})
    monkeypatch.setattr(knowledge_base, "brief", lambda: {"fragments": 0})
    monkeypatch.setattr(agent_registry, "list_agents", lambda: [])
    monkeypatch.setattr(agent_registry, "usage_rows", lambda limit: [])
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
        built = overview_summaries.build(scope)
        for block in ("research", "knowledge", "lab_models"):
            assert built[block] == {"unavailable": "owner_lab_only"}


def test_research_week_deltas_follow_creation_and_status_changes(domains, monkeypatch):
    monkeypatch.setattr(registry, "list_experiments", lambda: [
        {"status": "sandbox_candidate", "created_at_utc": iso(days=2), "updated_at_utc": iso(days=1)},
        {"status": "portfolio_contributor", "created_at_utc": iso(days=40), "updated_at_utc": iso(days=30)},
        {"status": "champion_candidate", "created_at_utc": iso(days=20), "updated_at_utc": iso(days=3)},
        {"status": "archived", "created_at_utc": iso(days=50), "updated_at_utc": iso(days=45)},
        {"status": "rejected", "created_at_utc": iso(days=1), "updated_at_utc": iso(days=1)},
    ])
    research = overview_summaries.build(authorized())["research"]
    assert research == {"researches": 0, "experiments": 5, "experiments_week": 2, "candidates": 2, "candidates_week": 1,
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


def test_strategies_developed_before_the_registry_count_in_the_research_tiles(domains, monkeypatch):
    monkeypatch.setattr(research_catalog, "list_researches", lambda: {"researches": [
        {"evaluation": {"linked_strategy_profiles": 6, "working_strategies": 2, "archived_strategies": 4}},
        {"evaluation": {"linked_strategy_profiles": 1, "working_strategies": 1, "archived_strategies": 0}}]})
    research = overview_summaries.build(authorized())["research"]
    assert (research["researches"], research["experiments"], research["candidates"], research["archived"]) == (2, 7, 3, 4)
    assert research["experiments_week"] == 0


def test_model_roster_carries_usage_by_role_and_never_a_secret(domains, monkeypatch):
    monkeypatch.setattr(agent_registry, "list_agents", lambda: [
        {"id": "AGT-1", "name": "DeepSeek", "provider": "deepseek", "model": "deepseek-v4-pro", "enabled": True,
         "monthly_budget_usd": 5.0, "spend_month_usd": 0.5, "key_mask": "sk-****", "last_test": {"ok": True}},
        {"id": "AGT-2", "name": "Idle", "provider": "gemini", "model": "gemini-2.5-flash", "enabled": False}])
    monkeypatch.setattr(agent_registry, "usage_rows", lambda limit: [
        {"agent_id": "AGT-1", "role": "orchestrator", "status": "success", "cost_usd": 0.01, "total_tokens": 100, "timestamp_utc": iso(hours=2)},
        {"agent_id": "AGT-1", "role": "orchestrator", "status": "error", "cost_usd": 0, "total_tokens": 0, "timestamp_utc": iso(hours=1)},
        {"agent_id": "AGT-1", "role": "coder", "status": "success", "cost_usd": 0.02, "total_tokens": 50, "timestamp_utc": iso(minutes=5)}])
    items = overview_summaries.build(authorized())["lab_models"]["items"]
    first = items[0]
    assert [item["id"] for item in items] == ["AGT-1", "AGT-2"]
    assert (first["requests"], first["ok"], first["errors"], first["tokens"]) == (3, 2, 1, 150)
    assert [(row["role"], row["requests"], row["ok"]) for row in first["by_role"]] == [("orchestrator", 2, 1), ("coder", 1, 1)]
    assert first["recent"][0]["role"] == "coder" and first["last_test_ok"] is True
    assert "key_mask" not in first and "api_key" not in str(items)
