"""AI workspace budget enforcement for Production.

Development mode never blocks requests — all budget checks return success.
Production mode is fail-closed: if the budget check cannot reach PostgreSQL,
the request is denied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional

from . import observability, runtime_env
from .production_storage import Scope, StorageError, get_client
from .production_storage.core import _jsonb


_DEV_RESULT: Dict[str, Any] = {
    "ok": True,
    "code": "development_mode",
    "daily_remaining_usd": 9999.0,
    "monthly_remaining_usd": 99999.0,
}


def _is_prod() -> bool:
    # Canary is a real PostgreSQL-backed server contour, not Development.
    return (runtime_env.is_production() or runtime_env.is_canary()) and runtime_env.environment_explicit()


def _check_request_id(request_id: str) -> None:
    length = len(str(request_id or ""))
    if length < 8 or length > 160:
        raise ValueError("request_id must be 8–160 characters.")


def _clean_cost(value: float) -> float:
    try:
        cost = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("estimated_cost_usd must be numeric.") from exc
    if not math.isfinite(cost) or cost < 0 or cost > 10_000:
        raise ValueError("estimated_cost_usd must be between 0 and 10000.")
    return cost


def _budget_decision(
    conn: Any,
    workspace_id: str,
    estimated_cost_usd: float,
    *,
    lock: bool,
    exclude_request_id: str = "",
) -> Dict[str, Any]:
    budget_query = """
        SELECT daily_limit_usd, monthly_limit_usd, enabled
        FROM sf_ai_workspace_budgets WHERE workspace_id=%s
    """
    if lock:
        budget_query += " FOR UPDATE"
    budget = conn.execute(budget_query, (workspace_id,)).fetchone()
    if not budget:
        return {"ok": False, "code": "no_budget_configured",
                "daily_remaining_usd": 0.0, "monthly_remaining_usd": 0.0}
    if not budget["enabled"]:
        return {"ok": False, "code": "budget_disabled",
                "daily_remaining_usd": 0.0, "monthly_remaining_usd": 0.0}

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = conn.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN occurred_at>=%s THEN cost_usd ELSE 0 END),0) AS daily_used,
             COALESCE(SUM(CASE WHEN occurred_at>=%s THEN cost_usd ELSE 0 END),0) AS monthly_used
           FROM sf_ai_usage_events
           WHERE workspace_id=%s AND status IN ('success','error')""",
        (start_of_day, start_of_month, workspace_id),
    ).fetchone()
    daily_used = float(usage["daily_used"]) if usage else 0.0
    monthly_used = float(usage["monthly_used"]) if usage else 0.0

    pending_query = """
        SELECT COALESCE(SUM(estimated_cost_usd),0) AS pending
        FROM sf_ai_reservations
        WHERE workspace_id=%s AND expires_at>clock_timestamp()
    """
    pending_params: tuple[Any, ...] = (workspace_id,)
    if exclude_request_id:
        pending_query += " AND request_id<>%s"
        pending_params += (exclude_request_id,)
    pending = conn.execute(pending_query, pending_params).fetchone()
    pending_cost = float(pending["pending"]) if pending else 0.0

    daily_limit = float(budget["daily_limit_usd"])
    monthly_limit = float(budget["monthly_limit_usd"])
    daily_remaining = max(0.0, daily_limit - daily_used - pending_cost)
    monthly_remaining = max(0.0, monthly_limit - monthly_used - pending_cost)
    if daily_used + pending_cost + estimated_cost_usd > daily_limit:
        return {"ok": False, "code": "daily_budget_exceeded",
                "daily_remaining_usd": daily_remaining,
                "monthly_remaining_usd": monthly_remaining}
    if monthly_used + pending_cost + estimated_cost_usd > monthly_limit:
        return {"ok": False, "code": "monthly_budget_exceeded",
                "daily_remaining_usd": daily_remaining,
                "monthly_remaining_usd": monthly_remaining}
    return {"ok": True, "code": "budget_ok",
            "daily_remaining_usd": round(daily_remaining - estimated_cost_usd, 8),
            "monthly_remaining_usd": round(monthly_remaining - estimated_cost_usd, 8)}


