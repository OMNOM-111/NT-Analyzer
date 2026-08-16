"""Identity invariants: one verified identifier, one account.

These are adversarial rather than happy-path. The rule that matters is not
"the UI rejects it" but "two accounts can never end up owning the same proven
identity", including when two requests race and both pass their checks before
either commits -- which is why the database carries the same constraints.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import account_auth, auth_identity

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# E-mail normalisation: canonical, but never silently rewritten.
# --------------------------------------------------------------------------- #
def test_case_and_surrounding_space_are_one_address():
    assert auth_identity.normalize_email("  Owner@Example.COM ") == "owner@example.com"


def test_dots_and_plus_tags_are_not_stripped():
    # Gmail treats these as one mailbox, most providers do not. Merging them
    # would join accounts their owners consider separate.
    assert auth_identity.normalize_email("a.b+tag@example.com") == "a.b+tag@example.com"


@pytest.mark.parametrize("value", [
    "", "no-at-sign", "two@@example.com", "user@", "@example.com",
    "user@example", "user@-example.com", "user@example-.com",
    "user@exa mple.com", "user@example..com", "user@example.c",
    "user@example.12", "a" * 65 + "@example.com", "u" * 250 + "@example.com",
])
def test_malformed_addresses_are_refused(value):
    with pytest.raises(auth_identity.IdentityError):
        auth_identity.normalize_email(value)


@pytest.mark.parametrize("value", [
    "user\u200b@example.com",   # zero-width space
    "user\u202e@example.com",   # right-to-left override
    "user\u2066@example.com",   # directional isolate
    "user\x00@example.com",
    "user\x7f@example.com",
])
def test_invisible_and_control_characters_are_refused(value):
    # These are invisible in a UI and are exactly how one address is made to
    # look like another.
    with pytest.raises(auth_identity.IdentityError):
        auth_identity.normalize_email(value)


def test_obvious_domain_typos_are_suggested_never_applied():
    assert auth_identity.email_domain_suggestion("me@gmial.com") == "me@gmail.com"
    assert auth_identity.email_domain_suggestion("me@outlok.com") == "me@outlook.com"
    # A correct address gets no suggestion, and nothing is rewritten anywhere.
    assert auth_identity.email_domain_suggestion("me@gmail.com") == ""
    assert auth_identity.normalize_email("me@gmial.com") == "me@gmial.com"


def test_a_deliberate_unusual_domain_is_not_second_guessed():
    assert auth_identity.email_domain_suggestion("me@mail.example.co.uk") == ""


# --------------------------------------------------------------------------- #
# Phone: canonical E.164, not "the digits".
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("+1 (555) 010-9999", "+15550109999"),
    ("0044 20 7946 0018", "+442079460018"),
    ("+380671234567", "+380671234567"),
])
def test_phone_is_normalised_to_e164(raw, expected):
    assert auth_identity.normalize_phone_e164(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "+0123456789", "+" + "9" * 20, "not-a-number"])
def test_invalid_phone_is_refused(raw):
    with pytest.raises(auth_identity.IdentityError):
        auth_identity.normalize_phone_e164(raw)


# --------------------------------------------------------------------------- #
# Provider subjects.
# --------------------------------------------------------------------------- #
def test_telegram_subject_must_be_a_numeric_id():
    assert auth_identity.normalize_subject("telegram", "1647145559") == "1647145559"
    for bad in ("dimon_check", "0", "-5", "12a"):
        with pytest.raises(auth_identity.IdentityError):
            auth_identity.normalize_subject("telegram", bad)


def test_email_subject_goes_through_the_same_normalisation():
    assert auth_identity.normalize_subject("email", " User@Example.Com ") == "user@example.com"
    with pytest.raises(auth_identity.IdentityError):
        auth_identity.normalize_subject("email", "user\u200b@example.com")


# --------------------------------------------------------------------------- #
# The database carries the invariants, so a race cannot create a duplicate.
# --------------------------------------------------------------------------- #
def _migration(version: int) -> str:
    from app.production_storage.core import MigrationRunner

    return {row["version"]: row for row in MigrationRunner.migrations()}[version]["sql"]


def test_verified_email_is_unique_across_every_provider():
    sql = _migration(13)
    assert "sf_identity_verified_email_uidx" in sql
    # The old index was scoped to provider = 'email', which left the
    # Google-carries-the-same-address case open.
    assert "provider = 'email'" not in sql.split("CREATE UNIQUE INDEX")[1].split(";")[0]
    body = sql.split("sf_identity_verified_email_uidx")[1].split(";")[0]
    assert "verified_at IS NOT NULL" in body
    assert "revoked_at IS NULL" in body


def test_verified_phone_is_unique_and_shaped():
    sql = _migration(13)
    assert "sf_users_verified_phone_uidx" in sql
    assert "sf_users_verified_phone_e164_shape" in sql
    assert r"^\+[1-9][0-9]{6,14}$" in sql


def test_phone_backfill_refuses_to_guess():
    sql = _migration(13)
    backfill = sql[sql.index("UPDATE sf_users"):]
    # Only already-canonical numbers are adopted, and never one that two
    # accounts share -- guessing here would rewrite someone's identity.
    assert r"~ '^\+[1-9][0-9]{6,14}$'" in backfill
    assert "NOT EXISTS" in backfill


def test_migration_13_is_transactional():
    sql = _migration(13)
    # The file opens with an explanatory comment block, so check the
    # statements rather than the first characters.
    statements = [line.strip() for line in sql.splitlines() if not line.strip().startswith("--")]
    assert "BEGIN;" in statements
    assert statements[-1] == "COMMIT;"
