"""Pure account-erasure boundaries; real PostgreSQL tests live in a DSN suite."""
from __future__ import annotations

import copy
from pathlib import Path
from uuid import uuid4

import pytest

from app.account_auth import AccountAuthError
from app.production_storage import account_erasure as erasure


def _docs():
    owner = str(uuid4())
    target = str(uuid4())
    ws_owner, ws_target = "ws_owner_12345678", "ws_target_12345678"
    docs = erasure._defaults()
    docs["auth"].update({
        "users": [
            {"user_id": 1, "user_uuid": owner, "is_owner": True, "status": "active"},
            {"user_id": 2, "user_uuid": target, "is_owner": False, "status": "active"},
        ],
        "auth_identities": [
            {"legacy_user_id": 1, "user_uuid": owner, "provider": "google"},
            {"legacy_user_id": 2, "user_uuid": target, "provider": "google"},
        ],
        "sessions": [
            {"user_id": 1, "user_uuid": owner, "session_id": "owner"},
            {"user_id": 2, "user_uuid": target, "session_id": "target"},
        ],
        "identity_history": [
            {"user_uuid": owner, "state": "active", "normalized_key": "owner@example.test"},
            {"user_uuid": target, "state": "active", "normalized_key": "target@example.test"},
        ],
    })
    docs["workspaces"].update({
        "workspaces": [
            {"workspace_id": ws_owner, "owner_user_id": 1, "owner_user_uuid": owner},
            {"workspace_id": ws_target, "owner_user_id": 2, "owner_user_uuid": target},
        ],
        "memberships": [
            {"workspace_id": ws_owner, "user_id": 1, "user_uuid": owner},
            {"workspace_id": ws_target, "user_id": 2, "user_uuid": target},
        ],
        "active_workspaces": {"1": ws_owner, "2": ws_target},
        "active_workspaces_by_uuid": {owner: ws_owner, target: ws_target},
    })
    docs["entitlements"]["entitlements"] = [
        {"user_id": 1, "workspace_id": ws_owner, "plan_id": "pro"},
        {"user_id": 2, "workspace_id": ws_target, "plan_id": "pro"},
    ]
    docs["connectors"]["installations"] = [
        {"installation_id": "owner-connector", "user_id": 1, "workspace_id": ws_owner},
        {"installation_id": "target-connector", "user_id": 2, "workspace_id": ws_target},
    ]
    docs["community"].update({
        "profiles": [
            {"profile_id": "owner-profile", "user_id": 1, "user_uuid": owner},
            {"profile_id": "target-profile", "user_id": 2, "user_uuid": target},
        ],
        "posts": [
            {"post_id": "owner-post", "author_profile_id": "owner-profile"},
            {"post_id": "target-post", "author_profile_id": "target-profile",
             "workspace_id": ws_target, "attachments": [{"stored_name": "private.png"}]},
        ],
    })
    docs["sf_chat"].update({
        "conversations": [
            {"conversation_id": "owner-conversation", "participant_profile_ids": ["owner-profile"]},
            {"conversation_id": "target-conversation", "participant_profile_ids": ["target-profile"]},
        ],
        "messages": [
            {"conversation_id": "owner-conversation", "message_id": "owner-message"},
            {"conversation_id": "target-conversation", "message_id": "target-message"},
        ],
    })
    return docs, target, ws_target


def test_private_documents_are_removed_and_foreign_rows_remain():
    docs, target, ws_target = _docs()
    original = copy.deepcopy(docs)
    user, canonical, owned, memberships = erasure._identity(docs, 2, retry=False)
    assert canonical == target and owned == memberships == {ws_target}
    planned, objects = erasure._transform(docs, 2, target, owned)
    assert [row["user_id"] for row in planned["auth"]["users"]] == [1]
    assert [row["session_id"] for row in planned["auth"]["sessions"]] == ["owner"]
    assert [row["workspace_id"] for row in planned["workspaces"]["workspaces"]] == ["ws_owner_12345678"]
    assert [row["plan_id"] for row in planned["entitlements"]["entitlements"]] == ["pro"]
    assert [row["installation_id"] for row in planned["connectors"]["installations"]] == ["owner-connector"]
    assert [row["profile_id"] for row in planned["community"]["profiles"]] == ["owner-profile"]
    assert [row["post_id"] for row in planned["community"]["posts"]] == ["owner-post"]
    assert [row["conversation_id"] for row in planned["sf_chat"]["conversations"]] == ["owner-conversation"]
    assert [row["message_id"] for row in planned["sf_chat"]["messages"]] == ["owner-message"]
    assert planned["auth"]["identity_history"][1]["state"] == "revoked"
    assert planned["auth"]["identity_history"][0] == original["auth"]["identity_history"][0]
    assert ("sf_chat", "target-conversation", None) in objects
    assert ("community", ws_target + "/private.png", None) in objects


def test_owner_service_and_shared_workspace_fail_closed():
    docs, target, ws_target = _docs()
    with pytest.raises(AccountAuthError) as owner:
        erasure._identity(docs, 1, retry=False)
    assert owner.value.status == 403
    docs["auth"]["users"][1]["is_service_account"] = True
    with pytest.raises(AccountAuthError) as service:
        erasure._identity(docs, 2, retry=False)
    assert service.value.status == 403
    docs["auth"]["users"][1]["is_service_account"] = False
    docs["workspaces"]["memberships"].append({"workspace_id": ws_target, "user_id": 1})
    with pytest.raises(AccountAuthError) as shared:
        erasure._identity(docs, 2, retry=False)
    assert shared.value.code == "workspace_shared"


def test_blocked_retry_is_explicit_not_self_admission():
    docs, _, _ = _docs()
    docs["auth"]["users"][1].update(status="blocked", deletion_pending=True)
    with pytest.raises(AccountAuthError):
        erasure._identity(docs, 2, retry=False)
    assert erasure._identity(docs, 2, retry=True)[0]["deletion_pending"] is True


def test_file_targets_must_stay_within_exact_root(tmp_path: Path):
    root = tmp_path / "objects"
    root.mkdir()
    assert erasure._safe_target(root, "ws_target_12345678/item.png").is_relative_to(root)
    for unsafe in ("../outside", str(tmp_path / "outside"), "C:/outside"):
        with pytest.raises(AccountAuthError):
            erasure._safe_target(root, unsafe)


def test_new_external_legacy_id_never_reuses_deleted_receipt(monkeypatch):
    from app import account_auth, account_lifecycle, storage_router
    first = account_auth.EXTERNAL_LEGACY_ID_FLOOR + 17
    second = first + 1
    monkeypatch.setattr(storage_router, "production_enabled", lambda: True)
    monkeypatch.setattr(account_lifecycle, "deleted_legacy_ids", lambda: {first})
    picks = iter((17, 18))
    monkeypatch.setattr(account_auth.secrets, "randbelow", lambda _: next(picks))
    assert account_auth._allocate_external_legacy_user_id({"users": []}) == second
