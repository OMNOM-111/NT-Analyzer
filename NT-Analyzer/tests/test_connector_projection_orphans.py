"""One orphaned installation must not deny service to every other connector.

The connector document is global: it carries every installation for every
workspace. Projecting it into sf_connector_installations used to insert them
all unconditionally, so an installation whose workspace row no longer existed
made the foreign key reject the statement and failed the entire write. On
Production that meant a healthy device retrying a signed challenge could never
succeed, because an unrelated orphan poisoned the transaction.
"""
from __future__ import annotations

from app.production_storage.core import DocumentRepository


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Conn:
    """Records statements and answers the workspace-existence probe."""

    def __init__(self, existing_workspaces):
        self.existing = set(existing_workspaces)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), params))
        if "FROM sf_workspaces WHERE workspace_id = ANY" in " ".join(sql.split()):
            wanted = list(params[0]) if params else []
            return _Result([(w,) for w in wanted if w in self.existing])
        return _Result([])


def _doc():
    return {
        "installations": [
            {"installation_id": "inst_live", "workspace_id": "ws_good_00000001",
             "user_id": 42, "status": "offline", "public_key_fingerprint": "f" * 32},
            {"installation_id": "inst_orphan", "workspace_id": "ws_gone_00000002",
             "user_id": 42, "status": "revoked", "public_key_fingerprint": "e" * 32},
        ],
        "sessions": [
            {"session_id": "csess_live", "installation_id": "inst_live",
             "workspace_id": "ws_good_00000001", "token_hash": "a" * 64},
            {"session_id": "csess_orphan", "installation_id": "inst_orphan",
             "workspace_id": "ws_gone_00000002", "token_hash": "b" * 64},
        ],
        "commands": [
            {"command_id": "cmd_live", "installation_id": "inst_live",
             "workspace_id": "ws_good_00000001", "user_id": 42, "status": "queued"},
            {"command_id": "cmd_orphan", "installation_id": "inst_orphan",
             "workspace_id": "ws_gone_00000002", "user_id": 42, "status": "queued"},
        ],
    }


def _inserted(conn, table):
    return [
        params for sql, params in conn.statements
        if sql.startswith(f"INSERT INTO {table}(")
    ]


def test_orphaned_installation_is_skipped_and_the_healthy_one_still_projects():
    conn = _Conn({"ws_good_00000001"})
    DocumentRepository._sync_connectors(
        DocumentRepository.__new__(DocumentRepository), conn, _doc())

    installs = _inserted(conn, "sf_connector_installations")
    ids = [p[0] for p in installs]
    assert "inst_live" in ids, "the healthy installation must still be projected"
    assert "inst_orphan" not in ids, "the orphan must not be inserted"


def test_rows_referencing_a_skipped_installation_are_not_projected():
    conn = _Conn({"ws_good_00000001"})
    DocumentRepository._sync_connectors(
        DocumentRepository.__new__(DocumentRepository), conn, _doc())

    sessions = [p[0] for p in _inserted(conn, "sf_connector_sessions")]
    commands = [p[0] for p in _inserted(conn, "sf_commands")]
    assert sessions == ["csess_live"], sessions
    assert commands == ["cmd_live"], commands


def test_the_orphan_is_pruned_from_the_projection():
    conn = _Conn({"ws_good_00000001"})
    DocumentRepository._sync_connectors(
        DocumentRepository.__new__(DocumentRepository), conn, _doc())

    # _delete_missing is driven by the surviving id list, so an orphan already
    # sitting in the table is removed rather than left behind.
    deletes = [
        (sql, params) for sql, params in conn.statements
        if sql.startswith("DELETE FROM sf_connector_installations")
    ]
    assert deletes, conn.statements
    kept = deletes[-1][1]
    assert "inst_orphan" not in str(kept)


def test_every_workspace_present_projects_everything():
    conn = _Conn({"ws_good_00000001", "ws_gone_00000002"})
    DocumentRepository._sync_connectors(
        DocumentRepository.__new__(DocumentRepository), conn, _doc())

    ids = [p[0] for p in _inserted(conn, "sf_connector_installations")]
    assert sorted(ids) == ["inst_live", "inst_orphan"]
