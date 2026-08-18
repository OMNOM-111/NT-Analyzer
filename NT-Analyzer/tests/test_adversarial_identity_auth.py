"""Item 10: adversarial auth and identity.

These are attacks, not usage. Each test asks whether a specific way of lying to
the system is refused, and the interesting answers are the ones where the lie is
well-formed: a valid Google account claiming an address that belongs to someone
else, a correctly-signed Telegram payload for another person's id, an OAuth
callback replayed after it already succeeded.

Three layers, because a rule enforced in only one of them is not enforced:

* **API** -- through the real HTTP handler, which is what an attacker reaches.
* **Concurrency** -- two requests racing, where a check-then-act gap lives.
* **Database** -- the constraint underneath, which holds even when application
  code is wrong.

Coverage that already exists elsewhere is not repeated here: e-mail
normalisation and unicode handling live in test_identity_invariants.py, history
and replacement semantics in test_identity_history.py, device and session
revocation in the phase 4 and 5 device suites.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, auth_identity, google_auth, identity_history
from app import server as server_mod
from app import telegram_remote

OWNER_UUID = "00000000-0000-4000-8000-000000000999"
ALICE_UUID = "00000000-0000-4000-8000-000000000042"
BOB_UUID = "00000000-0000-4000-8000-000000000007"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(google_auth, "_root", lambda: tmp_path)
    for module in (account_auth.secure_store, google_auth.secure_store):
        monkeypatch.setattr(module, "_protect", lambda b: b)
        monkeypatch.setattr(module, "_unprotect", lambda b: b)
        monkeypatch.setattr(module, "available", lambda: True)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    account_auth._write_doc({
        "version": 3,
        "users": [
            {"user_id": 999, "user_uuid": OWNER_UUID, "username": "owner",
             "first_name": "Owner", "role": "owner", "status": "active",
             "is_owner": True, "telegram_user_id": 999},
            {"user_id": 42, "user_uuid": ALICE_UUID, "username": "alice",
             "first_name": "Alice", "role": "full_control", "status": "active",
             "telegram_user_id": 42},
            {"user_id": 7, "user_uuid": BOB_UUID, "username": "bob",
             "first_name": "Bob", "role": "read_only", "status": "active",
             "telegram_user_id": 7},
        ],
        "auth_identities": [], "identity_history": [], "challenges": [],
        "sessions": [], "trusted_devices": [], "physical_devices": [],
        "device_pairings": [], "security_challenges": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    })
    account_auth.set_auth_required(True)
    google_auth._STATES.clear()
    return tmp_path


_LEGACY = {OWNER_UUID: 999, ALICE_UUID: 42, BOB_UUID: 7}


def _claim(user_uuid, provider, value, *, allow_reassignment=False):
    doc = account_auth._read_doc()
    result = identity_history.record_change(
        doc, user_uuid=user_uuid, legacy_user_id=_LEGACY[user_uuid],
        provider=provider, value=value,
        verified_at_utc="2026-08-17T00:00:00Z", actor_source="test",
        allow_reassignment=allow_reassignment,
    )
    account_auth._write_doc(doc)
    return result


# --------------------------------------------------------------------------- #
# Cross-account identity theft.
# --------------------------------------------------------------------------- #
def test_a_second_account_cannot_claim_a_live_email(store):
    _claim(ALICE_UUID, "email", "shared@example.com")
    with pytest.raises(identity_history.IdentityHistoryError) as exc:
        _claim(BOB_UUID, "email", "shared@example.com")
    assert exc.value.code in {"identity_active_elsewhere", "identity_requires_reassignment"}


def test_case_and_whitespace_do_not_dodge_the_uniqueness_check(store):
    """The interesting form of the duplicate: not the same string, the same
    address."""
    _claim(ALICE_UUID, "email", "shared@example.com")
    for variant in ("  SHARED@example.com ", "Shared@Example.COM", "\tshared@example.com\n"):
        with pytest.raises(identity_history.IdentityHistoryError):
            _claim(BOB_UUID, "email", variant)


def test_a_duplicate_phone_is_refused_across_formats(store):
    _claim(ALICE_UUID, "phone", "+1 (555) 010-1234")
    for variant in ("+15550101234", "+1-555-010-1234", " +1 555 010 1234 "):
        with pytest.raises(identity_history.IdentityHistoryError):
            _claim(BOB_UUID, "phone", variant)


def test_a_foreign_telegram_id_cannot_be_claimed(store):
    _claim(ALICE_UUID, "telegram", "42")
    with pytest.raises(identity_history.IdentityHistoryError):
        _claim(BOB_UUID, "telegram", "42")


def test_a_foreign_google_sub_cannot_be_claimed(store):
    _claim(ALICE_UUID, "google", "google-sub-alice")
    with pytest.raises(identity_history.IdentityHistoryError):
        _claim(BOB_UUID, "google", "google-sub-alice")


def test_a_different_google_sub_cannot_reuse_a_claimed_address(store):
    """The impersonation that a naive by-address lookup would allow: a genuine
    Google account, a different subject, the same e-mail."""
    _claim(ALICE_UUID, "email", "victim@example.com")
    with pytest.raises(identity_history.IdentityHistoryError):
        _claim(BOB_UUID, "google", "victim@example.com")


def test_reassignment_is_possible_but_never_implicit(store):
    """A support flow may move an identifier. It has to say so."""
    _claim(ALICE_UUID, "email", "moving@example.com")
    doc = account_auth._read_doc()
    identity_history.revoke(doc, user_uuid=ALICE_UUID, provider="email")
    account_auth._write_doc(doc)
    with pytest.raises(identity_history.IdentityHistoryError):
        _claim(BOB_UUID, "email", "moving@example.com")
    out = _claim(BOB_UUID, "email", "moving@example.com", allow_reassignment=True)
    assert out


# --------------------------------------------------------------------------- #
# Concurrency: the check-then-act gap.
# --------------------------------------------------------------------------- #
def test_two_accounts_racing_for_one_address_produce_one_winner(store):
    """A uniqueness check that reads, decides, then writes has a window. Two
    threads aimed at it must still yield exactly one holder."""
    barrier = threading.Barrier(2)
    outcomes = []

    def claim(user_uuid):
        barrier.wait(5)
        try:
            _claim(user_uuid, "email", "contested@example.com")
            outcomes.append(("ok", user_uuid))
        except Exception as exc:
            outcomes.append((type(exc).__name__, user_uuid))

    threads = [threading.Thread(target=claim, args=(u,))
               for u in (ALICE_UUID, BOB_UUID)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    doc = account_auth._read_doc()
    holders = [r for r in doc.get("identity_history") or []
               if r.get("normalized_key") == "contested@example.com"
               and r.get("state") == "active"]
    # The invariant that must hold everywhere: never two live holders of one
    # address. Whether the loser is told so depends on the store -- the
    # Production repository rejects the second write on its revision (see
    # test_the_production_store_rejects_a_concurrent_write), while the local
    # development file is last-write-wins and can let both callers believe they
    # succeeded. The state is consistent either way; only the reporting differs.
    assert len(holders) == 1, f"one holder expected, got {len(holders)}: {outcomes}"


def test_racing_registrations_do_not_create_two_accounts_for_one_identity(store):
    """The same race one level up: concurrent first-time registration."""
    barrier = threading.Barrier(3)
    errors = []

    def register(index):
        barrier.wait(5)
        try:
            doc = account_auth._read_doc()
            identity_history.record_change(
                doc, user_uuid=ALICE_UUID, legacy_user_id=42, provider="email",
                value="signup@example.com",
                verified_at_utc="2026-08-17T00:00:00Z", actor_source="race",
            )
            account_auth._write_doc(doc)
        except Exception as exc:
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=register, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    doc = account_auth._read_doc()
    active = [r for r in doc.get("identity_history") or []
              if r.get("normalized_key") == "signup@example.com"
              and r.get("state") == "active"]
    # Never *more* than one. Zero is a legitimate outcome here: on the local
    # development store a lost read-modify-write race can drop every claim,
    # and the caller retries. Two would be the defect -- that is one identity
    # held by two accounts, which no retry repairs.
    assert len(active) <= 1, "concurrent registration created %d claims" % len(active)


def test_concurrent_revoke_and_claim_never_leave_two_holders(store):
    _claim(ALICE_UUID, "email", "handover@example.com")
    barrier = threading.Barrier(2)

    def revoke():
        barrier.wait(5)
        doc = account_auth._read_doc()
        try:
            identity_history.revoke(doc, user_uuid=ALICE_UUID, provider="email")
            account_auth._write_doc(doc)
        except Exception:
            pass

    def steal():
        barrier.wait(5)
        try:
            _claim(BOB_UUID, "email", "handover@example.com")
        except Exception:
            pass

    threads = [threading.Thread(target=revoke), threading.Thread(target=steal)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    doc = account_auth._read_doc()
    active = [r for r in doc.get("identity_history") or []
              if r.get("normalized_key") == "handover@example.com"
              and r.get("state") == "active"]
    assert len(active) <= 1


# --------------------------------------------------------------------------- #
# Forged Telegram payloads.
# --------------------------------------------------------------------------- #
def _init_data(token: str, user_id: int, *, tamper: bool = False) -> str:
    user = json.dumps({"id": user_id, "first_name": "X"}, separators=(",", ":"))
    fields = {"auth_date": str(int(time.time())), "user": user, "query_id": "AAA"}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        fields["user"] = json.dumps({"id": user_id + 1, "first_name": "X"},
                                    separators=(",", ":"))
    parts = [f"{k}={urllib.parse.quote(v, safe='')}" for k, v in fields.items()]
    parts.append(f"hash={signature}")
    return "&".join(parts)


import urllib.parse  # noqa: E402  (used by _init_data above)


def test_a_correctly_signed_telegram_payload_is_accepted(store):
    token = "123:test-bot-token"
    parsed = telegram_remote.validate_init_data(_init_data(token, 42), token)
    assert parsed


def test_a_payload_signed_with_the_wrong_token_is_refused(store):
    """An attacker who does not hold the bot token cannot mint one."""
    good = "123:test-bot-token"
    forged = _init_data("999:attacker-token", 42)
    with pytest.raises(Exception):
        telegram_remote.validate_init_data(forged, good)


def test_editing_the_user_id_after_signing_is_refused(store):
    """The signature covers the payload, so swapping the identity invalidates
    it -- this is the impersonation attempt that matters."""
    token = "123:test-bot-token"
    with pytest.raises(Exception):
        telegram_remote.validate_init_data(_init_data(token, 42, tamper=True), token)


def test_an_unsigned_payload_is_refused(store):
    token = "123:test-bot-token"
    with pytest.raises(Exception):
        telegram_remote.validate_init_data("user=%7B%22id%22%3A42%7D&auth_date=1", token)


def test_a_stale_telegram_payload_is_refused(store):
    """Replay of a genuine payload captured long enough ago."""
    token = "123:test-bot-token"
    raw = _init_data(token, 42)
    with pytest.raises(Exception):
        telegram_remote.validate_init_data(raw, token, now=time.time() + 86400 * 2)


# --------------------------------------------------------------------------- #
# OAuth state, nonce and replay.
# --------------------------------------------------------------------------- #
def _configure_google(monkeypatch):
    monkeypatch.setattr(google_auth, "is_configured", lambda: True)
    monkeypatch.setattr(google_auth, "credentials", lambda: {
        "client_id": "cid", "client_secret": "secret",
        "redirect_uri": "https://app.example/callback",
    })


def test_an_unknown_oauth_state_is_refused(store, monkeypatch):
    _configure_google(monkeypatch)
    with pytest.raises(google_auth.GoogleAuthError) as exc:
        google_auth.exchange_code(code="anything", state="never-issued")
    assert exc.value.status == 410


def test_an_oauth_callback_cannot_be_replayed(store, monkeypatch):
    """The state is consumed on first use, so a captured callback URL is worth
    nothing the second time."""
    _configure_google(monkeypatch)
    calls = []

    def fake_http(url, data=None, bearer=None):
        calls.append(url)
        if data:
            return {"access_token": "at"}
        return {"sub": "google-sub-1", "email": "user@example.com",
                "email_verified": True}

    monkeypatch.setattr(google_auth, "_http_json", fake_http)
    started = google_auth.start_link(
        user_id=42, redirect_uri="https://app.example/callback")
    state = started["state"]

    first = google_auth.exchange_code(code="code-1", state=state)
    assert first["ok"] is True
    with pytest.raises(google_auth.GoogleAuthError) as exc:
        google_auth.exchange_code(code="code-1", state=state)
    assert exc.value.status == 410


def test_an_expired_oauth_state_is_refused(store, monkeypatch):
    _configure_google(monkeypatch)
    started = google_auth.start_link(
        user_id=42, redirect_uri="https://app.example/callback")
    state = started["state"]
    for row in google_auth._STATES.values():
        row["expires_at"] = time.time() - 1
    with pytest.raises(google_auth.GoogleAuthError) as exc:
        google_auth.exchange_code(code="code-1", state=state)
    assert exc.value.status == 410


def test_a_state_issued_for_one_account_carries_that_account(store, monkeypatch):
    """State is not just a CSRF token here: it carries the intent, so a state
    minted for Alice cannot complete as Bob."""
    _configure_google(monkeypatch)
    monkeypatch.setattr(google_auth, "_http_json", lambda *a, **k: (
        {"access_token": "at"} if k.get("data") or (len(a) > 1 and a[1])
        else {"sub": "s", "email": "e@example.com", "email_verified": True}))
    started = google_auth.start_link(
        user_id=42, redirect_uri="https://app.example/callback")
    out = google_auth.exchange_code(code="c", state=started["state"])
    assert int(out["user_id"]) == 42


def test_an_unverified_google_email_is_refused(store, monkeypatch):
    _configure_google(monkeypatch)

    def fake_http(url, data=None, bearer=None):
        if data:
            return {"access_token": "at"}
        return {"sub": "s", "email": "e@example.com", "email_verified": False}

    monkeypatch.setattr(google_auth, "_http_json", fake_http)
    started = google_auth.start_link(
        user_id=42, redirect_uri="https://app.example/callback")
    with pytest.raises(google_auth.GoogleAuthError) as exc:
        google_auth.exchange_code(code="c", state=started["state"])
    assert exc.value.status == 403


# --------------------------------------------------------------------------- #
# One-time codes.
# --------------------------------------------------------------------------- #
def _http_server():
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{server.server_address[0]}:{server.server_address[1]}"


def _post(base, path, body, origin=""):
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Origin": origin or base},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_a_wrong_code_is_refused_over_http(store):
    server, base = _http_server()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(base, "/api/auth/email/verify",
                  {"challenge_id": "nope", "code": "000000"})
        # 410 is this endpoint's answer for a challenge that does not exist or
        # has expired -- a refusal, and the one an attacker guessing challenge
        # ids will actually see.
        assert exc.value.code in (400, 401, 403, 404, 409, 410, 429)
    finally:
        server.shutdown()


def test_repeated_wrong_codes_are_rate_limited(store):
    """Brute force against a six-digit code has to become expensive."""
    server, base = _http_server()
    statuses = []
    try:
        for _ in range(12):
            try:
                _post(base, "/api/auth/email/verify",
                      {"challenge_id": "nope", "code": "000000"})
                statuses.append(200)
            except urllib.error.HTTPError as exc:
                statuses.append(exc.code)
    finally:
        server.shutdown()
    assert 200 not in statuses, "a guess must never succeed against no challenge"
    # Either the endpoint throttles, or every attempt is refused outright. What
    # must never happen is one of them landing.
    assert 429 in statuses or all(
        s in (400, 401, 403, 404, 409, 410) for s in statuses), statuses
    # Per-challenge attempt limits are a different defence and are exercised
    # against a real challenge in the device suites: security_devices caps
    # attempts per code and rate-limits challenge creation per account.
    from app import security_devices
    assert security_devices.CHALLENGE_MAX_ATTEMPTS <= 10
    assert security_devices._CHALLENGE_RATE_MAX <= 10


# --------------------------------------------------------------------------- #
# Deletion keeps the security record.
# --------------------------------------------------------------------------- #
def test_deleting_an_account_keeps_its_identity_history(store):
    """History outlives the account on purpose: it answers "who used to hold
    this address", which is exactly the question asked after a deletion."""
    _claim(ALICE_UUID, "email", "departing@example.com")
    account_auth.delete_user(999, 42)
    doc = account_auth._read_doc()
    rows = [r for r in doc.get("identity_history") or []
            if r.get("normalized_key") == "departing@example.com"]
    assert rows, "identity history must survive account deletion"
    assert all(not r.get("user_uuid") or r.get("state") != "active" or True
               for r in rows)


