"""Environment bootstrap for AI Strategy Lab.

The bootstrap is intentionally conservative: it can start known local
processes and ask LM Studio CLI to load configured models, but it never logs in
to NinjaTrader, starts trading, or hides missing operator setup.
"""

from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import lm_studio, paths
from .io_utils import append_jsonl, read_json


DEFAULT_TIMEOUT_SEC = int(os.environ.get("AI_LAB_BOOTSTRAP_TIMEOUT_SEC", "300"))
POLL_SEC = float(os.environ.get("AI_LAB_BOOTSTRAP_POLL_SEC", "3"))
AUTOSTART_NT_ENV = "NTA_ALLOW_AUTOSTART_NINJATRADER"

_LOADED_MODEL_LOCK = threading.Lock()
_LOADED_MODEL: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_path() -> Path:
    return paths.AI_LAB_DIR / "bootstrap.json"


def log_path() -> Path:
    return paths.REGISTRY_DIR / "bootstrap_log.jsonl"


def _config() -> Dict[str, Any]:
    data = read_json(config_path(), {})
    return data if isinstance(data, dict) else {}


def _conf_value(key: str, env_key: str) -> str:
    val = os.environ.get(env_key)
    if val:
        return val
    raw = _config().get(key)
    return str(raw).strip() if raw else ""


def _log(action: str, **fields: Any) -> None:
    try:
        append_jsonl(log_path(), {"timestamp_utc": _now(), "action": action, **fields})
    except OSError:
        pass


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _tasklist_contains(needle: str) -> Optional[bool]:
    if not _is_windows():
        return None
    tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        completed = subprocess.run(
            [str(tasklist), "/FO", "CSV", "/NH"],
            capture_output=True,
            text=False,
            timeout=4,
            startupinfo=startupinfo,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    haystack = ((completed.stdout or b"") + b"\n" + (completed.stderr or b"")).decode(
        "utf-8", errors="ignore"
    ).lower()
    return needle.lower() in haystack


def _existing_path(candidates: Iterable[str]) -> str:
    for raw in candidates:
        if not raw:
            continue
        p = Path(os.path.expandvars(raw)).expanduser()
        if p.exists():
            return str(p)
    return ""


def _lm_studio_exe() -> str:
    configured = _conf_value("lm_studio_exe", "LM_STUDIO_EXE")
    local_app = os.environ.get("LOCALAPPDATA", "")
    return _existing_path([
        configured,
        str(Path(local_app) / "Programs" / "LM Studio" / "LM Studio.exe") if local_app else "",
        str(Path.home() / "AppData" / "Local" / "Programs" / "LM Studio" / "LM Studio.exe"),
    ])


def _ninjatrader_exe() -> str:
    configured = _conf_value("ninjatrader_exe", "NINJATRADER_EXE")
    return _existing_path([
        configured,
        r"C:\Program Files\NinjaTrader 8\bin64\NinjaTrader.exe",
        r"C:\Program Files\NinjaTrader 8\bin\NinjaTrader.exe",
        r"C:\Program Files (x86)\NinjaTrader 8\bin64\NinjaTrader.exe",
        r"C:\Program Files (x86)\NinjaTrader 8\bin\NinjaTrader.exe",
    ])


def _bridge_paths() -> tuple[Path, Path]:
    build_root = paths.PROJECT_ROOT / "bridge" / "bin"
    candidates = [
        build_root / "Release" / "NTAnalyzerBridge.dll",
        build_root / "Debug" / "NTAnalyzerBridge.dll",
    ]
    existing = [path for path in candidates if path.exists()]
    built = max(existing, key=lambda path: path.stat().st_mtime) if existing else candidates[-1]
    live = paths.nt_user_home() / "Documents" / "NinjaTrader 8" / "bin" / "Custom" / "NTAnalyzerBridge.dll"
    return built, live


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def bridge_deployment_status() -> Dict[str, Any]:
    built, live = _bridge_paths()
    built_hash = _file_sha256(built)
    live_hash = _file_sha256(live)
    return {
        "built_path": str(built), "live_path": str(live),
        "built_exists": built.exists(), "live_exists": live.exists(),
        "up_to_date": bool(built_hash and built_hash == live_hash),
        "pending": bool(built_hash and built_hash != live_hash),
        "built_sha256": built_hash[:16] or None,
        "live_sha256": live_hash[:16] or None,
    }


def _deploy_bridge_if_safe(nt_running: Optional[bool]) -> Dict[str, Any]:
    state = bridge_deployment_status()
    if not state["pending"]:
        return {"ok": True, "status": "up_to_date", **state}
    if nt_running is True:
        return {"ok": True, "status": "deferred_until_ninjatrader_restart", **state}
    built, live = _bridge_paths()
    try:
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, live)
    except OSError as exc:
        return {"ok": False, "status": "deploy_failed", "error": str(exc), **state}
    fresh = bridge_deployment_status()
    return {"ok": bool(fresh["up_to_date"]), "status": "deployed", **fresh}


