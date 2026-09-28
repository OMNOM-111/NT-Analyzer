"""Shared model access: the owner of a connection decides who may *call* it.

Owning a connection and using it are separate facts, kept in separate places:

* the connection itself -- provider account, credential, endpoint, persona
  binding, connection tests -- stays in its owner's workspace and is never
  copied, listed or projected to anybody else;
* a share is one switch per connection. On, other people's requests may be
  executed through it; off, only its owner's may. Turning it off refuses every
  new call from the next check onwards and removes nothing that happened;
* every call made through somebody else's connection is written to one ledger
  row naming both people, the model, the task/agent, tokens and money, so the
  owner sees that use apart from their own requests.

A share grants the right to invoke, nothing else: no key, no settings, and no
view into the owner's chats, memory or tasks -- nor the owner into the
caller's. This module never reads a secret.
"""
from __future__ import annotations

import sqlite3
import threading
import contextvars
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .. import runtime_env
from .states import ContractError

_LOCK = threading.RLock()
_PREVIEW_PRINCIPAL = contextvars.ContextVar("shared_preview_principal", default=None)


@contextmanager
def preview_principal(person):
    """Trusted Local bridge attribution; never populated from public auth JSON."""
    if not runtime_env.is_development():
        raise ContractError("preview_development_required")
    token = _PREVIEW_PRINCIPAL.set(dict(person))
    try:
        yield
    finally:
        _PREVIEW_PRINCIPAL.reset(token)
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS shares (
        model_id TEXT PRIMARY KEY, environment TEXT NOT NULL, owner_workspace_id TEXT NOT NULL,
        owner_user_uuid TEXT NOT NULL, label TEXT NOT NULL, provider TEXT NOT NULL, model_key TEXT NOT NULL,
        credential_source TEXT NOT NULL, registry_id TEXT, shared INTEGER NOT NULL,
        revision INTEGER NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS share_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, model_id TEXT NOT NULL, shared INTEGER NOT NULL,
        actor_user_uuid TEXT NOT NULL, at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS calls (
        request_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, owner_user_uuid TEXT NOT NULL,
        owner_workspace_id TEXT NOT NULL, caller_user_uuid TEXT NOT NULL, caller_name TEXT NOT NULL,
        caller_workspace_id TEXT NOT NULL, task TEXT NOT NULL, agent TEXT NOT NULL, purpose TEXT NOT NULL,
        status TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
        cost_usd REAL, cost_known INTEGER NOT NULL, at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS calls_owner ON calls(owner_user_uuid, at)",
    "CREATE INDEX IF NOT EXISTS calls_caller ON calls(caller_user_uuid, at)",
    "CREATE INDEX IF NOT EXISTS shares_registry ON shares(registry_id)",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path():
    return runtime_env.data_path("ai_control_center", "model_sharing.sqlite3")


@contextmanager
def _db(create: bool = True):
    """``create=False`` for reads: a question must never write storage."""
    path = _db_path()
    if not create and not path.is_file():
        yield None
        return
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        connection = (sqlite3.connect(str(path), timeout=10) if create else
                      sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10))
        connection.row_factory = sqlite3.Row
        try:
            if create:
                connection.execute("PRAGMA journal_mode=WAL")
                for statement in _SCHEMA:
                    connection.execute(statement)
            yield connection
            connection.commit()
        finally:
            connection.close()


def _share(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    value = dict(row)
    value["shared"] = bool(value["shared"])
    return value


# -- the switch ---------------------------------------------------------------

def set_shared(*, environment: str, owner_workspace_id: str, owner_user_uuid: str, model_id: str,
               shared: bool, label: str, provider: str, model_key: str, credential_source: str,
               registry_id: Optional[str] = None, context=None) -> Dict[str, Any]:
    """Only the connection's own service calls this, after checking ownership."""
    if type(shared) is not bool:
        raise ContractError("model_share_invalid")
    if runtime_env.is_server_environment():
        from . import server_model_sharing
        if (context is None or context.scope.environment.value != environment
                or context.scope.workspace_id != owner_workspace_id
                or str(context.user_uuid) != owner_user_uuid):
            raise ContractError("model_share_owner_mismatch")
        return server_model_sharing.set_shared(context, model_id=model_id, shared=shared,
            label=label, provider=provider, model_key=model_key,
            credential_source=credential_source, registry_id=registry_id)
    with _db() as db:
        current = _share(db.execute("SELECT * FROM shares WHERE model_id = ?", (model_id,)).fetchone())
        if current is not None and (current["owner_user_uuid"] != owner_user_uuid
                                    or current["owner_workspace_id"] != owner_workspace_id
                                    or current["environment"] != environment):
            raise ContractError("model_share_owner_mismatch")
        if current is not None and current["shared"] == shared:
            return current
        revision = (current["revision"] + 1) if current else 1
        db.execute("""INSERT INTO shares (model_id, environment, owner_workspace_id, owner_user_uuid, label, provider,
                          model_key, credential_source, registry_id, shared, revision, updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(model_id) DO UPDATE SET label=excluded.label, provider=excluded.provider,
                          model_key=excluded.model_key, credential_source=excluded.credential_source,
                          registry_id=excluded.registry_id, shared=excluded.shared,
                          revision=excluded.revision, updated_at=excluded.updated_at""",
                   (model_id, environment, owner_workspace_id, owner_user_uuid, label[:80], provider[:80],
                    model_key[:120], credential_source[:80], registry_id, int(shared), revision, _now()))
        db.execute("INSERT INTO share_events (model_id, shared, actor_user_uuid, at) VALUES (?,?,?,?)",
                   (model_id, int(shared), owner_user_uuid, _now()))
        return _share(db.execute("SELECT * FROM shares WHERE model_id = ?", (model_id,)).fetchone())


def get(model_id: str, *, context=None) -> Optional[Dict[str, Any]]:
    if runtime_env.is_server_environment():
        if context is None:
            raise ContractError("model_server_scope_required")
        from . import server_model_sharing
        return server_model_sharing.get(context, model_id)
    with _db(create=False) as db:
        if db is None:
            return None
        return _share(db.execute("SELECT * FROM shares WHERE model_id = ?", (str(model_id),)).fetchone())


def history(model_id: str, *, context=None) -> List[Dict[str, Any]]:
    if runtime_env.is_server_environment():
        if context is None:
            raise ContractError("model_server_scope_required")
        from . import server_model_sharing
        return server_model_sharing.history(context, model_id)
    with _db(create=False) as db:
        if db is None:
            return []
        return [dict(row) | {"shared": bool(row["shared"])} for row in db.execute(
            "SELECT shared, at FROM share_events WHERE model_id = ? ORDER BY id", (str(model_id),))]


def available(*, environment: str, caller_user_uuid: str, context=None) -> List[Dict[str, Any]]:
    """Connections other people currently share. Never the caller's own."""
    if runtime_env.is_server_environment():
        if (context is None or context.scope.environment.value != environment
                or str(context.user_uuid) != caller_user_uuid):
            raise ContractError("model_server_scope_required")
        from . import server_model_sharing
        return server_model_sharing.available(context)
    with _db(create=False) as db:
        if db is None:
            return []
        return [_share(row) for row in db.execute(
            """SELECT * FROM shares WHERE shared = 1 AND environment = ? AND owner_user_uuid != ?
               ORDER BY label, model_id""", (environment, str(caller_user_uuid)))]


def require(model_id: str, *, environment: str, caller_user_uuid: str, context=None) -> Dict[str, Any]:
    """The live grant for one call. Checked again right before transmission."""
    from ..account_lifecycle import deleted_ids
    if str(caller_user_uuid) in deleted_ids():
        raise ContractError("model_caller_deleted")
    if runtime_env.is_server_environment():
        if (context is None or context.scope.environment.value != environment
                or str(context.user_uuid) != caller_user_uuid):
            raise ContractError("model_server_scope_required")
        from . import server_model_sharing
        return server_model_sharing.require(context, model_id)
    share = get(model_id)
    if share is None or share["environment"] != environment or share["owner_user_uuid"] == str(caller_user_uuid):
        raise ContractError("model_share_not_found")
    if not share["shared"]:
        raise ContractError("model_share_revoked")
    return share


class Grant:
    """What an executor receives for a shared call: a revocable right, no key."""

    def __init__(self, share: Dict[str, Any], *, caller_user_uuid: str, context=None):
        self.share = dict(share)
        self.caller_user_uuid = str(caller_user_uuid)
        self.context = context

    def check(self) -> Dict[str, Any]:
        current = require(self.share["model_id"], environment=self.share["environment"],
                          caller_user_uuid=self.caller_user_uuid, context=self.context)
        if current["owner_user_uuid"] != self.share["owner_user_uuid"]:
            raise ContractError("model_share_revoked")
        return current


# -- the owner's registry models (Local owner bindings) ---------------------------

def registry_share(registry_id: str) -> Optional[Dict[str, Any]]:
    """The active share of the owner connection bound to one registry model."""
    if not registry_id:
        return None
    if runtime_env.is_server_environment():
        return None
    with _db(create=False) as db:
        if db is None:
            return None
        row = db.execute("""SELECT * FROM shares WHERE registry_id = ? AND shared = 1
                            AND credential_source = 'owner_registry_binding' ORDER BY model_id LIMIT 1""",
                         (str(registry_id),)).fetchone()
        return _share(row)


def shared_registry_ids() -> set:
    if runtime_env.is_server_environment():
        return set()
    with _db(create=False) as db:
        if db is None:
            return set()
        return {row[0] for row in db.execute("""SELECT registry_id FROM shares WHERE shared = 1
                    AND credential_source = 'owner_registry_binding' AND registry_id IS NOT NULL""")}


def caller(usage_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Who a model call is made for, or None for the platform's own work.

    A background job with no person attached keeps its existing behaviour. A
    request carrying a person who is not the owner is limited to what has been
    shared with them.
    """
    from .. import account_auth
    raw = str((usage_context or {}).get("user_id") or "").strip()
    if not raw:
        return None
    preview = _PREVIEW_PRINCIPAL.get()
    if preview is not None and raw == preview.get("user_uuid"):
        return dict(preview)
    user = (account_auth.find_active_user(int(raw)) if raw.isdigit()
            else account_auth.find_active_user_by_uuid(raw))
    if not user:
        # An attributed but inactive/unknown principal must not be treated as
        # an unattributed platform job with access to the owner's registry.
        return {"is_owner": False, "user_uuid": raw, "invalid": True}
    return {"is_owner": user.get("is_owner") is True,
            "user_uuid": str(user.get("user_uuid") or raw), "user_id": user.get("user_id"),
            "name": str(usage_context.get("user_name") or user.get("display_name") or user.get("name") or "")}


def registry_filter(usage_context: Dict[str, Any]) -> Optional[set]:
    """None when the whole registry is open to this call, else the shared ids.

    Sharing is a Local/Development contract for now. Canary and Production keep
    their existing workspace budgets and allocation untouched until the owner
    extends this there deliberately.
    """
    if runtime_env.is_server_environment():
        person = caller(usage_context)
        return None if person is None or person["is_owner"] else set()
    if not runtime_env.is_development():
        return set()
    person = caller(usage_context)
    if person is None or person["is_owner"]:
        return None
    if person.get("invalid"):
        return set()
    return shared_registry_ids()


def registry_allowed(agent_id: str, usage_context: Dict[str, Any]) -> bool:
    allowed = registry_filter(usage_context)
    return allowed is None or str(agent_id) in allowed


def require_registry_access(agent_id: str, usage_context: Dict[str, Any]) -> None:
    if not registry_allowed(agent_id, usage_context):
        raise ContractError("model_not_shared")


# -- the ledger ---------------------------------------------------------------------

def observe(row: Dict[str, Any], usage_context: Dict[str, Any], *, grant: Optional[Dict[str, Any]] = None) -> None:
    """Write one ledger row when a call ran through somebody else's connection."""
    if runtime_env.is_server_environment():
        if grant is None:
            return
        from . import server_model_sharing
        from .contracts import ActorKind, ActorRef, Environment, RequestContext, TenantScope
        from uuid import UUID
        person = caller(usage_context)
        if person is None or person.get("invalid"):
            raise ContractError("model_caller_invalid")
        identity = UUID(person["user_uuid"])
        context = RequestContext(scope=TenantScope(environment=Environment(runtime_env.deployment_environment()),
            workspace_id=str(usage_context.get("workspace_id") or "")), user_uuid=identity,
            actor=ActorRef(kind=ActorKind.HUMAN, actor_id=identity))
        server_model_sharing.observe(context, row, usage_context, grant)
        return
    if not runtime_env.is_development():
        return
    person = caller(usage_context)
    if person is None or person.get("invalid"):
        return
    share = grant
    if share is None:
        if person["is_owner"]:
            return
        share = registry_share(str(row.get("agent_id") or ""))
    if share is None or share["owner_user_uuid"] == person["user_uuid"]:
        return
    request_id = str(row.get("request_id") or "")
    if not request_id:
        return
    source = str(usage_context.get("request_source") or "")
    task = source.removeprefix("agent_world.") if source.startswith("agent_world.") else (
        str(usage_context.get("conversation_id") or source or ""))
    cost = row.get("cost_usd")
    known = row.get("cost_known") is not False and isinstance(cost, (int, float))
    with _db() as db:
        db.execute("""INSERT OR IGNORE INTO calls (request_id, model_id, owner_user_uuid, owner_workspace_id,
                          caller_user_uuid, caller_name, caller_workspace_id, task, agent, purpose, status,
                          input_tokens, output_tokens, cost_usd, cost_known, at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (request_id, share["model_id"], share["owner_user_uuid"], share["owner_workspace_id"],
                    person["user_uuid"], person["name"][:80], str(usage_context.get("workspace_id") or ""),
                    task[:160], str(usage_context.get("acting_agent") or row.get("request_role") or row.get("role") or "")[:80],
                    str(row.get("purpose") or "")[:120], str(row.get("status") or "")[:40],
                    int(row.get("input_tokens") or 0), int(row.get("output_tokens") or 0),
                    float(cost) if known else None, int(known), str(row.get("timestamp_utc") or _now())))


def _summary(rows) -> Dict[str, Any]:
    rows = [dict(row) for row in rows]
    known = [row["cost_usd"] for row in rows if row["cost_known"]]
    return {"calls": len(rows), "failed": sum(1 for row in rows if row["status"] not in {"success", "ok"}),
            "input_tokens": sum(row["input_tokens"] for row in rows),
            "output_tokens": sum(row["output_tokens"] for row in rows),
            "cost_usd": round(sum(known), 6), "cost_unknown_calls": len(rows) - len(known),
            "last_at": max((row["at"] for row in rows), default=None)}


def owner_usage(owner_user_uuid: str, *, limit: int = 50, context=None) -> Dict[str, Any]:
    """Calls other people made through this person's connections, by model and person."""
    if runtime_env.is_server_environment():
        if context is None or str(context.user_uuid) != owner_user_uuid:
            raise ContractError("model_server_scope_required")
        from . import server_model_sharing
        rows = server_model_sharing.calls(context, as_owner=True)
    else:
        with _db(create=False) as db:
            rows = [dict(row) for row in (db.execute(
                "SELECT * FROM calls WHERE owner_user_uuid = ? AND caller_user_uuid != ? ORDER BY at DESC",
                (str(owner_user_uuid), str(owner_user_uuid))) if db is not None else [])]
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    from ..account_lifecycle import deleted_ids, active_preview_identities
    deleted = deleted_ids()
    active_preview = active_preview_identities() if any(row["caller_name"].startswith("Preview ") for row in rows) else None
    for row in rows:
        if row["caller_user_uuid"] in deleted or (active_preview is not None
                and row["caller_name"].startswith("Preview ") and row["caller_user_uuid"] not in active_preview):
            row["caller_name"] = "Удалённый пользователь"
        groups.setdefault((row["model_id"], row["caller_user_uuid"]), []).append(row)
    by_caller = [{"model_id": model_id, "caller_user_uuid": person, "caller_name": items[0]["caller_name"],
                  **_summary(items)} for (model_id, person), items in groups.items()]
    by_caller.sort(key=lambda item: item["last_at"] or "", reverse=True)
    recent = [{key: row[key] for key in ("at", "model_id", "caller_name", "task", "agent", "purpose", "status",
                                          "input_tokens", "output_tokens", "cost_usd")} for row in rows[:limit]]
    return {"total": _summary(rows), "by_caller": by_caller, "recent": recent}


def caller_usage(caller_user_uuid: str, *, context=None) -> Dict[str, Any]:
    """What this person spent through connections other people share."""
    if runtime_env.is_server_environment():
        if context is None or str(context.user_uuid) != caller_user_uuid:
            raise ContractError("model_server_scope_required")
        from . import server_model_sharing
        rows = server_model_sharing.calls(context, as_owner=False)
    else:
        with _db(create=False) as db:
            rows = [dict(row) for row in (db.execute(
                "SELECT * FROM calls WHERE caller_user_uuid = ? AND owner_user_uuid != ? ORDER BY at DESC",
                (str(caller_user_uuid), str(caller_user_uuid))) if db is not None else [])]
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["model_id"], []).append(row)
    return {"total": _summary(rows),
            "by_model": [{"model_id": model_id, **_summary(items)} for model_id, items in groups.items()]}
