from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import telegram_remote
from app import tunnel_manager


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(tunnel_manager, "_root", lambda: tmp_path)
    monkeypatch.setattr(telegram_remote, "_root", lambda: tmp_path)
    monkeypatch.setattr(tunnel_manager, "DEFAULT_CONFIG", tmp_path / "config.yml")
    monkeypatch.setattr(tunnel_manager, "DEFAULT_EXE_CANDIDATES", ())
    monkeypatch.setenv("NTA_CLOUDFLARED_EXE", str(tmp_path / "cloudflared.exe"))
    (tmp_path / "cloudflared.exe").write_text("", encoding="utf-8")
    (tmp_path / "config.yml").write_text(
        "tunnel: test-tunnel-id\ncredentials-file: creds.json\n"
        "ingress:\n  - hostname: app.example.com\n    service: http://localhost:8765\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )
    telegram_remote._write({
        "remote_enabled": False,
        "public_url": "https://app.example.com",
        "users": [],
        "pairings": [],
    })
    return tmp_path


def test_status_reports_backend_and_config(isolated, monkeypatch) -> None:
    monkeypatch.setattr(tunnel_manager, "_backend_listening", lambda port=8765: True)
    monkeypatch.setattr(tunnel_manager, "_tracked_pid", lambda: 0)
    monkeypatch.setattr(
        tunnel_manager,
        "_probe_public",
        lambda url, timeout=12.0: {"configured": True, "reachable": False, "status": 530, "error": "HTTP 530"},
    )
    doc = tunnel_manager.status()
    assert doc["backend"]["listening"] is True
    assert doc["cloudflared"]["tunnel"] == "test-tunnel-id"
    assert doc["ready"] is False
    assert "не запущен" in doc["message_ru"].lower()


def test_launch_enables_remote_and_starts_tunnel(isolated, monkeypatch) -> None:
    monkeypatch.setattr(tunnel_manager, "_backend_listening", lambda port=8765: True)
    monkeypatch.setattr(tunnel_manager, "_spawn_tunnel", lambda exe, config, tunnel_ref: 4242)
    monkeypatch.setattr(tunnel_manager, "_tracked_pid", lambda: 4242)
    monkeypatch.setattr(
        tunnel_manager,
        "_probe_public",
        lambda url, timeout=12.0: {"configured": True, "reachable": True, "status": 200, "error": ""},
    )
    doc = tunnel_manager.launch(enable_remote=True)
    assert doc["remote_enabled"] is True
    assert doc["ready"] is True
    stored = json.loads((isolated / "data" / "integrations" / "telegram.remote-access.json").read_text(encoding="utf-8"))
    assert stored["remote_enabled"] is True


def test_stop_clears_state(isolated, monkeypatch) -> None:
    tunnel_manager._write_state({"pid": 99999, "tunnel": "test-tunnel-id"})
    monkeypatch.setattr(tunnel_manager, "_pid_alive", lambda pid: pid == 99999)
    monkeypatch.setattr(tunnel_manager, "_stop_pid", lambda pid: True)
    monkeypatch.setattr(tunnel_manager, "_backend_listening", lambda port=8765: True)
    monkeypatch.setattr(tunnel_manager, "_tracked_pid", lambda: 0)
    monkeypatch.setattr(
        tunnel_manager,
        "_probe_public",
        lambda url, timeout=12.0: {"configured": True, "reachable": False, "status": None, "error": ""},
    )
    tunnel_manager.stop()
    assert tunnel_manager._read_state() == {}