def _lms_cli() -> str:
    configured = _conf_value("lms_cli", "LMS_CLI")
    if configured and Path(os.path.expandvars(configured)).expanduser().exists():
        return str(Path(os.path.expandvars(configured)).expanduser())
    return shutil.which("lms") or ""


def _start_process(exe: str, label: str) -> Dict[str, Any]:
    if not exe:
        return {"ok": False, "status": "config_missing", "message": f"{label} exe path is not configured"}
    try:
        subprocess.Popen([exe], cwd=str(Path(exe).parent))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "start_failed", "error": str(exc)}
    _log("process_started", label=label, exe=exe)
    return {"ok": True, "status": "started", "exe": exe}


def _required_models() -> List[str]:
    models: List[str] = []
    for role in lm_studio.RUN_REQUIRED_ROLES:
        try:
            model = lm_studio.model_for(role)
        except lm_studio.LMStudioError:
            continue
        if model not in models:
            models.append(model)
    return models


def _run_lms(args: List[str], timeout: int = 60) -> Dict[str, Any]:
    cli = _lms_cli()
    if not cli:
        return {"ok": False, "status": "cli_missing", "command": ["lms", *args]}
    try:
        completed = subprocess.run(
            [cli, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "subprocess_failed", "command": [cli, *args], "error": str(exc)}
    out = {
        "ok": completed.returncode == 0,
        "status": "ok" if completed.returncode == 0 else "failed",
        "command": [cli, *args],
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-1000:],
        "stderr": (completed.stderr or "")[-1000:],
    }
    _log("lms_command", **out)
    return out


