"""Phase 5: one user card, two levels of detail.

The Cabinet and the Admin user page describe the same person. If they were two
assemblies of the same facts they would drift -- a device revoked in one view
still live in the other, an identity retirement in one timeline and not the
other -- and nothing would say which was wrong.

So the central tests here are equality tests: for every fact both views show,
the two must agree exactly, and Admin must be a strict superset rather than a
parallel model.

The rest covers the shape the card has to have over the canonical models:
machine -> client -> session, never flattened, and never a browser silently
attached to a machine it was not proven to run on.
"""
from __future__ import annotations

import pytest

from app import account_auth, identity_history, physical_devices, security_devices
from app import user_card


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
                "is_owner": False, "telegram_user_id": 42,
                "email": "alice@example.com", "ux_mode": "professional",
                "created_at_utc": "2026-01-01T00:00:00Z",
                "last_login_at_utc": "2026-08-17T00:00:00Z",
            },
            {
                "user_id": 7, "user_uuid": BOB_UUID, "username": "bob",
                "first_name": "Bob", "role": "read_only", "status": "active",
                "is_owner": False, "telegram_user_id": 7, "ux_mode": "professional",
            },
        ],
        "auth_identities": [],
        "identity_history": [],
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
# Fixtures that build a realistic account.
# --------------------------------------------------------------------------- #
def _observe(uid, *, credential="", installation="", session_id="sess",
             user_agent=WINDOWS_UA, environment="development"):
    doc = account_auth._read_doc()
    user = account_auth._user(doc, uid)
    session = {"session_id": session_id, "user_uuid": account_auth._user_uuid(user)}
    security_devices.observe_session(
        doc, session, user, ip="203.0.113.5", user_agent=user_agent,
        source="connector" if installation else "",
        connector_installation_id=installation, device_credential=credential,
    )
    doc.setdefault("sessions", []).append({
        "session_id": session_id,
        "user_id": uid,
        "token_hash": "hash_" + session_id,
        "revoked": False,
        "expires_at": 4102444800.0,
        "created_at_utc": "2026-08-17T00:00:00Z",
        "environment": environment,
        "ip": "203.0.113.5",
        "trusted_device_id": session["trusted_device_id"],
    })
    account_auth._write_doc(doc)
    return session


def _trust_connector(uid, installation="conn-1"):
    doc = account_auth._read_doc()
    uuid_val = account_auth._user_uuid(account_auth._user(doc, uid))
    client = [r for r in doc["trusted_devices"]
              if r.get("connector_installation_id") == installation][-1]
    security_devices._trust_device(client, provider="telegram")
    security_devices._trust_machine_for(doc, uuid_val, client, provider="telegram")
    account_auth._write_doc(doc)


def _add_identity(uid, provider, value, *, state="active", valid_from="2026-01-01T00:00:00Z",
                  valid_to="", reason=""):
    doc = account_auth._read_doc()
    uuid_val = account_auth._user_uuid(account_auth._user(doc, uid))
    normalized = identity_history.normalize_key(provider, value)
    doc.setdefault("identity_history", []).append({
        "history_id": f"hist-{provider}-{len(doc['identity_history'])}",
        "user_uuid": uuid_val,
        "provider": provider,
        "normalized_key": normalized,
        "display_value": identity_history.display_value(provider, normalized),
        "key_hash": identity_history.key_hash(normalized),
        "state": state,
        "verified_at": valid_from if state in ("active", "retired") else "",
        "valid_from": valid_from,
        "valid_to": valid_to,
        "replacement_reason": reason,
        "actor_source": "self_service",
    })
    account_auth._write_doc(doc)