def check_budget(workspace_id: str, estimated_cost_usd: float) -> Dict[str, Any]:
    """Return whether the workspace can afford ``estimated_cost_usd``."""
    if not _is_prod():
        return dict(_DEV_RESULT)
    try:
        cost = _clean_cost(estimated_cost_usd)
        scope = Scope(workspace_id=str(workspace_id))
        with get_client().transaction(scope, read_only=True) as conn:
            return _budget_decision(conn, str(workspace_id), cost, lock=False)
    except (StorageError, ValueError):
        # Fail-closed: deny if storage is unreachable.
        return {"ok": False, "code": "storage_unavailable",
                "daily_remaining_usd": 0.0, "monthly_remaining_usd": 0.0}


def reserve(
    request_id: str,
    workspace_id: str,
    user_id: int,
    provider: str,
    model: str,
    role: str,
    estimated_cost_usd: float,
    prompt_sha256: str,
    ttl_sec: int = 300,
) -> Dict[str, Any]:
    """Atomically admit and reserve a workspace budget before provider use."""
    _check_request_id(request_id)
    if not _is_prod():
        return {"ok": True, "code": "development_mode",
                "reservation_id": "air_" + uuid.uuid4().hex}
    reservation_id = "air_" + uuid.uuid4().hex
    try:
        ttl = max(10, min(int(ttl_sec), 3600))
        cost = _clean_cost(estimated_cost_usd)
        workspace = str(workspace_id or "").strip()
        user = int(user_id)
        clean_provider = str(provider or "").strip()[:80]
        clean_model = str(model or "").strip()[:160]
        clean_role = str(role or "").strip()[:80]
        clean_prompt_hash = str(prompt_sha256 or "").strip().lower()
        if not workspace or user <= 0:
            return {"ok": False, "code": "invalid_scope"}
        if (
            not clean_provider or not clean_model or not clean_role
            or not re.fullmatch(r"[0-9a-f]{64}", clean_prompt_hash)
        ):
            return {"ok": False, "code": "invalid_request"}
        scope = Scope(workspace_id=workspace)
        with get_client().transaction(scope) as conn:
            # Migration 0003 backfills and installs a creation trigger.  This
            # idempotent insert also protects workspaces created by an older
            # app process during a rolling upgrade.
            conn.execute(
                """INSERT INTO sf_ai_workspace_budgets(workspace_id)
                   VALUES(%s) ON CONFLICT(workspace_id) DO NOTHING""",
                (workspace,),
            )
            decision = _budget_decision(
                conn, workspace, cost, lock=True, exclude_request_id=str(request_id),
            )
            if not decision["ok"]:
                return decision
            existing = conn.execute(
                """SELECT reservation_id,workspace_id,user_id,provider,model,
                          role,estimated_cost_usd,prompt_sha256
                   FROM sf_ai_reservations WHERE request_id=%s FOR UPDATE""",
                (str(request_id),),
            ).fetchone()
            if existing:
                same_request = (
                    str(existing["workspace_id"]) == workspace
                    and int(existing["user_id"]) == user
                    and str(existing["provider"]) == clean_provider
                    and str(existing["model"]) == clean_model
                    and str(existing["role"]) == clean_role
                    and abs(float(existing["estimated_cost_usd"]) - cost) < 1e-9
                    and str(existing["prompt_sha256"]) == clean_prompt_hash
                )
                if not same_request:
                    return {"ok": False, "code": "idempotency_conflict"}
                conn.execute(
                    """UPDATE sf_ai_reservations SET
                         expires_at=clock_timestamp()+(%s*interval '1 second')
                       WHERE request_id=%s""",
                    (ttl, str(request_id)),
                )
                return {
                    **decision,
                    "code": "reserved",
                    "reservation_id": str(existing["reservation_id"]),
                    "idempotent_replay": True,
                }
            inserted = conn.execute(
                """INSERT INTO sf_ai_reservations(
                     reservation_id,request_id,workspace_id,user_id,
                     provider,model,role,estimated_cost_usd,prompt_sha256,expires_at
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+(%s*interval '1 second'))
                   RETURNING reservation_id""",
                (reservation_id, str(request_id), workspace,
                 user, clean_provider, clean_model,
                 clean_role, cost, clean_prompt_hash, ttl),
            ).fetchone()
        return {
            **decision,
            "code": "reserved",
            "reservation_id": str(inserted["reservation_id"]),
        }
    except (StorageError, TypeError, ValueError):
        return {"ok": False, "code": "storage_unavailable"}


