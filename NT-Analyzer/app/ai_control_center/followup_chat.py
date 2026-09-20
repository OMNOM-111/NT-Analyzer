"""Explicit manual follow-up delivery through the existing worker and SF Chat.

An accepted Routine/CalendarItem is a source, not executable authority. Opening
its manual discussion is a separate human action after the acceptance commit.
There is no due-time scheduler, provider dispatch, rating or Telegram delivery.
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
import time
from uuid import uuid5

from .. import worker_router
from ..ai_lab import chief_agent
from . import contracts as c, domain_gateway
from .domain_contracts import CalendarItem, Routine
from .domain_service import DomainService, _hash, _uuid
from .states import ContractError, EntityKind


CONSUMER = "agent_world.manual_followup.sf_chat.v1"
SOURCE = "agent_world_followup"
PHASE = "chat_delivery"
_DOMAINS = {"routines": EntityKind.ROUTINE, "calendar": EntityKind.CALENDAR_ITEM}


def _fresh(authorized, domain, *, write):
    if domain not in _DOMAINS or not isinstance(authorized, dict):
        raise ContractError("followup_domain_denied")
    if write and authorized.get("read_only"):
        raise ContractError("followup_write_required")
    context = authorized.get("context")
    if (not isinstance(context, c.RequestContext) or context.actor.kind != c.ActorKind.HUMAN
            or not callable(authorized.get("admit"))):
        raise ContractError("followup_human_context_required")
    authorized["admit"]()
    current = domain_gateway.access(authorized.get("chat_scope"), read_only=not write)
    if current["context"] != context:
        raise ContractError("followup_context_changed")
    domain_gateway.domain_admission(current, domain, "open_chat" if write else "read")()
    return current


def _same_owner(job, authorized):
    scope = (job.get("payload") or {}).get("scope") or {}
    expected = authorized["chat_scope"]
    return (str(job.get("workspace_id")) == expected["workspace_id"]
            and str(job.get("user_id")) == str(expected["user_id"])
            and str(scope.get("workspace_id")) == expected["workspace_id"]
            and str(scope.get("user_id")) == str(expected["user_id"])
            and str(scope.get("user_uuid")) == expected["user_uuid"])


def _accepted(authorized, service, domain, identity, revision):
    c.require_revision(revision)
    context = authorized["context"]
    record = service._owned(context, _DOMAINS[domain], identity)
    if (not isinstance(record, (Routine, CalendarItem)) or record.status != "accepted"
            or record.header.revision != revision or record.automation_enabled is not False
            or record.handoff is None):
        raise ContractError("followup_accepted_revision_required")
    definition = service._json(context, record.definition)
    handoff = service._json(context, record.handoff)
    request_key = "domain-followup." + _hash([str(context.user_uuid), str(record.header.entity_id), "accept"])
    source_id = "wj_aw_followup_" + hashlib.sha256(request_key.encode()).hexdigest()[:32]
    if (handoff.get("authority") != "existing_jobs" or handoff.get("job_id") != source_id
            or handoff.get("automation_enabled") is not False or handoff.get("manual_review_required") is not True):
        raise ContractError("followup_handoff_required")
    source = worker_router.get(source_id, workspace_id=context.scope.workspace_id) or {}
    expected_request = {**definition, "id": str(record.header.entity_id), "automation_enabled": False,
                        "manual_review_required": True}
    if (source.get("kind") != SOURCE or not _same_owner(source, authorized)
            or (source.get("payload") or {}).get("phase")
            or (source.get("payload") or {}).get("kind") != record.KIND.value
            or (source.get("payload") or {}).get("request") != expected_request
            or source.get("cancel_requested") or source.get("status") not in {"queued", "running", "succeeded"}):
        raise ContractError("followup_handoff_source_invalid")
    return record, definition, source_id


def _manifest(authorized, record, domain, source_id):
    context = authorized["context"]
    identity = str(record.header.entity_id)
    key = _hash([context.scope.environment.value, context.scope.workspace_id, str(context.user_uuid),
                 domain, identity, record.header.revision])
    return {"schema_version": 1, "source": SOURCE, "domain": domain, "entity_id": identity,
            "revision": record.header.revision, "environment": context.scope.environment.value,
            "workspace_id": context.scope.workspace_id, "user_uuid": str(context.user_uuid),
            "user_id": authorized["source_scope"]["user_id"], "definition": c.primitive(record.definition),
            "handoff": c.primitive(record.handoff), "source_worker_job_id": source_id,
            "event_id": str(uuid5(record.header.entity_id, f"revision:{record.header.revision}")),
            "conversation_id": "AW-FU-" + key[:28], "job_id": "wj_aw_followup_chat_" + key[:32],
            "request_id": "aw.followup." + key, "source_url": "/ui/ai-command-center.html#tab=overview&domain="
            + domain + "&entity=" + identity, "automation_enabled": False, "manual_review_required": True,
            "execution_performed": False, "synthetic": False}


def _load_manifest(service, context, payload):
    if (type(payload) is not dict or set(payload) != {"phase", "scope", "domain", "entity_id", "revision", "manifest"}
            or payload.get("phase") != PHASE or payload.get("domain") not in _DOMAINS):
        raise ContractError("followup_delivery_payload_invalid")
    value = payload.get("manifest")
    if type(value) is not dict or set(value) != {"artifact_id", "sha256"}:
        raise ContractError("followup_manifest_required")
    reference = c.SnapshotRef(artifact_id=_uuid(value["artifact_id"]), sha256=value["sha256"], scope=context.scope)
    return service._json(context, reference), reference


def _claim(authorized, job):
    identity = job.get("worker_job_id", job.get("id"))
    current = worker_router.get(identity, workspace_id=authorized["context"].scope.workspace_id) or {}
    try:
        live = all(math.isfinite(float(current.get(key) or 0)) and float(current.get(key) or 0) > time.time()
                   for key in ("locked_until", "deadline_at"))
    except (TypeError, ValueError):
        live = False
    if (job.get("kind") != SOURCE or job.get("status") != "running" or not job.get("worker_id")
            or type(job.get("attempts")) is not int or job["attempts"] < 1
            or current.get("kind") != SOURCE or current.get("status") != "running"
            or current.get("worker_id") != job.get("worker_id") or current.get("attempts") != job.get("attempts")
            or current.get("payload") != job.get("payload") or not _same_owner(current, authorized)
            or not _same_owner(job, authorized) or current.get("cancel_requested") or job.get("cancel_requested") or not live):
        raise ContractError("followup_delivery_claim_required")
    return current


def _dto(manifest, job, *, replayed=False):
    result = job.get("result") or {}
    delivered = job.get("status") == "succeeded" and result.get("status") == "delivered"
    return {"ok": True, "conversation_id": manifest["conversation_id"], "conversation_type": "ai",
            "job_id": manifest["job_id"], "status": "delivered" if delivered else job.get("status", "queued"),
            "source_domain": manifest["domain"], "source_id": manifest["entity_id"],
            "source_revision": manifest["revision"], "source_sha256": manifest["definition"]["sha256"],
            "source_url": manifest["source_url"], "automation_enabled": False, "manual_review_required": True,
            "execution_performed": False, "synthetic": False, "replayed": replayed,
            "message_id": result.get("message_id"), "recorded_at": result.get("recorded_at"),
            "receipt": result.get("receipt")}


def start(authorized, domain_service, domain, identity, expected_revision, idempotency_key):
    """A fresh explicit action after accept, not a callback from that transaction."""
    authorized = _fresh(authorized, domain, write=True)
    context = authorized["context"]
    # A different click key still opens the same accepted-revision discussion;
    # request keys cannot manufacture unlimited duplicate reminder threads.
    domain_service._key(context, idempotency_key)
    record, _, source_id = _accepted(authorized, domain_service, domain, identity, expected_revision)
    manifest = _manifest(authorized, record, domain, source_id)
    reference = domain_service._put(context, authorized["admit"], manifest)
    payload = {"phase": PHASE, "scope": authorized["chat_scope"], "domain": domain,
               "entity_id": str(record.header.entity_id), "revision": expected_revision,
               "manifest": {"artifact_id": str(reference.artifact_id), "sha256": reference.sha256}}
    authorized = _fresh(authorized, domain, write=True)
    _accepted(authorized, domain_service, domain, identity, expected_revision)
    replayed = False
    try:
        job = worker_router.enqueue(SOURCE, payload, user_id=authorized["source_scope"]["user_id"],
            workspace_id=context.scope.workspace_id, job_id=manifest["job_id"], max_attempts=3,
            timeout_sec=30, priority=70)
    except sqlite3.IntegrityError:
        job = worker_router.get(manifest["job_id"], workspace_id=context.scope.workspace_id) or {}
        saved, _ = _load_manifest(domain_service, context, job.get("payload"))
        if (job.get("kind") != SOURCE or not _same_owner(job, authorized) or saved != manifest
                or (job.get("status") != "succeeded" and job.get("payload", {}).get("scope", {}).get("auth_session_id")
                    != authorized["chat_scope"].get("auth_session_id"))):
            raise ContractError("followup_delivery_identity_conflict") from None
        replayed = True
    return _dto(manifest, job, replayed=replayed)


def projection(authorized, domain_service, domain, identity):
    """Read existing delivery only. GET never creates a conversation/job/artifact."""
    authorized = _fresh(authorized, domain, write=False)
    record = domain_service._owned(authorized["context"], _DOMAINS[domain], identity)
    if record.status != "accepted":
        return None
    record, _, source_id = _accepted(authorized, domain_service, domain, identity, record.header.revision)
    manifest = _manifest(authorized, record, domain, source_id)
    job = worker_router.get(manifest["job_id"], workspace_id=authorized["context"].scope.workspace_id)
    if job is None:
        return None
    saved, _ = _load_manifest(domain_service, authorized["context"], job.get("payload"))
    if job.get("kind") != SOURCE or not _same_owner(job, authorized) or saved != manifest:
        raise ContractError("followup_delivery_identity_conflict")
    return _dto(manifest, job, replayed=True)


def _message_text(manifest, definition, queued_at):
    lines = ["Ручной разбор: " + definition["title"], "Принятая запись открыта для ручной проверки.",
             "Запрос на разбор записан: " + str(queued_at) + " (UTC)."]
    if definition.get("description"):
        lines.append(definition["description"])
    if manifest["domain"] == "calendar":
        lines += ["Указанное начало: " + definition["starts_at"] + " (UTC).",
                  "Указанное окончание: " + definition["ends_at"] + " (UTC)."]
    else:
        lines.append("Предложенный интервал: " + str(definition["interval_minutes"]) + " минут.")
    lines += ["Это немедленная запись по вашему действию, не доставка по расписанию.",
              "Автоматизация выключена. Модель, бэктест и внешние действия не запускались.",
              "Откройте источник и выберите следующий шаг самостоятельно.",
              "Источник: " + manifest["source_url"], "Ревизия: " + str(manifest["revision"]),
              "SHA256 определения: " + manifest["definition"]["sha256"]]
    return "\n".join(lines)


def execute(authorized, job, cancelled, heartbeat):
    """Claim-fenced, idempotent delivery; authority is reread before each write."""
    payload = job.get("payload") or {}
    domain = payload.get("domain")
    authorized = _fresh(authorized, domain, write=True)
    if payload.get("scope") != authorized["chat_scope"]:
        raise ContractError("followup_delivery_scope_invalid")
    service = DomainService(domain_gateway.repository(authorized))
    context = authorized["context"]
    manifest, reference = _load_manifest(service, context, payload)

    def check():
        if cancelled():
            raise ContractError("followup_cancelled")
        heartbeat()
        current_auth = _fresh(authorized, domain, write=True)
        current = _claim(current_auth, job)
        record, definition, source_id = _accepted(current_auth, service, domain,
            payload["entity_id"], payload["revision"])
        if (manifest != _manifest(current_auth, record, domain, source_id)
                or current.get("worker_job_id", current.get("id")) != manifest["job_id"]):
            raise ContractError("followup_delivery_identity_conflict")
        return definition, current

    definition, current = check()
    event_id = _uuid(manifest["event_id"])
    # Compare replays against exactly the existing chat storage normalization,
    # including its redaction; never treat a safe redaction as another request.
    text = chief_agent._redact_sensitive(_message_text(manifest, definition, current["queued_at_utc"])).strip()[:12000]
    cid, key = manifest["conversation_id"], manifest["request_id"]
    action = {"name": SOURCE, "status": "needs_input", "source_kind": SOURCE, "synthetic": False,
              "source_domain": domain, "source_id": manifest["entity_id"], "source_revision": manifest["revision"],
              "source_sha256": manifest["definition"]["sha256"], "source_url": manifest["source_url"],
              "automation_enabled": False, "manual_review_required": True, "execution_performed": False}
    with chief_agent._LOCK:
        check()
        # Empty initial title avoids create_conversation's optional Telegram
        # topic synchronization. The title is set below with mirroring OFF.
        path = chief_agent._conversation_file(cid, scope=authorized["chat_scope"])
        rows = chief_agent.read_jsonl(path)
        matched = [row for row in rows if row.get("request_id") == key]
        if len(matched) > 1:
            raise ContractError("followup_chat_receipt_conflict")
        message = matched[0] if matched else None
        replayed = message is not None
        if message is not None:
            if (message.get("role") != "system" or message.get("source") != SOURCE
                    or message.get("content") != text or message.get("actions") != [action]
                    or message.get("workspace_id") != context.scope.workspace_id
                    or message.get("user_uuid") != str(context.user_uuid)):
                raise ContractError("followup_chat_receipt_conflict")
        elif rows or chief_agent._conversation_is_closed(cid, scope=authorized["chat_scope"]):
            raise ContractError("followup_chat_not_empty")
        chief_agent.create_conversation("", conversation_id=cid, scope=authorized["chat_scope"])
        if message is None:
            check()
            message = chief_agent._append_conversation("system", text, source=SOURCE,
                agent_name="Ручной разбор", actions=[action], request_id=key,
                participation_chain=[], path=path, scope=authorized["chat_scope"])
            rows.append(message)
        check()
        chief_agent._touch_conversation(cid, title_hint="Ручной разбор · " + definition["title"],
            message_count=len(rows), scope=authorized["chat_scope"], mirror_to_telegram=False)
        if rows[-1].get("message_id") == message["message_id"] and not chief_agent._conversation_is_closed(cid, scope=authorized["chat_scope"]):
            chief_agent._set_conversation_work_state(cid, "awaiting_owner", "Ручная проверка; автоматизация выключена.",
                scope=authorized["chat_scope"])
    check()
    proof = service._put(context, authorized["admit"], {"schema_version": 1, "source": SOURCE,
        "manifest": c.primitive(reference), "event_id": manifest["event_id"], "conversation_id": cid,
        "message_id": message["message_id"], "message_sha256": _hash(message),
        "recorded_at": message["timestamp_utc"], "source_revision": manifest["revision"],
        "manual_review_required": True, "automation_enabled": False, "execution_performed": False,
        "scheduled_delivery": False, "synthetic": False})
    check()
    acknowledged = service.repository.events.acknowledge(context=context, consumer=CONSUMER, event_id=event_id)
    if not acknowledged and not service.repository.events.is_acknowledged(context=context, consumer=CONSUMER, event_id=event_id):
        raise ContractError("followup_delivery_ack_unconfirmed")
    return {"ok": True, "status": "delivered", "conversation_id": cid, "message_id": message["message_id"],
            "recorded_at": message["timestamp_utc"], "receipt": {"artifact_id": str(proof.artifact_id), "sha256": proof.sha256},
            "source_url": manifest["source_url"], "source_revision": manifest["revision"],
            "manual_review_required": True, "automation_enabled": False, "execution_performed": False,
            "scheduled_delivery": False, "synthetic": False, "replayed": replayed}
