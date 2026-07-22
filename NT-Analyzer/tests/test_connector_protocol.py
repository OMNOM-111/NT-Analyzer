from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app import connector_protocol
from app import secure_store
from app import server as server_mod
from app import subscriptions
from app import workspaces


def _b64(value: bytes) -> str:
    return connector_protocol._b64url_encode(value)


def _device_key():
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64(numbers.x.to_bytes(32, "big")),
        "y": _b64(numbers.y.to_bytes(32, "big")),
    }
    return private, jwk


def _enroll(workspace_id: str, user_id: int = 42):
    private, jwk = _device_key()
    started = connector_protocol.start_enrollment(
        user_id,
        workspace_id=workspace_id,
        machine_label="Test NT",
        capabilities=["telemetry", "accounts_read", "paper_commands"],
    )
    pending = connector_protocol.enroll_device({
        "code": started["code"],
        "public_key": jwk,
        "connector_version": "0.2.0-test",
        "nt_version": "8.1.6.3",
        "machine_label": "Test NT",
        "ninja_instance_id": "nt_test_instance_01",
    })
    return private, jwk, started, pending


def _hello(private, pending, *, overrides=None):
    payload = {
        "protocol_version": connector_protocol.PROTOCOL_VERSION,
        "connector_version": "0.2.0-test",
        "nt_version": "8.1.6.3",
        "installation_id": pending["installation_id"],
        "workspace_id": pending["workspace_id"],
        "nonce": pending["nonce"],
        "public_key_fingerprint": pending["public_key_fingerprint"],
        "ninja_instance_id": "nt_test_instance_01",
    }
    payload.update(overrides or {})
    payload["signature"] = _b64(private.sign(
        connector_protocol.hello_signing_message(payload),
        ec.ECDSA(hashes.SHA256()),
    ))
    return payload


def _challenge(private, pending, *, overrides=None):
    payload = {
        "protocol_version": connector_protocol.PROTOCOL_VERSION,
        "installation_id": pending["installation_id"],
        "public_key_fingerprint": pending["public_key_fingerprint"],
        "client_nonce": _b64(b"c" * 32),
        "requested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload.update(overrides or {})
    payload["signature"] = _b64(private.sign(
        connector_protocol.challenge_signing_message(payload),
        ec.ECDSA(hashes.SHA256()),
    ))
    return payload


@pytest.fixture
def connector_store(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "development"))
    monkeypatch.delenv("NTA_APP_ENV", raising=False)
    monkeypatch.delenv("NTA_ENV", raising=False)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(connector_protocol, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test encrypted store")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    subscriptions._write_doc({
        "version": 1,
        "vouchers": [],
        "entitlements": [
            {
                "entitlement_id": "ent_42",
                "user_id": 42,
                "workspace_id": "",
                "plan_id": "developer_free",
                "status": "active",
                "source": "test",
                "starts_at_utc": "2026-07-21T00:00:00Z",
                "expires_at_utc": "",
                "created_at_utc": "2026-07-21T00:00:00Z",
            },
            {
                "entitlement_id": "ent_7",
                "user_id": 7,
                "workspace_id": "",
                "plan_id": "developer_free",
                "status": "active",
                "source": "test",
                "starts_at_utc": "2026-07-21T00:00:00Z",
                "expires_at_utc": "",
                "created_at_utc": "2026-07-21T00:00:00Z",
            },
        ],
    })
    ws_42 = workspaces.ensure_personal_workspace(42)
    ws_7 = workspaces.ensure_personal_workspace(7)
    with server_mod._API_RATE_LOCK:
        server_mod._CONNECTOR_RATE.clear()
    return {42: ws_42, 7: ws_7, "root": tmp_path}


