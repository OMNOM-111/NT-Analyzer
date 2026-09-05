"""Immutable independent model evaluation, not a routing weight or self-score."""
from dataclasses import dataclass
from typing import ClassVar

from .contracts import Record, EntityRef, SnapshotRef, require_entity, require_snapshot, require_token
from .states import EntityKind


@dataclass(frozen=True, kw_only=True)
class Evaluation(Record):
    KIND: ClassVar = EntityKind.EVALUATION
    task: EntityRef
    outcome: EntityRef
    evidence: SnapshotRef
    model: EntityRef
    rubric_key: str

    def __post_init__(self):
        super().__post_init__()
        require_entity(self.task, EntityKind.TASK)
        require_entity(self.outcome, EntityKind.OUTCOME)
        require_entity(self.model, EntityKind.MODEL)
        require_snapshot(self.evidence)
        require_token(self.rubric_key)
