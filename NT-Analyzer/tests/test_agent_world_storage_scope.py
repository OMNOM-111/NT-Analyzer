"""What the PostgreSQL suites cover, before and after the Agent World adapter.

The program record once carried a historical "41 PostgreSQL PASS" beside a
current "41 PostgreSQL skipped" without saying what either covered. That is
recorded here so no reader has to re-derive it.

The pre-integration baseline is kept as history: 41 cases across four suites,
none importing `ai_control_center`, 22 migrations, one SQLite repository. A
green run at that baseline proved the Stage 8 control/data plane and the SF Chat
relational read path — never the Agent World schema.

Integration changed that, and the expectations below now describe the **merged**
contract: migration 0023 creates the Agent World tables with row level security
forced on every one of them, a PostgreSQL repository exists beside the SQLite
one, and Agent World has its own DSN-gated suite whose cases are counted
separately from the original 41. Those cases still skip without a real server,
which is the honest outcome — reading SQL is not executing a migration.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
MIGRATIONS = ROOT / "app" / "production_storage" / "migrations"

# History: what was true before the mechanisms were merged in.
BASELINE = {
    "described_on": "2026-09-06",
    "reviewed_from": "45ab4361d5ab9b8422ec049c0c689953d548a318",
    "shipped_migrations": 22,
    "agent_world_repositories": {"sqlite_repository.py"},
    "postgres_cases": 41,
}

# The merged contract these tests now assert.
MERGED = {
    "shipped_migrations": 23,
    "agent_world_migration": "0023_agent_world_repository.sql",
    "agent_world_repositories": {"sqlite_repository.py", "postgres_repository.py"},
    "agent_world_suite": "test_agent_world_postgres.py",
    # Ten tables, every one with RLS enabled *and* forced.
    "agent_world_tables": ("meta", "records", "revisions", "events", "outbox",
                           "mutations", "inbox", "artifacts", "memory_grants",
                           "memory_grant_anchors"),
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

REPLACE = ("\n\nThis expectation lives in {file}. If the storage contract has moved "
           "again, update the statement to the new contract rather than reverting "
           "the implementation.").format(file=Path(__file__).name)


def _gated_modules() -> set[str]:
    """Suites that refuse to run without a real PostgreSQL.

    The original four gate on STRATFORGE_TEST_POSTGRES_* through pytestmark.
    The Agent World suite gates on its own STRATFORGE_TEST_AGENT_WORLD_POSTGRES_*
    inside a fixture, because it additionally insists the target is a disposable
    loopback database — so both shapes count as gated.
    """
    found = set()
    for path in TESTS.glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue  # this module names the DSNs in order to assert on them
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "STRATFORGE_TEST_POSTGRES" in text and "pytestmark" in text:
            found.add(path.name)
        elif "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW" in text and "pytest.skip" in text:
            found.add(path.name)
    return found


def test_the_original_forty_one_are_still_these_four_suites():
    """Agent World's own suite is counted separately, never folded into the 41."""
    gated = _gated_modules()
    assert set(POSTGRES_SUITES) <= gated, REPLACE
    assert sum(POSTGRES_SUITES.values()) == REPORTED_TOTAL == BASELINE["postgres_cases"]
    assert MERGED["agent_world_suite"] in gated, (
        "the Agent World PostgreSQL suite should be DSN-gated like the others" + REPLACE)
    assert MERGED["agent_world_suite"] not in POSTGRES_SUITES


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


def test_the_agent_world_migration_shipped_and_the_count_moved_with_it():
    files = sorted(MIGRATIONS.glob("*.sql"))
    assert len(files) == MERGED["shipped_migrations"], (
        f"expected {MERGED['shipped_migrations']} migrations, found {len(files)}." + REPLACE)
    assert (MIGRATIONS / MERGED["agent_world_migration"]).is_file(), REPLACE


def test_every_agent_world_table_has_row_level_security_enabled_and_forced():
    """RLS is applied in a loop, so the table list is what has to be asserted."""
    sql = (MIGRATIONS / MERGED["agent_world_migration"]).read_text(encoding="utf-8", errors="ignore")
    created = {name.strip('"').split(".")[-1].lower() for name in re.findall(
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z0-9_.\"]+)", sql, re.I)}
    expected = {"sf_aw_" + suffix for suffix in MERGED["agent_world_tables"]}
    assert expected <= created, sorted(expected - created)

    loop = re.search(r"FOREACH\s+relation\s+IN\s+ARRAY\s+ARRAY\[(.*?)\]", sql, re.S | re.I)
    assert loop, "expected the RLS loop over the Agent World relations" + REPLACE
    covered = {value.strip().strip("'").lower() for value in loop.group(1).split(",")}
    assert set(MERGED["agent_world_tables"]) <= covered, sorted(
        set(MERGED["agent_world_tables"]) - covered)
    assert "ENABLE ROW LEVEL SECURITY" in sql.upper()
    assert "FORCE ROW LEVEL SECURITY" in sql.upper()
    # The application role must not be able to read around the policies.
    assert re.search(r"REVOKE\s+ALL\s+ON[^;]*FROM\s+PUBLIC", sql, re.I), REPLACE


def test_agent_world_now_has_both_repository_implementations():
    from app.ai_control_center import domain_gateway, sqlite_repository
    assert hasattr(sqlite_repository, "SQLiteAgentWorldRepository")
    source = Path(domain_gateway.__file__).read_text(encoding="utf-8", errors="ignore")
    assert "SQLiteAgentWorldRepository" in source
    assert "PostgresAgentWorldRepository" in source, (
        "the gateway should be able to select the PostgreSQL adapter" + REPLACE)
    package = ROOT / "app" / "ai_control_center"
    implementations = {path.name for path in package.glob("*repository*.py")}
    assert implementations == MERGED["agent_world_repositories"], REPLACE


def test_the_agent_world_postgres_suite_skips_rather_than_passes_without_a_server():
    """Reading SQL is not executing a migration; a missing DSN must skip.

    This suite also refuses a target that is not a disposable loopback database
    and checks the app role is neither superuser nor RLS-bypassing, so isolation
    is proven with runtime-like rights rather than around them.
    """
    text = (TESTS / MERGED["agent_world_suite"]).read_text(encoding="utf-8", errors="ignore")
    assert "pytest.skip" in text
    assert "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ALLOW" in text
    assert "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_URL" in text
    assert "STRATFORGE_TEST_AGENT_WORLD_POSTGRES_ADMIN_URL" in text
    assert "aw_disposable_" in text, "must refuse a non-disposable target"
    assert "rolsuper" in text and "rolbypassrls" in text, "must run as an RLS-bound role"
    assert "ai_control_center" in text, "this suite is the one that does exercise Agent World"
