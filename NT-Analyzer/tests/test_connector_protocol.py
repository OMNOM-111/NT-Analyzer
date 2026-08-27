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

from app import account_auth, connector_protocol
from app import secure_store
from app import server as server_mod
from app import runtime as ops_runtime
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
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(connector_protocol, "_root", lambda: tmp_path)
    with connector_protocol._RUNTIME_ACCOUNT_CACHE_LOCK:
        connector_protocol._RUNTIME_ACCOUNT_CACHE.clear()
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test encrypted store")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    account_auth._write_doc({
        "version": 3,
        "users": [
            {"user_id": 42, "legacy_user_id": 42,
             "user_uuid": "71900420-731c-4ee9-b842-1b0045781f2a",
             "first_name": "Ada", "status": "active", "is_owner": False},
            {"user_id": 7, "legacy_user_id": 7,
             "user_uuid": "805e497b-45fb-4ad5-a96b-c148d09ccfbd",
             "first_name": "Grace", "status": "active", "is_owner": False},
        ],
        "auth_identities": [], "challenges": [], "sessions": [],
    })
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


def test_phase3_connector_identity_backfill_preserves_legacy_mappings(connector_store) -> None:
    user_uuid = account_auth.user_uuid_for_legacy_id(42)
    connector_protocol._write_doc({
        "schema_version": 1,
        "enrollments": [{
            "enrollment_id": "enr_phase3", "created_by_user_id": 42,
        }],
        "installations": [{
            "installation_id": "inst_phase3", "enrolled_by_user_id": 42,
        }],
        "sessions": [{
            "session_id": "csess_phase3", "installation_id": "inst_phase3",
        }],
        "commands": [{
            "command_id": "cmd_phase3", "installation_id": "inst_phase3",
            "issued_by_user_id": 42,
        }],
        "results": [],
    })

    migrated = connector_protocol._read_doc()

    assert migrated["enrollments"][0]["created_by_user_id"] == 42
    assert migrated["enrollments"][0]["created_by_user_uuid"] == user_uuid
    assert migrated["installations"][0]["enrolled_by_user_id"] == 42
    assert migrated["installations"][0]["user_id"] == 42
    assert migrated["installations"][0]["user_uuid"] == user_uuid
    assert migrated["sessions"][0]["user_id"] == 42
    assert migrated["sessions"][0]["user_uuid"] == user_uuid
    assert migrated["commands"][0]["issued_by_user_id"] == 42
    assert migrated["commands"][0]["issued_by_user_uuid"] == user_uuid
    assert migrated["commands"][0]["user_uuid"] == user_uuid


def test_phase3_connector_identity_backfill_resolves_each_user_once(monkeypatch) -> None:
    user_42 = "71900420-731c-4ee9-b842-1b0045781f2a"
    user_7 = "805e497b-45fb-4ad5-a96b-c148d09ccfbd"
    calls: list[int] = []

    def resolve(user_id):
        value = int(user_id or 0)
        calls.append(value)
        return {42: user_42, 7: user_7}.get(value, "")

    monkeypatch.setattr(connector_protocol, "_user_uuid_for_legacy_id", resolve)
    doc = {
        "schema_version": connector_protocol.CONNECTOR_STORE_VERSION,
        "enrollments": [{
            "enrollment_id": "enr_cached", "created_by_user_id": 42,
            "created_by_user_uuid": "incorrect",
        }],
        "installations": [{
            "installation_id": "inst_cached", "enrolled_by_user_id": 42,
            "user_id": 42, "user_uuid": "incorrect",
        }],
        "sessions": [
            {
                "session_id": f"csess_cached_{index}",
                "installation_id": "inst_cached", "user_id": 42,
                "user_uuid": user_42,
            }
            for index in range(1_100)
        ],
        "commands": [{
            "command_id": "cmd_cached", "installation_id": "inst_cached",
            "issued_by_user_id": 7, "user_id": 7,
            "issued_by_user_uuid": "incorrect", "user_uuid": "incorrect",
        }],
        "results": [
            {
                "command_id": "cmd_cached", "user_id": 7,
                "user_uuid": "incorrect",
            },
            {"command_id": "cmd_without_user"},
        ],
        "identity_schema": {
            "stage": "dual_write", "canonical_key": "user_uuid",
            "legacy_key": "user_id",
        },
    }

    migrated, changed = connector_protocol._migrate_doc(doc)

    assert changed is True
    assert calls == [42, 7]
    assert migrated["enrollments"][0]["created_by_user_uuid"] == user_42
    assert migrated["installations"][0]["user_uuid"] == user_42
    assert all(row["user_uuid"] == user_42 for row in migrated["sessions"])
    assert migrated["commands"][0]["issued_by_user_uuid"] == user_7
    assert migrated["commands"][0]["user_uuid"] == user_7
    assert migrated["results"][0]["user_uuid"] == user_7
    assert "user_uuid" not in migrated["results"][1]


