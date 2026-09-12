"""Scoped application use cases over the one Agent World record/event ledger.

The server supplies authenticated context and a fresh admission callback. This
module grants no rights, reads no credentials, starts no scheduler and executes
no jobs or trades. Court calls only an explicitly supplied, admitted model adapter.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5

from . import contracts as c
from .domain_contracts import CalendarItem, CourtCase, CourtVote, JudgeContext, JudgeResult, Routine, StrategyProject
from .events import EventData, EventEnvelope, MutationIdentity
from .repositories import PageRequest
from .states import ContractError, EntityKind


_NAMESPACE = UUID("c6fb5e1e-7a3c-54b4-9496-6b01e00d9da8")
_LOCK = threading.RLock()
_DOMAINS = {"personas": EntityKind.PERSONA, "memory": EntityKind.MEMORY,
            "projects": EntityKind.STRATEGY_PROJECT, "routines": EntityKind.ROUTINE,
            "calendar": EntityKind.CALENDAR_ITEM, "decisions": EntityKind.DECISION,
            "court": EntityKind.COURT_CASE}
_POLICY = {"version": "private-domain-v1", "execution_allowed": False,
           "automation_enabled": False, "memory_retrieval": "active-purpose-owner-ttl",
           "court_policy": "court-review-v1", "court_quorum": "2-of-3-unweighted",
           "judge_execution_allowed": False, "critical_min_failure_domains": 2}
_TRIGGERS = {"requested_review", "high_risk", "conflict", "low_confidence", "budget_exceeded"}
_SECRET_KEYS = {"api_key", "apikey", "password", "secret", "token", "authorization", "cookie", "credentials"}
_SECRET_TEXT = re.compile(r"(?i)(?:\bsk-[A-Za-z0-9_-]{16,}|\b(?:api[_ -]?key|password|authorization|access[_ -]?token)\s*[:=]\s*\S+|\bbearer\s+[A-Za-z0-9._-]{12,})")


def _json_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError("invalid_domain_payload") from exc


def _hash(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _uuid(value):
    try:
        result = value if isinstance(value, UUID) else UUID(str(value))
        c.require_uuid(result)
        return result
    except (TypeError, ValueError):
        raise ContractError("invalid_domain_id") from None


def _text(value, *, limit=4000, empty=False):
    if (not isinstance(value, str) or len(value) > limit or (not empty and not value.strip())
            or any((ord(ch) < 32 and ch not in "\n\t") or 127 <= ord(ch) <= 159 for ch in value)):
        raise ContractError("invalid_domain_text")
    if _SECRET_TEXT.search(value):
        raise ContractError("domain_secret_content_denied")
    return value.strip()


def _safe_json(value, *, depth=0):
    if depth > 8:
        raise ContractError("domain_payload_too_deep")
    if type(value) is dict:
        if len(value) > 64 or any(not isinstance(key, str) or len(key) > 80 for key in value):
            raise ContractError("invalid_domain_payload")
        if any(key.lower() in _SECRET_KEYS for key in value):
            raise ContractError("domain_secret_content_denied")
        return {key: _safe_json(item, depth=depth + 1) for key, item in value.items()}
    if type(value) is list:
        if len(value) > 100:
            raise ContractError("invalid_domain_payload")
        return [_safe_json(item, depth=depth + 1) for item in value]
    if type(value) is str:
        return _text(value, limit=32000, empty=True)
    if value is None or type(value) in (int, float, bool):
        _json_bytes(value)
        return value
    raise ContractError("invalid_domain_payload")


def _fields(payload, required, optional=()):
    if type(payload) is not dict or not set(required) <= set(payload) or set(payload) - set(required) - set(optional):
        raise ContractError("invalid_domain_fields")
    return _safe_json(payload)


def _utc(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        c.require_utc(result)
        return result
    except (TypeError, ValueError, AttributeError):
        raise ContractError("utc_required") from None


class DomainService:
    def __init__(self, repository, *, judge_runner=None, enqueue=None, now=None):
        self.repository = repository
        self.judge_runner = judge_runner
        self.enqueue = enqueue
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _guard(self, context, admit, *, write=False):
        if not isinstance(context, c.RequestContext) or not callable(admit):
            raise ContractError("domain_admission_required")
        if write and context.actor.kind != c.ActorKind.HUMAN:
            raise ContractError("domain_human_decision_required")
        admit()

    def _id(self, context, name):
        return uuid5(_NAMESPACE, f"{context.scope.environment.value}:{context.scope.workspace_id}:{context.user_uuid}:{name}")

    def _key(self, context, key):
        if (not isinstance(key, str) or not 8 <= len(key) <= 160
                or any(ord(char) < 33 or ord(char) > 126 for char in key)):
            raise ContractError("invalid_idempotency_key")
        return "domain." + _hash([str(context.user_uuid), key])

    def _put(self, context, admit, value):
        self._guard(context, admit)
        return self.repository.put_artifact(context=context, content=_json_bytes(value), media_type="application/json")

    def _json(self, context, reference):
        found = self.repository.get_artifact(context=context, reference=reference)
        if not found or found[1] != "application/json":
            raise ContractError("domain_evidence_unavailable")
        try:
            value = json.loads(found[0])
        except (ValueError, UnicodeError):
            raise ContractError("domain_evidence_invalid") from None
        if not isinstance(value, dict):
            raise ContractError("domain_evidence_invalid")
        return value

    def _owned(self, context, kind, identity, *, revision=None):
        args = {"context": context, "kind": kind, "entity_id": _uuid(identity)}
        record = (self.repository.get(**args) if revision is None
                  else self.repository.get_revision(**args, revision=revision))
        if record is None or record.header.owner_user_uuid != context.user_uuid:
            raise ContractError("domain_record_not_found")
        return record

    def _sources(self, context, source_ids):
        if type(source_ids) is not list or len(source_ids) > 32:
            raise ContractError("invalid_domain_sources")
        result = []
        for identity in source_ids:
            found = self.repository.get_artifact_by_id(context=context, artifact_id=_uuid(identity))
            if found is None:
                raise ContractError("domain_evidence_unavailable")
            if found[0] not in result:
                result.append(found[0])
        return tuple(result)

    def _header(self, context, identity, policy, *, correlation_id=None):
        stamp = self.now()
        c.require_utc(stamp)
        return c.RecordHeader(entity_id=identity, scope=context.scope, owner_user_uuid=context.user_uuid,
                              revision=1, created_at=stamp, updated_at=stamp, created_by=context.actor,
                              correlation_id=correlation_id or identity, policy=policy)

    def _change(self, record, **changes):
        stamp = max(self.now(), record.header.updated_at)
        return replace(record, header=replace(record.header, revision=record.header.revision + 1, updated_at=stamp), **changes)

    def _replay(self, context, operation, key, digest):
        found = self.repository.lookup_mutation(context=context, operation=operation, idempotency_key=key)
        if found and found.event.data.reason_code != "rq." + digest:
            raise ContractError("idempotency_conflict")
        return found

    def _save(self, context, admit, record, operation, key, digest, *, references=()):
        self._guard(context, admit)
        semantic = {EntityKind.COURT_VOTE: "recorded", EntityKind.EVALUATION: "recorded"}.get(record.KIND, "changed")
        event = EventEnvelope(event_id=uuid5(record.header.entity_id, f"revision:{record.header.revision}"),
                              event_type=f"stratforge.ai.{record.KIND.value}.{semantic}", time=record.header.updated_at,
                              subject=record.ref(), actor=context.actor, correlation_id=record.header.correlation_id,
                              policy=record.header.policy, causation_id=record.header.causation_id,
                              data=EventData(references=tuple(references), reason_code="rq." + digest))
        mutation = MutationIdentity.for_record(context=context, operation=operation, idempotency_key=key,
                                               record=record, expected_revision=record.header.revision - 1, event=event)
        try:
            return self.repository.commit(context=context, record=record, expected_revision=record.header.revision - 1,
                                          event=event, mutation=mutation)
        except ContractError as exc:
            if exc.code not in {"idempotency_conflict", "revision_conflict", "agent_world_storage_conflict"}:
                raise
            replay = self._replay(context, operation, key, digest)
            if replay is None:
                raise
            return replay

    def _create_input(self, domain, payload):
        if domain == "personas":
            from .application_roles import role_key
            from .presentation import avatar_key
            from .persona_voice import VOICE_FIELDS, normalize_fields
            from .persona_identity import IDENTITY_FIELDS, normalize_fields as normalize_identity
            data = _fields(payload, ("name",), ("description", "style", "application_role", "avatar_key", *VOICE_FIELDS, *IDENTITY_FIELDS))
            return {"name": _text(data["name"], limit=160), "description": _text(data.get("description", ""), empty=True),
                    "style": _text(data.get("style", ""), limit=1000, empty=True),
                    "application_role": role_key(data.get("application_role", "")),
                    "avatar_key": avatar_key(data.get("avatar_key", "")),
                    **normalize_identity(data),
                    **{key: value for key, value in normalize_fields(data).items() if key in data}}
        if domain == "memory":
            data = _fields(payload, ("title", "content", "purpose", "retention_days"),
                           ("source_ids", "memory_class", "task_id", "verified_outcome_id"))
            if type(data["retention_days"]) is not int or not 1 <= data["retention_days"] <= 365:
                raise ContractError("invalid_memory_retention")
            memory_class = data.get("memory_class", "private")
            if memory_class not in {"private", "task", "working", "verified_lesson"}:
                raise ContractError("memory_visibility_promotion_not_enabled")
            if memory_class == "working" and data["retention_days"] != 1:
                raise ContractError("working_memory_ttl_limit")
            if (memory_class == "task") != bool(data.get("task_id")) or (memory_class == "verified_lesson") != bool(data.get("verified_outcome_id")):
                raise ContractError("memory_source_contract_required")
            return {**data, "title": _text(data["title"], limit=160), "content": _text(data["content"], limit=12000),
                    "purpose": _text(data["purpose"], limit=160), "source_ids": data.get("source_ids", []), "memory_class": memory_class}
        if domain == "projects":
            data = _fields(payload, ("title", "description", "strategy_key"))
            c.require_token(data["strategy_key"], limit=120)
            return {**data, "title": _text(data["title"], limit=160), "description": _text(data["description"], empty=True)}
        if domain in {"routines", "calendar"}:
            fields = ("title", "description", "interval_minutes") if domain == "routines" else ("title", "description", "starts_at", "ends_at")
            data = _fields(payload, fields, ("source_ids",))
            data = {**data, "title": _text(data["title"], limit=160), "description": _text(data["description"], empty=True),
                    "source_ids": data.get("source_ids", [])}
            if domain == "routines":
                if type(data["interval_minutes"]) is not int or not 5 <= data["interval_minutes"] <= 525600:
                    raise ContractError("invalid_routine_interval")
            elif _utc(data["ends_at"]) <= _utc(data["starts_at"]):
                raise ContractError("invalid_calendar_interval_or_provenance")
            return data
        if domain == "decisions":
            data = _fields(payload, ("title", "proposal", "evidence_ids", "risk", "trigger"), ("contribution_ids",))
            if data["risk"] not in {item.value for item in c.Risk} or data["trigger"] not in _TRIGGERS:
                raise ContractError("invalid_decision_policy")
            if not data["evidence_ids"]:
                raise ContractError("decision_evidence_required")
            return {**data, "title": _text(data["title"], limit=160), "proposal": _text(data["proposal"], limit=12000),
                    "contribution_ids": data.get("contribution_ids", [])}
        raise ContractError("unknown_domain")

    def create(self, *, context, admit, domain, payload, idempotency_key):
        self._guard(context, admit, write=True)
        data = self._create_input(domain, payload)
        key, operation = self._key(context, idempotency_key), "domain." + domain + ".create"
        digest = _hash({"domain": domain, "action": "create", "payload": data})
        replay = self._replay(context, operation, key, digest)
        if replay:
            return self._result(context, replay.record, replayed=True)
        identity = self._id(context, operation + ":" + key)
        policy = self._put(context, admit, _POLICY)
        header = self._header(context, identity, policy)
        definition = self._put(context, admit, data)
        if domain == "personas":
            record = c.Persona(header=header, status="draft", display_name=data["name"], profile=definition)
        elif domain == "projects":
            record = StrategyProject(header=header, status="draft", title=data["title"], definition=definition)
        elif domain in {"memory", "routines", "calendar"}:
            sources = self._sources(context, data["source_ids"])
            declaration = self._put(context, admit, {"source": "explicit_user_declaration", "user_uuid": str(context.user_uuid),
                                                    "request_sha256": digest, "verified": False})
            provenance = (declaration, *sources)
            if domain == "memory":
                task, verification = self._memory_bindings(context, data)
                record = c.Memory(header=header, status="draft", memory_class=c.MemoryClass(data["memory_class"]),
                                  visibility=c.Visibility.PRIVATE, sensitivity=c.Sensitivity.CONFIDENTIAL,
                                  content=definition, provenance=provenance, task=task, verification=verification,
                                  retention_until=header.created_at + timedelta(days=data["retention_days"]))
            elif domain == "routines":
                record = Routine(header=header, status="proposed", title=data["title"], definition=definition, provenance=provenance)
            else:
                record = CalendarItem(header=header, status="proposed", title=data["title"], definition=definition,
                                      starts_at=_utc(data["starts_at"]), ends_at=_utc(data["ends_at"]), provenance=provenance)
        else:
            evidence = self._sources(context, data["evidence_ids"])
            contributions = self._consensus_sources(context, data["contribution_ids"]) if data["contribution_ids"] else ()
            evidence_content = []
            for ref in evidence:
                found = self.repository.get_artifact(context=context, reference=ref)
                if found[1] != "application/json":
                    raise ContractError("court_structured_evidence_required")
                evidence_content.append({"reference": c.primitive(ref), "content": _safe_json(json.loads(found[0]))})
            acceptance = self._put(context, admit, {"rule": "independent_three_judge_review", "execution_allowed": False,
                                                    "evidence": [c.primitive(ref) for ref in evidence]})
            intent_id = self._id(context, operation + ":intent:" + key)
            prior = self._replay(context, operation + ".intent", key, digest)
            if prior:
                intent = prior.record
            else:
                intent = c.Intent(header=self._header(context, intent_id, policy, correlation_id=identity), status="draft",
                                  goal=definition, acceptance=acceptance, risk=c.Risk(data["risk"]), autonomy=c.Autonomy.ADVICE,
                                  budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET,
                                                       key="workspace:" + context.scope.workspace_id, scope=context.scope),
                                  deadline=header.created_at + timedelta(days=7))
                intent = self._save(context, admit, intent, operation + ".intent", key, digest).record
            packet = self._put(context, admit, {**data, "evidence": evidence_content,
                                               "policy_version": "court-review-v1", "prompt_version": "isolated-judge-v1",
                                               "execution_allowed": False, "requester_uuid": str(context.user_uuid)})
            record = c.Decision(header=header, status="proposed", intent=intent.ref(),
                                contributions=tuple(item.ref() for item in contributions), evidence_packet=packet)
        result = self._save(context, admit, record, operation, key, digest)
        return self._result(context, result.record, replayed=result.replayed)

    def act(self, *, context, admit, domain, entity_id, action, payload, expected_revision, idempotency_key):
        self._guard(context, admit, write=True)
        if domain not in _DOMAINS or domain == "court":
            raise ContractError("unknown_domain")
        c.require_revision(expected_revision)
        identity = _uuid(entity_id)
        clean = _safe_json(payload)
        if type(clean) is not dict:
            raise ContractError("invalid_domain_fields")
        key, operation = self._key(context, idempotency_key), "domain." + domain + "." + action
        c.require_token(operation, limit=100)
        digest = _hash({"domain": domain, "id": str(identity), "action": action,
                        "revision": expected_revision, "payload": clean})
        replay = self._replay(context, operation, key, digest)
        if replay:
            return self._result(context, replay.record, replayed=True)
        record = self._owned(context, _DOMAINS[domain], identity)
        resumed_review = (domain == "decisions" and action == "review"
                          and self._replay(context, operation + ".enter", key, digest) is not None)
        if record.header.revision != expected_revision and not resumed_review:
            raise ContractError("revision_conflict")
        if domain == "memory" and action == "publish_to_workspace":
            return self._publish_memory(context, admit, record, clean, operation, key, digest)
        if domain == "decisions" and action == "review":
            return self._review(context, admit, record, clean, operation, key, digest)
        references = ()
        if action == "update" and domain in {"personas", "projects", "memory"}:
            if domain == "personas":
                # Older clients submit only fields they know. A rename must
                # not silently reset the face, voice, style or explicit role.
                from .persona_voice import VOICE_FIELDS
                from .persona_identity import IDENTITY_FIELDS
                previous = self._json(context, record.profile)
                clean = {**{key: previous[key] for key in ("description", "style", "application_role", "avatar_key", *VOICE_FIELDS, *IDENTITY_FIELDS)
                            if key in previous and key not in clean}, **clean}
            data = self._create_input(domain, clean)
            if domain == "personas" and "application_role" not in clean:
                # Older clients can rename a Persona without unassigning its role.
                data["application_role"] = self._json(context, record.profile).get("application_role", "")
            if domain == "memory" and record.status != "draft":
                raise ContractError("finalized_record_immutable")
            if domain == "memory" and record.retention_until <= self.now():
                raise ContractError("memory_expired")
            definition = self._put(context, admit, data)
            if domain == "personas":
                following = self._change(record, display_name=data["name"], profile=definition)
            elif domain == "projects":
                following = self._change(record, title=data["title"], definition=definition)
            else:
                sources = self._sources(context, data["source_ids"])
                if c.MemoryClass(data["memory_class"]) != record.memory_class:
                    raise ContractError("memory_class_immutable")
                task, verification = self._memory_bindings(context, data)
                following = self._change(record, content=definition, provenance=(record.provenance[0], *sources),
                                         retention_until=record.header.created_at + timedelta(days=data["retention_days"]),
                                         task=task, verification=verification)
        elif domain == "personas" and action in {"activate", "suspend", "archive"}:
            _fields(clean, ())
            following = self._change(record, status={"activate": "active", "suspend": "suspended", "archive": "retired"}[action])
        elif domain == "memory" and action in {"promote", "revoke", "expire"}:
            reason = _text(_fields(clean, ("reason",))["reason"], limit=1000)
            proof = self._put(context, admit, {"method": "explicit_user_review", "reviewed_by": str(context.user_uuid),
                                              "reason": reason, "action": action, "memory_id": str(identity),
                                              "content_sha256": record.content.sha256})
            references = (proof,)
            if action == "promote":
                if record.status != "draft" or record.retention_until <= self.now():
                    raise ContractError("memory_not_promotable")
                following = self._change(record, status="active", verification=record.verification or proof)
            elif action == "expire":
                if record.retention_until > self.now():
                    raise ContractError("memory_not_expired")
                following = self._change(record, status="expired")
            else:
                following = self._change(record, status="revoked")
        elif domain == "projects" and action == "version":
            data = _fields(clean, ("notes", "parameters"))
            if type(data["parameters"]) is not dict:
                raise ContractError("invalid_strategy_parameters")
            notes = _text(data["notes"], empty=True)
            snapshot = self._put(context, admit, {"version": len(record.versions) + 1, "notes": notes,
                                                 "parameters": data["parameters"], "definition": c.primitive(record.definition),
                                                 "created_at": c.primitive(self.now()),
                                                 "created_by": str(context.user_uuid), "request_sha256": digest})
            following = self._change(record, versions=(*record.versions, snapshot))
        elif domain == "projects" and action == "archive":
            _fields(clean, ())
            following = self._change(record, status="archived")
        elif domain in {"routines", "calendar"} and action in {"accept", "dismiss"}:
            _fields(clean, ())
            if action == "accept":
                if record.status != "proposed":
                    raise ContractError("domain_suggestion_not_proposed")
                if not callable(self.enqueue):
                    raise ContractError("domain_followup_adapter_required")
                definition = self._json(context, record.definition)
                self._guard(context, admit)
                reply = self.enqueue(context=context, kind=record.KIND.value,
                                     payload={**definition, "id": str(identity), "automation_enabled": False,
                                              "manual_review_required": True},
                                     idempotency_key="domain-followup." + _hash([str(context.user_uuid), str(identity), "accept"]))
                if (type(reply) is not dict or not isinstance(reply.get("job_id"), str)
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", reply["job_id"])):
                    raise ContractError("invalid_followup_receipt")
                handoff = self._put(context, admit, {"job_id": reply["job_id"], "status": str(reply.get("status") or "queued")[:40],
                                                    "authority": "existing_jobs", "automation_enabled": False,
                                                    "manual_review_required": True})
                following = self._change(record, status="accepted", handoff=handoff)
            else:
                following = self._change(record, status="dismissed")
        elif domain == "decisions" and action == "withdraw":
            _fields(clean, ())
            following = self._change(record, status="withdrawn")
        else:
            raise ContractError("domain_action_not_supported")
        result = self._save(context, admit, following, operation, key, digest, references=references)
        return self._result(context, result.record, replayed=result.replayed)

    def list(self, *, context, admit, domain, limit=50, cursor=None):
        self._guard(context, admit)
        if domain not in _DOMAINS:
            raise ContractError("unknown_domain")
        page = self.repository.list(context=context, kind=_DOMAINS[domain], page=PageRequest(limit=limit, cursor=cursor))
        items = []
        for record in page.items:
            if record.header.owner_user_uuid == context.user_uuid:
                items.append(self._dto(context, record))
            elif domain == "memory":
                shared = self._shared_memory_dto(context, record)
                if shared is not None:
                    items.append(shared)
        self._guard(context, admit)
        return {"enabled": True, "items": items, "next_cursor": page.next_cursor,
                "capabilities": {"can_create": domain != "court", "can_review": callable(self.judge_runner),
                                 "can_accept_suggestion": callable(self.enqueue),
                                 "automation_enabled": False, "execution_allowed": False},
                "limitations": ["Own records plus explicitly active shared memory from this workspace only.",
                                "Routine/calendar acceptance creates an existing-queue manual follow-up; automation remains off.",
                                "Court judges cannot execute decisions; confidence never weights a vote."]}

    def get(self, *, context, admit, domain, entity_id):
        self._guard(context, admit)
        if domain not in _DOMAINS:
            raise ContractError("unknown_domain")
        record = self.repository.get(context=context, kind=_DOMAINS[domain], entity_id=_uuid(entity_id))
        if record is None:
            raise ContractError("domain_record_not_found")
        if record.header.owner_user_uuid == context.user_uuid:
            result = self._dto(context, record, detail=True)
        else:
            result = self._shared_memory_dto(context, record) if domain == "memory" else None
            if result is None:
                raise ContractError("domain_record_not_found")
        self._guard(context, admit)
        return result

    def _result(self, context, record, *, replayed=False):
        return {"ok": True, "item": self._dto(context, record, detail=True), "replayed": replayed,
                "correlation_id": str(record.header.correlation_id)}

    def _dto(self, context, record, *, detail=False):
        data, actions = {}, []
        title, summary, status = record.KIND.value, "", record.status
        if isinstance(record, c.Persona):
            data = self._json(context, record.profile)
            title, summary = record.display_name, data.get("description", "")
            data.setdefault("aliases", [])
            data.setdefault("main_assistant", False)
            data["profile"] = {key: data.get(key, "") for key in ("description", "style")}
            from .persona_voice import presentation
            data["presentation"] = presentation(data)
            data["voice_label"] = data["presentation"]["voice_label"]
            actions = ["update"] if status in {"draft", "active", "suspended"} else []
            actions += {"draft": ["activate", "archive"], "active": ["suspend", "archive"],
                        "suspended": ["activate", "archive"]}.get(status, [])
        elif isinstance(record, c.Memory):
            data = self._json(context, record.content)
            title, summary = data.get("title", "Memory"), data.get("purpose", "")
            expired = record.retention_until <= self.now()
            if expired and status in {"draft", "active"}:
                data["stored_status"], status = status, "expired"
            if status == "active" and not self._memory_source_valid(context, record, data):
                data["stored_status"], status = status, "review"
            if status not in {"active", "draft"}:
                data.pop("content", None)
            data.update(memory_class=record.memory_class.value, visibility=record.visibility.value,
                        sensitivity=record.sensitivity.value, retention_until=c.primitive(record.retention_until),
                        provenance=[c.primitive(ref) for ref in record.provenance],
                        verification=self._json(context, record.verification) if record.verification else None)
            if status in {"draft", "active"}:
                prefix = ("/api/ai-control-center/memory-artifacts/" + str(record.header.entity_id) + "/"
                          if record.memory_class == c.MemoryClass.WORKSPACE else "/api/ai-control-center/artifacts/")
                data["content_artifact_url"] = prefix + str(record.content.artifact_id)
                if record.verification:
                    data["verification_artifact_url"] = prefix + str(record.verification.artifact_id)
            actions = ["update", "promote", "revoke"] if status == "draft" else ["revoke"] if status in {"active", "review"} else []
            if status == "active" and record.memory_class != c.MemoryClass.WORKSPACE:
                actions.append("publish_to_workspace")
        elif isinstance(record, (StrategyProject, Routine, CalendarItem)):
            data = self._json(context, record.definition)
            title, summary = record.title, data.get("description", "")
            if isinstance(record, StrategyProject):
                data["version_count"] = len(record.versions)
                data["versions"] = [self._json(context, ref) for ref in record.versions] if detail else []
                actions = ["update", "version", "archive"] if status != "archived" else []
            else:
                data["automation_enabled"] = False
                data["provenance"] = [c.primitive(ref) for ref in record.provenance]
                data["handoff"] = self._json(context, record.handoff) if record.handoff else None
                actions = ((["accept"] if callable(self.enqueue) else []) + ["dismiss"]) if status == "proposed" else ["dismiss"] if status == "accepted" else []
        elif isinstance(record, c.Decision):
            data = self._json(context, record.evidence_packet)
            court_eligible = data.get("policy_version") == "court-review-v1" and "proposal" in data and "title" in data
            title, summary = data.get("title", "Explicit task authorization"), data.get("proposal", "Bounded user-request authorization; not a Court decision.")
            data["decision_type"] = "advisory_proposal" if court_eligible else "explicit_task_authorization"
            data["court_eligible"] = court_eligible
            data["packet_sha256"] = record.evidence_packet.sha256
            data["execution_allowed"] = False
            data["approval"] = self._json(context, record.approval) if record.approval else None
            actions = (["review"] if callable(self.judge_runner) else []) if court_eligible and status in {"proposed", "review"} else []
            if court_eligible and status == "proposed":
                actions.append("withdraw")
            if detail:
                data["court_cases"] = self._cases(context, record.header.entity_id)
        elif isinstance(record, CourtCase):
            packet = self._json(context, record.packet)
            title, summary = "Court · " + packet["title"], record.reason_code or record.verdict or "independent_review"
            data = {"decision_id": str(record.decision.entity_id), "packet_sha256": record.packet.sha256,
                    "model_ids": [str(ref.entity_id) for ref in record.models], "session_ids": [str(value) for value in record.session_ids],
                    "verdict": record.verdict, "reason_code": record.reason_code, "execution_allowed": False,
                    "policy_version": "court-review-v1", "prompt_version": "isolated-judge-v1", "quorum": "2-of-3",
                    "votes": [self._vote_dto(context, ref) for ref in record.votes]}
        return {**data, "id": str(record.header.entity_id), "title": title, "status": status, "summary": summary,
                "created_at": c.primitive(record.header.created_at), "updated_at": c.primitive(record.header.updated_at),
                "revision": record.header.revision, "actions": actions, "correlation_id": str(record.header.correlation_id)}

    def retrieve_memory(self, *, context, admit, purpose, limit=50, task_id=None):
        """TTL and purpose-filtered retrieval, not access to a raw transcript."""
        self._guard(context, admit)
        purpose = _text(purpose, limit=160)
        task = self._owned(context, EntityKind.TASK, task_id) if task_id is not None else None
        page = self.repository.list(context=context, kind=EntityKind.MEMORY, page=PageRequest(limit=limit))
        result = []
        for record in page.items:
            if record.status != "active" or record.retention_until <= self.now():
                continue
            if record.header.owner_user_uuid != context.user_uuid:
                shared = self._shared_memory_dto(context, record)
                if shared and shared.get("purpose") == purpose:
                    result.append({key: shared[key] for key in ("id", "content", "provenance")})
                continue
            if record.memory_class == c.MemoryClass.TASK and (task is None or record.task.entity_id != task.header.entity_id):
                continue
            data = self._json(context, record.content)
            if data.get("purpose") == purpose and self._memory_source_valid(context, record, data):
                result.append({"id": str(record.header.entity_id), "content": data["content"],
                               "provenance": [c.primitive(ref) for ref in record.provenance]})
        self._guard(context, admit)
        return {"items": result, "next_cursor": page.next_cursor, "purpose": purpose}

    def _publish_memory(self, context, admit, record, payload, operation, key, digest):
        reason = _text(_fields(payload, ("reason",))["reason"], limit=1000)
        data = self._json(context, record.content)
        if (record.status != "active" or record.retention_until <= self.now()
                or record.memory_class == c.MemoryClass.WORKSPACE or not self._memory_source_valid(context, record, data)):
            raise ContractError("memory_not_publishable")
        identity = self._id(context, "memory-publication:" + str(record.header.entity_id) + ":" + str(record.header.revision))
        existing = self.repository.get(context=context, kind=EntityKind.MEMORY, entity_id=identity)
        if existing is not None and not self._replay(context, operation + ".draft", key, digest):
            raise ContractError("memory_publication_already_exists")
        proof = self._put(context, admit, {"type": "workspace_memory_publication", "memory_id": str(identity),
                                          "owner_user_uuid": str(context.user_uuid), "source_memory_id": str(record.header.entity_id),
                                          "source_revision": record.header.revision, "content_sha256": record.content.sha256,
                                          "reason": reason, "visibility": "workspace"})
        if existing is None:
            shared = c.Memory(header=self._header(context, identity, record.header.policy, correlation_id=record.header.correlation_id),
                              status="draft", memory_class=c.MemoryClass.WORKSPACE, visibility=c.Visibility.PRIVATE,
                              sensitivity=record.sensitivity, content=record.content, provenance=(proof,),
                              retention_until=record.retention_until, verification=proof)
            shared = self._save(context, admit, shared, operation + ".draft", key, digest).record
        else:
            shared = existing
        if shared.status != "draft" or shared.verification != proof:
            raise ContractError("memory_publication_already_exists")
        result = self._save(context, admit, self._change(shared, status="active", visibility=c.Visibility.WORKSPACE),
                            operation, key, digest, references=(record.ref(),))
        return self._result(context, result.record, replayed=result.replayed)

    def _shared_memory_dto(self, context, record):
        if not isinstance(record, c.Memory):
            return None
        content = self.repository.read_memory_artifact(context=context, memory_id=record.header.entity_id,
                                                       artifact_id=record.content.artifact_id, now=self.now())
        proof = (self.repository.read_memory_artifact(context=context, memory_id=record.header.entity_id,
                                                      artifact_id=record.verification.artifact_id, now=self.now())
                 if record.verification else None)
        if content is None or proof is None or content[2] != "application/json":
            return None
        data, publication = json.loads(content[1]), json.loads(proof[1])
        # Only explicitly published content and its publication provenance; no
        # private source artifacts, history, task checkpoint or owner context.
        return {"id": str(record.header.entity_id), "title": data["title"], "content": data["content"],
                "summary": data["purpose"], "purpose": data["purpose"], "status": "active", "memory_class": "workspace",
                "visibility": "workspace", "sensitivity": record.sensitivity.value, "provenance": [publication],
                "owner_user_uuid": str(record.header.owner_user_uuid), "retention_until": c.primitive(record.retention_until),
                "created_at": c.primitive(record.header.created_at), "updated_at": c.primitive(record.header.updated_at),
                "revision": record.header.revision, "actions": [], "correlation_id": str(record.header.correlation_id),
                "content_artifact_url": "/api/ai-control-center/memory-artifacts/" + str(record.header.entity_id) + "/" + str(record.content.artifact_id),
                "verification_artifact_url": "/api/ai-control-center/memory-artifacts/" + str(record.header.entity_id) + "/" + str(record.verification.artifact_id)}

    def _memory_bindings(self, context, data):
        task, verification = None, None
        if data["memory_class"] == "task":
            task = self._owned(context, EntityKind.TASK, data["task_id"]).ref()
        elif data["memory_class"] == "verified_lesson":
            outcome = self._owned(context, EntityKind.OUTCOME, data["verified_outcome_id"])
            if outcome.status != "verified" or not outcome.verification or not outcome.evidence:
                raise ContractError("memory_verified_outcome_required")
            verification = outcome.verification
        return task, verification

    def _memory_source_valid(self, context, record, data):
        if record.memory_class == c.MemoryClass.WORKSPACE:
            return self.repository.read_memory_artifact(context=context, memory_id=record.header.entity_id,
                                                        artifact_id=record.content.artifact_id, now=self.now()) is not None
        if record.memory_class != c.MemoryClass.VERIFIED_LESSON:
            return True
        try:
            outcome = self._owned(context, EntityKind.OUTCOME, data["verified_outcome_id"])
            return outcome.status == "verified" and outcome.verification == record.verification
        except (ContractError, KeyError):
            return False

    def suggest_routine(self, *, context, admit, outcome_ids, title, interval_minutes, idempotency_key):
        """Process intelligence consumes verified structured outcomes, not chats."""
        self._guard(context, admit, write=True)
        if type(outcome_ids) is not list or not 2 <= len(outcome_ids) <= 32 or len(set(outcome_ids)) != len(outcome_ids):
            raise ContractError("routine_verified_observations_required")
        sources = []
        for identity in outcome_ids:
            outcome = self._owned(context, EntityKind.OUTCOME, identity)
            if outcome.status != "verified" or not outcome.verification:
                raise ContractError("routine_verified_observations_required")
            sources.append(str(outcome.verification.artifact_id))
        return self.create(context=context, admit=admit, domain="routines", idempotency_key=idempotency_key,
                           payload={"title": title, "description": f"Suggestion from {len(outcome_ids)} verified outcomes; automation is off.",
                                    "interval_minutes": interval_minutes, "source_ids": sources})

    def evidence_candidates(self, *, context, admit, limit=50):
        """Expose only existing owned structured evidence, never a global index."""
        self._guard(context, admit)
        c.require_revision(limit)
        if limit > 100:
            raise ContractError("invalid_page_limit")
        result, seen = [], set()
        for kind in (EntityKind.OUTCOME, EntityKind.CONTRIBUTION):
            page = self.repository.list(context=context, kind=kind, page=PageRequest(limit=100))
            for record in page.items:
                if record.header.owner_user_uuid != context.user_uuid:
                    continue
                if isinstance(record, c.Outcome):
                    if record.status != "verified":
                        continue
                    references = (*record.evidence, *((record.verification,) if record.verification else ()))
                else:
                    if record.status not in {"submitted", "accepted"}:
                        continue
                    references = (record.result, *record.evidence)
                for reference in references:
                    found = self.repository.get_artifact(context=context, reference=reference)
                    if reference.artifact_id in seen or not found or found[1] != "application/json":
                        continue
                    seen.add(reference.artifact_id)
                    result.append({"id": str(reference.artifact_id), "title": f"{kind.value} · {record.header.entity_id}",
                                   "sha256": reference.sha256, "source_kind": kind.value,
                                   "source_id": str(record.header.entity_id), "source_status": record.status})
                    if len(result) == limit:
                        self._guard(context, admit)
                        return {"items": result, "read_limit": limit}
        self._guard(context, admit)
        return {"items": result, "read_limit": limit}

    def consensus_candidates(self, *, context, admit, limit=50):
        """Project contributions, not deduplicated files from the evidence picker."""
        self._guard(context, admit)
        c.require_revision(limit)
        if limit > 100:
            raise ContractError("invalid_page_limit")
        groups = {}
        page = self.repository.list(context=context, kind=EntityKind.CONTRIBUTION, page=PageRequest(limit=100))
        for contribution in page.items:
            if contribution.header.owner_user_uuid != context.user_uuid or contribution.status != "accepted":
                continue
            try:
                task = self._owned(context, EntityKind.TASK, contribution.task.entity_id)
                if task.status != "succeeded" or not task.checkpoint:
                    continue
                checkpoint = self._json(context, task.checkpoint)
                spec = checkpoint.get("spec") or {}
                if (checkpoint.get("source") != "real_model_task" or checkpoint.get("synthetic") is not False
                        or spec.get("rubric_key") == "court_vote"):
                    continue
                model = self._owned(context, EntityKind.MODEL, checkpoint.get("model_id"))
            except ContractError:
                continue
            group = _hash(spec)
            groups.setdefault(group, []).append({"id": str(contribution.header.entity_id),
                "title": f"{checkpoint.get('persona_name', model.model_key)} · {spec.get('rubric_key')} · {model.model_key} · вход {group[:8]}",
                "input_group": group, "model_id": str(model.header.entity_id)})
        result = [row for rows in groups.values() if len({row["model_id"] for row in rows}) >= 2 for row in rows]
        self._guard(context, admit)
        return result[:limit]

    def _consensus_sources(self, context, identities):
        if type(identities) is not list or not 2 <= len(identities) <= 3:
            raise ContractError("consensus_independent_contributions_required")
        contributions, tasks, model_ids, specs = [], set(), set(), set()
        for identity in identities:
            contribution = self._owned(context, EntityKind.CONTRIBUTION, identity)
            task = self._owned(context, EntityKind.TASK, contribution.task.entity_id)
            if contribution.status != "accepted" or task.status != "succeeded" or not task.checkpoint:
                raise ContractError("consensus_verified_contributions_required")
            checkpoint = self._json(context, task.checkpoint)
            if (checkpoint.get("source") != "real_model_task" or checkpoint.get("synthetic") is not False
                    or (checkpoint.get("spec") or {}).get("rubric_key") == "court_vote"):
                raise ContractError("consensus_verified_contributions_required")
            contributions.append(contribution)
            tasks.add(task.header.entity_id)
            model_ids.add(checkpoint.get("model_id"))
            specs.add(_hash(checkpoint.get("spec")))
        if len(tasks) != len(identities) or len(model_ids) < 2 or None in model_ids or len(specs) != 1:
            raise ContractError("consensus_independent_same_task_required")
        return tuple(contributions)

    def propose_consensus(self, *, context, admit, title, proposal, contribution_ids, risk,
                          trigger="requested_review", idempotency_key):
        """Form a proposal from independently completed same-input model paths.

        This is not a vote and does not approve execution. Court, if requested,
        subsequently uses three fresh contexts over this sealed proposal.
        """
        self._guard(context, admit, write=True)
        contributions = self._consensus_sources(context, contribution_ids)
        evidence = list(dict.fromkeys(str(item.result.artifact_id) for item in contributions))
        return self.create(context=context, admit=admit, domain="decisions", idempotency_key=idempotency_key,
                           payload={"title": title, "proposal": proposal, "evidence_ids": evidence,
                                    "risk": risk, "trigger": trigger, "contribution_ids": contribution_ids})

    def _cases(self, context, decision_id):
        page = self.repository.list(context=context, kind=EntityKind.COURT_CASE, page=PageRequest(limit=100))
        return [self._dto(context, record) for record in page.items
                if record.header.owner_user_uuid == context.user_uuid and record.decision.entity_id == decision_id]

    def _vote_dto(self, context, reference):
        vote = self._owned(context, EntityKind.COURT_VOTE, reference.entity_id, revision=reference.revision)
        return {"id": str(vote.header.entity_id), "model_id": str(vote.model.entity_id), "session_id": str(vote.session_id),
                "verdict": vote.verdict, "confidence": vote.confidence, "rationale": self._json(context, vote.rationale)["rationale"],
                "provider_key": vote.provider_key, "model_key": vote.model_key, "model_version": vote.model_version,
                "failure_domain": vote.failure_domain, "contribution_id": str(vote.contribution_id) if vote.contribution_id else None,
                "packet_sha256": vote.packet.sha256, "execution_allowed": False}

    def _review(self, context, admit, decision, payload, operation, key, digest):
        data = _fields(payload, ("model_ids",))
        if type(data["model_ids"]) is not list or len(data["model_ids"]) != 3:
            raise ContractError("three_isolated_judges_required")
        if not callable(self.judge_runner):
            raise ContractError("court_judge_provider_required")
        models = tuple(self._owned(context, EntityKind.MODEL, identity) for identity in data["model_ids"])
        if any(model.status != "active" for model in models):
            raise ContractError("court_model_unavailable")
        if decision.status not in {"proposed", "review"}:
            raise ContractError("decision_not_reviewable")
        intent = self._owned(context, EntityKind.INTENT, decision.intent.entity_id, revision=decision.intent.revision)
        if intent.deadline <= self.now():
            raise ContractError("court_review_expired")
        packet = self._json(context, decision.evidence_packet)
        if packet.get("policy_version") != "court-review-v1" or "proposal" not in packet:
            raise ContractError("court_proposal_required")
        packet_found = self.repository.get_artifact(context=context, reference=decision.evidence_packet)
        packet_json = packet_found[0].decode("utf-8")
        # A process lock avoids duplicate concurrent local submissions. Durable
        # model calls also receive stable run keys; their existing call/job
        # authority must deduplicate any paid retry across processes/restarts.
        with _LOCK:
            replay = self._replay(context, operation, key, digest)
            if replay:
                return self._result(context, replay.record, replayed=True)
            current = self._owned(context, EntityKind.DECISION, decision.header.entity_id)
            if current.evidence_packet != decision.evidence_packet:
                raise ContractError("court_packet_changed")
            if current.status == "proposed":
                entered = self._save(context, admit, self._change(current, status="review"), operation + ".enter", key, digest)
                current = entered.record
            elif not self._replay(context, operation + ".enter", key, digest):
                # Explicit additional review of the SAME sealed proposal is a
                # new independently identified case, not replacement of votes.
                entered = self._save(context, admit, self._change(current), operation + ".enter", key, digest)
                current = entered.record
            case_id = self._id(context, "court:" + str(current.header.entity_id) + ":" + key)
            case = self.repository.get(context=context, kind=EntityKind.COURT_CASE, entity_id=case_id)
            if case is None:
                case = CourtCase(header=self._header(context, case_id, current.header.policy,
                                                     correlation_id=current.header.correlation_id),
                                 status="open", decision=current.ref(), packet=current.evidence_packet,
                                 models=tuple(model.ref() for model in models), risk=c.Risk(packet["risk"]),
                                 session_ids=tuple(uuid5(case_id, f"isolated-session:{index}") for index in range(3)))
                case = self._save(context, admit, case, operation + ".case", key, digest).record
            if case.header.owner_user_uuid != context.user_uuid or case.packet != current.evidence_packet:
                raise ContractError("court_packet_changed")
            if tuple(ref.entity_id for ref in case.models) != tuple(model.header.entity_id for model in models):
                raise ContractError("idempotency_conflict")
            if case.status == "open":
                case = self._save(context, admit, self._change(case, status="voting"), operation + ".voting", key, digest).record
            if case.status == "voting":
                for index, (model_ref, session_id) in enumerate(zip(case.models, case.session_ids)):
                    self._guard(context, admit)
                    live_model = self._owned(context, EntityKind.MODEL, model_ref.entity_id)
                    if live_model.status != "active" or live_model.ref() != model_ref:
                        raise ContractError("court_model_changed")
                    vote_id = uuid5(case_id, "vote:" + str(index))
                    vote = self.repository.get(context=context, kind=EntityKind.COURT_VOTE, entity_id=vote_id)
                    if vote is None:
                        request = JudgeContext(context=context, model_id=model_ref.entity_id, case_id=case_id,
                                               session_id=session_id, packet_json=packet_json,
                                               packet_sha256=case.packet.sha256, run_key="court." + str(session_id))
                        # No peer votes, shared working memory, chat history,
                        # credentials or executable tools enter JudgeContext.
                        try:
                            result = self.judge_runner(request)
                        except ContractError:
                            raise
                        except Exception:
                            raise ContractError("court_judge_unavailable") from None
                        self._guard(context, admit)
                        if not isinstance(result, JudgeResult):
                            raise ContractError("invalid_judge_result")
                        if result.provider_key != live_model.provider_key or result.model_key != live_model.model_key:
                            raise ContractError("judge_model_provenance_mismatch")
                        if self._owned(context, EntityKind.MODEL, model_ref.entity_id).ref() != model_ref:
                            raise ContractError("court_model_changed")
                        contribution = self._judge_contribution(context, request, result)
                        rationale = self._put(context, admit, {"rationale": _text(result.rationale, limit=8000),
                                                               "prompt_version": request.prompt_version,
                                                               "policy_version": request.policy_version,
                                                               "session_id": str(session_id), "packet_sha256": case.packet.sha256})
                        judge_context = c.RequestContext(scope=context.scope, user_uuid=context.user_uuid,
                                                        actor=c.ActorRef(kind=c.ActorKind.AGENT, actor_id=model_ref.entity_id,
                                                                         on_behalf_of=context.user_uuid))
                        vote = CourtVote(header=self._header(judge_context, vote_id, case.header.policy,
                                                             correlation_id=case.header.correlation_id), status="recorded",
                                         case=case.ref(), model=model_ref, session_id=session_id, packet=case.packet,
                                         verdict=result.verdict, confidence=result.confidence, rationale=rationale,
                                         provider_key=result.provider_key, model_key=result.model_key, model_version=result.model_version,
                                         failure_domain=result.failure_domain, contribution_id=result.contribution_id,
                                         contribution=contribution.ref())
                        vote = self._save(judge_context, admit, vote, operation + f".vote{index}", key, digest).record
                    if (vote.header.owner_user_uuid != context.user_uuid or vote.session_id != session_id
                            or vote.packet != case.packet or vote.model != model_ref):
                        raise ContractError("court_vote_binding_mismatch")
                    if vote.ref() not in case.votes:
                        case = self._save(context, admit, self._change(case, votes=(*case.votes, vote.ref())),
                                          operation + f".attach{index}", key, digest).record
                votes = [self._owned(context, EntityKind.COURT_VOTE, ref.entity_id) for ref in case.votes]
                approve = sum(vote.verdict == "approve" for vote in votes)
                reject = sum(vote.verdict == "reject" for vote in votes)
                diverse = len({vote.failure_domain for vote in votes}) >= 2
                verdict = "approve" if approve >= 2 else "reject" if reject >= 2 else "no_quorum"
                reason = "court_diversity_required" if case.risk == c.Risk.CRITICAL and not diverse else "court_no_quorum" if verdict == "no_quorum" else None
                case = self._save(context, admit, self._change(case, status="blocked" if reason else "decided",
                                                              verdict=verdict, reason_code=reason),
                                  operation + ".close", key, digest).record
            current = self._owned(context, EntityKind.DECISION, decision.header.entity_id)
            if current.status != "review" or current.evidence_packet != case.packet:
                raise ContractError("court_decision_changed")
            if case.status == "decided":
                approval = self._put(context, admit, {"type": "court_advisory_verdict", "case_id": str(case_id),
                                                     "packet_sha256": case.packet.sha256, "policy_version": "court-review-v1",
                                                     "verdict": case.verdict, "quorum": "2-of-3-unweighted",
                                                     "votes": [c.primitive(ref) for ref in case.votes],
                                                     "execution_allowed": False, "human_execution_approval_required": True})
                following = self._change(current, status="approved" if case.verdict == "approve" else "rejected", approval=approval)
            else:
                # Failed quorum/diversity remains visible as a reviewed but
                # unapproved proposal. An explicit new request may retry.
                following = self._change(current)
            result = self._save(context, admit, following, operation, key, digest, references=(case.ref(),))
            return self._result(context, result.record, replayed=result.replayed)

    def _judge_contribution(self, context, request, result):
        if result.contribution_id is None:
            raise ContractError("judge_contribution_required")
        contribution = self._owned(context, EntityKind.CONTRIBUTION, result.contribution_id)
        task = self._owned(context, EntityKind.TASK, contribution.task.entity_id)
        if contribution.status != "accepted" or not contribution.evidence or task.status != "succeeded" or not task.checkpoint:
            raise ContractError("judge_contribution_not_verified")
        checkpoint = self._json(context, task.checkpoint)
        spec = checkpoint.get("spec") or {}
        expected = {"rubric_key": "court_vote", "session_id": str(request.session_id), "case_id": str(request.case_id),
                    "packet_sha256": request.packet_sha256, "policy_version": request.policy_version,
                    "prompt_version": request.prompt_version}
        if (checkpoint.get("source") != "real_model_task" or checkpoint.get("synthetic") is not False
                or checkpoint.get("model_id") != str(request.model_id)
                or any(spec.get(key) != value for key, value in expected.items())):
            raise ContractError("judge_contribution_mismatch")
        receipt = self._json(context, contribution.result)
        try:
            response = json.loads(receipt.get("response", ""))
        except (ValueError, TypeError):
            raise ContractError("judge_contribution_mismatch") from None
        if (receipt.get("source") != "provider_response" or receipt.get("synthetic") is not False
                or receipt.get("task_id") != str(task.header.entity_id)
                or receipt.get("request_sha256") != checkpoint.get("request_sha256")
                or response != {"verdict": result.verdict, "confidence": result.confidence, "rationale": result.rationale}):
            raise ContractError("judge_contribution_mismatch")
        return contribution
