"""Publishing a candidate to Production as one operation with visible stages.

Promotion used to be several separate calls that the caller had to sequence:
approve, promote, then confirm the environment actually came up. Whoever drove
it had to know the order, and a failure halfway left the owner reading state
names to work out how far it got.

This runs the sequence server-side and reports it as the stages an owner
watches: Подтверждение → Развёртывание → Readiness → Smoke → Готово. Every
authorisation stays where it was — capability, owner, step-up and the
`canary_passed` state are all enforced by release_center, and this adds no way
around them. The first failing stage stops the run and carries a short reason;
later stages are reported as not started rather than silently missing.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from . import release_center

STAGE_APPROVE = "approve"
STAGE_DEPLOY = "deploy"
STAGE_READINESS = "readiness"
STAGE_SMOKE = "smoke"
STAGE_DONE = "done"

STAGES = (
    (STAGE_APPROVE, "Подтверждение"),
    (STAGE_DEPLOY, "Развёртывание"),
    (STAGE_READINESS, "Readiness"),
    (STAGE_SMOKE, "Smoke"),
    (STAGE_DONE, "Готово"),
)

_TIMEOUT_SEC = 30.0
# Probed anonymously: these must work for a visitor who has not signed in.
_SMOKE_PATHS = ("/api/legal/documents", "/ui/")


def _fetch(url: str, timeout: float = _TIMEOUT_SEC) -> tuple[int, str]:
    request = urllib.request.Request(
        url, method="GET",
        headers={"Accept": "application/json", "User-Agent": "StratForge-Publish/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(262144).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:
        return 0, ""


def _readiness(origin: str) -> Dict[str, Any]:
    status, body = _fetch(origin.rstrip("/") + "/api/ready")
    if status != 200:
        return {"ok": False, "reason": f"/api/ready вернул {status or 'нет ответа'}."}
    try:
        payload = json.loads(body)
    except ValueError:
        return {"ok": False, "reason": "/api/ready вернул неразбираемый ответ."}
    checks = payload.get("checks") or {}
    failing = [name for name, row in checks.items() if not (row or {}).get("ok")]
    if failing:
        return {"ok": False, "reason": "Не готовы компоненты: " + ", ".join(sorted(failing))}
    return {"ok": True, "deployment": payload.get("deployment") or {}}


def _smoke(origin: str, expected_build_id: str) -> Dict[str, Any]:
    """Public surface answers, and it is the artifact we just published."""
    base = origin.rstrip("/")
    ready = _readiness(base)
    if not ready["ok"]:
        return ready
    live_build = str((ready.get("deployment") or {}).get("build_id") or "")
    if expected_build_id and live_build != expected_build_id:
        return {
            "ok": False,
            "reason": f"Production сообщает build {live_build or 'неизвестен'}, ожидался {expected_build_id}.",
        }
    for path in _SMOKE_PATHS:
        status, _ = _fetch(base + path)
        if status != 200:
            return {"ok": False, "reason": f"{path} вернул {status or 'нет ответа'}."}
    return {"ok": True}


def _stage_row(stage: str, label: str) -> Dict[str, Any]:
    return {"stage": stage, "label": label, "state": "not_started", "reason": ""}


def publish(
    *, actor: Any, candidate_id: str, idempotency_key: str,
    step_up_challenge_id: str = "", production_origin: str = "",
    approve: Optional[Callable[..., Dict[str, Any]]] = None,
    promote: Optional[Callable[..., Dict[str, Any]]] = None,
    smoke: Optional[Callable[[str, str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Approve, promote and verify, reporting each stage.

    The callables are injectable so the sequencing can be tested without a live
    environment; production always passes the real ones.
    """
    approve_fn = approve or release_center.approve_production
    promote_fn = promote or release_center.promote_production
    smoke_fn = smoke or _smoke

    stages: List[Dict[str, Any]] = [_stage_row(key, label) for key, label in STAGES]
    by_key = {row["stage"]: row for row in stages}

    def fail(stage: str, reason: str, *, status: int = 409, code: str = "publish_failed"):
        by_key[stage]["state"] = "failed"
        by_key[stage]["reason"] = reason
        return {
            "ok": False, "stages": stages, "failed_stage": stage,
            "reason": reason, "status": status, "code": code,
        }

    summary = release_center.get_release(str(candidate_id or "")).get("summary") or {}
    state = str(summary.get("state") or "")
    # The button is only offered for canary_passed; this is the control.
    if state not in {release_center.STATE_CANARY_PASSED,
                     release_center.STATE_APPROVED,
                     release_center.STATE_PRODUCTION_SCHEDULED,
                     release_center.STATE_PRODUCTION_DEPLOYING,
                     release_center.STATE_PRODUCTION_FAILED}:
        return fail(STAGE_APPROVE,
                    "Публикация доступна только для кандидата, прошедшего Canary.",
                    code="invalid_transition")

    if state == release_center.STATE_CANARY_PASSED:
        try:
            approve_fn(actor=actor, candidate_id=candidate_id,
                       idempotency_key=idempotency_key + "-a",
                       step_up_challenge_id=step_up_challenge_id)
        except release_center.ReleaseCenterError as exc:
            return fail(STAGE_APPROVE, str(exc), status=exc.status, code=exc.code)
    by_key[STAGE_APPROVE]["state"] = "passed"

    try:
        promote_fn(actor=actor, candidate_id=candidate_id,
                   idempotency_key=idempotency_key + "-p",
                   step_up_challenge_id=step_up_challenge_id)
    except release_center.ReleaseCenterError as exc:
        return fail(STAGE_DEPLOY, str(exc), status=exc.status, code=exc.code)
    by_key[STAGE_DEPLOY]["state"] = "passed"

    origin = str(production_origin or "").strip()
    if not origin:
        # Without an origin the deployment cannot be confirmed. Reporting that
        # is better than showing a green run nobody verified.
        return fail(STAGE_READINESS, "Origin Production не настроен, проверка невозможна.",
                    code="production_origin_missing")

    ready = _readiness(origin)
    if not ready["ok"]:
        return fail(STAGE_READINESS, str(ready.get("reason") or "Production не готов."))
    by_key[STAGE_READINESS]["state"] = "passed"

    expected = str(summary.get("build_id") or "")
    checked = smoke_fn(origin, expected)
    if not checked.get("ok"):
        return fail(STAGE_SMOKE, str(checked.get("reason") or "Smoke-проверка не прошла."))
    by_key[STAGE_SMOKE]["state"] = "passed"
    by_key[STAGE_DONE]["state"] = "passed"

    final = release_center.get_release(str(candidate_id or "")).get("summary") or {}
    return {"ok": True, "stages": stages, "failed_stage": "", "reason": "",
            "summary": final}