def test_phase3_connector_creation_dual_writes_uuid_companions(connector_store) -> None:
    workspace = connector_store[42]
    user_uuid = account_auth.user_uuid_for_legacy_id(42)
    private, _, _, pending = _enroll(workspace["workspace_id"])
    installation = connector_protocol.list_installations(
        42, workspace_id=workspace["workspace_id"],
    )["connections"][0]
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    command = connector_protocol.queue_command(
        42,
        workspace_id=workspace["workspace_id"],
        connection_id=welcome["connection_id"],
        capability="telemetry",
        idempotency_key="phase3-connector-command-01",
        payload={"command": "ping"},
    )["command"]
    document = connector_protocol._read_doc()

    assert installation["user_uuid"] == user_uuid
    assert command["user_uuid"] == user_uuid
    assert command["issued_by_user_uuid"] == user_uuid
    assert document["sessions"][0]["user_uuid"] == user_uuid


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


def _market_data_payload(connector_sequence: int, source_sequence: int = 1) -> dict:
    return {
        "connector_sequence": connector_sequence,
        "source_sequence": source_sequence,
        "bars": [{
            "timestamp": "2026-07-22T12:00:00Z",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000,
            "exact_contract": "MNQ 09-26",
            "timeframe": "1m",
        }],
    }


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
    assert schema["$defs"]["marketData"]["properties"]["bars"]["maxItems"] == 64
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(
        encoding="utf-8",
    )
    assert "data-nt-revoke" in ui
    assert "ожидает подписи" in ui
    assert "connectorMode" in ui


def test_csharp_connector_exposes_bounded_market_data_upload_hook() -> None:
    root = Path(__file__).resolve().parent.parent
    client = (root / "bridge" / "src" / "Connector" / "ConnectorClient.cs").read_text(
        encoding="utf-8",
    )
    addon = (root / "bridge" / "src" / "BridgeAddOn.cs").read_text(encoding="utf-8")
    state = (root / "bridge" / "src" / "Connector" / "ConnectorStateStore.cs").read_text(
        encoding="utf-8",
    )
    exporter = (root / "bridge" / "src" / "Connector" / "ProductionMarketDataExporter.cs").read_text(
        encoding="utf-8",
    )
    config = (root / "bridge" / "src" / "Config" / "BridgeConfig.cs").read_text(
        encoding="utf-8",
    )
    example = json.loads((
        root / "bridge" / "NTAnalyzerBridge.config.example.json"
    ).read_text(encoding="utf-8"))
    assert "QueueMarketDataBatch" in client
    assert '"api/connector/v1/market-data"' in client
    assert "MaxMarketDataBarsPerBatch = 64" in client
    assert "MaxMarketDataFlushBurst = MaxQueuedMarketDataBatches * 2" in client
    assert "for (int sent = 0; sent < MaxMarketDataFlushBurst; sent++)" in client
    assert "if (!FlushOneMarketDataBatch()) return;" in client
    assert 'heartbeat["account_snapshot"] = accountSnapshot' in client
    assert "ReadAccountSnapshot()" in client
    assert "48 * 1024" in client
    assert "market_data_source_sequence" in state
    assert "QueueProductionMarketData" in addon
    assert "new ProductionMarketDataExporter" in addon
    assert "MaxBarsPerBatch = 64" in exporter
    assert "Thread(SenderLoop)" in exporter
    assert "Connection.ConnectionStatusUpdate += OnConnectionStatusUpdate" in exporter
    assert "Connection.ConnectionStatusUpdate -= OnConnectionStatusUpdate" in exporter
    assert "snapshot.PriceStatus != ConnectionStatus.Connected" in exporter
    assert "Interlocked.CompareExchange(ref _connectionRefreshPending, 1, 0)" in exporter
    assert "if (_running && ForceResubscribe())" in exporter
    assert "MarketDataIpcClient" not in exporter
    assert "market_data_streams" in config
    assert example["production_connector"]["market_data_streams"] == []


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