def _full_account(uid=42):
    """A Connector with its machine, a paired browser, and an unbound browser."""
    _observe(uid, installation="conn-1", session_id="s-conn")
    _trust_connector(uid)
    _observe(uid, credential="browser-paired", session_id="s-paired")
    _observe(uid, credential="browser-loose", session_id="s-loose")

    clients = [c for c in account_auth._read_doc()["trusted_devices"]
               if c["device_type"] != "connector"]
    connector = [c for c in account_auth._read_doc()["trusted_devices"]
                 if c["device_type"] == "connector"][-1]
    issued = security_devices.issue_pairing_code(
        user_id=uid, device_id=connector["device_id"],
    )
    security_devices.redeem_pairing_code(
        user_id=uid, device_id=clients[0]["device_id"], code=issued["code"],
    )
    _add_identity(uid, "telegram", "42")
    _add_identity(uid, "email", "old@example.com", state="retired",
                  valid_from="2026-01-01T00:00:00Z", valid_to="2026-05-01T00:00:00Z",
                  reason="user_replaced")
    _add_identity(uid, "email", "alice@example.com", valid_from="2026-05-01T00:00:00Z")


# --------------------------------------------------------------------------- #
# The central claim: one model, two levels of detail.
# --------------------------------------------------------------------------- #
def test_cabinet_and_admin_describe_the_same_account(store):
    _full_account(42)
    own = user_card.build(actor_id=42, scope="self")
    admin = user_card.build(actor_id=999, target_id=42, scope="admin")

    assert own["summary"]["user_uuid"] == admin["summary"]["user_uuid"]
    assert own["summary"]["role"] == admin["summary"]["role"]
    assert own["summary"]["status"] == admin["summary"]["status"]
    assert own["summary"]["security"] == admin["summary"]["security"]
    assert own["environments"] == admin["environments"]
    assert own["policy"] == admin["policy"]


def test_admin_is_a_superset_never_a_different_answer(store):
    """Every key the Cabinet shows must exist in the Admin view with the same
    value. A field that differs would mean two sources of truth."""
    _full_account(42)
    own = user_card.build(actor_id=42, scope="self")
    admin = user_card.build(actor_id=999, target_id=42, scope="admin")

    for key, value in own["summary"].items():
        assert key in admin["summary"], f"admin view is missing {key}"
        assert admin["summary"][key] == value, f"{key} disagrees between the views"

    assert set(admin["summary"]) > set(own["summary"]), "admin adds nothing"


def test_the_device_trees_are_identical_in_shape(store):
    _full_account(42)
    own = user_card.build(actor_id=42, scope="self")["devices"]
    admin = user_card.build(actor_id=999, target_id=42, scope="admin")["devices"]

    def shape(tree):
        return [
            (m["physical_device_id"], m["status"],
             [(c["device_id"], c["status"], len(c["sessions"])) for c in m["clients"]])
            for m in tree["machines"]
        ], [(c["device_id"], c["status"]) for c in tree["unbound_clients"]]

    assert shape(own) == shape(admin)


def test_identities_agree_between_the_views(store):
    _full_account(42)
    own = user_card.build(actor_id=42, scope="self")["identities"]
    admin = user_card.build(actor_id=999, target_id=42, scope="admin")["identities"]
    assert [r["display_value"] for r in own["current"]] == \
           [r["display_value"] for r in admin["current"]]
    assert [r["display_value"] for r in own["history"]] == \
           [r["display_value"] for r in admin["history"]]
    assert own["replacement_timeline"] == admin["replacement_timeline"]


def test_admin_only_detail_stays_out_of_the_cabinet(store):
    """Operational detail an ordinary user has no reason to read."""
    _full_account(42)
    own = user_card.build(actor_id=42, scope="self")
    admin = user_card.build(actor_id=999, target_id=42, scope="admin")

    assert "legacy_user_id" not in own["summary"]
    assert "legacy_user_id" in admin["summary"]

    own_machine = own["devices"]["machines"][0]
    admin_machine = admin["devices"]["machines"][0]
    assert "last_region" not in own_machine
    assert "last_region" in admin_machine


