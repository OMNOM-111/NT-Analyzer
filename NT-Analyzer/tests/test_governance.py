"""Smoke tests for governance source-of-truth files.

Run: python -m tests.test_governance
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import governance  # noqa: E402


@pytest.fixture(autouse=True)
def seed_canonical_governance() -> None:
    """Give each test tracked baselines without reading workstation state."""
    source = ROOT / "data" / "governance"
    target = Path(os.environ["NTA_DATA_ROOT"]) / "governance"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("goals.json", "documents.json", "laws.json", "change_log.jsonl"):
        shutil.copy2(source / name, target / name)


def test_runtime_defaults_shape() -> None:
    defaults = governance.runtime_defaults()
    assert defaults["starting_capital"] > 0
    assert defaults["round_turn_commission"] > 0
    assert defaults["slippage_ticks"] >= 1
    assert defaults["order_fill_resolution"] == "High"


def test_governance_documents_exist() -> None:
    docs = {row["id"]: row for row in governance.list_documents()}
    for required in ("project-overview", "charter", "roles", "laws", "local-ai-laws", "registry-policy", "sync-map", "ai-lab-competitive-feedback"):
        assert required in docs, f"missing document registry row: {required}"
        assert Path(docs[required]["abs_path"]).is_file(), f"missing file for {required}"


def test_charter_is_mission_led_and_legal_package_remains_draft() -> None:
    charter = governance.read_document("charter")["content"]
    assert "## Миссия" in charter
    assert "Автотрейдинг — ещё лучше" in charter
    assert "TopstepX" in charter
    assert "Google и e-mail identity paths" in charter
    legal = [row for row in governance.list_documents() if row["id"].startswith("legal-")]
    assert len(legal) == 9
    assert all(row["draft"] is True for row in legal)


def test_competitive_feedback_law_is_registered() -> None:
    laws = {row["id"]: row for row in governance.load_laws().get("laws", [])}
    law = laws.get("GOV-AI-017")
    assert law, "competitive feedback law must be registered"
    assert law["audience"] == "local_ai"
    assert law["value"] is True
    assert "AI_LAB_COMPETITIVE_FEEDBACK.md" in " ".join(law.get("source_refs") or [])


def test_north_star_goal_is_registered_and_readable() -> None:
    goals = governance.read_goals()
    north = goals.get("north_star")
    assert isinstance(north, dict) and north, "north_star goal must be configured"
    assert north["target_usd"] == 100000
    assert north["deadline"] == "2026-12-31"
    assert len(north.get("milestones") or []) == 4
    # registered as a governance document and the markdown file exists
    docs = {row["id"]: row for row in governance.list_documents()}
    assert "north-star-2026" in docs
    assert Path(docs["north-star-2026"]["abs_path"]).is_file()


def test_north_star_progress_shape() -> None:
    progress = governance.north_star_progress()
    assert progress["configured"] is True
    assert progress["target_usd"] == 100000
    assert progress["deadline"] == "2026-12-31"
    # progress/remaining come from runtime realized PnL; keys must always exist
    for key in ("progress_usd", "remaining_usd", "progress_pct", "days_left", "pace_required_usd_per_day"):
        assert key in progress


def test_change_log_reader_shape() -> None:
    entries = governance.read_change_log(10)
    assert isinstance(entries, list)
    for entry in entries:
        assert "amendment_no" in entry
        assert "ts_utc" in entry
        assert "actor" in entry
        assert "changes" in entry


def test_law_update_writes_history_and_overview() -> None:
    previous_root = os.environ.get("NT_ANALYZER_ROOT")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "NT-Analyzer"
        (root / "app").mkdir(parents=True, exist_ok=True)
        os.environ["NT_ANALYZER_ROOT"] = str(root)
        try:
            governance.ensure_governance_files(render=True)
            result = governance.update_law(
                "GOV-RISK-001",
                {"value": "10000", "reason": "raise capital default"},
                actor="test_owner",
            )
            assert result["history_entry"]["entity_id"] == "GOV-RISK-001"
            assert result["history_entry"]["actor"] == "test_owner"
            entries = governance.read_change_log(10)
            assert entries
            assert entries[0]["changes"][0]["after_text"] == "10000.00 USD"
            overview = (governance.docs_dir() / "OVERVIEW.md").read_text(encoding="utf-8")
            assert "10000.00 USD" in overview
        finally:
            if previous_root is None:
                os.environ.pop("NT_ANALYZER_ROOT", None)
            else:
                os.environ["NT_ANALYZER_ROOT"] = previous_root


def test_explicit_production_renders_governance_outside_immutable_release(
    tmp_path, monkeypatch,
) -> None:
    release_root = (tmp_path / "release").resolve()
    data_root = (tmp_path / "persistent-runtime").resolve()
    (release_root / "app").mkdir(parents=True)
    monkeypatch.setenv("NT_ANALYZER_ROOT", str(release_root))
    monkeypatch.setenv("STRATFORGE_ENV", "production")
    monkeypatch.delenv("NTA_APP_ENV", raising=False)
    monkeypatch.delenv("NTA_ENV", raising=False)
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(data_root))

    rendered = governance.docs_dir()
    assert rendered == data_root / "governance-rendered"
    assert release_root not in rendered.parents
    governance.ensure_governance_files(render=True)
    assert (rendered / "README.md").is_file()
    assert not (release_root / "docs" / "governance").exists()


def test_explicit_fallback_data_root_never_renders_tracked_docs(
    tmp_path, monkeypatch,
) -> None:
    """A fallback root is still an explicit isolation boundary for tests."""
    data_root = (tmp_path / "isolated-data").resolve()
    monkeypatch.setenv("NTA_DATA_ROOT", str(data_root))
    for name in ("DEPLOYMENT_ENV", "STRATFORGE_ENV", "NTA_APP_ENV", "NTA_ENV"):
        monkeypatch.delenv(name, raising=False)

    rendered = governance.docs_dir()
    assert rendered == data_root / "governance-rendered"
    assert rendered != ROOT / "docs" / "governance"


def test_implicit_library_import_does_not_rewrite_tracked_governance(
    tmp_path,
) -> None:
    project = tmp_path / "NT-Analyzer"
    (project / "app").mkdir(parents=True)
    rendered = project / "docs" / "governance"
    rendered.mkdir(parents=True)
    sentinel = rendered / "README.md"
    sentinel.write_text("tracked governance sentinel\n", encoding="utf-8")

    env = os.environ.copy()
    env["NT_ANALYZER_ROOT"] = str(project)
    for name in ("DEPLOYMENT_ENV", "STRATFORGE_ENV", "NTA_APP_ENV", "NTA_ENV"):
        env.pop(name, None)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), env.get("PYTHONPATH", "")) if part
    )

    result = subprocess.run(
        [sys.executable, "-c", "import app.governance"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert sentinel.read_text(encoding="utf-8") == "tracked governance sentinel\n"


def main() -> int:
    test_runtime_defaults_shape()
    test_governance_documents_exist()
    test_competitive_feedback_law_is_registered()
    test_change_log_reader_shape()
    test_law_update_writes_history_and_overview()
    print("test_governance: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
