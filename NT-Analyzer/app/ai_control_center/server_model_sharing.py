"""PostgreSQL/RLS backing for the existing shared-model contract on servers."""
from __future__ import annotations

from contextlib import contextmanager
import os
from uuid import UUID

from .. import runtime_env
from ..production_storage.core import Scope, PostgresClient
from .contracts import Environment, RequestContext
from .states import ContractError

_TABLES = ("sf_aw_model_shares", "sf_aw_model_share_events", "sf_aw_model_calls", "sf_aw_credentials")


@contextmanager
def _db(context: RequestContext, *, write=False, global_read=False):
    if (context.scope.environment.value != runtime_env.deployment_environment()
            or context.scope.environment not in {Environment.CANARY, Environment.PRODUCTION}):
        raise ContractError("model_server_scope_required")
    if global_read and write:
        raise ContractError("model_server_scope_required")
    scope = Scope.global_service_scope() if global_read else Scope.workspace_scope(context.scope.workspace_id)
    client = PostgresClient(os.environ.get("STRATFORGE_DATABASE_URL", ""), production=True)
    with client.transaction(scope, read_only=not write) as conn:
        role = conn.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        tables = conn.execute("""SELECT c.relrowsecurity,c.relforcerowsecurity,
            pg_has_role(current_user,c.relowner,'USAGE') AS owned
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s) AND c.relkind='r'""", (list(_TABLES),)).fetchall()
        if (not role or role["rolsuper"] or role["rolbypassrls"] or len(tables) != len(_TABLES)
                or any(row["owned"] or not row["relrowsecurity"] or not row["relforcerowsecurity"] for row in tables)):
            raise ContractError("model_server_rls_required")
        conn.execute("SELECT set_config('stratforge.aw_environment',%s,true)", (context.scope.environment.value,))
        conn.execute("SELECT set_config('stratforge.aw_user_uuid',%s,true)", (str(context.user_uuid),))
        yield conn


def _share(row):
    if row is None:
        return None
    value = dict(row)
    for key in ("model_id", "owner_user_uuid"):
        value[key] = str(value[key])
    value["updated_at"] = value["updated_at"].isoformat()
    value["shared"] = bool(value["shared"])
    return value


def get(context, model_id):
    with _db(context, global_read=True) as conn:
        row = conn.execute("SELECT * FROM sf_aw_model_shares WHERE environment=%s AND model_id=%s",
            (context.scope.environment.value, UUID(str(model_id)))).fetchone()
    return _share(row)


def available(context):
    with _db(context, global_read=True) as conn:
        rows = conn.execute("""SELECT * FROM sf_aw_model_shares
            WHERE environment=%s AND shared=TRUE AND owner_user_uuid<>%s
            ORDER BY label,model_id""", (context.scope.environment.value, context.user_uuid)).fetchall()
    return [_share(row) for row in rows]


def require(context, model_id):
    share = get(context, model_id)
    if share is None or not share["shared"] or share["owner_user_uuid"] == str(context.user_uuid):
        raise ContractError("model_share_revoked")
    return share


