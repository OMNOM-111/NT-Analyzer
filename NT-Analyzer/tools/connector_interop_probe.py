"""Build the net48 Connector harness and verify its signature in Python."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import connector_protocol


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    bridge_project = root / "bridge" / "NTAnalyzerBridge.csproj"
    harness_project = root / "bridge" / "tests" / "ConnectorInteropHarness" / "ConnectorInteropHarness.csproj"
    bridge_dll = root / "bridge" / "bin" / "Release" / "NTAnalyzerBridge.dll"
    build_bridge = subprocess.run(
        ["dotnet", "build", str(bridge_project), "-c", "Release", "--no-restore"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if build_bridge.returncode:
        print(json.dumps({"ok": False, "step": "bridge_build"}))
        return 2
    build_harness = subprocess.run(
        ["dotnet", "build", str(harness_project), "-c", "Release"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if build_harness.returncode:
        print(json.dumps({"ok": False, "step": "harness_build", "detail": build_harness.stderr[-1000:]}))
        return 2
    harness_exe = harness_project.parent / "bin" / "Release" / "net48" / "StratForge.ConnectorInteropHarness.exe"
    with tempfile.TemporaryDirectory(prefix="stratforge-connector-interop-") as state_dir:
        run = subprocess.run(
            [str(harness_exe), str(bridge_dll), state_dir],
            cwd=root,
            text=True,
            capture_output=True,
        )
        if run.returncode:
            print(json.dumps({"ok": False, "step": "harness_run", "detail": run.stderr[-1000:]}))
            return 2
        vector = json.loads(run.stdout)
        hello = vector["hello"]
        canonical = connector_protocol.hello_signing_message(hello)
        emitted = base64.b64decode(vector["message_base64"])
        if canonical != emitted:
            print(json.dumps({"ok": False, "step": "canonical_message"}))
            return 2
        if connector_protocol.public_key_fingerprint(vector["public_key"]) != vector["fingerprint"]:
            print(json.dumps({"ok": False, "step": "fingerprint"}))
            return 2
        connector_protocol._verify_signature(
            vector["public_key"], hello["signature"], canonical,
        )
        challenge = vector["challenge"]
        challenge_canonical = connector_protocol.challenge_signing_message(challenge)
        challenge_emitted = base64.b64decode(vector["challenge_message_base64"])
        if challenge_canonical != challenge_emitted:
            print(json.dumps({"ok": False, "step": "challenge_canonical_message"}))
            return 2
        connector_protocol._verify_signature(
            vector["public_key"], challenge["signature"], challenge_canonical,
        )
    print(json.dumps({
        "ok": True,
        "curve": "P-256",
        "hash": "SHA-256",
        "csharp_python_signature_interop": True,
        "challenge_proof_interop": True,
        "dpapi_key_reload": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