# --------------------------------------------------------------------------- #
# Authorization.
# --------------------------------------------------------------------------- #
def test_self_scope_cannot_name_a_subject(store):
    """The Cabinet route takes no id at all, and the builder ignores one if
    passed -- otherwise the id would be the authorization boundary."""
    _full_account(42)
    card = user_card.build(actor_id=42, target_id=7, scope="self")
    assert card["summary"]["user_uuid"] == ALICE_UUID


def test_an_ordinary_account_cannot_read_another_card(store):
    _full_account(42)
    with pytest.raises(account_auth.AccountAuthError):
        user_card.build(actor_id=7, target_id=42, scope="admin")


def test_an_anonymous_caller_is_refused(store):
    with pytest.raises(user_card.UserCardError) as exc:
        user_card.build(actor_id=0, scope="self")
    assert exc.value.code == "auth_required"


def test_an_unknown_scope_is_refused(store):
    with pytest.raises(user_card.UserCardError) as exc:
        user_card.build(actor_id=42, scope="everything")
    assert exc.value.code == "scope_invalid"


# --------------------------------------------------------------------------- #
# The device tree is three levels and stays that way.
# --------------------------------------------------------------------------- #
def test_machine_holds_its_connector_and_its_paired_browser(store):
    _full_account(42)
    devices = user_card.build(actor_id=42, scope="self")["devices"]
    assert len(devices["machines"]) == 1
    machine = devices["machines"][0]
    kinds = [c["kind"] for c in machine["clients"]]
    assert kinds == ["connector", "browser_app"], "connector should lead its machine"
    assert {c["bound_via"] for c in machine["clients"]} == {
        "connector_self", "attested_pairing",
    }


def test_an_unpaired_browser_is_never_attached_to_a_machine(store):
    """The whole point. Chrome and Edge on one workstation look identical from
    the server; attaching them to a machine without a proven Connector pairing
    would be a guess presented as a fact."""
    _full_account(42)
    devices = user_card.build(actor_id=42, scope="self")["devices"]
    assert len(devices["unbound_clients"]) == 1
    loose = devices["unbound_clients"][0]
    assert loose["bound_via"] == ""
    assert loose["kind"] == "browser_app"
    machine_client_ids = {
        c["device_id"] for m in devices["machines"] for c in m["clients"]
    }
    assert loose["device_id"] not in machine_client_ids
    assert devices["unbound_explanation"]


def test_two_browsers_do_not_become_a_machine(store):
    """Same account, same User-Agent, same IP, no Connector: two clients and
    zero machines."""
    _observe(42, credential="chrome", session_id="s1")
    _observe(42, credential="edge", session_id="s2")
    devices = user_card.build(actor_id=42, scope="self")["devices"]
    assert devices["machines"] == []
    assert len(devices["unbound_clients"]) == 2


def test_sessions_hang_off_their_client(store):
    _full_account(42)
    devices = user_card.build(actor_id=42, scope="self")["devices"]
    everything = [c for m in devices["machines"] for c in m["clients"]] \
        + devices["unbound_clients"]
    assert sum(len(c["sessions"]) for c in everything) == 3
    for client in everything:
        for session in client["sessions"]:
            assert session["session_id"]
            assert session["environment"] == "development"


def test_revoked_sessions_are_not_listed_as_live(store):
    _full_account(42)
    doc = account_auth._read_doc()
    doc["sessions"][0]["revoked"] = True
    account_auth._write_doc(doc)
    devices = user_card.build(actor_id=42, scope="self")["devices"]
    everything = [c for m in devices["machines"] for c in m["clients"]] \
        + devices["unbound_clients"]
    assert sum(len(c["sessions"]) for c in everything) == 2


