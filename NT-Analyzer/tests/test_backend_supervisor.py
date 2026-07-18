from __future__ import annotations

import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import backend_supervisor


def _isolate(monkeypatch, tmp_path) -> None:
    state = tmp_path / "backend-supervisor.json"
    history = tmp_path / "backend-restarts.jsonl"
    monkeypatch.setattr(backend_supervisor, "state_path", lambda: state)
    monkeypatch.setattr(backend_supervisor, "history_path", lambda: history)


def _unused_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_supervisor_records_exact_exit_code_and_log_paths(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(backend_supervisor, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        backend_supervisor.runtime_env, "data_path",
        lambda *parts, project_root=None: tmp_path.joinpath(*parts),
    )

    code = backend_supervisor.supervise(
        port=_unused_port(), retry_seconds=1, max_starts=1,
        command=[sys.executable, "-c", "import sys; print('probe'); sys.stderr.write('boom\\n'); raise SystemExit(7)"],
    )

    assert code == 7
    state = json.loads((tmp_path / "backend-supervisor.json").read_text(encoding="utf-8"))
    assert state["last_exit_code"] == 7
    assert state["last_exit_reason"] == "process_error"
    assert state["last_exit"]["stderr_tail"].strip() == "boom"
    assert state["stdout_path"].endswith(".stdout.log")
    assert state["stderr_path"].endswith(".stderr.log")
    assert state["kill_on_supervisor_exit"] is (sys.platform == "win32")


def test_three_crashes_enable_bounded_safe_mode(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    start = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    for offset in (0, 30, 60):
        state = backend_supervisor.record_exit(5, now=start + timedelta(seconds=offset))

    assert state["crash_streak"] == 3
    assert state["safe_mode"] is True
    assert backend_supervisor.safe_mode_active(state, now=start + timedelta(seconds=61)) is True
    assert backend_supervisor.safe_mode_active(state, now=start + timedelta(minutes=20)) is False


def test_windows_forced_exit_keeps_exact_code_and_reason(tmp_path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    state = backend_supervisor.record_exit(0xFFFFFFFF)
    assert state["last_exit_code"] == 4294967295
    assert state["last_exit_reason"] == "signal_or_forced_exit"


def test_scheduled_task_installs_supervisor_as_direct_action() -> None:
    script = (Path(__file__).resolve().parents[1] / "tools" / "install-vitek-background.ps1").read_text(encoding="utf-8")
    assert "-m app.backend_supervisor" in script
    assert "New-ScheduledTaskAction -Execute $python" in script
    assert "-File `\"$escapedLauncher`\"" not in script
