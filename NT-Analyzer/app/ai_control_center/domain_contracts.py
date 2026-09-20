"""Additive domain records; no scheduler, permission grant or judge execution.

Profiles, proposals and policy/evidence packets are immutable content references.
Court votes are separate terminal records, never a renamed legacy committee.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar
from uuid import UUID

from . import contracts as c
from .states import ContractError, EntityKind


@dataclass(frozen=True, kw_only=True)
class StrategyProject(c.Record):
    KIND: ClassVar = EntityKind.STRATEGY_PROJECT
    title: str
    definition: c.SnapshotRef
    versions: tuple[c.SnapshotRef, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        c.require_text(self.title)
        c.require_snapshot(self.definition)
        c.require_tuple(self.versions, c.SnapshotRef)
        if len(self.versions) > 1000:
            raise ContractError("project_version_limit")


@dataclass(frozen=True, kw_only=True)
class Routine(c.Record):
    KIND: ClassVar = EntityKind.ROUTINE
    title: str
    definition: c.SnapshotRef
    provenance: tuple[c.SnapshotRef, ...]
    automation_enabled: bool = False
    handoff: c.SnapshotRef | None = None

    def __post_init__(self):
        super().__post_init__()
        c.require_text(self.title)
        c.require_snapshot(self.definition)
        c.require_tuple(self.provenance, c.SnapshotRef)
        if not self.provenance:
            raise ContractError("routine_provenance_required")
        if self.automation_enabled is not False:
            raise ContractError("routine_automation_disabled")
        if self.handoff is not None:
            c.require_snapshot(self.handoff)


@dataclass(frozen=True, kw_only=True)
class CalendarItem(c.Record):
    KIND: ClassVar = EntityKind.CALENDAR_ITEM
    title: str
    definition: c.SnapshotRef
    starts_at: datetime
    ends_at: datetime
    provenance: tuple[c.SnapshotRef, ...]
    automation_enabled: bool = False
    handoff: c.SnapshotRef | None = None

    def __post_init__(self):
        super().__post_init__()
        c.require_text(self.title)
        c.require_snapshot(self.definition)
        c.require_utc(self.starts_at)
        c.require_utc(self.ends_at)
        c.require_tuple(self.provenance, c.SnapshotRef)
        if self.ends_at <= self.starts_at or not self.provenance:
            raise ContractError("invalid_calendar_interval_or_provenance")
        if self.automation_enabled is not False:
            raise ContractError("routine_automation_disabled")
        if self.handoff is not None:
            c.require_snapshot(self.handoff)


@dataclass(frozen=True, kw_only=True)
class CourtCase(c.Record):
    KIND: ClassVar = EntityKind.COURT_CASE
    decision: c.EntityRef
    packet: c.SnapshotRef
    models: tuple[c.EntityRef, ...]
    session_ids: tuple[UUID, ...]
    risk: c.Risk
    votes: tuple[c.EntityRef, ...] = ()
    verdict: str | None = None
    reason_code: str | None = None

    def __post_init__(self):
        super().__post_init__()
        c.require_entity(self.decision, EntityKind.DECISION)
        c.require_snapshot(self.packet)
        c.require_tuple(self.models, c.EntityRef)
        for model in self.models:
            c.require_entity(model, EntityKind.MODEL)
        c.require_tuple(self.session_ids, UUID)
        for session in self.session_ids:
            c.require_uuid(session)
        c.require_enum(self.risk, c.Risk)
        c.require_tuple(self.votes, c.EntityRef)
        for vote in self.votes:
            c.require_entity(vote, EntityKind.COURT_VOTE)
        if len(self.models) != 3 or len(self.session_ids) != 3 or len(set(self.session_ids)) != 3:
            raise ContractError("three_isolated_judges_required")
        if len(self.votes) > 3 or len({vote.entity_id for vote in self.votes}) != len(self.votes):
            raise ContractError("invalid_court_votes")
        if self.verdict not in {None, "approve", "reject", "no_quorum"}:
            raise ContractError("invalid_court_verdict")
        if self.status == "decided" and (len(self.votes) != 3 or self.verdict not in {"approve", "reject"}):
            raise ContractError("court_quorum_required")
        if self.reason_code is not None:
            c.require_token(self.reason_code, limit=80)


@dataclass(frozen=True, kw_only=True)
class CourtVote(c.Record):
    KIND: ClassVar = EntityKind.COURT_VOTE
    case: c.EntityRef
    model: c.EntityRef
    session_id: UUID
    packet: c.SnapshotRef
    verdict: str
    confidence: int
    rationale: c.SnapshotRef
    provider_key: str
    model_key: str
    model_version: str
    failure_domain: str
    contribution_id: UUID | None = None
    contribution: c.EntityRef | None = None

    def __post_init__(self):
        super().__post_init__()
        c.require_entity(self.case, EntityKind.COURT_CASE)
        c.require_entity(self.model, EntityKind.MODEL)
        c.require_uuid(self.session_id)
        c.require_snapshot(self.packet)
        c.require_snapshot(self.rationale)
        if self.verdict not in {"approve", "reject", "abstain"}:
            raise ContractError("invalid_court_verdict")
        if type(self.confidence) is not int or not 0 <= self.confidence <= 100:
            raise ContractError("invalid_confidence")
        for value in (self.provider_key, self.model_key, self.model_version, self.failure_domain):
            c.require_text(value, limit=160)
        if self.contribution_id is not None:
            c.require_uuid(self.contribution_id)
        if self.contribution is not None:
            c.require_entity(self.contribution, EntityKind.CONTRIBUTION)
            if self.contribution.entity_id != self.contribution_id:
                raise ContractError("judge_contribution_mismatch")


@dataclass(frozen=True, kw_only=True)
class JudgeContext:
    """The ONLY prompt context sent to one independently admitted model call."""
    context: c.RequestContext
    model_id: UUID
    case_id: UUID
    session_id: UUID
    packet_json: str
    packet_sha256: str
    run_key: str
    policy_version: str = "court-review-v1"
    prompt_version: str = "isolated-judge-v1"


@dataclass(frozen=True, kw_only=True)
class JudgeResult:
    """Trusted adapter result; provider/model provenance is NOT model output."""
    verdict: str
    confidence: int
    rationale: str
    provider_key: str
    model_key: str
    model_version: str
    failure_domain: str
    contribution_id: UUID | None = None
