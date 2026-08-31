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

def test_first_level_shows_the_four_figures_an_owner_reads() -> None:
    block = UI[UI.index("function loadChartHtml("):UI.index("function technicalMetricsHtml(")]
    for label in ("CPU", "RAM", "Диск", "Запросы"):
        assert label in block
    assert "Данные недоступны" in block


def test_diagnostics_leave_the_first_level_but_are_not_removed() -> None:
    technical = UI[UI.index("function technicalMetricsHtml("):UI.index("function stageCardHtml(")]
    assert "Технические данные / Метрики" in technical
    for kept in ("p50", "p95", "p99", "WebSocket", "Принято", "Отклонено"):
        assert kept in technical
    # Slice to the comment that introduces the diagnostics block: prose about
    # what moved is not the same as the markup still rendering it.
    first_level = UI[UI.index("function loadChartHtml("):UI.index("  // Kept, but off the first level")]
    for moved in ("p95", "WebSocket", "Отклонено"):
        assert moved not in first_level


def test_one_threshold_scale_defined_once() -> None:
    assert "const LOAD_THRESHOLDS = { elevated: 60, high: 80, critical: 92 };" in UI
    level = UI[UI.index("function loadLevel("):UI.index("function loadGaugeHtml(")]
    for name in ("critical", "high", "elevated", "normal"):
        assert name in level
    # Every gauge must classify through the one function, not its own numbers.
    block = UI[UI.index("function loadGaugeHtml("):UI.index("function technicalMetricsHtml(")]
    assert block.count("loadLevel(") >= 2
    for colour in ("is-normal", "is-elevated", "is-high", "is-critical"):
        assert ".load-gauge." + colour in CSS


def test_a_figure_that_was_not_measured_is_named_not_drawn() -> None:
    gauge = UI[UI.index("function loadGaugeHtml("):UI.index("function loadChartHtml(")]
    assert "нет данных" in gauge
    assert "percent == null" in gauge


def test_host_metrics_are_measured_or_absent() -> None:
    from app import host_metrics

    reading = host_metrics.sample(".")
    for key in ("cpu_percent", "memory_percent", "disk_percent"):
        if key in reading:
            assert 0.0 <= reading[key] <= 100.0
    # Nothing is ever filled in with a placeholder.
    assert None not in reading.values()


def test_host_metrics_report_nothing_on_an_unsupported_platform(monkeypatch) -> None:
    from app import host_metrics

    monkeypatch.setattr(host_metrics.sys, "platform", "sunos5")
    monkeypatch.setattr(host_metrics, "_CACHE", None)
    assert host_metrics.cpu_percent() is None
    assert host_metrics.memory_percent() is None
    assert host_metrics.source() == ""


def test_reported_host_load_is_validated_before_it_is_stored() -> None:
    from app import environment_registry as registry

    clean = registry._normalize_host({
        "cpu_percent": 42.4, "memory_percent": 0, "disk_percent": 100,
        "source": "proc",
    })
    assert clean == {"cpu_percent": 42.4, "memory_percent": 0.0,
                     "disk_percent": 100.0, "source": "proc"}
    # A peer sends this over the network: anything out of range or not a number
    # is dropped rather than clamped, so nonsense cannot pass as a reading.
    rejected = registry._normalize_host({
        "cpu_percent": 140, "memory_percent": -3, "disk_percent": "80",
    })
    assert rejected == {}
    assert registry._normalize_host({"cpu_percent": True}) == {}
    assert registry._normalize_host("nonsense") == {}


def test_an_environment_reports_its_own_load() -> None:
    from app import environment_registry as registry

    heartbeat = registry.self_heartbeat()
    assert "host" in heartbeat
    row = registry.public_row(dict(heartbeat, last_seen_at=registry._now()))
    assert isinstance(row["host"], dict)


def test_the_registry_can_store_what_the_heartbeat_reports() -> None:
    """The failure 0017 documents: a field reported but with no column."""
    from pathlib import Path

    core = (Path(release_deliver.__file__).resolve().parent
            / "production_storage" / "core.py").read_text(encoding="utf-8")
    block = core[core.index("INSERT INTO sf_environment_registry"):]
    block = block[:block.index("RETURNING")]
    assert "host" in block
    assert "host=EXCLUDED.host" in block
    migrations = (Path(release_deliver.__file__).resolve().parent
                  / "production_storage" / "migrations")
    assert any("host" in path.name for path in migrations.iterdir())


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
