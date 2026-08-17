"""The registry's INSERT and the registry's table must name the same columns.

This exists because they once did not. ``sf_environment_registry`` was created
before the heartbeat carried ``market_data`` and ``connector``; the application
then reported both on every beat, the INSERT had nowhere to put them, and the
compare view rendered "not reported" for two fields that were being reported
all along.

Nothing in the Python-only tests could see it: that side was self-consistent,
and only the round trip through the real schema lost the values. So the check
here is structural -- read the columns the repository writes, read the columns
the migrations create, and require that the first is a subset of the second.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "production_storage" / "migrations"
CORE = Path(__file__).resolve().parents[1] / "app" / "production_storage" / "core.py"

TABLE = "sf_environment_registry"


def _schema_columns(table: str) -> set:
    """Columns the migration set creates for ``table``, including later ADDs."""
    columns: set = set()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")

        created = re.search(
            r"CREATE TABLE IF NOT EXISTS\s+" + table + r"\s*\((.*?)\n\);",
            sql, re.S | re.I,
        )
        if created:
            for line in created.group(1).splitlines():
                line = line.strip()
                if not line or line.startswith("--"):
                    continue
                # Table-level constraints are not columns.
                if re.match(r"(CHECK|PRIMARY|UNIQUE|FOREIGN|CONSTRAINT)\b", line, re.I):
                    continue
                name = re.match(r"([a-z_][a-z0-9_]*)", line)
                if name:
                    columns.add(name.group(1))

        for added in re.finditer(
            r"ALTER TABLE\s+" + table + r"\s+ADD COLUMN(?:\s+IF NOT EXISTS)?\s+([a-z_][a-z0-9_]*)",
            sql, re.I,
        ):
            columns.add(added.group(1))
    return columns


def _insert_columns(table: str) -> set:
    """Columns the repository names in its INSERT for ``table``."""
    source = CORE.read_text(encoding="utf-8")
    match = re.search(
        r"INSERT INTO " + table + r"\((.*?)\)\s*\n\s*VALUES", source, re.S | re.I,
    )
    assert match, f"no INSERT INTO {table} found in core.py"
    body = re.sub(r"\s+", "", match.group(1))
    return {name for name in body.split(",") if name}


def test_registry_table_exists_in_the_migration_set():
    assert _schema_columns(TABLE), f"{TABLE} is not created by any migration"


def test_every_column_the_repository_writes_exists_in_the_schema():
    schema = _schema_columns(TABLE)
    written = _insert_columns(TABLE)
    missing = sorted(written - schema)
    assert not missing, (
        "the repository writes columns the schema does not have: "
        + ", ".join(missing)
        + ". Values sent to a column that does not exist are lost silently on "
        "the way in and read back empty."
    )


@pytest.mark.parametrize("column", ["market_data", "connector", "readiness", "schema_version"])
def test_the_reported_fields_are_actually_storable(column):
    """Named explicitly, because these are the ones the compare view depends on
    and an absent column shows up there as an innocent-looking blank."""
    assert column in _schema_columns(TABLE)
    assert column in _insert_columns(TABLE)