def test_signed_heartbeat_carries_a_bounded_functional_account_snapshot(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    snapshot = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exporter_version": "0.4.2-dev.7",
        "accounts": [{
            "account_name": "DEMO3369390", "account_mode": "paper",
            "cash_value": 11017.42, "buying_power": 22034.84,
            "net_liquidation": 11017.42, "realized_pnl": 0,
            "unrealized_pnl": 0, "currency": "USD",
            "connection_status": "Connected", "availability_notes": [],
        }],
        "summary": {"total": 1, "paper": 1, "live": 0, "playback": 0, "unknown": 0},
    }
    connector_protocol.heartbeat(welcome["session_token"], {
        "connector_sequence": 1,
        "ninja_instance_id": "nt_test_instance_01",
        "account_labels": ["DEMO3369390"],
        "account_snapshot": snapshot,
    })

    status = connector_protocol.runtime_account_status(
        42, workspace_id=workspace["workspace_id"],
    )
    assert status["functional_live"] is True
    assert status["account_count"] == 1
    assert status["accounts"][0]["net_liquidation"] == 11017.42
    assert status["source_workspace_id"] == workspace["workspace_id"]
    ui_payload = ops_runtime.accounts_from_connector_status(status)
    assert ui_payload["source"] == "production_connector"
    assert ui_payload["bridge_online"] is True
    assert ui_payload["functional_live"] is True
    assert ui_payload["accounts"][0]["is_selectable_for_online"] is True

    other = connector_protocol.runtime_account_status(
        7, workspace_id=connector_store[7]["workspace_id"],
    )
    assert other["functional_live"] is False
    assert other["accounts"] == []


def test_connector_transport_runtime_accounts_use_the_signed_snapshot(monkeypatch) -> None:
    """Where the Connector is the transport, its snapshot is the answer.

    Development is not such a place -- it reads the NinjaTrader beside it --
    so the transport is requested explicitly here, the same way the Connector
    view is reachable from LOCAL without taking LOCAL's own data path away.
    """
    monkeypatch.setattr(server_mod.runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(server_mod.runtime_env, "is_production", lambda: True)
    handler = object.__new__(server_mod.Handler)
    handler._remote_context = {"user_id": 42}
    replies = []
    handler._json = lambda status, payload: replies.append((status, payload))
    monkeypatch.setattr(server_mod, "_connector_runtime_status", lambda _context: {
        "present": True,
        "fresh": True,
        "functional_live": True,
        "installation_id": "inst_local_functional",
        "source_workspace_id": "ws_owner_training_test",
        "account_snapshot_at_utc": "2026-08-26T23:30:00Z",
        "account_count": 1,
        "accounts": [{
            "account_name": "DEMO3369390",
            "cash_value": 11017.42,
            "net_liquidation": 11017.42,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
        }],
    })
    monkeypatch.setattr(
        server_mod.ops_runtime,
        "read_accounts_with_source",
        lambda: pytest.fail("a server has no local runtime directory to read"),
    )

    assert handler._ops_get("/api/ops/runtime/accounts", {}) is True
    assert replies[0][1]["source"] == "production_connector"
    assert replies[0][1]["accounts"][0]["account_name"] == "DEMO3369390"
    assert replies[0][1]["accounts"][0]["net_liquidation"] == 11017.42


def test_owner_runtime_resolves_only_the_same_owners_connector(connector_store) -> None:
    personal = connector_store[42]
    private, _, _, pending = _enroll(personal["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    connector_protocol.heartbeat(welcome["session_token"], {
        "connector_sequence": 1,
        "ninja_instance_id": "nt_test_instance_01",
        "account_snapshot": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "exporter_version": "test",
            "accounts": [{"account_name": "DEMO3369390", "account_mode": "paper"}],
        },
    })
    owner_workspace = workspaces.ensure_owner_workspace(42)
    status = connector_protocol.runtime_account_status(
        42, workspace_id=owner_workspace["workspace_id"],
        uses_owner_runtime=True, is_owner=True,
    )
    assert status["functional_live"] is True
    assert status["resolved_via_owner_runtime"] is True
    assert status["requested_workspace_id"] == owner_workspace["workspace_id"]
    assert status["source_workspace_id"] == personal["workspace_id"]
    setup = connector_protocol.setup_payload(
        42, workspace_id=owner_workspace["workspace_id"],
        uses_owner_runtime=True, is_owner=True,
    )
    assert setup["owner_runtime"] is True
    assert setup["connections"][0]["functional_online"] is True
    assert setup["connections"][0]["account_snapshot_accounts"] == 1


