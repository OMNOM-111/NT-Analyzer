"""Who is allowed to promote, decided where the truth lives.

The promotion gates need two kinds of fact and they live in different places.
The release ledger -- candidate state, artifact digest, signature, acceptance --
is held by whoever cut the candidate, normally LOCAL. Whether Canary is *right
now* alive and actually running that artifact is held by the environment
registry, which is authoritative only on a server: on LOCAL,
``environment_registry.snapshot()`` returns nothing but LOCAL's own row.

So a promotion driven from LOCAL used to be structurally impossible. The
``artifact_unchanged`` gate could never pass, because LOCAL cannot see Canary.
Relaxing it on LOCAL would have been the wrong repair -- that gate is the one
that stops Production receiving something nobody verified.

Instead LOCAL asks. It sends the ledger facts it can attest to, signed with the
same key and replay protection the environment heartbeats already use, and the
server decides against its own registry. The owner drives the whole workflow
from one screen; the authority to say yes never leaves the server.

Nothing here fails open. An unreachable control plane, an unsigned request, a
non-authoritative responder and a stale Canary all produce the same outcome:
not allowed, with the reason said out loud.
"""
from __future__ import annotations

import json
import secrets
from typing import Any, Dict, List, Optional

from . import environment_registry, runtime_env

CONTROL_PATH = "/api/environments/release-control"

# A decision is about one artifact and is not reusable for another. It is also
# short-lived: "Canary was healthy a minute ago" is not a statement about now.
DECISION_TTL_SEC = 120

# Acceptance is a reached milestone, not a state the candidate remains in.
# The ordinary UI flow advances ``canary_passed`` to
# ``approved_for_production`` before it asks the authoritative server for the
# promotion decision.  Treating only the literal ``canary_passed`` value as
# accepted makes that valid sequence reject itself.  Production failures stay
# retryable in Release Center, so they retain the same proved Canary milestone.
_CANARY_ACCEPTED_STATES = {
    "canary_passed",
    "approved_for_production",
    "production_scheduled",
    "production_deploying",
    "production_failed",
    "production_live",
}
_CANARY_MIGRATED_STATES = {"canary_checking", *_CANARY_ACCEPTED_STATES}


def _gate(gate_id: str, label: str, ok: bool) -> Dict[str, Any]:
    return {"id": gate_id, "label": label, "ok": bool(ok)}


# --------------------------------------------------------------------------- #
# Server side: the authority.
# --------------------------------------------------------------------------- #
def decide(claim: Dict[str, Any], *, registry: Optional[Dict[str, Any]] = None,
           now: Optional[float] = None) -> Dict[str, Any]:
    """Rule on one promotion request, against this server's own registry.

    ``claim`` carries what the requester attests about the candidate. Those
    facts are taken at face value on purpose -- the requester is the ledger of
    record for them, and it authenticated itself to say so. What is *not* taken
    on trust is anything about the running environments: every gate below that
    concerns Canary is answered from the registry this server holds, which is
    the reason the request was made at all.
    """
    snapshot = registry if registry is not None else environment_registry.snapshot()
    rows = {str(r.get("environment") or ""): r
            for r in (snapshot.get("environments") or [])}
    canary = rows.get(runtime_env.CANARY) or {}

    artifact = str(claim.get("artifact_sha256") or "").strip().lower()
    canary_artifact = str(canary.get("artifact_sha256") or "").strip().lower()
    canary_state = str(canary.get("state") or "never_seen")

    gates: List[Dict[str, Any]] = [
        _gate("candidate_state", "Кандидат прошёл приёмку Canary",
              str(claim.get("state") or "") in _CANARY_ACCEPTED_STATES),
        _gate("acceptance", "Приёмка Canary пройдена",
              bool(claim.get("acceptance_passed"))),
        _gate("ci_green", "Обязательный CI зелёный для этого commit",
              bool(claim.get("ci_green"))),
        _gate("migrations", "Миграции применены",
              bool(claim.get("migrations_applied"))),
        _gate("artifact_signed", "Артефакт подписан и проверен",
              str(claim.get("signature_status") or "") == "verified" and bool(artifact)),
        # From here the server answers for itself.
        _gate("canary_live", "Canary отвечает сейчас", canary_state == "live"),
        _gate("canary_runs_candidate", "Canary запущен на этом артефакте",
              bool(artifact) and canary_artifact == artifact),
    ]
    blocking = [g for g in gates if not g["ok"]]
    decided_at = environment_registry._now() if now is None else float(now)
    return {
        "ok": True,
        "allowed": not blocking,
        "gates": gates,
        "blocking": [g["id"] for g in blocking],
        "reason": "" if not blocking else "; ".join(g["label"] for g in blocking),
        # Named so the caller can tell an authoritative answer from an echo.
        "decided_by": runtime_env.deployment_environment(),
        "decided_at_epoch": int(decided_at),
        "expires_at_epoch": int(decided_at) + DECISION_TTL_SEC,
        "artifact_sha256": artifact,
        "candidate_id": str(claim.get("candidate_id") or ""),
        "canary": {
            "state": canary_state,
            "app_version": canary.get("app_version") or "",
            "artifact_sha256": canary_artifact,
            "last_seen_at_utc": canary.get("last_seen_at_utc") or "",
        },
    }


def authoritative() -> bool:
    """Whether this process may rule on promotions at all.

    Only an environment whose registry is the real one. A development box
    answering this would be quoting itself back to itself.
    """
    from . import storage_router

    return bool(storage_router.production_enabled())


