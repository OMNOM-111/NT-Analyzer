"""Python's repository allowlist and the database CHECK are one contract.

They were not. ``REPOSITORIES`` in core.py grew ``releases`` and ``doc_specs``
while ``sf_repository_documents``'s CHECK still listed only the original four,
and nothing noticed because the two code paths that write those documents are
in practice driven from LOCAL, which uses the encrypted local store instead of
PostgreSQL.

That is a latent failure, not a harmless one: written from the Production
process, the INSERT violates the CHECK, the surrounding document write is rolled
back, and the caller gets an opaque 503. So the two lists are pinned together
here -- adding a repository to one without the other now fails a test rather
than waiting to fail in Production.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "app" / "production_storage" / "migrations"
CORE = ROOT / "app" / "production_storage" / "core.py"


def _python_allowlist() -> set:
    """The REPOSITORIES frozenset, read from the source rather than imported so
    the test does not depend on import-time environment validation."""
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "REPOSITORIES" not in targets:
            continue
        # frozenset({...})
        call = node.value
        if isinstance(call, ast.Call) and call.args:
            literal = call.args[0]
            return {
                element.value for element in getattr(literal, "elts", [])
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    raise AssertionError("REPOSITORIES not found in core.py")


def _sql_allowlist() -> set:
    """The effective CHECK, taking the last definition across the migration set
    in applied order -- a later migration may replace an earlier constraint."""
    effective: set = set()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"CHECK\s*\(\s*repository\s+IN\s*\((.*?)\)\s*\)", sql, re.S | re.I,
        ):
            effective = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    if not effective:
        raise AssertionError("no repository CHECK found in the migration set")
    return effective


def test_the_two_allowlists_are_identical():
    python = _python_allowlist()
    sql = _sql_allowlist()
    assert python == sql, (
        "the Python allowlist and the database CHECK disagree.\n"
        f"  only in Python: {sorted(python - sql)}\n"
        f"  only in SQL:    {sorted(sql - python)}\n"
        "A repository Python permits but the CHECK rejects fails the INSERT, "
        "rolls back the whole document write and surfaces as an opaque 503."
    )


def test_the_repositories_actually_used_are_permitted():
    """Named explicitly, because these two are the ones that drifted."""
    allowed = _python_allowlist() & _sql_allowlist()
    for repository in ("auth", "workspaces", "entitlements", "connectors",
                       "releases", "doc_specs"):
        assert repository in allowed, f"{repository} is not writable"


def test_every_store_key_in_the_app_is_allowlisted():
    """Catches a third repository being introduced without either list."""
    keys = set()
    for path in (ROOT / "app").glob("*.py"):
        for match in re.finditer(
            r'^_STORE_KEY\s*=\s*"([a-z_]+)"', path.read_text(encoding="utf-8"), re.M,
        ):
            keys.add(match.group(1))
    assert keys, "no _STORE_KEY definitions found -- has the pattern changed?"
    missing = sorted(keys - _python_allowlist())
    assert not missing, f"store keys with no repository allowlist entry: {missing}"
