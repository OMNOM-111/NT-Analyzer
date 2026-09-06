"""What the PostgreSQL acceptance suites do and do not cover.

The program record carries a historical "41 PostgreSQL PASS" beside a current
"41 PostgreSQL skipped". Both numbers describe the same four modules, and none
of them touches Agent World: the Agent World repository is SQLite only and no
shipped migration creates an Agent World table. A green PostgreSQL run
therefore proves the Stage 8 control/data plane and the SF Chat relational read
path — never the Agent World schema.

These tests exist so that stops being something a reader has to re-derive, and
so adding a PostgreSQL adapter has to update the statement rather than inherit
somebody else's green run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
MIGRATIONS = ROOT / "app" / "production_storage" / "migrations"

# The four modules gated on STRATFORGE_TEST_POSTGRES_* DSNs, with the case
# count each contributes to the reported total.
POSTGRES_SUITES = {
    "test_production_storage.py": 12,
    "test_production_workers.py": 12,
    "test_sf_chat_relational_postgres.py": 9,
    "test_stage8_postgresql.py": 8,
}
REPORTED_TOTAL = 41

AGENT_WORLD_ENTITIES = ("agent_world", "persona", "court_case", "court_vote",
                        "contribution", "strategy_project", "provider_account")


def _gated_modules() -> set[str]:
    found = set()
    for path in TESTS.glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue  # this module names the DSNs to assert on them
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "STRATFORGE_TEST_POSTGRES" in text and "pytestmark" in text:
            found.add(path.name)
    return found


def test_the_reported_forty_one_are_exactly_these_four_suites():
    assert _gated_modules() == set(POSTGRES_SUITES)
    assert sum(POSTGRES_SUITES.values()) == REPORTED_TOTAL


@pytest.mark.parametrize("module", sorted(POSTGRES_SUITES))
def test_each_postgres_suite_declares_its_case_count_here(module):
    """A suite that grows must update the number the program record quotes."""
    text = (TESTS / module).read_text(encoding="utf-8", errors="ignore")
    assert len(re.findall(r"^def test_", text, re.M)) == POSTGRES_SUITES[module]


@pytest.mark.parametrize("module", sorted(POSTGRES_SUITES))
def test_no_postgres_suite_exercises_agent_world(module):
    """The historical 41 PASS says nothing about the Agent World schema."""
    text = (TESTS / module).read_text(encoding="utf-8", errors="ignore")
    assert "ai_control_center" not in text
    assert "AgentWorldRepository" not in text


@pytest.mark.parametrize("module", sorted(POSTGRES_SUITES))
def test_missing_dsns_skip_rather_than_pass(module):
    """A green run that never opened a connection would be worse than a skip."""
    text = (TESTS / module).read_text(encoding="utf-8", errors="ignore")
    assert "pytest.mark.skipif" in text
    assert "STRATFORGE_TEST_POSTGRES_ADMIN_URL" in text
    assert "STRATFORGE_TEST_POSTGRES_URL" in text


def test_no_shipped_migration_creates_an_agent_world_table():
    files = sorted(MIGRATIONS.glob("*.sql"))
    assert len(files) == 22, "migration count changed; re-check the storage statement"
    for path in files:
        statements = re.findall(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z0-9_.\"]+)",
                                path.read_text(encoding="utf-8", errors="ignore"), re.I)
        for table in statements:
            name = table.strip('"').split(".")[-1].lower()
            assert not any(name.startswith(entity) or name == entity
                           for entity in AGENT_WORLD_ENTITIES), f"{path.name}: {table}"


def test_agent_world_has_exactly_one_repository_implementation_and_it_is_sqlite():
    from app.ai_control_center import domain_gateway, sqlite_repository
    assert hasattr(sqlite_repository, "SQLiteAgentWorldRepository")
    source = Path(domain_gateway.__file__).read_text(encoding="utf-8", errors="ignore")
    assert "SQLiteAgentWorldRepository" in source
    # If a PostgreSQL adapter appears, this assertion is the place to say so.
    package = ROOT / "app" / "ai_control_center"
    implementations = {path.name for path in package.glob("*repository*.py")}
    assert implementations == {"sqlite_repository.py"}
