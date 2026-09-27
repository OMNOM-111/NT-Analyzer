"""Account erasure and minimal, append-only deletion receipts.

Local and disposable Preview use the same erasure plan. Live-environment
storage is deliberately refused until its relational erasure adapter exists.
No owner credentials or private content belong in the deletion registry.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
from contextlib import closing

from . import account_auth, runtime_env, secure_store, subscriptions, workspaces

_LOCK = threading.RLock()
_REASONS = {"self_requested", "owner_requested", "preview_exit", "preview_reset", "preview_replaced"}


def _registry_path():
    return runtime_env.data_path("audit", "deleted_accounts.sqlite3")


def record_deletion(user, reason, *, preview=False):
    """Idempotent insert only. Inputs are server-owned account rows."""
    from . import preview_shared_models
    if preview_shared_models.transport_enabled():
        return preview_shared_models.request("/account-deleted", {
            "user": {key: user.get(key) for key in ("user_id", "user_uuid", "email", "created_at_utc")},
            "reason": reason,
        })
    uid = str(account_auth._user_uuid(user))
    if not uid or reason not in _REASONS:
        raise account_auth.AccountAuthError("Некорректная запись удаления.", 400)
    with _LOCK:
        key = secure_store.get_secret("account_deletion_fingerprint")
        if not key:
            key = secrets.token_hex(32)
            secure_store.set_secret("account_deletion_fingerprint", key)
        identity = str(user.get("email") or uid).strip().casefold()
        fingerprint = hmac.new(key.encode(), identity.encode(), hashlib.sha256).hexdigest()
        path = _registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(path))) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS deleted_accounts (
                user_uuid TEXT PRIMARY KEY, legacy_user_id INTEGER, identifier_fingerprint TEXT NOT NULL,
                created_at_utc TEXT NOT NULL, deleted_at_utc TEXT NOT NULL, reason TEXT NOT NULL,
                account_type TEXT NOT NULL, security_flags TEXT NOT NULL)""")
            if db.execute("PRAGMA user_version").fetchone()[0] < 2:
                # The first Local Preview bridge observed the forced freeze
                # instead of the pre-deletion status. A self-confirmed removal
                # necessarily came from an active session. Repair only those
                # synthetic receipts; do not infer real-account security flags.
                db.execute("UPDATE deleted_accounts SET security_flags=? WHERE account_type='test-preview' "
                           "AND reason='self_requested' AND security_flags=?",
                           (json.dumps({"previously_blocked": False}), json.dumps({"previously_blocked": True})))
                db.execute("PRAGMA user_version=2")
            db.execute("""INSERT OR IGNORE INTO deleted_accounts VALUES (?,?,?,?,?,?,?,?)""",
                (uid, int(user.get("user_id") or 0), fingerprint, str(user.get("created_at_utc") or ""),
                 account_auth._now_iso(), reason, "test-preview" if preview else "real",
                 json.dumps({"previously_blocked": user.get("deletion_original_status", user.get("status")) == "blocked"})))
    # A late usage receipt must also resolve the deleted label at read time.
    from .ai_control_center import model_sharing
    from .ai_lab import agent_registry
    agent_registry.anonymize_user_usage(int(user.get("user_id") or 0))
    if model_sharing._db_path().exists():
        with model_sharing._db() as db:
            db.execute("UPDATE calls SET caller_name=? WHERE caller_user_uuid=?", ("Удалённый пользователь", uid))
            db.execute("UPDATE shares SET shared=0, revision=revision+1 WHERE owner_user_uuid=?", (uid,))
    return {"ok": True, "deleted": True, "account_type": "test-preview" if preview else "real"}


def deleted_ids():
    path = _registry_path()
    if not path.exists():
        return set()
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return {row[0] for row in db.execute("SELECT user_uuid FROM deleted_accounts")}


