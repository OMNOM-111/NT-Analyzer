"""Local Cloudflare Tunnel lifecycle for the Telegram Mini App.

Starts ``cloudflared`` as a detached child of the backend process and tracks
its PID in a local state file.  Management endpoints are desktop-only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import runtime_env, telegram_remote


_LOCK = threading.RLock()
_CHILD: Optional[subprocess.Popen] = None

CONFIG_ENV = "NTA_CLOUDFLARED_CONFIG"
EXE_ENV = "NTA_CLOUDFLARED_EXE"
DEFAULT_CONFIG = Path.home() / ".cloudflared" / "config.yml"
DEFAULT_EXE_CANDIDATES = (
    Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
    Path(r"C:\Program Files\cloudflared\cloudflared.exe"),
)


class TunnelManagerError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _state_path() -> Path:
    return runtime_env.data_path(
        "integrations", "cloudflared-tunnel.state.json", project_root=_root(),
    )


def _portable_exe_candidates() -> List[Path]:
    root = _root()
    return [
        root / "tools" / "cloudflared" / "cloudflared.exe",
        root / "tools" / "cloudflared.exe",
        root / "bin" / "cloudflared.exe",
        root / "cloudflared.exe",
    ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_state() -> Dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        import json
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return dict(doc) if isinstance(doc, dict) else {}


def _write_state(doc: Dict[str, Any]) -> None:
    import json
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _config_path() -> Path:
    raw = str(os.environ.get(CONFIG_ENV) or "").strip()
    return Path(raw) if raw else DEFAULT_CONFIG


def _find_executable() -> Path:
    raw = str(os.environ.get(EXE_ENV) or "").strip()
    if raw:
        path = Path(raw)
        if path.is_file():
            return path
        raise TunnelManagerError(f"cloudflared не найден: {path}", 503)
    for candidate in _portable_exe_candidates():
        if candidate.is_file():
            return candidate
    found = shutil.which("cloudflared")
    if found:
        return Path(found)
    for candidate in DEFAULT_EXE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise TunnelManagerError(
        "cloudflared не найден. Положите cloudflared.exe в tools\\cloudflared\\ внутри папки приложения, "
        "установите Cloudflare Tunnel или задайте NTA_CLOUDFLARED_EXE.",
        503,
    )


def _parse_tunnel_ref(config_text: str) -> str:
    for line in config_text.splitlines():
        match = re.match(r"^\s*tunnel:\s*(\S+)\s*$", line)
        if match:
            return match.group(1)
    raise TunnelManagerError("В config.yml не найден ключ tunnel.", 400)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        # OSError is the documented exception; SystemError can also occur on
        # Windows when the process is in a transitional state (WinError 87).
        return False
    return True


def _backend_listening(port: int = 8765) -> bool:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.4)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _probe_public(url: str, *, timeout: float = 12.0) -> Dict[str, Any]:
    target = str(url or "").strip().rstrip("/")
    if not target:
        return {"configured": False, "reachable": False, "status": None, "error": "Публичный URL не задан."}
    check_url = f"{target}/ui/"
    try:
        request = urllib.request.Request(check_url, method="GET", headers={"User-Agent": "StratForge-Tunnel-Probe/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = int(response.status)
            return {"configured": True, "reachable": code < 500, "status": code, "url": check_url, "error": ""}
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        return {
            "configured": True,
            "reachable": code not in {530, 502, 503, 504},
            "status": code,
            "url": check_url,
            "error": "" if code not in {530, 502, 503, 504} else f"HTTP {code}",
        }
    except Exception as exc:
        return {"configured": True, "reachable": False, "status": None, "url": check_url, "error": str(exc)[:200]}


def _tracked_pid() -> int:
    state = _read_state()
    pid = int(state.get("pid") or 0)
    if _pid_alive(pid):
        return pid
    if pid:
        _write_state({})
    return 0


def _spawn_tunnel(exe: Path, config: Path, tunnel_ref: str) -> int:
    global _CHILD
    args = [str(exe), "--config", str(config), "tunnel", "run", tunnel_ref]
    popen_kw: Dict[str, Any] = {
        "cwd": str(config.parent),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)
    with _LOCK:
        proc = subprocess.Popen(args, **popen_kw)
        _CHILD = proc
        _write_state({
            "pid": proc.pid,
            "tunnel": tunnel_ref,
            "config": str(config),
            "exe": str(exe),
            "started_at_utc": _now_iso(),
        })
        return int(proc.pid)


def _stop_pid(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            return False
    return not _pid_alive(pid)


def status(*, port: int = 8765) -> Dict[str, Any]:
    config = _config_path()
    remote = telegram_remote.admin_status()
    public_url = str(remote.get("public_url") or "")
    exe = None
    exe_error = ""
    try:
        exe = _find_executable()
    except TunnelManagerError as exc:
        exe_error = str(exc)

    config_exists = config.is_file()
    tunnel_ref = ""
    config_error = ""
    if config_exists:
        try:
            tunnel_ref = _parse_tunnel_ref(config.read_text(encoding="utf-8"))
        except TunnelManagerError as exc:
            config_error = str(exc)

    pid = _tracked_pid()
    public = _probe_public(public_url) if public_url else {"configured": False, "reachable": False, "status": None, "error": ""}
    running = bool(pid) or bool(public.get("reachable"))
    ready = bool(_backend_listening(port) and running and public.get("reachable") and remote.get("remote_enabled"))

    return {
        "backend": {"listening": _backend_listening(port), "port": port},
        "cloudflared": {
            "installed": bool(exe),
            "exe": str(exe) if exe else "",
            "config": str(config),
            "config_exists": config_exists,
            "tunnel": tunnel_ref,
            "running": running,
            "managed_pid": pid,
            "error": exe_error or config_error,
        },
        "public": public,
        "remote_enabled": bool(remote.get("remote_enabled")),
        "public_url": public_url,
        "ready": ready,
        "message_ru": _status_message(ready, pid, public, remote.get("remote_enabled"), exe_error or config_error),
    }


def _status_message(ready: bool, pid: int, public: Dict[str, Any], remote_enabled: Any, error: str) -> str:
    if ready:
        return "Mini App доступен: туннель и удалённый доступ активны."
    if error:
        return error
    if not pid and not public.get("reachable"):
        return "Туннель не запущен. Нажмите «Запустить Mini App»."
    if not remote_enabled:
        return "Туннель работает, но удалённый доступ выключен в настройках."
    if pid and not public.get("reachable"):
        return "Туннель запускается… подождите 5–15 секунд и обновите статус."
    return "Проверьте backend, туннель и публичный URL."


def start(*, port: int = 8765, wait_sec: float = 12.0) -> Dict[str, Any]:
    if not _backend_listening(port):
        raise TunnelManagerError(f"Backend не слушает 127.0.0.1:{port}. Сначала запустите StratForge AI.", 503)
    if _tracked_pid():
        return status(port=port)
    config = _config_path()
    if not config.is_file():
        raise TunnelManagerError(f"Не найден config.yml: {config}", 404)
    tunnel_ref = _parse_tunnel_ref(config.read_text(encoding="utf-8"))
    exe = _find_executable()
    _spawn_tunnel(exe, config, tunnel_ref)
    deadline = time.time() + max(3.0, float(wait_sec))
    while time.time() < deadline:
        current = status(port=port)
        if current.get("ready") or (current.get("public") or {}).get("reachable"):
            return current
        time.sleep(0.8)
    return status(port=port)


def stop() -> Dict[str, Any]:
    global _CHILD
    pid = _tracked_pid()
    if not pid and _CHILD and _CHILD.poll() is None:
        pid = int(_CHILD.pid)
    if pid:
        _stop_pid(pid)
    with _LOCK:
        _CHILD = None
        _write_state({})
    return status()


def launch(*, port: int = 8765, enable_remote: bool = True) -> Dict[str, Any]:
    """Start tunnel and optionally enable remote access for the Mini App."""
    if enable_remote:
        remote = telegram_remote.admin_status()
        if not remote.get("remote_enabled"):
            if not str(remote.get("public_url") or "").strip():
                raise TunnelManagerError("Сначала сохраните публичный HTTPS URL в настройках Mini App.", 400)
            telegram_remote.update_settings({"remote_enabled": True})
    return start(port=port)
