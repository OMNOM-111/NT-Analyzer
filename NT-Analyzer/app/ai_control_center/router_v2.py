"""Explainable, scoped model selection; shadow does not change legacy routing.

Identity, current admission and same-class measurements are distinct inputs.
Diagnostic evidence is never a professional-quality score. This module reads
only the existing records and artifacts and never opens a provider connection.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from . import contracts as c
from .flags import DISABLED, Flag, current_snapshot, resolve
from .model_evaluation import digest
from .states import ContractError, EntityKind


VERSION = "agent-world-router-v2.1"
_CLASSES = frozenset({"json_arithmetic", "extract_facts", "backtest_spec", "chart_spec"})


@dataclass(frozen=True, kw_only=True)
class RoutingPolicy:
    """Trusted server composition, not a request-body policy or permission."""

    version: str = VERSION
    min_distinct_samples: int = 3
    max_candidates: int = 20
    max_sample_age_seconds: int = 30 * 86400

    def __post_init__(self):
        c.require_token(self.version)
        if (type(self.min_distinct_samples) is not int or not 3 <= self.min_distinct_samples <= 100
                or type(self.max_candidates) is not int or not 1 <= self.max_candidates <= 50
                or type(self.max_sample_age_seconds) is not int or not 60 <= self.max_sample_age_seconds <= 90 * 86400):
            raise ContractError("routing_policy_invalid")


def _number(value, *, positive=False):
    return (type(value) in {int, float} and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def _gate(authorized, mode):
    if type(mode) is not str or mode not in {"shadow", "active"} or not isinstance(authorized, dict):
        raise ContractError("routing_mode_invalid")
    context = authorized.get("context")
    if not isinstance(context, c.RequestContext) or not callable(authorized.get("admit")):
        raise ContractError("routing_context_required")
    authorized["admit"]()
    # An active switch is not an interpretation of the existing shadow flag.
    flag = getattr(Flag, "AI_ROUTER_V2", None) if mode == "active" else Flag.AI_ROUTER_SHADOW_V2
    if flag is None or not resolve(flag, scope=context.scope, snapshot=current_snapshot(authorized)).enabled:
        raise ContractError("routing_disabled")
    if mode == "active" and (authorized.get("read_only") or authorized.get("session_read_only")):
        raise ContractError("routing_read_only")
    return context


def _observations(service, context, model, task_class, now, policy):
    """Read independently recorded model observations for this exact class."""
    rows = {}
    for record in service._all(context, EntityKind.EVALUATION):
        if record.rubric_key != task_class or record.model.entity_id != model.header.entity_id:
            continue
        if not 0 <= (now - record.header.created_at).total_seconds() <= policy.max_sample_age_seconds:
            continue
        proof = service._json(context, record.evidence)
        if (proof.get("rubric_key") != task_class or proof.get("synthetic") is not False
                or proof.get("self_scored") is not False
                or proof.get("evaluator") != "independent_local_evidence_verifier"
                or proof.get("model_id") != str(model.header.entity_id)
                or type(proof.get("passed")) is not bool or not _number(proof.get("latency_ms"))
                or not _number(proof.get("cost_usd"))):
            continue
        source = service._get(context, EntityKind.TASK, record.task.entity_id)
        checkpoint = service._json(context, source.checkpoint)
        if (checkpoint.get("synthetic") is not False or checkpoint.get("source") != "real_model_task"
                or checkpoint.get("model_id") != str(model.header.entity_id)
                or checkpoint.get("spec", {}).get("rubric_key") != task_class
                or proof.get("input_sha256") != digest(checkpoint["spec"])
                or proof.get("task_id") != str(source.header.entity_id)):
            continue
        receipt_ref = proof.get("receipt")
        if not receipt_ref or receipt_ref != checkpoint.get("receipt"):
            continue
        receipt = service._json(context, receipt_ref)
        if (receipt.get("task_id") != str(source.header.entity_id)
                or receipt.get("request_sha256") != checkpoint.get("request_sha256")
                or receipt.get("latency_ms") != proof["latency_ms"] or receipt.get("cost_usd") != proof["cost_usd"]):
            continue
        # One immutable input is one observation; another retry is not a sample.
        rows.setdefault(proof["input_sha256"], {"ref": c.primitive(record.ref()),
            "latency_ms": proof["latency_ms"], "cost_usd": proof["cost_usd"], "passed": proof["passed"]})
    return [rows[key] for key in sorted(rows)]


def select(authorized, service, request, policy=None, *, quote=None, now=None):
    """Return candidate/exclusion evidence; caller must use normal task ingress.

    quote is a trusted server callback(context, model, account, profile), using
    existing permission/pricing/budget authorities. It returns current bounded
    cost_usd and allowed=True, or denies. Missing pricing is never guessed from
    the historical mean. No result grants task, tool or credential access.
    """
    from datetime import datetime, timezone
    policy = policy or RoutingPolicy()
    if not isinstance(policy, RoutingPolicy) or type(request) is not dict:
        raise ContractError("routing_request_invalid")
    if set(request) != {"mode", "task_class", "candidate_model_ids", "current_model_id", "max_cost_usd", "max_latency_ms"}:
        raise ContractError("routing_request_invalid")
    context = _gate(authorized, request["mode"])
    if type(request["task_class"]) is not str or request["task_class"] not in _CLASSES or not _number(request["max_cost_usd"]) or not _number(request["max_latency_ms"], positive=True):
        raise ContractError("routing_constraints_invalid")
    ids = request["candidate_model_ids"]
    if type(ids) is not list or not 1 <= len(ids) <= policy.max_candidates:
        raise ContractError("routing_candidates_invalid")
    from .model_service import _id, _uuid
    model_ids = tuple(_uuid(value) for value in ids)
    if len(set(model_ids)) != len(model_ids):
        raise ContractError("routing_candidates_invalid")
    current_id = _uuid(request["current_model_id"])
    if current_id not in model_ids:
        raise ContractError("routing_current_candidate_required")
    now = now or datetime.now(timezone.utc)
    c.require_utc(now)
    rows = []
    for identity in model_ids:
        row = {"model_id": str(identity), "eligible": False, "reason_codes": [], "quality_score": None,
               "quality_effect": "none", "evidence": [], "task_class": request["task_class"]}
        try:
            authorized["admit"]()
            model = service._get(context, EntityKind.MODEL, identity)
            profile = service._json(context, model.profile)
            persona = service._get(context, EntityKind.PERSONA, profile["persona_id"])
            account = service._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
            role = service._get(context, EntityKind.AGENT_ROLE, _id(context, "role:model-response"))
            if (model.status != "active" or persona.status != "active" or account.status != "active"
                    or role.status != "active" or role.role_key != "model_response"):
                raise ContractError("routing_identity_inactive")
            if profile.get("connection_kind") not in {"model", "external_agent"} or "text" not in model.modalities:
                raise ContractError("routing_connection_kind_unsupported")
            row.update(persona_id=str(persona.header.entity_id), role_id=str(role.header.entity_id),
                provider_account_id=str(account.header.entity_id), provider=model.provider_key,
                model_key=model.model_key, connection_kind=profile["connection_kind"],
                external_agent_id=str(model.header.entity_id) if profile["connection_kind"] == "external_agent" else None,
                identity_revisions={"persona": persona.header.revision, "role": role.header.revision,
                    "provider_account": account.header.revision, "model": model.header.revision})
            if profile.get("connected") is not True:
                raise ContractError("routing_connection_not_verified")
            if not callable(quote):
                raise ContractError("routing_current_admission_unavailable")
            allowance = quote(context=context, model=model, account=account, profile=profile)
            if (type(allowance) is not dict or allowance.get("allowed") is not True
                    or not _number(allowance.get("cost_usd"))):
                raise ContractError("routing_current_admission_denied")
            if allowance["cost_usd"] > request["max_cost_usd"]:
                raise ContractError("routing_cost_limit")
            # Includes present capability and workspace budget, not just history.
            service._access(context, "task", allowance["cost_usd"])
            observations = _observations(service, context, model, request["task_class"], now, policy)
            row.update(sample_size=len(observations), evidence=[item["ref"] for item in observations])
            if len(observations) < policy.min_distinct_samples:
                raise ContractError("routing_same_class_insufficient_data")
            if not all(item["passed"] for item in observations):
                raise ContractError("routing_same_class_verification_failed")
            required_role = {"backtest_spec": "backtest_researcher", "chart_spec": "chart_researcher"}.get(request["task_class"])
            if required_role and service._json(context, persona.profile).get("application_role") != required_role:
                raise ContractError("routing_application_role_unassigned")
            worst_latency = max(item["latency_ms"] for item in observations)
            if worst_latency > request["max_latency_ms"]:
                raise ContractError("routing_latency_limit")
            row.update(eligible=True, current_cost_usd=allowance["cost_usd"], observed_max_latency_ms=worst_latency)
            row["reason_codes"] = ["current_authority_pass", "same_class_latency_evidence", "cost_then_latency_policy"]
        except ContractError as exc:
            row["reason_codes"] = [exc.code]
        rows.append(row)
    eligible = sorted((row for row in rows if row["eligible"]),
                      key=lambda row: (row["current_cost_usd"], row["observed_max_latency_ms"], row["model_id"]))
    selected = eligible[0]["model_id"] if eligible else None
    _gate(authorized, request["mode"])
    result = {"schema_version": 1, "policy_version": policy.version, "mode": request["mode"],
        "workspace_id": context.scope.workspace_id, "user_uuid": str(context.user_uuid),
        "task_class": request["task_class"], "selected_model_id": selected,
        "effective_model_id": selected if request["mode"] == "active" else str(current_id),
        "legacy_model_id": str(current_id), "matches_legacy": selected == str(current_id),
        "status": "selected" if selected else "blocked", "candidates": rows,
        "constraints": {key: request[key] for key in ("max_cost_usd", "max_latency_ms")},
        "quality_ranking": False, "dispatch_performed": False, "permission_granted": False,
        "measured_at": now.isoformat(), "synthetic": False}
    result["decision_sha256"] = digest(result)
    return result
