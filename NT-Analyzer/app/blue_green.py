"""Phase 9: Blue-green Production deployment tooling (fail-closed dry-run).

The Release Center (Phase 8) promotes *exactly one immutable artifact* from
Canary to Production. Phase 9 adds the deployment *mechanism* that actually moves
traffic to that artifact with zero/minimal downtime, a graceful worker drain,
expand→migrate→contract compatible migrations and a proven rollback switch — all
as a **safe, fail-closed dry-run**. No real executor is wired in this phase: no
SSH, systemd, symlink switch, DNS, Cloudflare or database command is ever run,
and the external result of every stage is reported as PENDING/BLOCKED, never as a
real PASS.

Deployment model (owner decision #7): a ``current`` symlink points at one of two
release slots (``blue`` / ``green``). A deployment stages the new immutable
artifact into the idle slot, runs only online-safe *expand* migrations, gates on
green readiness, drains the active (blue) workers, then atomically switches the
``current`` symlink to green. Destructive *contract* migrations are deferred until
green is stable. Rollback is the reverse symlink switch to the previous, known
compatible slot while persistent data is preserved.

Nothing here stores or logs a signing key, token, secret, raw credential or a
credentialed URL. The module is intentionally pure and injectable so Phase 10+
can wire a real blue-green executor behind :func:`deployment_strategy` without
rewriting the Release Center.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import observability, runtime_env, service_readiness


# --------------------------------------------------------------------------- #
# Slots + stages.
# --------------------------------------------------------------------------- #
SLOT_BLUE = "blue"
SLOT_GREEN = "green"
_SLOTS = (SLOT_BLUE, SLOT_GREEN)

STAGE_PREPARE_GREEN = "prepare_green"
STAGE_EXPAND_MIGRATE = "expand_migrate"
STAGE_START_GREEN = "start_green"
STAGE_GREEN_READINESS = "green_readiness"
STAGE_DRAIN_BLUE = "drain_blue"
STAGE_SWITCH_TRAFFIC = "switch_traffic"
STAGE_VERIFY_LIVE = "verify_live"
STAGE_CONTRACT_MIGRATE = "contract_migrate"

STAGE_ORDER = (
    STAGE_PREPARE_GREEN,
    STAGE_EXPAND_MIGRATE,
    STAGE_START_GREEN,
    STAGE_GREEN_READINESS,
    STAGE_DRAIN_BLUE,
    STAGE_SWITCH_TRAFFIC,
    STAGE_VERIFY_LIVE,
    STAGE_CONTRACT_MIGRATE,
)

# Stage/step status vocabulary. A dry-run stage that would contact real
# infrastructure is `pending`; a stage blocked by an incompatibility is
# `blocked`; a purely local planning stage is `dry_run`. `pass`/`fail` are only
# ever set by a real executor, which never runs in this phase.
STATUS_DRY_RUN = "dry_run"
STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"
STATUS_PASS = "pass"
STATUS_FAIL = "fail"

MIGRATION_EXPAND = "expand"
MIGRATION_CONTRACT = "contract"

# The environment variable that would name a real blue-green executor. It is
# never honored as "available" in this phase: a real deployment can never be
# executed here.
_EXECUTOR_ENV = "STRATFORGE_BLUEGREEN_EXECUTOR"

# Default graceful worker-drain deadline when the runtime config does not
# provide one.
_DEFAULT_DRAIN_GRACE_SEC = 90

# Destructive / offline-only SQL fragments that force a migration into the
# *contract* phase (must run after green is stable, never online before switch).
_CONTRACT_PATTERNS = (
    re.compile(r"\bdrop\s+table\b"),
    re.compile(r"\bdrop\s+column\b"),
    re.compile(r"\bdrop\s+constraint\b"),
    re.compile(r"\balter\s+column\b.*\btype\b"),
    re.compile(r"\bset\s+not\s+null\b"),
    re.compile(r"\brename\s+column\b"),
    re.compile(r"\brename\s+to\b"),
    re.compile(r"\btruncate\b"),
    re.compile(r"\bdelete\s+from\b"),
)
# Guarded, idempotent drops that are online-safe (they are immediately
# re-created in the same additive migration), so they never mark a contract.
_ONLINE_SAFE_DROP = re.compile(
    r"\bdrop\s+(policy|index|trigger|function|materialized\s+view)\s+if\s+exists\b"
)


# --------------------------------------------------------------------------- #
# Strategy / executor availability (fail-closed).
# --------------------------------------------------------------------------- #
def _real_executor_name() -> str:
    return str(os.environ.get(_EXECUTOR_ENV) or "").strip().lower()


def _real_executor_requested() -> bool:
    name = _real_executor_name()
    return bool(name) and name not in {"dry_run", "none", "off"}


def deployment_strategy() -> Dict[str, Any]:
    """Return the blue-green strategy status. A real executor is never available
    in this phase, so a real deployment can never be executed here."""
    requested = _real_executor_requested()
    return {
        "strategy": "blue_green_symlink",
        "executor": _real_executor_name() or "dry_run",
        "real_requested": requested,
        # Fail-closed: a real blue-green executor does not exist yet.
        "real_available": False,
        "mode": STATUS_BLOCKED if requested else STATUS_DRY_RUN,
        "slots": list(_SLOTS),
        "current_link": "current",
    }


def other_slot(active_slot: str) -> str:
    active = str(active_slot or "").strip().lower()
    return SLOT_BLUE if active == SLOT_GREEN else SLOT_GREEN


# --------------------------------------------------------------------------- #
# Migration expand / contract compatibility.
# --------------------------------------------------------------------------- #
def _strip_sql_comments(sql: str) -> str:
    lines = []
    for raw in str(sql or "").splitlines():
        line = raw.strip()
        if line.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).lower()


def classify_migration_sql(sql: str) -> Dict[str, Any]:
    """Classify a single migration as online-safe *expand* or offline *contract*."""
    body = _strip_sql_comments(sql)
    # Remove online-safe guarded drops so they never count as destructive.
    scanned = _ONLINE_SAFE_DROP.sub(" ", body)
    reasons: List[str] = []
    for pattern in _CONTRACT_PATTERNS:
        match = pattern.search(scanned)
        if match:
            reasons.append(match.group(0).strip())
    phase = MIGRATION_CONTRACT if reasons else MIGRATION_EXPAND
    return {"phase": phase, "reasons": sorted(set(reasons))}


def _load_migrations() -> List[Dict[str, Any]]:
    from .production_storage.core import MigrationRunner

    return MigrationRunner.migrations()


def classify_migrations(
    migrations: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Split migrations into expand (online-safe) and contract (deferred) phases.

    Blue-green online deployment may only run the *expand* migrations before the
    traffic switch. Any *contract* migration is deferred until green is stable, so
    old (blue) and new (green) code stay schema-compatible during the switch.
    """
    rows = list(migrations) if migrations is not None else _load_migrations()
    expand: List[Dict[str, Any]] = []
    contract: List[Dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or row.get("version") or "")
        classified = classify_migration_sql(str(row.get("sql") or ""))
        entry = {"name": name, "version": row.get("version"), **classified}
        (contract if classified["phase"] == MIGRATION_CONTRACT else expand).append(entry)
    return {
        "expand": expand,
        "contract": contract,
        "online_safe": not contract,
        "blocking": [c["name"] for c in contract],
        "expand_count": len(expand),
        "contract_count": len(contract),
        "pending_known": True,
    }


