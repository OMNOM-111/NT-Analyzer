"""Immutable independent evaluation, not a routing weight or a self-score.

One contract covers every kind of subject. A model, a durable agent role, a
decision and an external agent connection are different things to be good at,
and a score measured for one is never shown as a score for another — so the
subject is typed and carried on the record rather than assumed.
"""
from dataclasses import dataclass
from typing import ClassVar

from .contracts import Record, EntityRef, SnapshotRef, require_entity, require_snapshot, require_token
from .states import ContractError, EntityKind


# What can be evaluated. A subject outside this set is refused rather than
# stored as an untyped reference nobody can interpret later.
#
# An external agent connection belongs here too and is deliberately absent: in
# this codebase an EntityKind means a storable record, and the codec round-trip
# covers every declared kind. Minting the kind before its record exists would
# leave a member nothing can store. P1-5 adds the kind, its states, its codec
# entry and its record together, and appends it to this one line — the seam is
# the typed subject below, which needs no further change to accept it.
SUBJECT_KINDS = frozenset({
    EntityKind.MODEL,
    EntityKind.AGENT_ROLE,
    EntityKind.DECISION,
})


@dataclass(frozen=True, kw_only=True)
class Evaluation(Record):
    KIND: ClassVar = EntityKind.EVALUATION
    task: EntityRef
    outcome: EntityRef
    evidence: SnapshotRef
    subject: EntityRef
    rubric_key: str

    def __post_init__(self):
        super().__post_init__()
        require_entity(self.task, EntityKind.TASK)
        require_entity(self.outcome, EntityKind.OUTCOME)
        require_snapshot(self.evidence)
        if not isinstance(self.subject, EntityRef):
            raise ContractError("reference_kind_mismatch")
        if self.subject.kind not in SUBJECT_KINDS:
            raise ContractError("evaluation_subject_kind_unsupported")
        require_token(self.rubric_key)

    @property
    def model(self) -> EntityRef:
        """Readers written when only a Model could be evaluated.

        Deliberately raises for any other subject: a caller asking an agent
        role or an external connection for its "model" has made a mistake that
        silently returning the subject would hide.
        """
        if self.subject.kind is not EntityKind.MODEL:
            raise ContractError("evaluation_subject_not_a_model")
        return self.subject
