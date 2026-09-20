"""The strategy-development knowledge base as fragments the AI Center can show."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai_lab import knowledge, knowledge_base, paths


@pytest.fixture
def lab(tmp_path, monkeypatch):
    data = tmp_path / "data" / "ai_lab"
    code = tmp_path / "checkout" / "NT-Analyzer"
    reference = code / "ai_lab" / "reference_strategies"
    monkeypatch.setattr(paths, "MUTABLE_AI_LAB_DIR", data)
    monkeypatch.setattr(paths, "PROJECT_ROOT", code)
    monkeypatch.setattr(paths, "REFERENCE_STRATEGIES_DIR", reference)
    monkeypatch.setattr(paths, "USER_RESEARCH_DIR", data / "user_research")
    monkeypatch.setattr(paths, "LESSON_LOG_PATH", data / "registry" / "lesson_log.jsonl")
    knowledge_base._cache.update(key=None, value=None)
    rules = data / "strategy_rules"
    rules.mkdir(parents=True)
    (rules / "Общие правила разработки стратегий.md").write_text(
        "# Общие правила разработки стратегий\n\nВступление.\n\n## Комиссии\n- RoundTurnCommission >= 1.90\n\n## Promotion gates\nPF >= 1.35\n",
        encoding="utf-8")
    (reference / "ai_lessons").mkdir(parents=True)
    (reference / "ai_lessons" / "FAILED_CELL_LESSONS.md").write_text("# Failed\n\n## Purpose\nskip\n\n## AI-CELL-004 Lessons\nToo many trades.\n", encoding="utf-8")
    (reference / "ai_lessons" / "LESSONS_SUMMARY.md").write_text(
        "# Summary\n\n## CRITICAL READ BEFORE ANY AI-CELL GENERATION\nRead all.\n\n## 1. The Commission Economics Law\n**RULE:** gross >= $5\n", encoding="utf-8")
    (reference / "REF-001").mkdir()
    (reference / "REF-001" / "normalized_spec.md").write_text("# Normalized Spec: REF-001 — SMA Crossover\n\n## Hypothesis\nMomentum shifts.\n", encoding="utf-8")
    (data / "user_research" / "curated" / "researches").mkdir(parents=True)
    (data / "user_research" / "curated" / "researches" / "RES-1.md").write_text("# MGC B1\n\n## AI metadata\n- id\n\n## Краткий вывод\n6 профилей.\n", encoding="utf-8")
    (data / "registry").mkdir(parents=True)
    (data / "registry" / "lesson_log.jsonl").write_text(json.dumps({"lesson_id": "LSN-1", "summary": "Не торговать новости", "timestamp_utc": "2026-09-18T10:00:00Z"}, ensure_ascii=False) + "\n", encoding="utf-8")
    yield tmp_path
    knowledge_base._cache.update(key=None, value=None)


def test_documents_become_section_fragments_by_kind(lab):
    value = knowledge_base.snapshot()
    kinds = {item["id"]: item["kind"] for item in value["items"]}
    assert (value["rules"], value["registry"], value["lessons"], value["references"], value["materials"]) == (2, 0, 3, 1, 1)
    titles = [item["title"] for item in value["items"]]
    assert "Комиссии" in titles and "Promotion gates" in titles and "REF-001 — SMA Crossover" in titles
    # Service sections are not knowledge of their own.
    assert "Purpose" not in titles and "CRITICAL READ BEFORE ANY AI-CELL GENERATION" not in titles
    material = next(item for item in value["items"] if item["kind"] == "data")
    assert material["summary"] == "6 профилей." and "lesson_log:LSN-1" in kinds


def test_brief_leads_with_the_newest_logged_lesson_then_the_summary(lab):
    brief = knowledge_base.brief()
    assert [item["title"] for item in brief["latest"]] == ["Не торговать новости", "1. The Commission Economics Law", "AI-CELL-004 Lessons"]
    assert brief["rules_found"] is True and "items" not in brief


def test_the_lab_reads_the_rules_from_the_data_root_in_a_worktree(lab):
    # A worktree has no «РАЗРАБОТКА СТРАТЕГИЙ» folder next to the checkout.
    found = [path.name for path in knowledge._project_docs()]
    assert "Общие правила разработки стратегий.md" in found


def test_a_changed_file_is_read_again(lab):
    first = knowledge_base.snapshot()["registry"]
    rules = Path(paths.MUTABLE_AI_LAB_DIR) / "strategy_rules" / "Реестр стратегий.md"
    rules.write_text("# Реестр\n\n## Готовые стратегии\nMNQ v1.\n", encoding="utf-8")
    # The registry of the owner's strategies is its own kind, not a rule.
    assert knowledge_base.snapshot()["registry"] == first + 1


def test_the_owners_documents_are_found_beside_their_data_not_only_beside_the_code(tmp_path, monkeypatch):
    """Local runs from a worktree; the owner's documents live next to their data."""
    data = tmp_path / "Анализатор стратегий NinjaTrader" / "NT-Analyzer" / "data"
    (data / "ai_lab").mkdir(parents=True)
    docs = tmp_path / "Анализатор стратегий NinjaTrader" / "РАЗРАБОТКА СТРАТЕГИЙ"
    docs.mkdir()
    (docs / "Общие правила.md").write_text("# Правила\n\n## Комиссии\nRTC >= 1.90\n", encoding="utf-8")
    monkeypatch.setattr(paths, "MUTABLE_AI_LAB_DIR", data / "ai_lab")
    # The checkout is somewhere else entirely, as a worktree is.
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path / "StratForge-worktrees" / "runtime" / "NT-Analyzer")
    assert [path.name for path in knowledge_base.strategy_rules_dirs()] == ["РАЗРАБОТКА СТРАТЕГИЙ"]


def test_the_owners_own_reports_are_part_of_the_memory(lab):
    reports = Path(paths.MUTABLE_AI_LAB_DIR) / "registry" / "chief_reports"
    (reports / "workspaces" / "ws_owner").mkdir(parents=True)
    (reports / "daily-2026-08-04.json").write_text(json.dumps(
        {"report_id": "R-1", "period": "day", "generated_at_utc": "2026-08-04T23:00:00Z",
         "content": "Отчёт владельца за день. PnL -81.3, сделок 19."}, ensure_ascii=False), encoding="utf-8")
    (reports / "workspaces" / "ws_owner" / "week-2026-08-08.json").write_text(json.dumps(
        {"report_id": "R-2", "period": "week", "generated_at_utc": "2026-08-08T23:00:00Z",
         "content": "Отчёт за неделю: три стратегии на проверке."}, ensure_ascii=False), encoding="utf-8")
    knowledge_base._cache.update(key=None, value=None)
    snapshot = knowledge_base.snapshot()
    assert snapshot["reports"] == 2
    kept = [item for item in snapshot["items"] if item["kind"] == knowledge_base.REPORT]
    assert {item["title"] for item in kept} == {"Отчёт за день 2026-08-04", "Отчёт за неделю 2026-08-08"}
    assert "PnL" in next(item["summary"] for item in kept if "день" in item["title"])
    # They count as memory the owner can see, not as history that vanished.
    assert snapshot["documents"] >= 2 and knowledge_base.brief()["reports"] == 2