# --------------------------------------------------------------------------- #
# Worker drain (graceful; dry-run).
# --------------------------------------------------------------------------- #
def _drain_grace_seconds(explicit: Optional[int]) -> int:
    if explicit is not None:
        try:
            return max(1, int(explicit))
        except (TypeError, ValueError):
            return _DEFAULT_DRAIN_GRACE_SEC
    try:
        config = runtime_env.deployment_config(strict=False)
        grace = int(getattr(config, "worker_shutdown_grace_sec", 0) or 0)
        return grace if grace > 0 else _DEFAULT_DRAIN_GRACE_SEC
    except Exception:
        return _DEFAULT_DRAIN_GRACE_SEC


def plan_worker_drain(
    *,
    active_leases: int = 0,
    in_flight_jobs: int = 0,
    queued_jobs: int = 0,
    grace_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Plan a graceful drain of the outgoing (blue) worker pool.

    Intake is stopped first, in-flight NinjaTrader leases and jobs are allowed to
    finish within the grace deadline, and only then is the slot considered
    drained. Nothing is actually stopped in this phase; this returns the plan and
    the wait set. ``forced`` stays False — a dry-run never force-kills work.
    """
    active = max(0, int(active_leases or 0))
    in_flight = max(0, int(in_flight_jobs or 0))
    queued = max(0, int(queued_jobs or 0))
    grace = _drain_grace_seconds(grace_seconds)
    must_wait = active + in_flight
    return {
        "status": STATUS_DRY_RUN,
        "grace_seconds": grace,
        "active_leases": active,
        "in_flight_jobs": in_flight,
        "queued_jobs": queued,
        "must_wait_for": must_wait,
        "intake_stopped": True,
        "drained": must_wait == 0,
        # A dry-run never force-terminates in-flight work; a real executor would
        # only escalate after the grace deadline with explicit owner policy.
        "forced": False,
        "steps": [
            "stop_new_intake",
            "await_active_ninjatrader_leases",
            "await_in_flight_jobs",
            "confirm_zero_in_flight",
        ],
        "note": "graceful drain plan only; no worker was stopped",
    }


# --------------------------------------------------------------------------- #
# Webhook / outbox replay de-duplication.
# --------------------------------------------------------------------------- #
def replay_key(kind: str, external_id: str) -> str:
    """Stable idempotency key for a webhook update or outbox message."""
    return f"{str(kind or '').strip().lower()}:{str(external_id or '').strip()}"


def dedupe_events(
    seen_keys: Sequence[str],
    incoming: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """De-duplicate replayed webhook/outbox events across a blue-green switch.

    During the switch both slots may briefly observe the same Telegram webhook
    update or outbox message. This returns which events are new versus already
    processed so neither slot double-processes a delivery.
    """
    seen = {str(k) for k in seen_keys}
    new_events: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    batch_seen = set(seen)
    for event in incoming:
        kind = str(event.get("kind") or "")
        external_id = str(event.get("external_id") or "")
        key = replay_key(kind, external_id)
        record = {"kind": kind, "external_id": external_id, "key": key}
        if key in batch_seen:
            duplicates.append(record)
        else:
            batch_seen.add(key)
            new_events.append(record)
    return {
        "new": new_events,
        "duplicate": duplicates,
        "new_count": len(new_events),
        "duplicate_count": len(duplicates),
    }


# --------------------------------------------------------------------------- #
# Green readiness gate.
# --------------------------------------------------------------------------- #
def green_readiness(
    *,
    config: Any = None,
    probes: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate the readiness contract the green instance must satisfy.

    The green instance is not actually started in this phase, so the gate is
    reported as ``pending`` (never a real ``pass``); the payload shows exactly
    which control-plane components a real green instance would have to satisfy
    before the traffic switch.
    """
    cfg = config if config is not None else runtime_env.deployment_config(strict=False)
    payload = service_readiness.readiness_payload(cfg, probes=probes)
    return {
        "status": STATUS_PENDING,
        "target_slot": SLOT_GREEN,
        "required_ready": True,
        "contract": {"status": payload.get("status"), "checks": payload.get("checks", {})},
        "note": "green instance not started in this phase; readiness is pending",
    }


# --------------------------------------------------------------------------- #
# Traffic switch + rollback switch (symlink model).
# --------------------------------------------------------------------------- #
def plan_traffic_switch(*, active_slot: str, build_id: str) -> Dict[str, Any]:
    active = str(active_slot or SLOT_BLUE).strip().lower()
    if active not in _SLOTS:
        active = SLOT_BLUE
    target = other_slot(active)
    return {
        "status": STATUS_PENDING,
        "action": "symlink_switch",
        "current_link": "current",
        "from_slot": active,
        "to_slot": target,
        # A release-relative reference only; never an absolute host path.
        "to_release_ref": f"releases/{str(build_id or '').strip()}".rstrip("/"),
        "atomic": True,
        "reversible": True,
        "note": "planned symlink switch only; current link was not moved",
    }


def plan_rollback_switch(
    *, from_slot: str = SLOT_GREEN, to_slot: str = SLOT_BLUE,
    to_build_id: str = "", reason: str = "",
) -> Dict[str, Any]:
    """Plan the reverse symlink switch to the previous known-compatible slot."""
    src = str(from_slot or SLOT_GREEN).strip().lower()
    dst = str(to_slot or SLOT_BLUE).strip().lower()
    if src not in _SLOTS:
        src = SLOT_GREEN
    if dst not in _SLOTS:
        dst = SLOT_BLUE
    return {
        "status": STATUS_PENDING,
        "action": "symlink_switch",
        "current_link": "current",
        "from_slot": src,
        "to_slot": dst,
        "to_release_ref": f"releases/{str(to_build_id or '').strip()}".rstrip("/"),
        "preserves_persistent_data": True,
        "atomic": True,
        "reason": str(reason or "")[:200],
        "note": "planned rollback symlink switch only; no traffic was moved",
    }


# --------------------------------------------------------------------------- #
# Maintenance window records.
# --------------------------------------------------------------------------- #
def maintenance_window(
    *, environment: str, reason: str = "", scheduled_for_utc: str = "",
    kind: str = "deploy",
) -> Dict[str, Any]:
    return {
        "environment": str(environment or ""),
        "kind": str(kind or "deploy"),
        # A record + interface contract only; no banner is shown and no traffic
        # is gated in this phase.
        "state": "planned",
        "reason": str(reason or "")[:200],
        "scheduled_for_utc": str(scheduled_for_utc or ""),
        "note": "maintenance window recorded only; not enforced in this phase",
    }


# --------------------------------------------------------------------------- #
# Deployment plan + fail-closed dry-run executor.
# --------------------------------------------------------------------------- #
def _stage(ordinal: int, stage: str, status: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ordinal": ordinal,
        "stage": stage,
        "status": status,
        "evidence": {k: observability.redact(v, key=k) for k, v in evidence.items()},
    }


def build_deployment_plan(
    *,
    environment: str,
    artifact: Mapping[str, Any],
    migrations: Optional[Sequence[Mapping[str, Any]]] = None,
    drain: Optional[Mapping[str, Any]] = None,
    active_slot: str = SLOT_BLUE,
    scheduled_for_utc: str = "",
) -> Dict[str, Any]:
    """Build the ordered, fail-closed blue-green deployment stage plan."""
    build_id = str(artifact.get("build_id") or "")
    target = other_slot(active_slot)
    # A dry-run has no live target DB, so the *pending* migration set is unknown
    # unless it is passed explicitly. We never classify the whole historical set
    # (which contains already-applied contract migrations) as if it were pending.
    if migrations is None:
        classification = {
            "expand": [], "contract": [], "online_safe": None, "blocking": [],
            "expand_count": 0, "contract_count": 0, "pending_known": False,
        }
    else:
        classification = dict(classify_migrations(migrations))
    drain_ctx = dict(drain or {})
    drain_plan = plan_worker_drain(
        active_leases=int(drain_ctx.get("active_leases") or 0),
        in_flight_jobs=int(drain_ctx.get("in_flight_jobs") or 0),
        queued_jobs=int(drain_ctx.get("queued_jobs") or 0),
        grace_seconds=drain_ctx.get("grace_seconds"),
    )
    readiness = green_readiness()
    switch = plan_traffic_switch(active_slot=active_slot, build_id=build_id)
    window = maintenance_window(
        environment=environment, reason="blue_green_switch",
        scheduled_for_utc=scheduled_for_utc,
    )

    # Expand migrations may run online; a pending contract migration blocks the
    # online expand stage until it is explicitly deferred behind green stability.
    # When the pending set is unknown (dry-run without a target DB), the stage is
    # pending — never fabricated as safe or as blocked.
    if not classification["pending_known"]:
        expand_status = STATUS_PENDING
        contract_status = STATUS_SKIPPED
    elif classification["online_safe"]:
        expand_status = STATUS_DRY_RUN
        contract_status = STATUS_SKIPPED
    else:
        expand_status = STATUS_BLOCKED
        contract_status = STATUS_PENDING

    steps = [
        _stage(1, STAGE_PREPARE_GREEN, STATUS_DRY_RUN, {
            "target_slot": target, "build_id": build_id,
            "artifact_id": artifact.get("artifact_id"),
        }),
        _stage(2, STAGE_EXPAND_MIGRATE, expand_status, {
            "online_safe": classification["online_safe"],
            "expand_count": classification["expand_count"],
            "contract_count": classification["contract_count"],
            "blocking": classification["blocking"],
        }),
        _stage(3, STAGE_START_GREEN, STATUS_PENDING, {"target_slot": target}),
        _stage(4, STAGE_GREEN_READINESS, readiness["status"], {
            "required_ready": readiness["required_ready"],
            "contract": readiness["contract"],
        }),
        _stage(5, STAGE_DRAIN_BLUE, drain_plan["status"], {
            "grace_seconds": drain_plan["grace_seconds"],
            "must_wait_for": drain_plan["must_wait_for"],
            "drained": drain_plan["drained"],
            "forced": drain_plan["forced"],
        }),
        _stage(6, STAGE_SWITCH_TRAFFIC, switch["status"], {
            "from_slot": switch["from_slot"], "to_slot": switch["to_slot"],
            "to_release_ref": switch["to_release_ref"], "atomic": switch["atomic"],
            "maintenance_window": window,
        }),
        _stage(7, STAGE_VERIFY_LIVE, STATUS_PENDING, {"target_slot": target}),
        _stage(8, STAGE_CONTRACT_MIGRATE, contract_status, {
            "deferred_until": "green_stable",
            "contract": classification["blocking"],
        }),
    ]
    blocked = [s["stage"] for s in steps if s["status"] == STATUS_BLOCKED]
    return {
        "strategy": "blue_green_symlink",
        "environment": str(environment or ""),
        "active_slot": str(active_slot or SLOT_BLUE),
        "target_slot": target,
        "build_id": build_id,
        "artifact_id": artifact.get("artifact_id"),
        "migrations": classification,
        "drain": drain_plan,
        "readiness": readiness,
        "traffic_switch": switch,
        "maintenance_window": window,
        "steps": steps,
        "blocked_stages": blocked,
        # "online_safe" here means the online (pre-switch) phase is not blocked.
        "online_safe": not blocked,
    }


def execute_deployment(
    environment: str,
    artifact: Mapping[str, Any],
    *,
    migrations: Optional[Sequence[Mapping[str, Any]]] = None,
    drain: Optional[Mapping[str, Any]] = None,
    active_slot: str = SLOT_BLUE,
    scheduled_for_utc: str = "",
) -> Dict[str, Any]:
    """Fail-closed dry-run blue-green deployment.

    Returns an outcome document compatible with the Release Center deployment
    adapter (``status``/``external_result``/``environment``/``artifact_id``) plus
    the full blue-green plan (slots, ordered steps, maintenance window). A real
    executor is never run: if one is configured the result is ``blocked``,
    otherwise it is a local ``dry_run``. The external result is always PENDING.
    """
    plan = build_deployment_plan(
        environment=environment, artifact=artifact, migrations=migrations,
        drain=drain, active_slot=active_slot, scheduled_for_utc=scheduled_for_utc,
    )
    strategy = deployment_strategy()
    status = STATUS_BLOCKED if strategy["real_requested"] else STATUS_DRY_RUN
    note = (
        "real blue-green executor not available in this phase"
        if strategy["real_requested"]
        else "no external infrastructure was contacted"
    )
    return {
        "status": status,
        "adapter": "blue_green",
        "strategy": strategy["strategy"],
        # The external, real deployment result is never fabricated here.
        "external_result": "pending",
        "environment": str(environment or ""),
        "artifact_id": artifact.get("artifact_id"),
        "active_slot": plan["active_slot"],
        "target_slot": plan["target_slot"],
        "online_safe": plan["online_safe"],
        "blocked_stages": plan["blocked_stages"],
        "steps": plan["steps"],
        "maintenance_window": plan["maintenance_window"],
        "note": note,
    }


def rehearse(
    environment: str,
    artifact: Mapping[str, Any],
    *,
    migrations: Optional[Sequence[Mapping[str, Any]]] = None,
    drain: Optional[Mapping[str, Any]] = None,
    active_slot: str = SLOT_BLUE,
) -> Dict[str, Any]:
    """Dry-run blue-green rehearsal: build and evaluate the full plan without any
    live effect. Nothing is deployed, migrated, drained or switched."""
    plan = build_deployment_plan(
        environment=environment, artifact=artifact, migrations=migrations,
        drain=drain, active_slot=active_slot,
    )
    return {
        "ok": True,
        "rehearsal": True,
        "strategy": plan["strategy"],
        "environment": plan["environment"],
        "active_slot": plan["active_slot"],
        "target_slot": plan["target_slot"],
        "online_safe": plan["online_safe"],
        "blocked_stages": plan["blocked_stages"],
        "migrations": plan["migrations"],
        "drain": plan["drain"],
        "readiness": plan["readiness"],
        "traffic_switch": plan["traffic_switch"],
        "rollback_switch": plan_rollback_switch(
            from_slot=plan["target_slot"], to_slot=plan["active_slot"],
            to_build_id="", reason="rehearsal_rollback_path",
        ),
        "maintenance_window": plan["maintenance_window"],
        "steps": plan["steps"],
        "external_result": "pending",
        "note": "dry-run rehearsal only; no deployment, migration, drain or switch occurred",
    }
