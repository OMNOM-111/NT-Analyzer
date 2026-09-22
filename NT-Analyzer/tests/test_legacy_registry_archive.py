"""The old registry becomes a read-only archive, and only facts migrate out of it."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.ai_control_center import legacy_migration
from app.ai_lab import legacy_archive


@pytest.fixture
def data(monkeypatch, tmp_path):
    """A data root shaped like the owner's: registry, usage log, ratings."""
    root = tmp_path / "data"
    (root / "integrations").mkdir(parents=True)
    (root / "ai_lab" / "registry" / "agent_usage").mkdir(parents=True)
    (root / "integrations" / "ai_agents.registry.json").write_text(json.dumps({
        "schema_version": "1.1", "updated_at_utc": "2026-09-18T23:25:23Z", "agents": [
            {"id": "AGT-1", "name": "Azure gpt-5-mini", "provider": "azure_foundry", "model": "gpt-5-mini",
             "role": "coder", "purpose": "Coder", "priority": 10, "rotation_group": "azure-critical",
             "enabled": True, "input_price_usd_per_m": 0.25, "output_price_usd_per_m": 2.0,
             "daily_budget_usd": 1.0, "monthly_budget_usd": 5.0, "billing_mode": "credit",
             "created_at_utc": "2026-07-01T04:39:53Z"},
            {"id": "AGT-2", "name": "DeepSeek Critical", "provider": "deepseek", "model": "deepseek-v4-pro",
             "role": "orchestrator", "purpose": "Orchestrator", "priority": 5, "rotation_group": "deepseek-paid",
             "enabled": True, "billing_mode": "payg", "created_at_utc": "2026-07-02T04:39:53Z"},
        ]}, ensure_ascii=False), encoding="utf-8")
    usage = [
        {"timestamp_utc": "2026-09-01T00:49:45Z", "request_id": "REQ-1", "agent_id": "AGT-2", "agent_name": "DeepSeek Critical",
         "provider": "deepseek", "model": "deepseek-v4-pro", "role": "orchestrator", "request_role": "orchestrator",
         "purpose": "month_report", "status": "success", "total_tokens": 3325, "cost_usd": 0.0025, "elapsed_sec": 46.6},
        {"timestamp_utc": "2026-09-01T01:42:10Z", "request_id": "REQ-2", "agent_id": "AGT-2", "agent_name": "DeepSeek Critical",
         "provider": "deepseek", "model": "deepseek-v4-pro", "role": "orchestrator", "request_role": "compile_error_fixer",
         "purpose": "job_failed", "status": "error", "error": "timeout", "total_tokens": 10, "cost_usd": 0.001},
        {"timestamp_utc": "2026-08-02T01:42:10Z", "request_id": "REQ-3", "agent_id": "AGT-GONE", "agent_name": "Удалённая модель",
         "provider": "openrouter", "model": "old-model", "role": "general", "status": "success", "cost_usd": 0.0},
    ]
    (root / "ai_lab" / "registry" / "agent_usage" / "2026-09.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in usage) + "\n", encoding="utf-8")
    (root / "ai_lab" / "registry" / "star_ratings.json").write_text(json.dumps({
        "version": 2, "model_stats": {
            "Azure gpt-5-mini": {"provider": "azure_foundry", "count": 4, "avg": 4.5, "sum": 18.0},
            "Chief agent / deterministic": {"provider": "local", "count": 116, "avg": 3.0, "sum": 348.0}},
        "role_model_stats": {}, "events": []}, ensure_ascii=False), encoding="utf-8")

    stub = SimpleNamespace(data_path=lambda *parts, project_root=None: root.joinpath(*[str(part) for part in parts]))
    monkeypatch.setattr(legacy_archive, "runtime_env", stub)
    monkeypatch.setattr(legacy_migration, "runtime_env", stub)
    return root


def test_freezing_copies_the_old_registry_and_leaves_it_untouched(data):
    before = (data / "integrations" / "ai_agents.registry.json").read_bytes()
    manifest = legacy_archive.freeze(note="перевод в архив")
    assert manifest["read_only"] is True and manifest["totals"]["files"] == 3
    assert (data / "integrations" / "ai_agents.registry.json").read_bytes() == before
    # The archive holds the agents, the month of usage and the ratings.
    assert {entry["source"] for entry in manifest["files"]} == {"registry", "usage", "ratings"}
    assert legacy_archive.verify(manifest["archive_id"])["ok"] is True
    assert len(legacy_archive.agents(manifest["archive_id"])) == 2


def test_a_changed_archive_is_reported_rather_than_trusted(data):
    manifest = legacy_archive.freeze()
    target = legacy_archive.path_of(manifest["archive_id"], "files", "ratings", "star_ratings.json")
    target.write_text("{}", encoding="utf-8")
    checked = legacy_archive.verify(manifest["archive_id"])
    assert checked["ok"] is False and checked["drift"][0]["problem"] == "changed"


def test_a_source_carrying_a_secret_is_refused(data):
    (data / "integrations" / "ai_agents.registry.json").write_text(
        json.dumps({"agents": [{"id": "AGT-1", "api_key": "sk-abcdefghijklmnop0123456789"}]}), encoding="utf-8")
    with pytest.raises(legacy_archive.ArchiveError):
        legacy_archive.freeze()


def test_models_migrate_without_a_position_or_a_routing_rule(data):
    legacy_archive.freeze()
    legacy_migration.migrate()
    models = legacy_migration.models()
    assert len(models) == 2
    for model in models:
        assert model["role"] is None
        assert not {"purpose", "priority", "rotation_group", "enabled", "daily_budget_usd",
                    "monthly_budget_usd", "team_role"} & set(model)
    # The facts that are facts do cross over.
    azure = next(model for model in models if model["name"] == "Azure gpt-5-mini")
    assert azure["provider"] == "azure_foundry" and azure["input_price_usd_per_m"] == 0.25


def test_old_role_links_survive_only_as_history(data):
    legacy_archive.freeze()
    legacy_migration.migrate()
    links = legacy_migration.provenance()
    orchestrator = next(link for link in links if link["legacy_role"] == "orchestrator")
    assert orchestrator["requests"] == 2 and orchestrator["ok"] == 1
    assert orchestrator["kind"] == "historical_provenance" and orchestrator["active"] is False


def test_every_logged_call_is_kept_including_one_whose_model_is_gone(data):
    legacy_archive.freeze()
    summary = legacy_migration.migrate()
    assert summary["history"] == 3
    rows = legacy_migration.history()
    orphan = next(row for row in rows if row["legacy_agent_id"] == "AGT-GONE")
    assert orphan["orphan"] is True and orphan["model_key"] is None
    assert orphan["cost_usd"] == 0.0 and orphan["legacy_role"] == "general"


def test_a_rating_whose_model_cannot_be_named_stays_in_the_archive(data):
    legacy_archive.freeze()
    legacy_migration.migrate()
    document = json.loads((legacy_migration.registry_dir() / "ratings.json").read_text(encoding="utf-8"))
    assert [row["model_name_at_the_time"] for row in document["ratings"]] == ["Azure gpt-5-mini"]
    refused = document["not_migrated"][0]
    assert refused["model_name_at_the_time"] == "Chief agent / deterministic" and refused["reason"]


def test_the_new_registry_becomes_authoritative_only_after_reconciliation(data):
    legacy_archive.freeze()
    assert legacy_migration.state()["authoritative"] is False
    legacy_migration.migrate()
    assert legacy_migration.state()["authoritative"] is False
    report = legacy_migration.reconcile()
    assert report["ok"] is True
    assert report["archive"]["agents"] == 2 and report["archive"]["unique_requests"] == 3
    assert report["migrated_as_history"] == {"models": 2, "calls": 3, "provenance_links": 2, "ratings": 1}
    assert report["new_entities"]["agent_roles_created"] == 0 and report["new_entities"]["model_pins_created"] == 0
    assert report["losses"] == {"models_missing": [], "calls_missing": 0, "orphan_calls": 1}
    assert report["wrong_pins"] == {"models_with_a_position": [], "active_legacy_links": 0}
    assert {row["field"] for row in report["not_migrated_on_purpose"]} >= {"role", "priority", "rotation_group", "api_key"}
    assert legacy_migration.state()["authoritative"] is True


def test_a_migration_that_lost_something_refuses_to_become_authoritative(data):
    legacy_archive.freeze()
    legacy_migration.migrate()
    legacy_migration.reconcile()
    path = legacy_migration.registry_dir() / "models.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["models"] = document["models"][:1]
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    report = legacy_migration.reconcile()
    assert report["ok"] is False and report["losses"]["models_missing"] == ["AGT-2"]
    assert legacy_migration.state()["authoritative"] is False


def test_a_model_pinned_to_a_position_fails_the_reconciliation(data):
    legacy_archive.freeze()
    legacy_migration.migrate()
    path = legacy_migration.registry_dir() / "models.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["models"][0]["role"] = "coder"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    report = legacy_migration.reconcile()
    assert report["ok"] is False and report["wrong_pins"]["models_with_a_position"]


def test_the_archive_is_inert_in_the_running_system():
    """Router, coordinator, rating and execution paths must not read the archive."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    # What matters is who imports the archive module - the word itself is also
    # a label of the memory layer's own read-only history, which is not this.
    import re
    importer = re.compile(r"^\s*(from\s+\S*ai_lab\s+import\s+[^\n]*\blegacy_archive\b"
                          r"|from\s+\S*legacy_archive\s+import|import\s+\S*legacy_archive\b)", re.M)
    readers = {path.relative_to(root).as_posix() for path in root.rglob("*.py")
               if importer.search(path.read_text(encoding="utf-8", errors="replace"))}
    assert readers == {"ai_control_center/legacy_migration.py", "ai_control_center/legacy_view.py"}
