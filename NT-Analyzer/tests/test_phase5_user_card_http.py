"""The card over HTTP, and the Chrome + Edge case specifically.

Two browsers on one workstation are indistinguishable from the server side.
Presenting them under a shared machine would be a guess dressed as a fact, so
the contract tested here is: they stay listed apart until a Connector on that
machine attests the binding, and the pairing flow is the only way across.
"""
from __future__ import annotations

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

CHROME_UA = "Mozilla/5.0 (Windows NT 10.0) Chrome/120"
EDGE_UA = "Mozilla/5.0 (Windows NT 10.0) Chrome/120 Edg/120"


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
                "is_owner": False, "telegram_user_id": 42,
                "email": "alice@example.com", "ux_mode": "professional",
            },
        ],
        "auth_identities": [], "identity_history": [], "challenges": [],
        "sessions": [], "trusted_devices": [], "physical_devices": [],
        "device_pairings": [], "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    account_auth.set_auth_required(True)
    return tmp_path


@pytest.fixture()
def http(store):
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://{server.server_address[0]}:{server.server_address[1]}"
    finally:
        server.shutdown()


def _login(uid, *, user_agent, credential):
    out = account_auth.create_session_for_user(
        uid, ip="203.0.113.5", user_agent=user_agent, require_google=False,
        skip_dual_auth_gate=True, device_credential=credential,
        device_confirmation_required=False,
    )
    return out["session_token"]