def _http_json(base: str, path: str, body: dict, *, token: str = ""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, dict(response.headers), json.loads(response.read())


def test_enrollment_stays_pending_until_valid_signed_hello(connector_store) -> None:
    workspace = connector_store[42]
    private, _, started, pending = _enroll(workspace["workspace_id"])

    assert pending["state"] == "pending"
    assert started["pairing_uri"].startswith("stratforge-connector://enroll?code=")
    listed = connector_protocol.list_installations(
        42, workspace_id=workspace["workspace_id"],
    )
    assert listed["connections"][0]["status"] == "pending"

    forged_private, _ = _device_key()
    with pytest.raises(connector_protocol.ConnectorProtocolError) as forged:
        connector_protocol.signed_hello(_hello(forged_private, pending))
    assert forged.value.code == "invalid_signature"
    assert connector_protocol.list_installations(
        42, workspace_id=workspace["workspace_id"],
    )["connections"][0]["status"] == "pending"

    welcome = connector_protocol.signed_hello(_hello(private, pending))
    assert welcome["state"] == "online"
    assert welcome["session_token"].startswith("sfc_v1_")
    assert welcome["allowed_capabilities"] == [
        "telemetry", "accounts_read", "paper_commands",
    ]

    with pytest.raises(connector_protocol.ConnectorProtocolError) as replay:
        connector_protocol.signed_hello(_hello(private, pending))
    assert replay.value.code == "invalid_nonce"

    raw_store = connector_protocol._store_path().read_bytes()
    assert started["code"].encode() not in raw_store
    assert welcome["session_token"].encode() not in raw_store


def test_challenge_rotation_requires_fresh_device_proof(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    forged_private, _ = _device_key()

    with pytest.raises(connector_protocol.ConnectorProtocolError) as forged:
        connector_protocol.issue_challenge(_challenge(forged_private, pending))
    assert forged.value.code == "invalid_signature"

    request = _challenge(private, pending)
    rotated = connector_protocol.issue_challenge(request)
    assert rotated["nonce"] != pending["nonce"]

    with pytest.raises(connector_protocol.ConnectorProtocolError) as replay:
        connector_protocol.issue_challenge(request)
    assert replay.value.code == "challenge_replay"

    stale = _challenge(private, pending, overrides={
        "client_nonce": _b64(b"d" * 32),
        "requested_at": (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).isoformat().replace("+00:00", "Z"),
    })
    with pytest.raises(connector_protocol.ConnectorProtocolError) as stale_error:
        connector_protocol.issue_challenge(stale)
    assert stale_error.value.code == "stale_challenge_request"

    welcome = connector_protocol.signed_hello(_hello(
        private, {**pending, "nonce": rotated["nonce"]},
    ))
    assert welcome["state"] == "online"


def test_reconnect_keeps_installation_and_supersedes_old_session(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    first = connector_protocol.signed_hello(_hello(private, pending))
    challenge = connector_protocol.issue_challenge(_challenge(
        private,
        pending,
        overrides={"client_nonce": _b64(b"r" * 32)},
    ))
    second = connector_protocol.signed_hello(_hello(
        private, {**pending, "nonce": challenge["nonce"]},
    ))

    assert second["connection_id"] == first["connection_id"]
    assert second["session_id"] != first["session_id"]
    with pytest.raises(connector_protocol.ConnectorProtocolError) as old_session:
        connector_protocol.heartbeat(first["session_token"], {
            "connector_sequence": 1,
            "ninja_instance_id": "nt_test_instance_01",
        })
    assert old_session.value.code == "session_expired"


def test_contract_schema_and_production_ui_states_are_versioned() -> None:
    root = Path(__file__).resolve().parent.parent
    schema = json.loads((
        root / "docs" / "schemas" / "connector-protocol-v1.schema.json"
    ).read_text(encoding="utf-8"))
    assert schema["$defs"]["hello"]["properties"]["protocol_version"]["const"] == "1.0"
    assert schema["$defs"]["challenge"]["additionalProperties"] is False
    assert schema["$defs"]["result"]["additionalProperties"] is False
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(
        encoding="utf-8",
    )
    assert "data-nt-revoke" in ui
    assert "ожидает подписи" in ui
    assert "connectorMode" in ui


def test_forged_workspace_and_fingerprint_are_rejected(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])

    with pytest.raises(connector_protocol.ConnectorProtocolError) as wrong_workspace:
        connector_protocol.signed_hello(_hello(
            private, pending, overrides={"workspace_id": connector_store[7]["workspace_id"]},
        ))
    assert wrong_workspace.value.code == "workspace_mismatch"

    with pytest.raises(connector_protocol.ConnectorProtocolError) as wrong_key:
        connector_protocol.signed_hello(_hello(
            private, pending, overrides={"public_key_fingerprint": "SHA256:" + "0" * 64},
        ))
    assert wrong_key.value.code == "key_mismatch"


def test_command_scope_idempotency_result_and_revoke(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    token = welcome["session_token"]

    command = connector_protocol.queue_command(
        42,
        workspace_id=workspace["workspace_id"],
        connection_id=welcome["connection_id"],
        capability="telemetry",
        idempotency_key="test-command-0001",
        payload={"command": "ping", "request": "health"},
        expires_in_sec=120,
    )
    replay = connector_protocol.queue_command(
        42,
        workspace_id=workspace["workspace_id"],
        connection_id=welcome["connection_id"],
        capability="telemetry",
        idempotency_key="test-command-0001",
        payload={"command": "ping", "request": "health"},
        expires_in_sec=120,
    )
    assert replay["command"]["idempotent_replay"] is True

    with pytest.raises(connector_protocol.ConnectorProtocolError) as conflict:
        connector_protocol.queue_command(
            42,
            workspace_id=workspace["workspace_id"],
            connection_id=welcome["connection_id"],
            capability="telemetry",
            idempotency_key="test-command-0001",
            payload={"command": "snapshot_runtime"},
            expires_in_sec=120,
        )
    assert conflict.value.code == "idempotency_conflict"

    polled = connector_protocol.poll_commands(
        token, connector_sequence=1, wait_seconds=0,
    )
    assert [row["command_id"] for row in polled["commands"]] == [
        command["command"]["command_id"],
    ]
    with pytest.raises(connector_protocol.ConnectorProtocolError) as sequence_replay:
        connector_protocol.poll_commands(token, connector_sequence=1)
    assert sequence_replay.value.code == "sequence_replay"

    completed = connector_protocol.submit_result(token, {
        "command_id": command["command"]["command_id"],
        "idempotency_key": "test-command-0001",
        "status": "completed",
        "connector_sequence": 2,
        "safe_result": {"message": "pong"},
        "error_class": "",
    })
    assert completed["command"]["status"] == "completed"
    status = connector_protocol.command_status(
        42,
        workspace_id=workspace["workspace_id"],
        command_id=command["command"]["command_id"],
    )
    assert status["result"]["safe_result"] == {"message": "pong"}

    with pytest.raises(workspaces.WorkspaceError):
        connector_protocol.list_installations(
            7, workspace_id=workspace["workspace_id"],
        )
    with pytest.raises(workspaces.WorkspaceError):
        connector_protocol.revoke_installation(
            7, welcome["connection_id"], workspace_id=workspace["workspace_id"],
        )

    revoked = connector_protocol.revoke_installation(
        42, welcome["connection_id"], workspace_id=workspace["workspace_id"],
    )
    assert revoked["connection"]["status"] == "revoked"
    with pytest.raises(connector_protocol.ConnectorProtocolError) as revoked_session:
        connector_protocol.heartbeat(token, {
            "connector_sequence": 3,
            "ninja_instance_id": "nt_test_instance_01",
        })
    assert revoked_session.value.code in {"session_expired", "installation_revoked"}


def test_expired_offline_command_is_never_delivered(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    queued = connector_protocol.queue_command(
        42,
        workspace_id=workspace["workspace_id"],
        connection_id=welcome["connection_id"],
        capability="accounts_read",
        idempotency_key="expire-command-0001",
        payload={"command": "snapshot_accounts"},
        expires_in_sec=5,
    )
    with connector_protocol._LOCK:
        doc = connector_protocol._read_doc()
        row = next(item for item in doc["commands"] if item["command_id"] == queued["command"]["command_id"])
        row["expires_at"] = time.time() - 1
        connector_protocol._write_doc(doc)

    polled = connector_protocol.poll_commands(
        welcome["session_token"], connector_sequence=1, wait_seconds=0,
    )
    assert polled["commands"] == []
    status = connector_protocol.command_status(
        42,
        workspace_id=workspace["workspace_id"],
        command_id=queued["command"]["command_id"],
    )
    assert status["command"]["status"] == "expired"


def test_heartbeat_masks_accounts_and_rejects_instance_change(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    hb = connector_protocol.heartbeat(welcome["session_token"], {
        "connector_sequence": 1,
        "ninja_instance_id": "nt_test_instance_01",
        "account_labels": ["DEMO3369390", "SIM-SECRET-99"],
    })
    assert hb["state"] == "online"
    listed = connector_protocol.list_installations(
        42, workspace_id=workspace["workspace_id"],
    )
    labels = listed["connections"][0]["account_labels"]
    assert labels == ["***9390", "***ET99"]
    assert "DEMO3369390" not in json.dumps(listed)

    with pytest.raises(connector_protocol.ConnectorProtocolError) as mismatch:
        connector_protocol.heartbeat(welcome["session_token"], {
            "connector_sequence": 2,
            "ninja_instance_id": "nt_other_instance_99",
        })
    assert mismatch.value.code == "instance_mismatch"


def test_http_long_poll_connector_flow_has_no_browser_cookie(connector_store) -> None:
    workspace = connector_store[42]
    private, jwk = _device_key()
    started = connector_protocol.start_enrollment(
        42,
        workspace_id=workspace["workspace_id"],
        machine_label="HTTP NT",
        capabilities=["telemetry"],
    )
    srv = server_mod.ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        _, enroll_headers, pending = _http_json(base, "/api/connector/v1/enroll", {
            "code": started["code"],
            "public_key": jwk,
            "connector_version": "0.2.0-test",
            "nt_version": "8.1.6.3",
            "machine_label": "HTTP NT",
            "ninja_instance_id": "nt_http_instance_01",
        })
        assert pending["state"] == "pending"
        assert enroll_headers["Cache-Control"] == "no-store"
        assert "Set-Cookie" not in enroll_headers

        challenge_request = _challenge(private, pending, overrides={
            "client_nonce": _b64(b"h" * 32),
        })
        _, challenge_headers, challenge = _http_json(
            base, "/api/connector/v1/challenge", challenge_request,
        )
        assert challenge_headers["Cache-Control"] == "no-store"
        assert "Set-Cookie" not in challenge_headers

        hello = {
            "protocol_version": connector_protocol.PROTOCOL_VERSION,
            "connector_version": "0.2.0-test",
            "nt_version": "8.1.6.3",
            "installation_id": pending["installation_id"],
            "workspace_id": pending["workspace_id"],
            "nonce": challenge["nonce"],
            "public_key_fingerprint": pending["public_key_fingerprint"],
            "ninja_instance_id": "nt_http_instance_01",
        }
        hello["signature"] = _b64(private.sign(
            connector_protocol.hello_signing_message(hello),
            ec.ECDSA(hashes.SHA256()),
        ))
        _, hello_headers, welcome = _http_json(
            base, "/api/connector/v1/hello", hello,
        )
        assert welcome["state"] == "online"
        assert hello_headers["Cache-Control"] == "no-store"
        token = welcome["session_token"]

        queued = connector_protocol.queue_command(
            42,
            workspace_id=workspace["workspace_id"],
            connection_id=welcome["connection_id"],
            capability="telemetry",
            idempotency_key="http-command-0001",
            payload={"command": "ping"},
            expires_in_sec=120,
        )
        _, _, polled = _http_json(
            base,
            "/api/connector/v1/commands/poll",
            {"connector_sequence": 1, "wait_seconds": 1},
            token=token,
        )
        assert polled["commands"][0]["command_id"] == queued["command"]["command_id"]
        _, _, result = _http_json(
            base,
            "/api/connector/v1/commands/result",
            {
                "command_id": queued["command"]["command_id"],
                "idempotency_key": "http-command-0001",
                "status": "completed",
                "connector_sequence": 2,
                "safe_result": {"message": "pong"},
                "error_class": "",
            },
            token=token,
        )
        assert result["command"]["status"] == "completed"

        with pytest.raises(urllib.error.HTTPError) as missing_token:
            _http_json(
                base,
                "/api/connector/v1/heartbeat",
                {"connector_sequence": 3, "ninja_instance_id": "nt_http_instance_01"},
            )
        assert missing_token.value.code == 401
        assert json.loads(missing_token.value.read())["code"] == "invalid_session"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
