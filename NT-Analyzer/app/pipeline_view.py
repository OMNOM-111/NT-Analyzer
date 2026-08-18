"""Environments and releases as one question, answered once.

The Environment Switcher knew what each environment was running. The Release
Center knew how a candidate moves. Neither knew the other, so the owner had to
hold the workflow in their head: which candidate is on Canary, whether it is
the same artifact Production would receive, and what exactly is stopping the
next step.

This assembles both from sources that already exist -- the environment registry
for what each environment reports about itself, the release centre for
candidate state, development_sync for whether LOCAL is even running the code
being released. Nothing here is a second source of truth; where a fact exists
in two places it is read from one.

The gates are the point. A promotion is allowed only when the artifact Canary
accepted is exactly the one Production receives, and when it is not allowed the
reasons are stated in words rather than left to be inferred from a state name.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import runtime_env


# The stages an owner actually cares about, in the order they happen. The
# release centre's internal states are richer on purpose -- they distinguish
# failure modes that matter to the machinery and not to the person watching.
STAGES = (
    ("ci", "CI"),
    ("build", "Сборка"),
    ("sign", "Подпись"),
    ("migrate", "Миграции"),
    ("canary", "Canary"),
    ("acceptance", "Приёмка"),
    ("production", "Production"),
)

_REACHED = {
    "build": {"built", "signed", "canary_deploying", "canary_checking",
              "canary_passed", "approved_for_production", "production_scheduled",
              "production_deploying", "production_live"},
    "sign": {"signed", "canary_deploying", "canary_checking", "canary_passed",
             "approved_for_production", "production_scheduled",
             "production_deploying", "production_live"},
    "canary": {"canary_checking", "canary_passed", "approved_for_production",
               "production_scheduled", "production_deploying", "production_live"},
    "acceptance": {"canary_passed", "approved_for_production",
                   "production_scheduled", "production_deploying",
                   "production_live"},
    "production": {"production_live"},
}

_FAILED = {
    "build": {"build_failed"},
    "canary": {"canary_failed"},
    "production": {"production_failed", "rolled_back"},
}


def _stage_state(stage: str, candidate: Dict[str, Any]) -> str:
    state = str(candidate.get("state") or "")
    if state in _FAILED.get(stage, set()):
        return "failed"
    if state in _REACHED.get(stage, set()):
        return "done"
    # CI and migrations are not release-centre states. CI ran before the
    # candidate could exist at all, and migrations are part of reaching Canary.
    if stage == "ci":
        return "done" if state and state != "draft" else "pending"
    if stage == "migrate":
        return "done" if state in _REACHED["canary"] else "pending"
    return "pending"


def stage_progress(candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"id": key, "label": label, "state": _stage_state(key, candidate)}
        for key, label in STAGES
    ]


def promotion_gates(candidate: Dict[str, Any],
                    registry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Why Production promotion is or is not allowed, in plain terms.

    Each gate is phrased as the thing that must be true, so a blocked promotion
    reads as a checklist rather than as a refusal. The artifact gates matter
    most: Production must receive exactly what Canary accepted, never a rebuild.
    """
    state = str(candidate.get("state") or "")
    artifact = str(candidate.get("artifact_sha256") or "")

    registry_rows = {}
    for row in ((registry or {}).get("environments") or []):
        registry_rows[str(row.get("environment") or "")] = row
    canary_live = registry_rows.get(runtime_env.CANARY) or {}
    canary_reported = str(canary_live.get("artifact_sha256") or "")

    gates = [
        {
            "id": "artifact_exists",
            "label": "Неизменяемый артефакт собран и подписан",
            "ok": bool(artifact) and state in _REACHED["sign"],
        },
        {
            "id": "migrations",
            "label": "Миграции применены на Canary",
            "ok": state in _REACHED["canary"],
        },
        {
            "id": "canary_deployed",
            "label": "Canary развёрнут с этим кандидатом",
            "ok": state in _REACHED["canary"],
        },
        {
            "id": "acceptance",
            "label": "Приёмка Canary пройдена",
            "ok": state in _REACHED["acceptance"],
        },
        {
            "id": "artifact_unchanged",
            "label": "Canary подтверждает тот же артефакт",
            # Checked against what Canary itself reports rather than against
            # what the release record claims: an environment saying "this is
            # what I am running" is the stronger statement.
            "ok": bool(artifact) and bool(canary_reported)
                  and canary_reported.lower() == artifact.lower(),
        },
    ]
    blocked = [g for g in gates if not g["ok"]]
    return {
        "gates": gates,
        "allowed": not blocked,
        "blocking": [g["id"] for g in blocked],
        "reason": "" if not blocked else "; ".join(g["label"] for g in blocked),
    }


