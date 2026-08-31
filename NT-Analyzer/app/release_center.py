"""Phase 8: Release Center — immutable-artifact promotion control plane.

A release candidate is created from an explicitly selected clean commit, built
once into an immutable artifact (manifest + ECDSA signature + SHA-256 + build id),
deployed to Canary, checked, owner-approved and then promoted to Production as
*exactly the same artifact* — never rebuilt. The module is a strict, idempotent,
auditable state machine:

    draft -> building -> built -> signed -> canary_deploying -> canary_checking
    -> canary_passed -> approved_for_production -> production_scheduled
    -> production_deploying -> production_live

Failure / terminal states: build_failed, canary_failed, production_failed,
rolled_back, superseded, cancelled.

Exact-artifact invariants (enforced here and by tests): a dirty worktree can
never produce a publishable candidate; an artifact is immutable after build;
Canary and Production reference the same frozen fingerprint (artifact SHA,
manifest SHA, commit SHA, build id); any rebuild between Canary and Production is
rejected; an altered manifest or invalid/missing signature is rejected; a
Production promotion requires the matching Canary pass, a separate owner approval
and a fresh step-up; rollback only targets a known compatible artifact.

Without an explicitly configured executor the deployment adapter is a safe,
fail-closed dry-run.  The opt-in ``stage9_ssh`` adapter builds with the protected
host-side production signing key and deploys the frozen artifact through the
checked-in blue-green scripts. Missing infrastructure is reported as
PENDING/BLOCKED and never as PASS. No signing key, token, secret, host-local path
or raw credential is stored in the public document, audit or notifications.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import account_auth, blue_green, observability, release_executor, runtime_env, secure_store


# --------------------------------------------------------------------------- #
# State machine.
# --------------------------------------------------------------------------- #
STATE_DRAFT = "draft"
STATE_BUILDING = "building"
STATE_BUILT = "built"
STATE_SIGNED = "signed"
STATE_CANARY_DEPLOYING = "canary_deploying"
STATE_CANARY_CHECKING = "canary_checking"
STATE_CANARY_PASSED = "canary_passed"
STATE_APPROVED = "approved_for_production"
STATE_PRODUCTION_SCHEDULED = "production_scheduled"
STATE_PRODUCTION_DEPLOYING = "production_deploying"
STATE_PRODUCTION_LIVE = "production_live"

STATE_BUILD_FAILED = "build_failed"
STATE_CANARY_FAILED = "canary_failed"
STATE_PRODUCTION_FAILED = "production_failed"
STATE_ROLLED_BACK = "rolled_back"
STATE_SUPERSEDED = "superseded"
STATE_CANCELLED = "cancelled"

TERMINAL_STATES = frozenset({
    STATE_PRODUCTION_LIVE, STATE_ROLLED_BACK, STATE_SUPERSEDED, STATE_CANCELLED,
})
FAILURE_STATES = frozenset({
    STATE_BUILD_FAILED, STATE_CANARY_FAILED, STATE_PRODUCTION_FAILED,
})

# Allowed forward transitions. Any transition not listed is rejected, which also
# rejects skipped and reverse transitions.
_TRANSITIONS: Dict[str, frozenset] = {
    STATE_DRAFT: frozenset({STATE_BUILDING, STATE_CANCELLED, STATE_SUPERSEDED}),
    STATE_BUILDING: frozenset({STATE_BUILT, STATE_BUILD_FAILED}),
    STATE_BUILT: frozenset({STATE_SIGNED, STATE_BUILD_FAILED, STATE_CANCELLED, STATE_SUPERSEDED}),
    STATE_SIGNED: frozenset({STATE_CANARY_DEPLOYING, STATE_CANCELLED, STATE_SUPERSEDED}),
    STATE_CANARY_DEPLOYING: frozenset({STATE_CANARY_CHECKING, STATE_CANARY_FAILED}),
    STATE_CANARY_CHECKING: frozenset({STATE_CANARY_PASSED, STATE_CANARY_FAILED}),
    STATE_CANARY_PASSED: frozenset({STATE_APPROVED, STATE_CANCELLED, STATE_SUPERSEDED}),
    STATE_APPROVED: frozenset({
        STATE_PRODUCTION_SCHEDULED, STATE_PRODUCTION_DEPLOYING, STATE_CANCELLED,
    }),
    STATE_PRODUCTION_SCHEDULED: frozenset({
        STATE_PRODUCTION_DEPLOYING, STATE_CANCELLED,
    }),
    STATE_PRODUCTION_DEPLOYING: frozenset({STATE_PRODUCTION_LIVE, STATE_PRODUCTION_FAILED}),
    STATE_PRODUCTION_LIVE: frozenset({STATE_ROLLED_BACK}),
    STATE_BUILD_FAILED: frozenset({STATE_BUILDING, STATE_CANCELLED, STATE_SUPERSEDED}),
    STATE_CANARY_FAILED: frozenset({STATE_CANARY_DEPLOYING, STATE_CANCELLED, STATE_SUPERSEDED}),
    STATE_PRODUCTION_FAILED: frozenset({STATE_PRODUCTION_DEPLOYING, STATE_ROLLED_BACK, STATE_CANCELLED}),
}

ENVIRONMENT_CANARY = "canary"
ENVIRONMENT_PRODUCTION = "production"

CHECK_PASS = "pass"
CHECK_FAIL = "fail"
CHECK_PENDING = "pending"
CHECK_BLOCKED = "blocked"

# Critical step-up actions (bound to security_devices challenges).
ACTION_DEPLOY_CANARY = "release_deploy_canary"
ACTION_APPROVE_PRODUCTION = "release_approve_production"
ACTION_PROMOTE_PRODUCTION = "release_promote_production"
ACTION_ROLLBACK_PRODUCTION = "release_rollback_production"
#: Replacing a platform credential is a step-up action in its own right, and
#: deliberately not one the owner session alone may perform.
ACTION_REPLACE_PLATFORM_SECRET = "replace_platform_secret"

STEP_UP_ACTIONS = (
    ACTION_DEPLOY_CANARY, ACTION_APPROVE_PRODUCTION,
    ACTION_PROMOTE_PRODUCTION, ACTION_ROLLBACK_PRODUCTION,
    ACTION_REPLACE_PLATFORM_SECRET,
)
STEP_UP_GRANT_TTL_SEC = 10 * 60

NOTIFICATION_KINDS = (
    "scheduled_update", "warn_5m", "warn_60s", "deploy_started",
    "deploy_successful", "deploy_failed", "rollback", "reload_available",
)

# Scheduling: explicit offsets only. "after market close" stays disabled until a
# real market-calendar provider (timezone, holidays, early-close policy) is
# approved, so it is never emulated with a hard-coded time.
SCHEDULE_OFFSETS_SEC = {"now": 0, "in_5m": 5 * 60, "in_15m": 15 * 60}
MARKET_CLOSE_OPTION = {
    "id": "after_market_close",
    "available": False,
    "reason": (
        "Требуется утверждённый источник рыночного календаря (таймзона, праздники, "
        "ранние закрытия). До этого используйте явное время."
    ),
}

SCHEMA_VERSION = 1
_STORE_KEY = "releases"
_MAGIC = b"NTARELEASE1\n"
_LOCK = threading.RLock()
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{32,128}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class ReleaseCenterError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


# --------------------------------------------------------------------------- #
# Store I/O (mirror the Connector encrypted-document pattern).
# --------------------------------------------------------------------------- #
def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return runtime_env.data_path("integrations", "releases.dpapi", project_root=_root())


def _audit_path() -> Path:
    return runtime_env.data_path("audit", "release-center.jsonl", project_root=_root())


def _now() -> float:
    return time.time()


def _now_iso(epoch: Optional[float] = None) -> str:
    value = time.time() if epoch is None else float(epoch)
    return datetime.fromtimestamp(value, timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _default_doc() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "candidates": [],
        "artifacts": [],
        "deployments": [],
        "checks": [],
        "approvals": [],
        "rollbacks": [],
        "notifications": [],
        "events": [],
        # Phase 9: blue-green deployment step log + maintenance-window records.
        "deploy_steps": [],
        "maintenance": [],
        "rehearsals": [],
        "idempotency": {},
        "seq": 0,
    }


def _normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        return _default_doc()
    base = _default_doc()
    for key in ("candidates", "artifacts", "deployments", "checks", "approvals",
                "rollbacks", "notifications", "events", "deploy_steps",
                "maintenance", "rehearsals"):
        rows = doc.get(key)
        base[key] = rows if isinstance(rows, list) else []
    base["idempotency"] = doc.get("idempotency") if isinstance(doc.get("idempotency"), dict) else {}
    try:
        base["seq"] = int(doc.get("seq") or 0)
    except (TypeError, ValueError):
        base["seq"] = 0
    return base


def _read_doc() -> Dict[str, Any]:
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            doc = storage_router.read_document(_STORE_KEY, _default_doc())
        except StorageError as exc:
            raise ReleaseCenterError(
                f"Production release repository unavailable ({exc.code}).",
                503, code=exc.code,
            ) from None
        return _normalize(doc)
    path = _store_path()
    if not path.is_file():
        return _default_doc()
    try:
        raw = path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise ReleaseCenterError("Неизвестный формат release store.", 500, code="store_format")
        import base64
        encrypted = base64.b64decode(raw[len(_MAGIC):], validate=True)
        doc = json.loads(secure_store._unprotect(encrypted).decode("utf-8"))
    except ReleaseCenterError:
        raise
    except secure_store.SecureStoreError as exc:
        raise ReleaseCenterError(str(exc), 503, code="store_unavailable") from None
    except Exception as exc:
        raise ReleaseCenterError(
            f"Release store повреждён: {type(exc).__name__}.", 500, code="store_corrupt",
        ) from None
    return _normalize(doc)


def _write_doc(doc: Dict[str, Any]) -> None:
    doc = _normalize(doc)
    if runtime_env.is_production() and runtime_env.environment_explicit():
        from . import storage_router
        from .production_storage import StorageError
        try:
            storage_router.write_document(_STORE_KEY, doc)
            return
        except StorageError as exc:
            raise ReleaseCenterError(
                f"Production release repository write denied ({exc.code}).",
                503, code=exc.code,
            ) from None
    if not secure_store.available():
        raise ReleaseCenterError(
            "Encrypted release repository недоступен.", 503, code="store_unavailable",
        )
    import base64
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        protected = secure_store._protect(plaintext)
    except secure_store.SecureStoreError as exc:
        raise ReleaseCenterError(str(exc), 503, code="store_unavailable") from None
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
            storage_router.append_audit("release_center", event, safe)
            return
        except StorageError:
            return
    row = {"timestamp_utc": _now_iso(), "source": "release_center", "event": str(event), **safe}
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


# --------------------------------------------------------------------------- #
# Identity + helpers.
# --------------------------------------------------------------------------- #
def _actor_uuid(actor: Any) -> str:
    try:
        return account_auth.user_uuid_for_legacy_id(_actor_id(actor)) or ""
    except Exception:
        return ""


def _actor_id(actor: Any) -> int:
    if isinstance(actor, dict):
        value = actor.get("user_id")
    else:
        value = actor
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


def _fingerprint(source: Dict[str, Any]) -> Dict[str, str]:
    return {
        "artifact_id": str(source.get("artifact_id") or ""),
        "artifact_sha256": str(source.get("artifact_sha256") or ""),
        "manifest_sha256": str(source.get("manifest_sha256") or ""),
        "git_commit_sha": str(source.get("git_commit_sha") or ""),
        "build_id": str(source.get("build_id") or ""),
    }


def _validate_idempotency_key(value: Any) -> str:
    key = str(value or "").strip()
    if not (8 <= len(key) <= 160):
        raise ReleaseCenterError(
            "idempotency_key должен быть длиной 8..160 символов.", 400, code="idempotency_invalid",
        )
    return key


# --------------------------------------------------------------------------- #
# Git state (injectable for deterministic tests).
# --------------------------------------------------------------------------- #
def _git_state() -> Tuple[str, bool]:
    """Return (HEAD commit sha, dirty). Overridden in tests via monkeypatch."""
    import subprocess
    root = _root()
    try:
        # git reports paths as UTF-8; the console locale would corrupt a
        # non-ASCII checkout path and turn a clean tree into a dirty one.
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
    except (OSError, ValueError):
        return "", True
    return revision, bool(status)


# --------------------------------------------------------------------------- #
# Step-up (reuse the Phase 4-5 security-challenge grants; owner is exempt).
# --------------------------------------------------------------------------- #
def _require_step_up(actor: Any, *, action: str, challenge_id: str = "",
                     allow_owner_exempt: bool = True) -> Dict[str, Any]:
    """Confirm a recent, unused step-up grant for this action.

    The owner is exempt for release actions, where the account itself is the
    authority. Replacing a platform secret is different: possession of the
    session is not meant to be enough, so that caller asks for the strict form
    and no exemption applies.
    """
    if action not in STEP_UP_ACTIONS:
        raise ReleaseCenterError("Недопустимое step-up действие.", 400, code="action_invalid")
    if allow_owner_exempt and _is_owner(actor):
        return {"ok": True, "owner_exempt": True, "action": action}
    from . import security_devices
    environment = runtime_env.deployment_environment()
    uid = _actor_id(actor)
    user_uuid = _actor_uuid(actor)
    if not user_uuid:
        raise ReleaseCenterError("Профиль без UUID identity.", 409, code="identity_missing")
    now = _now()
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        grant = None
        for row in reversed(doc.get("security_challenges") or []):
            if not isinstance(row, dict):
                continue
            if str(row.get("purpose") or "") != security_devices.PURPOSE_STEP_UP:
                continue
            if str(row.get("status") or "") != "consumed":
                continue
            if str(row.get("action") or "") != action:
                continue
            if row.get("step_up_used_at"):
                continue
            if str(row.get("user_uuid") or "") != user_uuid:
                continue
            if str(row.get("environment") or "") != environment:
                continue
            if challenge_id and str(row.get("challenge_id") or "") != challenge_id:
                continue
            consumed = _iso_to_epoch(row.get("consumed_at_utc"))
            if consumed and now > consumed + STEP_UP_GRANT_TTL_SEC:
                continue
            grant = row
            break
        if grant is None:
            raise ReleaseCenterError(
                "Требуется подтверждение действия (step-up).", 403, code="step_up_required",
            )
        grant["step_up_used_at"] = account_auth._now_iso()
        account_auth._write_doc(doc)
        used = str(grant.get("challenge_id") or "")
    return {"ok": True, "action": action, "challenge_id": used}


def begin_step_up(actor: Any, *, action: str, provider: str = "", ip: str = "", user_agent: str = "") -> Dict[str, Any]:
    """Start a step-up challenge for a critical Release Center action."""
    if action not in STEP_UP_ACTIONS:
        raise ReleaseCenterError("Недопустимое step-up действие.", 400, code="action_invalid")
    from . import security_devices
    try:
        out = security_devices.create_challenge(
            user_id=_actor_id(actor), purpose=security_devices.PURPOSE_STEP_UP,
            action=action, provider=provider, ip=ip, user_agent=user_agent,
        )
    except security_devices.SecurityDeviceError as exc:
        raise ReleaseCenterError(str(exc), exc.status, code=exc.code) from None
    out["action"] = action
    return out


def _iso_to_epoch(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


# --------------------------------------------------------------------------- #
# Transition + events.
# --------------------------------------------------------------------------- #
def _transition(
    doc: Dict[str, Any], candidate: Dict[str, Any], to_state: str, *,
    actor: Any, event_type: str, evidence: Optional[Dict[str, Any]] = None,
    idempotency_key: str = "", failure_reason: str = "",
) -> None:
    from_state = str(candidate.get("state") or "")
    if to_state != from_state and to_state not in _TRANSITIONS.get(from_state, frozenset()):
        raise ReleaseCenterError(
            f"Недопустимый переход {from_state} -> {to_state}.",
            409, code="invalid_transition",
        )
    candidate["state"] = to_state
    candidate["updated_at_utc"] = _now_iso()
    if failure_reason:
        candidate["failure_reason"] = str(failure_reason)[:500]
    doc["seq"] = int(doc.get("seq") or 0) + 1
    doc["events"].append({
        "event_id": _new_id("rev"),
        "candidate_id": candidate.get("candidate_id"),
        "event_type": str(event_type),
        "from_state": from_state,
        "to_state": to_state,
        "actor_user_uuid": _actor_uuid(actor),
        "actor_legacy_id": _actor_id(actor),
        "idempotency_key": str(idempotency_key or ""),
        "seq": doc["seq"],
        "document": {k: observability.redact(v, key=k) for k, v in (evidence or {}).items()},
        "created_at_utc": _now_iso(),
    })
    _audit(
        event_type, candidate_id=candidate.get("candidate_id"),
        from_state=from_state, to_state=to_state,
        actor_id=_actor_id(actor), **(evidence or {}),
    )


def _idempotent(doc: Dict[str, Any], key: str, scope: str) -> Optional[Dict[str, Any]]:
    record = doc.get("idempotency", {}).get(f"{scope}:{key}")
    return record if isinstance(record, dict) else None


def _remember(doc: Dict[str, Any], key: str, scope: str, result: Dict[str, Any]) -> None:
    doc.setdefault("idempotency", {})[f"{scope}:{key}"] = result


# --------------------------------------------------------------------------- #
# Public views.
# --------------------------------------------------------------------------- #
def _candidate_summary(doc: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    artifact = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or "")) or {}
    deployments = [d for d in doc["deployments"] if str(d.get("candidate_id") or "") == str(candidate.get("candidate_id") or "")]
    canary = next((d for d in deployments if d.get("environment") == ENVIRONMENT_CANARY), {})
    production = next((d for d in deployments if d.get("environment") == ENVIRONMENT_PRODUCTION), {})
    return {
        "candidate_id": candidate.get("candidate_id"),
        "app_version": candidate.get("app_version"),
        "release_channel": candidate.get("release_channel"),
        "git_commit_sha": candidate.get("git_commit_sha"),
        "state": candidate.get("state"),
        "artifact_id": candidate.get("artifact_id") or "",
        "artifact_sha256": artifact.get("artifact_sha256") or "",
        "manifest_sha256": artifact.get("manifest_sha256") or "",
        "build_id": artifact.get("build_id") or "",
        "signature_status": artifact.get("signature_status") or "",
        "dirty": bool(artifact.get("dirty")) if artifact else False,
        "canary_state": canary.get("state") or "",
        "production_state": production.get("state") or "",
        "failure_reason": candidate.get("failure_reason") or "",
        "created_at_utc": candidate.get("created_at_utc"),
        "updated_at_utc": candidate.get("updated_at_utc"),
    }


def list_releases() -> Dict[str, Any]:
    doc = _read_doc()
    rows = sorted(doc["candidates"], key=lambda c: str(c.get("created_at_utc") or ""), reverse=True)
    return {
        "ok": True,
        "environment": runtime_env.deployment_environment(),
        "adapter": _adapter_status(),
        "blue_green": blue_green.deployment_strategy(),
        "schedule_options": schedule_options(),
        "notification_preview": notification_preview(),
        "releases": [_candidate_summary(doc, c) for c in rows],
    }


def get_release(candidate_id: str) -> Dict[str, Any]:
    doc = _read_doc()
    candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
    if candidate is None:
        raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
    cid = str(candidate.get("candidate_id"))
    artifact = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or "")) or {}
    deployments = [d for d in doc["deployments"] if str(d.get("candidate_id")) == cid]
    checks = [c for c in doc["checks"] if str(c.get("candidate_id")) == cid]
    approvals = [a for a in doc["approvals"] if str(a.get("candidate_id")) == cid]
    rollbacks = [r for r in doc["rollbacks"] if str(r.get("candidate_id")) == cid]
    notifications = [n for n in doc["notifications"] if str(n.get("candidate_id")) == cid]
    events = [e for e in doc["events"] if str(e.get("candidate_id")) == cid]
    deploy_steps = [s for s in doc["deploy_steps"] if str(s.get("candidate_id")) == cid]
    maintenance = [m for m in doc["maintenance"] if str(m.get("candidate_id")) == cid]
    rehearsals = [h for h in doc["rehearsals"] if str(h.get("candidate_id")) == cid]
    return {
        "ok": True,
        "summary": _candidate_summary(doc, candidate),
        "artifact": _public_artifact(artifact) if artifact else {},
        "deployments": deployments,
        "checks": checks,
        "approvals": [_public_approval(a) for a in approvals],
        "rollbacks": rollbacks,
        "notifications": notifications,
        "events": sorted(events, key=lambda e: int(e.get("seq") or 0)),
        "deploy_steps": sorted(deploy_steps, key=lambda s: int(s.get("ordinal") or 0)),
        "maintenance": maintenance,
        "rehearsals": rehearsals,
        "available_transitions": sorted(_TRANSITIONS.get(str(candidate.get("state") or ""), frozenset())),
        "adapter": _adapter_status(),
        "blue_green": blue_green.deployment_strategy(),
    }


def _public_artifact(artifact: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "artifact_id", "app_version", "release_channel", "build_id",
        "git_commit_sha", "artifact_sha256", "manifest_sha256",
        "signature_algorithm", "signature_status", "trust_tier",
        "built_at_utc", "dirty", "storage_uri", "file_count",
        "migration_count", "immutable", "archive_sha256",
        "runtime_artifact_sha256",
    )
    return {k: artifact.get(k) for k in keys}


def _public_approval(approval: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "approval_id", "candidate_id", "artifact_id", "environment",
        "artifact_sha256", "manifest_sha256", "git_commit_sha", "build_id",
        "approved_by_legacy_id", "status", "created_at_utc",
    )
    return {k: approval.get(k) for k in keys}


# --------------------------------------------------------------------------- #
# Deployment adapter (dry-run by default; real only when explicitly configured).
# --------------------------------------------------------------------------- #
def _adapter_name() -> str:
    return str(os.environ.get("STRATFORGE_RELEASE_DEPLOY_ADAPTER") or "dry_run").strip().lower()


def _adapter_status() -> Dict[str, Any]:
    name = _adapter_name()
    if name == release_executor.ADAPTER_NAME:
        return release_executor.status()
    real_configured = name not in {"", "dry_run"}
    return {
        "name": name if name else "dry_run",
        "real_configured": bool(real_configured),
        "real_available": False,
        "canary_available": False,
        "production_available": False,
        "mode": "blocked" if real_configured else "dry_run",
        "configuration_state": "adapter_unknown" if real_configured else "not_configured",
    }


def _run_deploy_adapter(environment: str, artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Execute an explicitly configured adapter or return a fail-closed plan."""
    status = _adapter_status()
    if status["name"] == release_executor.ADAPTER_NAME and status["real_available"]:
        try:
            return release_executor.deploy(environment, artifact)
        except release_executor.ReleaseExecutorError as exc:
            return {
                "status": "fail",
                "adapter": status["name"],
                "external_result": "fail",
                "environment": environment,
                "artifact_id": artifact.get("artifact_id"),
                "note": str(exc)[:300],
            }
    if status["real_configured"]:
        return {
            "status": "blocked",
            "adapter": status["name"],
            "external_result": "pending",
            "note": "real deployment executor configuration is unavailable",
        }
    return blue_green.execute_deployment(environment, artifact)