def deleted_legacy_ids():
    path = _registry_path()
    if not path.exists():
        return set()
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return {row[0] for row in db.execute("SELECT legacy_user_id FROM deleted_accounts")}


def registry_rows():
    """Read-only projection for the already-authorized users.manage surface."""
    path = _registry_path()
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM deleted_accounts ORDER BY deleted_at_utc DESC LIMIT 200")]


def _matches(row, uid, canonical):
    if not isinstance(row, dict):
        return False
    return any(str(row.get(key) or "") == canonical for key in ("user_uuid", "owner_user_uuid", "legacy_user_uuid")) or any(
        str(row.get(key) or "") == str(uid) for key in ("user_id", "legacy_user_id", "owner_user_id"))


def _remove_tree(path, base):
    base = base.resolve()
    resolved = path.resolve()
    if resolved == base or not resolved.is_relative_to(base) or path.is_symlink():
        raise account_auth.AccountAuthError("Путь удаления не прошёл проверку.", 503)
    if path.exists():
        shutil.rmtree(path)


def _erase_agent_world(canonical, workspace_ids):
    from . import preview_sandbox
    paths = [runtime_env.data_path("ai_lab", "agent-world.sqlite3")]
    if preview_sandbox.enabled():
        paths.append(preview_sandbox.isolated_root() / "agent-world.sqlite3")
    for path in set(paths):
        if not path.exists():
            continue
        with closing(sqlite3.connect(str(path), timeout=30)) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA secure_delete=ON")
            # Collect the exact revisions first; remove FK dependants before
            # records/revisions. Never remove another workspace's rows by name.
            marks = ",".join("?" for _ in workspace_ids) or "NULL"
            where = f"environment='development' AND (owner_uuid=? OR workspace_id IN ({marks}))"
            values = [canonical, *workspace_ids]
            rows = db.execute(f"SELECT seq,kind,entity_id FROM aw_revisions WHERE {where}", values).fetchall()
            for _, kind, entity in rows:
                if kind == "provider_account":
                    secure_store.delete_secret("aw_provider." + entity)
            db.execute("CREATE TEMP TABLE erased_revisions (seq INTEGER PRIMARY KEY)")
            db.executemany("INSERT INTO erased_revisions VALUES (?)", [(row[0],) for row in rows])
            db.execute("CREATE TEMP TABLE erased_events AS SELECT event_id FROM aw_events WHERE "
                       "user_uuid=? OR EXISTS (SELECT 1 FROM aw_revisions r JOIN erased_revisions e ON r.seq=e.seq "
                       "WHERE r.environment=aw_events.environment AND r.workspace_id=aw_events.workspace_id "
                       "AND r.kind=aw_events.kind AND r.entity_id=aw_events.entity_id AND r.revision=aw_events.revision)", (canonical,))
            for table in ("aw_outbox", "aw_inbox", "aw_mutations"):
                db.execute(f"DELETE FROM {table} WHERE event_id IN (SELECT event_id FROM erased_events)")
            db.execute("DELETE FROM aw_events WHERE event_id IN (SELECT event_id FROM erased_events)")
            db.execute("DELETE FROM aw_records WHERE seq IN (SELECT seq FROM erased_revisions)")
            db.execute("DELETE FROM aw_revisions WHERE seq IN (SELECT seq FROM erased_revisions)")
            db.execute(f"DELETE FROM aw_artifacts WHERE {where}", values)
        with closing(sqlite3.connect(str(path), timeout=30)) as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _erase_social(uid, canonical):
    from . import community, sf_chat
    with community._LOCK:
        doc = community._load(include_preview=False)
        profiles = {row["profile_id"] for row in doc["profiles"] if _matches(row, uid, canonical)}
        posts = {row["post_id"] for row in doc["posts"] if row.get("author_profile_id") in profiles}
        for row in doc["posts"]:
            if row.get("post_id") not in posts:
                continue
            base = community._attachment_dir(str(row.get("workspace_id") or ""))
            for item in row.get("attachments") or []:
                name = str(item.get("stored_name") or "")
                path = base / name
                if name and path.resolve().parent == base.resolve():
                    path.unlink(missing_ok=True)
        for key, rows in list(doc.items()):
            if not isinstance(rows, list):
                continue
            doc[key] = [row for row in rows if not (_matches(row, uid, canonical)
                or any(row.get(field) in profiles for field in ("profile_id", "author_profile_id", "from_profile_id", "to_profile_id", "follower_profile_id", "target_profile_id", "owner_profile_id"))
                or row.get("post_id") in posts)]
        if profiles:
            community._save(doc)
    with sf_chat._LOCK:
        doc = sf_chat._load()
        conversations = {row["conversation_id"] for row in doc["conversations"]
                         if profiles.intersection(row.get("participant_profile_ids") or [])}
        if conversations:
            for key in ("conversations", "messages", "reads"):
                doc[key] = [row for row in doc[key] if row.get("conversation_id") not in conversations]
            sf_chat._save(doc)
            for cid in conversations:
                if re.fullmatch(r"[A-Za-z0-9_-]{1,96}", cid):
                    _remove_tree(sf_chat._uploads_root() / cid, sf_chat._uploads_root())