# --------------------------------------------------------------------------- #
# The two terminations are separate and say so.
# --------------------------------------------------------------------------- #
def test_client_and_machine_actions_are_advertised_separately(store):
    """Ending one browser session and revoking a whole laptop differ by an
    order of magnitude in blast radius, so the card never puts them behind one
    control."""
    _full_account(42)
    devices = user_card.build(actor_id=42, scope="self")["devices"]
    machine = devices["machines"][0]
    assert machine["actions"] == {"revoke_physical_device": True}
    for client in machine["clients"]:
        assert client["actions"] == {"end_session": True, "revoke_client": True}
    assert "revoke_physical_device" not in machine["clients"][0]["actions"]


def test_a_revoked_machine_offers_no_further_revoke(store):
    _full_account(42)
    machine_id = user_card.build(actor_id=42, scope="self")[
        "devices"]["machines"][0]["physical_device_id"]
    security_devices.revoke_physical_device(user_id=42, physical_device_id=machine_id)
    devices = user_card.build(actor_id=42, scope="self")["devices"]
    machine = devices["machines"][0]
    assert machine["status"] == "revoked"
    assert machine["actions"]["revoke_physical_device"] is False
    assert all(c["actions"]["revoke_client"] is False for c in machine["clients"])


def test_revoking_a_machine_clears_its_sessions_from_the_card(store):
    _full_account(42)
    card = user_card.build(actor_id=42, scope="self")
    machine_id = card["devices"]["machines"][0]["physical_device_id"]
    security_devices.revoke_physical_device(user_id=42, physical_device_id=machine_id)
    devices = user_card.build(actor_id=42, scope="self")["devices"]
    machine = devices["machines"][0]
    assert sum(len(c["sessions"]) for c in machine["clients"]) == 0
    # The unbound browser is untouched: revoking a machine is not revoking an
    # account.
    assert len(devices["unbound_clients"][0]["sessions"]) == 1


# --------------------------------------------------------------------------- #
# Identities: current, retired, and what replaced what.
# --------------------------------------------------------------------------- #
def test_current_and_retired_identities_are_separated(store):
    _full_account(42)
    identities = user_card.build(actor_id=42, scope="self")["identities"]
    assert {r["provider"] for r in identities["current"]} == {"telegram", "email"}
    assert [r["display_value"] for r in identities["history"]] == ['ol••@example.com']
    assert identities["history"][0]["state"] == "retired"
    assert identities["history"][0]["ended_reason"] == "replaced"


def test_a_revoked_identity_reads_differently_from_a_replaced_one(store):
    """Retired-because-superseded and revoked-because-compromised are not the
    same event, and collapsing them loses the distinction that matters when
    reading a compromise."""
    _add_identity(42, "email", "burned@example.com", state="revoked",
                  valid_from="2026-02-01T00:00:00Z", valid_to="2026-03-01T00:00:00Z")
    identities = user_card.build(actor_id=42, scope="self")["identities"]
    revoked = [r for r in identities["history"] if r["state"] == "revoked"]
    assert revoked and revoked[0]["ended_reason"] == "revoked"


def test_replacement_timeline_shows_what_replaced_what(store):
    _full_account(42)
    timeline = user_card.build(actor_id=42, scope="self")[
        "identities"]["replacement_timeline"]
    email = next(chain for chain in timeline if chain["provider"] == "email")
    assert len(email["steps"]) == 1
    step = email["steps"][0]
    assert step["from"] == 'ol••@example.com'
    assert step["to"] == 'al•••@example.com'
    assert step["at_utc"] == "2026-05-01T00:00:00Z"


def test_the_raw_identifier_is_never_rendered(store):
    _full_account(42)
    import json
    card = json.dumps(user_card.build(actor_id=42, scope="self"), ensure_ascii=False)
    assert "alice@example.com" not in card
    assert "old@example.com" not in card


def test_a_provider_with_one_identity_has_no_replacement_chain(store):
    _add_identity(42, "telegram", "42")
    timeline = user_card.build(actor_id=42, scope="self")[
        "identities"]["replacement_timeline"]
    assert timeline == []