def _get(base, path, token="", origin=""):
    headers = {"Origin": origin or base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    request = urllib.request.Request(base + path, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _post(base, path, body, token, csrf):
    headers = {"Origin": base, "Content-Type": "application/json",
               "Cookie": f"{account_auth.SESSION_COOKIE}={token}",
               "X-CSRF-Token": csrf}
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode("utf-8"),
        method="POST", headers=headers,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# Chrome + Edge: the case that must not be guessed.
# --------------------------------------------------------------------------- #
def test_chrome_and_edge_are_two_unpaired_clients(http):
    """Same account, same workstation, same IP. Without a Connector there is no
    evidence they share a machine, so the card must not claim one."""
    chrome = _login(42, user_agent=CHROME_UA, credential="chrome-profile")
    _login(42, user_agent=EDGE_UA, credential="edge-profile")

    card = _get(http, "/api/account/card", chrome)
    devices = card["devices"]
    assert devices["machines"] == [], "no Connector means no proven machine"
    assert len(devices["unbound_clients"]) == 2
    assert {c["bound_via"] for c in devices["unbound_clients"]} == {""}
    assert devices["unbound_explanation"]


def test_the_card_offers_a_pairing_path_rather_than_a_guess(http):
    chrome = _login(42, user_agent=CHROME_UA, credential="chrome-profile")
    card = _get(http, "/api/account/card", chrome)
    # Every unbound client can be paired; none is silently attached.
    for client in card["devices"]["unbound_clients"]:
        assert client["actions"]["end_session"] is True
        assert client["actions"]["revoke_client"] is True
        assert client["physical_device_id"] == ""


def test_a_connector_attested_pairing_puts_them_under_one_machine(http):
    """The proven case. Once the Connector on DIMONCHECK vouches for each
    browser, the card shows the machine with both clients under it."""
    chrome = _login(42, user_agent=CHROME_UA, credential="chrome-profile")
    _login(42, user_agent=EDGE_UA, credential="edge-profile")
    # The Connector enrolls with its hardware-bound installation id. It has no
    # cookie jar, so it registers through observe_session rather than a browser
    # login.
    doc = account_auth._read_doc()
    alice = account_auth._user(doc, 42)
    connector_session = {"session_id": "s-conn", "user_uuid": ALICE_UUID}
    security_devices.observe_session(
        doc, connector_session, alice, ip="203.0.113.5", user_agent="",
        source="connector", connector_installation_id="dimoncheck-install",
    )
    doc.setdefault("sessions", []).append({
        "session_id": "s-conn", "user_id": 42, "token_hash": "hash_s_conn",
        "revoked": False, "expires_at": 4102444800.0,
        "created_at_utc": "2026-08-17T00:00:00Z", "environment": "development",
        "trusted_device_id": connector_session["trusted_device_id"],
    })
    account_auth._write_doc(doc)
    doc = account_auth._read_doc()
    connector = [c for c in doc["trusted_devices"] if c["device_type"] == "connector"][-1]
    security_devices._trust_device(connector, provider="telegram")
    security_devices._trust_machine_for(doc, ALICE_UUID, connector, provider="telegram")
    account_auth._write_doc(doc)

    browsers = [c for c in account_auth._read_doc()["trusted_devices"]
                if c["device_type"] != "connector"]
    for browser in browsers:
        issued = security_devices.issue_pairing_code(
            user_id=42, device_id=connector["device_id"],
        )
        security_devices.redeem_pairing_code(
            user_id=42, device_id=browser["device_id"], code=issued["code"],
        )

    card = _get(http, "/api/account/card", chrome)
    devices = card["devices"]
    assert len(devices["machines"]) == 1
    machine = devices["machines"][0]
    # Connector first, then the two browsers it vouched for.
    assert [c["kind"] for c in machine["clients"]] == [
        "connector", "browser_app", "browser_app",
    ]
    assert devices["unbound_clients"] == []
    assert {c["bound_via"] for c in machine["clients"]} == {
        "connector_self", "attested_pairing",
    }
    assert sum(len(c["sessions"]) for c in machine["clients"]) >= 3


# --------------------------------------------------------------------------- #
# HTTP contract.
# --------------------------------------------------------------------------- #
def test_the_cabinet_card_needs_a_session(http):
    """A remote origin, deliberately: on the localhost desktop build a request
    with no cookie resolves to the owner, so a same-origin probe would prove
    nothing about authentication."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(http, "/api/account/card", origin="https://app.stratforge.example")
    assert exc.value.code == 401


def test_an_ordinary_account_cannot_read_the_admin_card(http):
    token = _login(42, user_agent=CHROME_UA, credential="chrome-profile")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(http, "/api/auth/users/999/card", token)
    assert exc.value.code in (401, 403)


def test_the_owner_reads_the_same_card_at_admin_scope(http):
    _login(42, user_agent=CHROME_UA, credential="chrome-profile")
    owner = _login(999, user_agent=CHROME_UA, credential="owner-profile")
    admin = _get(http, "/api/auth/users/42/card", owner)
    assert admin["scope"] == "admin"
    assert admin["summary"]["user_uuid"] == ALICE_UUID
    assert "legacy_user_id" in admin["summary"]
    assert "admin" in admin


def test_ending_one_session_leaves_the_others_alone(http):
    token = _login(42, user_agent=CHROME_UA, credential="chrome-profile")
    _login(42, user_agent=EDGE_UA, credential="edge-profile")
    context = account_auth.authenticate_session(token)
    csrf = context["csrf_token"]

    card = _get(http, "/api/account/card", token)
    clients = card["devices"]["unbound_clients"]
    assert len(clients) == 2

    # Deliberately not the caller's own session: revoking that would invalidate
    # the cookie the next request uses, and the card read afterwards would
    # describe a different identity rather than a shorter session list.
    import hashlib
    own_hash = hashlib.sha256(token.encode()).hexdigest()
    own = account_auth._session_id(next(
        row for row in account_auth._read_doc()["sessions"]
        if row.get("token_hash") == own_hash
    ))
    victim = next(
        s["session_id"] for c in clients for s in c["sessions"]
        if s["session_id"] != own
    )
    out = _post(http, "/api/account/sessions/revoke",
                {"session_id": victim}, token, csrf)
    assert out["revoked"] == 1

    remaining = _get(http, "/api/account/card", token)
    total = sum(len(c["sessions"])
                for c in remaining["devices"]["unbound_clients"])
    assert total == 1, "only the named session should end"


def test_a_session_id_from_another_account_cannot_be_ended(http):
    token = _login(42, user_agent=CHROME_UA, credential="chrome-profile")
    owner_token = _login(999, user_agent=CHROME_UA, credential="owner-profile")
    context = account_auth.authenticate_session(token)
    csrf = context["csrf_token"]

    owner_card = _get(http, "/api/account/card", owner_token)
    owner_session = next(
        s["session_id"] for c in owner_card["devices"]["unbound_clients"]
        for s in c["sessions"]
    )
    # Alice names the owner's session. The subject comes from her own
    # authentication, so nothing is revoked.
    out = _post(http, "/api/account/sessions/revoke",
                {"session_id": owner_session}, token, csrf)
    assert out["revoked"] == 0
    still = _get(http, "/api/account/card", owner_token)
    assert sum(len(c["sessions"]) for c in still["devices"]["unbound_clients"]) == 1
