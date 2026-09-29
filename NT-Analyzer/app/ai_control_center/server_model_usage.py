"""Secret-free, cross-workspace spend projection for one shared model ID.

The authoritative workspace budget still reserves every call atomically in
``ai_budgets``.  This reader lets the private registry display/enforce its
existing per-connection daily/monthly limits without using Local JSONL.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from .. import runtime_env
from ..production_storage.core import PostgresClient, Scope, StorageError
from .states import ContractError

_AGENT = re.compile(r"aw_model\.[0-9a-f-]{36}\Z")


def usage_rows(*, agent_id, limit=100_000):
    if (not runtime_env.environment_explicit() or not runtime_env.is_server_environment()
            or not _AGENT.fullmatch(str(agent_id or "")) or limit != 100_000):
        raise ContractError("model_usage_scope_denied")
    now = datetime.now(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    client = PostgresClient(os.environ.get("STRATFORGE_DATABASE_URL", ""), production=True)
    try:
        with client.transaction(Scope.global_service_scope(), read_only=True) as conn:
            role = conn.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            table = conn.execute("""SELECT c.relrowsecurity,c.relforcerowsecurity,
                pg_has_role(current_user,c.relowner,'USAGE') AS owned
                FROM pg_class c WHERE c.oid='sf_ai_usage_events'::regclass""").fetchone()
            if (not role or role["rolsuper"] or role["rolbypassrls"] or not table
                    or table["owned"] or not table["relrowsecurity"] or not table["relforcerowsecurity"]):
                raise ContractError("model_server_rls_required")
            row = conn.execute("""SELECT
                COALESCE(SUM(cost_usd) FILTER (WHERE occurred_at>=%s),0) AS daily_used,
                COALESCE(SUM(cost_usd) FILTER (WHERE occurred_at>=%s),0) AS monthly_used
                FROM sf_ai_usage_events WHERE document->>'agent_id'=%s
                AND status IN ('success','error') AND occurred_at>=%s""",
                (day, month, agent_id, month)).fetchone()
    except StorageError:
        raise ContractError("model_usage_unavailable") from None
    daily = float(row["daily_used"] or 0) if row else 0.0
    monthly = float(row["monthly_used"] or 0) if row else 0.0
    if daily < 0 or monthly < daily:
        raise ContractError("model_usage_unavailable")
    return [{"agent_id": agent_id, "timestamp_utc": now.isoformat(), "cost_usd": daily},
            {"agent_id": agent_id, "timestamp_utc": month.isoformat(), "cost_usd": monthly - daily}]
