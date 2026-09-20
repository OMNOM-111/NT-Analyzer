from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai_control_center import overview_snapshot


@pytest.fixture
def store(monkeypatch, tmp_path):
    database = tmp_path / "ai_lab" / "agent-world.sqlite3"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"one")
    monkeypatch.setattr(overview_snapshot, "runtime_env", SimpleNamespace(
        data_path=lambda *parts: tmp_path.joinpath(*parts), data_root=lambda: tmp_path))
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_STORAGE", "sqlite")
    overview_snapshot.invalidate()
    yield database
    overview_snapshot.invalidate()


def authorized(workspace="ws_one", user=None, capabilities=None, read_only=True, role="owner"):
    user = user or UUID_ONE
    context = SimpleNamespace(scope=SimpleNamespace(environment=SimpleNamespace(value="development"), workspace_id=workspace),
                              user_uuid=user)
    return {"context": context, "read_only": read_only, "snapshot": SimpleNamespace(revision="owner-domains-v1"),
            "chat_scope": {"user_id": 1, "workspace_kind": "personal", "membership_role": role, "is_owner": True,
                           "uses_owner_runtime": True, "capabilities": capabilities or {"ai_lab": True}}}


UUID_ONE = uuid4()


def counting():
    calls = []

    def build():
        calls.append(1)
        return {"tasks": [{"id": len(calls)}]}
    return calls, build


def test_unchanged_store_reuses_only_a_just_computed_overview(store, monkeypatch):
    calls, build = counting()
    assert overview_snapshot.fresh(authorized(), build) == {"tasks": [{"id": 1}]}
    assert overview_snapshot.fresh(authorized(), build) == {"tasks": [{"id": 1}]}
    assert len(calls) == 1
    clock = [overview_snapshot.time.monotonic() + overview_snapshot.REUSE_SECONDS + 1]
    monkeypatch.setattr(overview_snapshot.time, "monotonic", lambda: clock[0])
    assert overview_snapshot.fresh(authorized(), build) == {"tasks": [{"id": 2}]}


def test_a_committed_change_is_never_served_as_fresh(store):
    calls, build = counting()
    overview_snapshot.fresh(authorized(), build)
    store.write_bytes(b"changed and longer")
    assert overview_snapshot.fresh(authorized(), build) == {"tasks": [{"id": 2}]}
    wal = Path(str(store) + "-wal")
    wal.write_bytes(b"x")
    assert overview_snapshot.fresh(authorized(), build) == {"tasks": [{"id": 3}]}


@pytest.mark.parametrize("other", [
    {"workspace": "ws_two"}, {"user": uuid4()}, {"capabilities": {"ai_lab": False}},
    {"read_only": False}, {"role": "viewer"},
])
def test_snapshot_never_crosses_authorization(store, other):
    _calls, build = counting()
    overview_snapshot.fresh(authorized(), build)
    assert overview_snapshot.last(authorized()) is not None
    assert overview_snapshot.last(authorized(**other)) is None


def test_snapshot_is_a_copy_and_writes_clear_it(store):
    _calls, build = counting()
    overview_snapshot.fresh(authorized(), build)
    value, computed_at = overview_snapshot.last(authorized())
    value["tasks"].clear()
    assert overview_snapshot.last(authorized())[0] == {"tasks": [{"id": 1}]} and computed_at.endswith("Z")
    overview_snapshot.invalidate()
    assert overview_snapshot.last(authorized()) is None


def test_other_storage_backends_are_never_cached(store, monkeypatch):
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_STORAGE", "postgres")
    calls, build = counting()
    overview_snapshot.fresh(authorized(), build)
    overview_snapshot.fresh(authorized(), build)
    assert len(calls) == 2 and overview_snapshot.last(authorized()) is None