def _preflight(user):
    from . import storage_router
    if (not runtime_env.is_development() or storage_router.production_enabled()
            or os.environ.get("STRATFORGE_AGENT_WORLD_STORAGE", "sqlite").strip().lower() != "sqlite"):
        raise account_auth.AccountAuthError("Удаление доступно в Local; адаптер этого окружения ещё не принят.", 503)
    if not user or user.get("is_owner") or user.get("is_service_account"):
        raise account_auth.AccountAuthError("Этот системный аккаунт нельзя удалить.", 403)
    report = workspaces.user_footprint(account_auth._user_uuid(user), user["user_id"])
    if report["shared_workspaces"]:
        raise account_auth.AccountAuthError("Сначала передайте рабочие области с другими участниками.", 409, code="workspace_shared")
    return report


def _freeze(uid, automatic_preview):
    from . import preview_sandbox
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        user = account_auth._user(doc, uid)
        report = _preflight(user)
        canonical = account_auth._user_uuid(user)
        if automatic_preview and not (preview_sandbox.enabled() and user.get("is_preview_user")):
            raise account_auth.AccountAuthError("Автоудаление разрешено только disposable Preview.", 403)
        # Freeze authority before touching data. On an erasure failure the
        # blocked identity survives for a safe owner retry, never active access.
        original = dict(user)
        user.setdefault("deletion_original_status", user.get("status"))
        user["status"] = "blocked"
        user["permissions"] = {}
        user["deletion_pending"] = True
        for row in doc.get("sessions", []):
            if _matches(row, uid, canonical):
                row["revoked"] = True
        account_auth._write_doc(doc)
        return original, report, canonical