def development_card(sync: Dict[str, Any],
                     registry_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What LOCAL is, including whether it is running the current code.

    The stale/dirty state belongs on this card rather than in a separate
    banner: a release cut from a checkout that LOCAL is not running is the
    failure this whole pipeline exists to prevent.
    """
    row = registry_row or {}
    deployment = runtime_env.public_status()
    return {
        "environment": runtime_env.DEVELOPMENT,
        "online": str(row.get("state") or "") in {"live", "stale"},
        "presence": str(row.get("state") or "never_seen"),
        "last_seen_at_utc": row.get("last_seen_at_utc") or "",
        "sync_state": str(sync.get("state") or "unknown"),
        "sync_message": str(sync.get("message") or ""),
        "version": str(sync.get("running_version")
                       or deployment.get("app_version") or ""),
        "running_commit": str(sync.get("running_commit_short") or ""),
        "head_commit": str(sync.get("head_commit_short") or ""),
        "head_branch": str(sync.get("head_branch") or ""),
        "dirty_count": int(sync.get("dirty_count") or 0),
        "commit": str(sync.get("running_commit_short") or ""),
        "build_id": str(deployment.get("build_id") or ""),
        "artifact_sha256": "",
        "schema_version": int(row.get("schema_version") or 0),
        "readiness": str(row.get("readiness") or ""),
        "market_data": str(row.get("market_data") or ""),
        "connector": str(row.get("connector") or ""),
        "release_channel": str(deployment.get("release_channel") or ""),
    }


def server_card(environment: str, registry_row: Optional[Dict[str, Any]] = None,
                deployment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    row = registry_row or {}
    deploy = deployment or {}
    return {
        "environment": environment,
        "presence": str(row.get("state") or "never_seen"),
        "last_seen_at_utc": row.get("last_seen_at_utc") or "",
        "version": str(row.get("app_version") or ""),
        "commit": str(row.get("git_commit_sha") or "")[:12],
        "artifact_sha256": str(row.get("artifact_sha256") or ""),
        "schema_version": int(row.get("schema_version") or 0),
        "readiness": str(row.get("readiness") or ""),
        "market_data": str(row.get("market_data") or ""),
        "connector": str(row.get("connector") or ""),
        "release_channel": str(row.get("release_channel") or ""),
        "last_deploy_at_utc": str(deploy.get("updated_at_utc")
                                  or deploy.get("created_at_utc") or ""),
        "deploy_state": str(deploy.get("state") or ""),
    }


def compare(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Field by field across the three environments.

    Only environments that have reported take part, and a blank is reported as
    missing rather than as a disagreement -- calling absent data a mismatch
    teaches the reader to ignore the panel.
    """
    fields = (
        ("version", "Версия"), ("commit", "Commit"),
        ("artifact_sha256", "Артефакт"), ("schema_version", "Схема"),
        ("readiness", "Готовность"), ("market_data", "Market data"),
        ("connector", "Connector"), ("release_channel", "Канал"),
    )
    known = [c for c in cards if c.get("presence") not in {"never_seen", None}]
    rows = []
    for key, label in fields:
        values = {c["environment"]: c.get(key) for c in known}
        stated = [v for v in values.values() if v not in ("", 0, None)]
        rows.append({
            "field": key,
            "label": label,
            "values": values,
            "differs": len({str(v) for v in stated}) > 1,
            "missing": [e for e, v in values.items() if v in ("", 0, None)],
        })
    return {"environments": [c["environment"] for c in known], "fields": rows}


def development_access(is_local_request: bool) -> Dict[str, Any]:
    """Whether this browser may open LOCAL directly.

    Allowed only from the development machine itself. Nothing here publishes
    localhost outward and there is no proxy through Production: a convenience
    tunnel to a development box is a hole that outlives the convenience.
    """
    if is_local_request:
        return {
            "allowed": True,
            "origin": "http://127.0.0.1:8765",
            "reason": "",
        }
    return {
        "allowed": False,
        "origin": "",
        "reason": ("Development доступен только с зарегистрированного "
                   "development-устройства. Локальный сервер намеренно не "
                   "публикуется наружу."),
    }
