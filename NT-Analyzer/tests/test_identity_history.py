"""Identity history: append-only, one live claim, nothing lost on change."""
from __future__ import annotations

import pytest

from app import identity_history as ih

ALICE = "00000000-0000-4000-8000-0000000000a1"
BOB = "00000000-0000-4000-8000-0000000000b2"


@pytest.fixture()
def doc():
    return {"identity_history": []}


def _add(doc, user, provider, value, **kw):
    return ih.record_change(
        doc, user_uuid=user, legacy_user_id=1, provider=provider, value=value,
        verified_at_utc="2026-08-17T00:00:00Z", actor_source="test", **kw)


# --------------------------------------------------------------------------- #
# A change retires rather than overwrites.
# --------------------------------------------------------------------------- #
def test_replacing_an_email_keeps_the_previous_one_in_history(doc):
    first = _add(doc, ALICE, "email", "old@example.com")
    second = _add(doc, ALICE, "email", "new@example.com", reason="user changed address")

    rows = ih.history_for_user(doc, ALICE)
    assert len(rows) == 2, "the previous address must survive the change"
    states = {r["normalized_key"]: r["state"] for r in rows}
    assert states["old@example.com"] == ih.STATE_RETIRED
    assert states["new@example.com"] == ih.STATE_ACTIVE

    retired = next(r for r in rows if r["normalized_key"] == "old@example.com")
    assert retired["valid_to"], "a retired window must be closed"
    assert retired["replaced_by_history_id"] == second["history_id"]
    assert retired["replacement_reason"] == "user changed address"
    assert first["history_id"] == retired["history_id"]


def test_only_one_active_value_per_provider_per_account(doc):
    _add(doc, ALICE, "email", "one@example.com")
    _add(doc, ALICE, "email", "two@example.com")
    _add(doc, ALICE, "email", "three@example.com")
    active = [r for r in ih.history_for_user(doc, ALICE) if r["state"] == ih.STATE_ACTIVE]
    assert len(active) == 1
    assert active[0]["normalized_key"] == "three@example.com"


def test_providers_do_not_retire_each_other(doc):
    _add(doc, ALICE, "email", "a@example.com")
    _add(doc, ALICE, "phone", "+15550100001")
    _add(doc, ALICE, "telegram", "1647145559")
    active = {r["provider"] for r in ih.history_for_user(doc, ALICE)
              if r["state"] == ih.STATE_ACTIVE}
    assert active == {"email", "phone", "telegram"}


# --------------------------------------------------------------------------- #
# One live claim on an identifier, globally.
# --------------------------------------------------------------------------- #
def test_a_live_identifier_cannot_move_to_another_account(doc):
    _add(doc, ALICE, "email", "shared@example.com")
    with pytest.raises(ih.IdentityHistoryError) as exc:
        _add(doc, BOB, "email", "shared@example.com")
    assert exc.value.code == "identity_active_elsewhere"


def test_case_and_spacing_do_not_create_a_second_claim(doc):
    _add(doc, ALICE, "email", "shared@example.com")
    with pytest.raises(ih.IdentityHistoryError) as exc:
        _add(doc, BOB, "email", "  SHARED@Example.COM ")
    assert exc.value.code == "identity_active_elsewhere"


def test_a_retired_identifier_is_not_free_for_the_taking(doc):
    _add(doc, ALICE, "email", "old@example.com")
    _add(doc, ALICE, "email", "new@example.com")
    # Alice released it, but Bob cannot simply claim it by typing it.
    with pytest.raises(ih.IdentityHistoryError) as exc:
        _add(doc, BOB, "email", "old@example.com")
    assert exc.value.code == "identity_requires_reassignment"


def test_reassignment_is_possible_but_must_be_explicit(doc):
    _add(doc, ALICE, "email", "old@example.com")
    _add(doc, ALICE, "email", "new@example.com")
    moved = _add(doc, BOB, "email", "old@example.com", allow_reassignment=True,
                 reason="owner-approved transfer")
    assert moved["user_uuid"] == BOB
    # Alice's record of having held it is still there.
    alice_keys = {r["normalized_key"] for r in ih.history_for_user(doc, ALICE)}
    assert "old@example.com" in alice_keys


def test_reclaiming_your_own_retired_identifier_is_allowed(doc):
    _add(doc, ALICE, "email", "old@example.com")
    _add(doc, ALICE, "email", "new@example.com")
    back = _add(doc, ALICE, "email", "old@example.com")
    assert back["state"] == ih.STATE_ACTIVE


def test_re_recording_the_same_active_value_is_a_no_op(doc):
    first = _add(doc, ALICE, "email", "a@example.com")
    again = _add(doc, ALICE, "email", "a@example.com")
    assert again["history_id"] == first["history_id"]
    assert len(ih.history_for_user(doc, ALICE)) == 1


