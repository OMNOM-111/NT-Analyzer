from __future__ import annotations

import json

import pytest

from app import release_executor


def _configure(monkeypatch, tmp_path):
    key = tmp_path / "release-ssh-key"
    key.write_text("test-only", encoding="utf-8")
    monkeypatch.setenv("STRATFORGE_RELEASE_DEPLOY_ADAPTER", "stage9_ssh")
    monkeypatch.setenv("STRATFORGE_RELEASE_SSH_HOST", "ssh-canary.example.test")
    monkeypatch.setenv("STRATFORGE_RELEASE_SSH_USER", "stratforge")
    monkeypatch.setenv("STRATFORGE_RELEASE_SSH_KEY", str(key))
    monkeypatch.setenv("STRATFORGE_RELEASE_SSH_PROXY_COMMAND", "")
    monkeypatch.setattr(release_executor.shutil, "which", lambda name: "C:/tools/" + name)
    return key


def test_status_is_fail_closed_and_redacted(monkeypatch, tmp_path):
    key = _configure(monkeypatch, tmp_path)
    status = release_executor.status()
    assert status["real_available"] is True
    assert status["canary_available"] is True
    assert status["production_available"] is False
    serialized = json.dumps(status)
    assert "ssh-canary.example.test" not in serialized
    assert str(key) not in serialized


def test_production_requires_separate_process_gate(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    assert release_executor.status()["production_available"] is False
    monkeypatch.setenv("STRATFORGE_RELEASE_PRODUCTION_EXECUTION", "owner_approved")
    assert release_executor.status()["production_available"] is True


def test_unknown_adapter_never_becomes_available(monkeypatch):
    monkeypatch.setenv("STRATFORGE_RELEASE_DEPLOY_ADAPTER", "unknown-real-adapter")
    status = release_executor.status()
    assert status["real_configured"] is False
    assert status["real_available"] is False


def test_result_parser_requires_verified_prefixed_json():
    payload = {"ok": True, "git_commit_sha": "a" * 40}
    parsed = release_executor._parse_result(
        ("diagnostic\nSTRATFORGE_RESULT=" + json.dumps(payload) + "\n").encode()
    )
    assert parsed == payload
    with pytest.raises(release_executor.ReleaseExecutorError):
        release_executor._parse_result(b'{"ok":true}\n')


def test_remote_argument_rejects_shell_metacharacters(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    with pytest.raises(release_executor.ReleaseExecutorError):
        release_executor._run_remote("build", "0.10.0-beta.1;touch", "beta", "a" * 40)
