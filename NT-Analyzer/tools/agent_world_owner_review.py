"""Launch this checkout's existing isolated Preview without replacing Local.

Developer CLI only. The local owner must already be available at --parent-origin.
No owner state/credentials are copied. The regular Preview environment builder,
entry-token redemption, session/device gates and network guard remain in use.
The disposable child stays running for visual acceptance; Exit returns to Local.
"""
from __future__ import annotations

import argparse
import json
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-origin", default="http://127.0.0.1:8765")
    parser.add_argument("--scenario", choices=("trusted_device", "active_user", "new_user"), default="trusted_device")
    args = parser.parse_args()
    origin = urllib.parse.urlsplit(args.parent_origin)
    if (origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost"}
            or origin.username or origin.password or origin.path not in {"", "/"}
            or origin.query or origin.fragment or not origin.port):
        parser.error("Use the exact HTTP loopback owner origin with a port.")
    parent = f"http://{origin.hostname}:{origin.port}"
    with urllib.request.urlopen(parent + "/api/runtime/env", timeout=10) as response:
        identity = json.load(response)
    with urllib.request.urlopen(parent + "/api/auth/status", timeout=10) as response:
        auth = json.load(response)
    if identity.get("deployment_environment") != "development" or not auth.get("is_owner"):
        raise SystemExit("The existing parent must be the local Development owner.")

    sys.path.insert(0, str(APP_ROOT))
    from app.dev_preview import _sandbox_environment

    preview_id = secrets.token_hex(12)
    entry, control = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    base = Path(tempfile.gettempdir()) / "stratforge-preview-sandboxes"
    container = base / "agent-world-owner-review" / preview_id
    root = container / "data"
    root.mkdir(parents=True, exist_ok=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = _sandbox_environment(preview_id=preview_id, scenario=args.scenario,
        parent_origin=parent, root=root, base=base, entry_token=entry, control_token=control, port=port)
    log_path = container / "preview-server.log"
    with log_path.open("w", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-m", "app.preview_server", "--port", str(port)],
            cwd=APP_ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))
    ready = False
    for _ in range(80):
        if child.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/runtime/env", timeout=1) as response:
                actual = json.load(response)
            ready = True
            break
        except OSError:
            time.sleep(0.1)
    if not ready:
        child.terminate()
        raise SystemExit(f"Preview did not start. Inspect {log_path}")
    print(json.dumps({"pid": child.pid, "origin": f"http://127.0.0.1:{port}",
        "entry_url": f"http://127.0.0.1:{port}/api/dev/preview/enter?token={urllib.parse.quote(entry)}",
        "source_sha": actual.get("git_commit_sha"), "version": actual.get("app_version"),
        "parent_version": identity.get("app_version"), "isolated_root": str(root),
        "log": str(log_path), "note": "One-use entry URL; do not share. Exit Preview returns to unchanged Local."},
        ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
