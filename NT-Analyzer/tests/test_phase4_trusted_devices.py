"""Phase 4: trusted-device registry and step-up security challenges.

These tests exercise the device lifecycle, challenge binding/replay/attempt
limits, ownership boundaries, session revocation semantics, metadata masking and
the self-service HTTP contract. PostgreSQL acceptance is covered separately and
gated by real DSNs; here the store is the DPAPI account document in dev-test.
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, security_devices
from app import server as server_mod

OWNER_UUID = "00000000-0000-4000-8000-000000000999"
ALICE_UUID = "00000000-0000-4000-8000-000000000042"
BOB_UUID = "00000000-0000-4000-8000-000000000007"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")  # -> deployment_environment == development
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_DUAL_AUTH_REQUIRED", "1")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    security_devices._CHALLENGE_RATE.clear()
    account_auth._write_doc({
        "version": 3,
        "users": [
            {
                "user_id": 999, "user_uuid": OWNER_UUID, "username": "owner",
                "first_name": "Owner", "role": "owner", "status": "active",
                "is_owner": True, "telegram_user_id": 999,
            },
            {
                "user_id": 42, "user_uuid": ALICE_UUID, "username": "alice",
                "first_name": "Alice", "role": "full_control", "status": "active",
                "is_owner": False, "telegram_user_id": 42, "email": "alice@example.com",
                "ux_mode": "professional",
            },
            {
                "user_id": 7, "user_uuid": BOB_UUID, "username": "bob",
                "first_name": "Bob", "role": "read_only", "status": "active",
                "is_owner": False, "telegram_user_id": 7, "ux_mode": "professional",
            },
        ],
        "auth_identities": [],
        "challenges": [],
        "sessions": [],
        "trusted_devices": [],
        "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    account_auth.set_auth_required(True)
    return tmp_path


def _login(uid: int, *, user_agent: str = "Mozilla/5.0 (Windows NT 10.0) Chrome/120",
           device_credential: str = "browser-credential-a") -> str:
    out = account_auth.create_session_for_user(
        uid, ip="203.0.113.5", user_agent=user_agent, require_google=False,
        skip_dual_auth_gate=True, device_credential=device_credential,
    )
    return out["session_token"]


def _device_for(uid: int, *, status: str = "") -> dict:
    doc = account_auth._read_doc()
    user = account_auth._user(doc, uid)
    uuid_val = account_auth._user_uuid(user)
    rows = [
        row for row in doc.get("trusted_devices") or []
        if row.get("user_uuid") == uuid_val and (not status or row.get("status") == status)
    ]
    return rows[-1] if rows else {}


# --------------------------------------------------------------------------- #
# Device lifecycle.
# --------------------------------------------------------------------------- #
def test_new_session_registers_pending_device(store):
    token = _login(42)
    device = _device_for(42)
    assert device["status"] == "pending"
    assert device["device_type"] == "desktop"
    assert device["confirmation_provider"] == ""
    # Session is bound to the device but still authenticates (no lockout).
    ctx = account_auth.authenticate_session(token)
    assert ctx is not None
    doc = account_auth._read_doc()
    session = next(s for s in doc["sessions"] if s["token_hash"] == hashlib.sha256(token.encode()).hexdigest())
    assert session["trusted_device_id"] == device["device_id"]


def test_browser_credential_identifies_the_device_not_the_user_agent(store):
    # One browser profile is one device: repeated logins, and a User-Agent that
    # changes under it (a browser update), must not split it in two.
    _login(42)
    _login(42)
    _login(42, user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/121")
    # A different account on the same browser is still a separate device.
    _login(7)
    doc = account_auth._read_doc()
    alice = [d for d in doc["trusted_devices"] if d["user_uuid"] == ALICE_UUID]
    bob = [d for d in doc["trusted_devices"] if d["user_uuid"] == BOB_UUID]
    assert len(alice) == 1
    assert len(bob) == 1
    assert alice[0]["device_id"] != bob[0]["device_id"]


def test_a_second_browser_is_a_second_device_even_with_one_user_agent(store):
    # The old fingerprint mixed in the server hostname and account name, so two
    # different browsers presenting the same User-Agent collapsed onto one
    # record. They must stay separate.
    _login(42, device_credential="browser-credential-a")
    _login(42, device_credential="browser-credential-b")
    doc = account_auth._read_doc()
    alice = [d for d in doc["trusted_devices"] if d["user_uuid"] == ALICE_UUID]
    assert len(alice) == 2
    assert alice[0]["fingerprint"] != alice[1]["fingerprint"]


def test_device_identity_never_depends_on_server_environment(store, monkeypatch):
    _login(42)
    monkeypatch.setenv("USERNAME", "another-service-account")
    monkeypatch.setenv("NTA_DEVICE_LABEL", "SOME-OTHER-HOST")
    _login(42)
    doc = account_auth._read_doc()
    alice = [d for d in doc["trusted_devices"] if d["user_uuid"] == ALICE_UUID]
    assert len(alice) == 1


def test_pending_to_trusted_via_approve(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    assert started["provider"] == "telegram"
    assert "test_code" in started
    out = security_devices.approve_device(
        user_id=42, device_id=device["device_id"],
        challenge_id=started["challenge_id"], code=started["test_code"],
    )
    assert out["device"]["status"] == "trusted"
    assert out["device"]["confirmation_provider"] == "telegram"


def test_confirm_challenge_generic_trusts_device(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    out = security_devices.confirm_challenge(
        user_id=42, challenge_id=started["challenge_id"], code=started["test_code"],
    )
    assert out["purpose"] == "device_confirm"
    assert out["device"]["status"] == "trusted"


def test_pending_to_rejected_blocks_session(store):
    token = _login(42)
    device = _device_for(42)
    out = security_devices.reject_device(user_id=42, device_id=device["device_id"])
    assert out["device"]["status"] == "revoked"
    assert out["revoked_sessions"] == 1
    # The pending session no longer authenticates.
    assert account_auth.authenticate_session(token) is None
    failure = account_auth.session_auth_failure(token)
    assert failure["code"] == "session_device_revoked"


def test_trusted_to_revoked(store):
    token = _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    security_devices.approve_device(
        user_id=42, device_id=device["device_id"],
        challenge_id=started["challenge_id"], code=started["test_code"],
    )
    out = security_devices.revoke_device(user_id=42, device_id=device["device_id"])
    assert out["device"]["status"] == "revoked"
    assert out["revoked_sessions"] == 1
    assert account_auth.authenticate_session(token) is None


def test_expired_trusted_device_marked_expired(store):
    _login(42)
    device = _device_for(42)
    doc = account_auth._read_doc()
    row = next(d for d in doc["trusted_devices"] if d["device_id"] == device["device_id"])
    row["status"] = "trusted"
    row["expires_at"] = 1.0  # far in the past
    account_auth._write_doc(doc)
    listed = security_devices.list_devices(42)["devices"]
    assert listed[0]["status"] == "expired"


def test_invalid_transitions_rejected(store):
    _login(42)
    device = _device_for(42)
    # Reject only applies to pending; a trusted device cannot be "rejected".
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    security_devices.approve_device(
        user_id=42, device_id=device["device_id"],
        challenge_id=started["challenge_id"], code=started["test_code"],
    )
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.reject_device(user_id=42, device_id=device["device_id"])
    assert exc.value.code == "device_not_pending"


def test_revoke_is_idempotent(store):
    _login(42)
    device = _device_for(42)
    security_devices.revoke_device(user_id=42, device_id=device["device_id"])
    out = security_devices.revoke_device(user_id=42, device_id=device["device_id"])
    assert out["revoked_sessions"] == 0
    assert out["device"]["status"] == "revoked"


# --------------------------------------------------------------------------- #
# Challenge invariants.
# --------------------------------------------------------------------------- #
def test_challenge_wrong_code_then_success(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.approve_device(
            user_id=42, device_id=device["device_id"],
            challenge_id=started["challenge_id"], code="000000",
        )
    assert exc.value.code in {"challenge_bad_code", "challenge_attempts_exhausted"}
    # A correct code still works while attempts remain.
    if started["test_code"] != "000000":
        out = security_devices.approve_device(
            user_id=42, device_id=device["device_id"],
            challenge_id=started["challenge_id"], code=started["test_code"],
        )
        assert out["device"]["status"] == "trusted"


def test_challenge_attempts_exhausted(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    bad = "111111" if started["test_code"] != "111111" else "222222"
    last_code = ""
    for _ in range(security_devices.CHALLENGE_MAX_ATTEMPTS):
        with pytest.raises(security_devices.SecurityDeviceError) as exc:
            security_devices.approve_device(
                user_id=42, device_id=device["device_id"],
                challenge_id=started["challenge_id"], code=bad,
            )
        last_code = exc.value.code
    assert last_code == "challenge_attempts_exhausted"
    # Even the correct code no longer works after exhaustion.
    with pytest.raises(security_devices.SecurityDeviceError):
        security_devices.approve_device(
            user_id=42, device_id=device["device_id"],
            challenge_id=started["challenge_id"], code=started["test_code"],
        )


def test_challenge_expired(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    doc = account_auth._read_doc()
    row = next(c for c in doc["security_challenges"] if c["challenge_id"] == started["challenge_id"])
    row["expires_at"] = 1.0
    account_auth._write_doc(doc)
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.approve_device(
            user_id=42, device_id=device["device_id"],
            challenge_id=started["challenge_id"], code=started["test_code"],
        )
    assert exc.value.code == "challenge_expired"


def test_challenge_replay_blocked(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    security_devices.approve_device(
        user_id=42, device_id=device["device_id"],
        challenge_id=started["challenge_id"], code=started["test_code"],
    )
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.confirm_challenge(
            user_id=42, challenge_id=started["challenge_id"], code=started["test_code"],
        )
    assert exc.value.code == "challenge_not_pending"


def test_challenge_wrong_user(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.confirm_challenge(
            user_id=7, challenge_id=started["challenge_id"], code=started["test_code"],
        )
    assert exc.value.code == "challenge_wrong_user"


def test_challenge_wrong_device(store):
    # Alice logs in from two different clients -> two devices.
    _login(42, user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/120",
           device_credential="browser-credential-a")
    _login(42, user_agent="Mozilla/5.0 (X11; Linux) Firefox/119",
           device_credential="browser-credential-b")
    doc = account_auth._read_doc()
    devices = [d for d in doc["trusted_devices"] if d["user_uuid"] == ALICE_UUID]
    assert len(devices) == 2
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=devices[0]["device_id"],
    )
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.approve_device(
            user_id=42, device_id=devices[1]["device_id"],
            challenge_id=started["challenge_id"], code=started["test_code"],
        )
    assert exc.value.code == "challenge_wrong_device"


def test_challenge_wrong_purpose(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(user_id=42, purpose="step_up")
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.approve_device(
            user_id=42, device_id=device["device_id"],
            challenge_id=started["challenge_id"], code=started["test_code"],
        )
    assert exc.value.code == "challenge_wrong_purpose"


def test_challenge_wrong_environment(store, monkeypatch):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    assert started["environment"] == "development"
    monkeypatch.setattr(security_devices, "_current_environment", lambda: "canary")
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.approve_device(
            user_id=42, device_id=device["device_id"],
            challenge_id=started["challenge_id"], code=started["test_code"],
        )
    assert exc.value.code == "challenge_wrong_environment"


def test_challenge_concurrent_consumption_single_winner(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        try:
            security_devices.confirm_challenge(
                user_id=42, challenge_id=started["challenge_id"], code=started["test_code"],
            )
            results.append("ok")
        except security_devices.SecurityDeviceError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1
    assert "challenge_not_pending" in results


# --------------------------------------------------------------------------- #
# Authorization / ownership.
# --------------------------------------------------------------------------- #
def test_other_user_cannot_touch_device(store):
    _login(42)
    device = _device_for(42)
    for call in (
        lambda: security_devices.reject_device(user_id=7, device_id=device["device_id"]),
        lambda: security_devices.revoke_device(user_id=7, device_id=device["device_id"]),
        lambda: security_devices.create_challenge(
            user_id=7, purpose="device_confirm", device_id=device["device_id"]),
    ):
        with pytest.raises(security_devices.SecurityDeviceError) as exc:
            call()
        assert exc.value.status in {403, 404, 409}
        assert exc.value.code in {"device_not_found", "device_revoked"}


def test_unauthenticated_rejected(store):
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.list_devices(0)
    assert exc.value.code == "auth_required"


def test_list_devices_scoped_to_owner(store):
    _login(42)
    _login(7)
    alice = security_devices.list_devices(42)["devices"]
    bob = security_devices.list_devices(7)["devices"]
    assert len(alice) == 1
    assert len(bob) == 1
    assert alice[0]["device_id"] != bob[0]["device_id"]


# --------------------------------------------------------------------------- #
# Sessions.
# --------------------------------------------------------------------------- #
def test_revoke_device_only_affects_that_device(store):
    token_a = _login(42, user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/120",
                     device_credential="browser-credential-a")
    token_b = _login(42, user_agent="Mozilla/5.0 (X11; Linux) Firefox/119",
                     device_credential="browser-credential-b")
    token_bob = _login(7)
    doc = account_auth._read_doc()
    devices = [d for d in doc["trusted_devices"] if d["user_uuid"] == ALICE_UUID]
    device_a = next(d for d in devices if "Windows" in (d.get("os_family") or ""))
    security_devices.revoke_device(user_id=42, device_id=device_a["device_id"])
    assert account_auth.authenticate_session(token_a) is None
    assert account_auth.authenticate_session(token_b) is not None
    assert account_auth.authenticate_session(token_bob) is not None


def test_legacy_session_without_device_still_authenticates(store):
    # Simulate a pre-Phase-4 session row (no trusted_device_id).
    token = "l" * 64
    csrf = "c" * 48
    doc = account_auth._read_doc()
    doc["sessions"].append({
        "session_id": "sess_legacy1",
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
        "csrf_token": csrf,
        "user_id": 42, "user_uuid": ALICE_UUID,
        "created_at_utc": "2026-07-15T00:00:00Z", "expires_at": 4_000_000_000,
        "revoked": False, "device_id": "legacy", "client": "Chrome",
        "machine": "PC", "ip": "127.0.0.1", "source": "desktop_session",
    })
    account_auth._write_doc(doc)
    assert account_auth.authenticate_session(token) is not None


# --------------------------------------------------------------------------- #
# Metadata masking.
# --------------------------------------------------------------------------- #
def test_public_device_hides_fingerprint_and_raw_ip(store):
    _login(42)
    device = security_devices.list_devices(42)["devices"][0]
    assert "fingerprint" not in device
    assert "audit_metadata" not in device
    assert device["last_region"] in {"203.0.•.•", ""}
    # The stored record keeps the correlation fingerprint but never a raw IP.
    stored = _device_for(42)
    assert stored["fingerprint"]
    assert "203.0.113.5" not in json.dumps(stored)


def test_challenge_store_and_audit_have_no_plaintext_code(store):
    _login(42)
    device = _device_for(42)
    started = security_devices.create_challenge(
        user_id=42, purpose="device_confirm", device_id=device["device_id"],
    )
    code = started["test_code"]
    doc = account_auth._read_doc()
    row = next(c for c in doc["security_challenges"] if c["challenge_id"] == started["challenge_id"])
    # The plaintext one-time code is never persisted: only a salted hash.
    assert "code" not in row
    assert row["code_hash"] and row["code_hash"] != code
    assert code not in [str(v) for v in row.values()]
    # The challenge-created audit event carries no code field or value.
    audit_lines = [
        json.loads(line)
        for line in account_auth._audit_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    created = [e for e in audit_lines if e.get("event") == "security.challenge_created"]
    assert created
    for entry in created:
        assert "code" not in entry
        assert code not in [str(v) for v in entry.values()]


# --------------------------------------------------------------------------- #
# Connector device type.
# --------------------------------------------------------------------------- #
def test_connector_device_classification(store):
    doc = account_auth._read_doc()
    user = account_auth._user(doc, 42)
    session = {"session_id": "sess_conn", "user_uuid": ALICE_UUID}
    security_devices.observe_session(
        doc, session, user, ip="203.0.113.9", user_agent="",
        source="connector", connector_installation_id="conn-install-1",
    )
    account_auth._write_doc(doc)
    device = _device_for(42)
    assert device["device_type"] == "connector"
    assert device["connector_installation_id"] == "conn-install-1"
    assert session["trusted_device_id"] == device["device_id"]


# --------------------------------------------------------------------------- #
# HTTP contract.
# --------------------------------------------------------------------------- #
def _request(base, path, *, token="", csrf="", method="GET", body=None, origin=""):
    data = None
    headers = {"Origin": origin or base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _serve():
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    return server, base


def test_http_security_page_scoped_and_authz(store):
    token = _login(42)
    ctx = account_auth.authenticate_session(token)
    csrf = ctx["csrf_token"]
    server, base = _serve()
    try:
        page = _request(base, "/api/account/security", token=token)
        assert page["ok"] is True
        assert len(page["devices"]) == 1
        device_id = page["devices"][0]["device_id"]

        # Unauthenticated read is server-denied for a remote request (on the
        # localhost desktop build a no-cookie request resolves to the owner).
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/account/security", origin="https://app.stratforge.example")
        assert exc.value.code == 401

        # A mutation without CSRF is rejected server-side.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/account/devices/revoke", token=token,
                     method="POST", body={"device_id": device_id})
        assert exc.value.code == 403

        # Owner of the device can revoke with a valid CSRF token.
        out = _request(base, "/api/account/devices/revoke", token=token, csrf=csrf,
                       method="POST", body={"device_id": device_id})
        assert out["device"]["status"] == "revoked"
    finally:
        server.shutdown()
        server.server_close()


def test_http_cross_user_device_not_found(store):
    alice_token = _login(42)
    bob_token = _login(7)
    bob_ctx = account_auth.authenticate_session(bob_token)
    alice_device = _device_for(42)
    server, base = _serve()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/account/devices/revoke", token=bob_token,
                     csrf=bob_ctx["csrf_token"], method="POST",
                     body={"device_id": alice_device["device_id"]})
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------- #
# Migration static contract (no live DB required).
# --------------------------------------------------------------------------- #
def test_migration_0006_is_additive_and_scoped():
    from app.production_storage.core import MigrationRunner

    migrations = {row["version"]: row for row in MigrationRunner.migrations()}
    assert 6 in migrations
    sql = str(migrations[6]["sql"]).lower()
    assert "drop table" not in sql
    assert "create table if not exists sf_trusted_devices" in sql
    assert "create table if not exists sf_security_challenges" in sql
    assert "enable row level security" in sql
    assert "references sf_users(user_uuid)" in sql
    # No plaintext one-time code column: only a salted hash is stored.
    assert "code_hash" in sql
    assert "code_salt" in sql


# --------------------------------------------------------------------------- #
# Relational mirror (runs without PostgreSQL: the SQL is captured, not executed)
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, log):
        self._log = log

    def fetchone(self):
        return None


class _FakeConn:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(str(sql).split()), params))
        return _FakeCursor(self.statements)


def _device_row(**overrides):
    row = {
        "device_id": "11111111-1111-4111-8111-111111111111",
        "user_uuid": "22222222-2222-4222-8222-222222222222",
        "legacy_user_id": 42,
        "fingerprint": "fp-alpha",
        "device_type": "browser",
        "display_name": "Chrome",
        "status": "trusted",
        "confirmation_provider": "telegram",
        "audit_metadata": {"last_ip": "203.0.•.•"},
    }
    row.update(overrides)
    return row


def test_devices_are_mirrored_into_their_relational_table():
    from app.production_storage.core import DocumentRepository

    conn = _FakeConn()
    doc = {"trusted_devices": [_device_row()]}
    DocumentRepository._sync_trusted_devices(
        DocumentRepository, conn, doc, {42: "22222222-2222-4222-8222-222222222222"},
    )
    inserts = [s for s, _ in conn.statements if "INSERT INTO sf_trusted_devices" in s]
    assert len(inserts) == 1
    prune = [s for s, _ in conn.statements if "DELETE FROM sf_trusted_devices" in s]
    assert prune, "rows removed from the document must be pruned from the table"


def test_duplicate_active_device_fingerprint_is_rejected_before_write():
    from app.production_storage import StorageConstraintError
    from app.production_storage.core import DocumentRepository

    conn = _FakeConn()
    doc = {"trusted_devices": [
        _device_row(),
        _device_row(device_id="33333333-3333-4333-8333-333333333333"),
    ]}
    with pytest.raises(StorageConstraintError):
        DocumentRepository._sync_trusted_devices(
            DocumentRepository, conn, doc, {42: "22222222-2222-4222-8222-222222222222"},
        )


def test_revoked_duplicate_fingerprint_is_allowed_to_coexist():
    from app.production_storage.core import DocumentRepository

    conn = _FakeConn()
    doc = {"trusted_devices": [
        _device_row(status="revoked", device_id="44444444-4444-4444-8444-444444444444"),
        _device_row(),
    ]}
    DocumentRepository._sync_trusted_devices(
        DocumentRepository, conn, doc, {42: "22222222-2222-4222-8222-222222222222"},
    )
    inserts = [s for s, _ in conn.statements if "INSERT INTO sf_trusted_devices" in s]
    assert len(inserts) == 2