# --------------------------------------------------------------------------- #
# Security posture.
# --------------------------------------------------------------------------- #
def test_posture_counts_rather_than_scores(store):
    """A count is actionable; a score invites belief in a precision that is not
    there."""
    _full_account(42)
    security = user_card.build(actor_id=42, scope="self")["summary"]["security"]
    assert security["verified_identities"] == 2
    assert security["known_machines"] == 1
    assert security["live_sessions"] == 3
    assert "score" not in security


def test_an_account_with_one_identity_is_flagged(store):
    _add_identity(42, "telegram", "42")
    security = user_card.build(actor_id=42, scope="self")["summary"]["security"]
    assert "single_recovery_channel" in security["attention"]


def test_an_account_with_no_verified_identity_is_flagged(store):
    """The fixture account carries legacy Telegram and e-mail fields, which
    document migration turns into verified identities, so they are removed here
    to actually get an account with none."""
    doc = account_auth._read_doc()
    doc["auth_identities"] = []
    doc["identity_history"] = []
    for user in doc["users"]:
        user.pop("telegram_user_id", None)
        user.pop("email", None)
    account_auth._write_doc(doc)

    security = user_card.build(actor_id=42, scope="self")["summary"]["security"]
    assert "no_verified_identity" in security["attention"]


def test_pending_devices_are_flagged(store):
    _observe(42, credential="new-browser", session_id="s1")
    security = user_card.build(actor_id=42, scope="self")["summary"]["security"]
    assert "devices_awaiting_confirmation" in security["attention"]
    assert security["pending_devices"] == 1


# --------------------------------------------------------------------------- #
# Timeline.
# --------------------------------------------------------------------------- #
def test_timeline_reports_security_events_for_this_account_only(store):
    _full_account(42)
    _observe(7, credential="bob-browser", session_id="s-bob")

    alice = user_card.build(actor_id=42, scope="self")["timeline"]
    assert alice, "an account with devices and identities has a security history"
    assert all(entry["category"] in
               {"login", "session", "identity", "device", "machine", "admin"}
               for entry in alice)


def test_timeline_carries_attribution_only_for_admins(store):
    _full_account(42)
    own = user_card.build(actor_id=42, scope="self")["timeline"]
    admin = user_card.build(actor_id=999, target_id=42, scope="admin")["timeline"]
    if own:
        assert "actor_user_id" not in own[0]
    if admin:
        assert "actor_user_id" in admin[0]
        assert "origin" in admin[0]


def test_both_views_see_the_same_events(store):
    _full_account(42)
    own = user_card.build(actor_id=42, scope="self")["timeline"]
    admin = user_card.build(actor_id=999, target_id=42, scope="admin")["timeline"]
    assert [e["event"] for e in own] == [e["event"] for e in admin]
    assert [e["at_utc"] for e in own] == [e["at_utc"] for e in admin]