def erase(user_id, *, reason, automatic_preview=False):
    """Internal authorized primitive. Callers authenticate/confirm beforehand."""
    from .ai_lab import chief_agent
    uid = int(user_id)
    with _LOCK:
        original, report, canonical = _freeze(uid, automatic_preview)
        owned = report["owned_workspaces"]
        from .ai_control_center import model_sharing
        if model_sharing._db_path().exists():
            with model_sharing._db() as db:
                db.execute("UPDATE shares SET shared=0, revision=revision+1 WHERE owner_user_uuid=?", (canonical,))
        _erase_agent_world(canonical, owned)
        with chief_agent._LOCK:
            scopes = chief_agent._conversations_index_path().parent / "orchestrator_scopes"
            if scopes.exists():
                for path in scopes.glob(f"u{uid}__*"):
                    _remove_tree(path, scopes)
        _erase_social(uid, canonical)
        with subscriptions._LOCK:
            subscription_doc = subscriptions._read_doc()
            for key, rows in list(subscription_doc.items()):
                if isinstance(rows, list):
                    subscription_doc[key] = [row for row in rows if not _matches(row, uid, canonical)]
            subscriptions._write_doc(subscription_doc)
        for workspace in owned:
            _remove_tree(workspaces._tenant_root(workspace), runtime_env.data_path("tenants"))
        workspaces.purge_user(canonical, uid)
        # Persist receipt before removing the last identity; a failed receipt
        # leaves an explicitly blocked retryable account, not a silent loss.
        result = record_deletion(original, reason, preview=bool(original.get("is_preview_user")))
        with account_auth._LOCK:
            doc = account_auth._read_doc()
            for key, rows in list(doc.items()):
                if isinstance(rows, list):
                    doc[key] = [row for row in rows if not _matches(row, uid, canonical)]
            account_auth._write_doc(doc)
        for path in account_auth._avatars_dir().glob(f"{uid}.*"):
            path.unlink()
        return result


def start(user_id, session_id, *, provider="", ip=""):
    from . import security_devices
    with account_auth._LOCK:
        user = account_auth._user(account_auth._read_doc(), int(user_id))
        _preflight(user)
    if not session_id:
        raise account_auth.AccountAuthError("Войдите в аккаунт заново.", 401)
    return security_devices.create_challenge(user_id=user_id, purpose="account_delete",
                                             session_id=session_id, provider=provider, ip=ip)


def confirm(user_id, session_id, *, challenge_id, code, confirmation, ip=""):
    from . import security_devices
    if confirmation != "УДАЛИТЬ" or not session_id:
        raise account_auth.AccountAuthError("Введите УДАЛИТЬ и подтвердите личность кодом.", 400)
    with _LOCK:
        with account_auth._LOCK:
            doc = account_auth._read_doc()
            user = account_auth._user(doc, int(user_id))
            _preflight(user)
            security_devices._consume_and_persist(doc, uid=int(user_id), ip=ip,
                challenge_id=challenge_id, code=code, user_uuid=account_auth._user_uuid(user),
                purpose="account_delete", session_id=session_id)
            account_auth._write_doc(doc)
        return erase(user_id, reason="self_requested")


def erase_preview(reason):
    from . import preview_sandbox
    preview_sandbox.require_enabled()
    for user in list(account_auth._read_doc().get("users", [])):
        if user.get("is_preview_user") and not user.get("is_owner"):
            erase(user["user_id"], reason=reason, automatic_preview=True)


def preview_accounts(container, preview_id):
    """Read identities only from a parent-validated disposable container."""
    import base64
    path = container / "data" / "integrations" / "accounts.dpapi"
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw.startswith(account_auth._MAGIC):
        raise account_auth.AccountAuthError("Некорректное хранилище Preview.", 503)
    doc = json.loads(secure_store._unprotect(base64.b64decode(raw[len(account_auth._MAGIC):], validate=True)))
    return [user for user in doc.get("users", []) if user.get("is_preview_user")
            and not user.get("is_owner") and user.get("preview_sandbox_id") == preview_id]


def record_terminated_preview(container, preview_id):
    """Parent receipt fallback after terminating a disposable child process."""
    for user in preview_accounts(container, preview_id):
        record_deletion(user, "preview_replaced", preview=True)


def active_preview_identities():
    """Parent-only identity presence for historical Preview usage attribution."""
    from . import dev_preview
    if not runtime_env.is_development():
        return None
    active = dev_preview._ACTIVE_SANDBOX
    if not active or not dev_preview._process_alive(active):
        return set()
    container = dev_preview._validated_preview_container(active)
    if not container:
        return None  # Uncertain state is not proof of deletion.
    try:
        return {account_auth._user_uuid(user) for user in preview_accounts(container, active["preview_id"])}
    except (OSError, ValueError, account_auth.AccountAuthError):
        return None
