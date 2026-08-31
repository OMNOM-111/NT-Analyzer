"""Getting the current commit onto Canary as one operation.

Reaching Canary used to take four calls in a fixed order — create the
candidate, build, verify, deploy — and the owner had to leave the release panel
to make the first one, on a screen whose only job was to fill in a version and
a commit that the repository already knows.

This runs the sequence server-side and reports the stages an owner watches:
Кандидат → Сборка → Проверка → Развёртывание → Готово. Nothing is relaxed:
release_center still refuses a dirty worktree, still requires the selected
commit to be the current clean HEAD, and still enforces every capability. The
version and channel come from VERSION.json and the commit from HEAD, so there
is no field to fill in and no way to ask for a build of something else.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import release_center

STAGE_CANDIDATE = "candidate"
STAGE_BUILD = "build"
STAGE_VERIFY = "verify"
STAGE_DEPLOY = "deploy"
STAGE_ACCEPTANCE = "acceptance"
STAGE_DONE = "done"

STAGES = (
    (STAGE_CANDIDATE, "Кандидат"),
    (STAGE_BUILD, "Сборка"),
    (STAGE_VERIFY, "Проверка"),
    (STAGE_DEPLOY, "Развёртывание"),
    (STAGE_ACCEPTANCE, "Canary checks / acceptance"),
    (STAGE_DONE, "Готово"),
)


def _version_file() -> Path:
    return Path(__file__).resolve().parents[1] / "VERSION.json"


def release_target() -> Dict[str, str]:
    """What a delivery would build, read from the repository itself."""
    try:
        raw = json.loads(_version_file().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"app_version": "", "release_channel": ""}
    channel = str(raw.get("channel") or "").strip().lower()
    return {
        "app_version": str(raw.get("version") or "").strip(),
        # dev builds are not deployable to Canary; the ledger rejects them
        # anyway, and saying so here keeps the reason readable.
        "release_channel": channel if channel in {"beta", "stable"} else channel,
    }


def canary_acceptance(candidate_id: str, origin: str, expected_build_id: str,
                      *, readiness=None, smoke=None) -> Dict[str, Any]:
    """The checks acceptance actually stands for, run against the live Canary.

    Recording a pass without probing would make the stage a formality and the
    "✓ Readiness / ✓ Smoke" line a decoration. Each row here is the result of a
    request that was made, and the names are what the panel shows.
    """
    from . import release_publish

    readiness_fn = readiness or release_publish._readiness
    smoke_fn = smoke or release_publish._smoke

    rows: List[Dict[str, Any]] = []
    if not origin:
        return {"ok": False, "reason": "Origin Canary не настроен, проверка невозможна.",
                "checks": rows}

    ready = readiness_fn(origin)
    rows.append({"name": "readiness", "label": "Readiness", "ok": bool(ready.get("ok")),
                 "detail": str(ready.get("reason") or "все компоненты готовы")})
    if not ready.get("ok"):
        return {"ok": False, "reason": str(ready.get("reason") or "Canary не готов."),
                "checks": rows}

    live_build = str((ready.get("deployment") or {}).get("build_id") or "")
    identical = bool(expected_build_id) and live_build == expected_build_id
    rows.append({
        "name": "artifact_identity", "label": "Artifact identity", "ok": identical,
        "detail": (f"Canary выполняет {live_build or 'неизвестный build'}"
                   if not identical else expected_build_id),
    })
    if not identical:
        return {"ok": False,
                "reason": (f"Canary сообщает build {live_build or 'неизвестен'}, "
                           f"ожидался {expected_build_id}."),
                "checks": rows}

    checked = smoke_fn(origin, expected_build_id)
    rows.append({"name": "smoke", "label": "Smoke", "ok": bool(checked.get("ok")),
                 "detail": str(checked.get("reason") or "публичные маршруты отвечают")})
    if not checked.get("ok"):
        return {"ok": False, "reason": str(checked.get("reason") or "Smoke не прошёл."),
                "checks": rows}
    return {"ok": True, "reason": "", "checks": rows}


def _stage_row(stage: str, label: str) -> Dict[str, Any]:
    return {"stage": stage, "label": label, "state": "not_started", "reason": ""}


def deliver(
    *, actor: Any, idempotency_key: str, step_up_challenge_id: str = "",
    create: Optional[Callable[..., Dict[str, Any]]] = None,
    build: Optional[Callable[..., Dict[str, Any]]] = None,
    verify: Optional[Callable[..., Dict[str, Any]]] = None,
    deploy: Optional[Callable[..., Dict[str, Any]]] = None,
    record: Optional[Callable[..., Dict[str, Any]]] = None,
    accept: Optional[Callable[..., Dict[str, Any]]] = None,
    canary_origin: str = "",
) -> Dict[str, Any]:
    """Create, build, verify and deploy to Canary, reporting each stage."""
    create_fn = create or release_center.create_candidate
    build_fn = build or release_center.build_release
    verify_fn = verify or release_center.verify_release
    deploy_fn = deploy or release_center.deploy_canary
    record_fn = record or release_center.record_canary_check
    accept = accept or canary_acceptance

    stages: List[Dict[str, Any]] = [_stage_row(key, label) for key, label in STAGES]
    by_key = {row["stage"]: row for row in stages}
    candidate_id = ""

    def fail(stage: str, reason: str, *, status: int = 409, code: str = "deliver_failed"):
        by_key[stage]["state"] = "failed"
        by_key[stage]["reason"] = reason
        return {
            "ok": False, "stages": stages, "failed_stage": stage, "reason": reason,
            "status": status, "code": code, "candidate_id": candidate_id,
        }

    target = release_target()
    version = target["app_version"]
    channel = target["release_channel"]
    if not version:
        return fail(STAGE_CANDIDATE, "VERSION.json не читается: нечего собирать.",
                    code="version_unreadable")
    if channel not in {"beta", "stable"}:
        return fail(
            STAGE_CANDIDATE,
            f"Канал «{channel or 'не задан'}» нельзя отправить в Canary; "
            "укажите beta или stable в VERSION.json.",
            code="channel_not_deployable")

    try:
        created = create_fn(
            actor=actor, app_version=version, release_channel=channel,
            # Empty means "the current clean HEAD", which release_center
            # verifies; passing a commit from here would only add a way to be
            # wrong about it.
            git_commit_sha="", idempotency_key=idempotency_key + "-c",
        )
    except release_center.ReleaseCenterError as exc:
        return fail(STAGE_CANDIDATE, str(exc), status=exc.status, code=exc.code)
    holder = created.get("candidate") or created
    candidate_id = str(holder.get("candidate_id") or created.get("candidate_id") or "")
    if not candidate_id:
        return fail(STAGE_CANDIDATE, "Release Center не вернул идентификатор кандидата.",
                    code="candidate_id_missing")
    by_key[STAGE_CANDIDATE]["state"] = "passed"

    steps = (
        (STAGE_BUILD, build_fn, "-b", {}),
        (STAGE_VERIFY, verify_fn, "-v", {}),
        (STAGE_DEPLOY, deploy_fn, "-d", {"step_up_challenge_id": step_up_challenge_id}),
    )
    for stage, function, suffix, extra in steps:
        try:
            function(actor=actor, candidate_id=candidate_id,
                     idempotency_key=idempotency_key + suffix, **extra)
        except release_center.ReleaseCenterError as exc:
            return fail(stage, str(exc), status=exc.status, code=exc.code)
        by_key[stage]["state"] = "passed"

    summary = release_center.get_release(candidate_id).get("summary") or {}
    state = str(summary.get("state") or "")
    # The build and canary steps can report failure in a successful response;
    # the ledger state is what says whether Canary actually received it.
    if state in release_center.FAILURE_STATES:
        return fail(STAGE_DEPLOY,
                    str(summary.get("failure_reason") or "Развёртывание не удалось."),
                    code="deploy_failed")

    # Acceptance is part of the same action, and it is a real probe of the live
    # environment rather than a formality: readiness, the artifact Canary is
    # actually running, and the public surface answering.
    verdict = accept(candidate_id, canary_origin,
                     str(summary.get("build_id") or ""))
    checks = verdict.get("checks") or []
    if not verdict.get("ok"):
        out = fail(STAGE_ACCEPTANCE, str(verdict.get("reason") or "Приёмка не прошла."),
                   code="acceptance_failed")
        out["checks"] = checks
        return out
    for row in checks:
        try:
            record_fn(actor=actor, candidate_id=candidate_id, name=str(row["name"]),
                      result="pass", evidence={"detail": str(row.get("detail") or "")},
                      final=False, idempotency_key=idempotency_key + "-" + str(row["name"])[:8])
        except release_center.ReleaseCenterError as exc:
            out = fail(STAGE_ACCEPTANCE, str(exc), status=exc.status, code=exc.code)
            out["checks"] = checks
            return out
    try:
        record_fn(actor=actor, candidate_id=candidate_id, name="acceptance",
                  result="pass", evidence={"detail": "readiness, artifact identity, smoke"},
                  final=True, idempotency_key=idempotency_key + "-final")
    except release_center.ReleaseCenterError as exc:
        out = fail(STAGE_ACCEPTANCE, str(exc), status=exc.status, code=exc.code)
        out["checks"] = checks
        return out
    by_key[STAGE_ACCEPTANCE]["state"] = "passed"

    summary = release_center.get_release(candidate_id).get("summary") or {}
    by_key[STAGE_DONE]["state"] = "passed"
    return {"ok": True, "stages": stages, "failed_stage": "", "reason": "",
            "candidate_id": candidate_id, "summary": summary, "checks": checks}
