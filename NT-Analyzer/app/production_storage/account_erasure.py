"""PostgreSQL account erasure matching the Local lifecycle contract.

Only authenticated account_lifecycle / users.manage callers may invoke this
repository. The first transaction freezes authority and live model sharing;
the second removes exact private relational/document rows atomically. A failure
after freeze leaves a blocked, retryable account. File payload cleanup is
driven by durable PostgreSQL object references, never a guessed data root.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .core import DocumentRepository, Scope, StorageError, _jsonb, _uuid, get_client

_REASONS = frozenset({"self_requested", "owner_requested"})
_DOC_LOCK_ORDER = ("auth", "community", "connectors", "entitlements", "sf_chat", "workspaces")
_DOC_SYNC_ORDER = ("sf_chat", "community", "connectors", "entitlements", "workspaces", "auth")
_UUID_FIELDS = ("user_uuid", "owner_user_uuid", "legacy_user_uuid", "from_user_uuid",
                "to_user_uuid", "created_by_user_uuid")
_ID_FIELDS = ("user_id", "legacy_user_id", "owner_user_id", "from_user_id",
              "to_user_id", "created_by_user_id")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
_SAFE_FILE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _deny(message: str, status: int, code: str = "account_delete_failed"):
    from ..account_auth import AccountAuthError
    raise AccountAuthError(message, status, code=code)


def _matches(row: Mapping[str, Any], uid: int, canonical: str) -> bool:
    if not isinstance(row, Mapping):
        return False
    if any(str(row.get(key) or "") == canonical for key in _UUID_FIELDS):
        return True
    return any(str(row.get(key) or "") == str(uid) for key in _ID_FIELDS)


def _defaults() -> dict[str, dict[str, Any]]:
    from .. import account_auth, community, connector_protocol, sf_chat, subscriptions, workspaces
    return {
        "auth": account_auth._default_doc(),
        "community": community._empty_doc(),
        "connectors": connector_protocol._default_doc(),
        "entitlements": subscriptions._default_doc(),
        "sf_chat": sf_chat._empty_doc(),
        "workspaces": workspaces._default_doc(),
    }


def _locked_documents(conn, client) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    defaults = _defaults()
    docs, revisions = {}, {}
    # A table lock prevents a concurrent first insert for an absent document;
    # ordinary writers take ROW EXCLUSIVE and therefore serialize here.
    conn.execute("LOCK TABLE sf_repository_documents IN SHARE ROW EXCLUSIVE MODE")
    rows = conn.execute("SELECT repository,revision,document FROM sf_repository_documents "
                        "WHERE repository=ANY(%s) ORDER BY repository FOR UPDATE",
                        (list(_DOC_LOCK_ORDER),)).fetchall()
    indexed = {str(row["repository"]): row for row in rows}
    for name in _DOC_LOCK_ORDER:
        row = indexed.get(name)
        docs[name] = copy.deepcopy(dict(row["document"]) if row else defaults[name])
        revisions[name] = int(row["revision"]) if row else 0
    DocumentRepository(client)._reconcile_auth_document(conn, docs["auth"])
    return docs, revisions


def _write_document(conn, client, name: str, doc: Mapping[str, Any], revision: int) -> None:
    next_revision = revision + 1
    conn.execute("""INSERT INTO sf_repository_documents(repository,revision,document,updated_at)
        VALUES(%s,%s,%s,clock_timestamp()) ON CONFLICT(repository) DO UPDATE SET
        revision=EXCLUDED.revision,document=EXCLUDED.document,updated_at=clock_timestamp()""",
        (name, next_revision, _jsonb(dict(doc))))
    DocumentRepository(client)._sync_mirrors(conn, name, dict(doc))


def _identity(docs: Mapping[str, Mapping[str, Any]], uid: int, *, retry: bool) -> tuple[dict[str, Any], str, set[str], set[str]]:
    from .. import account_auth
    user = next((row for row in docs["auth"].get("users", [])
                 if isinstance(row, dict) and str(row.get("user_id") or "") == str(uid)), None)
    if user is None:
        _deny("Пользователь не найден.", 404, "account_not_found")
    if user.get("is_owner") or user.get("is_service_account") or str(user.get("role") or "").lower() == "service":
        _deny("Этот системный аккаунт нельзя удалить.", 403, "protected_account")
    if user.get("status") != "active" and not (retry and user.get("deletion_pending")):
        _deny("Аккаунт не активен.", 403, "account_inactive")
    canonical = account_auth._user_uuid(user)
    if not canonical:
        _deny("У аккаунта нет канонической identity.", 409, "identity_missing")
    workspace_doc = docs["workspaces"]
    owned = {str(row.get("workspace_id") or "") for row in workspace_doc.get("workspaces", [])
             if isinstance(row, dict) and (str(row.get("owner_user_uuid") or "") == canonical
             or str(row.get("owner_user_id") or "") == str(uid))}
    memberships = {str(row.get("workspace_id") or "") for row in workspace_doc.get("memberships", [])
                   if isinstance(row, dict) and _matches(row, uid, canonical)}
    for workspace in owned:
        others = [row for row in workspace_doc.get("memberships", [])
                  if isinstance(row, dict) and str(row.get("workspace_id") or "") == workspace
                  and not row.get("revoked_at_utc") and not _matches(row, uid, canonical)]
        if others:
            _deny("Сначала передайте рабочую область с другими участниками.", 409, "workspace_shared")
    return user, canonical, owned, memberships | owned


def _fingerprint(user: Mapping[str, Any], canonical: str) -> str:
    # Domain-separated HMAC from the existing environment-specific external
    # server key. Neither key nor plaintext identity enters PostgreSQL/logs.
    from .. import platform_secrets
    try:
        key = base64.b64decode(platform_secrets.get("STRATFORGE_AGENT_WORLD_CREDENTIAL_KEY"), validate=True)
    except Exception:
        _deny("Серверный ключ записи удаления недоступен.", 503, "erasure_key_unavailable")
    if len(key) != 32:
        _deny("Серверный ключ записи удаления недоступен.", 503, "erasure_key_unavailable")
    identity = str(user.get("email") or canonical).strip().casefold()
    return hmac.new(key, b"stratforge.account.erasure.v1:" + identity.encode(), hashlib.sha256).hexdigest()


def _scope(conn, environment: str, workspace: str, canonical: str) -> None:
    conn.execute("SELECT set_config('stratforge.service_scope','scoped',true)")
    conn.execute("SELECT set_config('stratforge.workspace_id',%s,true)", (workspace,))
    conn.execute("SELECT set_config('stratforge.aw_environment',%s,true)", (environment,))
    conn.execute("SELECT set_config('stratforge.aw_user_uuid',%s,true)", (canonical,))


def _global(conn) -> None:
    conn.execute("SELECT set_config('stratforge.service_scope','global',true)")
    conn.execute("SELECT set_config('stratforge.workspace_id','',true)")
    conn.execute("SELECT set_config('stratforge.aw_user_uuid','',true)")


def _check_schema_and_role(conn) -> None:
    role = conn.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
    ready = conn.execute("SELECT to_regclass('sf_deleted_accounts') IS NOT NULL AS ready").fetchone()
    if not role or role["rolsuper"] or role["rolbypassrls"] or not ready["ready"]:
        _deny("Безопасный relational-erasure backend недоступен.", 503, "erasure_backend_unavailable")


def _assert_idle(conn, uid: int, owned: set[str]) -> None:
    active_jobs = conn.execute("SELECT 1 FROM sf_jobs WHERE user_id=%s "
                               "AND status IN ('queued','leased','running','review') LIMIT 1", (uid,)).fetchone()
    active_commands = conn.execute("SELECT 1 FROM sf_commands WHERE user_id=%s "
                                   "AND status IN ('queued','leased','running','review') LIMIT 1", (uid,)).fetchone()
    active_leases = conn.execute("SELECT 1 FROM sf_ninjatrader_resource_leases "
                                 "WHERE requested_by_legacy_id=%s AND state IN ('queued','active') "
                                 "LIMIT 1", (uid,)).fetchone()
    if active_jobs or active_commands or active_leases:
        _deny("Сначала дождитесь завершения активной работы.", 409, "account_work_active")
    if owned:
        for table, column in (("sf_jobs", "user_id"), ("sf_commands", "user_id"),
                              ("sf_artifacts", "user_id"),
                              ("sf_market_data_subscriptions", "requested_by_user_id")):
            foreign = conn.execute(f"SELECT 1 FROM {table} WHERE workspace_id=ANY(%s) "
                                   f"AND {column}<>%s LIMIT 1", (sorted(owned), uid)).fetchone()
            if foreign:
                _deny("Рабочая область содержит данные другого пользователя.", 409, "workspace_shared_data")


def _transform(docs: dict[str, dict[str, Any]], uid: int, canonical: str,
               owned: set[str]) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str, str | None]]]:
    """Pure document plan; unrelated users/workspaces remain byte-for-byte rows."""
    objects: list[tuple[str, str, str | None]] = []
    social = docs["community"]
    profiles = {str(row.get("profile_id") or "") for row in social.get("profiles", [])
                if isinstance(row, dict) and _matches(row, uid, canonical)}
    posts = {str(row.get("post_id") or "") for row in social.get("posts", [])
             if isinstance(row, dict) and str(row.get("author_profile_id") or "") in profiles}
    for row in social.get("posts", []):
        if not isinstance(row, dict) or str(row.get("post_id") or "") not in posts:
            continue
        workspace = str(row.get("workspace_id") or "shared")
        for attachment in row.get("attachments") or []:
            name = str((attachment or {}).get("stored_name") or "")
            if _SAFE_ID.fullmatch(workspace) and _SAFE_FILE.fullmatch(name):
                objects.append(("community", workspace + "/" + name, None))
            elif name:
                _deny("Небезопасная ссылка на вложение.", 503, "erasure_object_invalid")
    for key, rows in list(social.items()):
        if isinstance(rows, list):
            social[key] = [row for row in rows if not (isinstance(row, dict) and (
                _matches(row, uid, canonical)
                or any(str(row.get(field) or "") in profiles for field in (
                    "profile_id", "author_profile_id", "from_profile_id", "to_profile_id",
                    "follower_profile_id", "target_profile_id", "owner_profile_id"))
                or str(row.get("post_id") or "") in posts))]

    chat = docs["sf_chat"]
    conversations = {str(row.get("conversation_id") or "") for row in chat.get("conversations", [])
                     if isinstance(row, dict) and profiles.intersection(row.get("participant_profile_ids") or [])}
    for key in ("conversations", "messages", "reads"):
        chat[key] = [row for row in chat.get(key, []) if not (isinstance(row, dict)
                     and str(row.get("conversation_id") or "") in conversations)]
    for conversation in conversations:
        if not _SAFE_ID.fullmatch(conversation):
            _deny("Небезопасный идентификатор диалога.", 503, "erasure_object_invalid")
        objects.append(("sf_chat", conversation, None))

    entitlement = docs["entitlements"]
    for key, rows in list(entitlement.items()):
        if isinstance(rows, list):
            entitlement[key] = [row for row in rows if not (isinstance(row, dict)
                                and _matches(row, uid, canonical))]
    for key in (str(uid), canonical):
        if isinstance(entitlement.get("plan_overrides"), dict):
            entitlement["plan_overrides"].pop(key, None)

    connectors = docs["connectors"]
    for key, rows in list(connectors.items()):
        if isinstance(rows, list):
            connectors[key] = [row for row in rows if not (isinstance(row, dict) and (
                _matches(row, uid, canonical)
                or str(row.get("workspace_id") or "") in owned))]

    workspace_doc = docs["workspaces"]
    workspace_doc["workspaces"] = [row for row in workspace_doc.get("workspaces", [])
                                   if str(row.get("workspace_id") or "") not in owned]
    for key in ("memberships", "connections", "pairings"):
        workspace_doc[key] = [row for row in workspace_doc.get(key, [])
                              if not (isinstance(row, dict) and (
                                  _matches(row, uid, canonical)
                                  or str(row.get("workspace_id") or "") in owned))]
    for key in (str(uid), canonical):
        for mapping in ("active_workspaces", "active_workspaces_by_uuid"):
            if isinstance(workspace_doc.get(mapping), dict):
                workspace_doc[mapping].pop(key, None)

    auth = docs["auth"]
    for key, rows in list(auth.items()):
        if key == "identity_history" and isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and _matches(row, uid, canonical) and row.get("state") in {"active", "pending"}:
                    row["state"], row["valid_to"], row["replacement_reason"] = "revoked", _now(), "account_deleted"
            continue
        if isinstance(rows, list):
            auth[key] = [row for row in rows if not (isinstance(row, dict) and _matches(row, uid, canonical))]
    return docs, objects


def _client():
    from .. import storage_router
    if not storage_router.production_enabled():
        _deny("Relational-erasure backend доступен только на сервере.", 503, "erasure_backend_unavailable")
    return get_client(production=True)


def preflight(user: Mapping[str, Any]) -> dict[str, Any]:
    from .. import account_auth, workspaces
    if not user or user.get("is_owner") or user.get("is_service_account"):
        _deny("Этот системный аккаунт нельзя удалить.", 403, "protected_account")
    canonical = account_auth._user_uuid(dict(user))
    report = workspaces.user_footprint(canonical, user.get("user_id"))
    if report["shared_workspaces"]:
        _deny("Сначала передайте рабочие области с другими участниками.", 409, "workspace_shared")
    with _client().transaction(Scope.global_service_scope(), read_only=True) as conn:
        _check_schema_and_role(conn)
        _assert_idle(conn, int(user["user_id"]), set(report["owned_workspaces"]))
    return report


def _freeze(client, uid: int, *, reason: str) -> None:
    from .. import runtime_env
    with client.transaction(Scope.global_service_scope()) as conn:
        _check_schema_and_role(conn)
        docs, revisions = _locked_documents(conn, client)
        user, canonical, owned, memberships = _identity(docs, uid, retry=True)
        _assert_idle(conn, uid, owned)
        if user.get("deletion_pending"):
            return
        user.setdefault("deletion_original_status", user.get("status"))
        user["status"] = "blocked"
        user["permissions"] = {}
        user["deletion_pending"] = True
        for row in docs["auth"].get("sessions", []):
            if isinstance(row, dict) and _matches(row, uid, canonical):
                row["revoked"] = True
        _write_document(conn, client, "auth", docs["auth"], revisions["auth"])
        environment = runtime_env.deployment_environment()
        conn.execute("SELECT set_config('stratforge.aw_environment',%s,true)", (environment,))
        conn.execute("SELECT set_config('stratforge.aw_user_uuid',%s,true)", (canonical,))
        share_rows = conn.execute("SELECT DISTINCT owner_workspace_id FROM sf_aw_model_shares "
                                  "WHERE environment=%s AND owner_user_uuid=%s",
                                  (environment, canonical)).fetchall()
        memberships.update(str(row["owner_workspace_id"]) for row in share_rows)
        for workspace in sorted(memberships):
            _scope(conn, environment, workspace, canonical)
            conn.execute("UPDATE sf_aw_model_shares SET shared=false,revision=revision+1,"
                         "updated_at=clock_timestamp() WHERE environment=%s AND "
                         "owner_workspace_id=%s AND owner_user_uuid=%s AND shared",
                         (environment, workspace, canonical))
        _global(conn)


def _erase_agent_world(conn, environment: str, canonical: str, workspaces: set[str]) -> None:
    from ..ai_control_center.sqlite_repository import _canonical
    # Historical shared-model calls may have been made in a workspace the
    # caller has since left. Retain the receipt, but remove their display name
    # under the exact original caller scope before private-record deletion.
    conn.execute("SELECT set_config('stratforge.aw_environment',%s,true)", (environment,))
    conn.execute("SELECT set_config('stratforge.aw_user_uuid',%s,true)", (canonical,))
    call_workspaces = conn.execute("SELECT DISTINCT caller_workspace_id FROM sf_aw_model_calls "
                                   "WHERE environment=%s AND caller_user_uuid=%s",
                                   (environment, canonical)).fetchall()
    for row in call_workspaces:
        workspace = str(row["caller_workspace_id"])
        _scope(conn, environment, workspace, canonical)
        conn.execute("UPDATE sf_aw_model_calls SET caller_name=%s WHERE environment=%s "
                     "AND caller_workspace_id=%s AND caller_user_uuid=%s",
                     ("Удалённый пользователь", environment, workspace, canonical))
    for workspace in sorted(workspaces):
        _scope(conn, environment, workspace, canonical)
        lock = int.from_bytes(hashlib.sha256(_canonical(["sf-aw-v1", environment, workspace])).digest()[:8],
                              "big", signed=True)
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
        conn.execute("DELETE FROM sf_aw_credentials WHERE environment=%s AND workspace_id=%s "
                     "AND owner_uuid=%s", (environment, workspace, canonical))
        conn.execute("UPDATE sf_aw_model_shares SET shared=false,label='Deleted model',"
                     "provider='deleted',model_key='deleted',revision=revision+1,"
                     "updated_at=clock_timestamp() WHERE environment=%s AND owner_workspace_id=%s "
                     "AND owner_user_uuid=%s AND (shared OR label<>'Deleted model')",
                     (environment, workspace, canonical))
        conn.execute("DELETE FROM sf_aw_memory_grant_anchors WHERE environment=%s AND workspace_id=%s "
                     "AND owner_uuid=%s", (environment, workspace, canonical))
        conn.execute("DELETE FROM sf_aw_memory_grants WHERE environment=%s AND workspace_id=%s "
                     "AND owner_uuid=%s", (environment, workspace, canonical))
        for table in ("sf_aw_outbox", "sf_aw_inbox", "sf_aw_mutations"):
            conn.execute(f"DELETE FROM {table} WHERE environment=%s AND workspace_id=%s "
                         "AND user_uuid=%s", (environment, workspace, canonical))
        conn.execute("DELETE FROM sf_aw_events WHERE environment=%s AND workspace_id=%s "
                     "AND user_uuid=%s", (environment, workspace, canonical))
        conn.execute("DELETE FROM sf_aw_records WHERE environment=%s AND workspace_id=%s "
                     "AND owner_uuid=%s", (environment, workspace, canonical))
        conn.execute("DELETE FROM sf_aw_revisions WHERE environment=%s AND workspace_id=%s "
                     "AND owner_uuid=%s", (environment, workspace, canonical))
        conn.execute("DELETE FROM sf_aw_artifacts WHERE environment=%s AND workspace_id=%s "
                     "AND owner_uuid=%s", (environment, workspace, canonical))
    _global(conn)


def _usage_anonymize(conn, uid: int, canonical: str, fingerprint: str) -> None:
    conn.execute("""UPDATE sf_ai_usage_events SET user_id=NULL,user_uuid=NULL,workspace_id=NULL,
        deleted_user_fingerprint=%s,document='{"user_name":"Удалённый пользователь","deleted_user":true}'::jsonb
        WHERE user_id=%s OR user_uuid=%s""", (fingerprint, uid, canonical))


def _identity_history_revoke(conn, canonical: str) -> None:
    conn.execute("""UPDATE sf_identity_history SET state='revoked',valid_to=clock_timestamp(),
        replacement_reason='account_deleted' WHERE user_uuid=%s AND state IN ('active','pending')""",
        (canonical,))


def _erase_private_documents(conn, owned: set[str]) -> None:
    # Document revisions are explicitly dependent on their exact parent ID;
    # deleting private workspace/strategy parents invokes that declared FK.
    if owned:
        conn.execute("DELETE FROM sf_documents WHERE scope_type IN ('workspace','strategy') "
                     "AND workspace_id=ANY(%s)", (sorted(owned),))


def _collect_objects(conn, uid: int, owned: set[str], planned):
    objects = list(planned)
    rows = conn.execute("SELECT object_key,sha256 FROM sf_artifacts WHERE user_id=%s "
                        "OR workspace_id=ANY(%s)", (uid, sorted(owned))).fetchall()
    for row in rows:
        objects.append(("artifact", str(row["object_key"]), str(row["sha256"])))
    from .. import account_auth
    avatar_root = account_auth._avatars_dir()
    for path in avatar_root.glob(f"{uid}.*"):
        if path.is_file() and not path.is_symlink() and _SAFE_FILE.fullmatch(path.name):
            objects.append(("avatar", path.name, None))
    for workspace in sorted(owned):
        if not _SAFE_ID.fullmatch(workspace):
            _deny("Небезопасная рабочая область удаления.", 503, "erasure_object_invalid")
        objects.append(("tenant", workspace, None))
    # The legacy orchestrator still has a per-user file-backed conversation
    # scope alongside PostgreSQL Agent World. It is not a relational mirror.
    # Record only exact u<legacy-id>__<workspace> directories for this user;
    # cleanup happens after the relational commit and is retryable.
    from ..ai_lab import chief_agent
    legacy_root = chief_agent._conversations_index_path().parent / "orchestrator_scopes"
    for path in legacy_root.glob(f"u{uid}__*"):
        if path.is_symlink() or not path.is_dir() or not _SAFE_ID.fullmatch(path.name):
            _deny("Небезопасный scope старого AI-чата.", 503, "erasure_object_invalid")
        objects.append(("orchestrator_scope", path.name, None))
    return sorted(set(objects), key=lambda row: (row[0], row[1], row[2] or ""))


def erase(uid: int, *, reason: str) -> dict[str, Any]:
    from .. import runtime_env
    if reason not in _REASONS or int(uid) <= 0:
        _deny("Некорректное удаление аккаунта.", 400)
    client = _client()
    try:
        with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
            _check_schema_and_role(conn)
            receipt = conn.execute("SELECT user_uuid FROM sf_deleted_accounts WHERE legacy_user_id=%s",
                                   (int(uid),)).fetchone()
        if receipt:
            cleanup_files(str(receipt["user_uuid"]))
            return {"ok": True, "deleted": True, "account_type": "real"}
        _freeze(client, int(uid), reason=reason)
        with client.transaction(Scope.global_service_scope()) as conn:
            _check_schema_and_role(conn)
            docs, revisions = _locked_documents(conn, client)
            user, canonical, owned, memberships = _identity(docs, int(uid), retry=True)
            if not user.get("deletion_pending"):
                _deny("Удаление не прошло стадию заморозки.", 503, "erasure_not_frozen")
            _assert_idle(conn, int(uid), owned)
            original = dict(user)
            fingerprint = _fingerprint(original, canonical)
            environment = runtime_env.deployment_environment()
            conn.execute("SELECT set_config('stratforge.aw_environment',%s,true)", (environment,))
            conn.execute("SELECT set_config('stratforge.aw_user_uuid',%s,true)", (canonical,))
            share_rows = conn.execute("SELECT DISTINCT owner_workspace_id FROM sf_aw_model_shares "
                                      "WHERE environment=%s AND owner_user_uuid=%s",
                                      (environment, canonical)).fetchall()
            memberships.update(str(row["owner_workspace_id"]) for row in share_rows)
            _global(conn)
            _identity_history_revoke(conn, canonical)
            _usage_anonymize(conn, int(uid), canonical, fingerprint)
            _erase_agent_world(conn, environment, canonical, memberships)
            _erase_private_documents(conn, owned)
            docs, objects = _transform(docs, int(uid), canonical, owned)
            objects = _collect_objects(conn, int(uid), owned, objects)
            conn.execute("""INSERT INTO sf_deleted_accounts(user_uuid,legacy_user_id,
                identifier_fingerprint,created_at_utc,reason,security_flags)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(user_uuid) DO NOTHING""",
                (canonical, int(uid), fingerprint, original.get("created_at_utc"), reason,
                 _jsonb({"previously_blocked": original.get("deletion_original_status", original.get("status")) == "blocked"})))
            for category, object_key, digest in objects:
                conn.execute("""INSERT INTO sf_account_erasure_objects(user_uuid,category,object_key,sha256)
                    VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (canonical, category, object_key, digest))
            for name in _DOC_SYNC_ORDER:
                _write_document(conn, client, name, docs[name], revisions[name])
        cleanup_files(canonical)
        return {"ok": True, "deleted": True, "account_type": "real"}
    except StorageError:
        _deny("Серверное хранилище удаления недоступно.", 503, "erasure_storage_unavailable")


