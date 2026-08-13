"""Workspace isolation and personal NinjaTrader connection registry."""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from . import runtime_env, secure_store


_MAGIC = b"STRATFORGE-WORKSPACES-DPAPI-1\n"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.RLock()
_DOC_CACHE_KEY: Optional[tuple[str, int, int]] = None
_DOC_CACHE_DOC: Optional[Dict[str, Any]] = None
PAIRING_TTL_SEC = 10 * 60
WORKSPACE_STORE_VERSION = 2
WORKSPACE_ROLES = {"owner", "admin", "operator", "viewer", "developer"}
WRITE_ROLES = {"owner", "admin", "operator", "developer"}
ENTITLEMENT_OK = {"promo_grant", "trial", "active"}


class WorkspaceError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


def _root() -> Path:
    return _PROJECT_ROOT


def _store_path() -> Path:
    return runtime_env.data_path("integrations", "workspaces.dpapi", project_root=_root())


def _audit_path() -> Path:
    return runtime_env.data_path("audit", "workspace-access.jsonl", project_root=_root())


def _tenant_root(workspace_id: str) -> Path:
    safe = _safe_workspace_id(workspace_id)
    return runtime_env.data_path("tenants", safe, project_root=_root())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_doc() -> Dict[str, Any]:
    return {
        "version": WORKSPACE_STORE_VERSION,
        "workspaces": [],
        "memberships": [],
        "active_workspaces": {},
        "active_workspaces_by_uuid": {},
        "connections": [],
        "pairings": [],
        "identity_schema": {"stage": "dual_write", "canonical_key": "user_uuid"},
    }


def _user_uuid_for_legacy_id(user_id: Any) -> str:
    try:
        from . import account_auth
        return account_auth.user_uuid_for_legacy_id(user_id)
    except Exception:
        return ""


def _backfill_user_uuid(row: Dict[str, Any], legacy_key: str, uuid_key: str) -> bool:
    user_uuid = _user_uuid_for_legacy_id(row.get(legacy_key))
    if not user_uuid or row.get(uuid_key) == user_uuid:
        return False
    row[uuid_key] = user_uuid
    return True