def _record_deploy_plan(
    doc: Dict[str, Any], candidate: Dict[str, Any], deployment: Dict[str, Any],
    outcome: Dict[str, Any],
) -> None:
    """Persist the blue-green deployment step log + maintenance window."""
    environment = str(deployment.get("environment") or "")
    active_slot = str(outcome.get("active_slot") or "")
    target_slot = str(outcome.get("target_slot") or "")
    for step in outcome.get("steps") or []:
        doc["deploy_steps"].append({
            "step_id": _new_id("stp"),
            "deployment_id": deployment.get("deployment_id"),
            "candidate_id": candidate.get("candidate_id"),
            "environment": environment,
            "strategy": str(outcome.get("strategy") or "blue_green_symlink"),
            "stage": str(step.get("stage") or ""),
            "ordinal": int(step.get("ordinal") or 0),
            "status": str(step.get("status") or ""),
            "active_slot": active_slot,
            "target_slot": target_slot,
            "evidence": step.get("evidence") or {},
            "created_at_utc": _now_iso(),
        })
    window = outcome.get("maintenance_window")
    if isinstance(window, dict):
        doc["maintenance"].append({
            "window_id": _new_id("mwn"),
            "candidate_id": candidate.get("candidate_id"),
            "environment": window.get("environment") or environment,
            "kind": window.get("kind") or "deploy",
            "state": window.get("state") or "planned",
            "reason": window.get("reason") or "",
            "scheduled_for_utc": window.get("scheduled_for_utc") or "",
            "document": {k: observability.redact(v, key=k) for k, v in window.items()},
            "created_at_utc": _now_iso(),
        })


