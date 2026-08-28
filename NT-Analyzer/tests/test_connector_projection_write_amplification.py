"""Writing less must not mean writing late, or writing the wrong rows.

The authoritative Connector document retains terminal history. Re-projecting
all of it on every live request meant one Production installation with 1,144
retained sessions issued 1,144 physical session UPDATEs per heartbeat, poll or
market-data batch: 44 real changes became 50,336 writes in a 90-second window.

Skipping unchanged rows is only correct if everything that genuinely moved is
still written on that same pass. A renewal that is not projected is a Connector
that cannot authenticate; a command that is not projected is a command the
device never receives; a revocation that is not projected is a credential that
keeps working. These hold that line from the other side of the optimisation.
"""
from __future__ import annotations

import copy

from app.production_storage import core

from tests.test_connector_storage_reconciliation import (
    VALID_USER,
    _command as _raw_command,
    _existing_projection,
    _installation,
    _session,
    _sync,
)


def _command(index, **overrides):
    """A command owned by a live actor, so it projects rather than reconciling
    away as a terminal orphan."""
    overrides.setdefault("user_id", VALID_USER)
    return _raw_command(index, **overrides)


def _history_projection(installation, sessions, command):
    base = _existing_projection(installation, sessions[0], command)
    base["sessions"] = [
        {
            "session_id": row["session_id"],
            "installation_id": row["installation_id"],
            "workspace_id": row["workspace_id"],
            "token_hash": row["token_hash"],
            "expires_at": core._timestamp(row["expires_at"]),
            "revoked_at": None,
            "document": copy.deepcopy(row),
        }
        for row in sessions
    ]
    return base


# --------------------------------------------------------------------------- #
# Sessions: renewal, issuance, revocation.
# --------------------------------------------------------------------------- #
def test_a_renewed_session_is_projected_immediately():
    """A heartbeat that extends a session must reach the mirror on that write."""
    installation = _installation(status="online")
    session = _session(1, status="active")
    command = _command(1)
    existing = _existing_projection(installation, session, command)

    renewed = dict(session, expires_at=session["expires_at"] + 900.0)
    conn = _sync(
        {"installations": [installation], "sessions": [renewed], "commands": [command]},
        existing=existing,
    )
    written = conn.inserts("sf_connector_sessions")
    assert [params[0] for params in written] == [session["session_id"]]
    assert written[0][4] == core._timestamp(renewed["expires_at"])


def test_an_expiry_change_alone_is_enough_to_rewrite_the_row():
    """Expiry drives staleness and retry, so a row whose only difference is
    when it expires has still changed."""
    installation = _installation(status="online")
    session = _session(1, status="active")
    command = _command(1)
    later = dict(session, expires_at=session["expires_at"] + 1.0)
    conn = _sync(
        {"installations": [installation], "sessions": [later], "commands": [command]},
        existing=_existing_projection(installation, session, command),
    )
    assert len(conn.inserts("sf_connector_sessions")) == 1


def test_a_new_session_beside_retained_history_is_the_only_row_written():
    """Signed hello issues a session while the old ones are retained.

    This is the shape of the original fault: the one new row was correct and
    the thirty-nine unchanged ones behind it were the waste.
    """
    installation = _installation(status="online")
    history = [_session(index) for index in range(1, 40)]
    command = _command(1)
    fresh = _session(999, status="active")
    conn = _sync(
        {"installations": [installation], "sessions": [*history, fresh],
         "commands": [command]},
        existing=_history_projection(installation, history, command),
    )
    assert [params[0] for params in conn.inserts("sf_connector_sessions")] == [
        fresh["session_id"],
    ]


def test_a_revoked_session_is_projected_so_it_stops_authenticating():
    """Revocation is a security transition and is never optimised away."""
    installation = _installation(status="online")
    session = _session(1, status="active")
    command = _command(1)
    revoked = dict(session, status="revoked", revoked_at_utc="2026-08-27T23:40:00Z")
    conn = _sync(
        {"installations": [installation], "sessions": [revoked], "commands": [command]},
        existing=_existing_projection(installation, session, command),
    )
    written = conn.inserts("sf_connector_sessions")
    assert len(written) == 1
    assert written[0][5] == core._timestamp("2026-08-27T23:40:00Z")


# --------------------------------------------------------------------------- #
# Commands: nothing queued may be lost.
# --------------------------------------------------------------------------- #
def test_a_command_lease_transition_is_projected_then_settles():
    """commands/poll leases a command; that moves the row, so it is written.
    Polling again with nothing new writes nothing."""
    installation = _installation(status="online")
    session = _session(1, status="active")
    queued = _command(1, status="pending")
    existing = _existing_projection(installation, session, queued)
    existing["commands"][0]["status"] = "queued"

    leased = dict(queued, status="delivered")
    conn = _sync(
        {"installations": [installation], "sessions": [session], "commands": [leased]},
        existing=existing,
    )
    assert [params[0] for params in conn.inserts("sf_commands")] == [queued["command_id"]]

    existing["commands"][0]["status"] = "leased"
    existing["commands"][0]["document"] = copy.deepcopy(leased)
    again = _sync(
        {"installations": [installation], "sessions": [session], "commands": [leased]},
        existing=existing,
    )
    assert again.inserts("sf_commands") == []


def test_a_newly_queued_command_is_never_skipped():
    installation = _installation(status="online")
    session = _session(1, status="active")
    old = _command(1, status="completed")
    existing = _existing_projection(installation, session, old)
    existing["commands"][0]["status"] = "completed"

    fresh = _command(2, status="pending")
    conn = _sync(
        {"installations": [installation], "sessions": [session],
         "commands": [old, fresh]},
        existing=existing,
    )
    assert [params[0] for params in conn.inserts("sf_commands")] == [fresh["command_id"]]


# --------------------------------------------------------------------------- #
# Installations, and removal.
# --------------------------------------------------------------------------- #
def test_an_installation_going_online_is_projected():
    installation = _installation(status="offline")
    session = _session(1)
    command = _command(1)
    conn = _sync(
        {"installations": [dict(installation, status="online")],
         "sessions": [session], "commands": [command]},
        existing=_existing_projection(installation, session, command),
    )
    assert len(conn.inserts("sf_connector_installations")) == 1


def test_rows_that_left_the_document_are_still_deleted():
    """Writing less must not become forgetting to remove: a session dropped
    from the authoritative document has to leave the mirror with it."""
    installation = _installation(status="online")
    kept = _session(1, status="active")
    dropped = _session(2)
    command = _command(1)
    existing = _history_projection(installation, [kept, dropped], command)

    conn = _sync(
        {"installations": [installation], "sessions": [kept], "commands": [command]},
        existing=existing,
    )
    deletes = [
        params for sql, params in conn.statements
        if sql.startswith("DELETE FROM sf_connector_sessions")
    ]
    assert deletes == [([dropped["session_id"]],)]


def test_a_steady_state_issues_no_write_at_all():
    """Not one UPDATE, not one DELETE that matches nothing. The whole point is
    to stop touching rows that did not move."""
    installation = _installation(status="online")
    session = _session(1, status="active")
    command = _command(1)
    conn = _sync(
        {"installations": [installation], "sessions": [session], "commands": [command]},
        existing=_existing_projection(installation, session, command),
    )
    assert conn.inserts("sf_connector_sessions") == []
    assert conn.inserts("sf_connector_installations") == []
    assert conn.inserts("sf_commands") == []
    assert [sql for sql, _ in conn.statements if sql.startswith("DELETE")] == []
