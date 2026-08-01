from __future__ import annotations

import copy

import pytest

from tools import production_owner_bootstrap as bootstrap


def _documents():
    owner_id = 999
    old_user = 42
    workspace_id = "ws_personal_owner1234"
    auth = {
        "version": 2,
        "users": [
            {"user_id": owner_id, "role": "owner", "is_owner": True, "status": "active"},
            {"user_id": old_user, "role": "full_control", "is_owner": False, "status": "active"},
        ],
        "challenges": [], "sessions": [],
    }
    workspaces = {
        "version": 1,
        "workspaces": [{
            "workspace_id": workspace_id, "kind": "personal", "status": "active",
            "owner_user_id": old_user,
        }],
        "memberships": [{
            "workspace_id": workspace_id, "user_id": old_user, "role": "owner",
            "revoked_at_utc": "",
        }],
        "active_workspaces": {str(old_user): workspace_id},
        "connections": [], "pairings": [],
    }
    connectors = {
        "schema_version": 1,
        "enrollments": [{
            "enrollment_id": "enr_12345678", "workspace_id": workspace_id,
            "created_by_user_id": old_user, "status": "consumed",
        }],
        "installations": [{
            "installation_id": "inst_12345678", "workspace_id": workspace_id,
            "enrolled_by_user_id": old_user, "status": "online",
        }],
        "sessions": [], "commands": [], "results": [],
    }
    return owner_id, old_user, workspace_id, auth, workspaces, connectors


def test_reconciliation_binds_preconfigured_owner_and_is_idempotent() -> None:
    owner_id, old_user, workspace_id, auth, workspaces, connectors = _documents()
    original = copy.deepcopy((auth, workspaces, connectors))

    repaired, summary = bootstrap.reconcile_documents(
        auth, workspaces, connectors, owner_id=owner_id, workspace_id=workspace_id,
    )

    assert (auth, workspaces, connectors) == original
    assert summary["owner_users"] == 1
    assert summary["owner_workspaces"] == 1
    assert summary["owner_memberships"] == 1
    assert summary["online_connectors"] == 1
    target = repaired["workspaces"]["workspaces"][0]
    assert target["owner_user_id"] == owner_id
    owner_membership = next(
        row for row in repaired["workspaces"]["memberships"]
        if row["user_id"] == owner_id
    )
    old_membership = next(
        row for row in repaired["workspaces"]["memberships"]
        if row["user_id"] == old_user
    )
    assert owner_membership["role"] == "owner" and not owner_membership["revoked_at_utc"]
    assert old_membership["role"] == "viewer"
    assert repaired["workspaces"]["active_workspaces"][str(owner_id)] == workspace_id
    assert repaired["connectors"]["installations"][0]["enrolled_by_user_id"] == owner_id

    second, second_summary = bootstrap.reconcile_documents(
        repaired["auth"], repaired["workspaces"], repaired["connectors"],
        owner_id=owner_id, workspace_id=workspace_id,
    )
    assert second == repaired
    assert second_summary["idempotent"] is True
    assert second_summary["changes"] == {"auth": 0, "workspaces": 0, "connectors": 0}


def test_reconciliation_rejects_foreign_owner_and_implicit_workspace() -> None:
    owner_id, _old_user, workspace_id, auth, workspaces, connectors = _documents()
    auth["users"].append({
        "user_id": 77, "role": "owner", "is_owner": True, "status": "active",
    })
    with pytest.raises(bootstrap.OwnerBootstrapError):
        bootstrap.reconcile_documents(
            auth, workspaces, connectors, owner_id=owner_id, workspace_id=workspace_id,
        )

    auth["users"].pop()
    with pytest.raises(bootstrap.OwnerBootstrapError):
        bootstrap.reconcile_documents(
            auth, workspaces, connectors,
            owner_id=owner_id, workspace_id="ws_missing_12345678",
        )


def test_reconciliation_requires_exactly_one_online_connector() -> None:
    owner_id, _old_user, workspace_id, auth, workspaces, connectors = _documents()
    connectors["installations"][0]["status"] = "offline"
    with pytest.raises(bootstrap.OwnerBootstrapError):
        bootstrap.reconcile_documents(
            auth, workspaces, connectors, owner_id=owner_id, workspace_id=workspace_id,
        )
