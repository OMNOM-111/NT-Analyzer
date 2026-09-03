from __future__ import annotations

import copy
import json

import pytest

from app.production_storage.core import StorageConflictError, StorageConstraintError
from tools import community_storage_migration as migration


def _documents():
    profiles = [
        {"profile_id": "sfp_alpha_0001", "user_id": 101, "username": "alpha_user"},
        {"profile_id": "sfp_beta_00001", "user_id": 202, "username": "beta_user"},
    ]
    community = {
        "version": 4, "profiles": profiles,
        "posts": [{"post_id": "cpost_00000001", "author_profile_id": "sfp_alpha_0001"}],
        "comments": [], "follows": [], "post_reactions": [], "bookmarks": [],
        "social_blocks": [],
    }
    chat = {
        "version": 1,
        "conversations": [{
            "conversation_id": "sfh_alpha_beta_01",
            "participant_profile_ids": ["sfp_alpha_0001", "sfp_beta_00001"],
            "last_seq": 1,
        }],
        "messages": [{
            "message_id": "sfm_00000000001", "conversation_id": "sfh_alpha_beta_01",
            "sender_profile_id": "sfp_alpha_0001", "seq": 1, "text": "hello",
        }],
        "reads": [{
            "conversation_id": "sfh_alpha_beta_01", "profile_id": "sfp_alpha_0001",
            "last_read_seq": 1,
        }],
    }
    for name in migration._COLLECTION_KEYS["community"]:
        community.setdefault(name, [])
    return community, chat


def test_plan_is_deterministic_validated_and_backup_is_reusable(tmp_path):
    community, chat = _documents()
    community_path, chat_path = tmp_path / "community.json", tmp_path / "sf_chat.json"
    community_path.write_text(json.dumps(community), encoding="utf-8")
    chat_path.write_text(json.dumps(chat), encoding="utf-8")
    plan = migration.build_plan(community_path=community_path, sf_chat_path=chat_path)
    summary = migration.plan_summary(plan)
    assert len(summary["plan_sha256"]) == 64
    assert summary["counts"]["community.profiles"] == 2
    assert summary["counts"]["sf_chat.messages"] == 1

    first = migration.backup_sources(plan, tmp_path / "backup")
    second = migration.backup_sources(plan, tmp_path / "backup")
    assert first == second
    assert len(first["files"]) == 2
    assert (tmp_path / "backup" / f"manifest-{summary['plan_sha256'][:16]}.json").is_file()


def test_merge_is_idempotent_and_conflicts_fail_closed():
    community, _ = _documents()
    first = migration._merge_document("community", {}, community, "a" * 64)
    replay = migration._merge_document("community", first, community, "a" * 64)
    assert replay == first
    changed = copy.deepcopy(community)
    changed["profiles"][0]["username"] = "tampered"
    with pytest.raises(StorageConflictError, match="Conflicting community.profiles"):
        migration._merge_document("community", first, changed, "b" * 64)


def test_validation_rejects_nonparticipant_message_and_chat_without_community():
    community, chat = _documents()
    chat["messages"][0]["sender_profile_id"] = "sfp_outsider_0001"
    with pytest.raises(StorageConstraintError, match="ACL/sequence"):
        migration.validate_documents({"community": community, "sf_chat": chat})
    with pytest.raises(StorageConstraintError, match="matching Community"):
        migration.validate_documents({"sf_chat": _documents()[1]})


def test_validation_rejects_orphan_social_edges_and_stale_chat_sequence():
    community, chat = _documents()
    community["bookmarks"].append({
        "post_id": "missing_post", "profile_id": "sfp_alpha_0001",
    })
    with pytest.raises(StorageConstraintError, match="bookmarks edge"):
        migration.validate_documents({"community": community, "sf_chat": chat})

    community, chat = _documents()
    chat["conversations"][0]["last_seq"] = 0
    with pytest.raises(StorageConstraintError, match="last_seq is behind"):
        migration.validate_documents({"community": community, "sf_chat": chat})


def test_validation_rejects_case_insensitive_duplicate_profile_username():
    community, _ = _documents()
    community["profiles"][1]["username"] = "ALPHA_USER"
    with pytest.raises(StorageConstraintError, match="username is duplicated"):
        migration.validate_documents({"community": community})