def test_account_snapshot_rejects_unbounded_or_unknown_data(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    with pytest.raises(connector_protocol.ConnectorProtocolError) as invalid:
        connector_protocol.heartbeat(welcome["session_token"], {
            "connector_sequence": 1,
            "ninja_instance_id": "nt_test_instance_01",
            "account_snapshot": {
                "accounts": [{"account_name": "DEMO3369390", "secret": "must-not-pass"}],
            },
        })
    assert invalid.value.code == "invalid_account_snapshot"


def test_market_data_is_session_bound_idempotent_and_persists_bars(connector_store) -> None:
    from app import market_data_ingestion

    market_data_ingestion.reset_for_tests()
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    token = welcome["session_token"]

    first = connector_protocol.ingest_market_data(token, _market_data_payload(1))
    assert first["ok"] is True
    assert first["items"] == 1
    snapshot = market_data_ingestion.latest_snapshot(
        workspace["workspace_id"], pending["installation_id"], "MNQ 09-26", "1m",
    )
    assert snapshot["document"]["bars"][0]["close"] == 100.5

    replay = connector_protocol.ingest_market_data(token, _market_data_payload(2))
    assert replay["idempotent_replay"] is True
    changed = _market_data_payload(3)
    changed["bars"][0]["close"] = 100.25
    with pytest.raises(connector_protocol.ConnectorProtocolError) as conflict:
        connector_protocol.ingest_market_data(token, changed)
    assert conflict.value.code == "source_sequence_conflict"


def test_market_data_requires_telemetry_capability(connector_store) -> None:
    workspace = connector_store[42]
    private, jwk = _device_key()
    started = connector_protocol.start_enrollment(
        42,
        workspace_id=workspace["workspace_id"],
        machine_label="No telemetry",
        capabilities=["accounts_read"],
    )
    pending = connector_protocol.enroll_device({
        "code": started["code"],
        "public_key": jwk,
        "connector_version": "0.2.0-test",
        "nt_version": "8.1.6.3",
        "machine_label": "No telemetry",
        "ninja_instance_id": "nt_no_telemetry_01",
    })
    welcome = connector_protocol.signed_hello(_hello(
        private, pending, overrides={"ninja_instance_id": "nt_no_telemetry_01"},
    ))

    with pytest.raises(connector_protocol.ConnectorProtocolError) as denied:
        connector_protocol.ingest_market_data(welcome["session_token"], _market_data_payload(1))
    assert denied.value.code == "market_data_capability_denied"


def test_blocked_connector_version_cannot_queue_unsafe_commands(
    connector_store, monkeypatch, tmp_path: Path,
) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    release = {
        "version": "0.2.1-test",
        "archive_url": "https://releases.stratforges.com/connector-test.zip",
        "archive_sha256": "A" * 64,
        "manifest_sha256": "B" * 64,
        "protocol_version": "1.0",
        "minimum_version": "0.2.0-test",
        "blocked_versions": ["0.2.0-test"],
        "major_approved": False,
        "health_timeout_sec": 900,
        "published_at_utc": "2026-07-21T00:00:00Z",
    }
    catalog = tmp_path / "connector-releases.json"
    catalog.write_text(json.dumps({
        "schema_version": 1,
        "channels": {"stable": release, "canary": release},
        "canary_installation_ids": [],
    }), encoding="utf-8")
    monkeypatch.setenv("STRATFORGE_CONNECTOR_RELEASE_CATALOG", str(catalog))

    welcome = connector_protocol.signed_hello(_hello(private, pending))
    assert welcome["update_state"] == "blocked"
    assert welcome["update_reason"] == "version_revoked"
    assert welcome["update_offer"]["version"] == "0.2.1-test"

    telemetry = connector_protocol.queue_command(
        42,
        workspace_id=workspace["workspace_id"],
        connection_id=welcome["connection_id"],
        capability="telemetry",
        idempotency_key="blocked-safe-telemetry-01",
        payload={"command": "ping"},
    )
    assert telemetry["command"]["status"] == "queued"
    with pytest.raises(connector_protocol.ConnectorProtocolError) as unsafe:
        connector_protocol.queue_command(
            42,
            workspace_id=workspace["workspace_id"],
            connection_id=welcome["connection_id"],
            capability="paper_commands",
            idempotency_key="blocked-paper-command-01",
            payload={"command": "disable_strategy"},
        )
    assert unsafe.value.status == 426
    assert unsafe.value.code == "connector_update_required"


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

        _, market_headers, market = _http_json(
            base,
            "/api/connector/v1/market-data",
            _market_data_payload(1),
            token=token,
        )
        assert market["items"] == 1
        assert market_headers["Cache-Control"] == "no-store"

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
            {"connector_sequence": 2, "wait_seconds": 1},
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
                "connector_sequence": 3,
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
                {"connector_sequence": 4, "ninja_instance_id": "nt_http_instance_01"},
            )
        assert missing_token.value.code == 401
        assert json.loads(missing_token.value.read())["code"] == "invalid_session"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_re_enrollment_after_revoke(connector_store) -> None:
    workspace = connector_store[42]
    private, jwk, started, pending = _enroll(workspace["workspace_id"])
    welcome = connector_protocol.signed_hello(_hello(private, pending))
    assert welcome["state"] == "online"
    
    # Revoke
    connector_protocol.revoke_installation(42, welcome["connection_id"])
    
    # Re-enroll
    private2, jwk2, started2, pending2 = _enroll(workspace["workspace_id"])
    welcome2 = connector_protocol.signed_hello(_hello(private2, pending2))
    assert welcome2["state"] == "online"
    assert pending["installation_id"] != pending2["installation_id"]


