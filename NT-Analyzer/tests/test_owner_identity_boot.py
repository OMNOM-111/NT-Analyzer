"""Boot must never invent a second owner.

The owner is defined by an immutable UUID. A Telegram chat id, a Google account
or an e-mail are identities *of* that UUID, not the thing that decides who the
owner is.

Treating the development convenience variable as the definition is exactly what
went wrong on LOCAL: NTA_TELEGRAM_CHAT_ID=999 met an empty auth store, and
ensure_owner minted a synthetic owner with a fresh UUID while the real owner
already existed in the workspace store under another one. Nothing reported a
problem, and the two stores disagreed from then on.
"""
from __future__ import annotations

import pytest

from app import account_auth, auth_identity

CANONICAL = "eb9d8e32-8db0-d590-9b35-ef1bd07ec61f"
OTHER = "2c347848-1eff-4493-a5d8-880ece389c1d"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    monkeypatch.delenv(account_auth.CANONICAL_OWNER_UUID_ENV, raising=False)
    return tmp_path


def _seed(owner_id, owner_uuid):
    account_auth._write_doc({
        "version": 3,
        "users": [{
            "user_id": owner_id, "legacy_user_id": owner_id,
            "user_uuid": owner_uuid, "telegram_user_id": owner_id,
            "first_name": "Owner", "role": "owner", "status": "active",
            "is_owner": True,
        }],
        "auth_identities": [], "identity_history": [], "challenges": [],
        "sessions": [], "trusted_devices": [], "physical_devices": [],
        "device_pairings": [], "security_challenges": [],
    })


def _owners():
    doc = account_auth._read_doc()
    return [u for u in doc["users"] if u.get("is_owner") and u.get("status") == "active"]


# --------------------------------------------------------------------------- #
# The regression: existing canonical owner + conflicting chat id.
# --------------------------------------------------------------------------- #
def test_a_conflicting_chat_id_does_not_create_a_second_owner(store, monkeypatch):
    """The exact LOCAL scenario, in reverse: the canonical owner is already
    here and the environment names a different chat id."""
    _seed(1647145559, CANONICAL)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL)

    with pytest.raises(account_auth.OwnerIdentityConflict) as exc:
        account_auth.ensure_owner(999)

    owners = _owners()
    assert len(owners) == 1, "boot must not mint a rival owner"
    assert owners[0]["user_uuid"] == CANONICAL, "the canonical UUID must not move"
    assert owners[0]["user_id"] == 1647145559
    assert "999" in str(exc.value), "the conflict must name the values involved"


def test_the_synthetic_chat_id_does_not_become_an_owner_identity(store, monkeypatch):
    """999 is a development convenience. It must not end up recorded as a
    verified identity of the real owner."""
    _seed(1647145559, CANONICAL)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL)

    with pytest.raises(account_auth.OwnerIdentityConflict):
        account_auth.ensure_owner(999)

    doc = account_auth._read_doc()
    subjects = [str(r.get("provider_subject") or "")
                for r in doc.get("auth_identities") or []]
    assert "999" not in subjects


def test_the_conflict_is_diagnosable_rather_than_silent(store, monkeypatch):
    _seed(1647145559, CANONICAL)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    with pytest.raises(account_auth.OwnerIdentityConflict) as exc:
        account_auth.ensure_owner(999)
    assert exc.value.status == 409
    assert "1647145559" in str(exc.value)


def test_a_mismatched_canonical_uuid_refuses_to_rewrite(store, monkeypatch):
    """Rewriting the stored owner would destroy whatever identities it holds."""
    _seed(999, OTHER)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL)

    with pytest.raises(account_auth.OwnerIdentityConflict) as exc:
        account_auth.ensure_owner(999)
    assert OTHER in str(exc.value) and CANONICAL in str(exc.value)
    assert _owners()[0]["user_uuid"] == OTHER, "nothing is rewritten on conflict"


# --------------------------------------------------------------------------- #
# The paths that must still work.
# --------------------------------------------------------------------------- #
def test_a_matching_owner_is_left_alone(store, monkeypatch):
    _seed(1647145559, CANONICAL)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "1647145559")
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL)
    account_auth.ensure_owner(1647145559)
    owners = _owners()
    assert len(owners) == 1 and owners[0]["user_uuid"] == CANONICAL


def test_an_empty_store_adopts_the_canonical_uuid(store, monkeypatch):
    """A fresh deployment should come up as the same owner, not a new person."""
    account_auth._write_doc({"version": 3, "users": [], "auth_identities": [],
                             "identity_history": [], "challenges": [],
                             "sessions": [], "trusted_devices": [],
                             "physical_devices": [], "device_pairings": [],
                             "security_challenges": []})
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "1647145559")
    monkeypatch.setenv(account_auth.CANONICAL_OWNER_UUID_ENV, CANONICAL)
    account_auth.ensure_owner(1647145559)
    owners = _owners()
    assert len(owners) == 1
    assert owners[0]["user_uuid"] == CANONICAL


def test_without_a_canonical_uuid_a_fresh_store_still_works(store, monkeypatch):
    """Deployments that have not been told a canonical UUID keep working; they
    simply get a generated one."""
    account_auth._write_doc({"version": 3, "users": [], "auth_identities": [],
                             "identity_history": [], "challenges": [],
                             "sessions": [], "trusted_devices": [],
                             "physical_devices": [], "device_pairings": [],
                             "security_challenges": []})
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "555")
    account_auth.ensure_owner(555)
    owners = _owners()
    assert len(owners) == 1
    assert auth_identity.normalize_user_uuid(owners[0]["user_uuid"])


def test_the_canonical_uuid_is_not_hardcoded_in_the_repository():
    """It is a real personal identifier and belongs in a local secret store."""
    source = open(account_auth.__file__, encoding="utf-8").read()
    assert CANONICAL not in source
    assert account_auth.CANONICAL_OWNER_UUID_ENV in source
