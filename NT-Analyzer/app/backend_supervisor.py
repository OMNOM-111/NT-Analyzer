"""Persistent StratForge backend supervisor with a durable restart ledger.

The scheduled PowerShell launcher delegates process ownership here so exit codes,
log locations, crash-loop backoff and safe mode are available to the application
after a restart instead of disappearing with the old Python process.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from . import runtime_env


CRASH_WINDOW_SECONDS = 10 * 60
SAFE_MODE_SECONDS = 15 * 60
CRASH_THRESHOLD = 3
MAX_BACKOFF_SECONDS = 60
DEFAULT_DEVELOPMENT_PUBLIC_ORIGIN = "https://app.stratforges.com"


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _project_root() -> Path:
    configured = str(os.environ.get("NT_ANALYZER_ROOT") or "").strip()
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[1]


def _checkout_identity(project_root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_root, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=project_root, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return "0" * 40, True
    return revision, dirty


def configure_development_profile(
    root: Optional[Path] = None,
    *,
    public_origin: str = DEFAULT_DEVELOPMENT_PUBLIC_ORIGIN,
    apply_environment: bool = True,
) -> Dict[str, str]:
    """Install the explicit local-development environment for Task Scheduler.

    Scheduled tasks do not preserve the launching terminal's environment.  The
    profile is opt-in so a Production supervisor can never inherit these values
    by accident.
    """
    project_root = Path(root or _project_root()).resolve()
    version_path = project_root / "VERSION.json"
    try:
        version = json.loads(version_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"VERSION.json is missing or invalid: {exc}") from exc
    if not isinstance(version, dict) or (
        str(version.get("channel") or "") != "dev"
        or str(version.get("status") or "") != "in_development"
    ):
        raise RuntimeError(
            "Persistent local launcher requires VERSION.json "
            "channel=dev and status=in_development."
        )
    from urllib.parse import urlparse

    parsed = urlparse(str(public_origin or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        raise RuntimeError("Development public origin must be an HTTPS origin without a path.")
    hostname = parsed.hostname.lower()
    computer = str(os.environ.get("COMPUTERNAME") or "local").strip() or "local"
    revision, dirty = _checkout_identity(project_root)
    app_version = str(version.get("version") or "")
    build_timestamp = str(version.get("build_timestamp_utc") or "").strip()
    if not build_timestamp and version.get("build_date"):
        build_timestamp = f"{version['build_date']}T00:00:00Z"
    values = {
        "DEPLOYMENT_ENV": "development",
        "STRATFORGE_ENV": "development",
        "STRATFORGE_INSTANCE_ID": f"stratforge-dev-{computer}",
        "STRATFORGE_DEPLOYMENT_ROLE": "all-in-one",
        "STRATFORGE_CONFIG_PROFILE": "local-development",
        "APP_VERSION": app_version,
        "STRATFORGE_BUILD_VERSION": app_version,
        "STRATFORGE_BUILD_DATE": str(version.get("build_date") or ""),
        "BUILD_TIMESTAMP_UTC": build_timestamp,
        "STRATFORGE_BUILD_TIMESTAMP_UTC": build_timestamp,
        "RELEASE_CHANNEL": "dev",
        "STRATFORGE_RELEASE_CHANNEL": "dev",
        "BUILD_ID": f"dev-{app_version}-{revision[:12]}",
        "STRATFORGE_BUILD_ID": f"dev-{app_version}-{revision[:12]}",
        "GIT_COMMIT_SHA": revision,
        "STRATFORGE_GIT_COMMIT_SHA": revision,
        "ARTIFACT_SHA256": "",
        "STRATFORGE_ARTIFACT_SHA256": "",
        "DIRTY": "1" if dirty else "0",
        "STRATFORGE_BUILD_DIRTY": "1" if dirty else "0",
        "STRATFORGE_REGION": "local",
        "STRATFORGE_BIND_HOST": "127.0.0.1",
        "STRATFORGE_ALLOWED_HOSTS": f"127.0.0.1,localhost,{hostname}",
        "STRATFORGE_PUBLIC_ORIGIN": f"https://{hostname}",
        "STRATFORGE_DEVELOPMENT_DATA_ROOT": str(project_root / "data"),
        "STRATFORGE_DATA_ROOT": str(project_root / ".stratforge-production-data-disabled"),
        "STRATFORGE_DATABASE_ID": "development-sqlite",
        "STRATFORGE_QUEUE_ID": "development-local-worker",
        "STRATFORGE_OBJECT_STORAGE_ID": "development-files",
        "STRATFORGE_TELEGRAM_BOT_ID": "development-local",
        "STRATFORGE_COOKIE_NAMESPACE": "sf-dev",
        "STRATFORGE_SIGNING_KEY_ID": "development-local",
        "STRATFORGE_LOG_NAMESPACE": "development",
        "STRATFORGE_LIVE_TRADING_ALLOWED": "0",
        "STRATFORGE_REAL_PAYMENTS_ALLOWED": "0",
        "NT_ANALYZER_ROOT": str(project_root),
        # Local Development is a single-operator loopback sandbox: grant the
        # owner session automatically without Telegram so the app never opens in
        # guest mode on the owner's own machine. This bypass is loopback-only
        # (see server._authorize_api / _is_remote_api_request) and is hard
        # rejected in Production by runtime_env.assert_startup_safe().
        "NTA_TEST_BYPASS_AUTH": "1",
        "NTA_VITEK_BACKGROUND": "1",
    }
    if not values["APP_VERSION"] or not values["BUILD_TIMESTAMP_UTC"]:
        raise RuntimeError("VERSION.json must define version and build_timestamp_utc.")
    if apply_environment:
        os.environ.update(values)
    return values


def state_path() -> Path:
    return runtime_env.data_path("operations", "backend-supervisor.json", project_root=_project_root())


def history_path() -> Path:
    return runtime_env.data_path("operations", "backend-restarts.jsonl", project_root=_project_root())


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _append_history(value: Dict[str, Any]) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def _recent_crashes(rows: Iterable[Any], *, now: Optional[datetime] = None) -> list[str]:
    current = now or _now_dt()
    result = []
    for value in rows:
        parsed = _parse_time(value)
        if parsed and 0 <= (current - parsed).total_seconds() <= CRASH_WINDOW_SECONDS:
            result.append(parsed.isoformat(timespec="seconds").replace("+00:00", "Z"))
    return result[-20:]


def safe_mode_active(state: Optional[Dict[str, Any]] = None, *, now: Optional[datetime] = None) -> bool:
    doc = dict(state or _read_json(state_path()))
    until = _parse_time(doc.get("safe_mode_until_utc"))
    return bool(doc.get("safe_mode") and until and until > (now or _now_dt()))


def record_start(*, pid: int, port: int, stdout_path: str, stderr_path: str,
                 safe_mode: bool, kill_on_supervisor_exit: bool = False) -> Dict[str, Any]:
    path = state_path()
    doc = _read_json(path)
    doc.update({
        "schema_version": 1, "supervisor_pid": os.getpid(), "backend_pid": int(pid),
        "port": int(port), "status": "running", "started_at_utc": _now(),
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
        "safe_mode": bool(safe_mode),
        "kill_on_supervisor_exit": bool(kill_on_supervisor_exit),
        "updated_at_utc": _now(),
    })
    _write_json(path, doc)
    _append_history({
        "at_utc": _now(), "event": "backend_started", "pid": int(pid),
        "port": int(port), "safe_mode": bool(safe_mode),
        "kill_on_supervisor_exit": bool(kill_on_supervisor_exit),
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
    })
    return doc


def record_exit(exit_code: int, *, stderr_tail: str = "", now: Optional[datetime] = None) -> Dict[str, Any]:
    current = now or _now_dt()
    path = state_path()
    doc = _read_json(path)
    code = int(exit_code)
    abnormal = code != 0
    crashes = _recent_crashes(doc.get("recent_crashes_at_utc") or [], now=current)
    if abnormal:
        crashes.append(current.isoformat(timespec="seconds").replace("+00:00", "Z"))
    crash_streak = len(crashes)
    safe_mode = crash_streak >= CRASH_THRESHOLD
    safe_until = (
        current + timedelta(seconds=SAFE_MODE_SECONDS)
    ).isoformat(timespec="seconds").replace("+00:00", "Z") if safe_mode else ""
    # POSIX reports signals as negative return codes. Windows exposes forced
    # termination/NTSTATUS values as unsigned DWORDs (for example 0xFFFFFFFF),
    # so retain the exact integer while classifying the high-bit range honestly.
    forced_or_signal = code < 0 or code >= 0x80000000
    reason = "clean_exit" if code == 0 else "signal_or_forced_exit" if forced_or_signal else "process_error"
    exit_row = {
        "at_utc": current.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "event": "backend_exited", "exit_code": code, "reason": reason,
        "abnormal": abnormal, "stderr_tail": str(stderr_tail or "")[-8000:],
        "crash_streak": crash_streak, "safe_mode": safe_mode,
    }
    doc.update({
        "schema_version": 1, "status": "stopped", "backend_pid": 0,
        "last_exit": exit_row, "last_exit_code": code, "last_exit_reason": reason,
        "last_exit_at_utc": exit_row["at_utc"], "recent_crashes_at_utc": crashes,
        "crash_streak": crash_streak, "safe_mode": safe_mode,
        "safe_mode_until_utc": safe_until,
        "restart_count": int(doc.get("restart_count") or 0) + 1,
        "updated_at_utc": exit_row["at_utc"],
    })
    _write_json(path, doc)
    _append_history(exit_row)
    return doc


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.8):
            return True
    except OSError:
        return False


def _stderr_tail(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-8000:].decode("utf-8", errors="replace")


def _attach_windows_kill_job(process: subprocess.Popen[Any]) -> Any:
    """Put the backend in a kill-on-close Job Object owned by the supervisor."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    info = ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel32.CloseHandle(handle)
        return None
    process_handle = wintypes.HANDLE(int(getattr(process, "_handle", 0) or 0))
    if not process_handle or not kernel32.AssignProcessToJobObject(handle, process_handle):
        kernel32.CloseHandle(handle)
        return None
    return (kernel32, handle)