# --------------------------------------------------------------------------- #
# Scheduling + notifications.
# --------------------------------------------------------------------------- #
def schedule_options() -> Dict[str, Any]:
    return {
        "explicit_offsets": list(SCHEDULE_OFFSETS_SEC.keys()),
        "explicit_time_supported": True,
        "market_close": dict(MARKET_CLOSE_OPTION),
    }


def notification_preview(app_version: str = "", release_channel: str = "") -> Dict[str, Any]:
    """Rendered, send-free preview of every update notification/banner message.

    This never sends a real Telegram message or Production banner: it only
    returns the canonical text for each notification kind so the interface can
    preview the top update banner ("через 5 минут", "через 60 секунд",
    "обновление завершено") without any external infrastructure.
    """
    ver = str(app_version or "").strip()
    label = f"v{ver}" if ver else "новая версия"
    previews = [
        {"kind": "scheduled_update", "title": "Запланировано обновление",
         "message": f"Обновление до {label} запланировано."},
        {"kind": "warn_5m", "title": "Обновление через 5 минут",
         "message": f"Приложение обновится до {label} через 5 минут. Сохраните работу."},
        {"kind": "warn_60s", "title": "Обновление через 60 секунд",
         "message": f"Обновление до {label} начнётся через 60 секунд."},
        {"kind": "deploy_started", "title": "Обновление началось",
         "message": "Идёт обновление приложения…"},
        {"kind": "deploy_successful", "title": "Обновление завершено",
         "message": f"Приложение обновлено до {label}. Обновите страницу, чтобы применить."},
        {"kind": "reload_available", "title": "Доступна новая версия",
         "message": "Доступна новая версия приложения. Обновите страницу."},
    ]
    adapter = _adapter_status()
    return {
        "ok": True,
        "previews": previews,
        # Real delivery needs configured Canary/Production infrastructure; it is
        # never available in this phase, so a preview is never a real send.
        "real_send_available": bool(adapter.get("real_available")),
        "note": (
            "Предпросмотр текста уведомлений и верхнего баннера обновления. "
            "Реальная отправка недоступна без настроенной инфраструктуры Canary/Production."
        ),
    }