def test_expired_enrollment_code(connector_store, monkeypatch) -> None:
    import time
    workspace = connector_store[42]
    
    private, jwk = _device_key()
    started = connector_protocol.start_enrollment(
        42,
        workspace_id=workspace["workspace_id"],
        machine_label="Test NT",
        capabilities=["telemetry", "accounts_read", "paper_commands"],
    )
    
    # Fast forward
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 900)
    
    with pytest.raises(connector_protocol.ConnectorProtocolError) as exc:
        connector_protocol.enroll_device({
            "code": started["code"],
            "public_key": jwk,
            "connector_version": "0.2.0-test",
            "nt_version": "8.1.6.3",
            "machine_label": "Test NT",
            "ninja_instance_id": "nt_test_instance_01",
        })
    assert exc.value.code == "enrollment_unavailable"


def test_blocked_handshake_rollback(connector_store) -> None:
    workspace = connector_store[42]
    private, jwk, started, pending = _enroll(workspace["workspace_id"])
    
    # Send forged signature
    forged_private, _ = _device_key()
    with pytest.raises(connector_protocol.ConnectorProtocolError) as exc:
        connector_protocol.signed_hello(_hello(forged_private, pending))
    assert exc.value.code == "invalid_signature"
    
    # The installation shouldn't be fully enrolled / active
    listed = connector_protocol.list_installations(
        42, workspace_id=workspace["workspace_id"],
    )
    assert listed["connections"][0]["status"] == "pending"


