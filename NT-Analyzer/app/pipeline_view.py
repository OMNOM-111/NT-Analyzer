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


# States from which no further promotion is pending. Each carries the sentence
# that should be shown instead of a list of unmet conditions.
_TERMINAL = {
    "production_live": "Кандидат в Production. Дальнейший промоушен не требуется.",
    "rolled_back": "Кандидат откачен. Промоушен закрыт.",
    "superseded": "Кандидат вытеснен более новым. Промоушен закрыт.",
    "cancelled": "Кандидат отменён. Промоушен закрыт.",
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
                    registry: Optional[Dict[str, Any]] = None,
                    control: Optional[Dict[str, Any]] = None,
                    registry_is_authoritative: bool = True) -> Dict[str, Any]:
    """Why Production promotion is or is not allowed, in plain terms.

    Each gate is phrased as the thing that must be true, so a blocked promotion
    reads as a checklist rather than as a refusal. The artifact gates matter
    most: Production must receive exactly what Canary accepted, never a rebuild.

    Where the answer comes from depends on who is asking. On a server the
    registry is the real one and these gates are decided here. On LOCAL it is
    not -- ``snapshot()`` returns only LOCAL's own row -- so the gates about
    Canary come from ``control``: a decision made by the authoritative server
    and passed in. LOCAL never rules on Canary from its own snapshot, and a
    missing decision is a refusal rather than an omission.
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

    if not registry_is_authoritative:
        # This process cannot see Canary, so it must not answer for it. The
        # server's decision replaces the two gates that depend on the registry;
        # everything the release ledger knows is still checked here.
        decision = control or {}
        allowed = bool(decision.get("allowed"))
        available = bool(decision.get("available"))
        reason = str(decision.get("reason") or "")
        gates = [g for g in gates
                 if g["id"] not in {"canary_deployed", "artifact_unchanged"}]
        gates.append({
            "id": "server_authorised",
            "label": ("Сервер подтвердил промоушен" if allowed
                      else (reason or "Сервер не подтвердил промоушен")),
            "ok": allowed,
        })
        blocked = [g for g in gates if not g["ok"]]
        complete = state in _TERMINAL
        return {
            "gates": gates,
            "allowed": not blocked and not complete,
            "complete": complete,
            "blocking": [] if complete else [g["id"] for g in blocked],
            "reason": ("" if complete or not blocked
                       else "; ".join(g["label"] for g in blocked)),
            "note": _TERMINAL.get(state, ""),
            # Said out loud so the UI can distinguish "the server said no" from
            # "nobody could be asked", which are different problems.
            "decided_by": str(decision.get("decided_by") or ""),
            "control_available": available,
        }
    blocked = [g for g in gates if not g["ok"]]
    # A candidate that has already finished its journey is not a promotion
    # waiting on anything. Reporting it as blocked put a warning on every
    # completed release and taught the reader to ignore the warning.
    complete = state in _TERMINAL
    return {
        "gates": gates,
        "allowed": not blocked and not complete,
        "complete": complete,
        "blocking": [] if complete else [g["id"] for g in blocked],
        "reason": ("" if complete or not blocked
                   else "; ".join(g["label"] for g in blocked)),
        "note": _TERMINAL.get(state, ""),
        "decided_by": runtime_env.deployment_environment(),
        "control_available": True,
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


def assemble(*, registry: Optional[Dict[str, Any]], releases: Optional[Dict[str, Any]],
             sync: Optional[Dict[str, Any]], deployments: Optional[Dict[str, Any]] = None,
             is_local_request: bool = False,
             control: Optional[Dict[str, Any]] = None,
             registry_is_authoritative: bool = True) -> Dict[str, Any]:
    """The whole answer, from payloads the caller already fetched.

    This lives here rather than in the request handler because the joining is
    where the mistakes are: the release centre calls its candidate list
    ``releases`` while everything downstream calls the same rows candidates,
    and reading the wrong key produced an endpoint that cheerfully reported
    "no candidate" forever. A pure function can be tested against the real
    payload shapes; a branch inside a handler could not.
    """
    rows = {str(r.get("environment") or ""): r
            for r in ((registry or {}).get("environments") or [])}
    # The release centre publishes its candidate summaries under "releases".
    candidates = (releases or {}).get("releases") or []
    candidate = candidates[0] if candidates else {}
    deploys = deployments or {}

    development = development_card(sync or {}, rows.get(runtime_env.DEVELOPMENT))
    canary = server_card(runtime_env.CANARY, rows.get(runtime_env.CANARY),
                         deploys.get(runtime_env.CANARY))
    production = server_card(runtime_env.PRODUCTION, rows.get(runtime_env.PRODUCTION),
                             deploys.get(runtime_env.PRODUCTION))
    return {
        "ok": True,
        "environments": {
            "development": development,
            "canary": canary,
            "production": production,
        },
        "candidate": candidate,
        "candidates": candidates[:10],
        # Whether a deploy would be real or a rehearsal belongs next to the
        # buttons that would run it, not on a separate screen.
        "adapter": (releases or {}).get("adapter") or {},
        "notification_preview": (releases or {}).get("notification_preview") or {},
        "stages": stage_progress(candidate),
        "promotion": promotion_gates(
            candidate, registry, control=control,
            registry_is_authoritative=registry_is_authoritative),
        "compare": compare([development, canary, production]),
        "development_access": development_access(is_local_request),
    }
