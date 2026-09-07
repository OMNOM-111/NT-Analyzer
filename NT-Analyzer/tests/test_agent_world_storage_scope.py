"""What the PostgreSQL acceptance suites covered **at this reviewed baseline**.

This is a dated snapshot, not a rule. It exists because the program record
carried a historical "41 PostgreSQL PASS" beside a current "41 PostgreSQL
skipped" without saying what either covered, and a reader had to re-derive it.

At the baseline these tests describe, all 41 belong to four suites, none of
which imports `ai_control_center`; no shipped migration creates an Agent World
table; and the Agent World repository is SQLite only. A green PostgreSQL run at
that baseline therefore proved the Stage 8 control/data plane and the SF Chat
relational read path, never the Agent World schema.

**When an Agent World PostgreSQL adapter and schema land, these expectations are
meant to be replaced by checks of the new contract — migrations applied, RLS
policies present and forced, scope rejection, outbox atomicity, idempotency.**
A failure here is a signal to update the statement, never a reason to revert or
withhold the implementation. `BASELINE` records exactly what was verified and
when, so the diff between it and reality is the work to re-describe.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
MIGRATIONS = ROOT / "app" / "production_storage" / "migrations"

BASELINE = {
    "described_on": "2026-09-06",
    "reviewed_from": "45ab4361d5ab9b8422ec049c0c689953d548a318",
    "shipped_migrations": 22,
    "agent_world_repositories": {"sqlite_repository.py"},
    "note": "Snapshot of the reviewed baseline. Replace with new-contract checks "
            "when an Agent World PostgreSQL adapter lands; do not treat as a ban.",
}

# The four modules gated on STRATFORGE_TEST_POSTGRES_* DSNs, with the case
# count each contributed to the reported total at this baseline.
POSTGRES_SUITES = {
    "test_production_storage.py": 12,
    "test_production_workers.py": 12,
    "test_sf_chat_relational_postgres.py": 9,
    "test_stage8_postgresql.py": 8,
}
REPORTED_TOTAL = 41

AGENT_WORLD_ENTITIES = ("agent_world", "persona", "court_case", "court_vote",
                        "contribution", "strategy_project", "provider_account")

REPLACE = ("\n\nThis is the reviewed-baseline snapshot in {file}. If an Agent World "
           "PostgreSQL adapter or schema has landed, replace this expectation with "
           "checks of the new contract rather than reverting the implementation.").format(
    file=Path(__file__).name)


def _gated_modules() -> set[str]:
    found = set()
    for path in TESTS.glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue  # this module names the DSNs in order to assert on them
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "STRATFORGE_TEST_POSTGRES" in text and "pytestmark" in text:
            found.add(path.name)
    return found


def test_the_reported_forty_one_were_exactly_these_four_suites():
    assert _gated_modules() == set(POSTGRES_SUITES), REPLACE
    assert sum(POSTGRES_SUITES.values()) == REPORTED_TOTAL


@pytest.mark.parametrize("module", sorted(POSTGRES_SUITES))
def test_each_postgres_suite_still_declares_its_baseline_case_count(module):
    """A suite that grows must update the number the program record quotes."""
    text = (TESTS / module).read_text(encoding="utf-8", errors="ignore")
    assert len(re.findall(r"^def test_", text, re.M)) == POSTGRES_SUITES[module], REPLACE


@pytest.mark.parametrize("module", sorted(POSTGRES_SUITES))
def test_no_baseline_postgres_suite_exercised_agent_world(module):
    """The historical 41 PASS said nothing about the Agent World schema."""
    text = (TESTS / module).read_text(encoding="utf-8", errors="ignore")
    assert "ai_control_center" not in text, REPLACE
    assert "AgentWorldRepository" not in text, REPLACE


@pytest.mark.parametrize("module", sorted(POSTGRES_SUITES))
def test_missing_dsns_skip_rather_than_pass(module):
    """A green run that never opened a connection would be worse than a skip.

    This one is a standing rule, not a snapshot: it should hold for any future
    PostgreSQL suite too, including an Agent World one.
    """
    text = (TESTS / module).read_text(encoding="utf-8", errors="ignore")
    assert "pytest.mark.skipif" in text
    assert "STRATFORGE_TEST_POSTGRES_ADMIN_URL" in text
    assert "STRATFORGE_TEST_POSTGRES_URL" in text


def test_baseline_shipped_migration_count_is_still_what_was_reviewed():
    files = sorted(MIGRATIONS.glob("*.sql"))
    assert len(files) == BASELINE["shipped_migrations"], (
        f"reviewed baseline had {BASELINE['shipped_migrations']} migrations, found {len(files)}."
        + REPLACE)


def test_no_baseline_migration_created_an_agent_world_table():
    for path in sorted(MIGRATIONS.glob("*.sql")):
        statements = re.findall(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z0-9_.\"]+)",
                                path.read_text(encoding="utf-8", errors="ignore"), re.I)
        for table in statements:
            name = table.strip('"').split(".")[-1].lower()
            assert not any(name.startswith(entity) or name == entity
                           for entity in AGENT_WORLD_ENTITIES), f"{path.name}: {table}" + REPLACE


def test_agent_world_had_one_repository_implementation_at_this_baseline():
    from app.ai_control_center import domain_gateway, sqlite_repository
    assert hasattr(sqlite_repository, "SQLiteAgentWorldRepository")
    source = Path(domain_gateway.__file__).read_text(encoding="utf-8", errors="ignore")
    assert "SQLiteAgentWorldRepository" in source
    package = ROOT / "app" / "ai_control_center"
    implementations = {path.name for path in package.glob("*repository*.py")}
    assert implementations == BASELINE["agent_world_repositories"], REPLACE