# --------------------------------------------------------------------------- #
# A status probe must answer the status question without doing maintenance
# work: list_installations sweeps and persists, which turns a diagnostics read
# into a write under the connector lock, competing with the heartbeats of the
# device it is reporting on.
# --------------------------------------------------------------------------- #
def test_health_summary_reports_an_online_connector(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    summary = connector_protocol.health_summary(
        42, workspace_id=workspace["workspace_id"])
    assert summary["ok"] is True
    assert summary["installations"] == 1
    assert summary["online"] == 1
    assert summary["last_heartbeat_utc"]


def test_health_summary_never_writes_the_connector_document(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    writes = []
    original = connector_protocol._write_doc
    connector_protocol._write_doc = lambda doc: writes.append(1) or original(doc)
    try:
        for _ in range(5):
            connector_protocol.health_summary(
                42, workspace_id=workspace["workspace_id"])
    finally:
        connector_protocol._write_doc = original
    assert writes == [], "a status probe must not persist anything"


def test_health_summary_does_not_report_a_stale_device_as_online(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    doc = connector_protocol._read_doc()
    for row in doc["installations"]:
        row["last_heartbeat_at"] = time.time() - connector_protocol.OFFLINE_AFTER_SEC - 60
    connector_protocol._write_doc(doc)

    summary = connector_protocol.health_summary(
        42, workspace_id=workspace["workspace_id"])
    assert summary["installations"] == 1
    assert summary["online"] == 0, "expiry is applied in the reply, not persisted"
    # ...and still without writing.
    after = connector_protocol._read_doc()
    assert after["installations"][0]["status"] == "online"


def test_a_timed_out_probe_does_not_claim_the_source_is_unhealthy() -> None:
    """Diagnostics failure and source health are different facts."""
    slow = server_mod._connector_probe("connector", lambda: time.sleep(5), timeout_sec=0.2)
    assert slow["state"] == "timeout"
    assert slow["diagnostics"] == "timeout"
    assert slow["status_known"] is False
    # It must not invent counts that would read as "nothing is connected".
    assert "online" not in slow and "installations" not in slow
    assert "не измерено" in slow["detail"]

    broken = server_mod._connector_probe(
        "connector", lambda: (_ for _ in ()).throw(RuntimeError("boom")), timeout_sec=2)
    assert broken["state"] == "error"
    assert broken["status_known"] is False

    good = server_mod._connector_probe(
        "connector", lambda: {"installations": 1, "online": 1}, timeout_sec=2)
    assert good["status_known"] is True
    assert good["diagnostics"] == "ok"
    assert good["online"] == 1


def test_health_summary_gives_up_on_a_busy_store_instead_of_hanging(connector_store, monkeypatch) -> None:
    """A status question must not queue behind connector traffic."""
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    monkeypatch.setattr(connector_protocol, "HEALTH_SUMMARY_LOCK_WAIT_SEC", 0.2)
    holding = threading.Event()
    release = threading.Event()

    def hog():
        with connector_protocol._LOCK:
            holding.set()
            release.wait(timeout=5)

    worker = threading.Thread(target=hog, daemon=True)
    worker.start()
    holding.wait(timeout=5)
    try:
        started = time.monotonic()
        out = connector_protocol.health_summary(
            42, workspace_id=workspace["workspace_id"])
        elapsed = time.monotonic() - started
    finally:
        release.set()
        worker.join(timeout=5)

    assert elapsed < 1.0, "must not spend the caller's whole budget waiting"
    assert out["status_known"] is False
    assert out["reason"] == "connector_store_busy"
    # It must not invent an answer that reads as "nothing is connected".
    assert "online" not in out and "installations" not in out


def test_idle_long_poll_tick_is_not_a_tight_lock_loop() -> None:
    """Each idle tick costs a shared-lock acquisition and a database round trip."""
    assert connector_protocol.IDLE_POLL_TICK_SEC >= 2.0
    source = (Path(__file__).resolve().parent.parent
              / "app" / "connector_protocol.py").read_text(encoding="utf-8")
    body = source.split("def poll_commands", 1)[1].split("\ndef ", 1)[0]
    assert "IDLE_POLL_TICK_SEC" in body
    assert "min(0.5," not in body, "the half-second idle tick is what starved readers"


def test_status_snapshot_serves_a_busy_store_instead_of_giving_up(connector_store, monkeypatch) -> None:
    """A recent answer beats "unknown" when the document read is expensive."""
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    first = connector_protocol.health_summary(42, workspace_id=workspace["workspace_id"])
    assert first["status_known"] is True and first["stale_sec"] == 0.0

    # Now make the store unreachable and hold the lock: the snapshot answers.
    monkeypatch.setattr(connector_protocol, "HEALTH_SUMMARY_LOCK_WAIT_SEC", 0.1)
    monkeypatch.setattr(connector_protocol, "HEALTH_SNAPSHOT_TTL_SEC", 0.0)
    holding, release = threading.Event(), threading.Event()

    def hog():
        with connector_protocol._LOCK:
            holding.set()
            release.wait(timeout=5)

    worker = threading.Thread(target=hog, daemon=True)
    worker.start()
    holding.wait(timeout=5)
    try:
        out = connector_protocol.health_summary(42, workspace_id=workspace["workspace_id"])
    finally:
        release.set()
        worker.join(timeout=5)

    assert out["status_known"] is True
    assert out["installations"] == first["installations"]
    assert out["online"] == first["online"]
    assert out["stale_sec"] >= 0.0, "the age of the answer travels with it"


def test_enrolled_but_offline_is_reported_as_offline_not_as_a_fault(connector_store) -> None:
    """NinjaTrader being down for maintenance is an operational state."""
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    doc = connector_protocol._read_doc()
    for row in doc["installations"]:
        row["last_heartbeat_at"] = time.time() - connector_protocol.OFFLINE_AFTER_SEC - 600
    connector_protocol._write_doc(doc)
    connector_protocol._HEALTH_SNAPSHOT.clear()

    out = connector_protocol.health_summary(42, workspace_id=workspace["workspace_id"])
    assert out["status_known"] is True
    assert out["installations"] == 1 and out["online"] == 0


def test_a_stale_snapshot_refreshes_itself_off_the_request_path(connector_store, monkeypatch) -> None:
    """A snapshot that can never refresh just grows old in silence."""
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))
    connector_protocol._HEALTH_SNAPSHOT.clear()

    first = connector_protocol.health_summary(42, workspace_id=workspace["workspace_id"])
    assert first["installations"] == 1

    # A second device appears while the snapshot is still warm.
    private2, _, _, pending2 = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private2, pending2))

    monkeypatch.setattr(connector_protocol, "HEALTH_SNAPSHOT_TTL_SEC", 0.0)
    started = time.monotonic()
    served = connector_protocol.health_summary(42, workspace_id=workspace["workspace_id"])
    # The caller is answered immediately from the old snapshot...
    assert time.monotonic() - started < 0.5
    assert served["status_known"] is True

    # ...and the refresh lands shortly afterwards without anyone waiting on it.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        latest = connector_protocol.health_summary(42, workspace_id=workspace["workspace_id"])
        if latest["installations"] == 2:
            break
        time.sleep(0.05)
    assert latest["installations"] == 2, "the background refresh never landed"


