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

import re
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
                    registry_is_authoritative: bool = True,
                    provenance_check: Optional[Any] = None,
                    forward_check: Optional[Any] = None) -> Dict[str, Any]:
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
    if provenance_check is None:
        from . import release_provenance

        provenance_check = release_provenance.eligibility
    if forward_check is None:
        from . import release_provenance

        forward_check = release_provenance.forward_only
    state = str(candidate.get("state") or "")
    artifact = _runtime_artifact_sha(candidate)

    registry_rows = {}
    for row in ((registry or {}).get("environments") or []):
        registry_rows[str(row.get("environment") or "")] = row
    canary_live = registry_rows.get(runtime_env.CANARY) or {}
    canary_reported = str(canary_live.get("artifact_sha256") or "")

    # Provenance is decided by the backend and only reflected here; the panel
    # must not form its own opinion about whether a build may be published.
    # Asked unconditionally: a candidate with no commit at all is exactly the
    # case the checker has to refuse, not one to skip the question for.
    provenance = provenance_check(str(candidate.get("git_commit_sha") or ""))
    # Same rule the backend enforces, rendered rather than re-decided.
    forward = forward_check(str(candidate.get("git_commit_sha") or ""),
                            str((registry_rows.get(runtime_env.PRODUCTION) or {})
                                .get("git_commit_sha") or ""))

    gates = [
        {
            "id": "approved_main",
            "label": "Сборка сделана из утверждённого main",
            "ok": bool(provenance.get("eligible")),
            "detail": str(provenance.get("reason") or "")
                      or "commit входит в origin/main и прошёл CI",
        },
        {
            "id": "forward_only",
            "label": "Сборка не старее текущего Production",
            "ok": bool(forward.get("ok")),
            "detail": str(forward.get("reason") or "")
                      or "commit кандидата совпадает с Production или впереди него",
        },
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


def _version_order(value: Any) -> tuple[int, ...]:
    numbers = [int(part) for part in re.findall(r"\d+", str(value or ""))]
    return tuple(numbers[:4])


def _runtime_artifact_sha(release: Dict[str, Any]) -> str:
    """Identity reported by a running extracted artifact.

    ``artifact_sha256`` is the transport archive hash. Once extracted, Canary
    and Production intentionally report the signed manifest/runtime hash. They
    prove two different things and must not be compared to each other.
    """
    return str(release.get("manifest_sha256")
               or release.get("runtime_artifact_sha256")
               or release.get("artifact_sha256") or "")


def development_card(sync: Dict[str, Any],
                     registry_row: Optional[Dict[str, Any]] = None,
                     accepted_release: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What LOCAL is, including whether it is running the current code.

    The stale/dirty state belongs on this card rather than in a separate
    banner: a release cut from a checkout that LOCAL is not running is the
    failure this whole pipeline exists to prevent.
    """
    row = registry_row or {}
    deployment = runtime_env.public_status()
    version = str(row.get("app_version") or sync.get("running_version")
                  or deployment.get("app_version") or "")
    commit = str(row.get("git_commit_sha") or sync.get("running_commit") or "")
    sync_state = str(sync.get("state") or "unknown")
    sync_message = str(sync.get("message") or "")
    target = accepted_release or {}
    target_version = str(target.get("app_version") or "")
    target_commit = str(target.get("git_commit_sha") or "")
    same_release = bool(
        target_version and target_commit and version == target_version
        and commit and target_commit.startswith(commit[:12])
    )
    if same_release and row and sync_state in {"not_applicable", "unknown"}:
        sync_state = "current"
        sync_message = "Development сообщает version/commit принятого релиза."
    elif target_version and target_commit and not same_release:
        current_order = _version_order(version)
        target_order = _version_order(target_version)
        if current_order and target_order and current_order > target_order:
            sync_state = "ahead"
            relation = "опережает принятый релиз"
        elif version == target_version:
            sync_state = "diverged"
            relation = "имеет другую ревизию той же версии"
        else:
            sync_state = "behind"
            relation = "отстаёт от принятого релиза"
        sync_message = (
            f"Development {relation}: выполняется {version or 'неизвестная версия'} "
            f"({commit[:12] or 'commit неизвестен'}), принят {target_version} "
            f"({target_commit[:12]}). ALL ENVIRONMENTS PASS запрещён до сверки."
        )
    return {
        "environment": runtime_env.DEVELOPMENT,
        "online": str(row.get("state") or "") in {"live", "stale"},
        "presence": str(row.get("state") or "never_seen"),
        "last_seen_at_utc": row.get("last_seen_at_utc") or "",
        "sync_state": sync_state,
        "sync_message": sync_message,
        "release_consistent": same_release,
        "accepted_version": target_version,
        "accepted_commit": target_commit[:12],
        "version": version,
        "running_commit": commit[:12],
        "head_commit": str(sync.get("head_commit_short") or ""),
        "head_branch": str(sync.get("head_branch") or ""),
        "dirty_count": int(sync.get("dirty_count") or 0),
        "commit": commit[:12],
        "build_id": str(row.get("build_id") or deployment.get("build_id") or ""),
        "artifact_sha256": "",
        "schema_version": int(row.get("schema_version") or 0),
        "readiness": str(row.get("readiness") or ""),
        "market_data": str(row.get("market_data") or ""),
        "connector": str(row.get("connector") or ""),
        "release_channel": str(row.get("release_channel")
                               or deployment.get("release_channel") or ""),
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


def _identity_gate(environment: str, card: Dict[str, Any],
                   target_version: str, target_commit: str,
                   registry_known: bool) -> Dict[str, Any]:
    """One environment's runtime identity against the accepted release.

    Three answers, not two. "We have not been able to read this environment"
    is not the same claim as "this environment is running the wrong code", and
    collapsing them either blocks a good promotion for no stated reason or --
    worse, in the other direction -- lets an unread environment pass.
    """
    label = f"{environment}: текущие version/commit совпадают с принятым релизом"
    version = str(card.get("version") or "")
    commit = str(card.get("commit") or "")
    if not (target_version and target_commit):
        return {"id": f"{environment}_identity", "label": label,
                "state": "unknown", "ok": False,
                "detail": "Принятый релиз неизвестен этому процессу."}
    if not registry_known or not version or not commit:
        return {"id": f"{environment}_identity", "label": label,
                "state": "unknown", "ok": False,
                "detail": f"Реестр не сообщил, что выполняет {environment}."}
    if version == target_version and target_commit.startswith(commit):
        return {"id": f"{environment}_identity", "label": label,
                "state": "pass", "ok": True, "detail": ""}
    return {
        "id": f"{environment}_identity", "label": label,
        "state": "fail", "ok": False,
        "detail": (f"{environment} выполняет {version} ({commit}), "
                   f"принят {target_version} ({target_commit[:12]})."),
    }


def overall_status(cards: List[Dict[str, Any]],
                   accepted_release: Dict[str, Any],
                   *, registry_known: bool = True,
                   registry_source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Whether all three environments are provably on the accepted release.

    PASS requires proof, and unknown is its own answer: a gate nobody could
    read blocks the pass without claiming a mismatch that was never observed.
    """
    source = registry_source or {}
    target_version = str(accepted_release.get("app_version") or "")
    target_commit = str(accepted_release.get("git_commit_sha") or "")
    target_artifact = _runtime_artifact_sha(accepted_release)
    by_env = {str(card.get("environment") or ""): card for card in cards}
    gates = [
        _identity_gate(environment, by_env.get(environment) or {},
                       target_version, target_commit, registry_known)
        for environment in (runtime_env.DEVELOPMENT, runtime_env.CANARY,
                            runtime_env.PRODUCTION)
    ]

    canary_artifact = str((by_env.get(runtime_env.CANARY) or {}).get("artifact_sha256") or "")
    production_artifact = str((by_env.get(runtime_env.PRODUCTION) or {}).get("artifact_sha256") or "")
    artifact_label = "Canary и Production выполняют один принятый immutable artifact"
    if (not registry_known or not canary_artifact
            or not production_artifact or not target_artifact):
        artifact_gate = {
            "state": "unknown", "ok": False,
            "detail": "Артефакт Canary или Production не прочитан.",
        }
    elif (canary_artifact.lower() == target_artifact.lower()
            and production_artifact.lower() == target_artifact.lower()):
        artifact_gate = {"state": "pass", "ok": True, "detail": ""}
    else:
        artifact_gate = {
            "state": "fail", "ok": False,
            "detail": (f"Canary {canary_artifact[:16]}, "
                       f"Production {production_artifact[:16]}, "
                       f"принят {target_artifact[:16]}."),
        }
    artifact_gate.update({"id": "immutable_server_artifact", "label": artifact_label})
    gates.append(artifact_gate)

    failed = [gate["id"] for gate in gates if gate["state"] == "fail"]
    unknown = [gate["id"] for gate in gates if gate["state"] == "unknown"]
    if failed:
        state, message = "fail", "ALL ENVIRONMENTS PASS запрещён: окружения не согласованы."
    elif unknown:
        state, message = "unknown", "ALL ENVIRONMENTS PASS не доказан: часть окружений не прочитана."
    else:
        state, message = "pass", "ALL ENVIRONMENTS PASS"
    return {
        "ok": state == "pass",
        "state": state,
        "target_version": target_version,
        "target_commit": target_commit[:12],
        "target_artifact_sha256": target_artifact,
        "gates": gates,
        "blocking": failed + unknown,
        "failing": failed,
        "unknown": unknown,
        "registry_known": bool(registry_known),
        "registry_source": str(source.get("source") or ""),
        "registry_origin": str(source.get("origin") or ""),
        "message": message,
    }


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
             registry_is_authoritative: bool = True,
             registry_source: Optional[Dict[str, Any]] = None,
             registry_known: bool = True) -> Dict[str, Any]:
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
    accepted = next((row for row in candidates
                     if str(row.get("state") or "") == "production_live"), {})
    deploys = deployments or {}

    development = development_card(
        sync or {}, rows.get(runtime_env.DEVELOPMENT), accepted)
    canary = server_card(runtime_env.CANARY, rows.get(runtime_env.CANARY),
                         deploys.get(runtime_env.CANARY))
    production = server_card(runtime_env.PRODUCTION, rows.get(runtime_env.PRODUCTION),
                             deploys.get(runtime_env.PRODUCTION))
    cards = [development, canary, production]
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
        "compare": compare(cards),
        "overall": overall_status(cards, accepted,
                                  registry_known=registry_known,
                                  registry_source=registry_source),
        "development_access": development_access(is_local_request),
    }
