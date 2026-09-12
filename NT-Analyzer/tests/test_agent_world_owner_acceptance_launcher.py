"""Isolation contracts for the optional owner-review launcher (no server)."""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def launcher():
    path = Path(__file__).resolve().parents[1] / "deploy/testing/agent-world-owner-acceptance.py"
    spec = importlib.util.spec_from_file_location("owner_acceptance_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("port", [8765, 8804, 8810, 80, 0, 65535])
def test_protected_ports_are_rejected(launcher, tmp_path, port):
    with pytest.raises(RuntimeError, match="port_protected"):
        launcher.checked_root(tmp_path, port)


def test_only_named_direct_artifacts_child_is_allowed(launcher, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "CODE", tmp_path)
    good = tmp_path / ".artifacts" / "owner-acceptance-test"
    assert launcher.checked_root(good, 8814)[0] == good
    for bad in (tmp_path, tmp_path / ".artifacts", tmp_path / "data",
                good / "child", tmp_path / ".artifacts" / "foreign"):
        with pytest.raises(RuntimeError, match="outside_exact_ignored_scope"):
            launcher.checked_root(bad, 8814)


def test_unmarked_existing_data_and_wrong_marker_are_never_reused(launcher, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "CODE", tmp_path)
    root = tmp_path / ".artifacts" / "owner-acceptance-test"
    root.mkdir(parents=True)
    (root / "important").write_text("preserve", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unmarked_existing_data"):
        launcher.checked_root(root, 8814)
    (root / launcher.MARKER).write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="marker_mismatch"):
        launcher.checked_root(root, 8814)
    assert (root / "important").read_text() == "preserve"


def test_valid_marker_keeps_fixed_ids_on_restart(launcher, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "CODE", tmp_path)
    root = tmp_path / ".artifacts" / "owner-acceptance-test"
    _, marker = launcher.checked_root(root, 8814)
    root.mkdir(parents=True)
    (root / launcher.MARKER).write_text(json.dumps(marker), encoding="utf-8")
    assert launcher.checked_root(root, 8814)[1] == marker
    assert len(set([marker["owner_id"], *marker["user_ids"]])) == 3
    with pytest.raises(RuntimeError, match="marker_mismatch"):
        launcher.checked_root(root, 8815)


def test_owner_credentials_and_environment_are_not_inherited(launcher, monkeypatch):
    for name in ("OPENAI_API_KEY", "NTA_TELEGRAM_TOKEN", "STRATFORGE_DATABASE_URL",
                 "STRATFORGE_DEVELOPMENT_DATA_ROOT", "STRATFORGE_CANONICAL_OWNER_UUID"):
        monkeypatch.setenv(name, "fixture-not-a-secret")
        assert name not in launcher.clean_environment()
    with pytest.raises(OSError, match="external_network_denied"):
        launcher.loopback_guard("socket.connect", (None, ("203.0.113.1", 443)))
    launcher.loopback_guard("socket.connect", (None, ("127.0.0.1", 8814)))
