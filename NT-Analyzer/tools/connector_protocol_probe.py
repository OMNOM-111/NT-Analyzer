"""Isolated concurrency, failure and tenant-scope probe for Connector v1."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import statistics
import sys
import tempfile
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import connector_protocol, workspaces


def _b64(value: bytes) -> str:
    return connector_protocol._b64url_encode(value)


def _new_device() -> tuple[object, dict]:
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    return private, {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64(numbers.x.to_bytes(32, "big")),
        "y": _b64(numbers.y.to_bytes(32, "big")),
    }


def _connect(user_id: int, workspace_id: str) -> dict:
    started_at = time.perf_counter()
    private, public = _new_device()
    enrollment = connector_protocol.start_enrollment(
        user_id,
        workspace_id=workspace_id,
        machine_label=f"Load NT {user_id}",
        capabilities=["telemetry", "accounts_read", "paper_commands"],
    )
    pending = connector_protocol.enroll_device({
        "code": enrollment["code"],
        "public_key": public,
        "connector_version": "0.2.0-probe",
        "nt_version": "8.1.6.3",
        "machine_label": f"Load NT {user_id}",
        "ninja_instance_id": f"nt_load_instance_{user_id:03d}",
    })
    hello = {
        "protocol_version": connector_protocol.PROTOCOL_VERSION,
        "connector_version": "0.2.0-probe",
        "nt_version": "8.1.6.3",
        "installation_id": pending["installation_id"],
        "workspace_id": pending["workspace_id"],
        "nonce": pending["nonce"],
        "public_key_fingerprint": pending["public_key_fingerprint"],
        "ninja_instance_id": f"nt_load_instance_{user_id:03d}",
    }
    hello["signature"] = _b64(private.sign(
        connector_protocol.hello_signing_message(hello),
        ec.ECDSA(hashes.SHA256()),
    ))
    welcome = connector_protocol.signed_hello(hello)
    return {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "private": private,
        "pending": pending,
        "welcome": welcome,
        "connect_ms": (time.perf_counter() - started_at) * 1000,
    }


def _command_cycle(device: dict) -> float:
    started_at = time.perf_counter()
    command = connector_protocol.queue_command(
        device["user_id"],
        workspace_id=device["workspace_id"],
        connection_id=device["welcome"]["connection_id"],
        capability="telemetry",
        idempotency_key=f"load-command-{device['user_id']:04d}",
        payload={"command": "ping"},
        expires_in_sec=60,
    )["command"]
    polled = connector_protocol.poll_commands(
        device["welcome"]["session_token"],
        connector_sequence=1,
        wait_seconds=0,
    )
    assert [row["command_id"] for row in polled["commands"]] == [command["command_id"]]
    result = connector_protocol.submit_result(device["welcome"]["session_token"], {
        "command_id": command["command_id"],
        "idempotency_key": command["idempotency_key"],
        "status": "completed",
        "connector_sequence": 2,
        "safe_result": {"message": "pong"},
        "error_class": "",
    })
    assert result["command"]["status"] == "completed"
    return (time.perf_counter() - started_at) * 1000


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return ordered[rank]


def main() -> int:
    previous = {name: os.environ.get(name) for name in (
        "STRATFORGE_ENV", "NTA_APP_ENV", "NTA_ENV",
        "STRATFORGE_DATA_ROOT", "STRATFORGE_DEVELOPMENT_DATA_ROOT",
    )}
    errors: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="stratforge-connector-probe-") as temp:
            root = Path(temp)
            os.environ["STRATFORGE_ENV"] = "development"
            os.environ.pop("NTA_APP_ENV", None)
            os.environ.pop("NTA_ENV", None)
            os.environ["STRATFORGE_DATA_ROOT"] = str(root / "production")
            os.environ["STRATFORGE_DEVELOPMENT_DATA_ROOT"] = str(root / "development")
            workspaces_rows = [
                workspaces.ensure_personal_workspace(
                    user_id,
                    display_name=f"Probe {user_id}",
                    require_entitlement=False,
                )
                for user_id in range(1, 11)
            ]
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = [
                    pool.submit(_connect, user_id, row["workspace_id"])
                    for user_id, row in enumerate(workspaces_rows, 1)
                ]
                devices = []
                for future in futures:
                    try:
                        devices.append(future.result())
                    except Exception as exc:  # pragma: no cover - probe reporting
                        errors.append(type(exc).__name__)
            with ThreadPoolExecutor(max_workers=10) as pool:
                command_ms = []
                for future in [pool.submit(_command_cycle, row) for row in devices]:
                    try:
                        command_ms.append(future.result())
                    except Exception as exc:  # pragma: no cover - probe reporting
                        errors.append(type(exc).__name__)

            cross_workspace_denied = False
            try:
                connector_protocol.list_installations(
                    1, workspace_id=workspaces_rows[1]["workspace_id"],
                )
            except workspaces.WorkspaceError:
                cross_workspace_denied = True

            revoked = devices[0]
            connector_protocol.revoke_installation(
                revoked["user_id"],
                revoked["welcome"]["connection_id"],
                workspace_id=revoked["workspace_id"],
            )
            revoked_session_denied = False
            try:
                connector_protocol.heartbeat(revoked["welcome"]["session_token"], {
                    "connector_sequence": 3,
                    "ninja_instance_id": "nt_load_instance_001",
                })
            except connector_protocol.ConnectorProtocolError:
                revoked_session_denied = True

            connect_ms = [row["connect_ms"] for row in devices]
            report = {
                "ok": not errors and len(devices) == 10 and len(command_ms) == 10
                and cross_workspace_denied and revoked_session_denied,
                "profiles": 10,
                "completed_command_cycles": len(command_ms),
                "errors": errors,
                "cross_workspace_denied": cross_workspace_denied,
                "revoked_session_denied": revoked_session_denied,
                "connect_ms": {
                    "p50": round(statistics.median(connect_ms), 2),
                    "p95": round(_percentile(connect_ms, 0.95), 2),
                    "p99": round(_percentile(connect_ms, 0.99), 2),
                },
                "command_cycle_ms": {
                    "p50": round(statistics.median(command_ms), 2),
                    "p95": round(_percentile(command_ms, 0.95), 2),
                    "p99": round(_percentile(command_ms, 0.99), 2),
                },
            }
            print(json.dumps(report, sort_keys=True))
            return 0 if report["ok"] else 2
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
