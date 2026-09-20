"""Phase 5: physical machine -> client -> session.

The point of the level is that a machine is *never* inferred. Most of what
follows is therefore negative: a browser must not acquire a machine by looking
like one, two browsers on one workstation must not be merged by their
User-Agent or IP, and trust must not leak between levels in either direction.

The store here is the DPAPI account document in dev-test mode, same as the
Phase 4 suite. Relational enforcement is covered by the PostgreSQL acceptance
tests, which are gated on a real DSN.
"""
from __future__ import annotations

import pytest

from app import account_auth, physical_devices, security_devices

OWNER_UUID = "00000000-0000-4000-8000-000000000999"
ALICE_UUID = "00000000-0000-4000-8000-000000000042"
BOB_UUID = "00000000-0000-4000-8000-000000000007"

WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0) Chrome/120"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
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
        "physical_devices": [],
        "device_pairings": [],
        "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    account_auth.set_auth_required(True)
    return tmp_path


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #
def _observe(uid, *, credential="", installation="", user_agent=WINDOWS_UA,
             ip="203.0.113.5", source="", session_id="sess"):
    """Run one session observation and persist, as a real login would."""
    doc = account_auth._read_doc()
    user = account_auth._user(doc, uid)
    session = {"session_id": session_id, "user_uuid": account_auth._user_uuid(user)}
    security_devices.observe_session(
        doc, session, user, ip=ip, user_agent=user_agent, source=source,
        connector_installation_id=installation, device_credential=credential,
    )
    doc.setdefault("sessions", []).append({
        "session_id": session_id,
        "user_id": uid,
        "token_hash": "hash_" + session_id,
        "revoked": False,
        "expires_at": 4102444800.0,
        "trusted_device_id": session["trusted_device_id"],
    })
    account_auth._write_doc(doc)
    return session


def _clients(uid):
    doc = account_auth._read_doc()
    uuid_val = account_auth._user_uuid(account_auth._user(doc, uid))
    return [r for r in doc.get("trusted_devices") or [] if r.get("user_uuid") == uuid_val]


def _machines(uid):
    doc = account_auth._read_doc()
    uuid_val = account_auth._user_uuid(account_auth._user(doc, uid))
    return [r for r in doc.get("physical_devices") or [] if r.get("user_uuid") == uuid_val]


def _trust_connector(uid, *, installation="conn-install-1"):
    """Bring a Connector and its machine to trusted, the way confirmation does."""
    doc = account_auth._read_doc()
    uuid_val = account_auth._user_uuid(account_auth._user(doc, uid))
    client = [r for r in doc["trusted_devices"]
              if r.get("connector_installation_id") == installation][-1]
    security_devices._trust_device(client, provider="telegram")
    security_devices._trust_machine_for(doc, uuid_val, client, provider="telegram")
    account_auth._write_doc(doc)
    return client


# --------------------------------------------------------------------------- #
# A machine is only ever the Connector's hardware-bound credential.
# --------------------------------------------------------------------------- #
def test_connector_registers_a_machine_and_binds_itself(store):
    _observe(42, installation="conn-install-1", source="connector", user_agent="")
    machines = _machines(42)
    assert len(machines) == 1
    assert machines[0]["status"] == "pending"

    client = _clients(42)[-1]
    assert client["device_type"] == "connector"
    assert client["physical_device_id"] == machines[0]["physical_device_id"]
    assert client["bound_via"] == "connector_self"


def test_browser_never_acquires_a_machine_on_its_own(store):
    _observe(42, credential="browser-a")
    assert _machines(42) == []
    client = _clients(42)[-1]
    assert client["physical_device_id"] == ""
    assert client["bound_via"] == ""


def test_two_browsers_on_one_workstation_are_not_merged(store):
    """Same User-Agent, same IP, same account -- and still two clients with no
    machine between them. Merging them is precisely the inference this model
    removes: those three signals are identical for every user of a deployment."""
    _observe(42, credential="browser-a", session_id="s1")
    _observe(42, credential="browser-b", session_id="s2")
    clients = _clients(42)
    assert len({c["device_id"] for c in clients}) == 2
    assert all(c["physical_device_id"] == "" for c in clients)
    assert _machines(42) == []