def _migrate_doc(doc: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    changed = False
    for key in ("workspaces", "memberships", "connections", "pairings"):
        if not isinstance(doc.get(key), list):
            doc[key] = []
            changed = True
    if not isinstance(doc.get("active_workspaces"), dict):
        doc["active_workspaces"] = {}
        changed = True
    if not isinstance(doc.get("active_workspaces_by_uuid"), dict):
        doc["active_workspaces_by_uuid"] = {}
        changed = True
    for row in doc["workspaces"]:
        if isinstance(row, dict):
            changed = _backfill_user_uuid(row, "owner_user_id", "owner_user_uuid") or changed
    for row in doc["memberships"]:
        if isinstance(row, dict):
            changed = _backfill_user_uuid(row, "user_id", "user_uuid") or changed
            changed = _backfill_user_uuid(row, "created_by_user_id", "created_by_user_uuid") or changed
    for row in doc["connections"]:
        if isinstance(row, dict):
            changed = _backfill_user_uuid(row, "owner_user_id", "owner_user_uuid") or changed
    for row in doc["pairings"]:
        if isinstance(row, dict):
            changed = _backfill_user_uuid(row, "created_by_user_id", "created_by_user_uuid") or changed
    active_by_uuid = doc["active_workspaces_by_uuid"]
    for raw_user_id, workspace_id in doc["active_workspaces"].items():
        user_uuid = _user_uuid_for_legacy_id(raw_user_id)
        if user_uuid and active_by_uuid.get(user_uuid) != workspace_id:
            active_by_uuid[user_uuid] = workspace_id
            changed = True
    identity_schema = doc.get("identity_schema") if isinstance(doc.get("identity_schema"), dict) else {}
    expected_schema = dict(identity_schema)
    expected_schema.update({
        "stage": "dual_write",
        "canonical_key": "user_uuid",
        "legacy_key": "user_id",
    })
    if expected_schema != identity_schema:
        expected_schema.setdefault("migrated_at_utc", _now_iso())
        doc["identity_schema"] = expected_schema
        changed = True
    if int(doc.get("version") or 1) < WORKSPACE_STORE_VERSION:
        doc["version"] = WORKSPACE_STORE_VERSION
        changed = True
    return doc, changed


def _doc_cache_key(path: Path) -> Optional[tuple[str, int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    identity = path if path.is_absolute() else path.resolve()
    return (str(identity), int(stat.st_mtime_ns), int(stat.st_size))


def _clear_doc_cache() -> None:
    global _DOC_CACHE_KEY, _DOC_CACHE_DOC
    with _LOCK:
        _DOC_CACHE_KEY = None
        _DOC_CACHE_DOC = None


def _cache_doc(path: Path, doc: Dict[str, Any]) -> None:
    global _DOC_CACHE_KEY, _DOC_CACHE_DOC
    key = _doc_cache_key(path)
    if key is None:
        _clear_doc_cache()
        return
    with _LOCK:
        _DOC_CACHE_KEY = key
        _DOC_CACHE_DOC = copy.deepcopy(doc)


def _authoritative_storage() -> bool:
    """Route both Canary and Production workspace state through PostgreSQL."""
    from . import storage_router
    return storage_router.production_enabled()


def _read_doc() -> Dict[str, Any]:
    if _authoritative_storage():
        from . import storage_router
        from .production_storage import StorageError
        try:
            doc = storage_router.read_document("workspaces", _default_doc())
        except StorageError as exc:
            raise WorkspaceError(
                f"Production workspace repository unavailable ({exc.code}).", 503,
            ) from None
        if not isinstance(doc, dict):
            raise WorkspaceError("Production workspace repository returned invalid data.", 500)
        for key in ("workspaces", "memberships", "connections", "pairings"):
            if not isinstance(doc.get(key), list):
                doc[key] = []
        if not isinstance(doc.get("active_workspaces"), dict):
            doc["active_workspaces"] = {}
        return _migrate_doc(doc)[0]
    path = _store_path()
    cache_key = _doc_cache_key(path)
    if cache_key is None:
        _clear_doc_cache()
        return _default_doc()
    with _LOCK:
        if _DOC_CACHE_KEY == cache_key and _DOC_CACHE_DOC is not None:
            cached, changed = _migrate_doc(copy.deepcopy(_DOC_CACHE_DOC))
            if changed:
                _write_doc(cached)
            return cached
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise WorkspaceError("Неизвестный формат хранилища рабочих областей.", 500)
        encrypted = base64.b64decode(raw[len(_MAGIC):], validate=True)
        doc = json.loads(secure_store._unprotect(encrypted).decode("utf-8"))
    except WorkspaceError:
        raise
    except secure_store.SecureStoreError as exc:
        raise WorkspaceError(str(exc), 503) from None
    except Exception as exc:
        raise WorkspaceError(f"Не удалось прочитать рабочие области: {exc}", 500) from None
    if not isinstance(doc, dict):
        raise WorkspaceError("Хранилище рабочих областей повреждено.", 500)
    for key in ("workspaces", "memberships", "connections", "pairings"):
        if not isinstance(doc.get(key), list):
            doc[key] = []
    if not isinstance(doc.get("active_workspaces"), dict):
        doc["active_workspaces"] = {}
    doc, changed = _migrate_doc(doc)
    if changed:
        _write_doc(doc)
        return doc
    _cache_doc(path, doc)
    return doc


def _read_doc_reference() -> Dict[str, Any]:
    """Return an internal read-only cache view while the caller holds _LOCK."""
    if _authoritative_storage():
        return _read_doc()
    path = _store_path()
    key = _doc_cache_key(path)
    with _LOCK:
        if key is not None and _DOC_CACHE_KEY == key and _DOC_CACHE_DOC is not None:
            return _DOC_CACHE_DOC
        loaded = _read_doc()
        if key is not None and _DOC_CACHE_KEY == _doc_cache_key(path) and _DOC_CACHE_DOC is not None:
            return _DOC_CACHE_DOC
        return loaded


def _write_doc(doc: Dict[str, Any]) -> None:
    doc, _ = _migrate_doc(doc)
    if _authoritative_storage():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.write_document("workspaces", doc)
            _clear_doc_cache()
            return
        except StorageError as exc:
            raise WorkspaceError(
                f"Production workspace repository write denied ({exc.code}).", 503,
            ) from None
    if not secure_store.available():
        raise WorkspaceError("Windows DPAPI недоступен; рабочие области не могут быть сохранены.", 503)
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        payload = _MAGIC + base64.b64encode(secure_store._protect(plaintext))
    except secure_store.SecureStoreError as exc:
        raise WorkspaceError(str(exc), 503) from None
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(payload)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        _cache_doc(path, doc)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise WorkspaceError(f"Не удалось сохранить рабочие области: {exc}", 500) from None


def storage_status() -> Dict[str, Any]:
    if _authoritative_storage():
        from . import storage_router
        return storage_router.storage_status()
    return {"available": secure_store.available(), "backend": secure_store.backend_name(), "encrypted": _store_path().is_file()}


def _audit(event: str, **values: Any) -> None:
    if _authoritative_storage():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.append_audit("workspace_registry", event, values)
            return
        except StorageError as exc:
            raise WorkspaceError(
                f"Production workspace audit unavailable ({exc.code}).", 503,
            ) from None
    row = {"timestamp": _now_iso(), "source": "workspace_registry", "event": event, **values}
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _owner_workspace_id(owner_id: int) -> str:
    digest = hashlib.sha256(str(int(owner_id)).encode("ascii")).hexdigest()[:12]
    return f"ws_owner_training_{digest}"


def _new_workspace_id(prefix: str) -> str:
    return f"ws_{prefix}_{secrets.token_urlsafe(12)}"


def _safe_workspace_id(workspace_id: Any) -> str:
    value = str(workspace_id or "").strip()
    if not re.fullmatch(r"ws_[A-Za-z0-9_-]{8,80}", value):
        raise WorkspaceError("Некорректный workspace id.")
    return value


def _clean_name(value: Any, fallback: str) -> str:
    name = " ".join(str(value or "").strip().split())
    if not name:
        name = fallback
    if not 1 <= len(name) <= 120:
        raise WorkspaceError("Название рабочей области слишком длинное.")
    return name


def _workspace(doc: Dict[str, Any], workspace_id: str) -> Optional[Dict[str, Any]]:
    return next((row for row in doc["workspaces"] if str(row.get("workspace_id") or "") == workspace_id), None)


def _memberships(doc: Dict[str, Any], user_id: int) -> list[Dict[str, Any]]:
    return [row for row in doc["memberships"] if int(row.get("user_id") or 0) == int(user_id) and not row.get("revoked_at_utc")]


def _membership(doc: Dict[str, Any], workspace_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    return next((row for row in _memberships(doc, user_id) if str(row.get("workspace_id") or "") == workspace_id), None)


def _ensure_membership(doc: Dict[str, Any], *, workspace_id: str, user_id: int, role: str, created_by: int) -> bool:
    if role not in WORKSPACE_ROLES:
        raise WorkspaceError("Неизвестная роль рабочей области.")
    row = _membership(doc, workspace_id, user_id)
    if row is None:
        doc["memberships"].append({
            "workspace_id": workspace_id,
            "user_id": int(user_id),
            "role": role,
            "created_by_user_id": int(created_by or user_id),
            "created_at_utc": _now_iso(),
            "revoked_at_utc": "",
        })
        return True
    if str(row.get("role") or "") != role:
        row["role"] = role
        row["updated_at_utc"] = _now_iso()
        return True
    return False


def _ensure_tenant_dirs(workspace_id: str) -> None:
    if _authoritative_storage():
        return
    base = _tenant_root(workspace_id)
    for name in ("runtime", "ops", "portfolio", "reports", "statements"):
        (base / name).mkdir(parents=True, exist_ok=True)


def _ensure_owner_workspace_doc(doc: Dict[str, Any], owner_id: int) -> tuple[Dict[str, Any], bool]:
    workspace_id = _owner_workspace_id(owner_id)
    row = _workspace(doc, workspace_id)
    changed = False
    if row is None:
        row = {
            "workspace_id": workspace_id,
            "kind": "owner_training",
            "owner_user_id": int(owner_id),
            "display_name": "Аккаунт владельца · NinjaTrader",
            "status": "active",
            "data_root": "data",
            "default_runtime_connection_id": "owner_local",
            "entitlement_id": "founder",
            "created_at_utc": _now_iso(),
            "updated_at_utc": _now_iso(),
        }
        doc["workspaces"].append(row)
        changed = True
    else:
        if row.get("display_name") in ("Учебный аккаунт владельца", "", None):
            row["display_name"] = "Аккаунт владельца · NinjaTrader"
            changed = True
        if row.get("entitlement_id") in ("owner_unlimited", "", None):
            row["entitlement_id"] = "founder"
            changed = True
    changed = _ensure_membership(doc, workspace_id=workspace_id, user_id=owner_id, role="owner", created_by=owner_id) or changed
    return row, changed


def _public_membership(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not row:
        return {}
    return {key: row.get(key) for key in (
        "workspace_id", "user_id", "user_uuid", "role", "created_by_user_id",
        "created_by_user_uuid", "created_at_utc", "revoked_at_utc",
    )}


def _public_workspace(row: Dict[str, Any], membership: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    kind = str(row.get("kind") or "")
    return {
        "workspace_id": row.get("workspace_id"),
        "kind": kind,
        "owner_user_id": row.get("owner_user_id"),
        "owner_user_uuid": row.get("owner_user_uuid") or "",
        "display_name": row.get("display_name") or "Workspace",
        "status": row.get("status") or "active",
        "entitlement_id": row.get("entitlement_id") or "",
        "default_runtime_connection_id": row.get("default_runtime_connection_id") or "",
        "uses_owner_runtime": kind == "owner_training",
        "membership": _public_membership(membership),
    }


def ensure_owner_workspace(owner_id: Any) -> Dict[str, Any]:
    owner = int(owner_id or 0)
    if owner <= 0:
        raise WorkspaceError("Owner identity обязательна.", 403)
    with _LOCK:
        doc = _read_doc()
        row, changed = _ensure_owner_workspace_doc(doc, owner)
        if changed:
            _write_doc(doc)
            _ensure_tenant_dirs(str(row["workspace_id"]))
    return _public_workspace(row, _membership(doc, str(row["workspace_id"]), owner))


def ensure_training_membership(user_id: Any, owner_id: Any) -> None:
    user = int(user_id or 0)
    owner = int(owner_id or 0)
    if user <= 0 or owner <= 0:
        return
    with _LOCK:
        doc = _read_doc()
        owner_workspace, changed = _ensure_owner_workspace_doc(doc, owner)
        role = "owner" if user == owner else "viewer"
        changed = _ensure_membership(doc, workspace_id=str(owner_workspace["workspace_id"]), user_id=user, role=role, created_by=owner) or changed
        if not doc["active_workspaces"].get(str(user)):
            doc["active_workspaces"][str(user)] = str(owner_workspace["workspace_id"])
            changed = True
        if changed:
            _write_doc(doc)
            _ensure_tenant_dirs(str(owner_workspace["workspace_id"]))


def ensure_service_membership(user_id: Any, owner_id: Any) -> str:
    """Bind a Development service account to the owner's workspace as an owner.

    Unlike ``ensure_training_membership`` (which adds ordinary members as
    viewers), a Claude/GPT service account is granted the ``owner`` workspace
    role so it works on exactly the owner's runtime data. Development only; the
    caller (``dev_service_accounts``) is gated to localhost.
    """
    user = int(user_id or 0)
    owner = int(owner_id or 0)
    if user <= 0 or owner <= 0:
        raise WorkspaceError("Service membership requires user and owner.", 400)
    with _LOCK:
        doc = _read_doc()
        owner_workspace, changed = _ensure_owner_workspace_doc(doc, owner)
        workspace_id = str(owner_workspace["workspace_id"])
        changed = _ensure_membership(
            doc, workspace_id=workspace_id, user_id=user, role="owner", created_by=owner,
        ) or changed
        if str(doc["active_workspaces"].get(str(user)) or "") != workspace_id:
            doc["active_workspaces"][str(user)] = workspace_id
            changed = True
        if changed:
            _write_doc(doc)
            _ensure_tenant_dirs(workspace_id)
    return workspace_id


def _is_expired(expires_at_utc: Any) -> bool:
    text = str(expires_at_utc or "").strip()
    if not text:
        return False
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    except ValueError:
        return True


def _personal_entitlement(user_id: int) -> str:
    try:
        from . import subscriptions
        rows = subscriptions.entitlements_for_user(user_id).get("entitlements") or []
    except Exception:
        return ""
    for row in rows:
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        features = plan.get("features") if isinstance(plan.get("features"), dict) else {}
        if row.get("status") in ENTITLEMENT_OK and features.get("personal_nt") and not _is_expired(row.get("expires_at_utc")):
            return str(row.get("entitlement_id") or "")
    return ""


def ensure_personal_workspace(user_id: Any, *, display_name: str = "", entitlement_id: str = "", require_entitlement: bool = True) -> Dict[str, Any]:
    user = int(user_id or 0)
    if user <= 0:
        raise WorkspaceError("Пользователь обязателен.", 403)
    entitlement = str(entitlement_id or "").strip() or _personal_entitlement(user)
    if require_entitlement and not entitlement:
        raise WorkspaceError("Для личного NinjaTrader нужна активная подписка или промокод.", 402)
    with _LOCK:
        doc = _read_doc()
        existing = next((row for row in doc["workspaces"] if int(row.get("owner_user_id") or 0) == user and row.get("kind") == "personal" and row.get("status") == "active"), None)
        changed = False
        if existing is None:
            workspace_id = _new_workspace_id("personal")
            existing = {
                "workspace_id": workspace_id,
                "kind": "personal",
                "owner_user_id": user,
                "display_name": _clean_name(display_name, "Мой NinjaTrader"),
                "status": "active",
                "data_root": f"data/tenants/{workspace_id}",
                "default_runtime_connection_id": "",
                "entitlement_id": entitlement,
                "created_at_utc": _now_iso(),
                "updated_at_utc": _now_iso(),
            }
            doc["workspaces"].append(existing)
            changed = True
        elif entitlement and not existing.get("entitlement_id"):
            existing["entitlement_id"] = entitlement
            existing["updated_at_utc"] = _now_iso()
            changed = True
        changed = _ensure_membership(doc, workspace_id=str(existing["workspace_id"]), user_id=user, role="owner", created_by=user) or changed
        doc["active_workspaces"][str(user)] = str(existing["workspace_id"])
        changed = True
        if changed:
            _write_doc(doc)
        _ensure_tenant_dirs(str(existing["workspace_id"]))
    _audit("personal_workspace_ensured", user_id=user, workspace_id=existing["workspace_id"], entitlement_id=entitlement)
    return _public_workspace(existing, _membership(doc, str(existing["workspace_id"]), user))


def context_for_user(user_id: Any, *, is_owner: bool = False, owner_id: Any = 0) -> Dict[str, Any]:
    user = int(user_id or 0)
    owner = int(owner_id or 0)
    if user <= 0:
        return {"workspaces": [], "active_workspace": {}, "active_membership": {}, "storage": storage_status()}
    initialized_workspace_id = ""
    with _LOCK:
        doc = _read_doc_reference()
        changed = False
        if owner > 0:
            initialized_workspace_id = _owner_workspace_id(owner)
            existing_owner_workspace = _workspace(doc, initialized_workspace_id)
            existing_membership = _membership(doc, initialized_workspace_id, user)
            expected_role = "owner" if user == owner else "viewer"
            initialization_required = bool(
                existing_owner_workspace is None
                or existing_owner_workspace.get("display_name") in (
                    "Учебный аккаунт владельца", "", None,
                )
                or existing_owner_workspace.get("entitlement_id") in (
                    "owner_unlimited", "", None,
                )
                or existing_membership is None
                or str(existing_membership.get("role") or "") != expected_role
                or not doc["active_workspaces"].get(str(user))
            )
            if initialization_required:
                # Never amend the shared cache object. Mutation continues on a
                # private snapshot and becomes visible only after atomic write.
                doc = copy.deepcopy(doc)
                owner_workspace, changed = _ensure_owner_workspace_doc(doc, owner)
                initialized_workspace_id = str(owner_workspace["workspace_id"])
                changed = _ensure_membership(
                    doc,
                    workspace_id=initialized_workspace_id,
                    user_id=user,
                    role=expected_role,
                    created_by=owner,
                ) or changed
                if not doc["active_workspaces"].get(str(user)):
                    doc["active_workspaces"][str(user)] = initialized_workspace_id
                    changed = True
        if changed:
            _write_doc(doc)
        memberships = _memberships(doc, user)
        visible: list[Dict[str, Any]] = []
        for member in memberships:
            row = _workspace(doc, str(member.get("workspace_id") or ""))
            if row and row.get("status") == "active":
                visible.append(_public_workspace(row, member))
        active_id = str(doc["active_workspaces"].get(str(user)) or "")
        if active_id and not any(row.get("workspace_id") == active_id for row in visible):
            active_id = ""
        if not active_id and visible:
            personal = next((row for row in visible if row.get("kind") == "personal"), None)
            active_id = str((personal or visible[0]).get("workspace_id") or "")
            updated_doc = copy.deepcopy(doc)
            updated_doc["active_workspaces"][str(user)] = active_id
            _write_doc(updated_doc)
            doc = updated_doc
        active = next((row for row in visible if row.get("workspace_id") == active_id), {})
        active_member = active.get("membership") if isinstance(active.get("membership"), dict) else {}
    if initialized_workspace_id and changed:
        _ensure_tenant_dirs(initialized_workspace_id)
    return {
        "workspaces": visible,
        "active_workspace": active,
        "active_membership": active_member,
        "uses_owner_runtime": bool(active.get("uses_owner_runtime")),
        "storage": storage_status(),
        "is_global_owner": bool(is_owner),
    }


def runtime_monitor_scopes() -> list[Dict[str, Any]]:
    """Return one service-event scope per active NinjaTrader workspace."""
    with _LOCK:
        doc = _read_doc()
        scopes: list[Dict[str, Any]] = []
        for workspace in doc.get("workspaces") or []:
            if not isinstance(workspace, dict) or workspace.get("status") != "active":
                continue
            workspace_id = str(workspace.get("workspace_id") or "")
            members = [
                row for row in (doc.get("memberships") or [])
                if isinstance(row, dict) and not row.get("revoked_at_utc")
                and str(row.get("workspace_id") or "") == workspace_id
            ]
            if not members:
                continue
            owner_id = int(workspace.get("owner_user_id") or 0)
            representative = next(
                (row for row in members if int(row.get("user_id") or 0) == owner_id),
                members[0],
            )
            kind = str(workspace.get("kind") or "")
            scopes.append({
                "user_id": int(representative.get("user_id") or owner_id),
                "workspace_id": workspace_id,
                "workspace_kind": kind,
                "uses_owner_runtime": bool(kind == "owner_training"),
                "membership_role": str(representative.get("role") or "viewer"),
                "is_owner": int(representative.get("user_id") or 0) == owner_id,
                "display_name": "System",
            })
        return scopes


def select_workspace(user_id: Any, workspace_id: Any) -> Dict[str, Any]:
    user = int(user_id or 0)
    workspace = _safe_workspace_id(workspace_id)
    with _LOCK:
        doc = _read_doc()
        member = _membership(doc, workspace, user)
        row = _workspace(doc, workspace)
        if not row or row.get("status") != "active" or not member:
            raise WorkspaceError("Рабочая область недоступна.", 403)
        doc["active_workspaces"][str(user)] = workspace
        _write_doc(doc)
    _audit("workspace_selected", user_id=user, workspace_id=workspace)
    return {"ok": True, "active_workspace": _public_workspace(row, member)}


def _active_workspace_doc(doc: Dict[str, Any], user_id: int, workspace_id: str = "") -> tuple[Dict[str, Any], Dict[str, Any]]:
    workspace = workspace_id or str(doc["active_workspaces"].get(str(user_id)) or "")
    row = _workspace(doc, workspace)
    member = _membership(doc, workspace, user_id) if row else None
    if not row or not member:
        raise WorkspaceError("Рабочая область недоступна.", 403)
    return row, member


def _require_workspace_writer(member: Dict[str, Any]) -> None:
    if str(member.get("role") or "") not in WRITE_ROLES:
        raise WorkspaceError("В этой рабочей области доступно только чтение.", 403)


def require_workspace_access(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    """Return one authorized workspace without exposing the encrypted document."""
    user = int(user_id or 0)
    with _LOCK:
        doc = _read_doc()
        row, member = _active_workspace_doc(doc, user, workspace_id)
        if row.get("status") != "active":
            raise WorkspaceError("Рабочая область неактивна.", 403)
        return _public_workspace(row, member)


def require_workspace_writer(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    user = int(user_id or 0)
    with _LOCK:
        doc = _read_doc()
        row, member = _active_workspace_doc(doc, user, workspace_id)
        if row.get("status") != "active":
            raise WorkspaceError("Рабочая область неактивна.", 403)
        _require_workspace_writer(member)
        return _public_workspace(row, member)


def start_bridge_pairing(user_id: Any, *, workspace_id: str = "", machine_label: str = "") -> Dict[str, Any]:
    user = int(user_id or 0)
    with _LOCK:
        doc = _read_doc()
        row, member = _active_workspace_doc(doc, user, workspace_id)
        _require_workspace_writer(member)
        if row.get("kind") == "owner_training" and not member.get("role") == "owner":
            raise WorkspaceError("Учебный workspace владельца нельзя подключать к чужому NinjaTrader.", 403)
        code = secrets.token_hex(4).upper()
        pairing = {
            "pairing_id": "pair_" + secrets.token_urlsafe(10),
            "code_hash": hashlib.sha256(("bridge-pair:" + code).encode("ascii")).hexdigest(),
            "workspace_id": row["workspace_id"],
            "created_by_user_id": user,
            "machine_label": _clean_name(machine_label, "Мой компьютер"),
            "status": "created",
            "created_at_utc": _now_iso(),
            "expires_at": time.time() + PAIRING_TTL_SEC,
        }
        doc["pairings"].append(pairing)
        _write_doc(doc)
    _audit("bridge_pairing_started", user_id=user, workspace_id=row["workspace_id"], pairing_id=pairing["pairing_id"])
    return {"ok": True, "pairing_id": pairing["pairing_id"], "code": code, "expires_in_sec": PAIRING_TTL_SEC, "workspace": _public_workspace(row, member)}


def _code_hash(code: Any) -> str:
    value = re.sub(r"[^A-Fa-f0-9]", "", str(code or "").upper())
    if len(value) < 8:
        raise WorkspaceError("Pairing code некорректен.")
    return hashlib.sha256(("bridge-pair:" + value).encode("ascii")).hexdigest()


def complete_bridge_pairing(user_id: Any, *, code: Any, device_id: str = "", bridge_instance_id: str = "",
                            machine_label: str = "", capabilities: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    user = int(user_id or 0)
    digest = _code_hash(code)
    with _LOCK:
        doc = _read_doc()
        pairing = next((row for row in doc["pairings"] if row.get("status") == "created" and float(row.get("expires_at") or 0) > time.time() and hmac.compare_digest(str(row.get("code_hash") or ""), digest)), None)
        if pairing is None:
            raise WorkspaceError("Pairing code истёк или не найден.", 404)
        if int(pairing.get("created_by_user_id") or 0) != user:
            raise WorkspaceError("Pairing code принадлежит другому пользователю.", 403)
        row, member = _active_workspace_doc(doc, user, str(pairing.get("workspace_id") or ""))
        _require_workspace_writer(member)
        allowed_caps = [str(value) for value in (capabilities or []) if str(value) in {"accounts_read", "paper_commands", "live_read", "live_commands"}]
        if not allowed_caps:
            allowed_caps = ["accounts_read", "paper_commands"]
        connection = {
            "connection_id": "conn_" + secrets.token_urlsafe(12),
            "workspace_id": row["workspace_id"],
            "owner_user_id": user,
            "device_id": str(device_id or "").strip()[:120],
            "bridge_instance_id": str(bridge_instance_id or secrets.token_urlsafe(8)).strip()[:120],
            "machine_label": _clean_name(machine_label or pairing.get("machine_label"), "Мой компьютер"),
            "mode": "local_node",
            "status": "online",
            "capabilities": allowed_caps,
            "created_at_utc": _now_iso(),
            "last_heartbeat_utc": _now_iso(),
            "revoked_at_utc": "",
            "account_names": [],
        }
        doc["connections"].append(connection)
        pairing["status"] = "completed"
        pairing["completed_at_utc"] = _now_iso()
        row["default_runtime_connection_id"] = connection["connection_id"]
        row["updated_at_utc"] = _now_iso()
        _write_doc(doc)
        _ensure_tenant_dirs(str(row["workspace_id"]))
    _audit("bridge_pairing_completed", user_id=user, workspace_id=row["workspace_id"], connection_id=connection["connection_id"])
    return {"ok": True, "connection": _public_connection(connection), "workspace": _public_workspace(row, member)}


def _public_connection(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in (
        "connection_id", "workspace_id", "owner_user_id", "owner_user_uuid", "device_id", "bridge_instance_id",
        "machine_label", "mode", "status", "capabilities", "created_at_utc",
        "last_heartbeat_utc", "revoked_at_utc", "account_names",
    )}


def list_connections(user_id: Any, *, workspace_id: str = "") -> Dict[str, Any]:
    user = int(user_id or 0)
    with _LOCK:
        doc = _read_doc()
        row, member = _active_workspace_doc(doc, user, workspace_id)
        connections = [conn for conn in doc["connections"] if str(conn.get("workspace_id") or "") == str(row["workspace_id"]) and not conn.get("revoked_at_utc")]
    return {"connections": [_public_connection(conn) for conn in connections], "workspace": _public_workspace(row, member)}


def bridge_setup(user_id: Any) -> Dict[str, Any]:
    """Instructions + config template for connecting a personal NinjaTrader.

    For the owner-training contour it reports the owner's real NinjaTrader.
    For a personal workspace it returns the tenant runtime directory and a
    ready ``NTAnalyzerBridge.config.json`` template that points the local bridge
    at that isolated directory, plus a step-by-step wizard.
    """
    user = int(user_id or 0)
    with _LOCK:
        doc = _read_doc()
        row, member = _active_workspace_doc(doc, user)
        connections = [conn for conn in doc["connections"] if str(conn.get("workspace_id") or "") == str(row["workspace_id"]) and not conn.get("revoked_at_utc")]
    workspace = _public_workspace(row, member)
    if row.get("kind") == "owner_training":
        return {
            "ok": True, "owner_runtime": True, "workspace": workspace, "connections": [],
            "message": "Активен аккаунт владельца — используется реальный NinjaTrader владельца. Свой NinjaTrader подключать не нужно.",
            "steps": [], "config_template": {},
        }
    workspace_id = str(row["workspace_id"])
    if _authoritative_storage():
        origin = runtime_env.deployment_config(strict=False).public_origin
        return {
            "ok": True,
            "owner_runtime": False,
            "workspace": workspace,
            "connections": [_public_connection(conn) for conn in connections],
            "runtime_data_dir": "",
            "install_command": "StratForgeConnectorSetup.exe",
            "config_file": "managed-by-stratforge-connector",
            "config_template": {
                "server_url": origin,
                "workspace_id": workspace_id,
                "protocol_version": "1.0",
            },
            "steps": [
                "Скачайте подписанный установщик StratForge Connector из приложения.",
                "Закройте NinjaTrader и запустите установщик; локальные пути вводить не нужно.",
                "Введите одноразовый код подключения из приложения.",
                "Запустите NinjaTrader и дождитесь подтверждённого heartbeat.",
            ],
        }
    runtime_dir = str(_tenant_root(workspace_id) / "runtime")
    return {
        "ok": True,
        "owner_runtime": False,
        "workspace": workspace,
        "connections": [_public_connection(conn) for conn in connections],
        "runtime_data_dir": runtime_dir,
        "install_command": "01_INSTALL_BRIDGE.cmd",
        "config_file": "%USERPROFILE%\\Documents\\NinjaTrader 8\\bin\\Custom\\NTAnalyzerBridge.config.json",
        "config_template": {
            "project_root": str(_root()),
            "ninjatrader_user_dir": "%USERPROFILE%\\Documents\\NinjaTrader 8",
            "runtime_data_dir": runtime_dir,
            "poll_interval_ms": 1500,
            "heartbeat_interval_ms": 5000,
        },
        "steps": [
            "Установите NT-Analyzer bridge: закройте NinjaTrader 8 и запустите 01_INSTALL_BRIDGE.cmd (устанавливает AddOn).",
            "Впишите в NTAnalyzerBridge.config.json поле runtime_data_dir из этого окна — тогда ваш NinjaTrader пишет данные в вашу изолированную область.",
            "Откройте NinjaTrader 8 и войдите в свой брокерский/симуляционный аккаунт — приложение не запрашивает пароли брокера.",
            "Нажмите «Получить код подключения», введите его при первом старте bridge — область привяжется к вашему компьютеру.",
            "После heartbeat интерфейс покажет ваши счета NinjaTrader вместо аккаунта владельца.",
        ],
    }


def revoke_connection(user_id: Any, connection_id: Any) -> Dict[str, Any]:
    user = int(user_id or 0)
    target = str(connection_id or "").strip()
    with _LOCK:
        doc = _read_doc()
        conn = next((row for row in doc["connections"] if str(row.get("connection_id") or "") == target), None)
        if conn is None:
            raise WorkspaceError("Подключение не найдено.", 404)
        workspace_row, member = _active_workspace_doc(doc, user, str(conn.get("workspace_id") or ""))
        _require_workspace_writer(member)
        conn["status"] = "revoked"
        conn["revoked_at_utc"] = _now_iso()
        if str(workspace_row.get("default_runtime_connection_id") or "") == target:
            workspace_row["default_runtime_connection_id"] = ""
        _write_doc(doc)
    _audit("bridge_connection_revoked", user_id=user, workspace_id=workspace_row["workspace_id"], connection_id=target)
    return {"ok": True, "connection": _public_connection(conn)}


_ALLOWED_CONNECTION_CAPS = ("accounts_read", "paper_commands", "live_read", "live_commands")


def set_default_connection(user_id: Any, connection_id: Any) -> Dict[str, Any]:
    """Make one active connection the workspace default runtime (step-up gated)."""
    user = int(user_id or 0)
    target = str(connection_id or "").strip()
    with _LOCK:
        doc = _read_doc()
        conn = next(
            (row for row in doc["connections"]
             if str(row.get("connection_id") or "") == target and not row.get("revoked_at_utc")),
            None,
        )
        if conn is None:
            raise WorkspaceError("Подключение не найдено.", 404)
        workspace_row, member = _active_workspace_doc(doc, user, str(conn.get("workspace_id") or ""))
        _require_workspace_writer(member)
        workspace_row["default_runtime_connection_id"] = target
        workspace_row["updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit("bridge_default_connection_set", user_id=user, workspace_id=workspace_row["workspace_id"], connection_id=target)
    return {"ok": True, "connection": _public_connection(conn), "workspace": _public_workspace(workspace_row, member)}


def set_connection_capabilities(
    user_id: Any, connection_id: Any, capabilities: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Set the granted capabilities of an active connection (step-up gated)."""
    user = int(user_id or 0)
    target = str(connection_id or "").strip()
    requested = [str(v) for v in (capabilities or []) if str(v) in _ALLOWED_CONNECTION_CAPS]
    if not requested:
        raise WorkspaceError("Не указаны допустимые возможности.", 400)
    with _LOCK:
        doc = _read_doc()
        conn = next(
            (row for row in doc["connections"]
             if str(row.get("connection_id") or "") == target and not row.get("revoked_at_utc")),
            None,
        )
        if conn is None:
            raise WorkspaceError("Подключение не найдено.", 404)
        workspace_row, member = _active_workspace_doc(doc, user, str(conn.get("workspace_id") or ""))
        _require_workspace_writer(member)
        conn["capabilities"] = sorted(set(requested), key=_ALLOWED_CONNECTION_CAPS.index)
        conn["capabilities_updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit("bridge_connection_capabilities_set", user_id=user, workspace_id=workspace_row["workspace_id"], connection_id=target)
    return {"ok": True, "connection": _public_connection(conn)}


def _ledger_path(workspace_id: str) -> Path:
    return _tenant_root(workspace_id) / "statements" / "account_ledger.json"


def _default_ledger() -> Dict[str, Any]:
    return {"schema_version": 1, "updated_at_utc": _now_iso(), "accounts": {}}


def _read_ledger(workspace_id: str) -> Dict[str, Any]:
    if _authoritative_storage():
        from . import storage_router
        from .production_storage import StorageError
        try:
            return storage_router.read_workspace_ledger(workspace_id, _default_ledger())
        except StorageError as exc:
            raise WorkspaceError(
                f"Production workspace ledger unavailable ({exc.code}).", 503,
            ) from None
    path = _ledger_path(workspace_id)
    if not path.is_file():
        return _default_ledger()
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return _default_ledger()
    if not isinstance(doc, dict) or not isinstance(doc.get("accounts"), dict):
        return _default_ledger()
    return doc


def _write_ledger(workspace_id: str, doc: Dict[str, Any]) -> None:
    if _authoritative_storage():
        from . import storage_router
        from .production_storage import StorageError
        doc["updated_at_utc"] = _now_iso()
        try:
            storage_router.write_workspace_ledger(workspace_id, doc)
            return
        except StorageError as exc:
            raise WorkspaceError(
                f"Production workspace ledger write denied ({exc.code}).", 503,
            ) from None
    path = _ledger_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at_utc"] = _now_iso()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _ledger_account(doc: Dict[str, Any], account_name: str) -> Dict[str, Any]:
    name = _clean_name(account_name, "Personal account")
    return doc["accounts"].setdefault(name, {"snapshots": [], "events": []})


def workspace_account_history(workspace_id: Any, account_name: str = "", limit: int = 500) -> Dict[str, Any]:
    workspace = _safe_workspace_id(workspace_id)
    doc = _read_ledger(workspace)
    names = [account_name] if account_name else sorted(doc["accounts"])
    rows = []
    capped = max(1, min(int(limit or 500), 5000))
    for name in names:
        account = doc["accounts"].get(name)
        if not account:
            continue
        snapshots = list(account.get("snapshots") or [])[-capped:]
        events = list(account.get("events") or [])[-capped:]
        classified = [event for event in events if event.get("classification_status") == "classified"]
        flow_by_kind = {
            kind: round(sum(float(event.get("amount") or 0) for event in classified if event.get("kind") == kind), 2)
            for kind in ("deposit", "withdrawal", "transfer", "fee")
        }
        rows.append({
            "account_name": name,
            "snapshots": snapshots,
            "events": events,
            "summary": {
                "snapshots": len(snapshots),
                "events": len(events),
                "needs_review": sum(1 for event in events if event.get("classification_status") == "needs_review"),
                "classified_cash_flow": round(sum(flow_by_kind.values()), 2),
                "flow_by_kind": flow_by_kind,
            },
        })
    return {
        "ok": True,
        "generated_at_utc": _now_iso(),
        "workspace_id": workspace,
        "accounts": rows,
        "cash_flow_capability": "workspace_manual_events",
        "cash_flow_note": "Personal workspace ledger is isolated from the owner training account.",
    }


def workspace_add_event(workspace_id: Any, account_name: str, kind: str, amount: Any, actor: str,
                        note: str = "", at_utc: Any = None, source: str = "manual", source_id: str = "") -> Dict[str, Any]:
    workspace = _safe_workspace_id(workspace_id)
    event_kind = str(kind or "").strip().lower()
    if event_kind not in {"deposit", "withdrawal", "transfer", "fee"}:
        raise ValueError("kind must be deposit, withdrawal, transfer or fee")
    try:
        value = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("amount must be numeric") from None
    doc = _read_ledger(workspace)
    account = _ledger_account(doc, account_name)
    clean_source_id = str(source_id or "").strip()
    if clean_source_id:
        for event in account.get("events") or []:
            if str(event.get("source_id") or "") == clean_source_id:
                return {"ok": True, "event": event, "duplicate": True}
    event = {
        "event_id": "evt_" + secrets.token_urlsafe(12),
        "at_utc": str(at_utc or _now_iso()),
        "kind": event_kind,
        "amount": value,
        "actor": str(actor or "ui")[:120],
        "note": str(note or "")[:1000],
        "source": str(source or "manual")[:80],
        "source_id": clean_source_id,
        "classification_status": "classified",
        "created_at_utc": _now_iso(),
    }
    account.setdefault("events", []).append(event)
    _write_ledger(workspace, doc)
    return {"ok": True, "event": event, "duplicate": False, "history": workspace_account_history(workspace, account_name)}


def workspace_import_events(workspace_id: Any, account_name: str, rows: Iterable[Dict[str, Any]], actor: str,
                            source: str = "broker_statement") -> Dict[str, Any]:
    imported = 0
    duplicates = 0
    for raw in list(rows or [])[:5000]:
        result = workspace_add_event(
            workspace_id, account_name, str(raw.get("kind") or ""), raw.get("amount"), actor,
            str(raw.get("note") or ""), raw.get("at_utc"), source, str(raw.get("source_id") or ""),
        )
        if result.get("duplicate"):
            duplicates += 1
        else:
            imported += 1
    return {"ok": True, "imported": imported, "duplicates": duplicates, "history": workspace_account_history(workspace_id, account_name)}


def workspace_classify_event(workspace_id: Any, account_name: str, event_id: str, kind: str, actor: str, note: str = "") -> Dict[str, Any]:
    workspace = _safe_workspace_id(workspace_id)
    doc = _read_ledger(workspace)
    account = _ledger_account(doc, account_name)
    event = next((row for row in account.get("events") or [] if str(row.get("event_id") or "") == str(event_id or "")), None)
    if event is None:
        raise ValueError("event not found")
    event_kind = str(kind or "").strip().lower()
    if event_kind not in {"deposit", "withdrawal", "transfer", "fee"}:
        raise ValueError("kind must be deposit, withdrawal, transfer or fee")
    event["kind"] = event_kind
    event["classification_status"] = "classified"
    event["classified_by"] = str(actor or "ui")[:120]
    event["classified_at_utc"] = _now_iso()
    if note:
        event["note"] = str(note)[:1000]
    _write_ledger(workspace, doc)
    return {"ok": True, "event": event, "history": workspace_account_history(workspace, account_name)}


def uses_owner_runtime(context: Dict[str, Any]) -> bool:
    return bool((context or {}).get("uses_owner_runtime"))


def runtime_dir_for_context(context: Dict[str, Any]) -> str:
    if _authoritative_storage():
        # Production Connectors use the signed HTTP protocol. A server path is
        # never returned to or trusted from a Connector client.
        return ""
    active = (context or {}).get("active_workspace") if isinstance(context, dict) else {}
    if not isinstance(active, dict) or not active or active.get("uses_owner_runtime"):
        return ""
    workspace_id = str(active.get("workspace_id") or "")
    connection_id = str(active.get("default_runtime_connection_id") or "")
    if not workspace_id or not connection_id:
        return ""
    try:
        with _LOCK:
            doc = _read_doc()
            connection = next((row for row in doc["connections"]
                               if str(row.get("connection_id") or "") == connection_id
                               and str(row.get("workspace_id") or "") == workspace_id
                               and str(row.get("status") or "") == "online"
                               and not row.get("revoked_at_utc")), None)
        if connection is None:
            return ""
        runtime_dir = _tenant_root(workspace_id) / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return str(runtime_dir)
    except WorkspaceError:
        return ""


def runtime_storage_dir_for_context(context: Dict[str, Any]) -> str:
    """Return the isolated runtime store even while a personal bridge is offline.

    ``runtime_dir_for_context`` intentionally reports only an online bridge and
    is used by read endpoints to decide whether to show the pairing stub. Writes
    and background AI work need a different invariant: a personal workspace
    must never fall back to the owner's global ``data/runtime`` directory just
    because its bridge is temporarily offline.
    """
    if _authoritative_storage():
        return ""
    active = (context or {}).get("active_workspace") if isinstance(context, dict) else {}
    if not isinstance(active, dict) or not active or active.get("uses_owner_runtime"):
        return ""
    try:
        workspace_id = _safe_workspace_id(active.get("workspace_id"))
    except WorkspaceError:
        return ""
    runtime_dir = _tenant_root(workspace_id) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return str(runtime_dir)


def runtime_stub(path: str, query: Dict[str, list[str]], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    active = (context or {}).get("active_workspace") if isinstance(context, dict) else {}
    if not isinstance(active, dict) or active.get("uses_owner_runtime"):
        return None
    if runtime_dir_for_context(context):
        return None
    workspace_id = str(active.get("workspace_id") or "")
    workspace_ready = bool(workspace_id)
    # Never fall through to the owner's global runtime when an authenticated
    # user has no active workspace yet (for example during an interrupted
    # entitlement migration).  The old fall-through made account-history call
    # the tenant ledger with an empty id and surfaced a 500 on Overview.
    if not workspace_ready:
        warning = "Для этого профиля ещё не подготовлена рабочая область NinjaTrader."
        source = "workspace_required"
    else:
        warning = "Личный NinjaTrader для этой рабочей области ещё не подключён. Запустите pairing bridge."
        source = "workspace_runtime_not_connected"
    if path == "/api/ops/runtime/instruments" and workspace_ready:
        return None
    base = {
        "ok": True,
        "source": source,
        "workspace": active,
        "warnings": [warning],
        "next_action": warning,
    }
    if path == "/api/ops/runtime/instruments":
        return {**base, "instruments": []}
    if path == "/api/ops/runtime/accounts":
        return {**base, "accounts": [], "online_accounts": [], "connection_required": True}
    if path == "/api/ops/runtime/account-history":
        if not workspace_ready:
            return {
                **base,
                "workspace_id": "",
                "accounts": [],
                "cash_flow_capability": "workspace_unavailable",
                "cash_flow_note": warning,
            }
        account = (query.get("account") or [""])[0]
        try:
            limit = int((query.get("limit") or ["500"])[0])
        except ValueError:
            limit = 500
        history = workspace_account_history(workspace_id, account, limit)
        return {**history, "workspace": active, "warnings": [warning]}
    if path == "/api/ops/runtime/strategies":
        return {**base, "strategies": [], "raw": []}
    if re.fullmatch(r"/api/ops/runtime/strategies/[^/]+", path):
        return {**base, "strategy": {}, "runtime": {}, "warnings": [warning]}
    if path == "/api/ops/runtime/positions":
        return {}
    if path == "/api/ops/runtime/executions":
        return {**base, "executions": [], "raw_count": 0, "deduped_count": 0, "duplicate_count": 0, "dedupe": {}}
    if path == "/api/ops/runtime/orders":
        return {**base, "orders": [], "raw_count": 0, "deduped_count": 0, "duplicate_count": 0, "dedupe": {}}
    if path == "/api/ops/runtime/errors":
        return {**base, "errors": []}
    if path == "/api/ops/runtime/commands":
        return {**base, "commands": []}
    if path == "/api/ops/runtime/command-results":
        return {**base, "results": []}
    if path == "/api/ops/runtime/command-status":
        command_id = (query.get("command_id") or [""])[0]
        if command_id:
            return {**base, "command_id": command_id, "state": "workspace_bridge_offline", "reason": warning}
        return {**base, "statuses": []}
    if path in {"/api/ops/runtime/history", "/api/ops/runtime/strategy-history"}:
        return {**base, "sessions": [], "events": []}
    if path in {"/api/ops/runtime/health", "/api/ops/runtime/heartbeat"}:
        return {**base, "ok": False, "connected": False}
    return base
