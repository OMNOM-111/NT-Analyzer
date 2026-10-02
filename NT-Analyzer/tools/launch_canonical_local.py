"""Canonical owner Local runtime: pin the source and preserve the original data root.

This is a Windows development launcher, never a Canary/Production entrypoint.
The exact worktree path and beta.106 application baseline are deliberate guards:
editing a Desktop shortcut back to the old root must fail before server startup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser


EXPECTED_ROOT = Path(r"C:\Users\dimon\Documents\StratForge-worktrees\local-current\NT-Analyzer")
ORIGINAL_DATA = Path(r"C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer\data")
MAIN_BASELINE = "9483bac868d829f3891e5e09fe84c18d242cf9c6"
RUNTIME_SOURCE = "e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885"
OWNER_WORKSPACE = "ws_owner_training_c1fe3f2f8a52"
EXPECTED_VERSION = "0.10.0-beta.106"
ALLOWED_BRANCHES = {"main", "codex/local-runtime-doc-canonicalization"}
MECHANISMS = {"environment": "development", "flags": {}}


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=EXPECTED_ROOT, text=True,
                            encoding="utf-8", errors="replace", capture_output=True,
                            timeout=10, check=True)
    return result.stdout.strip()


def fail(reason: str, *, actual: str = "unknown") -> None:
    raise RuntimeError(
        "Local runtime source mismatch: " + reason + "\n"
        + f"expected path={EXPECTED_ROOT}, baseline SHA={MAIN_BASELINE}\n"
        + f"actual path={Path(__file__).resolve().parent.parent}, SHA={actual}"
    )


def validate_source() -> str:
    actual_root = Path(__file__).resolve().parent.parent
    if actual_root != EXPECTED_ROOT.resolve() or not ORIGINAL_DATA.is_dir():
        fail("worktree or original owner data root differs")
    sha = _git("rev-parse", "HEAD")
    if _git("branch", "--show-current") not in ALLOWED_BRANCHES:
        fail("unexpected Local branch", actual=sha)
    if subprocess.run(["git", "merge-base", "--is-ancestor", MAIN_BASELINE, "HEAD"],
                      cwd=EXPECTED_ROOT, check=False).returncode != 0:
        fail("checkout predates current main baseline", actual=sha)
    changed_runtime = _git("diff", "--name-only", RUNTIME_SOURCE, "HEAD", "--",
                           ":(top)NT-Analyzer/app", ":(top)NT-Analyzer/static",
                           ":(top)NT-Analyzer/VERSION.json")
    if changed_runtime:
        fail("application files differ from the accepted beta.106 source", actual=sha)
    if _git("status", "--porcelain", "--untracked-files=all"):
        fail("canonical worktree is dirty; commit reviewed task changes first", actual=sha)
    version = json.loads((EXPECTED_ROOT / "VERSION.json").read_text(encoding="utf-8"))
    if version.get("version") != EXPECTED_VERSION:
        fail("VERSION.json differs from accepted beta.106", actual=sha)
    return sha


def configure(sha: str) -> dict[str, str]:
    for key in list(os.environ):
        if key.startswith(("STRATFORGE_PREVIEW", "NTA_PREVIEW")) or key in {
            "NT_ANALYZER_SQLITE_PATH", "NT_ANALYZER_ROOT", "NTA_STAGING_DATA_ROOT",
            "NTA_DATA_ROOT", "NTA_STAGING_ALLOW_OWNER_TELEGRAM",
        }:
            os.environ.pop(key, None)
    os.chdir(EXPECTED_ROOT)
    sys.path.insert(0, str(EXPECTED_ROOT))
    from app.backend_supervisor import configure_development_profile
    values = configure_development_profile(EXPECTED_ROOT, apply_environment=False)
    if values["GIT_COMMIT_SHA"] != sha or values["STRATFORGE_BUILD_DIRTY"] != "0":
        fail("build identity does not match clean checkout", actual=sha)
    values.update({
        "STRATFORGE_DEVELOPMENT_DATA_ROOT": str(ORIGINAL_DATA),
        "STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES": OWNER_WORKSPACE,
        "STRATFORGE_AGENT_WORLD_LOCAL_MECHANISMS": json.dumps(MECHANISMS, separators=(",", ":")),
        "STRATFORGE_TELEGRAM_OWNER_ENVIRONMENT": "production",
        "NTA_STAGING_ALLOW_OWNER_TELEGRAM": "0",
        "NTA_VITEK_BACKGROUND": "0",
        "STRATFORGE_CANARY_DATA_ROOT": str(EXPECTED_ROOT / ".stratforge-canary-data-disabled"),
    })
    os.environ.update(values)
    from app import runtime_env, preview_sandbox
    from app.ai_control_center import live_gateway
    config = runtime_env.assert_startup_safe()
    if (config.environment != "development" or config.git_commit_sha != sha
            or runtime_env.data_root() != ORIGINAL_DATA.resolve()
            or preview_sandbox.enabled() or not live_gateway.configured(OWNER_WORKSPACE)
            or runtime_env.telegram_operational_delivery_active()):
        raise RuntimeError("Canonical Local environment/access/sender preflight failed")
    return values


def open_when_ready() -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/live", timeout=2) as response:
                if response.status == 200:
                    webbrowser.open("http://127.0.0.1:8765/ui/")
                    return
        except Exception:
            time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate source/environment without startup")
    parser.add_argument("--no-browser", action="store_true", help="do not open the normal UI")
    args = parser.parse_args()
    sha = validate_source()
    values = configure(sha)
    print(f"Canonical Local: {EXPECTED_ROOT} | SHA {sha} | {values['BUILD_ID']} | owner workspace {OWNER_WORKSPACE}", flush=True)
    if args.check:
        return 0
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8765)) == 0:
            raise RuntimeError("Port 8765 is already occupied; refusing a second Local runtime")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    from app.backend_supervisor import supervise
    return supervise(port=8765, retry_seconds=10)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(2)