def test_machine_display_name_is_not_the_server_hostname(monkeypatch, store):
    """COMPUTERNAME describes the server, which is the same machine for every
    user of a deployment and not the one being registered."""
    monkeypatch.setenv("COMPUTERNAME", "STRATFORGE-PROD-01")
    _observe(42, installation="conn-install-1", source="connector",
             user_agent=WINDOWS_UA)
    assert "STRATFORGE-PROD-01" not in _machines(42)[0]["display_name"]


def test_same_credential_is_one_machine_across_logins(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _observe(42, installation="conn-install-1", source="connector", session_id="s2")
    assert len(_machines(42)) == 1


def test_machine_key_is_scoped_per_account(store):
    """The same physical workstation used by two accounts is two machine records:
    one account must not learn anything about another's device inventory."""
    _observe(42, installation="shared-install", source="connector", session_id="s1")
    _observe(7, installation="shared-install", source="connector", session_id="s2")
    alice = _machines(42)
    bob = _machines(7)
    assert len(alice) == 1 and len(bob) == 1
    assert alice[0]["machine_key_hash"] != bob[0]["machine_key_hash"]


def test_revoked_machine_is_not_resurrected_by_reconnecting(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    doc = account_auth._read_doc()
    machine = doc["physical_devices"][-1]
    physical_devices.revoke_machine(doc, machine, reason="machine_revoked")
    account_auth._write_doc(doc)

    _observe(42, installation="conn-install-1", source="connector", session_id="s2")
    machines = _machines(42)
    assert len(machines) == 2
    assert machines[0]["status"] == "revoked"
    assert machines[1]["status"] == "pending"


# --------------------------------------------------------------------------- #
# Trust does not leak between levels.
# --------------------------------------------------------------------------- #
def test_confirming_the_connector_confirms_its_machine(store):
    _observe(42, installation="conn-install-1", source="connector")
    _trust_connector(42)
    assert _machines(42)[0]["status"] == "trusted"


def test_confirming_a_browser_confirms_no_machine(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")

    doc = account_auth._read_doc()
    uuid_val = account_auth._user_uuid(account_auth._user(doc, 42))
    browser = [c for c in doc["trusted_devices"] if c["device_type"] != "connector"][-1]
    events = security_devices._trust_machine_for(
        doc, uuid_val, browser, provider="telegram",
    )
    assert events == []


def test_trusted_machine_does_not_trust_a_new_client_on_it(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")
    browser = [c for c in _clients(42) if c["device_type"] != "connector"][-1]
    assert browser["status"] == "pending"


# --------------------------------------------------------------------------- #
# Pairing: the only path from a browser to a machine.
# --------------------------------------------------------------------------- #
def _issue_code(uid):
    connector = [c for c in _clients(uid) if c["device_type"] == "connector"][-1]
    return security_devices.issue_pairing_code(
        user_id=uid, device_id=connector["device_id"],
    )


def test_pairing_binds_a_browser_without_trusting_it(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")
    browser = [c for c in _clients(42) if c["device_type"] != "connector"][-1]

    issued = _issue_code(42)
    out = security_devices.redeem_pairing_code(
        user_id=42, device_id=browser["device_id"], code=issued["code"],
    )
    assert out["physical_device_id"] == issued["physical_device_id"]

    bound = [c for c in _clients(42) if c["device_id"] == browser["device_id"]][0]
    assert bound["bound_via"] == "attested_pairing"
    # Membership only: the browser is still an unconfirmed client.
    assert bound["status"] == "pending"


def test_untrusted_connector_cannot_issue_a_pairing_code(store):
    _observe(42, installation="conn-install-1", source="connector")
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        _issue_code(42)
    assert exc.value.code == "device_not_trusted"


def test_a_browser_cannot_issue_a_pairing_code(store):
    _observe(42, credential="browser-a")
    browser = _clients(42)[-1]
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.issue_pairing_code(user_id=42, device_id=browser["device_id"])
    assert exc.value.code == "pairing_requires_connector"


def test_pairing_code_is_single_use(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")
    _observe(42, credential="browser-b", session_id="s3")
    browsers = [c for c in _clients(42) if c["device_type"] != "connector"]

    issued = _issue_code(42)
    security_devices.redeem_pairing_code(
        user_id=42, device_id=browsers[0]["device_id"], code=issued["code"],
    )
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.redeem_pairing_code(
            user_id=42, device_id=browsers[1]["device_id"], code=issued["code"],
        )
    assert exc.value.code == "pairing_code_invalid"


def test_pairing_code_expires(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")
    browser = [c for c in _clients(42) if c["device_type"] != "connector"][-1]
    issued = _issue_code(42)

    doc = account_auth._read_doc()
    for row in doc["device_pairings"]:
        row["expires_at"] = 0.0
    account_auth._write_doc(doc)

    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.redeem_pairing_code(
            user_id=42, device_id=browser["device_id"], code=issued["code"],
        )
    assert exc.value.code == "pairing_code_invalid"


def test_pairing_code_from_one_account_does_not_work_in_another(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    issued = _issue_code(42)

    _observe(7, credential="bob-browser", session_id="s2")
    bob_browser = _clients(7)[-1]
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.redeem_pairing_code(
            user_id=7, device_id=bob_browser["device_id"], code=issued["code"],
        )
    assert exc.value.code == "pairing_code_invalid"


def test_pairing_attempts_are_limited(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")
    browser = [c for c in _clients(42) if c["device_type"] != "connector"][-1]
    issued = _issue_code(42)
    wrong = "".join("9" if ch != "9" else "1" for ch in issued["code"])

    for _ in range(physical_devices.PAIRING_MAX_ATTEMPTS):
        with pytest.raises(security_devices.SecurityDeviceError):
            security_devices.redeem_pairing_code(
                user_id=42, device_id=browser["device_id"], code=wrong,
            )
    # The correct code is now dead too -- the attempt budget is per code.
    with pytest.raises(security_devices.SecurityDeviceError):
        security_devices.redeem_pairing_code(
            user_id=42, device_id=browser["device_id"], code=issued["code"],
        )


def test_already_bound_client_cannot_be_rebound(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    connector = [c for c in _clients(42) if c["device_type"] == "connector"][-1]
    issued = _issue_code(42)
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.redeem_pairing_code(
            user_id=42, device_id=connector["device_id"], code=issued["code"],
        )
    assert exc.value.code == "device_already_bound"


# --------------------------------------------------------------------------- #
# Revocation: cascades down, never sideways or up.
# --------------------------------------------------------------------------- #
def test_revoking_a_machine_revokes_its_clients_and_sessions(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")
    browser = [c for c in _clients(42) if c["device_type"] != "connector"][-1]
    issued = _issue_code(42)
    security_devices.redeem_pairing_code(
        user_id=42, device_id=browser["device_id"], code=issued["code"],
    )

    machine_id = _machines(42)[0]["physical_device_id"]
    out = security_devices.revoke_physical_device(
        user_id=42, physical_device_id=machine_id,
    )
    assert out["revoked_clients"] == 2
    assert out["revoked_sessions"] == 2
    assert all(c["status"] == "revoked" for c in _clients(42))
    doc = account_auth._read_doc()
    assert all(s["revoked"] for s in doc["sessions"])


def test_revoking_a_client_leaves_the_machine_and_its_siblings_alone(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")
    browser = [c for c in _clients(42) if c["device_type"] != "connector"][-1]
    issued = _issue_code(42)
    security_devices.redeem_pairing_code(
        user_id=42, device_id=browser["device_id"], code=issued["code"],
    )

    security_devices.revoke_device(user_id=42, device_id=browser["device_id"])
    connector = [c for c in _clients(42) if c["device_type"] == "connector"][-1]
    assert connector["status"] == "trusted"
    assert _machines(42)[0]["status"] == "trusted"


def test_revoking_a_machine_kills_its_outstanding_pairing_code(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _trust_connector(42)
    _observe(42, credential="browser-a", session_id="s2")
    browser = [c for c in _clients(42) if c["device_type"] != "connector"][-1]
    issued = _issue_code(42)

    security_devices.revoke_physical_device(
        user_id=42, physical_device_id=issued["physical_device_id"],
    )
    with pytest.raises(security_devices.SecurityDeviceError):
        security_devices.redeem_pairing_code(
            user_id=42, device_id=browser["device_id"], code=issued["code"],
        )


def test_revoking_a_machine_is_idempotent(store):
    _observe(42, installation="conn-install-1", source="connector")
    machine_id = _machines(42)[0]["physical_device_id"]
    security_devices.revoke_physical_device(user_id=42, physical_device_id=machine_id)
    again = security_devices.revoke_physical_device(
        user_id=42, physical_device_id=machine_id,
    )
    assert again["revoked_clients"] == 0 and again["revoked_sessions"] == 0


# --------------------------------------------------------------------------- #
# Ownership boundaries.
# --------------------------------------------------------------------------- #
def test_machine_of_another_account_is_not_reachable(store):
    _observe(42, installation="conn-install-1", source="connector")
    machine_id = _machines(42)[0]["physical_device_id"]
    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.revoke_physical_device(
            user_id=7, physical_device_id=machine_id,
        )
    assert exc.value.code == "machine_not_found"
    assert _machines(42)[0]["status"] == "pending"


def test_user_can_rename_only_their_own_machine(store):
    _observe(42, installation="conn-install-1", source="connector")
    machine_id = _machines(42)[0]["physical_device_id"]

    renamed = security_devices.rename_physical_device(
        user_id=42,
        physical_device_id=machine_id,
        display_name="Рабочий компьютер",
    )
    assert renamed["machine"]["display_name"] == "Рабочий компьютер"
    assert _machines(42)[0]["display_name"] == "Рабочий компьютер"

    with pytest.raises(security_devices.SecurityDeviceError) as exc:
        security_devices.rename_physical_device(
            user_id=7,
            physical_device_id=machine_id,
            display_name="Чужое имя",
        )
    assert exc.value.code == "machine_not_found"


def test_listing_shows_only_your_own_machines(store):
    _observe(42, installation="alice-install", source="connector", session_id="s1")
    _observe(7, installation="bob-install", source="connector", session_id="s2")
    alice = security_devices.list_physical_devices(42)["physical_devices"]
    bob = security_devices.list_physical_devices(7)["physical_devices"]
    assert len(alice) == 1 and len(bob) == 1
    assert alice[0]["physical_device_id"] != bob[0]["physical_device_id"]


# --------------------------------------------------------------------------- #
# Disclosure.
# --------------------------------------------------------------------------- #
def test_public_machine_never_exposes_the_machine_key(store):
    _observe(42, installation="conn-install-1", source="connector")
    public = security_devices.list_physical_devices(42)["physical_devices"][0]
    assert "machine_key_hash" not in public
    stored = _machines(42)[0]["machine_key_hash"]
    assert stored not in repr(public)


def test_account_security_reports_the_two_levels_separately(store):
    _observe(42, installation="conn-install-1", source="connector", session_id="s1")
    _observe(42, credential="browser-a", session_id="s2")
    out = security_devices.account_security(42)
    assert len(out["devices"]) == 2
    assert len(out["physical_devices"]) == 1
    assert out["policy"]["pairing_ttl_sec"] == physical_devices.PAIRING_TTL_SEC


# --------------------------------------------------------------------------- #
# Relational mirror (runs without PostgreSQL: the SQL is captured, not executed)
# --------------------------------------------------------------------------- #
MACHINE_UUID = "55555555-5555-4555-8555-555555555555"
ACCOUNT_UUID = "22222222-2222-4222-8222-222222222222"


class _FakeCursor:
    def __init__(self, answer):
        self._answer = answer

    def fetchone(self):
        return self._answer


class _FakeConn:
    """Reports every to_regclass probe as "table exists", so the mirror takes
    its post-0015 path."""

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.statements.append((text, params))
        if "to_regclass" in text:
            return _FakeCursor((True,))
        return _FakeCursor(None)


def _machine_row(**overrides):
    row = {
        "physical_device_id": MACHINE_UUID,
        "user_uuid": ACCOUNT_UUID,
        "legacy_user_id": 42,
        "machine_key_hash": "a" * 64,
        "display_name": "Рабочая станция · Windows",
        "status": "trusted",
        "confirmation_provider": "telegram",
        "confirmed_at_utc": "2026-01-01T00:00:00Z",
        "audit_metadata": {"last_ip": "203.0.•.•"},
    }
    row.update(overrides)
    return row


def _client_row(**overrides):
    row = {
        "device_id": "11111111-1111-4111-8111-111111111111",
        "user_uuid": ACCOUNT_UUID,
        "legacy_user_id": 42,
        "fingerprint": "fp-alpha",
        "device_type": "connector",
        "display_name": "NinjaTrader Connector",
        "status": "trusted",
        "confirmation_provider": "telegram",
        "physical_device_id": MACHINE_UUID,
        "bound_via": "connector_self",
        "audit_metadata": {},
    }
    row.update(overrides)
    return row


def _mirror(doc):
    from app.production_storage.core import DocumentRepository

    conn = _FakeConn()
    DocumentRepository._sync_physical_devices(
        DocumentRepository, conn, doc, {42: ACCOUNT_UUID},
    )
    DocumentRepository._sync_trusted_devices(
        DocumentRepository, conn, doc, {42: ACCOUNT_UUID},
    )
    return conn


def test_machines_are_mirrored_before_the_clients_that_reference_them():
    conn = _mirror({
        "physical_devices": [_machine_row()],
        "trusted_devices": [_client_row()],
    })
    order = [s for s, _ in conn.statements if s.startswith("INSERT INTO sf_")]
    assert order[0].startswith("INSERT INTO sf_physical_devices")
    assert order[1].startswith("INSERT INTO sf_trusted_devices")
    # And the machine prune runs only after clients stopped referencing it.
    kinds = [s for s, _ in conn.statements if s.startswith("DELETE FROM sf_")]
    assert kinds.index("DELETE FROM sf_trusted_devices WHERE NOT (device_id = ANY(%s))"
                       ) < kinds.index(
        "DELETE FROM sf_physical_devices WHERE NOT (physical_device_id = ANY(%s))")


def test_client_binding_is_carried_into_the_relational_row():
    conn = _mirror({
        "physical_devices": [_machine_row()],
        "trusted_devices": [_client_row()],
    })
    sql, params = next(
        (s, p) for s, p in conn.statements if s.startswith("INSERT INTO sf_trusted_devices")
    )
    assert "physical_device_id,bound_via" in sql
    assert params[-2:] == (MACHINE_UUID, "connector_self")


def test_duplicate_active_machine_credential_is_rejected_before_write():
    from app.production_storage import StorageConstraintError

    with pytest.raises(StorageConstraintError):
        _mirror({
            "physical_devices": [
                _machine_row(),
                _machine_row(physical_device_id="66666666-6666-4666-8666-666666666666"),
            ],
            "trusted_devices": [],
        })


def test_revoked_machine_may_share_a_credential_with_a_live_one():
    conn = _mirror({
        "physical_devices": [
            _machine_row(
                physical_device_id="66666666-6666-4666-8666-666666666666",
                status="revoked", revoked_at_utc="2026-01-02T00:00:00Z",
            ),
            _machine_row(),
        ],
        "trusted_devices": [],
    })
    inserts = [s for s, _ in conn.statements if s.startswith("INSERT INTO sf_physical_devices")]
    assert len(inserts) == 2


def test_binding_without_an_origin_is_rejected_before_write():
    from app.production_storage import StorageConstraintError

    with pytest.raises(StorageConstraintError):
        _mirror({
            "physical_devices": [_machine_row()],
            "trusted_devices": [_client_row(bound_via="")],
        })


def test_machine_status_and_timestamps_must_agree_before_write():
    from app.production_storage import StorageConstraintError

    with pytest.raises(StorageConstraintError):
        _mirror({
            "physical_devices": [_machine_row(status="revoked")],
            "trusted_devices": [],
        })


def test_machine_of_a_foreign_account_is_rejected_before_write():
    from app.production_storage import StorageConstraintError

    with pytest.raises(StorageConstraintError):
        _mirror({
            "physical_devices": [
                _machine_row(user_uuid="99999999-9999-4999-8999-999999999999"),
            ],
            "trusted_devices": [],
        })


def test_machine_key_matches_the_sql_backfill_formula(store):
    """Migration 0015 recomputes this in SQL to backfill Connectors that already
    existed. If the two ever diverge a known Connector silently registers as a
    second machine, so the formula is pinned here."""
    import hashlib
    expected = hashlib.sha256(
        f"machine-key/v1|{ALICE_UUID}|conn-install-1".encode("utf-8")
    ).hexdigest()
    assert physical_devices.machine_key_hash(ALICE_UUID, "conn-install-1") == expected