def _safe_target(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts or ":" in relative:
        _deny("Небезопасная ссылка на объект удаления.", 503, "erasure_object_invalid")
    root = root.resolve()
    lexical = root / relative
    if any(part.is_symlink() for part in (lexical, *lexical.parents) if part != root and part.is_relative_to(root)):
        _deny("Небезопасная ссылка на объект удаления.", 503, "erasure_object_invalid")
    target = lexical.resolve()
    if target == root or not target.is_relative_to(root):
        _deny("Небезопасная ссылка на объект удаления.", 503, "erasure_object_invalid")
    return target


def cleanup_files(canonical: str) -> None:
    from .. import account_auth, community, runtime_env, sf_chat
    from ..ai_lab import chief_agent
    from .artifacts import FileArtifactStore
    client = _client()
    with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
        rows = conn.execute("SELECT category,object_key,sha256 FROM sf_account_erasure_objects "
                            "WHERE user_uuid=%s AND completed_at IS NULL ORDER BY category,object_key",
                            (canonical,)).fetchall()
    roots = {"artifact": FileArtifactStore(client, production=True).root,
             "sf_chat": sf_chat._uploads_root(),
             "community": community._attachment_dir("").parent,
             "avatar": account_auth._avatars_dir(),
             "tenant": runtime_env.data_path("tenants"),
             "orchestrator_scope": chief_agent._conversations_index_path().parent / "orchestrator_scopes"}
    for row in rows:
        category, object_key = str(row["category"]), str(row["object_key"])
        target = _safe_target(roots[category], object_key)
        if category in {"sf_chat", "tenant", "orchestrator_scope"}:
            if not _SAFE_ID.fullmatch(object_key):
                _deny("Небезопасный диалог для удаления.", 503, "erasure_object_invalid")
            if target.exists():
                import shutil
                shutil.rmtree(target)
        else:
            if target.exists():
                if not target.is_file() or target.is_symlink():
                    _deny("Объект удаления изменился.", 503, "erasure_object_invalid")
                digest = row.get("sha256")
                if digest and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    _deny("Контрольная сумма объекта удаления не совпала.", 503, "erasure_object_changed")
                target.unlink()
        with client.transaction(Scope.global_service_scope()) as conn:
            conn.execute("UPDATE sf_account_erasure_objects SET completed_at=clock_timestamp() "
                         "WHERE user_uuid=%s AND category=%s AND object_key=%s AND completed_at IS NULL",
                         (canonical, category, object_key))


def deleted_ids() -> set[str]:
    with _client().transaction(Scope.global_service_scope(), read_only=True) as conn:
        return {str(row["user_uuid"]) for row in conn.execute("SELECT user_uuid FROM sf_deleted_accounts")}


def deleted_legacy_ids() -> set[int]:
    with _client().transaction(Scope.global_service_scope(), read_only=True) as conn:
        return {int(row["legacy_user_id"]) for row in conn.execute("SELECT legacy_user_id FROM sf_deleted_accounts")}


def registry_rows() -> list[dict[str, Any]]:
    with _client().transaction(Scope.global_service_scope(), read_only=True) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM sf_deleted_accounts "
                                             "ORDER BY deleted_at_utc DESC LIMIT 200")]