def _resolve_schedule(mode: str, explicit_utc: str) -> Tuple[Optional[float], str]:
    mode = str(mode or "now").strip().lower()
    if mode in SCHEDULE_OFFSETS_SEC:
        offset = SCHEDULE_OFFSETS_SEC[mode]
        return (_now() + offset if offset else None), mode
    if mode == "after_market_close":
        raise ReleaseCenterError(
            MARKET_CLOSE_OPTION["reason"], 400, code="market_calendar_unavailable",
        )
    if mode == "explicit":
        epoch = _iso_to_epoch(explicit_utc)
        if epoch <= 0:
            raise ReleaseCenterError("Некорректное время расписания.", 400, code="schedule_time_invalid")
        if epoch < _now() - 60:
            raise ReleaseCenterError("Время расписания в прошлом.", 400, code="schedule_time_past")
        return epoch, "explicit"
    raise ReleaseCenterError("Неизвестный режим расписания.", 400, code="schedule_mode_invalid")


def _record_notification(
    doc: Dict[str, Any], candidate_id: str, kind: str, *, environment: str = ENVIRONMENT_PRODUCTION,
    scheduled_for: Optional[float] = None, evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if kind not in NOTIFICATION_KINDS:
        raise ReleaseCenterError("Неизвестный тип уведомления.", 400, code="notification_kind_invalid")
    row = {
        "notification_id": _new_id("rnt"),
        "candidate_id": candidate_id,
        "kind": kind,
        "environment": environment,
        "channel": "interface",
        # This phase only records the notification contract; no real Telegram or
        # Production banner is ever sent.
        "delivery": "recorded",
        "scheduled_for_utc": _now_iso(scheduled_for) if scheduled_for else "",
        "document": {k: observability.redact(v, key=k) for k, v in (evidence or {}).items()},
        "created_at_utc": _now_iso(),
    }
    doc["notifications"].append(row)
    return row


# --------------------------------------------------------------------------- #
# Operations.
# --------------------------------------------------------------------------- #
def create_candidate(
    *, actor: Any, app_version: str, release_channel: str, git_commit_sha: str = "",
    idempotency_key: str,
) -> Dict[str, Any]:
    """Create a draft release candidate from a clean, explicitly selected commit."""
    key = _validate_idempotency_key(idempotency_key)
    version = str(app_version or "").strip()
    channel = str(release_channel or "").strip().lower()
    if not _SEMVER.fullmatch(version):
        raise ReleaseCenterError("app_version должен быть semantic versioning.", 400, code="version_invalid")
    if channel not in {"dev", "beta", "stable"}:
        raise ReleaseCenterError("release_channel должен быть dev/beta/stable.", 400, code="channel_invalid")
    head, dirty = _git_state()
    commit = str(git_commit_sha or "").strip() or head
    if not _COMMIT_RE.fullmatch(commit):
        raise ReleaseCenterError("git_commit_sha некорректен.", 400, code="commit_invalid")
    # A dirty worktree can never produce a publishable candidate.
    if dirty:
        raise ReleaseCenterError(
            "Рабочее дерево содержит незакоммиченные изменения; выберите чистый commit.",
            409, code="dirty_worktree",
        )
    if head and commit != head:
        raise ReleaseCenterError(
            "Разрешён только явно выбранный текущий чистый commit.", 409, code="commit_not_selected",
        )
    with _LOCK:
        doc = _read_doc()
        cached = _idempotent(doc, key, "create_candidate")
        if cached:
            return cached
        candidate = {
            "candidate_id": _new_id("rc"),
            "app_version": version,
            "release_channel": channel,
            "git_commit_sha": commit,
            "state": STATE_DRAFT,
            "artifact_id": "",
            "created_by_user_uuid": _actor_uuid(actor),
            "created_by_legacy_id": _actor_id(actor),
            "failure_reason": "",
            "signed_fingerprint": {},
            "created_at_utc": _now_iso(),
            "updated_at_utc": _now_iso(),
        }
        doc["candidates"].append(candidate)
        doc["seq"] = int(doc.get("seq") or 0) + 1
        doc["events"].append({
            "event_id": _new_id("rev"),
            "candidate_id": candidate["candidate_id"],
            "event_type": "release.candidate_created",
            "from_state": "", "to_state": STATE_DRAFT,
            "actor_user_uuid": _actor_uuid(actor), "actor_legacy_id": _actor_id(actor),
            "idempotency_key": key, "seq": doc["seq"],
            "document": {"app_version": version, "release_channel": channel, "git_commit_sha": commit},
            "created_at_utc": _now_iso(),
        })
        result = {"ok": True, "candidate": _candidate_summary(doc, candidate)}
        _remember(doc, key, "create_candidate", result)
        _write_doc(doc)
    _audit("release.candidate_created", candidate_id=candidate["candidate_id"],
           actor_id=_actor_id(actor), app_version=version, release_channel=channel)
    return result


def build_release(
    *, actor: Any, candidate_id: str, idempotency_key: str,
    builder: Optional[Callable[[Dict[str, Any], str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the immutable artifact once. Rejects a dirty worktree."""
    key = _validate_idempotency_key(idempotency_key)
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"build:{candidate_id}")
        if cached:
            return cached
        if candidate.get("artifact_id"):
            raise ReleaseCenterError(
                "Artifact уже собран; пересборка запрещена (immutable).",
                409, code="artifact_immutable",
            )
        if candidate.get("state") not in {STATE_DRAFT, STATE_BUILD_FAILED}:
            raise ReleaseCenterError(
                "Сборка доступна только из состояния draft.", 409, code="invalid_transition",
            )
        head, dirty = _git_state()
        _transition(doc, candidate, STATE_BUILDING, actor=actor, event_type="release.build_started",
                    idempotency_key=key, evidence={"git_commit_sha": candidate.get("git_commit_sha")})
        if dirty:
            _transition(doc, candidate, STATE_BUILD_FAILED, actor=actor,
                        event_type="release.build_failed", idempotency_key=key,
                        failure_reason="dirty_worktree", evidence={"reason": "dirty_worktree"})
            result = {"ok": False, "state": STATE_BUILD_FAILED, "failure_reason": "dirty_worktree"}
            _remember(doc, key, f"build:{candidate_id}", result)
            _write_doc(doc)
            raise ReleaseCenterError("Сборка отклонена: грязное рабочее дерево.", 409, code="dirty_worktree")
        run_builder = builder or _default_builder
        try:
            report = run_builder(candidate, head or str(candidate.get("git_commit_sha") or ""))
        except Exception as exc:  # noqa: BLE001 - builder failure is recorded, not raised raw
            _transition(doc, candidate, STATE_BUILD_FAILED, actor=actor,
                        event_type="release.build_failed", idempotency_key=key,
                        failure_reason=type(exc).__name__, evidence={"reason": "builder_error"})
            _write_doc(doc)
            raise ReleaseCenterError(f"Сборка не удалась: {type(exc).__name__}.", 500, code="build_failed") from None
        artifact = _record_artifact(doc, candidate, report)
        candidate["artifact_id"] = artifact["artifact_id"]
        _transition(doc, candidate, STATE_BUILT, actor=actor, event_type="release.built",
                    idempotency_key=key, evidence=_fingerprint(artifact))
        result = {"ok": True, "state": STATE_BUILT, "artifact": _public_artifact(artifact)}
        _remember(doc, key, f"build:{candidate_id}", result)
        _write_doc(doc)
    return result


def _default_builder(candidate: Dict[str, Any], git_commit_sha: str) -> Dict[str, Any]:
    """Build locally for DEV or on the protected signer for a real release."""
    adapter = _adapter_status()
    if adapter.get("name") == release_executor.ADAPTER_NAME:
        if not adapter.get("real_available"):
            raise release_executor.ReleaseExecutorError(
                "real release executor configuration is incomplete"
            )
        return release_executor.build(candidate, git_commit_sha)
    import argparse
    from tools import build_server_release
    args = argparse.Namespace(
        version=str(candidate.get("app_version")),
        channel=str(candidate.get("release_channel")),
        production=False, force=True,
    )
    report = build_server_release.build(args)
    return {
        "app_version": report["app_version"],
        "release_channel": report["release_channel"],
        "build_id": report["build_id"],
        "git_commit_sha": report["git_commit_sha"],
        "artifact_sha256": report["archive_sha256"],
        "manifest_sha256": report["manifest_sha256"],
        "signature_algorithm": "ECDSA_P256_SHA256_RAW",
        "signature_status": "verified" if report.get("signature_verified") else "invalid",
        "trust_tier": report.get("trust_tier") or "development",
        "built_at_utc": report["build_timestamp_utc"],
        "dirty": bool(report.get("dirty")),
        "storage_uri": f"artifact://server/{report['app_version']}/{report['release_channel']}",
        "file_count": int(report.get("file_count") or 0),
        "migration_count": int(report.get("migration_count") or 0),
    }


def _record_artifact(doc: Dict[str, Any], candidate: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    artifact_sha = str(report.get("artifact_sha256") or "").strip()
    manifest_sha = str(report.get("manifest_sha256") or "").strip()
    build_id = str(report.get("build_id") or "").strip()
    commit = str(report.get("git_commit_sha") or "").strip()
    if not (_SHA256_RE.fullmatch(artifact_sha) and _SHA256_RE.fullmatch(manifest_sha)):
        raise ReleaseCenterError("Builder вернул некорректные контрольные суммы.", 500, code="checksum_invalid")
    if not build_id or not _COMMIT_RE.fullmatch(commit):
        raise ReleaseCenterError("Builder вернул некорректную идентичность сборки.", 500, code="build_identity_invalid")
    artifact = {
        "artifact_id": _new_id("art"),
        "app_version": str(report.get("app_version") or candidate.get("app_version")),
        "release_channel": str(report.get("release_channel") or candidate.get("release_channel")),
        "build_id": build_id,
        "git_commit_sha": commit,
        "artifact_sha256": artifact_sha,
        "manifest_sha256": manifest_sha,
        "signature_algorithm": str(report.get("signature_algorithm") or ""),
        "signature_status": str(report.get("signature_status") or "unverified"),
        "trust_tier": str(report.get("trust_tier") or "development"),
        "built_at_utc": str(report.get("built_at_utc") or _now_iso()),
        "dirty": bool(report.get("dirty")),
        "storage_uri": str(report.get("storage_uri") or "")[:500],
        # Private operational locator. It is required by the executor but is
        # deliberately omitted by _public_artifact and all ordinary UI views.
        "executor_ref": str(report.get("executor_ref") or "")[:200],
        "archive_sha256": str(report.get("archive_sha256") or artifact_sha),
        "runtime_artifact_sha256": str(
            report.get("runtime_artifact_sha256") or manifest_sha
        ),
        "file_count": int(report.get("file_count") or 0),
        "migration_count": int(report.get("migration_count") or 0),
        "immutable": True,
        "created_at_utc": _now_iso(),
    }
    doc["artifacts"].append(artifact)
    return artifact


def verify_release(*, actor: Any, candidate_id: str, idempotency_key: str) -> Dict[str, Any]:
    """Verify the signature and freeze the exact-artifact fingerprint."""
    key = _validate_idempotency_key(idempotency_key)
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"verify:{candidate_id}")
        if cached:
            return cached
        if candidate.get("state") != STATE_BUILT:
            raise ReleaseCenterError("Проверка доступна только из состояния built.", 409, code="invalid_transition")
        artifact = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or ""))
        if not artifact:
            raise ReleaseCenterError("Artifact отсутствует.", 409, code="artifact_missing")
        status = str(artifact.get("signature_status") or "")
        if status != "verified":
            raise ReleaseCenterError(
                f"Подпись не прошла проверку ({status or 'unknown'}).",
                409, code="signature_invalid",
            )
        candidate["signed_fingerprint"] = _fingerprint(artifact)
        _transition(doc, candidate, STATE_SIGNED, actor=actor, event_type="release.signed",
                    idempotency_key=key, evidence=_fingerprint(artifact))
        result = {"ok": True, "state": STATE_SIGNED, "fingerprint": _fingerprint(artifact)}
        _remember(doc, key, f"verify:{candidate_id}", result)
        _write_doc(doc)
    return result


def _assert_exact_artifact(candidate: Dict[str, Any], artifact: Dict[str, Any]) -> None:
    """Reject any drift from the frozen, signed artifact fingerprint."""
    frozen = candidate.get("signed_fingerprint") if isinstance(candidate.get("signed_fingerprint"), dict) else {}
    live = _fingerprint(artifact)
    if not frozen:
        raise ReleaseCenterError("Artifact не подписан.", 409, code="not_signed")
    for field in ("artifact_id", "artifact_sha256", "manifest_sha256", "git_commit_sha", "build_id"):
        if str(frozen.get(field) or "") != str(live.get(field) or ""):
            raise ReleaseCenterError(
                "Artifact/manifest/build/commit не совпадает с подписанным (пересборка запрещена).",
                409, code="artifact_mismatch",
            )


def deploy_canary(
    *, actor: Any, candidate_id: str, idempotency_key: str, step_up_challenge_id: str = "",
) -> Dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    _require_step_up(actor, action=ACTION_DEPLOY_CANARY, challenge_id=step_up_challenge_id)
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"deploy_canary:{candidate_id}")
        if cached:
            return cached
        # A failed Canary deploy is usually an environment problem, not an
        # artifact problem, and the transition map already allows the retry.
        # Forcing a rebuild would contradict the immutable-artifact contract;
        # `_assert_exact_artifact` below still pins the identity.
        if candidate.get("state") not in {STATE_SIGNED, STATE_CANARY_FAILED}:
            raise ReleaseCenterError(
                "Canary deploy доступен из состояний signed и canary_failed.",
                409, code="invalid_transition",
            )
        artifact = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or ""))
        if not artifact:
            raise ReleaseCenterError("Artifact отсутствует.", 409, code="artifact_missing")
        _assert_exact_artifact(candidate, artifact)
        deployment = {
            "deployment_id": _new_id("dep"),
            "candidate_id": candidate["candidate_id"],
            "artifact_id": artifact["artifact_id"],
            "environment": ENVIRONMENT_CANARY,
            "state": "requested",
            "adapter": _adapter_status()["name"],
            "artifact_sha256": artifact["artifact_sha256"],
            "manifest_sha256": artifact["manifest_sha256"],
            "git_commit_sha": artifact["git_commit_sha"],
            "build_id": artifact["build_id"],
            "requested_by_user_uuid": _actor_uuid(actor),
            "requested_by_legacy_id": _actor_id(actor),
            "scheduled_for_utc": "",
            "failure_reason": "",
            "idempotency_key": key,
            "document": {},
            "created_at_utc": _now_iso(),
            "updated_at_utc": _now_iso(),
        }
        outcome = _run_deploy_adapter(ENVIRONMENT_CANARY, artifact)
        failed = str(outcome.get("status") or "").lower() in {"fail", "failed", "blocked"} \
            or str(outcome.get("external_result") or "").lower() == "fail"
        real_pass = str(outcome.get("status") or "").lower() == "pass" \
            and str(outcome.get("external_result") or "").lower() == "pass"
        deployment["state"] = "failed" if failed else ("deployed" if real_pass else "deploying")
        deployment["failure_reason"] = str(outcome.get("note") or "")[:300] if failed else ""
        deployment["document"] = outcome
        doc["deployments"].append(deployment)
        _record_deploy_plan(doc, candidate, deployment, outcome)
        _record_notification(doc, candidate["candidate_id"], "deploy_started", environment=ENVIRONMENT_CANARY)
        _transition(doc, candidate, STATE_CANARY_DEPLOYING, actor=actor,
                    event_type="release.canary_deploy_requested", idempotency_key=key,
                    evidence={"deployment_id": deployment["deployment_id"], "adapter": deployment["adapter"]})
        if failed:
            _record_notification(doc, candidate["candidate_id"], "deploy_failed", environment=ENVIRONMENT_CANARY)
            _transition(doc, candidate, STATE_CANARY_FAILED, actor=actor,
                        event_type="release.canary_deploy_failed", idempotency_key=key,
                        failure_reason="canary_deploy_failed",
                        evidence={"external_result": outcome.get("external_result"),
                                  "adapter": deployment["adapter"]})
            result = {"ok": False, "state": STATE_CANARY_FAILED, "deployment": dict(deployment)}
        else:
            _transition(doc, candidate, STATE_CANARY_CHECKING, actor=actor,
                        event_type="release.canary_checking", idempotency_key=key,
                        evidence={"external_result": outcome.get("external_result")})
            result = {"ok": True, "state": STATE_CANARY_CHECKING, "deployment": dict(deployment)}
        _remember(doc, key, f"deploy_canary:{candidate_id}", result)
        _write_doc(doc)
    return result


def record_canary_check(
    *, actor: Any, candidate_id: str, name: str, result: str,
    evidence: Optional[Dict[str, Any]] = None, final: bool = False, idempotency_key: str,
) -> Dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    result_id = str(result or "").strip().lower()
    if result_id not in {CHECK_PASS, CHECK_FAIL, CHECK_PENDING, CHECK_BLOCKED}:
        raise ReleaseCenterError("Недопустимый результат проверки.", 400, code="check_result_invalid")
    check_name = str(name or "").strip()[:120]
    if not check_name:
        raise ReleaseCenterError("Имя проверки обязательно.", 400, code="check_name_invalid")
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"canary_check:{candidate_id}")
        if cached:
            return cached
        if candidate.get("state") not in {STATE_CANARY_CHECKING}:
            raise ReleaseCenterError("Проверки Canary доступны только в состоянии canary_checking.", 409, code="invalid_transition")
        deployment = next(
            (d for d in doc["deployments"]
             if str(d.get("candidate_id")) == str(candidate_id) and d.get("environment") == ENVIRONMENT_CANARY),
            None,
        )
        if deployment is None:
            raise ReleaseCenterError("Canary deployment отсутствует.", 409, code="deployment_missing")
        row = {
            "check_id": _new_id("chk"),
            "deployment_id": deployment["deployment_id"],
            "candidate_id": candidate["candidate_id"],
            "name": check_name,
            "result": result_id,
            "recorded_by_user_uuid": _actor_uuid(actor),
            "recorded_by_legacy_id": _actor_id(actor),
            "evidence": {k: observability.redact(v, key=k) for k, v in (evidence or {}).items()},
            "created_at_utc": _now_iso(),
        }
        doc["checks"].append(row)
        transitioned = candidate.get("state")
        if result_id == CHECK_FAIL:
            deployment["state"] = "failed"
            deployment["failure_reason"] = check_name[:200]
            _record_notification(doc, candidate["candidate_id"], "deploy_failed", environment=ENVIRONMENT_CANARY)
            _transition(doc, candidate, STATE_CANARY_FAILED, actor=actor,
                        event_type="release.canary_failed", idempotency_key=key,
                        failure_reason=f"canary_check_failed:{check_name}",
                        evidence={"check": check_name})
            transitioned = STATE_CANARY_FAILED
        elif final and result_id == CHECK_PASS:
            deployment["state"] = "live"
            _record_notification(doc, candidate["candidate_id"], "deploy_successful", environment=ENVIRONMENT_CANARY)
            _transition(doc, candidate, STATE_CANARY_PASSED, actor=actor,
                        event_type="release.canary_passed", idempotency_key=key,
                        evidence={"check": check_name})
            transitioned = STATE_CANARY_PASSED
        out = {"ok": True, "state": transitioned, "check": dict(row)}
        _remember(doc, key, f"canary_check:{candidate_id}", out)
        _write_doc(doc)
    return out


def _live_environment_rows() -> Dict[str, Any]:
    """What the environments report, for the checks that need Production's own
    word. A registry that cannot be read leaves the ledger as the fallback."""
    from . import environment_registry

    try:
        return {"environments": environment_registry.authoritative_rows().get("environments") or []}
    except Exception:
        return {"environments": []}


def approve_production(
    *, actor: Any, candidate_id: str, idempotency_key: str, step_up_challenge_id: str = "",
) -> Dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    if not _is_owner(actor):
        raise ReleaseCenterError("Production approval доступен только владельцу.", 403, code="owner_required")
    _require_step_up(actor, action=ACTION_APPROVE_PRODUCTION, challenge_id=step_up_challenge_id)
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"approve:{candidate_id}")
        if cached:
            return cached
        if candidate.get("state") != STATE_CANARY_PASSED:
            raise ReleaseCenterError("Approval доступен только после canary_passed.", 409, code="invalid_transition")
        # Where the code came from is a separate question from whether Canary is
        # healthy. An artifact built from an unmerged branch passed acceptance
        # and was one button away from Production; canary_passed cannot answer
        # this and neither can the version string.
        from . import release_provenance

        provenance = release_provenance.eligibility(str(candidate.get("git_commit_sha") or ""))
        if not provenance.get("eligible"):
            raise ReleaseCenterError(
                str(provenance.get("reason") or "Эта сборка не создана из утверждённого main."),
                409, code="provenance_not_approved")
        # Approved main says where the code came from, not whether it is still
        # current: an old commit on main is as approved as a new one, so a
        # superseded candidate passes provenance while publishing it would roll
        # Production back. Going back is what rollback_production is for, with
        # its own gate and its own artifact rules.
        forward = release_provenance.forward_only(
            str(candidate.get("git_commit_sha") or ""),
            release_provenance.production_identity(
                _live_environment_rows(),
                {"releases": [_candidate_summary(doc, row) for row in doc["candidates"]]}),
        )
        if not forward.get("ok"):
            raise ReleaseCenterError(
                str(forward.get("reason") or "Эта сборка старее текущего Production."),
                409, code=str(forward.get("code") or "candidate_not_ahead_of_production"))
        artifact = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or ""))
        if not artifact:
            raise ReleaseCenterError("Artifact отсутствует.", 409, code="artifact_missing")
        _assert_exact_artifact(candidate, artifact)
        approval = {
            "approval_id": _new_id("apr"),
            "candidate_id": candidate["candidate_id"],
            "artifact_id": artifact["artifact_id"],
            "environment": ENVIRONMENT_PRODUCTION,
            "artifact_sha256": artifact["artifact_sha256"],
            "manifest_sha256": artifact["manifest_sha256"],
            "git_commit_sha": artifact["git_commit_sha"],
            "build_id": artifact["build_id"],
            "approved_by_user_uuid": _actor_uuid(actor),
            "approved_by_legacy_id": _actor_id(actor),
            "step_up_challenge_id": str(step_up_challenge_id or ""),
            "status": "active",
            "idempotency_key": key,
            "created_at_utc": _now_iso(),
        }
        doc["approvals"].append(approval)
        _transition(doc, candidate, STATE_APPROVED, actor=actor, event_type="release.approved_for_production",
                    idempotency_key=key, evidence=_fingerprint(artifact))
        out = {"ok": True, "state": STATE_APPROVED, "approval": _public_approval(approval)}
        _remember(doc, key, f"approve:{candidate_id}", out)
        _write_doc(doc)
    return out


def schedule_production(
    *, actor: Any, candidate_id: str, mode: str = "now", explicit_utc: str = "", idempotency_key: str,
) -> Dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    scheduled_for, resolved_mode = _resolve_schedule(mode, explicit_utc)
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"schedule:{candidate_id}")
        if cached:
            return cached
        if candidate.get("state") != STATE_APPROVED:
            raise ReleaseCenterError("Расписание доступно только после approval.", 409, code="invalid_transition")
        candidate["scheduled_for_utc"] = _now_iso(scheduled_for) if scheduled_for else ""
        _record_notification(doc, candidate["candidate_id"], "scheduled_update",
                             scheduled_for=scheduled_for, evidence={"mode": resolved_mode})
        _record_notification(doc, candidate["candidate_id"], "warn_5m", scheduled_for=scheduled_for)
        _record_notification(doc, candidate["candidate_id"], "warn_60s", scheduled_for=scheduled_for)
        _transition(doc, candidate, STATE_PRODUCTION_SCHEDULED, actor=actor,
                    event_type="release.production_scheduled", idempotency_key=key,
                    evidence={"mode": resolved_mode, "scheduled_for_utc": candidate["scheduled_for_utc"]})
        out = {"ok": True, "state": STATE_PRODUCTION_SCHEDULED,
               "scheduled_for_utc": candidate["scheduled_for_utc"], "mode": resolved_mode}
        _remember(doc, key, f"schedule:{candidate_id}", out)
        _write_doc(doc)
    return out


def _production_deploy_succeeded(doc: Dict[str, Any], candidate_id: Any) -> bool:
    """True when a Production deployment for this candidate really landed.

    Used to tell "still deploying" apart from "the attempt errored and nothing
    was deployed", which look identical from the candidate state alone.
    """
    for row in doc.get("deployments") or []:
        if str(row.get("candidate_id")) != str(candidate_id):
            continue
        if row.get("environment") != ENVIRONMENT_PRODUCTION:
            continue
        if str(row.get("state") or "") in {"deployed", "live"}:
            return True
    return False


def promote_production(
    *, actor: Any, candidate_id: str, idempotency_key: str, step_up_challenge_id: str = "",
) -> Dict[str, Any]:
    """Promote exactly the Canary-passed artifact to Production (dry-run deploy)."""
    key = _validate_idempotency_key(idempotency_key)
    if not _is_owner(actor):
        raise ReleaseCenterError("Production promotion доступен только владельцу.", 403, code="owner_required")
    _require_step_up(actor, action=ACTION_PROMOTE_PRODUCTION, challenge_id=step_up_challenge_id)
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"promote:{candidate_id}")
        if cached:
            return cached
        retryable = {STATE_APPROVED, STATE_PRODUCTION_SCHEDULED, STATE_PRODUCTION_FAILED}
        # A promotion that errored before the executor reported an outcome left
        # the candidate in production_deploying with nothing deployed. That is
        # not a success and must stay retryable, otherwise a transient failure
        # strands the candidate permanently: the state is neither live nor
        # failed, so no transition out of it exists.
        if candidate.get("state") == STATE_PRODUCTION_DEPLOYING and not _production_deploy_succeeded(doc, candidate_id):
            retryable.add(STATE_PRODUCTION_DEPLOYING)
        if candidate.get("state") not in retryable:
            raise ReleaseCenterError("Promotion доступен только после approval/scheduling.", 409, code="invalid_transition")
        artifact = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or ""))
        if not artifact:
            raise ReleaseCenterError("Artifact отсутствует.", 409, code="artifact_missing")
        _assert_exact_artifact(candidate, artifact)
        # A live Production approval must exist and match the exact artifact.
        approval = next(
            (a for a in doc["approvals"]
             if str(a.get("candidate_id")) == str(candidate_id) and a.get("status") == "active"),
            None,
        )
        if approval is None:
            raise ReleaseCenterError("Отсутствует активное одобрение Production.", 403, code="approval_required")
        for field in ("artifact_sha256", "manifest_sha256", "git_commit_sha", "build_id"):
            if str(approval.get(field) or "") != str(artifact.get(field) or ""):
                raise ReleaseCenterError(
                    "Одобрение не соответствует продвигаемому artifact.", 409, code="approval_artifact_mismatch",
                )
        # The Canary deployment that passed must reference the same artifact.
        canary = next(
            (d for d in doc["deployments"]
             if str(d.get("candidate_id")) == str(candidate_id) and d.get("environment") == ENVIRONMENT_CANARY),
            None,
        )
        if canary is None or str(canary.get("artifact_id")) != str(artifact.get("artifact_id")):
            raise ReleaseCenterError("Canary не проверял этот artifact.", 409, code="canary_artifact_mismatch")
        deployment = {
            "deployment_id": _new_id("dep"),
            "candidate_id": candidate["candidate_id"],
            "artifact_id": artifact["artifact_id"],
            "environment": ENVIRONMENT_PRODUCTION,
            "state": "requested",
            "adapter": _adapter_status()["name"],
            "artifact_sha256": artifact["artifact_sha256"],
            "manifest_sha256": artifact["manifest_sha256"],
            "git_commit_sha": artifact["git_commit_sha"],
            "build_id": artifact["build_id"],
            "requested_by_user_uuid": _actor_uuid(actor),
            "requested_by_legacy_id": _actor_id(actor),
            "scheduled_for_utc": candidate.get("scheduled_for_utc") or "",
            "failure_reason": "",
            "idempotency_key": key,
            "document": {},
            "created_at_utc": _now_iso(),
            "updated_at_utc": _now_iso(),
        }
        outcome = _run_deploy_adapter(ENVIRONMENT_PRODUCTION, artifact)
        failed = str(outcome.get("status") or "").lower() in {"fail", "failed", "blocked"} \
            or str(outcome.get("external_result") or "").lower() == "fail"
        real_pass = str(outcome.get("status") or "").lower() == "pass" \
            and str(outcome.get("external_result") or "").lower() == "pass"
        deployment["state"] = "failed" if failed else ("deployed" if real_pass else "deploying")
        deployment["failure_reason"] = str(outcome.get("note") or "")[:300] if failed else ""
        deployment["document"] = outcome
        doc["deployments"].append(deployment)
        _record_deploy_plan(doc, candidate, deployment, outcome)
        _record_notification(doc, candidate["candidate_id"], "deploy_started", environment=ENVIRONMENT_PRODUCTION)
        _transition(doc, candidate, STATE_PRODUCTION_DEPLOYING, actor=actor,
                    event_type="release.production_deploy_requested", idempotency_key=key,
                    evidence={"deployment_id": deployment["deployment_id"], "adapter": deployment["adapter"]})
        if failed:
            _record_notification(doc, candidate["candidate_id"], "deploy_failed", environment=ENVIRONMENT_PRODUCTION)
            _transition(doc, candidate, STATE_PRODUCTION_FAILED, actor=actor,
                        event_type="release.production_deploy_failed", idempotency_key=key,
                        failure_reason="production_deploy_failed",
                        evidence={"external_result": outcome.get("external_result"),
                                  "adapter": deployment["adapter"]})
            result = {"ok": False, "state": STATE_PRODUCTION_FAILED,
                      "deployment": dict(deployment),
                      "external_result": outcome.get("external_result")}
        else:
            # The approval is spent only when the artifact actually landed. An
            # attempt that errored without deploying must leave it active, or
            # the retry is refused for want of an approval it already used up.
            if real_pass:
                approval["status"] = "consumed"
                # The executor verified a real deployment of this exact
                # artifact, which is the whole evidence bar mark_production_live
                # applies. Leaving the candidate in production_deploying made
                # the ledger disagree with the live environment -- and a retry
                # after an earlier failure could never reach a terminal state.
                deployment["state"] = "live"
                _record_notification(doc, candidate["candidate_id"], "deploy_successful",
                                     environment=ENVIRONMENT_PRODUCTION)
                _record_notification(doc, candidate["candidate_id"], "reload_available",
                                     environment=ENVIRONMENT_PRODUCTION)
                _transition(doc, candidate, STATE_PRODUCTION_LIVE, actor=actor,
                            event_type="release.production_live", idempotency_key=key,
                            evidence={"deployment_id": deployment["deployment_id"],
                                      "external_result": outcome.get("external_result")})
            result = {
                "ok": True,
                "state": candidate["state"],
                "deployment": dict(deployment),
                "external_result": outcome.get("external_result"),
                "note": ("real deployment verified; candidate is production_live"
                         if real_pass else "dry-run: real Production deployment not performed"),
            }
        _remember(doc, key, f"promote:{candidate_id}", result)
        _write_doc(doc)
    return result


def mark_production_live(*, actor: Any, candidate_id: str, idempotency_key: str) -> Dict[str, Any]:
    """Owner-confirmed transition to production_live once a real deploy is verified.

    This is intentionally separate from :func:`promote_production` so that a
    dry-run promotion can never auto-advance to live without real evidence.
    """
    key = _validate_idempotency_key(idempotency_key)
    if not _is_owner(actor):
        raise ReleaseCenterError("Только владелец подтверждает production_live.", 403, code="owner_required")
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"live:{candidate_id}")
        if cached:
            return cached
        if candidate.get("state") != STATE_PRODUCTION_DEPLOYING:
            raise ReleaseCenterError("Только из production_deploying.", 409, code="invalid_transition")
        deployment = next(
            (d for d in doc["deployments"]
             if str(d.get("candidate_id")) == str(candidate_id) and d.get("environment") == ENVIRONMENT_PRODUCTION),
            None,
        )
        if deployment is None or str((deployment.get("document") or {}).get("external_result") or "") != "pass":
            raise ReleaseCenterError(
                "production_live требует подтверждённый PASS реального deployment executor.",
                409, code="production_deploy_unverified",
            )
        deployment["state"] = "live"
        _record_notification(doc, candidate["candidate_id"], "deploy_successful", environment=ENVIRONMENT_PRODUCTION)
        _record_notification(doc, candidate["candidate_id"], "reload_available", environment=ENVIRONMENT_PRODUCTION)
        _transition(doc, candidate, STATE_PRODUCTION_LIVE, actor=actor,
                    event_type="release.production_live", idempotency_key=key)
        out = {"ok": True, "state": STATE_PRODUCTION_LIVE}
        _remember(doc, key, f"live:{candidate_id}", out)
        _write_doc(doc)
    return out


def rollback_production(
    *, actor: Any, candidate_id: str, to_artifact_id: str, reason: str = "",
    idempotency_key: str, step_up_challenge_id: str = "",
) -> Dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    if not _is_owner(actor):
        raise ReleaseCenterError("Rollback доступен только владельцу.", 403, code="owner_required")
    _require_step_up(actor, action=ACTION_ROLLBACK_PRODUCTION, challenge_id=step_up_challenge_id)
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"rollback:{candidate_id}")
        if cached:
            return cached
        if candidate.get("state") not in {STATE_PRODUCTION_LIVE, STATE_PRODUCTION_FAILED, STATE_PRODUCTION_DEPLOYING}:
            raise ReleaseCenterError("Rollback доступен только из Production состояния.", 409, code="invalid_transition")
        target = _find(doc["artifacts"], "artifact_id", str(to_artifact_id or ""))
        if target is None:
            raise ReleaseCenterError("Целевой artifact для rollback неизвестен.", 404, code="rollback_target_unknown")
        # Rollback target must be a known, previously Production-deployed artifact.
        deployed_prod = {
            str(d.get("artifact_id"))
            for d in doc["deployments"]
            if d.get("environment") == ENVIRONMENT_PRODUCTION
        }
        if str(target["artifact_id"]) not in deployed_prod:
            raise ReleaseCenterError(
                "Rollback разрешён только на ранее развёрнутый в Production artifact.",
                409, code="rollback_incompatible",
            )
        current = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or "")) or {}
        adapter = _adapter_status()
        if not adapter.get("production_available"):
            raise ReleaseCenterError(
                "Production rollback executor недоступен или не получил отдельный owner gate.",
                409, code="rollback_executor_unavailable",
            )
        try:
            executor_outcome = release_executor.rollback_production(current, target)
        except release_executor.ReleaseExecutorError as exc:
            raise ReleaseCenterError(
                f"Production rollback не выполнен: {str(exc)[:240]}",
                503, code="rollback_executor_failed",
            ) from None
        if str(executor_outcome.get("external_result") or "") != "pass":
            raise ReleaseCenterError(
                "Production rollback executor не подтвердил PASS.",
                503, code="rollback_executor_unverified",
            )
        switch = blue_green.plan_rollback_switch(
            to_build_id=str(target.get("build_id") or ""), reason=str(reason or ""),
        )
        rollback = {
            "rollback_id": _new_id("rbk"),
            "candidate_id": candidate["candidate_id"],
            "from_artifact_id": current.get("artifact_id") or "",
            "to_artifact_id": target["artifact_id"],
            "environment": ENVIRONMENT_PRODUCTION,
            "requested_by_user_uuid": _actor_uuid(actor),
            "requested_by_legacy_id": _actor_id(actor),
            "reason": str(reason or "")[:500],
            "evidence": {
                "to_build_id": target.get("build_id"),
                "traffic_switch": switch,
                "executor": {
                    "status": executor_outcome.get("status"),
                    "external_result": executor_outcome.get("external_result"),
                    "rollback_verified": bool(executor_outcome.get("rollback_verified")),
                    "secrets_redacted": True,
                },
            },
            "idempotency_key": key,
            "created_at_utc": _now_iso(),
        }
        doc["rollbacks"].append(rollback)
        _record_notification(doc, candidate["candidate_id"], "rollback", environment=ENVIRONMENT_PRODUCTION)
        _transition(doc, candidate, STATE_ROLLED_BACK, actor=actor, event_type="release.rolled_back",
                    idempotency_key=key, evidence={"to_artifact_id": target["artifact_id"]})
        out = {"ok": True, "state": STATE_ROLLED_BACK, "rollback": dict(rollback)}
        _remember(doc, key, f"rollback:{candidate_id}", out)
        _write_doc(doc)
    return out


def cancel_release(*, actor: Any, candidate_id: str, reason: str = "", idempotency_key: str) -> Dict[str, Any]:
    key = _validate_idempotency_key(idempotency_key)
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"cancel:{candidate_id}")
        if cached:
            return cached
        if STATE_CANCELLED not in _TRANSITIONS.get(str(candidate.get("state") or ""), frozenset()):
            raise ReleaseCenterError("Отмена недоступна в текущем состоянии.", 409, code="invalid_transition")
        _transition(doc, candidate, STATE_CANCELLED, actor=actor, event_type="release.cancelled",
                    idempotency_key=key, failure_reason=str(reason or "")[:500] or "cancelled")
        out = {"ok": True, "state": STATE_CANCELLED}
        _remember(doc, key, f"cancel:{candidate_id}", out)
        _write_doc(doc)
    return out


def rehearse_blue_green(
    *, actor: Any, candidate_id: str, environment: str = ENVIRONMENT_PRODUCTION,
    drain: Optional[Dict[str, Any]] = None, idempotency_key: str,
) -> Dict[str, Any]:
    """Rehearse blue-green without changing the release state.

    A configured real executor performs an actual Canary rollback, verifies the
    previous slot, and re-promotes the selected immutable artifact.  Production
    remains plan-only here; its traffic is never switched by a rehearsal.
    """
    key = _validate_idempotency_key(idempotency_key)
    env = str(environment or ENVIRONMENT_PRODUCTION).strip().lower()
    if env not in {ENVIRONMENT_CANARY, ENVIRONMENT_PRODUCTION}:
        raise ReleaseCenterError("Недопустимое окружение rehearsal.", 400, code="environment_invalid")
    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"rehearse:{candidate_id}")
        if cached:
            return cached
        artifact = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or ""))
        if not artifact:
            raise ReleaseCenterError("Artifact ещё не собран.", 409, code="artifact_missing")
        artifact_snapshot = dict(artifact)
        candidate_state = str(candidate.get("state") or "")

    adapter = _adapter_status()
    real_canary = (
        env == ENVIRONMENT_CANARY
        and adapter.get("name") == release_executor.ADAPTER_NAME
        and bool(adapter.get("canary_available"))
        and candidate_state in {STATE_CANARY_CHECKING, STATE_CANARY_PASSED}
    )
    if real_canary:
        try:
            result = release_executor.rehearse_canary_rollback(artifact_snapshot)
        except release_executor.ReleaseExecutorError as exc:
            raise ReleaseCenterError(
                str(exc), 503, code="canary_rollback_rehearsal_failed",
            ) from None
        verified = bool(result.get("rollback_verified")) and bool(result.get("re_promoted"))
        plan = {
            "environment": ENVIRONMENT_CANARY,
            "strategy": "blue_green_symlink",
            "mode": "real",
            "external_result": "pass" if verified else "fail",
            "online_safe": verified,
            "rollback_verified": bool(result.get("rollback_verified")),
            "re_promoted": bool(result.get("re_promoted")),
            "previous_git_commit_sha": str(result.get("previous_git_commit_sha") or ""),
            "current_git_commit_sha": str(result.get("current_git_commit_sha") or ""),
            "blocked_stages": [] if verified else ["rollback_or_repromotion_verification"],
            "secrets_redacted": True,
        }
    else:
        plan = blue_green.rehearse(env, artifact_snapshot, drain=drain)

    with _LOCK:
        doc = _read_doc()
        candidate = _find(doc["candidates"], "candidate_id", str(candidate_id or ""))
        if candidate is None:
            raise ReleaseCenterError("Release candidate не найден.", 404, code="candidate_not_found")
        cached = _idempotent(doc, key, f"rehearse:{candidate_id}")
        if cached:
            return cached
        artifact = _find(doc["artifacts"], "artifact_id", str(candidate.get("artifact_id") or ""))
        if not artifact or str(artifact.get("artifact_id") or "") != str(artifact_snapshot.get("artifact_id") or ""):
            raise ReleaseCenterError("Artifact изменился во время rehearsal.", 409, code="artifact_mismatch")
        record = {
            "rehearsal_id": _new_id("reh"),
            "candidate_id": candidate["candidate_id"],
            "artifact_id": artifact["artifact_id"],
            "environment": env,
            "online_safe": bool(plan.get("online_safe")),
            "blocked_stages": list(plan.get("blocked_stages") or []),
            "requested_by_user_uuid": _actor_uuid(actor),
            "requested_by_legacy_id": _actor_id(actor),
            "document": {k: observability.redact(v, key=k) for k, v in plan.items()},
            "created_at_utc": _now_iso(),
        }
        doc["rehearsals"].append(record)
        out = {
            "ok": bool(plan.get("online_safe")),
            "rehearsal": plan,
            "rehearsal_id": record["rehearsal_id"],
        }
        _remember(doc, key, f"rehearse:{candidate_id}", out)
        _write_doc(doc)
    _audit("release.blue_green_rehearsed", candidate_id=candidate_id,
           actor_id=_actor_id(actor), environment=env,
           online_safe=bool(plan.get("online_safe")))
    return out


def reset_for_tests() -> None:
    """Development/test helper: clear the local release store."""
    runtime_env.require_test_auth()
    with _LOCK:
        _write_doc(_default_doc())
