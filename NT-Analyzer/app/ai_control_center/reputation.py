"""Three separate reputation scopes over one Evaluation contract.

A model, a durable agent role and a particular decision are different things to
be good at, and a number measured for one says nothing about another. So there
is no combined score here and no shared aggregate: each scope is computed from
the evaluations recorded against its own subject kind, carries its own sample,
confidence, window and evidence, and reaches `NEW` independently of the others.

Nothing is invented. A scope with too few observations reports insufficient
data rather than a small number presented as a measurement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .states import ContractError, EntityKind


VERSION = "reputation-scopes-v1"
# Below this an observed rate is noise, and the scope says so instead of
# printing a percentage somebody would read as a judgement.
MIN_SAMPLE = 3
DEFAULT_WINDOW_DAYS = 30
# Which subject kind each scope measures. One scope never reads another's rows.
SCOPES = {
    "model_performance": EntityKind.MODEL,
    "agent_role_performance": EntityKind.AGENT_ROLE,
    "decision_performance": EntityKind.DECISION,
}


@dataclass(frozen=True)
class Window:
    days: int = DEFAULT_WINDOW_DAYS

    def contains(self, created_at, now):
        return timedelta(0) <= (now - created_at) <= timedelta(days=self.days)


def _basis(sample, synthetic):
    """What the observations actually were.

    The local test executor produces real runs and real evidence, but it is a
    diagnostic, not the field. A rate computed entirely from it is reported as
    a diagnostic result, never as observed performance.
    """
    if not sample:
        return "none"
    if synthetic == sample:
        return "diagnostic"
    return "field" if not synthetic else "mixed"


def _confidence(sample, passed):
    """Deliberately coarse: sample size first, agreement second.

    A narrow band on four observations is not high confidence, and calling it
    that is how a test fixture turns into a reputation.
    """
    if sample < MIN_SAMPLE:
        return "insufficient"
    if sample < 10:
        return "low"
    return "medium" if passed < sample else "high"


def _read_proof(service, context, record):
    try:
        return service._json(context, record.evidence)
    except ContractError:
        return None


def scope_for(subject_kind):
    for name, kind in SCOPES.items():
        if kind is subject_kind:
            return name
    raise ContractError("reputation_scope_unsupported")


def measure(service, context, *, subject_kind, subject_id, task_class, now, window=Window()):
    """One scope, one subject, one task class. Never a blend of several.

    `task_class` is part of the identity of a measurement: being reliable at a
    bounded arithmetic check says nothing about being reliable at anything else,
    so the two are never pooled.
    """
    if subject_kind not in SCOPES.values():
        raise ContractError("reputation_scope_unsupported")
    observations, evidence_refs, newest = [], [], None
    for record in service._all(context, EntityKind.EVALUATION):
        if record.subject.kind is not subject_kind or record.subject.entity_id != subject_id:
            continue
        if record.rubric_key != task_class or not window.contains(record.header.created_at, now):
            continue
        proof = _read_proof(service, context, record)
        if proof is None or proof.get("self_scored") is not False:
            # A self-reported score is not an observation of anything.
            continue
        observations.append(proof)
        newest = record.header.created_at if newest is None else max(newest, record.header.created_at)
        evidence_refs.append({"evaluation_id": str(record.header.entity_id),
                              "outcome_id": str(record.outcome.entity_id),
                              "evidence_sha256": record.evidence.sha256})
    sample = len(observations)
    passed = sum(1 for proof in observations if proof.get("passed") is True)
    synthetic = sum(1 for proof in observations if proof.get("synthetic") is True)
    enough = sample >= MIN_SAMPLE
    basis = _basis(sample, synthetic)
    return {
        "version": VERSION,
        "scope": scope_for(subject_kind),
        "subject": {"kind": subject_kind.value, "id": str(subject_id)},
        "task_class": task_class,
        "sample_size": sample,
        "confidence": _confidence(sample, passed),
        "status": "measured" if enough else "new",
        # Separate from `status`: a sample can be large enough to measure and
        # still be nothing but diagnostics.
        "basis": basis,
        "quality": {"passed": passed, "observed_pct": round(100.0 * passed / sample, 1) if enough else None},
        "evidence_refs": evidence_refs,
        # Anchored to the newest observation counted, not to the wall clock: the
        # same rows must measure the same however often they are read, or two
        # identical reads of one task disagree for no reason anybody can act on.
        "window": {"days": window.days,
                   "newest_observation": newest.isoformat() if newest else None},
        "provenance": {
            "evaluator": "independent_local_evidence_verifier",
            "self_scored": False,
            "synthetic_observations": synthetic,
            "measured_observations": sample - synthetic,
            "professional_quality_assessed": False,
        },
        # Said plainly so a reader never has to infer it from a small number,
        # or from a percentage that came entirely from the local diagnostic.
        "limitation": ("Недостаточно наблюдений для оценки." if not enough else
                       "Все наблюдения получены локальным диагностическим исполнителем. "
                       "Это результат диагностики, а не наблюдаемое качество работы."
                       if basis == "diagnostic" else
                       "Часть наблюдений получена локальным диагностическим исполнителем; "
                       "доля указана в происхождении оценки." if basis == "mixed" else
                       "Наблюдаемая проверка формата ответа в этом классе задач, "
                       "не профессиональная оценка качества."),
    }