def test_background_refresh_runs_one_worker_per_workspace(connector_store, monkeypatch) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))
    connector_protocol._HEALTH_SNAPSHOT.clear()
    connector_protocol.health_summary(42, workspace_id=workspace["workspace_id"])

    monkeypatch.setattr(connector_protocol, "HEALTH_SNAPSHOT_TTL_SEC", 0.0)
    started = []
    real = threading.Thread

    class Counting(real):
        def start(self):
            started.append(self.name)
            return super().start()

    monkeypatch.setattr(connector_protocol.threading, "Thread", Counting)
    with connector_protocol._LOCK:          # hold it so refreshes cannot finish
        for _ in range(5):
            connector_protocol.health_summary(42, workspace_id=workspace["workspace_id"])
        assert len(started) == 1, started


# --------------------------------------------------------------------------- #
# An operator must be able to tell "waiting for a restart" and "registered in
# another environment" apart from a plain dead device.
# --------------------------------------------------------------------------- #
def test_installation_reports_restart_required_for_a_safe_restart_update(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    doc = connector_protocol._read_doc()
    row = doc["installations"][0]
    row["update_state"] = "update_available"
    row["update_policy"] = "safe_restart"
    public = connector_protocol._public_installation(row)
    assert public["restart_required"] is True
    assert public["update_policy"] == "safe_restart"

    # A major update needing a real reinstall is not a restart prompt.
    row["update_policy"] = "manual"
    assert connector_protocol._public_installation(row)["restart_required"] is False
    # And an up-to-date connector never asks for one.
    row["update_state"] = "compatible"
    row["update_policy"] = "safe_restart"
    assert connector_protocol._public_installation(row)["restart_required"] is False


def test_installation_exposes_its_environment_and_flags_a_mismatch(connector_store) -> None:
    """A connector refused for belonging elsewhere must not read as 'offline'."""
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    doc = connector_protocol._read_doc()
    row = doc["installations"][0]
    here = connector_protocol.runtime_env.deployment_environment()
    assert connector_protocol._public_installation(row)["deployment_environment"] == here
    assert connector_protocol._public_installation(row)["environment_mismatch"] is False

    row["deployment_environment"] = "canary" if here != "canary" else "production"
    public = connector_protocol._public_installation(row)
    assert public["environment_mismatch"] is True
    assert public["deployment_environment"] in {"canary", "production"}


# --------------------------------------------------------------------------- #
# "Not calling" and "calling and being refused" must be distinguishable. Only
# successes were audited, so a turned-away connector left no trace at all.
# --------------------------------------------------------------------------- #
def test_a_refused_request_is_recorded(connector_store) -> None:
    connector_protocol.audit_refusal(
        "/api/connector/v1/hello", "connector_environment_mismatch", 403,
        installation_id="inst_probe",
    )
    rows = connector_protocol.recent_audit(20)
    refusals = [r for r in rows if r.get("event") == "request_refused"]
    assert refusals, rows
    last = refusals[-1]
    assert last["route"] == "/api/connector/v1/hello"
    assert last["code"] == "connector_environment_mismatch"
    assert last["status"] == 403
    assert last["installation_id"] == "inst_probe"


def test_audit_read_is_redacted_to_status_fields(connector_store) -> None:
    workspace = connector_store[42]
    private, _, _, pending = _enroll(workspace["workspace_id"])
    connector_protocol.signed_hello(_hello(private, pending))

    allowed = {
        "event", "event_type", "occurred_at", "timestamp_utc", "route", "code",
        "status", "installation_id", "workspace_id", "session_id",
        "enrollment_id", "connector_version", "update_state", "update_reason",
        "public_key_fingerprint", "source",
    }
    rows = connector_protocol.recent_audit(50)
    assert rows, "the successful hello should be visible too"
    for row in rows:
        assert set(row).issubset(allowed), set(row) - allowed
    # A token or signature must never appear.
    blob = json.dumps(rows)
    assert "session_token" not in blob and "signature" not in blob


def test_audit_refusal_never_raises(connector_store, monkeypatch) -> None:
    """Observability must not turn a refusal into a server error."""
    def boom(*_a, **_k):
        raise RuntimeError("audit sink down")

    monkeypatch.setattr(connector_protocol, "_audit", boom)
    connector_protocol.audit_refusal("/api/connector/v1/hello", "x", 400)


def test_connector_audit_endpoint_is_wired_and_owner_gated() -> None:
    """The route 500'd on a NameError because context was never defined here."""
    source = (Path(__file__).resolve().parent.parent / "app" / "server.py").read_text(encoding="utf-8")
    block = source.split('if path == "/api/admin/connector-audit":', 1)[1]
    block = block.split('if path == "/api/admin/development-sync":', 1)[0]
    # Every name the block uses must be bound inside it or by the route.
    assert 'context = getattr(self, "_remote_context", None) or {}' in block
    assert "_require_release_capability(context" in block
    assert "connector_protocol.recent_audit(" in block
    # Bounded, so a caller cannot ask for the whole table.
    assert "min(200" in block


def test_storage_refusal_detail_survives_to_the_audit(connector_store) -> None:
    """A storage constraint names what it denied; the code alone is unactionable."""
    connector_protocol.audit_refusal(
        "/api/connector/v1/challenge", "storage_constraint", 503,
        installation_id="inst_probe",
        detail="Production Connector repository write denied (storage_constraint): "
               "Storage isolation or integrity constraint denied the operation "
               "(sf_documents_scope_key).",
    )
    rows = [r for r in connector_protocol.recent_audit(20)
            if r.get("code") == "storage_constraint"]
    assert rows, "the refusal was not recorded"
    assert "sf_documents_scope_key" in rows[-1]["detail"]


def test_storage_errors_keep_their_message(connector_store, monkeypatch) -> None:
    """_write_doc used to reduce a storage failure to its bare code."""
    from app import storage_router
    from app.production_storage import StorageConstraintError

    monkeypatch.setattr(connector_protocol.runtime_env, "is_server_environment", lambda: True)
    monkeypatch.setattr(connector_protocol.runtime_env, "environment_explicit", lambda: True)

    def boom(*_a, **_k):
        raise StorageConstraintError(
            "Storage isolation or integrity constraint denied the operation "
            "(some_named_constraint).")

    monkeypatch.setattr(storage_router, "write_document", boom)

    with pytest.raises(connector_protocol.ConnectorProtocolError) as exc:
        connector_protocol._write_doc({
            "version": 1, "installations": [], "enrollments": [],
            "sessions": [], "commands": [],
        })
    assert exc.value.code == "storage_constraint"
    # The constraint name is the whole point: without it the code is unactionable.
    assert "some_named_constraint" in str(exc.value)


def test_an_unreadable_snapshot_timestamp_does_not_refuse_the_heartbeat() -> None:
    """A real Connector was answered 400 on every beat over this one field.

    Json.NET parses an ISO string into a Date token, and casting it back to
    string yields the current culture's format. The AddOn sent
    "8/27/2026 2:49:31 AM", the server could not read it, and refused the whole
    heartbeat -- so a machine sending genuine accounts reported as offline with
    no NinjaTrader at all. The field is provenance; the heartbeat is evidence.
    """
    snapshot = connector_protocol._normalise_account_snapshot({
        "generated_at_utc": "8/27/2026 2:49:31 AM",
        "exporter_version": "1.3.0",
        "accounts": [{
            "account_name": "DEMO3369390", "account_mode": "paper",
            "cash_value": 11017.42, "net_liquidation": 11017.42,
            "connection_status": "Connected",
        }],
    }, 1_800_000_000.0)
    assert snapshot["accounts"][0]["account_name"] == "DEMO3369390"
    assert snapshot["accounts"][0]["net_liquidation"] == 11017.42
    # Dropped, not invented, and not silently.
    assert snapshot["generated_at_utc"] == ""
    assert "generated_at_utc" in snapshot["generated_at_warning"]
    # Freshness never depended on it: arrival inside a signed heartbeat does.
    assert snapshot["received_at"] == 1_800_000_000.0


def test_a_readable_snapshot_timestamp_is_kept_verbatim() -> None:
    snapshot = connector_protocol._normalise_account_snapshot({
        "generated_at_utc": "2026-08-27T02:49:31Z",
        "accounts": [{"account_name": "Sim101"}],
    }, 1_800_000_000.0)
    assert snapshot["generated_at_utc"] == "2026-08-27T02:49:31Z"
    assert snapshot["generated_at_warning"] == ""


def test_a_snapshot_with_no_accounts_is_still_not_functional() -> None:
    """Tolerating a bad timestamp must not tolerate an empty payload."""
    snapshot = connector_protocol._normalise_account_snapshot({
        "generated_at_utc": "not a date at all", "accounts": [],
    }, 1_800_000_000.0)
    assert snapshot["accounts"] == []


def test_the_connector_reads_the_snapshot_without_reinterpreting_dates() -> None:
    """The fix at source: the AddOn must not let Json.NET rewrite the stamp."""
    root = Path(__file__).resolve().parent.parent
    client = (root / "bridge" / "src" / "Connector" / "ConnectorClient.cs").read_text(
        encoding="utf-8",
    )
    reader = client[client.index("private JObject ReadAccountSnapshot"):]
    reader = reader[: reader.index("catch (Exception ex)")]
    assert "DateParseHandling.None" in reader
    assert "JObject.Parse(" not in reader
