from __future__ import annotations

import copy

import pytest

from app.production_storage import build_owner_plan, owner_plan_summary
from app.production_storage.core import StorageConflictError, StorageConstraintError


OWNER_ID = 101
WORKSPACE_ID = "ws_owner_MIGRATE01"
INSTALLATION_ID = "inst_owner_migrate_01"


def _source():
    documents = {
        "auth": {
            "version": 2,
            "users": [{
                "user_id": OWNER_ID,
                "is_owner": True,
                "status": "active",
                "first_name": "Owner",
                "session_token": "must-not-migrate",
                "avatar_path": r"C:\\Users\\owner\\avatar.png",
            }, {
                "user_id": 202,
                "status": "active",
                "first_name": "Other",
            }],
            "challenges": [{"challenge_id": "challenge-secret"}],
            "sessions": [{"session_id": "session-secret", "user_id": OWNER_ID}],
        },
        "workspaces": {
            "version": 1,
            "workspaces": [{
                "workspace_id": WORKSPACE_ID,
                "owner_user_id": OWNER_ID,
                "status": "active",
                "kind": "personal",
                "data_root": r"C:\\client\\data",
            }],
            "memberships": [
                {"workspace_id": WORKSPACE_ID, "user_id": OWNER_ID, "role": "owner"},
                {"workspace_id": WORKSPACE_ID, "user_id": 202, "role": "viewer"},
            ],
            "active_workspaces": {str(OWNER_ID): WORKSPACE_ID, "202": WORKSPACE_ID},
            "connections": [{"connection_id": "legacy-unverified"}],
            "pairings": [{"code_hash": "secret"}],
        },
        "entitlements": {
            "version": 1,
            "entitlements": [
                {"entitlement_id": "ent_owner_001", "user_id": OWNER_ID,
                 "workspace_id": WORKSPACE_ID, "plan_id": "pro", "status": "active"},
                {"entitlement_id": "ent_other_001", "user_id": 202,
                 "workspace_id": WORKSPACE_ID, "plan_id": "pro", "status": "active"},
            ],
            "vouchers": [{"code_hash": "secret"}],
            "payment_config": {"secret": "must-not-migrate"},
            "paypal": {"access_token": "must-not-migrate"},
            "payment_requests": [{"request_id": "request-other"}],
            "plan_overrides": {"pro": {"price": 1}},
        },
        "connectors": {
            "schema_version": 1,
            "installations": [{
                "installation_id": INSTALLATION_ID,
                "workspace_id": WORKSPACE_ID,
                "enrolled_by_user_id": OWNER_ID,
                "status": "online",
                "public_key_fingerprint": "a" * 64,
                "public_key": {"kty": "EC", "crv": "P-256", "x": "x", "y": "y", "d": "private"},
                "challenge_nonce_hash": "must-not-migrate",
                "runtime_dir": r"C:\\NinjaTrader\\runtime",
            }],
            "enrollments": [{"code_hash": "secret"}],
            "sessions": [{"token_hash": "b" * 64}],
            "commands": [{"command_id": "cmd-secret"}],
            "results": [{"command_id": "cmd-secret"}],
        },
    }
    ledgers = {WORKSPACE_ID: {
        "version": 1,
        "accounts": {},
        "source_path": r"C:\\broker\\ledger.json",
    }}
    return documents, ledgers


def _plan():
    documents, ledgers = _source()
    return build_owner_plan(
        documents,
        ledgers,
        owner_user_id=OWNER_ID,
        categories=("auth", "workspaces", "entitlements", "connectors", "ledgers"),
        workspace_ids=(WORKSPACE_ID,),
        installation_ids=(INSTALLATION_ID,),
    )


def test_owner_plan_contains_only_explicit_durable_data_and_no_client_paths() -> None:
    plan = _plan()
    assert [row["user_id"] for row in plan["documents"]["auth"]["users"]] == [OWNER_ID]
    assert plan["documents"]["auth"]["sessions"] == []
    assert plan["documents"]["auth"]["challenges"] == []
    assert "session_token" not in plan["documents"]["auth"]["users"][0]
    assert "avatar_path" not in plan["documents"]["auth"]["users"][0]
    assert len(plan["documents"]["workspaces"]["memberships"]) == 1
    assert plan["documents"]["workspaces"]["connections"] == []
    assert plan["documents"]["entitlements"]["payment_config"] == {}
    assert [row["entitlement_id"] for row in plan["documents"]["entitlements"]["entitlements"]] == [
        "ent_owner_001"
    ]
    installation = plan["documents"]["connectors"]["installations"][0]
    assert installation["status"] == "offline"
    assert "challenge_nonce_hash" not in installation
    assert "runtime_dir" not in installation
    assert "d" not in installation["public_key"]
    assert "source_path" not in plan["ledgers"][WORKSPACE_ID]
    assert plan["redactions"]["credentials"] > 0
    assert plan["redactions"]["paths"] > 0


def test_owner_plan_summary_exposes_checksums_and_counts_but_not_payload() -> None:
    summary = owner_plan_summary(_plan())
    assert summary["dry_run"] is True
    assert len(summary["source_sha256"]) == 64
    assert len(summary["plan_sha256"]) == 64
    assert summary["counts"] == {
        "users": 1,
        "workspaces": 1,
        "memberships": 1,
        "entitlements": 1,
        "installations": 1,
        "ledgers": 1,
    }
    assert "documents" not in summary
    assert "ledgers" not in summary


def test_owner_plan_rejects_implicit_relations_and_unselected_installations() -> None:
    documents, ledgers = _source()
    with pytest.raises(StorageConstraintError, match="explicitly include auth"):
        build_owner_plan(
            documents, ledgers, owner_user_id=OWNER_ID,
            categories=("workspaces",), workspace_ids=(WORKSPACE_ID,),
        )
    with pytest.raises(StorageConstraintError, match="explicit installation_ids"):
        build_owner_plan(
            documents, ledgers, owner_user_id=OWNER_ID,
            categories=("auth", "workspaces", "connectors"),
            workspace_ids=(WORKSPACE_ID,),
        )


def test_owner_plan_checksum_detects_any_payload_tampering() -> None:
    plan = _plan()
    tampered = copy.deepcopy(plan)
    tampered["documents"]["auth"]["users"][0]["first_name"] = "Changed"
    with pytest.raises(StorageConflictError, match="checksum"):
        owner_plan_summary(tampered)
