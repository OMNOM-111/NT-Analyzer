"""A maintenance tool must operate on the store the server serves.

runtime_env.data_root() is deterministic given its environment variables, which
is precisely the trap: a tool started without them resolves a different
directory and reports confidently on a store nothing serves.

That is not hypothetical. start.ps1 exports
STRATFORGE_DEVELOPMENT_DATA_ROOT=<project>/data; an ad-hoc process without it
resolved <project>/data/development -- an abandoned copy weeks out of date --
and produced a complete, internally consistent, entirely fictional account
inventory. Acting on it would have "cleaned" a store nobody reads while leaving
the real one untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import data_root_guard, runtime_env


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A project tree with two plausible roots, only one of them live."""
    live = tmp_path / "data"
    stale = tmp_path / "data" / "development"
    for root in (live, stale):
        (root / "integrations").mkdir(parents=True, exist_ok=True)
        (root / "integrations" / "accounts.dpapi").write_bytes(b"x")
    monkeypatch.setattr(data_root_guard, "_project_root", lambda: tmp_path)
    return tmp_path, live, stale


def _resolve_to(monkeypatch, path):
    monkeypatch.setattr(runtime_env, "data_root", lambda *a, **k: path)


# --------------------------------------------------------------------------- #
# The regression: tool and server must agree.
# --------------------------------------------------------------------------- #
def test_the_tool_and_the_server_resolve_the_same_root(project, monkeypatch):
    tmp, live, stale = project
    _resolve_to(monkeypatch, live)
    data_root_guard.publish_active_root("development")

    # A tool that resolves the same way is satisfied.
    assert data_root_guard.require_active_root(tmp) == live


def test_a_tool_resolving_the_abandoned_root_is_refused(project, monkeypatch):
    """The exact failure. The stale root holds a real store, so nothing about
    it looks wrong from the inside -- only the published marker distinguishes
    them."""
    tmp, live, stale = project
    _resolve_to(monkeypatch, live)
    data_root_guard.publish_active_root("development")

    _resolve_to(monkeypatch, stale)
    with pytest.raises(data_root_guard.DataRootError) as exc:
        data_root_guard.require_active_root(tmp)
    assert "Cannot prove" in str(exc.value) or "legacy" in str(exc.value)


def test_ambiguity_fails_closed_when_nothing_is_published(project, monkeypatch):
    """Two live stores and no marker: refuse rather than pick. A cleanup run
    against the wrong store is worse than one that did not run."""
    tmp, live, stale = project
    _resolve_to(monkeypatch, live)
    with pytest.raises(data_root_guard.DataRootError) as exc:
        data_root_guard.require_active_root(tmp)
    assert str(stale) in str(exc.value), "the refusal must name the other candidate"


def test_a_single_store_needs_no_marker(project, monkeypatch, tmp_path):
    """A deployment with one root is unambiguous and must keep working."""
    tmp, live, stale = project
    import shutil
    shutil.rmtree(stale)
    _resolve_to(monkeypatch, live)
    assert data_root_guard.require_active_root(tmp) == live


# --------------------------------------------------------------------------- #
# Retiring a store without destroying it.
# --------------------------------------------------------------------------- #
def test_a_legacy_root_is_excluded_from_selection(project, monkeypatch):
    tmp, live, stale = project
    data_root_guard.mark_legacy(stale, "superseded by <project>/data")
    _resolve_to(monkeypatch, live)
    # With the other candidate retired there is no ambiguity left to resolve.
    assert data_root_guard.require_active_root(tmp) == live
    assert data_root_guard.is_legacy(stale)


def test_resolving_onto_a_legacy_root_is_refused(project, monkeypatch):
    tmp, live, stale = project
    data_root_guard.mark_legacy(stale, "superseded")
    _resolve_to(monkeypatch, stale)
    with pytest.raises(data_root_guard.DataRootError) as exc:
        data_root_guard.require_active_root(tmp)
    assert "legacy" in str(exc.value)


def test_marking_legacy_never_deletes_the_store(project):
    """An abandoned store is often the only record of what a deployment used to
    look like."""
    tmp, live, stale = project
    data_root_guard.mark_legacy(stale, "superseded")
    assert (stale / "integrations" / "accounts.dpapi").is_file()
    marker = json.loads((stale / data_root_guard.LEGACY_MARKER).read_text(encoding="utf-8"))
    assert marker["reason"]


# --------------------------------------------------------------------------- #
# Publication.
# --------------------------------------------------------------------------- #
def test_publishing_records_the_serving_root(project, monkeypatch):
    tmp, live, stale = project
    _resolve_to(monkeypatch, live)
    data_root_guard.publish_active_root("development")
    marker = data_root_guard.read_marker(live)
    assert marker["environment"] == "development"
    assert marker["root"] == str(live)
    assert marker["pid"] and marker["published_at_utc"]


def test_publishing_never_stops_the_server(monkeypatch, tmp_path):
    """The marker is a diagnostic aid, not a dependency."""
    def explode(*a, **k):
        raise OSError("read-only volume")

    monkeypatch.setattr(runtime_env, "data_root", explode)
    assert data_root_guard.publish_active_root("development") is None


def test_an_empty_directory_is_not_a_candidate(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(data_root_guard, "_project_root", lambda: tmp_path)
    assert data_root_guard.candidate_roots(tmp_path) == []


def test_the_server_publishes_on_startup():
    source = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(
        encoding="utf-8")
    assert "data_root_guard.publish_active_root(" in source
