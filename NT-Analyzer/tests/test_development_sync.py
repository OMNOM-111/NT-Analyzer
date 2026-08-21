"""Is the running LOCAL process the code in the checkout?

The project rule is that every change is developed and run on LOCAL first, then
promoted as one immutable artifact. That rule breaks silently whenever LOCAL
keeps serving an old process after a merge -- Canary ends up newer than the
machine the work is supposed to happen on, and the three environments start
feeling like three different products.

This is not hypothetical: LOCAL was found serving 0.10.0-beta.20 while the
checkout stood at beta.26, six releases behind.
"""
from __future__ import annotations

import pytest

from app import development_sync, runtime_env


@pytest.fixture()
def local(monkeypatch):
    monkeypatch.setattr(runtime_env, "is_development", lambda: True)
    return monkeypatch


def _deployment(monkeypatch, commit, version="0.10.0-beta.26"):
    monkeypatch.setattr(runtime_env, "public_status", lambda: {
        "app_version": version, "git_commit_sha": commit,
    })


def test_a_matching_checkout_reads_current(local, monkeypatch):
    _deployment(monkeypatch, "a" * 40)
    monkeypatch.setattr(development_sync, "_git",
                        lambda *a: "a" * 40 if a[0] == "rev-parse" else "main")
    monkeypatch.setattr(development_sync, "_dirty_paths", lambda: [])
    assert development_sync.status()["state"] == "current"


def test_a_stale_process_is_named_as_such(local, monkeypatch):
    """The beta.20-against-beta.26 case."""
    _deployment(monkeypatch, "b" * 40, version="0.10.0-beta.20")
    monkeypatch.setattr(development_sync, "_git",
                        lambda *a: "c" * 40 if a[0] == "rev-parse" else "main")
    monkeypatch.setattr(development_sync, "_dirty_paths", lambda: [])
    out = development_sync.status()
    assert out["state"] == "stale"
    assert out["running_commit"] != out["head_commit"]
    assert development_sync.is_stale() is True


def test_uncommitted_work_is_distinguished_from_a_stale_process(local, monkeypatch):
    """Dirty is observable, but whether the running interpreter loaded those
    edits is not.  The UI must not present that unknowable fact as certainty."""
    _deployment(monkeypatch, "a" * 40)
    monkeypatch.setattr(development_sync, "_git",
                        lambda *a: "a" * 40 if a[0] == "rev-parse" else "main")
    monkeypatch.setattr(development_sync, "_dirty_paths", lambda: ["app/x.py"])
    out = development_sync.status()
    assert out["state"] == "dirty"
    assert out["dirty_count"] == 1
    assert "Нельзя надёжно определить" in out["message"]
    assert "ещё не в запущенном процессе" not in out["message"]


def test_regenerated_data_never_counts_as_dirty(monkeypatch):
    """The server rewrites data/governance-rendered on startup. Counting it
    would make a freshly started LOCAL permanently dirty, and a signal that is
    always on is a signal nobody reads."""
    monkeypatch.setattr(
        development_sync, "_git",
        lambda *a: " M NT-Analyzer/data/governance-rendered/LAWS.md\n M app/real.py"
        if a[0] == "status" else "a" * 40)
    assert development_sync._dirty_paths() == ["app/real.py"]


def test_a_server_environment_declines_the_question(monkeypatch):
    """Canary and Production run a released artifact and have no checkout, so
    the honest answer is that the question does not apply -- not a made-up one."""
    monkeypatch.setattr(runtime_env, "is_development", lambda: False)
    out = development_sync.status()
    assert out["state"] == "not_applicable"
    assert out["reason"] == "server_environment"


def test_an_unreadable_checkout_says_unknown(local, monkeypatch):
    _deployment(monkeypatch, "a" * 40)
    monkeypatch.setattr(development_sync, "_git", lambda *a: "")
    out = development_sync.status()
    assert out["state"] == "unknown"
    assert out["reason"] == "git_unavailable"


def test_the_status_never_restarts_anything():
    """A background process that restarts the server someone is debugging is
    worse than a stale banner. It reports; the interface offers the action."""
    source = (development_sync.__file__)
    text = open(source, encoding="utf-8").read()
    for forbidden in ("Popen", "os.execv", "restart(", "kill("):
        assert forbidden not in text, f"{forbidden} must not appear here"
    assert "restart_hint" in text


def test_the_route_is_capability_gated():
    from app import permissions
    entry = dict(permissions.ADMIN_ROUTE_CAPABILITY)
    assert entry["/api/admin/development-sync"] == "environment.switch"
