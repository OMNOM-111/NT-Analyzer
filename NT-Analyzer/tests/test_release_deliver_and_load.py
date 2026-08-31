"""Reaching Canary in one action, and load charted only from real figures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import release_center, release_deliver

AURORA = Path(release_deliver.__file__).resolve().parents[1] / "app" / "static" / "aurora" / "assets"
UI = (AURORA / "ui.js").read_text(encoding="utf-8")
CSS = (AURORA / "theme.css").read_text(encoding="utf-8")


# ---- delivery to Canary -----------------------------------------------------

def _calls():
    seen = []

    def record(name, result=None):
        def inner(**kwargs):
            seen.append(name)
            return result or {}
        return inner

    return seen, record


def test_target_comes_from_the_repository_not_the_caller() -> None:
    target = release_deliver.release_target()
    assert target["app_version"], "VERSION.json must supply the version"
    assert release_deliver.deliver.__doc__


def test_delivery_runs_the_whole_sequence_in_order(monkeypatch) -> None:
    seen, record = _calls()
    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: {"summary": {"state": "canary_checking"}})
    out = release_deliver.deliver(
        actor={"is_owner": True}, idempotency_key="k" * 20,
        create=lambda **kw: (seen.append("create"), {"candidate_id": "rc_1"})[1],
        build=record("build"), verify=record("verify"), deploy=record("deploy"),
    )
    assert out["ok"] is True
    assert seen == ["create", "build", "verify", "deploy"]
    assert out["candidate_id"] == "rc_1"
    assert [row["state"] for row in out["stages"]] == ["passed"] * 5


def test_delivery_stops_at_the_failing_stage(monkeypatch) -> None:
    seen, record = _calls()

    def refuse(**kwargs):
        raise release_center.ReleaseCenterError(
            "Рабочее дерево содержит незакоммиченные изменения.", 409, code="dirty_worktree")

    out = release_deliver.deliver(
        actor={"is_owner": True}, idempotency_key="k" * 20,
        create=lambda **kw: {"candidate_id": "rc_1"},
        build=refuse, verify=record("verify"), deploy=record("deploy"),
    )
    assert out["ok"] is False
    assert out["failed_stage"] == release_deliver.STAGE_BUILD
    assert out["code"] == "dirty_worktree"
    assert "verify" not in seen and "deploy" not in seen
    states = {row["stage"]: row["state"] for row in out["stages"]}
    assert states[release_deliver.STAGE_CANDIDATE] == "passed"
    assert states[release_deliver.STAGE_BUILD] == "failed"
    assert states[release_deliver.STAGE_DONE] == "not_started"


def test_delivery_never_chooses_the_commit(monkeypatch) -> None:
    """An empty commit means the current clean HEAD, which the ledger verifies."""
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return {"candidate_id": "rc_1"}

    monkeypatch.setattr(release_center, "get_release",
                        lambda cid: {"summary": {"state": "canary_checking"}})
    release_deliver.deliver(
        actor={"is_owner": True}, idempotency_key="k" * 20, create=create,
        build=lambda **kw: {}, verify=lambda **kw: {}, deploy=lambda **kw: {},
    )
    assert captured["git_commit_sha"] == ""


def test_a_ledger_failure_state_is_not_reported_as_success(monkeypatch) -> None:
    """build and canary deploy can report failure inside a 200 response."""
    monkeypatch.setattr(release_center, "get_release", lambda cid: {
        "summary": {"state": release_center.STATE_CANARY_FAILED,
                    "failure_reason": "canary_check_failed:acceptance"}})
    out = release_deliver.deliver(
        actor={"is_owner": True}, idempotency_key="k" * 20,
        create=lambda **kw: {"candidate_id": "rc_1"},
        build=lambda **kw: {}, verify=lambda **kw: {}, deploy=lambda **kw: {},
    )
    assert out["ok"] is False
    assert out["failed_stage"] == release_deliver.STAGE_DEPLOY
    assert "acceptance" in out["reason"]


def test_a_dev_channel_is_refused_before_anything_runs(monkeypatch) -> None:
    monkeypatch.setattr(release_deliver, "release_target",
                        lambda: {"app_version": "0.10.0-dev.1", "release_channel": "dev"})
    out = release_deliver.deliver(
        actor={"is_owner": True}, idempotency_key="k" * 20,
        create=lambda **kw: pytest.fail("nothing may run for a dev channel"),
    )
    assert out["ok"] is False
    assert out["code"] == "channel_not_deployable"


def test_the_route_requires_both_capabilities() -> None:
    server = (Path(release_deliver.__file__).resolve().parent / "server.py").read_text(encoding="utf-8")
    block = server[server.index('if path == "/api/admin/releases/deliver-canary"'):]
    block = block[:block.index("# /api/admin/releases/{id}/{action}")]
    assert '"releases.create"' in block
    assert '"releases.deploy_canary"' in block


def test_the_panel_offers_delivery_without_another_screen() -> None:
    assert "data-stage-deliver" in UI
    assert "releaseDeliverCanary" in UI
    assert "Отправить в Canary" in UI
    assert "Активного релиз-кандидата нет" not in UI, (
        "a missing candidate is not a dead end on this card")


# ---- load charts ------------------------------------------------------------

def test_load_is_charted_only_from_reported_figures() -> None:
    block = UI[UI.index("function loadChartHtml("):UI.index("function stageCardHtml(")]
    assert "Данные недоступны" in block
    for invented in ("cpu", "CPU", "RAM", "memory"):
        assert invented not in block, f"{invented} is not measured anywhere"
    for real in ("duration_ms", "websockets", "accepted", "rejected", "storage"):
        assert real in block
    assert ".env-bar-fill" in CSS


def test_health_reports_measured_storage(tmp_path, monkeypatch) -> None:
    """Pinned to a directory that exists: other suites relocate the data root."""
    from app import runtime_env, server as server_mod

    monkeypatch.setattr(runtime_env, "data_root", lambda: tmp_path)
    storage = server_mod._data_root_storage()
    assert set(storage) >= {"free_mb", "total_mb", "used_mb"}
    assert storage["total_mb"] > 0
    assert storage["free_mb"] <= storage["total_mb"]


def test_storage_is_absent_rather_than_guessed(monkeypatch) -> None:
    from app import server as server_mod

    monkeypatch.setattr(server_mod.shutil, "disk_usage",
                        lambda path: (_ for _ in ()).throw(OSError("no such path")))
    assert server_mod._data_root_storage() == {}


# ---- one summary ------------------------------------------------------------

def test_a_uniform_release_states_what_changed_once() -> None:
    panel = UI[UI.index("function renderEnvironmentTargets("):]
    panel = panel[:panel.index("renderEnvironmentCompareInto")]
    assert "const uniform =" in panel
    assert "stage-shared" in panel
    assert "hide_summary" in panel
    assert "Все среды на версии" in panel
    meta = UI[UI.index("function environmentMetaHtml("):UI.index("function stageStatusHtml(")]
    assert "!target.hide_summary" in meta, "the card must suppress its own copy"