def test_an_unreadable_audit_trail_does_not_break_the_card(store, monkeypatch):
    """A timeline that cannot be read is an empty timeline, not a failed page."""
    _full_account(42)
    monkeypatch.setattr(user_card, "_read_audit", lambda **_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        user_card._read_audit(limit=1)
    monkeypatch.setattr(user_card, "_timeline", lambda user, scope: [])
    card = user_card.build(actor_id=42, scope="self")
    assert card["timeline"] == []
    assert card["summary"]["user_uuid"] == ALICE_UUID



def _only_these_identities(rows):
    """Replace the account's identities with exactly ``rows``.

    The fixture users carry legacy telegram_user_id/email fields, and document
    migration re-derives identities from them on every read, so those have to
    go or the test is measuring the migration rather than the backfill.
    """
    doc = account_auth._read_doc()
    doc["identity_history"] = []
    for user in doc["users"]:
        user.pop("telegram_user_id", None)
        user.pop("email", None)
    account_auth._write_doc(doc)

    doc = account_auth._read_doc()
    doc["identity_history"] = []
    doc["auth_identities"] = list(rows)
    account_auth._write_doc(doc)


# --------------------------------------------------------------------------- #
# Backfill: identities that predate the history model.
# --------------------------------------------------------------------------- #
def test_identities_predating_the_history_model_still_appear(store):
    """Found on the live Canary, not in a test: migration 0014 backfilled the
    relational table, the account document never got the same treatment, and an
    owner with three verified identities rendered a card claiming none."""
    _only_these_identities([{
        "identity_id": "id-1",
        "user_uuid": ALICE_UUID,
        "provider": "email",
        "provider_subject": "alice@example.com",
        "normalized_email": "alice@example.com",
        "verified_at_utc": "2026-02-01T00:00:00Z",
        "linked_at_utc": "2026-01-15T00:00:00Z",
    }])

    identities = user_card.build(actor_id=42, scope="self")["identities"]
    assert [r["provider"] for r in identities["current"]] == ["email"]
    assert identities["current"][0]["display_value"]
    # The identity's own link time, not today: a card showing every identity as
    # created at first render would misstate the age of the account.
    assert identities["current"][0]["valid_from"] == "2026-01-15T00:00:00Z"


def test_the_backfill_never_competes_with_real_history(store):
    """An account that already has history for a provider keeps it. The real
    record of what happened must never be shadowed by a row derived later."""
    doc = account_auth._read_doc()
    doc["identity_history"] = []
    for user in doc["users"]:
        user.pop("telegram_user_id", None)
        user.pop("email", None)
    account_auth._write_doc(doc)
    _add_identity(42, "email", "current@example.com",
                  valid_from="2026-05-01T00:00:00Z")

    doc = account_auth._read_doc()
    doc["auth_identities"] = [{
        "identity_id": "id-1",
        "user_uuid": ALICE_UUID,
        "provider": "email",
        "provider_subject": "someone-else@example.com",
        "normalized_email": "someone-else@example.com",
        "verified_at_utc": "2026-02-01T00:00:00Z",
        "linked_at_utc": "2026-01-15T00:00:00Z",
    }]
    account_auth._write_doc(doc)

    identities = user_card.build(actor_id=42, scope="self")["identities"]
    emails = [r for r in identities["current"] if r["provider"] == "email"]
    assert len(emails) == 1
    assert emails[0]["valid_from"] == "2026-05-01T00:00:00Z"


def test_the_backfill_is_idempotent(store):
    _only_these_identities([{
        "identity_id": "id-1",
        "user_uuid": ALICE_UUID,
        "provider": "telegram",
        "provider_subject": "42",
        "verified_at_utc": "2026-02-01T00:00:00Z",
        "linked_at_utc": "2026-01-15T00:00:00Z",
    }])

    first = user_card.build(actor_id=42, scope="self")["identities"]["current"]
    second = user_card.build(actor_id=42, scope="self")["identities"]["current"]
    assert len(first) == len(second) == 1
    assert len(account_auth._read_doc()["identity_history"]) == 1


def test_an_unverified_identity_is_not_backfilled(store):
    _only_these_identities([{
        "identity_id": "id-1",
        "user_uuid": ALICE_UUID,
        "provider": "email",
        "provider_subject": "unverified@example.com",
        "normalized_email": "unverified@example.com",
        "verified_at_utc": "",
        "linked_at_utc": "2026-01-15T00:00:00Z",
    }])
    assert user_card.build(actor_id=42, scope="self")["identities"]["current"] == []


def test_a_revoked_identity_is_not_backfilled(store):
    _only_these_identities([{
        "identity_id": "id-1",
        "user_uuid": ALICE_UUID,
        "provider": "email",
        "provider_subject": "revoked@example.com",
        "normalized_email": "revoked@example.com",
        "verified_at_utc": "2026-02-01T00:00:00Z",
        "revoked_at_utc": "2026-03-01T00:00:00Z",
        "linked_at_utc": "2026-01-15T00:00:00Z",
    }])
    assert user_card.build(actor_id=42, scope="self")["identities"]["current"] == []
