"""The PostgreSQL branch of the connection guard, without a PostgreSQL.

A real disposable PostgreSQL is not configured in this environment, so the
`test_agent_world_postgres*` suites skip and this branch of
`NativeExternalRepository.guard` is otherwise never executed at all. That is
worth something better than nothing: these cases drive the branch against a
recording client and pin the two properties that would be silently wrong in
production and invisible on SQLite.

The first is that the lock is transaction-scoped. `pg_advisory_lock` and
`pg_try_advisory_lock` are session-scoped, and a pooled connection handed back
while still holding one leaks it to whoever gets that connection next — a
deadlock nobody can reproduce. Only `pg_try_advisory_xact_lock` releases with
the transaction.

The second is that it is taken inside a workspace-scoped transaction, so one
tenant's guard can never block another's.

This is not a substitute for running the PostgreSQL suites. It is the part that
can be proved here, and the gap is recorded in the master status.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center.external_agent_repository import NativeExternalRepository
from app.ai_control_center.states import ContractError


CONNECTION = "11111111-2222-4333-8444-555555555555"


class Cursor:
    def __init__(self, acquired):
        self.acquired = acquired

    def fetchone(self):
        return {"acquired": self.acquired}


class Client:
    """Records what the guard asks PostgreSQL to do."""

    def __init__(self, grants):
        self.grants, self.statements, self.scopes = list(grants), [], []
        self.open_transactions = 0

    @contextmanager
    def transaction(self, scope):
        self.scopes.append(scope)
        self.open_transactions += 1
        try:
            yield self
        finally:
            self.open_transactions -= 1

    def execute(self, sql, params):
        self.statements.append((" ".join(sql.split()), params))
        return Cursor(self.grants.pop(0) if self.grants else True)


class Repository:
    def __init__(self, client):
        self.client, self.read_only = client, False

    def _context(self, context):
        return context


@pytest.fixture
def context():
    return c.RequestContext(
        scope=c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id="ws_guard_shape"),
        user_uuid=__import__("uuid").UUID("aa000000-0000-4000-8000-000000000101"),
        actor=c.ActorRef(kind=c.ActorKind.HUMAN,
                         actor_id=__import__("uuid").UUID("aa000000-0000-4000-8000-000000000101")))


def test_the_lock_is_transaction_scoped_so_a_pooled_connection_cannot_leak_it(context):
    client = Client([True])
    guard = NativeExternalRepository(Repository(client))
    with guard.guard(context, CONNECTION):
        assert client.open_transactions == 1, "the lock must be held inside the transaction"
    assert client.open_transactions == 0

    sql, params = client.statements[0]
    assert "pg_try_advisory_xact_lock" in sql
    assert "pg_advisory_lock" not in sql and "pg_try_advisory_lock(" not in sql
    assert isinstance(params[0], int)


def test_the_guard_is_taken_inside_this_workspace_and_no_other(context):
    client = Client([True])
    guard = NativeExternalRepository(Repository(client))
    with guard.guard(context, CONNECTION):
        pass
    assert len(client.scopes) == 1
    assert getattr(client.scopes[0], "workspace_id", None) == "ws_guard_shape"


def test_two_different_connections_do_not_share_a_lock_key(context):
    keys = []
    for identity in (CONNECTION, "99999999-2222-4333-8444-555555555555"):
        client = Client([True])
        with NativeExternalRepository(Repository(client)).guard(context, identity):
            pass
        keys.append(client.statements[0][1][0])
    assert keys[0] != keys[1]


def test_a_busy_connection_gives_up_by_the_deadline_rather_than_waiting_for_ever(context):
    client = Client([False] * 400)
    guard = NativeExternalRepository(Repository(client))
    with pytest.raises(ContractError) as refused:
        with guard.guard(context, CONNECTION, timeout=0.1):
            pytest.fail("the guard must not yield while the lock is held elsewhere")
    assert refused.value.code == "external_agent_connection_busy"
    assert client.open_transactions == 0, "the transaction must close when the wait is abandoned"


def test_a_read_only_repository_is_refused_before_any_lock_is_taken(context):
    client = Client([True])
    repository = Repository(client)
    repository.read_only = True
    with pytest.raises(ContractError) as refused:
        with NativeExternalRepository(repository).guard(context, CONNECTION):
            pytest.fail("a read-only repository must never take a write guard")
    assert refused.value.code == "agent_world_repository_read_only"
    assert client.statements == []