# --------------------------------------------------------------------------- #
# Nothing becomes active without proof.
# --------------------------------------------------------------------------- #
def test_an_unverified_value_cannot_be_activated(doc):
    with pytest.raises(ih.IdentityHistoryError) as exc:
        ih.record_change(doc, user_uuid=ALICE, legacy_user_id=1, provider="email",
                         value="a@example.com", verified_at_utc="")
    assert exc.value.code == "verification_required"


def test_revoke_closes_the_window_without_replacing(doc):
    _add(doc, ALICE, "phone", "+15550100001")
    ih.revoke(doc, user_uuid=ALICE, provider="phone", reason="lost handset")
    rows = ih.history_for_user(doc, ALICE)
    assert rows[0]["state"] == ih.STATE_REVOKED
    assert rows[0]["valid_to"]
    assert not [r for r in rows if r["state"] == ih.STATE_ACTIVE]


# --------------------------------------------------------------------------- #
# Rendering never leaks the raw identifier.
# --------------------------------------------------------------------------- #
def test_public_history_masks_every_value(doc):
    _add(doc, ALICE, "email", "someone@example.com")
    _add(doc, ALICE, "phone", "+15550100001")
    public = ih.public_history(ih.history_for_user(doc, ALICE))
    blob = repr(public)
    assert "someone@example.com" not in blob
    assert "+15550100001" not in blob
    assert "normalized_key" not in blob and "key_hash" not in blob
    assert all(row["display_value"] for row in public)


def test_phone_is_stored_canonically(doc):
    row = _add(doc, ALICE, "phone", "+1 (555) 010-0001")
    assert row["normalized_key"] == "+15550100001"
    assert row["display_value"] == "+•••0001"


# --------------------------------------------------------------------------- #
# The database carries the same rules, so a race cannot bypass them.
# --------------------------------------------------------------------------- #
def _migration_14() -> str:
    from app.production_storage.core import MigrationRunner

    return {row["version"]: row for row in MigrationRunner.migrations()}[14]["sql"]


def test_one_active_claim_per_identifier_is_a_database_index():
    sql = _migration_14()
    assert "sf_identity_history_active_key_uidx" in sql
    body = sql.split("sf_identity_history_active_key_uidx")[1].split(";")[0]
    assert "(provider, normalized_key)" in body
    assert "WHERE state = 'active'" in body


def test_one_active_value_per_account_per_provider_is_a_database_index():
    sql = _migration_14()
    assert "sf_identity_history_one_active_per_user_uidx" in sql


def test_history_survives_account_deletion():
    sql = _migration_14()
    # SET NULL, not CASCADE: deleting an account must not erase the record
    # that it once held an identifier, which is what an audit reads.
    assert "user_uuid UUID REFERENCES sf_users(user_uuid) ON DELETE SET NULL" in sql


def test_state_and_window_cannot_disagree():
    sql = _migration_14()
    assert "CHECK ((state IN ('active', 'pending')) = (valid_to IS NULL))" in sql
    assert "CHECK (state <> 'active' OR verified_at IS NOT NULL)" in sql


def test_backfill_sets_a_closed_window_inline():
    sql = _migration_14()
    backfill = sql[sql.index("INSERT INTO sf_identity_history"):]
    # A revoked row with an open window violates the CHECK, so the window has
    # to be set in the insert rather than repaired afterwards.
    assert "valid_to" in backfill.split("SELECT")[0]
    assert "WHEN i.revoked_at IS NOT NULL THEN i.revoked_at" in backfill


def test_history_is_row_level_secured():
    sql = _migration_14()
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "sf_scope_global() OR legacy_user_id = sf_scope_user()" in sql
    # Only a global service scope may write history.
    assert "WITH CHECK (sf_scope_global())" in sql


def test_backfill_declares_the_service_scope_it_runs_under():
    """FORCE ROW LEVEL SECURITY applies to the table owner too.

    Without a declared scope the backfill is refused by this table's own
    policy -- "new row violates row-level security policy", SQLSTATE 42501 --
    which is what blocked 0014 on Canary. 0006 has the same policy shape and
    escaped it only because it inserts no rows.
    """
    sql = _migration_14()
    assert "SET LOCAL stratforge.service_scope = 'global';" in sql
    # SET LOCAL, not SET: the scope must not outlive the migration transaction.
    assert "SET stratforge.service_scope" not in sql.replace("SET LOCAL stratforge.service_scope", "")
    # It has to precede the insert it exists for.
    assert sql.index("SET LOCAL stratforge.service_scope") < sql.index("INSERT INTO sf_identity_history")


def test_the_fix_grants_no_privilege_and_weakens_no_policy():
    sql = _migration_14()
    # Declaring a scope is not the same as handing one out. A GRANT or a
    # relaxed policy here would widen what the runtime role can reach.
    # Checked against statements, not prose: the explanatory comments above
    # legitimately contain the word.
    statements = [line.strip() for line in sql.splitlines()
                  if line.strip() and not line.strip().startswith("--")]
    assert not [s for s in statements if s.upper().startswith("GRANT")]
    assert not [s for s in statements if "NO FORCE ROW LEVEL SECURITY" in s.upper()]
    assert "WITH CHECK (sf_scope_global())" in sql
