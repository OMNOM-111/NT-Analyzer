from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app import strategy_recovery


CLASS_NAME = "ExactStrategy"
PROFILE_ID = "exact-profile"


def _source_tree(root: Path, *, body: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{CLASS_NAME}.cs").write_text(
        body or f"namespace Test {{ public class {CLASS_NAME} {{ }} }}",
        encoding="utf-8",
    )
    (root / f"{CLASS_NAME}.Entry.cs").write_text("// exact partial", encoding="utf-8")
    return root


def _record(source: Path) -> dict:
    return {
        "class_name": CLASS_NAME,
        "profile_id": PROFILE_ID,
        "source_paths": [str(source)],
        "quarantine_kind": "production_lifecycle",
    }


def _profile() -> dict:
    return {
        "profile_id": PROFILE_ID,
        "strategy_class": CLASS_NAME,
        "instrument": "MNQ 06-26",
        "timeframe": "5 Minute",
        "test_period": {
            "from_utc": "2024-01-01T00:00:00Z",
            "to_utc": "2025-12-31T00:00:00Z",
        },
        "locked_parameters": {
            "RoundTurnCommission": 1.9,
            "SlippageTicks": 1,
        },
        "execution": {
            "calculate": "OnBarClose",
            "order_fill_resolution": "High",
            "slippage_ticks": 1,
            "commission_template": "None",
            "session_template": "CME US Index Futures RTH",
        },
    }


def test_exact_source_accepts_identical_nested_production_copies(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(strategy_recovery.paths, "PROJECT_ROOT", tmp_path)
    outer = _source_tree(tmp_path / "ninjatrader" / "strategies" / "_quarantine" / "Q" / CLASS_NAME)
    inner = _source_tree(outer / CLASS_NAME)

    source, manifest = strategy_recovery.exact_source(_record(outer), CLASS_NAME, PROFILE_ID)

    assert source == inner
    assert set(manifest) == {f"{CLASS_NAME}.cs", f"{CLASS_NAME}.Entry.cs"}


def test_exact_source_rejects_mismatching_quarantine_copies(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(strategy_recovery.paths, "PROJECT_ROOT", tmp_path)
    outer = _source_tree(tmp_path / "ninjatrader" / "strategies" / "_quarantine" / "Q" / CLASS_NAME)
    _source_tree(outer / CLASS_NAME, body=f"public class {CLASS_NAME} {{ int changed = 1; }}")

    with pytest.raises(strategy_recovery.StrategyRecoveryError, match="различаются"):
        strategy_recovery.exact_source(_record(outer), CLASS_NAME, PROFILE_ID)


def test_begin_restores_exact_tree_compiles_then_queues_two_evidence_jobs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(strategy_recovery.paths, "PROJECT_ROOT", tmp_path)
    source = _source_tree(tmp_path / "ninjatrader" / "strategies" / "_quarantine" / "Q" / CLASS_NAME)
    repo_destination = tmp_path / "repo" / CLASS_NAME
    nt_destination = tmp_path / "nt" / CLASS_NAME
    monkeypatch.setattr(strategy_recovery, "_restore_destinations", lambda _class: [repo_destination, nt_destination])
    monkeypatch.setattr(strategy_recovery, "_audit_path", lambda run_id: tmp_path / "audit" / f"{run_id}.json")
    monkeypatch.setattr(strategy_recovery.compile_pipeline, "capture_dll_baseline", lambda: 10.0)
    compile_calls = []
    monkeypatch.setattr(
        strategy_recovery.compile_pipeline,
        "run_compile_chain",
        lambda *args, **kwargs: compile_calls.append((args, kwargs)) or {"ok": True, "in_catalog": True},
    )
    monkeypatch.setattr(
        strategy_recovery, "_enqueue_validation_jobs",
        lambda profile, class_name, run_id, task_id: ["job-oos", "job-stress"],
    )

    result = strategy_recovery.begin(_profile(), _record(source), task_id="VT-ONE", compile_wait_sec=5)

    assert result["ok"] is True
    assert result["job_ids"] == ["job-oos", "job-stress"]
    assert (repo_destination / f"{CLASS_NAME}.cs").is_file()
    assert (nt_destination / f"{CLASS_NAME}.cs").is_file()
    assert compile_calls[0][1]["baseline_mtime"] == 10.0


def test_begin_rolls_back_only_new_exact_copies_when_compile_is_not_confirmed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(strategy_recovery.paths, "PROJECT_ROOT", tmp_path)
    source = _source_tree(tmp_path / "ninjatrader" / "strategies" / "_quarantine" / "Q" / CLASS_NAME)
    repo_destination = tmp_path / "repo" / CLASS_NAME
    nt_destination = tmp_path / "nt" / CLASS_NAME
    monkeypatch.setattr(strategy_recovery, "_restore_destinations", lambda _class: [repo_destination, nt_destination])
    monkeypatch.setattr(strategy_recovery, "_audit_path", lambda run_id: tmp_path / "audit" / f"{run_id}.json")
    monkeypatch.setattr(strategy_recovery.compile_pipeline, "capture_dll_baseline", lambda: 0.0)
    monkeypatch.setattr(
        strategy_recovery.compile_pipeline, "run_compile_chain",
        lambda *args, **kwargs: {"ok": False, "errors": ["compile failed"]},
    )

    result = strategy_recovery.begin(_profile(), _record(source), task_id="VT-TWO", compile_wait_sec=5)

    assert result["ok"] is False
    assert result["reason"] == "compile_not_confirmed"
    assert not repo_destination.exists()
    assert not nt_destination.exists()


def test_validation_jobs_are_oos_and_stricter_slippage_stress(tmp_path, monkeypatch) -> None:
    requests = []
    monkeypatch.setattr(strategy_recovery.jobqueue, "gen_job_id", lambda prefix: prefix)
    monkeypatch.setattr(
        strategy_recovery.jobqueue, "create_job",
        lambda request: requests.append(request) or (request.job_id, tmp_path / request.job_id),
    )

    job_ids = strategy_recovery._enqueue_validation_jobs(
        _profile(), CLASS_NAME, "recovery-run", "VT-THREE",
    )

    assert job_ids == ["recovery-run_oos", "recovery-run_stress"]
    assert [request.slippage_ticks for request in requests] == [1, 2]
    assert all(request.from_utc == "2025-01-01T00:00:00Z" for request in requests)
    assert requests[0].origin["task_id"] == "VT-THREE"
    assert requests[1].origin["variant"] == "stress"
