"""Phase 11: workspace / strategy document specification revisions.

A *document* has a scope (global / governance / workspace / strategy / changelog),
a slug and a title, and an append-only chain of immutable *revisions*:

    draft -> review -> approved -> published

A published revision supersedes the previously published one; a revert creates a
new draft that clones an earlier revision's content (never mutating history).

Scope safety (the Phase 10/11 acceptance invariant): global / governance /
changelog documents require the owner or ``docs.manage_global``. Workspace and
strategy documents are bound to a single workspace and require
``strategy.spec.manage`` (or ``docs.manage_workspace``); a workspace member can
only touch documents in their own workspace and can never create a global or
governance document. This module writes only to its own store; it never reads or
mutates the governance laws/safety-limit store (``app.governance``), so a
workspace or strategy revision can never change global governance or safety
limits. No secret, token or credential is ever stored.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import account_auth, observability, runtime_env, secure_store


# --------------------------------------------------------------------------- #
# Scopes + revision state machine.
# --------------------------------------------------------------------------- #
SCOPE_GLOBAL = "global"
SCOPE_GOVERNANCE = "governance"
SCOPE_WORKSPACE = "workspace"
SCOPE_STRATEGY = "strategy"
SCOPE_CHANGELOG = "changelog"
SCOPES = (SCOPE_GLOBAL, SCOPE_GOVERNANCE, SCOPE_WORKSPACE, SCOPE_STRATEGY, SCOPE_CHANGELOG)
# Scopes that are bound to a single workspace.
WORKSPACE_SCOPES = frozenset({SCOPE_WORKSPACE, SCOPE_STRATEGY})
# Scopes that only the owner / docs.manage_global may create or change.
GLOBAL_SCOPES = frozenset({SCOPE_GLOBAL, SCOPE_GOVERNANCE, SCOPE_CHANGELOG})

STATUS_DRAFT = "draft"
STATUS_REVIEW = "review"
STATUS_APPROVED = "approved"
STATUS_PUBLISHED = "published"
STATUS_SUPERSEDED = "superseded"

# Allowed forward transitions; anything else (skipped/backward) is rejected.
_TRANSITIONS: Dict[str, frozenset] = {
    STATUS_DRAFT: frozenset({STATUS_REVIEW}),
    STATUS_REVIEW: frozenset({STATUS_APPROVED, STATUS_DRAFT}),
    STATUS_APPROVED: frozenset({STATUS_PUBLISHED, STATUS_DRAFT}),
    STATUS_PUBLISHED: frozenset({STATUS_SUPERSEDED}),
    STATUS_SUPERSEDED: frozenset(),
}

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,159}$")
_STORE_KEY = "doc_specs"
_MAGIC = b"NTADOCSPEC1\n"
_LOCK = threading.RLock()


class DocSpecError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = code or "doc_spec_error"


# --------------------------------------------------------------------------- #
# Store (encrypted local in Development; storage_router in Production).
# --------------------------------------------------------------------------- #
def _root() -> Path:
    return runtime_env.data_path("integrations")


def _store_path() -> Path:
    return _root() / "doc_specs.dpapi"


def _audit_path() -> Path:
    return runtime_env.data_path("audit") / "doc-specs-audit.jsonl"


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _now_iso(epoch: Optional[float] = None) -> str:
    ts = datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else datetime.now(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_doc() -> Dict[str, Any]:
    return {"schema_version": 1, "documents": [], "revisions": []}


def _normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        return _default_doc()
    base = _default_doc()
    base["documents"] = doc.get("documents") if isinstance(doc.get("documents"), list) else []
    base["revisions"] = doc.get("revisions") if isinstance(doc.get("revisions"), list) else []
    return base


def _read_doc() -> Dict[str, Any]:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            return _normalize(storage_router.read_document(_STORE_KEY, _default_doc()))
        except StorageError as exc:
            raise DocSpecError(f"Document store unavailable ({exc.code}).", 503, code=exc.code) from None
    path = _store_path()
    if not path.is_file():
        return _default_doc()
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise DocSpecError("Неизвестный формат doc-spec store.", 500, code="store_format")
        import base64
        payload = secure_store._unprotect(base64.b64decode(raw[len(_MAGIC):], validate=True))
        return _normalize(json.loads(payload.decode("utf-8")))
    except DocSpecError:
        raise
    except secure_store.SecureStoreError as exc:
        raise DocSpecError(str(exc), 503, code="store_unavailable") from None
    except Exception as exc:  # noqa: BLE001
        raise DocSpecError(f"doc-spec store повреждён: {type(exc).__name__}.", 500, code="store_corrupt") from None


def _write_doc(doc: Dict[str, Any]) -> None:
    doc = _normalize(doc)
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.write_document(_STORE_KEY, doc)
            return
        except StorageError as exc:
            raise DocSpecError(f"Document store write denied ({exc.code}).", 503, code=exc.code) from None
    if not secure_store.available():
        raise DocSpecError("Encrypted document store недоступен.", 503, code="store_unavailable")
    import base64
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        protected = secure_store._protect(plaintext)
    except secure_store.SecureStoreError as exc:
        raise DocSpecError(str(exc), 503, code="store_unavailable") from None
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(_MAGIC + base64.b64encode(protected))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _audit(event: str, **values: Any) -> None:
    safe = {k: observability.redact(v, key=k) for k, v in values.items()}
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.append_audit("doc_specs", event, safe)
            return
        except StorageError:
            return
    row = {"timestamp_utc": _now_iso(), "source": "doc_specs", "event": str(event), **safe}
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


# --------------------------------------------------------------------------- #
# Identity + permission helpers.
# --------------------------------------------------------------------------- #
def _actor_id(actor: Any) -> int:
    value = actor.get("user_id") if isinstance(actor, dict) else actor
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _actor_uuid(actor: Any) -> str:
    try:
        return account_auth.user_uuid_for_legacy_id(_actor_id(actor)) or ""
    except Exception:
        return ""


def _is_owner(actor: Any) -> bool:
    if isinstance(actor, dict) and actor.get("is_owner"):
        return True
    uid = _actor_id(actor)
    if uid <= 0:
        return False
    with account_auth._LOCK:
        user = account_auth._user(account_auth._read_doc(), uid)
    return bool(user and user.get("is_owner"))


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _find(rows: List[Dict[str, Any]], key: str, value: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if isinstance(row, dict) and str(row.get(key) or "") == str(value):
            return row
    return None


def _caps(admin_caps: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return admin_caps if isinstance(admin_caps, dict) else {}


def _require_scope_permission(
    actor: Any, scope_type: str, workspace_id: str, admin_caps: Optional[Dict[str, Any]],
    actor_workspace_id: str,
) -> None:
    """Authorize a create/change for a scope. Owner is exempt.

    Global/governance/changelog scopes require ``docs.manage_global``. Workspace/
    strategy scopes require ``strategy.spec.manage`` (or ``docs.manage_workspace``)
    AND the target workspace must be the actor's own workspace, so a workspace
    member can never mutate a global governance document or another workspace.
    """
    if _is_owner(actor):
        return
    caps = _caps(admin_caps)
    if scope_type in GLOBAL_SCOPES:
        if not caps.get("docs.manage_global"):
            raise DocSpecError(
                "Глобальные/governance документы доступны только владельцу или docs.manage_global.",
                403, code="global_scope_forbidden",
            )
        return
    # Workspace / strategy scope.
    if not (caps.get("strategy.spec.manage") or caps.get("docs.manage_workspace")):
        raise DocSpecError(
            "Требуется право strategy.spec.manage для документов рабочей области/стратегии.",
            403, code="strategy_spec_forbidden",
        )
    if not workspace_id:
        raise DocSpecError("workspace_id обязателен для этой области.", 400, code="workspace_required")
    if actor_workspace_id and str(workspace_id) != str(actor_workspace_id):
        raise DocSpecError(
            "Нельзя изменять документы другой рабочей области.", 403, code="cross_workspace_forbidden",
        )


# --------------------------------------------------------------------------- #
# Public views.
# --------------------------------------------------------------------------- #
def _public_document(doc: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
    revs = [r for r in doc["revisions"] if str(r.get("document_id")) == str(document.get("document_id"))]
    published = next((r for r in revs if r.get("status") == STATUS_PUBLISHED), None)
    return {
        "document_id": document.get("document_id"),
        "scope_type": document.get("scope_type"),
        "workspace_id": document.get("workspace_id") or "",
        "strategy_id": document.get("strategy_id") or "",
        "slug": document.get("slug"),
        "title": document.get("title"),
        "current_revision_id": document.get("current_revision_id") or "",
        "revision_count": len(revs),
        "published_revision": published.get("revision") if published else None,
        "latest_status": (max(revs, key=lambda r: int(r.get("revision") or 0)).get("status") if revs else ""),
        "created_at_utc": document.get("created_at_utc"),
        "updated_at_utc": document.get("updated_at_utc"),
    }


def _public_revision(rev: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "revision_id", "document_id", "revision", "status", "reason",
        "author_legacy_id", "supersedes_revision_id", "reverted_from_revision",
        "approved_by_legacy_id", "published_by_legacy_id",
        "created_at_utc", "approved_at_utc", "published_at_utc", "content",
    )
    return {k: rev.get(k) for k in keys}


def _visible(actor: Any, admin_caps: Optional[Dict[str, Any]], actor_workspace_id: str,
             document: Dict[str, Any]) -> bool:
    if _is_owner(actor) or _caps(admin_caps).get("docs.manage_global"):
        return True
    scope = str(document.get("scope_type") or "")
    if scope in WORKSPACE_SCOPES:
        return bool(actor_workspace_id) and str(document.get("workspace_id") or "") == str(actor_workspace_id)
    return False


def list_documents(
    *, actor: Any, admin_caps: Optional[Dict[str, Any]] = None, actor_workspace_id: str = "",
    scope_type: str = "", workspace_id: str = "",
) -> Dict[str, Any]:
    doc = _read_doc()
    rows = []
    for document in doc["documents"]:
        if scope_type and str(document.get("scope_type")) != scope_type:
            continue
        if workspace_id and str(document.get("workspace_id") or "") != workspace_id:
            continue
        if not _visible(actor, admin_caps, actor_workspace_id, document):
            continue
        rows.append(_public_document(doc, document))
    rows.sort(key=lambda d: str(d.get("updated_at_utc") or ""), reverse=True)
    return {"ok": True, "documents": rows}


def get_document(*, actor: Any, document_id: str, admin_caps: Optional[Dict[str, Any]] = None,
                 actor_workspace_id: str = "") -> Dict[str, Any]:
    doc = _read_doc()
    document = _find(doc["documents"], "document_id", str(document_id or ""))
    if document is None:
        raise DocSpecError("Документ не найден.", 404, code="document_not_found")
    if not _visible(actor, admin_caps, actor_workspace_id, document):
        raise DocSpecError("Документ недоступен в вашей области.", 403, code="document_forbidden")
    revs = sorted(
        (r for r in doc["revisions"] if str(r.get("document_id")) == str(document_id)),
        key=lambda r: int(r.get("revision") or 0),
    )
    return {
        "ok": True,
        "document": _public_document(doc, document),
        "revisions": [_public_revision(r) for r in revs],
    }


# --------------------------------------------------------------------------- #
# Operations.
# --------------------------------------------------------------------------- #
def _validate_content(content: Any) -> Dict[str, Any]:
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise DocSpecError("content должен быть объектом.", 400, code="content_invalid")
    return content


def create_document(
    *, actor: Any, scope_type: str, slug: str, title: str = "", content: Any = None,
    workspace_id: str = "", strategy_id: str = "", reason: str = "",
    admin_caps: Optional[Dict[str, Any]] = None, actor_workspace_id: str = "",
) -> Dict[str, Any]:
    scope = str(scope_type or "").strip().lower()
    if scope not in SCOPES:
        raise DocSpecError("Недопустимая область документа.", 400, code="scope_invalid")
    slug = str(slug or "").strip().lower()
    if not _SLUG_RE.fullmatch(slug):
        raise DocSpecError("slug должен быть [a-z0-9._-], 1..160.", 400, code="slug_invalid")
    ws = str(workspace_id or "").strip()
    if scope in GLOBAL_SCOPES:
        ws = ""
    _require_scope_permission(actor, scope, ws, admin_caps, actor_workspace_id)
    body = _validate_content(content)
    with _LOCK:
        doc = _read_doc()
        if any(
            str(d.get("scope_type")) == scope and str(d.get("workspace_id") or "") == ws
            and str(d.get("slug")) == slug
            for d in doc["documents"]
        ):
            raise DocSpecError("Документ с таким slug уже существует в этой области.", 409, code="slug_conflict")
        document = {
            "document_id": _new_id("doc"),
            "scope_type": scope,
            "workspace_id": ws,
            "strategy_id": str(strategy_id or "").strip(),
            "slug": slug,
            "title": str(title or slug)[:200],
            "owner_user_uuid": _actor_uuid(actor),
            "owner_legacy_id": _actor_id(actor),
            "current_revision_id": "",
            "created_at_utc": _now_iso(),
            "updated_at_utc": _now_iso(),
        }
        revision = _make_revision(document["document_id"], 1, actor, body, reason)
        doc["documents"].append(document)
        doc["revisions"].append(revision)
        _write_doc(doc)
    _audit("doc_spec.created", document_id=document["document_id"], scope=scope,
           workspace_id=ws, slug=slug, actor_id=_actor_id(actor))
    return {"ok": True, "document": _public_document(doc, document),
            "revision": _public_revision(revision)}


def _make_revision(document_id: str, revision: int, actor: Any, content: Dict[str, Any],
                   reason: str, reverted_from: Optional[int] = None) -> Dict[str, Any]:
    return {
        "revision_id": _new_id("rev"),
        "document_id": document_id,
        "revision": int(revision),
        "author_user_uuid": _actor_uuid(actor),
        "author_legacy_id": _actor_id(actor),
        "status": STATUS_DRAFT,
        "content": content,
        "reason": str(reason or "")[:500],
        "supersedes_revision_id": "",
        "reverted_from_revision": reverted_from,
        "approved_by_legacy_id": 0,
        "published_by_legacy_id": 0,
        "release_build_id": "",
        "created_at_utc": _now_iso(),
        "approved_at_utc": "",
        "published_at_utc": "",
    }


def _document_for_revision(doc: Dict[str, Any], rev: Dict[str, Any]) -> Dict[str, Any]:
    document = _find(doc["documents"], "document_id", str(rev.get("document_id") or ""))
    if document is None:
        raise DocSpecError("Документ ревизии не найден.", 404, code="document_not_found")
    return document


def create_revision(
    *, actor: Any, document_id: str, content: Any = None, reason: str = "",
    admin_caps: Optional[Dict[str, Any]] = None, actor_workspace_id: str = "",
) -> Dict[str, Any]:
    body = _validate_content(content)
    with _LOCK:
        doc = _read_doc()
        document = _find(doc["documents"], "document_id", str(document_id or ""))
        if document is None:
            raise DocSpecError("Документ не найден.", 404, code="document_not_found")
        _require_scope_permission(actor, str(document.get("scope_type")),
                                  str(document.get("workspace_id") or ""), admin_caps, actor_workspace_id)
        revs = [r for r in doc["revisions"] if str(r.get("document_id")) == str(document_id)]
        # Only one open (non-terminal) revision at a time.
        if any(r.get("status") in {STATUS_DRAFT, STATUS_REVIEW, STATUS_APPROVED} for r in revs):
            raise DocSpecError("Есть незавершённая ревизия; опубликуйте или отклоните её.",
                               409, code="open_revision_exists")
        next_rev = max((int(r.get("revision") or 0) for r in revs), default=0) + 1
        revision = _make_revision(document_id, next_rev, actor, body, reason)
        doc["revisions"].append(revision)
        document["updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit("doc_spec.revision_created", document_id=document_id, revision=next_rev,
           actor_id=_actor_id(actor))
    return {"ok": True, "revision": _public_revision(revision)}


def _transition_revision(
    actor: Any, revision_id: str, to_status: str, event: str,
    admin_caps: Optional[Dict[str, Any]], actor_workspace_id: str,
    stamp: str = "",
) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        rev = _find(doc["revisions"], "revision_id", str(revision_id or ""))
        if rev is None:
            raise DocSpecError("Ревизия не найдена.", 404, code="revision_not_found")
        document = _document_for_revision(doc, rev)
        _require_scope_permission(actor, str(document.get("scope_type")),
                                  str(document.get("workspace_id") or ""), admin_caps, actor_workspace_id)
        current = str(rev.get("status") or "")
        if to_status not in _TRANSITIONS.get(current, frozenset()):
            raise DocSpecError(f"Недопустимый переход {current} -> {to_status}.",
                               409, code="invalid_transition")
        rev["status"] = to_status
        if stamp == "approved":
            rev["approved_at_utc"] = _now_iso()
            rev["approved_by_legacy_id"] = _actor_id(actor)
        elif stamp == "published":
            rev["published_at_utc"] = _now_iso()
            rev["published_by_legacy_id"] = _actor_id(actor)
            # Supersede the previously published revision + set current.
            for other in doc["revisions"]:
                if (str(other.get("document_id")) == str(document.get("document_id"))
                        and other is not rev and other.get("status") == STATUS_PUBLISHED):
                    other["status"] = STATUS_SUPERSEDED
                    rev["supersedes_revision_id"] = other.get("revision_id")
            document["current_revision_id"] = rev.get("revision_id")
        document["updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit(event, document_id=document.get("document_id"), revision=rev.get("revision"),
           to_status=to_status, actor_id=_actor_id(actor))
    return {"ok": True, "revision": _public_revision(rev)}


def submit_revision(*, actor, revision_id, admin_caps=None, actor_workspace_id=""):
    return _transition_revision(actor, revision_id, STATUS_REVIEW, "doc_spec.submitted",
                                admin_caps, actor_workspace_id)


def approve_revision(*, actor, revision_id, admin_caps=None, actor_workspace_id=""):
    return _transition_revision(actor, revision_id, STATUS_APPROVED, "doc_spec.approved",
                                admin_caps, actor_workspace_id, stamp="approved")


def publish_revision(*, actor, revision_id, admin_caps=None, actor_workspace_id=""):
    return _transition_revision(actor, revision_id, STATUS_PUBLISHED, "doc_spec.published",
                                admin_caps, actor_workspace_id, stamp="published")


def revert_document(
    *, actor: Any, document_id: str, to_revision: int, reason: str = "",
    admin_caps: Optional[Dict[str, Any]] = None, actor_workspace_id: str = "",
) -> Dict[str, Any]:
    """Create a new draft revision that clones an earlier revision's content.

    History is never mutated; a revert is a forward revision that carries the old
    content plus a ``reverted_from_revision`` marker.
    """
    with _LOCK:
        doc = _read_doc()
        document = _find(doc["documents"], "document_id", str(document_id or ""))
        if document is None:
            raise DocSpecError("Документ не найден.", 404, code="document_not_found")
        _require_scope_permission(actor, str(document.get("scope_type")),
                                  str(document.get("workspace_id") or ""), admin_caps, actor_workspace_id)
        revs = [r for r in doc["revisions"] if str(r.get("document_id")) == str(document_id)]
        source = next((r for r in revs if int(r.get("revision") or 0) == int(to_revision)), None)
        if source is None:
            raise DocSpecError("Целевая ревизия не найдена.", 404, code="revision_not_found")
        if any(r.get("status") in {STATUS_DRAFT, STATUS_REVIEW, STATUS_APPROVED} for r in revs):
            raise DocSpecError("Есть незавершённая ревизия; завершите её перед revert.",
                               409, code="open_revision_exists")
        next_rev = max((int(r.get("revision") or 0) for r in revs), default=0) + 1
        clone = dict(source.get("content") or {})
        revision = _make_revision(document_id, next_rev, actor, clone,
                                  reason or f"revert to r{to_revision}", reverted_from=int(to_revision))
        doc["revisions"].append(revision)
        document["updated_at_utc"] = _now_iso()
        _write_doc(doc)
    _audit("doc_spec.reverted", document_id=document_id, to_revision=int(to_revision),
           new_revision=next_rev, actor_id=_actor_id(actor))
    return {"ok": True, "revision": _public_revision(revision)}


def reset_for_tests() -> None:
    runtime_env.require_test_auth()
    with _LOCK:
        _write_doc(_default_doc())