def _close_windows_kill_job(job: Any) -> None:
    if job:
        kernel32, handle = job
        kernel32.CloseHandle(handle)


def supervise(*, port: int = 8765, retry_seconds: int = 10,
              max_starts: int = 0, command: Optional[list[str]] = None) -> int:
    root = _project_root()
    log_dir = runtime_env.data_path("logs", project_root=root)
    log_dir.mkdir(parents=True, exist_ok=True)
    starts = 0
    while max_starts <= 0 or starts < max_starts:
        if _port_open(port):
            time.sleep(max(1, min(10, int(retry_seconds))))
            continue
        previous = _read_json(state_path())
        safe = safe_mode_active(previous)
        stamp = _now_dt().strftime("%Y%m%dT%H%M%S%f")
        stdout_path = log_dir / f"backend-{stamp}.stdout.log"
        stderr_path = log_dir / f"backend-{stamp}.stderr.log"
        child_env = dict(os.environ)
        child_env.update({
            "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
            "NT_ANALYZER_ROOT": str(root), "NTA_VITEK_BACKGROUND": "1",
            "NTA_BACKEND_SUPERVISED": "1", "NTA_SAFE_MODE": "1" if safe else "0",
        })
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                list(command or [sys.executable, "-m", "app.server", str(int(port))]),
                cwd=str(root), env=child_env, stdout=stdout, stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            kill_job = _attach_windows_kill_job(process)
            record_start(
                pid=int(process.pid), port=int(port), stdout_path=str(stdout_path),
                stderr_path=str(stderr_path), safe_mode=safe,
                kill_on_supervisor_exit=bool(kill_job),
            )
            try:
                code = int(process.wait())
            finally:
                _close_windows_kill_job(kill_job)
        state = record_exit(code, stderr_tail=_stderr_tail(stderr_path))
        starts += 1
        if max_starts > 0 and starts >= max_starts:
            return code
        streak = int(state.get("crash_streak") or 0) if code else 0
        backoff = min(MAX_BACKOFF_SECONDS, max(1, int(retry_seconds)) * (2 ** max(0, streak - 1)))
        time.sleep(backoff)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Supervise the StratForge backend")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--retry-seconds", type=int, default=10)
    parser.add_argument("--max-starts", type=int, default=0,
                        help="0 keeps supervising; positive values are intended for tests")
    parser.add_argument(
        "--development-profile", action="store_true",
        help="load the explicit local Development profile before starting",
    )
    parser.add_argument(
        "--development-public-origin",
        default=DEFAULT_DEVELOPMENT_PUBLIC_ORIGIN,
        help="canonical HTTPS origin allowed by the Development background task",
    )
    args = parser.parse_args(argv)
    if args.development_profile:
        configure_development_profile(public_origin=args.development_public_origin)
    return supervise(
        port=max(1, min(65535, args.port)),
        retry_seconds=max(1, args.retry_seconds), max_starts=max(0, args.max_starts),
    )


if __name__ == "__main__":
    raise SystemExit(main())
