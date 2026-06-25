"""Real compile pipeline for AI sandbox strategies.

The AI never invokes ``csc`` directly. The bridge's :class:`CatalogRefresher`
already auto-refreshes when ``NinjaTrader.Custom.dll`` mtime changes, and also
processes manual ``data/commands/refresh_catalog.request`` files. We piggy-back:

1. Record baseline dll mtime.
2. Best-effort: focus NinjaScript Editor and send F5 through the desktop.
   If the editor is not open/focusable, UI still shows a manual F5 banner.
3. Poll dll mtime; on change, log "dll_changed".
4. Drop a ``refresh_catalog.request`` and wait for the matching
   ``refresh_catalog.response`` (max 30s).
5. Poll ``data/catalog/strategies.json`` for the class name.

Timeout semantics:
- dll mtime never increased        -> ``timed_out_dll=True``  (TERMINAL: awaiting_compile_timeout)
- dll changed but class not visible -> ``timed_out_dll=False`` (TERMINAL: compile_failed)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import activity, paths
from .io_utils import read_json


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nt_custom_dll() -> Path:
    return paths.nt_user_home() / "Documents" / "NinjaTrader 8" / "bin" / "Custom" / "NinjaTrader.Custom.dll"


def _commands_dir() -> Path:
    d = paths.PROJECT_ROOT / "data" / "commands"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dll_mtime() -> float:
    p = nt_custom_dll()
    try:
        return p.stat().st_mtime if p.exists() else 0.0
    except OSError:
        return 0.0


def auto_compile_enabled() -> bool:
    return os.environ.get("AI_LAB_AUTO_COMPILE", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def trigger_ninjascript_editor_compile(
    experiment_id: Optional[str] = None,
    *,
    class_name: str = "",
    timeout_sec: int = 12,
) -> Dict[str, Any]:
    """Best-effort desktop F5 in NinjaScript Editor.

    NinjaTrader does not expose a stable public compile API to this backend.
    The least invasive automation is to activate an already-open NinjaScript
    Editor window and send F5. If that window is not present, we return a soft
    failure and the normal dll watcher/manual banner path continues.
    """
    if not auto_compile_enabled():
        return {"ok": False, "reason": "disabled_by_AI_LAB_AUTO_COMPILE"}
    if os.name != "nt":
        return {"ok": False, "reason": "not_windows"}

    script = r'''
$ErrorActionPreference = "Stop"
$wshell = New-Object -ComObject WScript.Shell
$activated = $false
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class AiLabWin32 {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

$script:targetWindow = [IntPtr]::Zero
$script:targetTitle = ""
$cb = [AiLabWin32+EnumWindowsProc]{
    param([IntPtr]$hWnd, [IntPtr]$lParam)
    if (-not [AiLabWin32]::IsWindowVisible($hWnd)) { return $true }
    $sb = New-Object System.Text.StringBuilder 512
    [void][AiLabWin32]::GetWindowText($hWnd, $sb, $sb.Capacity)
    $title = $sb.ToString()
    if ([string]::IsNullOrWhiteSpace($title)) { return $true }
    if ($title -match "NinjaScript Editor|Редактор NinjaScript") {
        $script:targetWindow = $hWnd
        $script:targetTitle = $title
        return $false
    }
    return $true
}
[void][AiLabWin32]::EnumWindows($cb, [IntPtr]::Zero)

if ($script:targetWindow -ne [IntPtr]::Zero) {
    [AiLabWin32]::ShowWindowAsync($script:targetWindow, 9) | Out-Null
    Start-Sleep -Milliseconds 250
    [AiLabWin32]::SetForegroundWindow($script:targetWindow) | Out-Null
    $activated = $true
} else {
    foreach ($title in @("Редактор NinjaScript", "NinjaScript Editor")) {
        try {
            if ($wshell.AppActivate($title)) {
                $activated = $true
                $script:targetTitle = $title
                break
            }
        } catch {}
    }
}
if (-not $activated) {
    Write-Output "ninja_script_editor_not_found"
    exit 2
}
Start-Sleep -Milliseconds 500
$wshell.SendKeys("{F5}")
Write-Output ("sent_f5 " + $script:targetTitle)
'''
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(3, timeout_sec),
        )
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "reason": "subprocess_failed", "error": str(exc)}
        if experiment_id:
            activity.log(experiment_id, "compile", "auto_f5_failed", level="warn",
                         class_name=class_name, reason=out["reason"], error=str(exc)[:300])
        return out

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    ok = completed.returncode == 0 and "sent_f5" in stdout
    out = {
        "ok": ok,
        "returncode": completed.returncode,
        "stdout": stdout[-500:],
        "stderr": stderr[-500:],
    }
    if experiment_id:
        action = "auto_f5_sent" if ok else "auto_f5_failed"
        activity.log(experiment_id, "compile", action, level="info" if ok else "warn",
                     class_name=class_name, returncode=completed.returncode,
                     stdout=stdout[-300:], stderr=stderr[-300:])
    return out


def await_dll_change(
    baseline_mtime: float,
    timeout_sec: int,
    *,
    experiment_id: Optional[str] = None,
    poll_sec: float = 1.0,
    heartbeat_sec: int = 10,
) -> Dict[str, Any]:
    """Block until dll mtime > baseline, or timeout. Logs heartbeats."""
    deadline = time.time() + max(1, timeout_sec)
    last_beat = 0.0
    while time.time() < deadline:
        now = time.time()
        if experiment_id and (now - last_beat) >= heartbeat_sec:
            remaining = int(deadline - now)
            activity.log(experiment_id, "compile", "waiting_dll", level="info",
                         remaining_sec=remaining, dll=str(nt_custom_dll()))
            last_beat = now
        cur = _dll_mtime()
        if cur > baseline_mtime and cur > 0.0:
            return {"ok": True, "new_mtime": cur, "elapsed_sec": int(now - (deadline - timeout_sec)), "timed_out": False}
        time.sleep(poll_sec)
    return {"ok": False, "new_mtime": _dll_mtime(),
            "elapsed_sec": timeout_sec, "timed_out": True}


def _parse_ninjascript_error_cells(
    cells: List[Dict[str, Any]],
    *,
    class_name: str,
) -> List[Dict[str, Any]]:
    """Convert NinjaScript Editor UIA cells into compiler diagnostics."""
    grouped: Dict[int, Dict[str, str]] = {}
    for cell in cells:
        automation_id = str(cell.get("automation_id") or "")
        match = re.match(r"^RecordRow(\d+)_(.+)$", automation_id)
        if not match:
            continue
        row = grouped.setdefault(int(match.group(1)), {})
        key = match.group(2).strip().lower()
        value = str(cell.get("name") or "").strip()
        if key.startswith("файл ninjascript") or key.startswith("ninjascript file"):
            row["file"] = value
        elif key in {"ошибка", "error"}:
            row["message"] = value
        elif key in {"код", "code"}:
            row["code"] = value
        elif key in {"линия", "line"}:
            row["line"] = value
        elif key in {"колонка", "column"}:
            row["column"] = value

    out: List[Dict[str, Any]] = []
    for row_idx in sorted(grouped):
        row = grouped[row_idx]
        file_name = row.get("file", "")
        if class_name and class_name not in file_name:
            continue
        code = row.get("code", "")
        message = row.get("message", "")
        if not re.fullmatch(r"CS\d{4}", code) or not message:
            continue
        try:
            line = int(row.get("line") or 0)
            column = int(row.get("column") or 0)
        except ValueError:
            line = 0
            column = 0
        out.append({
            "class_name": class_name,
            "file": file_name,
            "line": line,
            "column": column,
            "code": code,
            "message": message[:1000],
            "timestamp_utc": _now(),
            "source": "ninjatrader_editor_uia",
        })
    return out


def read_ninjascript_editor_errors(class_name: str) -> List[Dict[str, Any]]:
    """Read the visible NinjaScript Editor error grid via Windows UI Automation."""
    if os.name != "nt":
        return []
    script = r'''
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class AiLabErrorGridWin32 {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
}
"@
$script:target = [IntPtr]::Zero
$cb = [AiLabErrorGridWin32+EnumWindowsProc]{
    param([IntPtr]$hWnd, [IntPtr]$lParam)
    if (-not [AiLabErrorGridWin32]::IsWindowVisible($hWnd)) { return $true }
    $sb = New-Object System.Text.StringBuilder 512
    [void][AiLabErrorGridWin32]::GetWindowText($hWnd, $sb, $sb.Capacity)
    if ($sb.ToString() -match "NinjaScript Editor|Редактор NinjaScript") {
        $script:target = $hWnd
        return $false
    }
    return $true
}
[void][AiLabErrorGridWin32]::EnumWindows($cb, [IntPtr]::Zero)
if ($script:target -eq [IntPtr]::Zero) {
    Write-Output "[]"
    exit 0
}
$root = [System.Windows.Automation.AutomationElement]::FromHandle($script:target)
$all = $root.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
)
$cells = @()
for ($i = 0; $i -lt $all.Count; $i++) {
    $element = $all.Item($i)
    $automationId = $element.Current.AutomationId
    if ($automationId -like "RecordRow*_*") {
        $cells += [pscustomobject]@{
            automation_id = $automationId
            name = $element.Current.Name
        }
    }
}
Write-Output ($cells | ConvertTo-Json -Compress)
'''
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
        )
        if completed.returncode != 0:
            return []
        payload = json.loads((completed.stdout or "[]").strip() or "[]")
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return []
        return _parse_ninjascript_error_cells(payload, class_name=class_name)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def quarantine_source(
    *,
    experiment_id: str,
    class_name: str,
    reason: str,
) -> Dict[str, Any]:
    """Move a broken AI source out of NinjaTrader Custom so it cannot poison later builds."""
    if not re.fullmatch(r"EXP-\d{8}-\d{4}", experiment_id or ""):
        return {"ok": False, "error": "invalid experiment_id"}
    sandbox = paths.ai_sandbox_strategies_dir().resolve()
    source = (sandbox / f"{class_name}.cs").resolve()
    try:
        source.relative_to(sandbox)
    except ValueError:
        return {"ok": False, "error": "source outside AI sandbox"}
    if not source.exists():
        return {"ok": False, "error": "source not found", "source": str(source)}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_dir = paths.QUARANTINE_DIR / experiment_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}_{stamp}.cs"
    try:
        shutil.move(str(source), str(target))
    except OSError as exc:
        return {"ok": False, "error": str(exc), "source": str(source)}
    meta = target.with_suffix(".json")
    meta.write_text(json.dumps({
        "experiment_id": experiment_id,
        "class_name": class_name,
        "reason": reason,
        "quarantined_at_utc": _now(),
        "source": str(source),
        "target": str(target),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        activity.log(
            experiment_id, "compile", "source_quarantined", level="warn",
            class_name=class_name, reason=reason[:200], quarantine_path=str(target),
        )
    except (OSError, ValueError):
        # The source has already been moved safely. A logging failure must not
        # turn a successful quarantine into an exception.
        pass
    return {"ok": True, "source": str(source), "quarantine_path": str(target)}


def quarantine_unrelated_editor_failures(
    *,
    experiment_id: str,
    current_class_name: str,
) -> List[Dict[str, Any]]:
    """Quarantine stale broken AI files reported by the global NT error grid."""
    rows = read_ninjascript_editor_errors("")
    file_names = {
        Path(str(row.get("file") or "")).stem
        for row in rows
        if str(row.get("file") or "").lower().endswith(".cs")
    }
    out: List[Dict[str, Any]] = []
    for class_name in sorted(file_names):
        if not class_name.startswith("NTAAiSandbox") or class_name == current_class_name:
            continue
        result = quarantine_source(
            experiment_id=experiment_id,
            class_name=class_name,
            reason="stale unrelated NinjaScript compile error",
        )
        if result.get("ok"):
            out.append(result)
    return out


def await_compile_outcome(
    baseline_mtime: float,
    timeout_sec: int,
    *,
    experiment_id: Optional[str],
    class_name: str,
    poll_sec: float = 1.0,
) -> Dict[str, Any]:
    """Wait for a DLL change or return visible class-specific compile errors."""
    started = time.time()
    deadline = started + max(1, timeout_sec)
    next_error_probe = started + 3.0
    last_beat = 0.0
    while time.time() < deadline:
        now = time.time()
        cur = _dll_mtime()
        if cur > baseline_mtime and cur > 0.0:
            return {
                "ok": True,
                "new_mtime": cur,
                "elapsed_sec": int(now - started),
                "timed_out": False,
                "errors": [],
            }
        if now >= next_error_probe:
            editor_errors = read_ninjascript_editor_errors(class_name)
            if editor_errors:
                if experiment_id:
                    activity.log(
                        experiment_id,
                        "compile",
                        "editor_errors_detected",
                        level="error",
                        count=len(editor_errors),
                        sample=str([
                            (e.get("code"), (e.get("message") or "")[:80])
                            for e in editor_errors[:3]
                        ])[:200],
                    )
                return {
                    "ok": False,
                    "new_mtime": cur,
                    "elapsed_sec": int(now - started),
                    "timed_out": False,
                    "compile_error_detected": True,
                    "errors": editor_errors,
                }
            next_error_probe = now + 10.0
        if experiment_id and (now - last_beat) >= 10.0:
            activity.log(
                experiment_id,
                "compile",
                "waiting_dll",
                level="info",
                remaining_sec=int(deadline - now),
                dll=str(nt_custom_dll()),
            )
            last_beat = now
        time.sleep(poll_sec)
    return {
        "ok": False,
        "new_mtime": _dll_mtime(),
        "elapsed_sec": timeout_sec,
        "timed_out": True,
        "errors": [],
    }


def trigger_catalog_refresh(experiment_id: Optional[str] = None, wait_sec: int = 30) -> Dict[str, Any]:
    """Write a request and wait for the response file the bridge writes back."""
    cdir = _commands_dir()
    req = cdir / "refresh_catalog.request"
    resp = cdir / "refresh_catalog.response"
    request_id = uuid.uuid4().hex

    try:
        if resp.exists():
            try:
                resp.unlink()
            except OSError:
                pass
        req.write_text(json.dumps({
            "schema_version": "0.1",
            "request_id": request_id,
            "requested_at_utc": _now(),
            "requested_by": "ai_lab",
            "experiment_id": experiment_id or "",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"cannot write request: {e}"}

    if experiment_id:
        activity.log(experiment_id, "catalog", "request_written", level="info",
                     request_id=request_id, request_file=str(req))

    deadline = time.time() + max(1, wait_sec)
    while time.time() < deadline:
        if resp.exists():
            data = read_json(resp, default=None)
            if isinstance(data, dict) and data.get("request_id") == request_id:
                return {
                    "ok": bool(data.get("ok", False)),
                    "strategies_count": int(data.get("strategies_count") or 0),
                    "error": data.get("error") or "",
                    "trigger": data.get("trigger", ""),
                    "responded_at_utc": data.get("responded_at_utc"),
                }
        time.sleep(0.5)
    return {"ok": False, "error": "refresh_catalog response timeout", "strategies_count": 0}


def class_in_catalog(class_name: str) -> bool:
    catalog_path = paths.PROJECT_ROOT / "data" / "catalog" / "strategies.json"
    data = read_json(catalog_path, default={"strategies": []}) or {}
    items = data.get("strategies", []) if isinstance(data, dict) else (data or [])
    for it in items:
        cn = it.get("class_name") if isinstance(it, dict) else it
        if cn == class_name:
            return True
    return False


def class_in_whitelist(class_name: str) -> bool:
    try:
        from .. import jobqueue
    except Exception:
        return False
    if hasattr(jobqueue, "whitelisted_strategies"):
        try:
            data = jobqueue.whitelisted_strategies()
            items = data.get("strategies") if isinstance(data, dict) else data
            for item in items or []:
                cn = item.get("class_name") if isinstance(item, dict) else item
                if cn == class_name:
                    return True
        except Exception:
            return False
    return False


def await_class_in_catalog(class_name: str, timeout_sec: int,
                            *, experiment_id: Optional[str] = None,
                            poll_sec: float = 1.0) -> bool:
    deadline = time.time() + max(1, timeout_sec)
    while time.time() < deadline:
        if class_in_catalog(class_name):
            return True
        time.sleep(poll_sec)
    if experiment_id:
        activity.log(experiment_id, "catalog", "class_not_visible", level="warn",
                     class_name=class_name, waited_sec=timeout_sec)
    return False


def run_compile_chain(
    experiment_id: str,
    class_name: str,
    *,
    request_restart_flag: bool = False,  # kept for backwards compat; ignored
    verify_poll_sec: int = 0,
    dll_wait_sec: int = 300,
    catalog_wait_sec: int = 30,
) -> Dict[str, Any]:
    """Trigger/observe NT compile -> refresh catalog -> verify class visible."""
    steps = []
    quarantined = quarantine_unrelated_editor_failures(
        experiment_id=experiment_id,
        current_class_name=class_name,
    )
    if quarantined:
        steps.append({"step": "quarantine_unrelated", "files": quarantined})
    baseline = _dll_mtime()
    activity.log(experiment_id, "compile", "baseline_recorded", level="info",
                 baseline_mtime=baseline, dll=str(nt_custom_dll()))

    auto_res = trigger_ninjascript_editor_compile(experiment_id, class_name=class_name)
    steps.append({"step": "auto_compile_f5", **auto_res})

    dll_res = await_compile_outcome(
        baseline,
        dll_wait_sec,
        experiment_id=experiment_id,
        class_name=class_name,
    )
    steps.append({"step": "dll_watch", **dll_res})
    if not dll_res["ok"]:
        return {
                "ok": False,
                "timed_out_dll": bool(dll_res.get("timed_out")),
                "compile_error_detected": bool(dll_res.get("compile_error_detected")),
                "errors": list(dll_res.get("errors") or []),
                "steps": steps,
                "in_whitelist": False, "in_catalog": False,
                "elapsed_sec": dll_res.get("elapsed_sec"),
        }
    activity.log(experiment_id, "compile", "dll_changed", level="success",
                 new_mtime=dll_res.get("new_mtime"))

    refresh_res = trigger_catalog_refresh(experiment_id, wait_sec=catalog_wait_sec)
    steps.append({"step": "catalog_refresh", **refresh_res})
    if not refresh_res.get("ok"):
        activity.log(experiment_id, "catalog", "refresh_failed", level="error",
                     error=str(refresh_res.get("error", ""))[:200])

    visible = await_class_in_catalog(
        class_name, timeout_sec=max(5, verify_poll_sec or catalog_wait_sec),
        experiment_id=experiment_id,
    )
    in_wl = class_in_whitelist(class_name)
    steps.append({"step": "verify_visibility", "in_whitelist": in_wl, "in_catalog": visible})
    return {
        "ok": bool(visible),
        "timed_out_dll": False,
        "in_whitelist": in_wl,
        "in_catalog": visible,
        "steps": steps,
    }