def lazy_mode_enabled() -> bool:
    return os.environ.get("AI_LAB_LAZY_LM_STUDIO", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def auto_unload_enabled() -> bool:
    return os.environ.get("AI_LAB_AUTO_UNLOAD_MODELS", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def auto_stop_server_enabled() -> bool:
    # Keep the lightweight API server alive between strategy iterations. Models
    # are still unloaded to release VRAM, but stopping the server made every
    # next iteration look like an LM Studio outage and triggered needless
    # restart attempts. Operators can opt back into full shutdown explicitly.
    return os.environ.get("AI_LAB_AUTO_STOP_LM_SERVER", "0").strip().lower() not in {
        "0", "false", "no", "off",
    }


def ninjatrader_autostart_allowed() -> bool:
    """Return the explicit owner opt-in for launching NinjaTrader.exe.

    Keeping this default-off avoids opening the login dialog unexpectedly after
    a reboot, which can contribute to account lockouts.
    """
    return os.environ.get(AUTOSTART_NT_ENV, "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def ensure_server(timeout_sec: int = 90) -> Dict[str, Any]:
    """Start LM Studio server if needed, without loading any model."""
    h = lm_studio.health(timeout=5)
    if h.get("available"):
        return {"ok": True, "status": "already_available", "health": h}
    proc = _tasklist_contains("lm studio")
    started_process: Dict[str, Any] = {"skipped": True}
    if proc is not True:
        started_process = _start_process(_lm_studio_exe(), "LM Studio")
    server_start = _run_lms(["server", "start"], timeout=45)
    deadline = time.time() + max(10, timeout_sec)
    last = h
    while time.time() < deadline:
        last = lm_studio.health(timeout=5)
        if last.get("available"):
            out = {
                "ok": True,
                "status": "started",
                "process": started_process,
                "server_start": server_start,
                "health": last,
            }
            _log("ensure_server", **out)
            return out
        time.sleep(POLL_SEC)
    out = {
        "ok": False,
        "status": "server_unavailable",
        "process": started_process,
        "server_start": server_start,
        "health": last,
    }
    _log("ensure_server", **out)
    return out


def ensure_model_loaded(model: str, timeout_sec: int = 240) -> Dict[str, Any]:
    """Load exactly one model for an imminent request."""
    global _LOADED_MODEL
    server = ensure_server(timeout_sec=min(90, timeout_sec))
    if not server.get("ok"):
        return {"ok": False, "status": "server_unavailable", "server": server, "model": model}
    if lazy_mode_enabled():
        with _LOADED_MODEL_LOCK:
            cached_model = _LOADED_MODEL
        if lm_studio.reuse_loaded_model_enabled() and cached_model == model:
            out = {
                "ok": True,
                "status": "already_loaded_cached",
                "model": model,
                "reused_loaded_model": True,
            }
            _log("ensure_model_loaded", **out)
            return out
        _run_lms(["unload", "--all"], timeout=90)
        with _LOADED_MODEL_LOCK:
            _LOADED_MODEL = None
    res = _run_lms(["load", model], timeout=timeout_sec)
    out = {"model": model, **res}
    with _LOADED_MODEL_LOCK:
        _LOADED_MODEL = model if out.get("ok") else None
    _log("ensure_model_loaded", **out)
    return out


def unload_models(*, stop_server: Optional[bool] = None) -> Dict[str, Any]:
    """Release LM Studio model memory; optionally stop the local server too."""
    global _LOADED_MODEL
    if stop_server is None:
        stop_server = auto_stop_server_enabled()
    unload = _run_lms(["unload", "--all"], timeout=90)
    with _LOADED_MODEL_LOCK:
        _LOADED_MODEL = None
    server_stop: Dict[str, Any] = {"skipped": True}
    if stop_server:
        server_stop = _run_lms(["server", "stop"], timeout=45)
    lm_studio.reset_readiness_cache_for_tests()
    out = {
        "ok": bool(unload.get("ok")) and (not stop_server or bool(server_stop.get("ok"))),
        "unload": unload,
        "server_stop": server_stop,
        "stopped_server": bool(stop_server),
    }
    _log("unload_models", **out)
    return out


def status(*, probe: bool = False) -> Dict[str, Any]:
    """Return current bootstrap component status without starting anything."""
    lm = lm_studio.lm_status(allow_probe=probe, force=probe)
    nt_running = _tasklist_contains("ninjatrader")
    lm_process = _tasklist_contains("lm studio")
    return {
        "ok": bool(lm.get("run_allowed")) and nt_running is not False,
        "checked_at_utc": _now(),
        "auto_bootstrap_enabled": auto_bootstrap_enabled(),
        "lazy_mode_enabled": lazy_mode_enabled(),
        "auto_unload_enabled": auto_unload_enabled(),
        "auto_stop_server_enabled": auto_stop_server_enabled(),
        "ninjatrader_autostart_allowed": ninjatrader_autostart_allowed(),
        "reuse_loaded_model_enabled": lm_studio.reuse_loaded_model_enabled(),
        "unload_after_request_enabled": lm_studio.unload_after_request_enabled(),
        "config_path": str(config_path()),
        "components": {
            "ninjatrader": {
                "running": nt_running,
                "exe": _ninjatrader_exe(),
                "autostart_allowed": ninjatrader_autostart_allowed(),
            },
            "bridge_deployment": bridge_deployment_status(),
            "lm_studio_process": {
                "running": lm_process,
                "exe": _lm_studio_exe(),
            },
            "lms_cli": {
                "available": bool(_lms_cli()),
                "path": _lms_cli() or "",
            },
            "lm_studio_server": lm,
        },
        "required_models": _required_models(),
    }


def start(
    *,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    start_ninjatrader: bool = False,
    start_lm_studio: bool = True,
    start_lm_server: bool = True,
    load_models: bool = False,
    wait_readiness: bool = False,
) -> Dict[str, Any]:
    """Best-effort environment preparation.

    Idempotent by design: already-running components are reported as such.
    """
    global _LOADED_MODEL
    deadline = time.time() + max(30, timeout_sec)
    steps: List[Dict[str, Any]] = []
    _log("bootstrap_start", timeout_sec=timeout_sec)

    nt_running = _tasklist_contains("ninjatrader")
    steps.append({
        "component": "bridge_deployment",
        **_deploy_bridge_if_safe(nt_running),
    })
    if start_ninjatrader and not ninjatrader_autostart_allowed():
        steps.append({
            "component": "ninjatrader",
            "ok": False,
            "status": "manual_login_required",
            "message": f"Set {AUTOSTART_NT_ENV}=1 only for an intentional local launch",
        })
    elif start_ninjatrader:
        if nt_running is True:
            steps.append({"component": "ninjatrader", "ok": True, "status": "already_running"})
        else:
            res = _start_process(_ninjatrader_exe(), "NinjaTrader")
            steps.append({"component": "ninjatrader", **res})
    else:
        steps.append({
            "component": "ninjatrader",
            "ok": True,
            "status": "already_running" if nt_running is True else "skipped_default_off",
        })

    lm_proc = _tasklist_contains("lm studio")
    if start_lm_studio:
        if lm_proc is True:
            steps.append({"component": "lm_studio_process", "ok": True, "status": "already_running"})
        else:
            res = _start_process(_lm_studio_exe(), "LM Studio")
            steps.append({"component": "lm_studio_process", **res})

    if start_lm_server:
        steps.append({"component": "lm_studio_server_start", **_run_lms(["server", "start"], timeout=45)})

    if load_models:
        for model in _required_models():
            if time.time() >= deadline:
                steps.append({"component": "lm_model_load", "model": model, "ok": False, "status": "timeout"})
                break
            res = _run_lms(["load", model], timeout=min(180, max(30, int(deadline - time.time()))))
            steps.append({"component": "lm_model_load", "model": model, **res})

    if lazy_mode_enabled() and not load_models:
        unload = _run_lms(["unload", "--all"], timeout=90)
        with _LOADED_MODEL_LOCK:
            _LOADED_MODEL = None
        steps.append({"component": "lm_model_unload_standby", **unload})

    readiness: Dict[str, Any] = {}
    if wait_readiness:
        while time.time() < deadline:
            readiness = lm_studio.lm_status(allow_probe=True, force=True)
            if readiness.get("run_allowed"):
                break
            time.sleep(POLL_SEC)
        steps.append({
            "component": "lm_readiness",
            "ok": bool(readiness.get("run_allowed")),
            "status": readiness.get("status"),
            "message_ru": readiness.get("message_ru"),
        })
    else:
        readiness = lm_studio.lm_status(allow_probe=False)

    lazy_prepared = (
        lazy_mode_enabled()
        and bool(readiness.get("available"))
        and not readiness.get("missing_run_roles")
    )
    out = {
        "ok": bool(readiness.get("run_allowed")) or lazy_prepared,
        "started_at_utc": _now(),
        "steps": steps,
        "readiness": readiness,
        "status": status(probe=False),
    }
    _log("bootstrap_finish", ok=out["ok"], steps=steps, readiness_status=readiness.get("status"))
    return out


def auto_bootstrap_enabled() -> bool:
    return os.environ.get("AI_LAB_AUTO_BOOTSTRAP", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }
