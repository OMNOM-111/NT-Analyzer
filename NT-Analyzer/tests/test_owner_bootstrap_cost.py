"""The owner bootstrap is not a per-request question.

Measured on Production beta.76: an endpoint that touches no auth answers in
0.9 ms, while /api/auth/status took 18.7-58.6 ms. The difference is a full
read of the account document -- from Postgres, on a path with no cache, then
migrated -- performed by ensure_owner before any session is even looked at,
on every authenticated poll.

ensure_owner authorises nothing. It makes sure the owner row exists and is
correct, which cannot spontaneously stop being true. These tests pin that it
is remembered only when it had nothing to fix, and forgotten the moment
anything writes to the store.
"""
from __future__ import annotations

import copy

import pytest

from app import account_auth


@pytest.fixture(autouse=True)
def _forget():
    account_auth._forget_owner_bootstrap()
    yield
    account_auth._forget_owner_bootstrap()


def _owner_doc(uid: int = 42) -> dict:
    return {
        "users": [{
            "user_id": uid, "legacy_user_id": uid,
            "user_uuid": "00000000-0000-4000-8000-000000000001",
            "telegram_user_id": uid, "username": "owner",
            "first_name": "O", "last_name": "W", "email": "", "phone": "",
            "role": "owner", "status": "active", "is_owner": True,
            "primary_login_provider": "telegram",
            "created_at_utc": "2026-01-01T00:00:00Z",
            "approved_at_utc": "2026-01-01T00:00:00Z", "revoked_at_utc": "",
        }],
        "auth_identities": [{
            "provider": "telegram", "subject": "42", "user_id": uid,
            "verified_at_utc": "2026-01-01T00:00:00Z", "metadata": {},
        }],
        "challenges": [], "sessions": [],
    }


@pytest.fixture
def store(monkeypatch):
    """A settled deployment: the owner exists and is already correct."""
    state = {"doc": _owner_doc(), "reads": 0, "writes": 0}

    def read():
        state["reads"] += 1
        return copy.deepcopy(state["doc"])

    def write(doc):
        state["writes"] += 1
        state["doc"] = copy.deepcopy(doc)

    monkeypatch.setattr(account_auth, "_read_doc", read)
    monkeypatch.setattr(account_auth, "_write_doc", write)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(account_auth, "canonical_owner_uuid",
                        lambda: "00000000-0000-4000-8000-000000000001")
    return state


def test_a_settled_owner_is_read_once_not_once_per_request(store):
    # The very first call on a fresh store completes the identity summary and
    # writes; that repair is deliberately not remembered.
    account_auth.ensure_owner("42")
    settled_reads, settled_writes = store["reads"], store["writes"]

    first = account_auth.ensure_owner("42")
    assert first and first.get("is_owner") is True
    assert store["reads"] == settled_reads + 1
    assert store["writes"] == settled_writes, "a settled owner needs no write"

    for _ in range(20):
        assert account_auth.ensure_owner("42") == first
    assert store["reads"] == settled_reads + 1,         "twenty polls must not be twenty reads"
    assert store["writes"] == settled_writes


def test_the_answer_is_a_copy_so_a_caller_cannot_poison_it(store):
    first = account_auth.ensure_owner("42")
    first["role"] = "tampered"
    again = account_auth.ensure_owner("42")
    assert again["role"] == "owner"


def test_a_run_that_repaired_something_is_not_remembered(store, monkeypatch):
    """Only a bootstrap with nothing to fix says anything about the next one."""
    store["doc"]["users"][0]["status"] = "revoked"
    account_auth.ensure_owner("42")
    assert store["writes"] == 1, "the repair must be written"
    reads_after_repair = store["reads"]

    account_auth.ensure_owner("42")
    assert store["reads"] > reads_after_repair, \
        "a repairing run must not be cached"


def test_any_write_forgets_what_the_bootstrap_remembered(store):
    account_auth.ensure_owner("42")
    assert store["reads"] == 1
    # Something else changes the account store.
    account_auth._write_doc(store["doc"])
    account_auth.ensure_owner("42")
    assert store["reads"] == 2, "the memo must not outlive a write"


def test_a_different_owner_id_is_never_served_from_the_memo(store, monkeypatch):
    account_auth.ensure_owner("42")
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "99")
    with pytest.raises(account_auth.AccountAuthError):
        # 42 no longer matches the configured chat, and the memo must not
        # paper over that.
        account_auth.ensure_owner("42")


def test_the_memo_expires(store, monkeypatch):
    account_auth.ensure_owner("42")
    assert store["reads"] == 1
    monkeypatch.setattr(
        account_auth, "_OWNER_BOOTSTRAP_TTL_SEC", 0.0)
    account_auth._forget_owner_bootstrap()
    account_auth.ensure_owner("42")
    assert store["reads"] == 2


def test_nothing_about_authorisation_moved_into_the_memo():
    """The bootstrap grants nothing; sessions are still read every time."""
    import inspect

    src = inspect.getsource(account_auth.ensure_owner)
    assert "_OWNER_BOOTSTRAP" in src
    for authorising in ("session", "csrf", "token"):
        assert authorising not in src.lower().split("_owner_bootstrap")[0][-400:]