def set_shared(context, *, model_id, shared, label, provider, model_key, credential_source, registry_id=None):
    if type(shared) is not bool or credential_source != "user_supplied" or registry_id is not None:
        raise ContractError("model_share_invalid")
    identity = UUID(str(model_id))
    # A shared descriptor is visible cross-workspace for invocation, but never
    # writable there. Check it before SELECT FOR UPDATE: PostgreSQL combines
    # SELECT and UPDATE RLS for that query and otherwise hides the foreign row.
    visible = get(context, identity)
    if visible is not None and (visible["owner_user_uuid"] != str(context.user_uuid)
                                or visible["owner_workspace_id"] != context.scope.workspace_id):
        raise ContractError("model_share_owner_mismatch")
    with _db(context, write=True) as conn:
        current = conn.execute("""SELECT * FROM sf_aw_model_shares WHERE environment=%s AND model_id=%s
            FOR UPDATE""", (context.scope.environment.value, identity)).fetchone()
        if current is not None and (current["owner_user_uuid"] != context.user_uuid
                                    or current["owner_workspace_id"] != context.scope.workspace_id):
            raise ContractError("model_share_owner_mismatch")
        if current is not None and current["shared"] == shared:
            return _share(current)
        conn.execute("""INSERT INTO sf_aw_model_shares
            (environment,owner_workspace_id,owner_user_uuid,model_id,label,provider,model_key,
             credential_source,shared,revision)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
            ON CONFLICT(environment,model_id) DO UPDATE SET shared=EXCLUDED.shared,
              label=EXCLUDED.label,provider=EXCLUDED.provider,model_key=EXCLUDED.model_key,
              revision=sf_aw_model_shares.revision+1,updated_at=clock_timestamp()""",
            (context.scope.environment.value, context.scope.workspace_id, context.user_uuid, identity,
             label[:80], provider[:80], model_key[:120], credential_source, shared))
        conn.execute("""INSERT INTO sf_aw_model_share_events
            (environment,owner_workspace_id,owner_user_uuid,model_id,shared)
            VALUES (%s,%s,%s,%s,%s)""", (context.scope.environment.value,
              context.scope.workspace_id, context.user_uuid, identity, shared))
        row = conn.execute("SELECT * FROM sf_aw_model_shares WHERE environment=%s AND model_id=%s",
            (context.scope.environment.value, identity)).fetchone()
    return _share(row)


def history(context, model_id):
    with _db(context) as conn:
        rows = conn.execute("""SELECT shared,at FROM sf_aw_model_share_events
            WHERE environment=%s AND model_id=%s ORDER BY event_id""",
            (context.scope.environment.value, UUID(str(model_id)))).fetchall()
    return [{"shared": bool(row["shared"]), "at": row["at"].isoformat()} for row in rows]


def calls(context, *, as_owner):
    column = "owner_user_uuid" if as_owner else "caller_user_uuid"
    with _db(context, global_read=True) as conn:
        rows = conn.execute("SELECT * FROM sf_aw_model_calls WHERE environment=%s AND " + column +
            "=%s ORDER BY at DESC LIMIT 10000", (context.scope.environment.value, context.user_uuid)).fetchall()
    return [{**dict(row), "model_id": str(row["model_id"]),
             "owner_user_uuid": str(row["owner_user_uuid"]), "caller_user_uuid": str(row["caller_user_uuid"]),
             "at": row["at"].isoformat(), "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None}
            for row in rows]


def observe(context, row, usage_context, share):
    if not share or share["owner_user_uuid"] == str(context.user_uuid):
        return
    request_id = str(row.get("request_id") or "")
    if not request_id:
        raise ContractError("model_usage_request_id_required")
    cost = row.get("cost_usd")
    known = row.get("cost_known") is not False and isinstance(cost, (int, float))
    source = str(usage_context.get("request_source") or "")
    task = source.removeprefix("agent_world.") if source.startswith("agent_world.") else (
        str(usage_context.get("conversation_id") or source or ""))
    with _db(context, write=True) as conn:
        conn.execute("""INSERT INTO sf_aw_model_calls
            (environment,request_id,model_id,owner_user_uuid,owner_workspace_id,
             caller_user_uuid,caller_workspace_id,caller_name,task,agent,purpose,status,
             input_tokens,output_tokens,cost_usd,cost_known)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(environment,request_id) DO NOTHING""",
            (context.scope.environment.value, request_id[:160], UUID(share["model_id"]),
             UUID(share["owner_user_uuid"]), share["owner_workspace_id"], context.user_uuid,
             context.scope.workspace_id, str(usage_context.get("user_name") or "")[:80], task[:160],
             str(usage_context.get("acting_agent") or row.get("request_role") or "")[:80],
             str(row.get("purpose") or "")[:120], str(row.get("status") or "")[:40],
             int(row.get("input_tokens") or 0), int(row.get("output_tokens") or 0),
             float(cost) if known else None, known))