def record_usage(
    request_id: str,
    workspace_id: str,
    user_id: int,
    provider: str,
    model: str,
    role: str,
    purpose: str,
    status: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    prompt_sha256: str,
    document: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Record actual AI usage, clearing any prior reservation."""
    _check_request_id(request_id)
    if not _is_prod():
        return {"ok": True, "code": "development_mode"}
    valid_status = status if status in {"success", "error", "blocked", "cache_hit"} else "error"
    clean = observability.redact(dict(document or {}))
    try:
        workspace = str(workspace_id or "").strip()
        user = int(user_id)
        if not workspace or user <= 0:
            return {"ok": False, "code": "invalid_scope"}
        clean_provider = str(provider or "").strip()[:80]
        clean_model = str(model or "").strip()[:160]
        clean_role = str(role or "").strip()[:80]
        clean_purpose = str(purpose or "").strip()[:120]
        clean_prompt_hash = str(prompt_sha256 or "").strip().lower()
        if (
            not clean_provider or not clean_model or not clean_role
            or not clean_purpose
            or not re.fullmatch(r"[0-9a-f]{64}", clean_prompt_hash)
        ):
            return {"ok": False, "code": "invalid_usage"}
        clean_input = max(0, int(input_tokens))
        clean_output = max(0, int(output_tokens))
        if clean_input > 2_000_000_000 or clean_output > 2_000_000_000:
            return {"ok": False, "code": "invalid_usage"}
        clean_cost = _clean_cost(cost_usd)
        scope = Scope(workspace_id=workspace)
        with get_client().transaction(scope) as conn:
            inserted = conn.execute(
                """INSERT INTO sf_ai_usage_events(
                     request_id,workspace_id,user_id,provider,model,role,
                     purpose,status,input_tokens,output_tokens,cost_usd,
                     prompt_sha256,document
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(request_id) DO UPDATE SET
                     status=EXCLUDED.status,cost_usd=EXCLUDED.cost_usd,
                     input_tokens=EXCLUDED.input_tokens,
                     output_tokens=EXCLUDED.output_tokens,
                     document=EXCLUDED.document
                   WHERE sf_ai_usage_events.workspace_id=EXCLUDED.workspace_id
                     AND sf_ai_usage_events.user_id=EXCLUDED.user_id
                     AND sf_ai_usage_events.provider=EXCLUDED.provider
                     AND sf_ai_usage_events.model=EXCLUDED.model
                     AND sf_ai_usage_events.role=EXCLUDED.role
                     AND sf_ai_usage_events.purpose=EXCLUDED.purpose
                     AND sf_ai_usage_events.status=EXCLUDED.status
                     AND sf_ai_usage_events.input_tokens=EXCLUDED.input_tokens
                     AND sf_ai_usage_events.output_tokens=EXCLUDED.output_tokens
                     AND sf_ai_usage_events.cost_usd=EXCLUDED.cost_usd
                     AND sf_ai_usage_events.prompt_sha256=EXCLUDED.prompt_sha256
                     AND sf_ai_usage_events.document=EXCLUDED.document
                   RETURNING request_id""",
                (str(request_id), workspace, user,
                 clean_provider, clean_model, clean_role,
                 clean_purpose, valid_status,
                 clean_input, clean_output,
                 clean_cost, clean_prompt_hash,
                 _jsonb(clean)),
            ).fetchone()
            if not inserted:
                return {"ok": False, "code": "idempotency_conflict"}
            conn.execute(
                "DELETE FROM sf_ai_reservations WHERE request_id=%s",
                (str(request_id),),
            )
        return {"ok": True, "code": "recorded"}
    except StorageError:
        return {"ok": False, "code": "storage_unavailable"}
    except (TypeError, ValueError, OverflowError):
        return {"ok": False, "code": "invalid_usage"}


def cancel_reservation(request_id: str, workspace_id: str = "") -> bool:
    """Remove an unexpired reservation."""
    _check_request_id(request_id)
    if not _is_prod():
        return True
    workspace = str(workspace_id or "").strip()
    if not workspace:
        return False
    try:
        with get_client().transaction(Scope.workspace_scope(workspace)) as conn:
            row = conn.execute(
                """DELETE FROM sf_ai_reservations
                   WHERE request_id=%s AND workspace_id=%s
                   RETURNING request_id""",
                (str(request_id), workspace),
            ).fetchone()
        return bool(row)
    except StorageError:
        return False


def workspace_usage_summary(workspace_id: str) -> Dict[str, Any]:
    """Return daily and monthly cost totals for a workspace."""
    if not _is_prod():
        return {"ok": True, "code": "development_mode",
                "daily_used_usd": 0.0, "monthly_used_usd": 0.0,
                "daily_requests": 0, "monthly_requests": 0}
    try:
        scope = Scope(workspace_id=str(workspace_id))
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with get_client().transaction(scope, read_only=True) as conn:
            row = conn.execute(
                """SELECT
                     COALESCE(SUM(CASE WHEN occurred_at>=%s THEN cost_usd ELSE 0 END),0) AS daily_usd,
                     COALESCE(SUM(CASE WHEN occurred_at>=%s THEN cost_usd ELSE 0 END),0) AS monthly_usd,
                     COALESCE(SUM(CASE WHEN occurred_at>=%s THEN 1 ELSE 0 END),0) AS daily_n,
                     COALESCE(SUM(CASE WHEN occurred_at>=%s THEN 1 ELSE 0 END),0) AS monthly_n
                   FROM sf_ai_usage_events
                   WHERE workspace_id=%s AND status IN ('success','error')""",
                (start_of_day, start_of_month, start_of_day, start_of_month,
                 str(workspace_id)),
            ).fetchone()
        return {
            "ok": True,
            "daily_used_usd": round(float(row["daily_usd"]), 8),
            "monthly_used_usd": round(float(row["monthly_usd"]), 8),
            "daily_requests": int(row["daily_n"]),
            "monthly_requests": int(row["monthly_n"]),
        }
    except StorageError:
        return {"ok": False, "code": "storage_unavailable"}


def _main(argv: Optional[list[str]] = None) -> int:
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-budget", dest="check_workspace")
    parser.add_argument("--cost", type=float, default=0.0)
    parser.add_argument("--usage-summary", dest="summary_workspace")
    parser.add_argument("--sweep", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check_workspace:
            out = check_budget(args.check_workspace, args.cost)
        elif args.summary_workspace:
            out = workspace_usage_summary(args.summary_workspace)
        elif args.sweep:
            if _is_prod():
                with get_client().transaction(Scope.global_service_scope()) as conn:
                    conn.execute(
                        "DELETE FROM sf_ai_reservations WHERE expires_at<clock_timestamp()"
                    )
            out = {"ok": True, "code": "swept"}
        else:
            parser.print_help()
            return 1
        print(json.dumps(out, ensure_ascii=False, default=str, sort_keys=True))
        return 0
    except StorageError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
