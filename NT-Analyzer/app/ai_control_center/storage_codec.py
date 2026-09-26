"""Strict internal JSON codec for the reviewed immutable contracts.

This is not a request-body decoder. Only the fixed contract classes below are
allowed; stored class/module names never cause imports or object construction.
"""
from __future__ import annotations

import json
import types
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Union, get_args, get_origin, get_type_hints
from uuid import UUID

from . import contracts as c
from .domain_contracts import CalendarItem, CourtCase, CourtVote, Routine, StrategyProject
from .model_contracts import Evaluation
from .external_agent_contracts import ExternalAgentConnection
from .events import EventEnvelope
from .states import ContractError, EntityKind


_RECORD_TYPES = {cls.KIND: cls for cls in (
    c.Persona, c.AgentRole, c.ProviderAccount, c.Model, c.Intent, c.Task,
    c.Contribution, c.Decision, c.Execution, c.Outcome, c.Memory,
    StrategyProject, Routine, CalendarItem, CourtCase, CourtVote, Evaluation, ExternalAgentConnection,
)}
MAX_RECORD_BYTES = 256 * 1024


def _decode(annotation, value):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for candidate in args:
            try:
                return _decode(candidate, value)
            except (ContractError, TypeError, ValueError, KeyError):
                continue
        raise ContractError("stored_contract_invalid")
    if annotation is type(None):
        if value is not None:
            raise ContractError("stored_contract_invalid")
        return None
    if origin is tuple:
        if type(value) is not list or len(args) != 2 or args[1] is not Ellipsis:
            raise ContractError("stored_contract_invalid")
        return tuple(_decode(args[0], item) for item in value)
    if annotation is UUID:
        if type(value) is not str:
            raise ContractError("stored_contract_invalid")
        return UUID(value)
    if annotation is datetime:
        if type(value) is not str:
            raise ContractError("stored_contract_invalid")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if type(value) is not str:
            raise ContractError("stored_contract_invalid")
        return annotation(value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        names = {field.name for field in fields(annotation)}
        if type(value) is not dict or set(value) != names:
            raise ContractError("stored_contract_invalid")
        hints = get_type_hints(annotation)
        return annotation(**{name: _decode(hints[name], value[name]) for name in names})
    if annotation in (str, int, bool) and type(value) is annotation:
        return value
    raise ContractError("stored_contract_invalid")


def _parse(raw: str) -> object:
    if type(raw) is not str or len(raw.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ContractError("stored_contract_invalid")
    try:
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result

        return json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError) as exc:
        raise ContractError("stored_contract_invalid") from exc


def _encode(value) -> str:
    raw = json.dumps(c.primitive(value), sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ContractError("stored_contract_too_large")
    return raw


def encode_record(record: c.Record) -> str:
    if type(record) not in _RECORD_TYPES.values():
        raise ContractError("stored_contract_invalid")
    return _encode(record)


def decode_record(raw: str) -> c.Record:
    try:
        value = _parse(raw)
        if type(value) is not dict:
            raise ContractError("stored_contract_invalid")
        kind = EntityKind(value.pop("kind"))
        cls = _RECORD_TYPES[kind]
        if kind is EntityKind.EVALUATION and "model" in value and "subject" not in value:
            # Written before an evaluation could name anything but a Model.
            # The bytes on disk are left alone; only this reading maps them.
            value["subject"] = value.pop("model")
        return _decode(cls, value)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ContractError("stored_contract_invalid") from exc


def encode_event(event: EventEnvelope) -> str:
    if type(event) is not EventEnvelope:
        raise ContractError("stored_contract_invalid")
    return _encode(event)


def decode_event(raw: str) -> EventEnvelope:
    try:
        return _decode(EventEnvelope, _parse(raw))
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ContractError("stored_contract_invalid") from exc
