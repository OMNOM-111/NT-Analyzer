#!/usr/bin/env python3
"""Plan, back up and idempotently import Community/SF Chat JSON documents.

Dry-run is the default. Applying requires an exact plan checksum and a backup
directory; source files are never modified or deleted.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.production_storage.core import (  # noqa: E402
    DocumentRepository,
    PostgresClient,
    Scope,
    StorageConflictError,
    StorageConstraintError,
    _canonical,
    _jsonb,
)


PLAN_VERSION = 1
_COLLECTION_KEYS: Dict[str, Dict[str, Sequence[str]]] = {
    "community": {
        "accounts": ("workspace_id", "user_id"),
        "messages": ("message_id",),
        "posts": ("post_id",),
        "strategies": ("strategy_id",),
        "copies": ("copy_id",),
        "reports": ("report_id",),
        "blocks": ("workspace_id", "user_id"),
        "shared_reports": ("report_id",),
        "requests": ("request_id",),
        "profiles": ("profile_id",),
        "follows": ("follower_profile_id", "target_profile_id"),
        "post_reactions": ("post_id", "profile_id"),
        "comments": ("comment_id",),
        "bookmarks": ("post_id", "profile_id"),
        "social_blocks": ("blocker_profile_id", "target_profile_id"),
    },
    "sf_chat": {
        "conversations": ("conversation_id",),
        "messages": ("message_id",),
        "reads": ("conversation_id", "profile_id"),
    },
}


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_document(path: Path, repository: str) -> Dict[str, Any]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise StorageConstraintError(f"{repository} source does not exist: {source}")
    try:
        parsed = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StorageConstraintError(f"{repository} source is not valid UTF-8 JSON.") from exc
    if not isinstance(parsed, dict):
        raise StorageConstraintError(f"{repository} source must be a JSON object.")
    clean: Dict[str, Any] = {"version": int(parsed.get("version") or 1)}
    for collection in _COLLECTION_KEYS[repository]:
        value = parsed.get(collection, [])
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise StorageConstraintError(f"{repository}.{collection} must be an object array.")
        clean[collection] = copy.deepcopy(value)
    return clean


def _identity(row: Mapping[str, Any], keys: Sequence[str], label: str) -> tuple[str, ...]:
    raw_identity = tuple(str(row.get(key) or "").strip() for key in keys)
    if not any(raw_identity):
        raise StorageConstraintError(f"{label} has an empty identity field.")
    if any(len(value) > 160 for value in raw_identity):
        raise StorageConstraintError(f"{label} identity is too long.")
    # Empty workspace is a meaningful legacy/global scope for compound keys.
    return tuple(value or "<empty>" for value in raw_identity)


def _unique_rows(document: Mapping[str, Any], repository: str) -> None:
    for collection, keys in _COLLECTION_KEYS[repository].items():
        seen = set()
        for row in document.get(collection, []):
            identity = _identity(row, keys, f"{repository}.{collection}")
            if identity in seen:
                raise StorageConstraintError(f"Duplicate {repository}.{collection} identity.")
            seen.add(identity)


def validate_documents(documents: Mapping[str, Mapping[str, Any]]) -> Dict[str, int]:
    if not documents:
        raise StorageConstraintError("At least one source document is required.")
    unknown = set(documents) - set(_COLLECTION_KEYS)
    if unknown:
        raise StorageConstraintError("Unsupported Community migration repository.")
    for repository, document in documents.items():
        _unique_rows(document, repository)

    community = documents.get("community") or {}
    profiles = {
        str(row.get("profile_id") or "") for row in community.get("profiles", [])
        if isinstance(row, Mapping)
    }
    profile_user_ids: set[int] = set()
    profile_usernames: set[str] = set()
    for row in community.get("profiles", []):
        profile_id = str(row.get("profile_id") or "")
        user_id = int(row.get("user_id") or 0)
        username = str(row.get("username") or "")
        if not 8 <= len(profile_id) <= 96:
            raise StorageConstraintError("Community profile_id length is invalid.")
        if user_id <= 0:
            raise StorageConstraintError("Community profile requires a positive user_id.")
        if user_id in profile_user_ids:
            raise StorageConstraintError("Community profile user_id is duplicated.")
        if not 3 <= len(username) <= 30:
            raise StorageConstraintError("Community profile username length is invalid.")
        folded_username = username.casefold()
        if folded_username in profile_usernames:
            raise StorageConstraintError("Community profile username is duplicated.")
        profile_user_ids.add(user_id)
        profile_usernames.add(folded_username)

    posts: set[str] = set()
    for row in community.get("posts", []):
        post_id = str(row.get("post_id") or "")
        author = str(row.get("author_profile_id") or "")
        if author not in profiles:
            raise StorageConstraintError("Community post author profile is missing.")
        posts.add(post_id)
        snapshot = row.get("object_snapshot") if isinstance(row.get("object_snapshot"), Mapping) else {}
        attestation = snapshot.get("attestation") if isinstance(snapshot.get("attestation"), Mapping) else {}
        digest = str(attestation.get("digest") or "")
        if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise StorageConstraintError("Community result attestation digest is invalid.")

    comments: set[str] = set()
    for row in community.get("comments", []):
        if str(row.get("post_id") or "") not in posts:
            raise StorageConstraintError("Community comment parent post is missing.")
        if str(row.get("author_profile_id") or "") not in profiles:
            raise StorageConstraintError("Community comment author profile is missing.")
        comments.add(str(row.get("comment_id") or ""))
    for collection, left_key, right_key in (
        ("follows", "follower_profile_id", "target_profile_id"),
        ("social_blocks", "blocker_profile_id", "target_profile_id"),
    ):
        for row in community.get(collection, []):
            left, right = str(row.get(left_key) or ""), str(row.get(right_key) or "")
            if left == right or left not in profiles or right not in profiles:
                raise StorageConstraintError(f"Community {collection} edge is invalid.")
    for collection in ("post_reactions", "bookmarks"):
        for row in community.get(collection, []):
            if (str(row.get("post_id") or "") not in posts
                    or str(row.get("profile_id") or "") not in profiles):
                raise StorageConstraintError(f"Community {collection} edge is invalid.")
    for row in community.get("reports", []):
        reporter = str(row.get("from_profile_id") or "")
        if not reporter:  # Legacy account-level report; not part of the social mirror.
            continue
        target_type = str(row.get("target_type") or "")
        target_id = str(row.get("target_id") or "")
        target_ids = {"post": posts, "comment": comments, "profile": profiles}.get(target_type)
        if reporter not in profiles or target_ids is None or target_id not in target_ids:
            raise StorageConstraintError("Community moderation report graph is invalid.")

    chat = documents.get("sf_chat") or {}
    if chat and not community:
        raise StorageConstraintError("SF Chat import requires the matching Community source.")
    conversations: Dict[str, set[str]] = {}
    for row in chat.get("conversations", []):
        conversation_id = str(row.get("conversation_id") or "")
        participants = {str(value) for value in row.get("participant_profile_ids", []) if value}
        if len(participants) != 2 or not participants <= profiles:
            raise StorageConstraintError("SF Chat conversation requires two valid Community profiles.")
        conversations[conversation_id] = participants
    sequence_keys = set()
    max_sequence: Dict[str, int] = {conversation_id: 0 for conversation_id in conversations}
    idempotency_keys = set()
    for row in chat.get("messages", []):
        conversation_id = str(row.get("conversation_id") or "")
        sender = str(row.get("sender_profile_id") or "")
        seq = int(row.get("seq") or 0)
        if conversation_id not in conversations or sender not in conversations[conversation_id] or seq <= 0:
            raise StorageConstraintError("SF Chat message ACL/sequence is invalid.")
        if (conversation_id, seq) in sequence_keys:
            raise StorageConstraintError("SF Chat message sequence is duplicated.")
        sequence_keys.add((conversation_id, seq))
        max_sequence[conversation_id] = max(max_sequence[conversation_id], seq)
        idem_hash = str(row.get("idempotency_key_hash") or "")
        if idem_hash:
            if not re.fullmatch(r"[0-9a-f]{64}", idem_hash):
                raise StorageConstraintError("SF Chat idempotency hash is invalid.")
            idem_key = (conversation_id, sender, idem_hash)
            if idem_key in idempotency_keys:
                raise StorageConstraintError("SF Chat idempotency hash is duplicated.")
            idempotency_keys.add(idem_key)
    conversation_last_seq = {
        str(row.get("conversation_id") or ""): int(row.get("last_seq") or 0)
        for row in chat.get("conversations", [])
    }
    for conversation_id, maximum in max_sequence.items():
        if conversation_last_seq.get(conversation_id, 0) < maximum:
            raise StorageConstraintError("SF Chat conversation last_seq is behind messages.")
    for row in chat.get("reads", []):
        conversation_id = str(row.get("conversation_id") or "")
        if str(row.get("profile_id") or "") not in conversations.get(conversation_id, set()):
            raise StorageConstraintError("SF Chat read state is not a participant state.")
        last_read_seq = int(row.get("last_read_seq") or 0)
        if last_read_seq < 0 or last_read_seq > conversation_last_seq.get(conversation_id, 0):
            raise StorageConstraintError("SF Chat read sequence is invalid.")

    return {
        f"{repository}.{collection}": len(document.get(collection, []))
        for repository, document in sorted(documents.items())
        for collection in _COLLECTION_KEYS[repository]
    }


def build_plan(*, community_path: Path, sf_chat_path: Path | None = None) -> Dict[str, Any]:
    documents = {"community": _read_document(community_path, "community")}
    sources = {"community": str(community_path.expanduser().resolve())}
    if sf_chat_path is not None:
        documents["sf_chat"] = _read_document(sf_chat_path, "sf_chat")
        sources["sf_chat"] = str(sf_chat_path.expanduser().resolve())
    counts = validate_documents(documents)
    source_sha256 = {repository: _sha(document) for repository, document in documents.items()}
    payload = {
        "plan_version": PLAN_VERSION,
        "documents": documents,
        "source_sha256": source_sha256,
        "counts": counts,
    }
    return {**payload, "sources": sources, "plan_sha256": _sha(payload)}


def plan_summary(plan: Mapping[str, Any]) -> Dict[str, Any]:
    payload = {key: plan[key] for key in ("plan_version", "documents", "source_sha256", "counts")}
    expected = _sha(payload)
    if expected != str(plan.get("plan_sha256") or ""):
        raise StorageConflictError("Community migration plan checksum mismatch.")
    return {
        "dry_run": True,
        "plan_version": int(plan.get("plan_version") or 0),
        "plan_sha256": expected,
        "source_sha256": dict(plan.get("source_sha256") or {}),
        "counts": dict(plan.get("counts") or {}),
        "repositories": sorted((plan.get("documents") or {}).keys()),
    }


def backup_sources(plan: Mapping[str, Any], backup_dir: Path) -> Dict[str, Any]:
    summary = plan_summary(plan)
    destination = backup_dir.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for repository, source_text in sorted((plan.get("sources") or {}).items()):
        source = Path(str(source_text)).resolve()
        expected = str((plan.get("source_sha256") or {}).get(repository) or "")
        if _sha(_read_document(source, repository)) != expected:
            raise StorageConflictError("Community migration source changed after planning.")
        target = destination / f"{repository}-{expected[:16]}.json"
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise StorageConflictError("Backup target already contains different bytes.")
        if not target.exists():
            shutil.copy2(source, target)
        files.append({"repository": repository, "path": str(target), "sha256": expected})
    manifest = {
        "format": "stratforge-community-backup-v1",
        "plan_sha256": summary["plan_sha256"],
        "files": files,
    }
    manifest_path = destination / f"manifest-{summary['plan_sha256'][:16]}.json"
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != rendered:
        raise StorageConflictError("Backup manifest already contains different data.")
    if not manifest_path.exists():
        manifest_path.write_text(rendered, encoding="utf-8")
    return {**manifest, "manifest_path": str(manifest_path)}


def _merge_document(repository: str, existing: Mapping[str, Any], incoming: Mapping[str, Any],
                    plan_sha256: str) -> Dict[str, Any]:
    merged = copy.deepcopy(dict(existing)) if existing else {"version": incoming.get("version", 1)}
    for collection, keys in _COLLECTION_KEYS[repository].items():
        current = [copy.deepcopy(dict(row)) for row in merged.get(collection, []) if isinstance(row, Mapping)]
        by_identity = {_identity(row, keys, f"{repository}.{collection}"): row for row in current}
        for row in incoming.get(collection, []):
            identity = _identity(row, keys, f"{repository}.{collection}")
            prior = by_identity.get(identity)
            if prior is not None and _canonical(prior) != _canonical(row):
                raise StorageConflictError(f"Conflicting {repository}.{collection} row.")
            if prior is None:
                copied = copy.deepcopy(dict(row))
                current.append(copied)
                by_identity[identity] = copied
        merged[collection] = current
    imports = [dict(row) for row in merged.get("migration_history", []) if isinstance(row, Mapping)]
    marker = {"kind": "community_sf_chat_import", "plan_sha256": plan_sha256}
    if marker not in imports:
        imports.append(marker)
    merged["migration_history"] = imports
    return merged


def apply_plan(client: PostgresClient, plan: Mapping[str, Any], *, confirm_sha256: str) -> Dict[str, Any]:
    summary = plan_summary(plan)
    if str(confirm_sha256 or "") != summary["plan_sha256"]:
        raise StorageConstraintError("Community migration checksum confirmation mismatch.")
    documents = dict(plan.get("documents") or {})
    repository = DocumentRepository(client)
    revisions: Dict[str, int] = {}
    changed: Dict[str, bool] = {}
    with client.transaction(Scope.global_service_scope()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(7838146202603)")
        for name in ("community", "sf_chat"):
            incoming = documents.get(name)
            if not isinstance(incoming, Mapping):
                continue
            row = conn.execute(
                "SELECT revision,document FROM sf_repository_documents WHERE repository=%s FOR UPDATE",
                (name,),
            ).fetchone()
            current_revision = int(row["revision"]) if row else 0
            current_document = dict(row["document"]) if row else {}
            merged = _merge_document(name, current_document, incoming, summary["plan_sha256"])
            if row and _canonical(current_document) == _canonical(merged):
                revisions[name] = current_revision
                changed[name] = False
                continue
            revision = current_revision + 1
            conn.execute(
                """
                INSERT INTO sf_repository_documents(repository,revision,document,updated_at)
                VALUES(%s,%s,%s,clock_timestamp())
                ON CONFLICT(repository) DO UPDATE SET revision=EXCLUDED.revision,
                  document=EXCLUDED.document,updated_at=clock_timestamp()
                """,
                (name, revision, _jsonb(merged)),
            )
            repository._sync_mirrors(conn, name, merged)
            revisions[name] = revision
            changed[name] = True
    return {
        **summary, "dry_run": False, "applied": any(changed.values()),
        "changed": changed, "document_revisions": revisions,
    }


def _url_from_env(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise StorageConstraintError(f"Database URL environment variable is empty: {name}")
    return value


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--community", required=True, type=Path)
    parser.add_argument("--sf-chat", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--url-env", default="STRATFORGE_DATABASE_URL")
    parser.add_argument("--allow-local-test", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-plan-sha256", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        plan = build_plan(community_path=args.community, sf_chat_path=args.sf_chat)
        if not args.apply:
            print(json.dumps(plan_summary(plan), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.backup_dir is None:
            raise StorageConstraintError("--backup-dir is mandatory for apply.")
        backup = backup_sources(plan, args.backup_dir)
        client = PostgresClient(
            _url_from_env(args.url_env), production=not args.allow_local_test,
        )
        result = apply_plan(client, plan, confirm_sha256=args.confirm_plan_sha256)
        result["backup_manifest"] = backup["manifest_path"]
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (StorageConstraintError, StorageConflictError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
