"""End-to-end failure/rollback probe for the standalone Connector updater."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / ".artifacts" / "connector"
VERSIONS = ("0.4.1-dev.1", "0.4.1-dev.2", "0.4.1-dev.10")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _bundle(version: str) -> Path:
    return ARTIFACTS / "releases" / version / "bundle"


def _archive(version: str) -> Path:
    return ARTIFACTS / "releases" / version / f"StratForge.Connector-{version}-stable.zip"


def _ensure_releases() -> None:
    for version in VERSIONS:
        if (
            os.environ.get("STRATFORGE_PROBE_REUSE_RELEASES") == "1"
            and _archive(version).is_file()
            and _bundle(version).is_dir()
        ):
            continue
        completed = subprocess.run(
            [sys.executable, "tools/build_connector_release.py", "--version", version,
             "--channel", "stable", "--force"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=180,
        )
        if completed.returncode:
            raise RuntimeError(f"release build failed for {version}: {completed.stdout[-1000:]}")


def _run(executable: Path, *args: Any, ok: bool = True) -> dict:
    completed = subprocess.run(
        [str(executable), *(str(item) for item in args)],
        cwd=executable.parent,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    payload = json.loads(lines[-1]) if lines else {
        "ok": False, "error": (completed.stderr or "missing JSON output")[-500:],
    }
    payload["exit_code"] = completed.returncode
    if ok and (completed.returncode or payload.get("ok") is not True):
        raise RuntimeError(f"command failed: {payload}")
    if not ok and completed.returncode == 0:
        raise RuntimeError(f"command unexpectedly succeeded: {payload}")
    return payload


def _protected_config(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    connector = doc["production_connector"]
    return {
        "mode": doc["mode"],
        "ninjatrader_user_dir": doc["ninjatrader_user_dir"],
        "runtime_data_dir": doc["runtime_data_dir"],
        "server_origin": connector["server_origin"],
        "protocol_version": connector["protocol_version"],
        "enrollment_credential_ref": connector["enrollment_credential_ref"],
        "state_dir": connector["state_dir"],
        "heartbeat_interval_ms": connector["heartbeat_interval_ms"],
        "command_poll_seconds": connector["command_poll_seconds"],
        "update_policy": connector["update_policy"],
    }


def main() -> int:
    _ensure_releases()
    probe = ARTIFACTS / "updater-probe"
    expected_parent = ARTIFACTS.resolve()
    if probe.resolve().parent != expected_parent:
        raise RuntimeError("unsafe updater probe root")
    if probe.exists():
        shutil.rmtree(probe)
    ninja = probe / "NinjaTrader 8"
    custom = ninja / "bin" / "Custom"
    state_base = probe / "state"
    custom.mkdir(parents=True)
    state_base.mkdir(parents=True)

    setup_n = _bundle(VERSIONS[0]) / "StratForge.Connector.Setup.exe"
    updater = _bundle(VERSIONS[0]) / "StratForge.Connector.Updater.exe"
    install = _run(
        setup_n, "--install", "--ninja-user-dir", ninja, "--state-root", state_base,
        "--server-origin", "https://app.stratforges.com",
        "--enrollment-code", "2345-6789-ABCD-EFGH", "--channel", "stable",
        "--update-policy", "safe_restart", "--skip-uri-registration", "--non-interactive",
    )
    state = Path(install["state_dir"])
    for _ in range(20):
        if state.is_dir():
            break
        time.sleep(0.1)
    if not state.is_dir():
        raise RuntimeError(
            f"Setup returned a missing state directory: raw={install['state_dir']!r} path={state!r}"
        )
    dll = custom / "NTAnalyzerBridge.dll"
    config = custom / "NTAnalyzerBridge.config.json"
    device_key = state / "device-key.dpapi"
    device_key.write_bytes(b"connector-updater-probe-device-key")
    base_dll_hash = _hash(dll)
    protected = _protected_config(config)
    device_hash = _hash(device_key)
    checks: dict[str, bool] = {
        "base_install": install.get("ok") is True,
        "updater_in_release_cache": (
            state / "release-cache" / VERSIONS[0] / "StratForge.Connector.Updater.exe"
        ).is_file(),
    }

    truncated = probe / "interrupted-download.zip"
    truncated.write_bytes(_archive(VERSIONS[1]).read_bytes()[:1024])
    interrupted = _run(
        updater, "--stage", "--ninja-user-dir", ninja, "--state-root", state,
        "--package", truncated, "--non-interactive", ok=False,
    )
    checks["interrupted_download_rejected"] = interrupted["exit_code"] != 0
    checks["interrupted_download_left_n"] = _hash(dll) == base_dll_hash

    staged = _run(
        updater, "--stage", "--ninja-user-dir", ninja, "--state-root", state,
        "--package", _archive(VERSIONS[1]), "--non-interactive",
    )
    checks["n_plus_one_staged_verified"] = staged.get("state") == "staged"

    fake = probe / "NinjaTrader.exe"
    shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe", fake)
    running = subprocess.Popen(
        [str(fake), "/d", "/c", "ping -n 30 127.0.0.1 >nul"],
        cwd=probe,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        time.sleep(0.7)
        waiting = _run(
            updater, "--apply-staged", "--ninja-user-dir", ninja,
            "--state-root", state, "--non-interactive",
        )
        checks["running_nt_defers_replace"] = (
            waiting.get("state") == "waiting_for_safe_restart"
            and _hash(dll) == base_dll_hash
        )
    finally:
        running.terminate()
        try:
            running.wait(timeout=5)
        except subprocess.TimeoutExpired:
            running.kill()
            running.wait(timeout=5)

    applied = _run(
        updater, "--apply-staged", "--ninja-user-dir", ninja,
        "--state-root", state, "--non-interactive",
    )
    n1_dll_hash = _hash(dll)
    checks["upgrade_n_to_n_plus_one"] = (
        applied.get("state") == "pending_health" and n1_dll_hash != base_dll_hash
    )
    checks["config_protected_fields_preserved"] = _protected_config(config) == protected
    checks["private_key_preserved"] = _hash(device_key) == device_hash

    pending_path = state / "pending-update.json"
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    (state / "update-health.json").write_text(json.dumps({
        "schema_version": 1,
        "version": VERSIONS[1],
        "health_nonce": pending["health_nonce"],
        "accepted": True,
        "reason": "probe_authenticated_hello_heartbeat",
        "installation_id": "inst_probe_health_01",
        "heartbeat_at_utc": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")
    healthy = _run(
        updater, "--finalize", "--ninja-user-dir", ninja,
        "--state-root", state, "--non-interactive",
    )
    checks["post_update_health_committed"] = (
        healthy.get("state") == "health_accepted" and not pending_path.exists()
    )

    n1_config_hash = _hash(config)
    _run(
        updater, "--stage", "--ninja-user-dir", ninja, "--state-root", state,
        "--package", _archive(VERSIONS[2]), "--non-interactive",
    )
    _run(
        updater, "--apply-staged", "--ninja-user-dir", ninja,
        "--state-root", state, "--non-interactive",
    )
    failed_pending = json.loads(pending_path.read_text(encoding="utf-8"))
    failed_pending["health_deadline_epoch"] = 0
    failed_pending["health_deadline_utc"] = "1970-01-01T00:00:00Z"
    pending_path.write_text(json.dumps(failed_pending), encoding="utf-8")
    rolled_back = _run(
        updater, "--finalize", "--ninja-user-dir", ninja,
        "--state-root", state, "--non-interactive",
    )
    checks["failed_handshake_restores_previous_dll"] = (
        rolled_back.get("state") == "rolled_back" and _hash(dll) == n1_dll_hash
    )
    checks["failed_handshake_restores_previous_config"] = _hash(config) == n1_config_hash
    checks["rollback_preserves_private_key"] = _hash(device_key) == device_hash
    retry = _run(
        updater, "--stage", "--ninja-user-dir", ninja, "--state-root", state,
        "--package", _archive(VERSIONS[2]), "--non-interactive", ok=False,
    )
    checks["one_shot_rollback_blocks_retry"] = (
        retry["exit_code"] != 0 and (state / "blocked-update.json").is_file()
    )
    journal_text = (state / "update-journal.jsonl").read_text(encoding="utf-8")
    checks["redacted_release_audit_journal"] = (
        "23456789ABCDEFGH" not in journal_text
        and "connector-updater-probe-device-key" not in journal_text
        and '"action":"rollback"' in journal_text
        and "health_timeout" in journal_text
    )

    failed = sorted(name for name, passed in checks.items() if not passed)
    report = {
        "ok": not failed,
        "check_count": len(checks),
        "passed": sum(checks.values()),
        "failed": failed,
        "versions": list(VERSIONS),
        "standalone_updater": True,
        "ninjatrader_auto_closed": False,
        "probe_root": str(probe),
    }
    (probe / "probe-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