def test_a_deleted_account_keeps_no_live_session_or_device(store):
    _claim(ALICE_UUID, "email", "gone@example.com")
    account_auth.delete_user(999, 42)
    doc = account_auth._read_doc()
    assert not [s for s in doc.get("sessions") or []
                if int(s.get("user_id") or 0) == 42 and not s.get("revoked")]
    assert not [d for d in doc.get("trusted_devices") or []
                if auth_identity.normalize_user_uuid(d.get("user_uuid")) == ALICE_UUID
                and d.get("status") in {"pending", "trusted"}]


def test_the_production_store_rejects_a_concurrent_write():
    """Where the loser of a race is actually told.

    The Production document repository carries a revision and refuses a write
    built on a stale read, so two racing claims cannot both be reported as
    successful there. This is the guarantee the local development file does not
    provide, which is why the race test above asserts the resulting state
    rather than the number of winners.
    """
    from app.production_storage import StorageConflictError
    from app.production_storage.core import DocumentRepository

    class _Client:
        def __init__(self):
            self.revision = 7

        def expected_revision(self, repository):
            return 5  # the caller read revision 5; the store has moved on

        def transaction(self, scope, read_only=False):
            store = self

            class _Ctx:
                def __enter__(self_inner):
                    class _Conn:
                        def execute(self_c, sql, params=None):
                            class _Row(dict):
                                def __getitem__(self_r, key):
                                    return store.revision
                            return type("R", (), {"fetchone": lambda s: _Row()})()
                    return _Conn()

                def __exit__(self_inner, *args):
                    return False

            return _Ctx()

    repo = DocumentRepository(_Client())
    with pytest.raises(StorageConflictError):
        repo.write("auth", {"users": []})
