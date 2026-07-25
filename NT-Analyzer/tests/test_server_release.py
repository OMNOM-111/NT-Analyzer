from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from tools import build_server_release


def test_server_release_selection_is_runtime_bounded() -> None:
    selected = {
        path.as_posix() for path in build_server_release._selected_files(
            Path(__file__).resolve().parent.parent,
        )
    }
    assert "app/server.py" in selected
    assert "app/production_telegram.py" in selected
    assert "deploy/production/stratforge-operations.timer" in selected
    assert "docs/PRODUCTION_DEPLOYMENT_RUNBOOK.md" in selected
    assert "tools/production_preflight.py" in selected
    assert "tests/test_server_release.py" not in selected
    assert "bridge/NTAnalyzerBridge.csproj" not in selected
    assert "docs/AGENTS.md" not in selected
    assert "docs/AI_DIALOGUE_CONTRACT.md" not in selected


def test_server_production_release_cannot_use_development_key(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv("STRATFORGE_RELEASE_SIGNING_KEY_PEM", raising=False)
    monkeypatch.delenv("STRATFORGE_RELEASE_SIGNING_KEY_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="STRATFORGE_RELEASE_SIGNING_KEY_PEM"):
        build_server_release._load_signing_key(tmp_path, True)


def test_server_release_channel_cannot_be_mislabeled(monkeypatch) -> None:
    monkeypatch.setattr(
        build_server_release,
        "_git_state",
        lambda root: ("f" * 40, False),
    )
    args = argparse.Namespace(
        version="0.9.0-dev.3", channel="canary", production=False, force=False,
    )
    with pytest.raises(RuntimeError, match="must remain development"):
        build_server_release.build(args)
