"""Closed registry of typed Agent World knowledge relationships.

Relationship names are data, not executable capabilities.  Keeping the
registry here makes SQLite and PostgreSQL accept exactly the same graph and
lets a migration reject invented edge semantics instead of silently storing
typos.  Adding a type is an additive contract change with tests and a changelog.
"""
from __future__ import annotations

from types import MappingProxyType


RELATIONSHIP_TYPES = MappingProxyType({
    "USED_MODEL": "An agent or task used a model.",
    "WORKED_ON": "An actor contributed to a task or project.",
    "CREATED": "A subject created a record or artifact.",
    "PRODUCED": "A task or execution produced an outcome.",
    "RESULTED_IN": "A source event resulted in a fact or outcome.",
    "DEPENDS_ON": "A subject depends on another record.",
    "DERIVED_FROM": "A fact or source version was derived from evidence.",
    "VERIFIED_BY": "A fact or outcome was verified by an evaluation or proof.",
    "LEARNED_FROM": "A lesson was learned from a task, outcome, or source.",
    "SUPERSEDES": "A newer fact replaces an older fact for its validity interval.",
    "CONTRADICTS": "Two facts make incompatible claims that need resolution.",
    "RELATED_TO": "A deliberately weak non-causal association.",
    "ABOUT": "A fact or fragment is about an entity.",
    "HAS_FRAGMENT": "A stable source contains a logical fragment.",
})


def validate_relationship_type(value: str) -> None:
    from .states import ContractError

    if not isinstance(value, str) or value not in RELATIONSHIP_TYPES:
        raise ContractError("relationship_type_unregistered")