# --------------------------------------------------------------------------- #
# Client side: the request.
# --------------------------------------------------------------------------- #
def claim_for(candidate: Dict[str, Any], *, ci_green: bool) -> Dict[str, Any]:
    """The ledger facts this environment is prepared to attest to."""
    state = str(candidate.get("state") or "")
    # The environment registry reports the digest embedded in the running
    # release identity.  That is the signed manifest digest, not the checksum
    # of the transport ZIP.  Release Center deliberately keeps both: the ZIP
    # checksum proves the uploaded archive, while the manifest checksum proves
    # which extracted code Canary is actually executing.  Asking the server to
    # compare Canary with the archive checksum makes two correct identities
    # look different and permanently blocks same-artifact promotion.
    archive_sha = str(candidate.get("artifact_sha256") or "")
    runtime_sha = str(candidate.get("manifest_sha256") or archive_sha)
    return {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "app_version": str(candidate.get("app_version") or ""),
        "release_channel": str(candidate.get("release_channel") or ""),
        "git_commit_sha": str(candidate.get("git_commit_sha") or ""),
        "artifact_sha256": runtime_sha,
        "archive_sha256": archive_sha,
        "manifest_sha256": str(candidate.get("manifest_sha256") or ""),
        "signature_status": str(candidate.get("signature_status") or ""),
        "state": state,
        "acceptance_passed": state in _CANARY_ACCEPTED_STATES,
        "migrations_applied": state in _CANARY_MIGRATED_STATES,
        "ci_green": bool(ci_green),
        "requested_by_environment": runtime_env.deployment_environment(),
    }


def unavailable(reason: str, code: str = "control_plane_unavailable") -> Dict[str, Any]:
    """A refusal shaped like a decision, so no caller can mistake it for a yes."""
    return {
        "ok": False, "allowed": False, "available": False,
        "gates": [], "blocking": [code], "reason": reason,
        "decided_by": "", "code": code,
    }


def request_decision(claim: Dict[str, Any], *, origins: Optional[List[str]] = None,
                     timeout: float = 8.0) -> Dict[str, Any]:
    """Ask the authoritative servers, and take the first real answer.

    Every failure mode -- no token, no peer configured, transport error, an
    answer from something that is not authoritative -- returns not-allowed with
    a reason. There is no path here that returns allowed without a server
    having said so.
    """
    import urllib.error
    import urllib.request

    targets = origins if origins is not None else environment_registry.peer_origins()
    if not targets:
        return unavailable(
            "Control plane не настроен: некуда отправить запрос на промоушен.",
            code="control_plane_not_configured")
    if not environment_registry.token_configured():
        return unavailable(
            "Нет ключа для подписи запроса к control plane.",
            code="control_plane_key_missing")

    payload = dict(claim)
    payload["nonce"] = secrets.token_hex(16)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    timestamp = int(environment_registry._now())
    signature = environment_registry.SIGNATURE_VERSION + "=" + environment_registry.sign(
        environment_registry.token(), timestamp=timestamp, body=body,
    )

    last = unavailable("Control plane не ответил.")
    for origin in targets:
        target = str(origin or "").strip().rstrip("/")
        if not target:
            continue
        request = urllib.request.Request(
            target + CONTROL_PATH, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                environment_registry.TIMESTAMP_HEADER: str(timestamp),
                environment_registry.SIGNATURE_HEADER: signature,
                "User-Agent": "StratForge-Release-Control/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                answer = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = unavailable(
                "Control plane отклонил запрос (HTTP %s)." % exc.code,
                code="control_plane_refused")
            continue
        except Exception:
            # Deliberately broad: a peer being unreachable is ordinary, and the
            # exception type is not something to show an operator.
            last = unavailable("Control plane недоступен: %s." % target)
            continue
        if not isinstance(answer, dict) or not answer.get("decided_by"):
            last = unavailable(
                "Ответ control plane не выглядит решением.",
                code="control_plane_answer_invalid")
            continue
        # An answer only counts from a server environment entitled to give one,
        # and only for the exact candidate and artifact that were asked about.
        if str(answer.get("decided_by") or "") not in {
                runtime_env.CANARY, runtime_env.PRODUCTION}:
            last = unavailable(
                "Ответ пришёл не от authoritative server environment.",
                code="control_plane_answer_not_authoritative")
            continue
        if str(answer.get("artifact_sha256") or "").lower() != str(
                claim.get("artifact_sha256") or "").lower():
            last = unavailable(
                "Решение control plane относится к другому артефакту.",
                code="control_plane_artifact_mismatch")
            continue
        if str(answer.get("candidate_id") or "") != str(
                claim.get("candidate_id") or ""):
            last = unavailable(
                "Решение control plane относится к другому кандидату.",
                code="control_plane_candidate_mismatch")
            continue
        try:
            decided_at = int(answer.get("decided_at_epoch"))
            expires_at = int(answer.get("expires_at_epoch"))
        except (TypeError, ValueError):
            last = unavailable(
                "Ответ control plane не содержит проверяемого срока действия.",
                code="control_plane_decision_invalid")
            continue
        moment = int(environment_registry._now())
        duration = expires_at - decided_at
        if (
            abs(moment - decided_at) > environment_registry.MAX_CLOCK_SKEW_SEC
            or expires_at <= moment
            or duration <= 0
            or duration > DECISION_TTL_SEC
        ):
            last = unavailable(
                "Решение control plane устарело.",
                code="control_plane_decision_stale")
            continue
        answer["available"] = True
        return answer
    return last
