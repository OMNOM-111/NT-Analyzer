"""Owned Persona addressing over existing profiles, adapters and task stores.

Names select a stable identity, never authority, tools or credentials. This
module neither calls a model nor creates a second chat/queue/preference store.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from uuid import UUID

from . import contracts as c
from .states import ContractError, EntityKind


IDENTITY_FIELDS = ("aliases", "main_assistant")
_RESERVED = {"модель", "model", "координатор", "coordinator"}
_ADDRESS = re.compile(r"^\s*(@?)([^\n,:]{1,160})\s*[:,]\s*([\s\S]*)$")
_LIVE_STATES = {"active", "suspended"}


def name_key(value):
    """A comparison token, not a replacement for the saved display name."""
    if type(value) is not str or not value or len(value) > 160:
        return ""
    text = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not text or text in _RESERVED or any(unicodedata.category(ch).startswith("C") for ch in text):
        return ""
    return text


def normalize_fields(payload):
    result = {}
    if "aliases" in payload:
        values = payload["aliases"]
        if type(values) is not list or len(values) > 5:
            raise ContractError("persona_aliases_invalid")
        aliases, seen = [], set()
        for value in values:
            if (type(value) is not str or not 1 <= len(value) <= 80
                    or any(unicodedata.category(ch).startswith("C") for ch in value)):
                raise ContractError("persona_aliases_invalid")
            alias = " ".join(unicodedata.normalize("NFKC", value).split())
            if (not alias or len(alias) > 80
                    or any(not (ch.isalnum() or unicodedata.category(ch).startswith("M") or ch in " -_.'") for ch in alias)):
                raise ContractError("persona_aliases_invalid")
            key = name_key(alias)
            if not key or key in seen:
                raise ContractError("persona_aliases_ambiguous")
            seen.add(key)
            aliases.append(alias)
        result["aliases"] = aliases
    if "main_assistant" in payload:
        if type(payload["main_assistant"]) is not bool:
            raise ContractError("persona_main_invalid")
        result["main_assistant"] = payload["main_assistant"]
    return result


def identity_tokens(record, profile):
    fields = normalize_fields(profile)
    return (name_key(record.display_name), {name_key(value) for value in fields.get("aliases", [])},
            fields.get("main_assistant", False))


def validate_assignment(record, profile, peers, *, previous=None):
    """Called *inside* the repository's existing serialized write transaction.

    Peers are owned current (record, profile) pairs. Duplicate display names
    remain legal and require an explicit UUID selector; aliases and a main slot
    must be unambiguous. Existing colliding history is never rewritten.
    """
    if record.status not in _LIVE_STATES:
        normalize_fields(profile)
        return
    current = identity_tokens(record, profile)
    if previous is not None and previous[0].status in _LIVE_STATES:
        if identity_tokens(*previous) == current:
            return  # A voice/style edit does not migrate existing identities.
    name, aliases, main = current
    if name and name in aliases:
        raise ContractError("persona_alias_repeats_name")
    for other, other_profile in peers:
        if other.status not in _LIVE_STATES or other.header.entity_id == record.header.entity_id:
            continue
        other_name, other_aliases, other_main = identity_tokens(other, other_profile)
        if main and other_main:
            raise ContractError("persona_main_already_assigned")
        if aliases & (other_aliases | {other_name}) or name and name in other_aliases:
            raise ContractError("persona_alias_already_assigned")


@dataclass(frozen=True)
class Selection:
    persona_id: str
    revision: int
    display_name: str
    message: str
    reason: str


def _identity(value):
    try:
        if type(value) is not str or str(UUID(value)) != value.lower():
            raise ValueError
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ContractError("persona_selection_invalid") from None


def _owned(service, context, persona_id):
    record = service.repository.get(context=context, kind=EntityKind.PERSONA, entity_id=UUID(_identity(persona_id)))
    if record is None or record.header.owner_user_uuid != context.user_uuid:
        raise ContractError("persona_selection_unavailable")
    if record.status != "active":
        raise ContractError("persona_selection_inactive")
    return record


def resolve_chat(service, *, context, message, persona_id=None):
    if (not isinstance(context, c.RequestContext) or context.actor.kind != c.ActorKind.HUMAN
            or type(message) is not str or not message.strip() or len(message) > 6000):
        raise ContractError("persona_selection_invalid")
    chosen = _owned(service, context, persona_id) if persona_id is not None else None
    records = [(row, service._json(context, row.profile)) for row in service._all(context, EntityKind.PERSONA)
               if row.header.owner_user_uuid == context.user_uuid and row.status in _LIVE_STATES]
    body, reason = message, "explicit_id" if chosen else "main"
    address = _ADDRESS.fullmatch(message)
    if address:
        key = name_key(address[2])
        found = [row for row, profile in records if key and key in
                 ({name_key(row.display_name)} | {name_key(alias) for alias in normalize_fields(profile).get("aliases", [])})]
        if len(found) > 1:
            raise ContractError("persona_address_ambiguous")
        if found:
            if chosen and chosen.header.entity_id != found[0].header.entity_id:
                raise ContractError("persona_address_mismatch")
            chosen, body, reason = found[0], address[3], "address"
        elif address[1]:
            raise ContractError("persona_selection_unavailable")
        elif chosen is None and any(key == word or key.startswith(word + " ") for word in _RESERVED):
            # Existing control commands keep their exact route. An ordinary
            # comma in a sentence is not an address and does not disable main.
            return None
    if chosen is None:
        main = [row for row, profile in records if normalize_fields(profile).get("main_assistant", False)]
        if len(main) > 1:
            raise ContractError("persona_main_ambiguous")
        chosen = main[0] if main else None
    if chosen is None:
        return None
    if chosen.status != "active":
        raise ContractError("persona_selection_inactive")
    if not body.strip():
        raise ContractError("persona_message_required")
    return Selection(str(chosen.header.entity_id), chosen.header.revision, chosen.display_name, body.strip(), reason)


def select_model(service, *, context, persona_id, kind=None, selected_model_id=None):
    persona = _owned(service, context, persona_id)
    if kind is not None:
        from .application_roles import for_kind
        role = for_kind(kind)
        if not role or service._json(context, persona.profile).get("application_role") != role:
            raise ContractError("persona_application_role_mismatch")
    candidates = [item for item in service.models(context=context)["items"]
                  if item["status"] == "active" and item.get("persona_id") == str(persona.header.entity_id)]
    if selected_model_id is not None:
        selected_model_id = _identity(selected_model_id)
        # The page offers only executable connections; the server has to hold
        # the same line, or a crafted request names one that cannot run.
        candidates = [item for item in candidates
                      if item["id"] == selected_model_id and item.get("execution_available") is True]
        if not candidates:
            raise ContractError("persona_model_selection_unavailable")
    if len(candidates) != 1:
        raise ContractError("persona_model_ambiguous" if candidates else "persona_model_required")
    # Admission/model constructors recheck again before enqueue. No credential
    # or fallback model is selected here and a paused Persona never routes.
    _owned(service, context, persona_id)
    return candidates[0]["id"]


def try_chat(message, *, scope, conversation_id, request_id, source, persona_id=None, selected_model_id=None):
    from . import application_chat, domain_gateway, live_gateway, model_chat
    if selected_model_id is not None and persona_id is None:
        raise ContractError("persona_model_selection_unavailable")
    if source != "app" or not live_gateway.configured(str((scope or {}).get("workspace_id") or "")):
        if persona_id is not None:
            raise ContractError("persona_chat_unavailable")
        return None
    authorized = domain_gateway.access(scope)
    service = domain_gateway.models(authorized)
    selected = resolve_chat(service, context=authorized["context"], message=message, persona_id=persona_id)
    if selected is None:
        return None
    authorized["admit"]()
    reply = application_chat.try_chat(selected.message, scope=authorized["chat_scope"],
        conversation_id=conversation_id, request_id=request_id, source=source,
        persona_id=selected.persona_id, persona_revision=selected.revision, user_message=message,
        **({"selected_model_id": selected_model_id} if selected_model_id is not None else {}))
    if reply is not None:
        return reply
    reply = model_chat.try_persona(message=selected.message, authorized=authorized, service=service,
        persona_id=selected.persona_id, persona_revision=selected.revision,
        conversation_id=conversation_id, request_id=request_id, user_message=message,
        **({"selected_model_id": selected_model_id} if selected_model_id is not None else {}))
    if reply is None:
        raise ContractError("persona_task_not_supported")
    return reply
