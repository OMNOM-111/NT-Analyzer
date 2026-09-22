"""New domain transitions; legacy display projections live in adapters.py."""
from __future__ import annotations

from enum import Enum
from types import MappingProxyType


class ContractError(ValueError):
    """Stable safe error code; never include caller data in error messages."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EntityKind(str, Enum):
    PERSONA = "persona"
    AGENT_ROLE = "agent_role"
    PROVIDER_ACCOUNT = "provider_account"
    MODEL = "model"
    INTENT = "intent"
    TASK = "task"
    CONTRIBUTION = "contribution"
    DECISION = "decision"
    EXECUTION = "execution"
    OUTCOME = "outcome"
    MEMORY = "memory"
    KNOWLEDGE_ENTITY = "knowledge_entity"
    RELATIONSHIP = "relationship"
    KNOWLEDGE_SOURCE = "knowledge_source"
    STRATEGY_PROJECT = "strategy_project"
    ROUTINE = "routine"
    CALENDAR_ITEM = "calendar_item"
    COURT_CASE = "court_case"
    COURT_VOTE = "court_vote"
    EVALUATION = "evaluation"
    EXTERNAL_AGENT_CONNECTION = "external_agent_connection"


def _graph(**edges: tuple[str, ...]):
    graph = {state: frozenset(targets) for state, targets in edges.items()}
    for targets in tuple(graph.values()):
        for target in targets:
            graph.setdefault(target, frozenset())
    return MappingProxyType(graph)


_PROFILE = _graph(draft=("active", "retired"), active=("suspended", "retired"),
                  suspended=("active", "retired"))
TRANSITIONS = MappingProxyType({
    EntityKind.EXTERNAL_AGENT_CONNECTION: _graph(
        draft=("verifying", "disabled", "revoked"),
        verifying=("active", "degraded", "disabled", "revoked"),
        active=("verifying", "degraded", "disabled", "revoked"),
        degraded=("verifying", "disabled", "revoked"),
        disabled=("verifying", "revoked")),
    EntityKind.PERSONA: _PROFILE,
    EntityKind.AGENT_ROLE: _PROFILE,
    EntityKind.PROVIDER_ACCOUNT: _PROFILE,
    EntityKind.MODEL: _PROFILE,
    EntityKind.INTENT: _graph(
        draft=("ready", "cancelled"), ready=("running", "blocked", "cancelled"),
        running=("waiting", "blocked", "completed", "failed", "cancelled"),
        waiting=("ready", "cancelled", "failed"), blocked=("ready", "cancelled", "failed")),
    EntityKind.TASK: _graph(
        planned=("ready", "blocked", "cancelled"), ready=("running", "blocked", "cancelled"),
        running=("waiting", "review", "blocked", "succeeded", "failed", "cancelled"),
        waiting=("ready", "cancelled", "failed"),
        review=("ready", "succeeded", "cancelled", "failed"),
        blocked=("ready", "cancelled", "failed")),
    EntityKind.CONTRIBUTION: _graph(
        draft=("submitted", "withdrawn"), submitted=("accepted", "rejected", "withdrawn")),
    EntityKind.DECISION: _graph(
        proposed=("review", "rejected", "withdrawn"), review=("approved", "rejected", "expired"),
        approved=("superseded", "expired")),
    EntityKind.EXECUTION: _graph(
        requested=("queued", "rejected", "cancelled"), queued=("running", "cancelled", "expired"),
        running=("succeeded", "failed", "deviated", "review"),
        review=("succeeded", "failed", "cancelled", "deviated")),
    EntityKind.OUTCOME: _graph(
        pending=("verified", "disputed"), verified=("disputed", "superseded"),
        disputed=("verified", "rejected", "superseded")),
    EntityKind.MEMORY: _graph(
        draft=("active", "revoked", "expired"), active=("superseded", "revoked", "expired")),
    EntityKind.KNOWLEDGE_ENTITY: _graph(
        active=("merged", "retired")),
    EntityKind.RELATIONSHIP: _graph(
        active=("superseded", "revoked", "expired")),
    EntityKind.KNOWLEDGE_SOURCE: _graph(
        active=("retired",)),
    EntityKind.STRATEGY_PROJECT: _graph(draft=("active", "archived"), active=("archived",)),
    EntityKind.ROUTINE: _graph(proposed=("accepted", "dismissed"), accepted=("dismissed",)),
    EntityKind.CALENDAR_ITEM: _graph(proposed=("accepted", "dismissed"), accepted=("dismissed",)),
    EntityKind.COURT_CASE: _graph(open=("voting", "withdrawn"), voting=("decided", "blocked", "withdrawn")),
    EntityKind.COURT_VOTE: _graph(recorded=()),
    EntityKind.EVALUATION: _graph(recorded=()),
})

INITIAL_STATES = MappingProxyType({
    EntityKind.EXTERNAL_AGENT_CONNECTION: "draft",
    **{kind: "draft" for kind in (EntityKind.PERSONA, EntityKind.AGENT_ROLE,
                                 EntityKind.PROVIDER_ACCOUNT, EntityKind.MODEL)},
    EntityKind.INTENT: "draft", EntityKind.TASK: "planned",
    EntityKind.CONTRIBUTION: "draft", EntityKind.DECISION: "proposed",
    EntityKind.EXECUTION: "requested", EntityKind.OUTCOME: "pending", EntityKind.MEMORY: "draft",
    EntityKind.KNOWLEDGE_ENTITY: "active", EntityKind.RELATIONSHIP: "active",
    EntityKind.KNOWLEDGE_SOURCE: "active",
    EntityKind.STRATEGY_PROJECT: "draft", EntityKind.ROUTINE: "proposed",
    EntityKind.CALENDAR_ITEM: "proposed", EntityKind.COURT_CASE: "open",
    EntityKind.COURT_VOTE: "recorded", EntityKind.EVALUATION: "recorded",
})


def validate_state(kind: EntityKind, state: str) -> None:
    if not isinstance(kind, EntityKind) or not isinstance(state, str) or state not in TRANSITIONS[kind]:
        raise ContractError("invalid_state")


# Versioned edits/checkpoints within a phase; finalized content uses a successor.
EDITABLE_STATES = MappingProxyType({
    EntityKind.EXTERNAL_AGENT_CONNECTION: frozenset({"draft", "verifying", "active", "degraded", "disabled"}),
    **{kind: frozenset({"draft", "active", "suspended"}) for kind in (
        EntityKind.PERSONA, EntityKind.AGENT_ROLE, EntityKind.PROVIDER_ACCOUNT, EntityKind.MODEL)},
    EntityKind.INTENT: frozenset({"draft"}),
    EntityKind.TASK: frozenset({"planned", "ready", "running", "waiting", "review", "blocked"}),
    EntityKind.CONTRIBUTION: frozenset({"draft"}),
    EntityKind.DECISION: frozenset({"proposed", "review"}),
    EntityKind.EXECUTION: frozenset({"requested", "queued", "running", "review"}),
    EntityKind.OUTCOME: frozenset({"pending", "disputed"}),
    EntityKind.MEMORY: frozenset({"draft"}),
    EntityKind.KNOWLEDGE_ENTITY: frozenset({"active"}),
    EntityKind.RELATIONSHIP: frozenset({"active"}),
    EntityKind.KNOWLEDGE_SOURCE: frozenset({"active"}),
    EntityKind.STRATEGY_PROJECT: frozenset({"draft", "active"}),
    EntityKind.ROUTINE: frozenset({"proposed"}),
    EntityKind.CALENDAR_ITEM: frozenset({"proposed"}),
    EntityKind.COURT_CASE: frozenset({"open", "voting"}),
    EntityKind.COURT_VOTE: frozenset(),
    EntityKind.EVALUATION: frozenset(),
})


def validate_transition(kind: EntityKind, previous: str, following: str) -> None:
    """Validate an edge, not permission, evidence, a replay or a storage write."""
    validate_state(kind, previous)
    validate_state(kind, following)
    if following not in TRANSITIONS[kind][previous]:
        raise ContractError("invalid_transition")
