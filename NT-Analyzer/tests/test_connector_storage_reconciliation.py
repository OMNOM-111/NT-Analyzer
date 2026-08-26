from __future__ import annotations

import copy
import hashlib

import pytest

from app.production_storage import StorageConstraintError
from app.production_storage import core
from app.production_storage.core import DocumentRepository


VALID_WORKSPACE = "ws_personal_AAHRJ7jWYo2lxdJm"
VALID_USER = 1647145559
VALID_INSTALLATION = "inst_9rVbadz0rNu0xlbbfsVSnkvY"
ORPHAN_WORKSPACE = "ws_personal_test"
ORPHAN_USER = 123456
ORPHAN_INSTALLATION = "inst_5IzgKhuFZU332EhNYy3a4tLL"
DEPARTED_COMMAND_USER = 9000000000728


class _Rows:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def fetchall(self):
        return list(self._rows)


class _ConstraintAwareConnection:
    """Small relational model that reproduces the Production FK failure."""

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.statements.append((text, params))
        if text.startswith("SELECT workspace_id FROM sf_workspaces"):
            return _Rows([{"workspace_id": VALID_WORKSPACE}])
        if text.startswith("SELECT user_id FROM sf_users"):
            return _Rows([{"user_id": VALID_USER}])
        if text.startswith("SELECT workspace_id,user_id FROM sf_workspace_memberships"):
            return _Rows([{"workspace_id": VALID_WORKSPACE, "user_id": VALID_USER}])
        if text.startswith("INSERT INTO sf_connector_installations"):
            if params[1] != VALID_WORKSPACE:
                raise StorageConstraintError(
                    "sf_connector_installations_workspace_id_fkey"
                )
        return _Rows()

    def inserts(self, table):
        prefix = f"INSERT INTO {table}"
        return [params for sql, params in self.statements if sql.startswith(prefix)]


def _installation(**overrides):
    row = {
        "installation_id": VALID_INSTALLATION,
        "workspace_id": VALID_WORKSPACE,
        "user_id": VALID_USER,
        "status": "offline",
        "public_key_fingerprint": "f" * 64,
        "created_at_utc": "2026-08-01T10:45:02Z",
    }
    row.update(overrides)
    return row


def _session(index, **overrides):
    row = {
        "session_id": f"csess_production_case_{index:04d}",
        "installation_id": VALID_INSTALLATION,
        "workspace_id": VALID_WORKSPACE,
        "status": "expired",
        "token_hash": hashlib.sha256(f"session-{index}".encode()).hexdigest(),
        "expires_at": 1785301059.177064,
        "created_at_utc": "2026-07-29T04:42:39Z",
    }
    row.update(overrides)
    return row


def _command(index, **overrides):
    row = {
        "command_id": f"cmd_production_case_{index:04d}",
        "workspace_id": VALID_WORKSPACE,
        "installation_id": VALID_INSTALLATION,
        "user_id": DEPARTED_COMMAND_USER,
        "status": "rejected",
        "command_type": "connector_command",
        "idempotency_key": f"legacy:production-case-{index}",
        "expires_at_utc": "2026-08-01T12:30:21Z",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def jsonb_without_postgres(monkeypatch):
    monkeypatch.setattr(core, "_jsonb", copy.deepcopy)


def _sync(doc):
    conn = _ConstraintAwareConnection()
    DocumentRepository._sync_connectors(DocumentRepository, conn, doc)
    return conn


def test_production_terminal_orphans_do_not_block_live_challenge_projection():
    """Reproduce the beta.47 Production document, including its exact first FK."""
    orphan_sessions = [
        _session(
            index,
            installation_id=ORPHAN_INSTALLATION,
            workspace_id=ORPHAN_WORKSPACE,
            status="revoked" if index == 50 else "expired",
        )
        for index in range(51)
    ]
    terminal_commands = [_command(index) for index in range(8)]
    doc = {
        "installations": [
            _installation(
                installation_id=ORPHAN_INSTALLATION,
                workspace_id=ORPHAN_WORKSPACE,
                user_id=ORPHAN_USER,
                status="revoked",
                revoked_at_utc="2026-07-29T17:17:24Z",
            ),
            _installation(),
        ],
        "sessions": [*orphan_sessions, _session(9000)],
        "commands": [
            *terminal_commands,
            _command(9000, user_id=VALID_USER, status="queued"),
        ],
    }
    before = copy.deepcopy(doc)

    conn = _sync(doc)

    assert doc == before, "terminal history remains in the authoritative JSON document"
    assert [params[0] for params in conn.inserts("sf_connector_installations")] == [
        VALID_INSTALLATION
    ]
    assert [params[0] for params in conn.inserts("sf_connector_sessions")] == [
        "csess_production_case_9000"
    ]
    assert [params[0] for params in conn.inserts("sf_commands")] == [
        "cmd_production_case_9000"
    ]
    assert ORPHAN_INSTALLATION not in {
        value for _, params in conn.statements if params for value in params if isinstance(value, str)
    }


def test_non_terminal_orphan_installation_still_fails_closed():
    doc = {
        "installations": [
            _installation(
                installation_id=ORPHAN_INSTALLATION,
                workspace_id=ORPHAN_WORKSPACE,
                user_id=ORPHAN_USER,
                status="online",
            )
        ]
    }

    with pytest.raises(StorageConstraintError, match="installation.*non-terminal orphan"):
        _sync(doc)


def test_non_terminal_session_of_revoked_orphan_still_fails_closed():
    doc = {
        "installations": [
            _installation(
                installation_id=ORPHAN_INSTALLATION,
                workspace_id=ORPHAN_WORKSPACE,
                user_id=ORPHAN_USER,
                status="revoked",
            )
        ],
        "sessions": [
            _session(
                1,
                installation_id=ORPHAN_INSTALLATION,
                workspace_id=ORPHAN_WORKSPACE,
                status="active",
            )
        ],
    }

    with pytest.raises(StorageConstraintError, match="session.*non-terminal orphan"):
        _sync(doc)


def test_non_terminal_command_with_departed_actor_still_fails_closed():
    doc = {
        "installations": [_installation()],
        "commands": [_command(1, status="queued")],
    }

    with pytest.raises(StorageConstraintError, match="command.*non-terminal orphan"):
        _sync(doc)
