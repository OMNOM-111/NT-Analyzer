"""Private user model connections and durable, evidence-backed bounded tasks.

The existing worker owns dispatch/leases and the existing model client owns
transport/budget accounting. This service owns only domain records/checkpoints.
No global provider discovery, chat store, background loop or routing change.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from .. import secure_store
from ..ai_lab import agent_registry
from . import contracts as c
from .events import EventData, EventEnvelope, MutationIdentity
from .model_contracts import Evaluation
from .model_evaluation import (APPLICATION_RUBRIC, APPLICATION_SOURCES, RUBRICS, VERSION,
    application_reputation, digest, evaluate, is_application_observation, json_bytes, prepare, prompts, reputation)
from . import presentation
from .connection_protocol import CHAT_PROTOCOL, describe as describe_protocol, validate as validate_protocol
from .repositories import PageRequest
from .states import ContractError, EDITABLE_STATES, EntityKind, INITIAL_STATES


_NS = UUID("34a15c32-6b28-514e-b14d-bda987c95882")
_LOCK = threading.RLock()
_RUN_LOCKS = tuple(threading.RLock() for _ in range(64))
_POLICY = {"version": "private-model-tasks-v1", "synthetic": False, "risk": "low",
           "autonomy": "advice", "tools": [], "routing_effect": "none",
           "budget_authority": "existing_universal_llm_and_ai_budgets",
           "approval": "explicit_user_bounded_text_request", "court_approval": False}
_SUPPORTED = ("openai", "deepseek", "openrouter", "github_models", "zai", "mistral", "groq", "custom")
_ACTIVE = frozenset({"planned", "ready", "running", "waiting", "blocked"})


def _now():
    return datetime.now(timezone.utc)


def _id(context, key):
    return uuid5(_NS, f"{context.scope.environment.value}:{context.scope.workspace_id}:{context.user_uuid}:{key}")


def _uuid(value):
    try:
        result = value if isinstance(value, UUID) else UUID(str(value))
        c.require_uuid(result)
        return result
    except (ValueError, TypeError, AttributeError):
        raise ContractError("model_id_invalid") from None


def _key(value):
    if (type(value) is not str or not 8 <= len(value) <= 120
            or any(ord(x) < 33 or ord(x) > 126 for x in value)):
        raise ContractError("invalid_idempotency_key")
    return hashlib.sha256(value.encode()).hexdigest()


def _chat_token(value):
    if value is None:
        return None
    value = str(value)
    c.require_token(value, limit=160)
    return value


def _wire(ref):
    return {"artifact_id": str(ref.artifact_id), "sha256": ref.sha256}


def receipt_provenance(receipt):
    """Classify a saved executor receipt, never a prompt or today's flag state.

    Earlier receipts retained the local executor identity but hardcoded
    ``synthetic=False``. Project those honestly without rewriting their bytes.
    The marker can only remove real-model credit, not authorize an execution.
    """
    from .test_executor import EXECUTOR
    synthetic = (receipt.get("executor") == EXECUTOR
                 or receipt.get("actual_model") == EXECUTOR
                 or receipt.get("synthetic") is True)
    return {"source_kind": "synthetic_model_response" if synthetic else "real_model_response",
            "synthetic": synthetic}


class ModelService:
    def __init__(self, repository, *, admit, enqueue=None, executor=None, secrets=None,
                 allowed_origins=(), chat_scope=None, mechanism_admit=None, mechanism_authorized=None):
        self.repository = repository
        self.admit = admit
        self.enqueue = enqueue
        self.executor = executor
        self.secrets = secrets or secure_store
        self.allowed_origins = frozenset(allowed_origins)
        # Optional trusted composition dependency, never an HTTP/task field.
        # Only explicit result handoffs require chat existence before a call.
        self.chat_scope = dict(chat_scope) if isinstance(chat_scope, dict) else None
        self.mechanism_admit = mechanism_admit
        self.mechanism_authorized = mechanism_authorized

    def _access(self, context, operation="read", estimate=0.0):
        if not isinstance(context, c.RequestContext):
            raise ContractError("context_required")
        if context.scope.environment != c.Environment.DEVELOPMENT:
            raise ContractError("model_development_only")
        if not callable(self.admit):
            raise ContractError("model_admission_required")
        # Existing auth/device/membership/entitlement/capability/Preview/flags
        # remain authoritative. This callback cannot originate in a JSON body.
        self.admit(context, operation, estimate)

    def _get(self, context, kind, entity_id):
        record = self.repository.get(context=context, kind=kind, entity_id=_uuid(entity_id))
        if record is None or record.header.owner_user_uuid != context.user_uuid:
            raise ContractError("model_record_not_found")
        return record

    def _all(self, context, kind):
        cursor, seen = None, set()
        while True:
            page = self.repository.list(context=context, kind=kind, page=PageRequest(limit=100, cursor=cursor))
            for record in page.items:
                if record.header.owner_user_uuid == context.user_uuid:
                    yield record
            if not page.next_cursor:
                return
            if page.next_cursor in seen:
                raise ContractError("model_cursor_invalid")
            seen.add(page.next_cursor)
            cursor = page.next_cursor

    def _put(self, context, value):
        return self.repository.put_artifact(context=context, content=json_bytes(value), media_type="application/json")

    def _json(self, context, reference):
        if isinstance(reference, dict):
            reference = c.SnapshotRef(scope=context.scope, artifact_id=_uuid(reference["artifact_id"]),
                                      sha256=reference["sha256"])
        found = self.repository.get_artifact(context=context, reference=reference)
        if found is None or found[1] != "application/json":
            raise ContractError("model_evidence_unavailable")
        try:
            value = json.loads(found[0])
        except (TypeError, ValueError):
            raise ContractError("model_evidence_invalid") from None
        if not isinstance(value, dict):
            raise ContractError("model_evidence_invalid")
        return value

    def _commit(self, context, record, previous=0):
        event_type = "stratforge.ai.evaluation.recorded" if isinstance(record, Evaluation) else f"stratforge.ai.{record.KIND.value}.changed"
        event = EventEnvelope(event_id=uuid5(record.header.entity_id, f"revision:{record.header.revision}"),
            event_type=event_type, time=record.header.updated_at, subject=record.ref(), actor=context.actor,
            correlation_id=record.header.correlation_id, policy=record.header.policy,
            causation_id=record.header.causation_id, data=EventData(reason_code="private_model_task"))
        mutation = MutationIdentity.for_record(context=context, operation="agent_world.model.write",
            idempotency_key=f"model.{record.header.entity_id}.{record.header.revision}", record=record,
            expected_revision=previous, event=event)
        return self.repository.commit(context=context, record=record, expected_revision=previous,
                                      event=event, mutation=mutation).record

    def _ensure(self, context, cls, identity, correlation, policy, **payload):
        found = self.repository.get(context=context, kind=cls.KIND, entity_id=identity)
        if found is not None:
            if type(found) is not cls or found.header.owner_user_uuid != context.user_uuid:
                raise ContractError("model_record_conflict")
            return found
        now = _now()
        if cls is c.Intent:
            payload["deadline"] = now + timedelta(hours=1)
        header = c.RecordHeader(entity_id=identity, scope=context.scope, owner_user_uuid=context.user_uuid,
            revision=1, created_at=now, updated_at=now, created_by=context.actor,
            correlation_id=correlation, policy=policy)
        return self._commit(context, cls(header=header, status=INITIAL_STATES[cls.KIND], **payload))

    def _change(self, context, record, status=None, **changes):
        if (status is None or status == record.status) and all(getattr(record, k) == v for k, v in changes.items()):
            return record
        header = replace(record.header, revision=record.header.revision + 1, updated_at=_now())
        return self._commit(context, replace(record, header=header, status=status or record.status, **changes), record.header.revision)

    def _walk(self, context, record, *states):
        for index, status in enumerate(states):
            if record.status == status:
                continue
            if record.status in states[index + 1:]:
                continue
            record = self._change(context, record, status)
        return record

    def _endpoint(self, provider, value):
        if provider not in _SUPPORTED:
            raise ContractError("model_provider_not_supported")
        default = str(agent_registry.PROVIDERS.get(provider, {}).get("base_url") or "").rstrip("/")
        endpoint = str(value or default).strip().rstrip("/")
        try:
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or parsed.port not in (None, 443)
                    or len(endpoint) > 250 or any(x in endpoint for x in ("\\", "\r", "\n"))):
                raise ValueError()
        except ValueError:
            raise ContractError("model_endpoint_invalid") from None
        if provider != "custom" and endpoint != default:
            raise ContractError("model_endpoint_not_allowed")
        if provider == "custom" and f"https://{parsed.hostname}" not in self.allowed_origins:
            raise ContractError("model_endpoint_not_allowed")
        return endpoint

    def connect(self, *, context, payload, idempotency_key):
        self._access(context, "connect")
        key = _key(idempotency_key)
        if not isinstance(payload, dict):
            raise ContractError("model_connection_invalid")
        allowed = {"label", "provider", "model", "base_url", "api_key", "persona_id", "connection_kind", "protocol"}
        if set(payload) - allowed:
            raise ContractError("model_connection_field_invalid")
        label, model = payload.get("label"), payload.get("model")
        c.require_text(label, limit=80)
        c.require_text(model, limit=120)
        persona = self._get(context, EntityKind.PERSONA, payload.get("persona_id"))
        if persona.status != "active":
            raise ContractError("model_persona_inactive")
        provider = str(payload.get("provider") or "openai")
        kind = payload.get("connection_kind", "model")
        if kind not in {"model", "external_agent"}:
            raise ContractError("model_connection_kind_invalid")
        protocol = validate_protocol({"protocol": payload.get("protocol", CHAT_PROTOCOL)})
        endpoint = self._endpoint(provider, payload.get("base_url"))
        api_key = payload.get("api_key")
        if (type(api_key) is not str or not 8 <= len(api_key) <= 4096
                or any(ord(x) < 33 or ord(x) > 126 for x in api_key)):
            raise ContractError("model_credential_invalid")
        if any(api_key in value for value in (label, model, endpoint)):
            raise ContractError("model_credential_in_metadata")
        model_id, account_id = _id(context, "model:" + key), _id(context, "provider:" + key)
        profile = {"schema_version": 1, "source": "private_model_connection", "label": label,
            "provider": provider, "model": model, "base_url": endpoint, "connection_kind": kind,
            "provider_account_id": str(account_id), "persona_id": str(persona.header.entity_id), "protocol": protocol,
            "credential_source": "user_supplied", "connected": False}
        with _LOCK:
            existing = self.repository.get(context=context, kind=EntityKind.MODEL, entity_id=model_id)
            if existing is not None:
                old = self._json(context, existing.profile)
                if any(old.get(k, CHAT_PROTOCOL if k == "protocol" else None) != v for k, v in profile.items() if k != "connected"):
                    raise ContractError("model_connection_idempotency_conflict")
                if existing.status == "draft":
                    account = self._get(context, EntityKind.PROVIDER_ACCOUNT, account_id)
                    if account.status == "draft":
                        self._change(context, account, "active")
                    self._change(context, existing, "active")
                return self.model_detail(context=context, model_id=model_id)
            if not self.secrets.available():
                raise ContractError("model_secure_storage_unavailable")
            credential_id = "aw_provider." + str(account_id)
            policy = self._put(context, {**_POLICY, "connection_request_sha256": digest(profile)})
            partial = self.repository.get(context=context, kind=EntityKind.PROVIDER_ACCOUNT, entity_id=account_id)
            if partial is not None and (partial.provider_key != provider or partial.header.policy != policy):
                raise ContractError("model_connection_idempotency_conflict")
            prior_key = self.secrets.get_secret(credential_id) if partial is not None else None
            if prior_key is not None and prior_key != api_key:
                raise ContractError("model_connection_idempotency_conflict")
            # No key in SQLite, API DTOs, events, error strings or usage logs.
            # An interrupted create can be retried; an orphan opaque DPAPI key
            # cannot be used without its owner-scoped account and model records.
            if prior_key is None:
                self.secrets.set_secret(credential_id, api_key)
            account = self._ensure(context, c.ProviderAccount, account_id, model_id, policy,
                provider_key=provider, credential=c.ExternalRef(authority=c.ExternalAuthority.CREDENTIAL,
                    key=credential_id, scope=context.scope))
            self._walk(context, account, "active")
            record = self._ensure(context, c.Model, model_id, model_id, policy,
                provider_key=provider, model_key=model, profile=self._put(context, profile), modalities=("text",))
            self._walk(context, record, "active")
        return self.model_detail(context=context, model_id=model_id)

    def _last_connection_test(self, context, model, profile):
        """Project historical origin from the receipt, not today's test switch."""
        last_test = profile.get("last_test")
        if isinstance(last_test, dict) and last_test.get("task_id"):
            tested = self._get(context, EntityKind.TASK, last_test["task_id"])
            checkpoint = self._json(context, tested.checkpoint)
            if (checkpoint.get("model_id") != str(model.header.entity_id)
                    or checkpoint.get("spec", {}).get("rubric_key") != "connection_exact"):
                raise ContractError("model_receipt_mismatch")
            receipt = self._json(context, checkpoint["receipt"]) if checkpoint.get("receipt") else {}
            last_test = {**last_test, **receipt_provenance(receipt),
                         "executor": receipt.get("executor"), "external_call": receipt.get("external_call")}
        return last_test

    def _check_execution_origin(self, context, model, profile, checkpoint):
        validate_protocol(profile)
        selection = checkpoint.get("persona_selection")
        if selection is not None:
            persona = self._get(context, EntityKind.PERSONA, profile["persona_id"])
            if (persona.status != "active" or c.primitive(persona.ref()) != selection
                    or checkpoint.get("persona_id", profile["persona_id"]) != profile["persona_id"]):
                raise ContractError("persona_selection_changed")
        from . import test_executor
        enabled = test_executor.enabled(context.scope.workspace_id)
        if checkpoint.get("test_executor_request") is True and not enabled:
            raise ContractError("model_test_executor_disabled")
        last_test = self._last_connection_test(context, model, profile)
        if (not enabled and last_test and last_test.get("synthetic") is True
                and checkpoint.get("spec", {}).get("rubric_key") != "connection_exact"):
            # A local calculation never verifies the configured provider/key.
            # An explicitly requested new connection check may still use the
            # usual provider admission; ordinary work cannot imply that consent.
            raise ContractError("model_real_connection_verification_required")

    def model_detail(self, *, context, model_id):
        self._access(context)
        model = self._get(context, EntityKind.MODEL, model_id)
        profile = self._json(context, model.profile)
        account = self._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
        protocol = describe_protocol(profile)
        active = model.status == account.status == "active" and protocol["protocol_supported"]
        last_test = self._last_connection_test(context, model, profile)
        test_only = bool(last_test and last_test.get("synthetic") is True)
        connected = bool(profile.get("connected")) and active and not test_only
        verified_test = bool(active and test_only and last_test.get("passed") is True)
        from . import test_executor
        can_execute_test_only = verified_test and test_executor.enabled(context.scope.workspace_id)
        return {"id": str(model.header.entity_id), "title": profile["label"], "label": profile["label"],
            "status": model.status, "model": model.model_key, "provider": model.provider_key,
            "persona_id": profile["persona_id"], "provider_account_id": str(account.header.entity_id),
            "persona_name": self._persona_name(context, profile["persona_id"]),
            "connection_kind": profile["connection_kind"], "connected": connected, **protocol,
            "test_executor_verified": verified_test,
            "can_execute_test_only": can_execute_test_only,
            "execution_available": connected or can_execute_test_only,
            "connection_verification": "test_executor_only" if test_only else "provider_verified" if connected else "not_verified",
            "credential_source": profile.get("credential_source"),
            "credentials_configured": active, "base_url": profile["base_url"], "synthetic": False,
            "last_test": last_test, "actions": ["test", "task", "disconnect"] if active else [],
            "fields": {"model": model.model_key, "provider": model.provider_key,
                       "connection_kind": profile["connection_kind"], "credentials": "configured" if active else "disconnected"}}

    def _persona_name(self, context, persona_id):
        """The connection label is free text the owner typed. The Persona this
        connection currently points at is a separate fact and is reported as
        one, so renaming or rebinding never looks like a permanent identity."""
        try:
            return self._get(context, EntityKind.PERSONA, persona_id).display_name
        except ContractError:
            return ""

    def models(self, *, context):
        self._access(context)
        items = [self.model_detail(context=context, model_id=m.header.entity_id)
                 for m in self._all(context, EntityKind.MODEL)
                 if self._json(context, m.profile).get("source") == "private_model_connection"]
        return {"enabled": True, "items": items, "actions": ["connect"],
            "providers": [{"id": p, "label": agent_registry.PROVIDERS[p]["label"]} for p in _SUPPORTED],
            "rubrics": list(RUBRICS), "limitations": ["Text-only OpenAI-compatible connections; no external tools.",
                "Private own-workspace credentials only; provider availability and budget are checked per call."]}

    def disconnect(self, *, context, model_id):
        self._access(context, "disconnect")
        with _LOCK:
            model = self._get(context, EntityKind.MODEL, model_id)
            profile = self._json(context, model.profile)
            account = self._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
            if account.status != "retired":
                self._change(context, account, "retired")
            if model.status != "retired":
                self._change(context, model, "retired")
            # Authorization was checked before resolving this exact opaque key.
            if profile.get("credential_source") == "user_supplied":
                self.secrets.delete_secret(account.credential.key)
        return self.model_detail(context=context, model_id=model_id)

    def bind_existing_model(self, *, context, payload, idempotency_key, resolve_binding):
        """Root-only callback resolves one approved ID; never list global models."""
        self._access(context, "owner_bind")
        key = _key(idempotency_key)
        if (not isinstance(payload, dict) or set(payload) - {"registry_id", "persona_id", "label"}
                or not callable(resolve_binding)):
            raise ContractError("model_owner_binding_denied")
        binding = resolve_binding(context, payload.get("registry_id"))
        if not isinstance(binding, dict) or binding.get("id") != payload.get("registry_id"):
            raise ContractError("model_owner_binding_denied")
        persona = self._get(context, EntityKind.PERSONA, payload.get("persona_id"))
        if persona.status != "active":
            raise ContractError("model_persona_inactive")
        label = payload.get("label") or binding.get("name")
        c.require_text(label, limit=80)
        provider, model_key = binding.get("provider"), binding.get("model")
        c.require_token(provider, limit=80)
        c.require_text(model_key, limit=120)
        endpoint = str(binding.get("base_url") or "")
        parsed = urlsplit(endpoint)
        # Only this server-resolved native owner binding may retain Azure's
        # API-version selector. Private endpoints and arbitrary query secrets
        # remain rejected; execution still uses the original registry adapter.
        azure_version = (provider == "azure_foundry" and parsed.scheme == "https" and bool(parsed.hostname)
                         and re.fullmatch(r"api-version=\d{4}-\d{2}-\d{2}(?:-preview)?", parsed.query))
        if parsed.username or parsed.password or parsed.fragment or (parsed.query and not azure_version):
            raise ContractError("model_endpoint_invalid")
        model_id, account_id = _id(context, "model:" + key), _id(context, "provider:" + key)
        profile = {"schema_version": 1, "source": "private_model_connection", "label": label,
            "provider": provider, "model": model_key, "base_url": endpoint,
            "connection_kind": "model", "provider_account_id": str(account_id),
            "persona_id": str(persona.header.entity_id), "credential_source": "owner_registry_binding",
            "existing_registry_id": binding["id"], "connected": False}
        with _LOCK:
            existing = self.repository.get(context=context, kind=EntityKind.MODEL, entity_id=model_id)
            if existing is not None:
                old = self._json(context, existing.profile)
                if any(old.get(k) != v for k, v in profile.items() if k != "connected"):
                    raise ContractError("model_connection_idempotency_conflict")
                return self.model_detail(context=context, model_id=model_id)
            policy = self._put(context, _POLICY)
            account = self._ensure(context, c.ProviderAccount, account_id, model_id, policy,
                provider_key=provider, credential=c.ExternalRef(authority=c.ExternalAuthority.CREDENTIAL,
                    key="owner_binding." + str(account_id), scope=context.scope))
            self._walk(context, account, "active")
            model = self._ensure(context, c.Model, model_id, model_id, policy, provider_key=provider,
                model_key=model_key, profile=self._put(context, profile), modalities=("text",))
            self._walk(context, model, "active")
        return self.model_detail(context=context, model_id=model_id)

    def test(self, *, context, model_id, idempotency_key, conversation_id=None, message_id=None, _persona=None):
        return self.start_task(context=context, model_id=model_id,
            payload={"rubric_key": "connection_exact"}, idempotency_key=idempotency_key,
            conversation_id=conversation_id, message_id=message_id, _persona=_persona)

    def start_task(self, *, context, model_id, payload, idempotency_key, conversation_id=None,
                   message_id=None, comparison_id=None, comparison_title=None, _sealed_spec=None, _comparison_spec=None,
                   _handoff=None, _delegation=None, _routing=None, _persona=None):
        self._access(context, "task")
        key = _key(idempotency_key)
        if not isinstance(payload, dict) or set(payload) - {"rubric_key", "input_text"}:
            raise ContractError("model_task_field_invalid")
        spec = _sealed_spec if _sealed_spec is not None else prepare(payload.get("rubric_key", "json_arithmetic"), payload.get("input_text", ""))
        if spec["rubric_key"] == "assistant_response" and any(value is not None for value in
                (_routing, _handoff, _delegation, _sealed_spec, _comparison_spec, comparison_id, comparison_title)):
            raise ContractError("assistant_response_direct_only")
        # Court invokes judge() synchronously with a sealed server-side packet.
        # Enqueuing the same call races the separate worker process; its in-flight
        # safeguard can block the task after the inline caller receives a result.
        inline_judge = _sealed_spec is not None and spec["rubric_key"] == "court_vote"
        # These optional IDs come from trusted chat integration, never payload.
        conversation, message = _chat_token(conversation_id), _chat_token(message_id)
        task_id = _id(context, "model-task:" + key)
        identity = {"model_id": str(_uuid(model_id)), "spec": spec, "conversation_id": conversation,
                    "message_id": message, "comparison_id": comparison_id, "comparison_title": comparison_title}
        if _persona is not None:
            if (not isinstance(_persona, c.EntityRef) or _persona.kind != EntityKind.PERSONA
                    or _persona.scope != context.scope
                    or any(value is not None for value in (_routing, _handoff, _delegation, _comparison_spec))
                    or _sealed_spec is not None and spec["rubric_key"] not in {"backtest_spec", "chart_spec"}):
                raise ContractError("persona_selection_invalid")
            identity["persona_selection"] = c.primitive(_persona)
        correlation, dependencies = task_id, ()
        if _routing is not None:
            if any(value is not None for value in (_handoff, _delegation, _sealed_spec, _comparison_spec)):
                raise ContractError("model_routing_exclusive")
            from .router_v2 import validate_constructor
            identity["routing"] = validate_constructor(self, context, _routing, model_id=model_id,
                spec=spec, conversation_id=conversation, message_id=message, task_id=task_id)
        if _delegation is not None:
            if _handoff is not None or _sealed_spec is not None or _comparison_spec is not None:
                raise ContractError("model_delegation_exclusive")
            from .delegation import validate_constructor
            identity["delegation"] = validate_constructor(self, context, _delegation,
                model_id=model_id, spec=spec, conversation_id=conversation)
            correlation, dependencies = _delegation.correlation_id, _delegation.dependencies
        if _handoff is not None:
            from .result_handoff import validate_constructor
            identity["handoff"] = validate_constructor(self, context, _handoff, model_id=model_id,
                                                       spec=spec, conversation_id=conversation)
            if not message or message == identity["handoff"]["source_message_id"]:
                raise ContractError("handoff_request_mismatch")
            correlation, dependencies = _handoff.correlation_id, (_handoff.parent,)
        if _comparison_spec is not None:
            identity["comparison_spec"] = _comparison_spec
        with _LOCK:
            existing = self.repository.get(context=context, kind=EntityKind.TASK, entity_id=task_id)
            if existing is not None:
                checkpoint = self._json(context, existing.checkpoint)
                if checkpoint.get("request_sha256") != digest(identity):
                    raise ContractError("model_task_idempotency_conflict")
                if checkpoint.get("enqueue_rejected") is True:
                    # This exact request was explicitly refused before queue
                    # creation. Do not turn its replay into a new dispatch or
                    # a false "queued" SF Chat acknowledgment.
                    raise ContractError(checkpoint["error_code"])
                if existing.status in {"planned", "ready"} and not checkpoint.get("receipt"):
                    model = self._get(context, EntityKind.MODEL, model_id)
                    self._check_execution_origin(context, model, self._json(context, model.profile), checkpoint)
                if existing.status == "planned":
                    existing = self._change(context, existing, "ready")
                if existing.status == "ready":
                    self._prepare_execution(context, existing, checkpoint)
                # Queue delivery can be repaired, but provider dispatch is never
                # repeated automatically after an ambiguous in-flight outcome.
                if existing.status == "ready" and not inline_judge and callable(self.enqueue):
                    self.enqueue(context=context, task_id=str(task_id))
                return self.task_detail(context=context, task_id=task_id)
            model = self._get(context, EntityKind.MODEL, model_id)
            profile = self._json(context, model.profile)
            account = self._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
            persona = self._get(context, EntityKind.PERSONA, profile["persona_id"])
            if model.status != "active" or account.status != "active" or persona.status != "active":
                raise ContractError("model_connection_inactive")
            validate_protocol(profile)
            if _persona is not None and persona.ref() != _persona:
                raise ContractError("persona_selection_changed")
            policy = self._put(context, _POLICY)
            speaking_identity = None
            if _routing is not None:
                # Selecting another connection is not selecting another speaker.
                # Only the server-issued source packet may preserve this binding.
                from .router_v2 import speaking_assignment
                persona, role, speaking_identity = speaking_assignment(self, context, _routing)
            else:
                role = self._ensure(context, c.AgentRole, _id(context, "role:model-response"),
                    _id(context, "role:model-response"), policy, role_key="model_response",
                    responsibilities=self._put(context, {"tools": [], "duty": "bounded verified text response"}),
                    capability_ceiling=("ai_pro_models",), autonomy_ceiling=c.Autonomy.ADVICE)
                role = self._walk(context, role, "active")
            from . import test_executor
            goal = {"source": "real_model_task", **identity, "request_sha256": digest(identity),
                    "persona_id": str(persona.header.entity_id),
                    "persona_name": speaking_identity["persona_name"] if speaking_identity else persona.display_name,
                    "provider_account_id": profile["provider_account_id"], "task_id": str(task_id),
                    "correlation_id": str(correlation), "synthetic": False,
                    "test_executor_request": test_executor.enabled(context.scope.workspace_id)}
            if speaking_identity is not None:
                goal.update(speaking_identity=speaking_identity, executor_persona_id=profile["persona_id"])
            if spec["rubric_key"] in {"backtest_spec", "chart_spec"}:
                goal["application_request"] = {"kind": spec["rubric_key"].removesuffix("_spec"),
                    "spec": spec["input"], "request_sha256": digest(spec["input"])}
            partial = self.repository.get(context=context, kind=EntityKind.INTENT, entity_id=_id(context, f"intent:{task_id}"))
            if partial is not None:
                old_goal = self._json(context, partial.goal)
                if old_goal.get("request_sha256") != goal["request_sha256"]:
                    raise ContractError("model_task_idempotency_conflict")
                if old_goal.get("test_executor_request") is True:
                    goal["test_executor_request"] = True
            self._check_execution_origin(context, model, profile, goal)
            intent = self._ensure(context, c.Intent, _id(context, f"intent:{task_id}"), correlation, policy,
                goal=self._put(context, goal), acceptance=self._put(context, {"rubric": spec, "version": VERSION}),
                risk=c.Risk.LOW, autonomy=c.Autonomy.ADVICE,
                budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET,
                    key="ai_budgets.model." + str(task_id), scope=context.scope))
            intent = self._walk(context, intent, "ready")
            task = self._ensure(context, c.Task, task_id, correlation, policy,
                intent=intent.ref(), role=role.ref(), dependencies=dependencies, checkpoint=self._put(context, goal))
            task = self._walk(context, task, "ready")
            self._prepare_execution(context, task, goal)
            if not inline_judge and callable(self.enqueue):
                self.enqueue(context=context, task_id=str(task_id))
        return self.task_detail(context=context, task_id=task_id)

    def _execution(self, context, task_id):
        return self._get(context, EntityKind.EXECUTION, _id(context, f"execution:{task_id}"))

    def _prepare_execution(self, context, task, checkpoint):
        task_id, policy = task.header.entity_id, task.header.policy
        correlation = task.header.correlation_id
        intent = self._get(context, EntityKind.INTENT, task.intent.entity_id)
        origin = "approved_bounded_automation" if checkpoint.get("delegation") else "explicit_bounded_user_request"
        approval = self._put(context, {"source": origin, "user_uuid": str(context.user_uuid),
            "request_sha256": checkpoint["request_sha256"], "task_id": str(task_id), "tools": [], "court": False,
            **({"delegation": checkpoint["delegation"]} if checkpoint.get("delegation") else {})})
        decision = self._ensure(context, c.Decision, _id(context, f"decision:{task_id}"), correlation, policy,
            intent=intent.ref(), contributions=(), evidence_packet=approval)
        if decision.status == "proposed":
            decision = self._change(context, decision, "review")
        if decision.status == "review":
            decision = self._change(context, decision, "approved", approval=approval)
        execution = self._ensure(context, c.Execution, _id(context, f"execution:{task_id}"), correlation, policy,
            decision=decision.ref(), approval=approval,
            command=c.ExternalRef(authority=c.ExternalAuthority.COMMAND,
                key="aw_model." + str(task_id), scope=context.scope))
        if execution.status == "requested":
            self._change(context, execution, "queued")

    def _finish(self, context, task, checkpoint):
        with _LOCK:
            return self._finish_locked(context, task, checkpoint)

    def _finish_locked(self, context, task, checkpoint):
        """Replayable pure domain closeout after the immutable provider receipt."""
        task = self._get(context, EntityKind.TASK, task.header.entity_id)
        if task.status == "cancelled":
            return self.task_detail(context=context, task_id=task.header.entity_id)
        receipt = self._json(context, checkpoint["receipt"])
        if receipt.get("task_id") != str(task.header.entity_id) or receipt.get("request_sha256") != checkpoint["request_sha256"]:
            raise ContractError("model_receipt_mismatch")
        model = self._get(context, EntityKind.MODEL, checkpoint["model_id"])
        execution = self._execution(context, task.header.entity_id)
        receipt_ref = c.SnapshotRef(scope=context.scope, artifact_id=_uuid(checkpoint["receipt"]["artifact_id"]),
                                    sha256=checkpoint["receipt"]["sha256"])
        recovering_judge = (task.status in {"blocked", "ready", "running"}
                            and checkpoint["spec"]["rubric_key"] == "court_vote"
                            and execution.status == "review")
        if recovering_judge:
            # Explicit admitted Court replay may finish a legacy dual-dispatch
            # collision only from the validated immutable receipt above. This
            # cannot re-send a request or recover an ambiguous call without proof.
            self._access(context, "complete")
            task = self._walk(context, task, "ready", "running")
            intent = self._get(context, EntityKind.INTENT, task.intent.entity_id)
            if intent.status in {"blocked", "ready"}:
                self._walk(context, intent, "ready", "running")
            execution = self._change(context, execution, "succeeded", receipt=receipt_ref)
        if execution.status == "running":
            execution = self._change(context, execution, "succeeded", receipt=receipt_ref)
        evaluation = evaluate(checkpoint["spec"], receipt["response"])
        provenance = receipt_provenance(receipt)
        proof = self._put(context, {**evaluation, **provenance, "task_id": str(task.header.entity_id),
            "model_id": str(model.header.entity_id), "receipt": _wire(receipt_ref),
            "actual_model": receipt.get("actual_model"),
            "provider": "local_test_executor" if provenance["synthetic"] else model.provider_key,
            "configured_provider": model.provider_key,
            "executor": receipt.get("executor"), "external_call": receipt.get("external_call"),
            "latency_ms": receipt.get("latency_ms"), "cost_usd": receipt.get("cost_usd")})
        policy, correlation = task.header.policy, task.header.correlation_id
        role = self._get(context, EntityKind.AGENT_ROLE, task.role.entity_id)
        contribution = self._ensure(context, c.Contribution, _id(context, f"contribution:{task.header.entity_id}"),
            correlation, policy, task=task.ref(), role=role.ref(), result=receipt_ref, evidence=(receipt_ref, proof))
        contribution = self._walk(context, contribution, "submitted", "accepted")
        outcome = self._ensure(context, c.Outcome, _id(context, f"outcome:{task.header.entity_id}"), correlation,
            policy, task=task.ref(), evidence=(receipt_ref, proof), execution=execution.ref())
        if outcome.status == "pending":
            outcome = self._change(context, outcome, "verified" if evaluation["passed"] else "disputed", verification=proof)
        self._ensure(context, Evaluation, _id(context, f"evaluation:{task.header.entity_id}"), correlation, policy,
            task=task.ref(), outcome=outcome.ref(), evidence=proof, subject=model.ref(),
            rubric_key=checkpoint["spec"]["rubric_key"])
        # The same outcome is also evidence about the decision that authorised
        # this execution — a different subject, in its own task class. It writes
        # nothing when the execution failed on its own account.
        from .decision_evaluation import record as record_decision
        record_decision(self, context, task=task, checkpoint=checkpoint,
                        execution=execution, outcome=outcome, provenance=provenance)
        waiting_for_application = bool(checkpoint.get("application_request") and evaluation["passed"])
        task = self._change(context, task, "waiting" if waiting_for_application else "succeeded" if evaluation["passed"] else "review")
        intent = self._get(context, EntityKind.INTENT, task.intent.entity_id)
        if intent.status == "running":
            self._change(context, intent, "waiting" if waiting_for_application else "completed" if evaluation["passed"] else "failed")
        if checkpoint["spec"]["rubric_key"] == "connection_exact" and model.status == "active":
            profile = self._json(context, model.profile)
            if (profile.get("last_test") or {}).get("task_id") != str(task.header.entity_id):
                profile.update(connected=evaluation["passed"] and not provenance["synthetic"],
                    last_test={"task_id": str(task.header.entity_id), "passed": evaluation["passed"],
                               "at": _now().isoformat(), **provenance})
                self._change(context, model, profile=self._put(context, profile))
        return self.task_detail(context=context, task_id=task.header.entity_id)

    def execute(self, *, context, task_id, cancelled=None):
        self._access(context, "execute")
        task_id = _uuid(task_id)
        with _RUN_LOCKS[task_id.int % len(_RUN_LOCKS)]:
            task = self._get(context, EntityKind.TASK, task_id)
            checkpoint = self._json(context, task.checkpoint)
            if checkpoint.get("source") != "real_model_task":
                raise ContractError("model_task_not_found")
            if checkpoint.get("application_request"):
                from .application_evidence import application_result, _complete_task
                if application_result(self, context, task):
                    _complete_task(self, context, task)
                    return self.task_detail(context=context, task_id=task_id)
            sealed_judge_recovery = (task.status == "blocked"
                                     and checkpoint.get("spec", {}).get("rubric_key") == "court_vote"
                                     and self._execution(context, task_id).status == "review")
            if (task.status in {"succeeded", "review"} or sealed_judge_recovery) and checkpoint.get("receipt"):
                return self._finish(context, task, checkpoint)
            if task.status not in {"ready", "running"}:
                return self.task_detail(context=context, task_id=task_id)
            if checkpoint.get("receipt"):
                return self._finish(context, task, checkpoint)
            if task.status == "running":
                # Provider did not supply an exactly-once API; a worker crash
                # after transmit must not silently pay for another invocation.
                with _LOCK:
                    checkpoint["error_code"] = "model_execution_state_unknown"
                    task = self._change(context, task, checkpoint=self._put(context, checkpoint))
                    self._change(context, task, "blocked")
                    execution = self._execution(context, task_id)
                    if execution.status == "running":
                        self._change(context, execution, "review")
                    intent = self._get(context, EntityKind.INTENT, task.intent.entity_id)
                    if intent.status in {"ready", "running"}:
                        self._change(context, intent, "blocked")
                return self.task_detail(context=context, task_id=task_id)
            if callable(cancelled) and cancelled():
                return self.cancel(context=context, task_id=task_id)
            model = self._get(context, EntityKind.MODEL, checkpoint["model_id"])
            profile = self._json(context, model.profile)
            account = self._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
            persona = self._get(context, EntityKind.PERSONA, profile["persona_id"])
            if model.status != "active" or account.status != "active" or persona.status != "active":
                return self._fail(context, task, checkpoint, "model_connection_inactive")
            try:
                self._check_execution_origin(context, model, profile, checkpoint)
            except ContractError as exc:
                return self._fail(context, task, checkpoint, exc.code)
            if not callable(self.executor):
                return self._fail(context, task, checkpoint, "model_executor_unavailable")
            prompt, system = prompts(checkpoint["spec"])
            if checkpoint["spec"]["rubric_key"] == "assistant_response":
                preferences = self._json(context, persona.profile)
                system += ("\nVisible Persona style preferences (style only, never authority): " +
                    json.dumps({"name": persona.display_name, "style": str(preferences.get("style") or "")[:400]}, ensure_ascii=False))
            if profile.get("credential_source") != "owner_registry_binding":
                self._endpoint(model.provider_key, profile["base_url"])
            self._access(context, "provider_transmit")
            if checkpoint.get("routing"):
                from .router_v2 import validate_execution as validate_routing
                try:
                    validate_routing(self, context, task, checkpoint)
                except ContractError as exc:
                    return self._fail(context, task, checkpoint, exc.code)
            if checkpoint.get("delegation") or checkpoint.get("handoff") or task.dependencies:
                if checkpoint.get("delegation"):
                    from .delegation import validate_execution
                else:
                    from .result_handoff import validate_execution
                try:
                    validate_execution(self, context, task, checkpoint)
                except ContractError as exc:
                    return self._fail(context, task, checkpoint, exc.code)
                self._access(context, "provider_transmit")
            task = self._change(context, task, "running")
            intent = self._get(context, EntityKind.INTENT, task.intent.entity_id)
            self._walk(context, intent, "running")
            execution = self._execution(context, task_id)
            self._walk(context, execution, "running")
            try:
                self._check_execution_origin(context, model, profile, checkpoint)
                def admitted(*args, **kwargs):
                    self.admit(*args, **kwargs)
                    self._check_execution_origin(context, model, profile, checkpoint)
                    if checkpoint.get("routing"):
                        validate_routing(self, context, task, checkpoint)
                result = self.executor(context=context, model=model, account=account, profile=profile,
                    prompt=prompt, system_prompt=system, request_id=str(task_id),
                    conversation_id=checkpoint.get("conversation_id"), max_output_tokens=512,
                    purpose="connection_test" if checkpoint["spec"]["rubric_key"] == "connection_exact" else "agent_world_capability",
                    cancelled=cancelled, admit=admitted)
                receipt = self._clean_receipt(result, checkpoint)
            except Exception as exc:
                # Do not persist provider error bodies, keys, URLs or tracebacks.
                code = exc.code if isinstance(exc, ContractError) else "model_provider_error"
                return self._fail(context, task, checkpoint, code)
            with _LOCK:
                current = self._get(context, EntityKind.TASK, task_id)
                if current.status == "cancelled" or (callable(cancelled) and cancelled()):
                    if current.status != "cancelled":
                        self.cancel(context=context, task_id=task_id)
                    return self.task_detail(context=context, task_id=task_id)
                checkpoint["receipt"] = _wire(self._put(context, receipt))
                task = self._change(context, current, checkpoint=self._put(context, checkpoint))
            # Accounting/receipt survive loss of access; publishing/scoring
            # waits for a fresh authorized continuation instead of leaking data.
            self._access(context, "complete")
            return self._finish(context, task, checkpoint)

    @staticmethod
    def _clean_receipt(result, checkpoint):
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("application_cache_hit") is True:
            raise ContractError("model_provider_response_invalid")
        response = result.get("response")
        if type(response) is not str or not 1 <= len(response) <= 30000:
            raise ContractError("model_provider_response_invalid")
        latency = result.get("elapsed_sec")
        if type(latency) not in {int, float} or not math.isfinite(latency) or latency < 0:
            raise ContractError("model_provider_latency_invalid")
        cost = result.get("cost_usd") if result.get("cost_known") is True else None
        if cost is not None and (type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0):
            raise ContractError("model_provider_cost_invalid")
        tokens = {}
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            value = result.get(key)
            if type(value) is int and 0 <= value <= 2_000_000_000:
                tokens[key] = value
        actual_model = result.get("actual_model")
        if actual_model is not None:
            c.require_text(actual_model, limit=180)
        provider_request_id = result.get("request_id")
        if provider_request_id is not None:
            c.require_token(provider_request_id, limit=120)
        # Who actually answered, and whether anything left this machine. An
        # executor that computes locally must not be readable as the
        # connection's provider having replied.
        executor = result.get("executor")
        if executor is not None:
            c.require_text(executor, limit=180)
        external_call = result.get("external_call")
        provenance = receipt_provenance({"actual_model": actual_model, "executor": executor})
        if provenance["synthetic"] and (external_call is not False or cost != 0
                                        or result.get("paid_call", False) is not False):
            raise ContractError("model_provider_response_invalid")
        return {"schema_version": 1, "source": "local_test_executor" if provenance["synthetic"] else "provider_response",
            **provenance,
            "task_id": checkpoint["task_id"], "request_sha256": checkpoint["request_sha256"],
            "request_id": checkpoint["task_id"], "response": response, "actual_model": actual_model,
            "provider_request_id": provider_request_id, "executor": executor,
            "external_call": external_call if type(external_call) is bool else None,
            **({"paid_call": False} if provenance["synthetic"] else {}),
            "latency_ms": round(latency * 1000, 3), "cost_usd": cost,
            "cost_estimated": result.get("cost_estimated") is True if cost is not None else None,
            "observed_at": _now().isoformat(), **tokens}

    def _fail(self, context, task, checkpoint, code, *, pre_enqueue=False):
        with _LOCK:
            return self._fail_locked(context, task, checkpoint, code, pre_enqueue=pre_enqueue)

    def _fail_locked(self, context, task, checkpoint, code, *, pre_enqueue=False):
        current = self._get(context, EntityKind.TASK, task.header.entity_id)
        if pre_enqueue:
            # Preserve a concurrent result/cancel/in-flight state. The existing
            # repository CAS also refuses a newer revision at the first write.
            if (current != task or current.status != "ready"
                    or self._json(context, current.checkpoint) != checkpoint
                    or checkpoint.get("receipt") or checkpoint.get("application_dispatch")
                    or self._execution(context, current.header.entity_id).status != "queued"):
                return self.task_detail(context=context, task_id=current.header.entity_id)
            checkpoint = {**checkpoint, "enqueue_rejected": True}
        allowed = {"model_connection_inactive", "model_executor_unavailable", "model_provider_error",
            "persona_selection_changed", "model_protocol_not_supported",
            "model_test_executor_disabled", "model_real_connection_verification_required",
            "routing_disabled", "routing_preview_changed", "routing_source_changed", "routing_request_mismatch",
            "routing_context_required", "routing_packet_invalid", "routing_preview_invalid", "routing_source_invalid",
            "routing_speaking_identity_changed", "routing_speaking_identity_invalid", "routing_speaking_assignment_changed",
            "routing_fresh_identity_preview_required",
            "model_budget_exhausted", "model_key_invalid", "model_endpoint_unavailable", "model_not_found",
            "model_provider_response_invalid", "model_provider_latency_invalid", "model_provider_cost_invalid",
            "model_pricing_unavailable", "model_access_denied", "model_cancelled",
            "model_private_budget_not_configured", "model_owner_binding_denied", "model_owner_binding_changed",
            "model_owner_binding_unavailable", "handoff_source_changed", "handoff_source_unavailable",
            "handoff_request_mismatch", "handoff_target_inactive", "handoff_different_persona_required",
            "handoff_recursive_denied", "handoff_chat_scope_required", "handoff_chat_unavailable",
            "handoff_source_message_required"}
        if pre_enqueue:
            allowed |= {"execution_v2_controller_required", "execution_v2_controller_mismatch",
                "execution_v2_connection_changed", "execution_v2_authority_denied",
                "execution_v2_automation_refresh_required", "execution_v2_gate_disabled",
                "execution_v2_approved_scope_changed", "execution_v2_approved_decision_changed",
                "execution_v2_deadline_expired", "execution_v2_new_approved_task_required",
                "execution_v2_legacy_adoption_denied", "execution_v2_approved_decision_required",
                "execution_v2_approval_invalid", "execution_v2_high_risk_not_supported",
                "agent_world_identity_required", "agent_world_session_expired",
                "agent_world_confirmed_session_required", "agent_world_own_workspace_required",
                "agent_world_capability_required", "agent_world_context_changed",
                "agent_world_disabled", "agent_world_local_disabled", "model_capability_required",
                "model_context_required", "model_history_read_only"}
        checkpoint["error_code"] = (code if code in allowed else
            "model_enqueue_refused" if pre_enqueue else "model_provider_error")
        if current.status == "cancelled":
            return self.task_detail(context=context, task_id=task.header.entity_id)
        current = self._change(context, current, checkpoint=self._put(context, checkpoint))
        execution = self._execution(context, current.header.entity_id)
        if execution.status == "queued":
            self._change(context, execution, "cancelled")
        elif execution.status == "running":
            self._change(context, execution, "failed")
        if current.status == "ready":
            current = self._change(context, current, "blocked")
        else:
            current = self._change(context, current, "failed")
        intent = self._get(context, EntityKind.INTENT, current.intent.entity_id)
        if intent.status == "running":
            self._change(context, intent, "failed")
        elif intent.status == "ready":
            self._change(context, intent, "blocked")
        return self.task_detail(context=context, task_id=current.header.entity_id)

    def cancel(self, *, context, task_id):
        self._access(context, "cancel")
        with _LOCK:
            task = self._get(context, EntityKind.TASK, task_id)
            checkpoint = self._json(context, task.checkpoint)
            if checkpoint.get("source") != "real_model_task":
                raise ContractError("model_task_not_found")
            if task.status not in _ACTIVE:
                return self.task_detail(context=context, task_id=task.header.entity_id)
            if checkpoint.get("application_dispatch") and not checkpoint.get("application_cancelled"):
                raise ContractError("model_application_cancel_requires_source")
            self._change(context, task, "cancelled")
            execution = self._execution(context, task.header.entity_id)
            if execution.status == "running":
                execution = self._change(context, execution, "review")
            if execution.status in {"requested", "queued", "review"}:
                self._change(context, execution, "cancelled")
            intent = self._get(context, EntityKind.INTENT, task.intent.entity_id)
            if intent.status in {"ready", "running", "waiting", "blocked"}:
                self._change(context, intent, "cancelled")
        return self.task_detail(context=context, task_id=task.header.entity_id)

    def intent_view(self, context, task, checkpoint, receipt):
        """What the person was committed to, beside what came back.

        Read-only. Every field already existed on the Intent record; none of it
        is recomputed here, and nothing about the task's state is decided by it.
        """
        intent = self._get(context, EntityKind.INTENT, task.intent.entity_id)
        acceptance = self._json(context, intent.acceptance)
        spec = checkpoint.get("spec") or {}
        rubric = (acceptance.get("rubric") or {}).get("rubric_key") or spec.get("rubric_key")
        # An Intent is editable only while it is a draft, and a task's Intent
        # leaves that state the moment the task exists. Nothing here offers to
        # change it: what was asked for is bound to the request hash, and a
        # different request is a new one. Stopping it is the action that exists.
        amendable = intent.status in EDITABLE_STATES[EntityKind.INTENT]
        actions = ["cancel"] if task.status in _ACTIVE else []
        return {
            "id": str(intent.header.entity_id), "revision": intent.header.revision,
            "status": intent.status,
            "goal": {"text": presentation.rubric_label(rubric),
                     "request": spec.get("input"),
                     "persona_name": checkpoint.get("persona_name"),
                     "conversation_id": checkpoint.get("conversation_id"),
                     "message_id": checkpoint.get("message_id")},
            "constraints": {"risk": intent.risk.value, "deadline": intent.deadline.isoformat(),
                            "budget_key": intent.budget.key,
                            "max_output_tokens": 512},
            "required_evidence": {"rubric_key": rubric,
                                  "rubric_label": presentation.rubric_label(rubric),
                                  "verified_by": "independent_local_evidence_verifier",
                                  "human_review": "separate decision, never a quality claim"},
            "approval_mode": intent.autonomy.value,
            "scope": {"workspace_id": context.scope.workspace_id,
                      "environment": context.scope.environment.value},
            "amendable": amendable, "actions": actions,
            "created_at": intent.header.created_at.isoformat(),
            "updated_at": intent.header.updated_at.isoformat()}

    def task_detail(self, *, context, task_id):
        self._access(context)
        task = self._get(context, EntityKind.TASK, task_id)
        checkpoint = self._json(context, task.checkpoint)
        if checkpoint.get("source") != "real_model_task":
            raise ContractError("model_task_not_found")
        if checkpoint.get("routing"):
            from .router_v2 import validate_assignment
            validate_assignment(self, context, task, checkpoint)
        model = self._get(context, EntityKind.MODEL, checkpoint["model_id"])
        model_profile = self._json(context, model.profile)
        receipt = self._json(context, checkpoint["receipt"]) if checkpoint.get("receipt") else {}
        evaluation = self.repository.get(context=context, kind=EntityKind.EVALUATION,
            entity_id=_id(context, f"evaluation:{task.header.entity_id}"))
        provenance = receipt_provenance(receipt)
        evidence = self._validated_evidence(context, task, checkpoint, receipt, evaluation)
        rubric_key = checkpoint["spec"]["rubric_key"]
        # The owner reads this title; the rubric key stays machine-readable in
        # task_class and in the technical details of the inspector.
        title = f"{checkpoint['persona_name']} · {presentation.rubric_label(rubric_key)}"
        task_dto = {"id": str(task.header.entity_id), "task_id": str(task.header.entity_id),
            "revision": task.header.revision,
            "title": title, "status": task.status, "stage": "provider_receipt" if receipt else "awaiting_provider",
            "summary": checkpoint.get("error_code") or ("Verified bounded response" if task.status == "succeeded" else task.status),
            "task_class": checkpoint["spec"]["rubric_key"], **provenance,
            "lead": {"id": checkpoint["persona_id"], "display_name": checkpoint["persona_name"], "role": "model_response"},
            "model_id": str(model.header.entity_id), "model": model.model_key, "provider": model.provider_key,
            "configured_model": model.model_key, "configured_provider": model.provider_key,
            "response_provider": "local_test_executor" if provenance["synthetic"] else model.provider_key if receipt else None,
            "model_label": model_profile["label"], "persona_id": checkpoint["persona_id"],
            "conversation_id": checkpoint.get("conversation_id"), "message_id": checkpoint.get("message_id"),
            "correlation_id": str(task.header.correlation_id), "intent_id": str(task.intent.entity_id),
            "execution_id": str(_id(context, f"execution:{task.header.entity_id}")),
            "contribution_id": str(_id(context, f"contribution:{task.header.entity_id}")) if receipt and evaluation else None,
            "outcome_id": str(evaluation.outcome.entity_id) if evaluation else None,
            "evaluation_id": str(evaluation.header.entity_id) if evaluation else None,
            "provider_result_received": bool(receipt),
            "result_origin": "local_test_executor" if provenance["synthetic"] else "provider" if receipt else "awaiting_receipt",
            "cost_usd": receipt.get("cost_usd"), "latency_ms": receipt.get("latency_ms"),
            "created_at": task.header.created_at.isoformat(), "updated_at": task.header.updated_at.isoformat(),
            "evidence_count": 2 if evaluation else int(bool(receipt)), "comparison_id": checkpoint.get("comparison_id"),
            "comparison_title": checkpoint.get("comparison_title"), "error_code": checkpoint.get("error_code"),
            "enqueue_rejected": checkpoint.get("enqueue_rejected") is True,
            "error_reason": (presentation.refusal_reason(checkpoint.get("error_code")) or ("", ""))[0]
                            if checkpoint.get("enqueue_rejected") is True else None,
            "actions": ["cancel"] if task.status in _ACTIVE else [],
            "task_class_label": presentation.rubric_label(rubric_key),
            "progress_pct": presentation.progress_pct(task.status)}
        if checkpoint.get("speaking_identity"):
            task_dto.update(speaking_identity=checkpoint["speaking_identity"],
                            executor_persona_id=checkpoint.get("executor_persona_id"))
        if checkpoint.get("application_cancel_request"):
            task_dto["actions"] = []
        task_dto["application_dispatch"] = checkpoint.get("application_dispatch")
        task_dto["application_cancel_request"] = checkpoint.get("application_cancel_request")
        task_dto["application_request"] = checkpoint.get("application_request")
        task_dto["model_plan_verified"] = bool(checkpoint.get("application_request") and evidence and evidence["passed"])
        result_text = receipt.get("response")
        application_evaluation = None
        artifacts = []
        outcomes = []
        if evaluation is not None:
            outcome = self._get(context, EntityKind.OUTCOME, evaluation.outcome.entity_id)
            outcomes.append({"id": str(outcome.header.entity_id), "status": outcome.status,
                "title": "Проверка ответа модели", "detail": result_text,
                **provenance,
                "created_at": outcome.header.created_at.isoformat()})
        if checkpoint.get("application_request") and task_dto["model_plan_verified"] and task.status not in {"failed", "cancelled"}:
            from .application_evidence import application_result
            result = application_result(self, context, task)
            task_dto["application_result"] = result
            task_dto["stage"] = "application_verified" if result else "awaiting_application"
            task_dto["status"] = "succeeded" if result else "waiting"
            task_dto["summary"] = "Application receipt verified" if result else "Model plan verified; actual application result is still pending"
            task_dto["progress_pct"] = presentation.progress_pct(task_dto["status"])
            if not result and checkpoint.get("application_cancel_request"):
                task_dto["stage"] = "application_cancel_requested"
                task_dto["summary"] = "Cancellation requested; awaiting authoritative application confirmation"
            if result:
                application_evaluation = self._application_observation(context, task, checkpoint, result)
                result_text = result.get("result_text") or result_text
                task_dto["source_job_id"] = result["source_id"] if result["source_kind"] == "ninjatrader_report" else None
                task_dto["command_id"] = result["source_id"] if result["source_kind"] == "desktop_chart" else None
                task_dto["report_url"] = result.get("report_url")
                task_dto["application_evaluation_id"] = str(_id(context, f"application-evaluation:{task.header.entity_id}"))
                outcome = self._get(context, EntityKind.OUTCOME, result["outcome_id"])
                outcomes = [{"id": str(outcome.header.entity_id), "status": outcome.status,
                    "title": "Проверенный результат приложения", "detail": result_text,
                    "created_at": outcome.header.created_at.isoformat(), "source_kind": result["source_kind"],
                    "source_job_id": task_dto["source_job_id"], "synthetic": False}]
                for artifact_id in result["artifact_ids"]:
                    found = self.repository.get_artifact_by_id(context=context, artifact_id=_uuid(artifact_id))
                    if found:
                        ref, _, mime = found
                        artifacts.append({"id": str(ref.artifact_id), "title": "Verified application evidence",
                            "url": "/api/ai-control-center/artifacts/" + str(ref.artifact_id),
                            "sha256": ref.sha256, "mime_type": mime, "media_type": mime, "synthetic": False})
        if checkpoint.get("application_error"):
            task_dto["summary"] = checkpoint["application_error"]
            task_dto["error_code"] = checkpoint["application_error"]
            task_dto["stage"] = "application_failed"
        if (task.status == "succeeded" and application_evaluation is not None
                and not checkpoint.get("handoff") and not task.dependencies
                and checkpoint.get("conversation_id") and checkpoint.get("message_id")):
            task_dto["actions"].append("handoff")
        if checkpoint.get("handoff"):
            from .result_handoff import LIMITATION
            packet = checkpoint["handoff"]
            task_dto["handoff"] = {"kind": packet["kind"], "parent_task_id": packet["parent_task"]["entity_id"],
                "parent_revision": packet["parent_task"]["revision"], "source_persona_id": packet["source_persona_id"],
                "source_model_id": packet["source_model_id"], "target_persona_id": packet["target_persona_id"],
                "source_outcome_id": packet["source_outcome_id"], "source_message_id": packet["source_message_id"],
                "facts": packet["facts"], "facts_sha256": packet["facts_sha256"], "source_kind": packet["source_kind"],
                "synthetic": False, "limitation": LIMITATION, "recursive_delegation": False}
            task_dto["dependencies"] = [c.primitive(ref) for ref in task.dependencies]
            task_dto["title"] = checkpoint["persona_name"] + " · передача проверенных фактов"
            task_dto["summary"] = ("Точность передачи фактов проверена. " if task.status == "succeeded"
                                    else "Передача фактов: " + task.status + ". ") + LIMITATION
            if result_text:
                result_text = LIMITATION + "\n\n" + result_text
        from . import task_review, task_presentation
        from . import execution_v2
        task_dto["execution_v2"] = execution_v2.projection(self, context, task.header.entity_id) if execution_v2.is_managed(self, context, task.header.entity_id) else None
        review = task_review.projection(self, context, task, checkpoint, task_dto)
        if review["status"] == "pending":
            task_dto["actions"].append("review_result")
        # task_presentation is the single lifecycle computation. Everything
        # below is derived from its display_status, never from the raw status a
        # second time, so the page and the counters cannot diverge again.
        task_dto = task_presentation.project(task_dto, evaluation=evidence, human_review=review)
        task_dto["stage_label"] = presentation.stage_label(task_dto["stage"])
        task_dto["progress_pct"] = presentation.progress_pct(task_dto["display_status"])
        return {"task": task_dto, **task_dto, "result_text": result_text,
            "actual_model": receipt.get("actual_model"), "evaluation": evidence,
            "intent": self.intent_view(context, task, checkpoint, receipt),
            "reputation": self.task_reputation(context, task, checkpoint),
            "executor": receipt.get("executor"), "external_call": receipt.get("external_call"),
            "application_evaluation": application_evaluation,
            "evaluations": ([evidence] if evidence else []) + ([application_evaluation] if application_evaluation else []),
            "artifacts": artifacts,
            "fields": {"model": model.model_key, "provider": model.provider_key, "intent_id": str(task.intent.entity_id),
                       "latency_ms": receipt.get("latency_ms"), "cost_usd": receipt.get("cost_usd")},
            "activity": [], "contributions": [], "decisions": [], "outcomes": outcomes,
            "limitations": ["Bounded text capability evidence; no real trading or calibrated routing influence."]}

    def _validated_evidence(self, context, task, checkpoint, receipt, evaluation):
        """Receipt identity and deterministic checks stay authoritative on GET.

        Synthetic is provenance, not a correctness check. Old false markers are
        projected from the immutable executor identity; artifacts stay intact.
        """
        if receipt and (receipt.get("task_id") != str(task.header.entity_id)
                        or receipt.get("request_sha256") != checkpoint["request_sha256"]):
            raise ContractError("model_receipt_mismatch")
        if evaluation is None:
            return None
        evidence = self._json(context, evaluation.evidence)
        if (str(evaluation.model.entity_id) != checkpoint["model_id"]
                or evaluation.task.entity_id != task.header.entity_id
                or evidence.get("task_id") != str(task.header.entity_id)
                or evidence.get("model_id") != checkpoint["model_id"]
                or evidence.get("receipt") != checkpoint.get("receipt")
                or any(evidence.get(k) != v for k, v in evaluate(checkpoint["spec"], receipt.get("response", "")).items()
                       if k != "synthetic")):
            raise ContractError("model_evaluation_mismatch")
        provenance = receipt_provenance(receipt)
        return {**evidence, **provenance,
                "configured_provider": evidence.get("configured_provider", evidence.get("provider")),
                "provider": "local_test_executor" if provenance["synthetic"] else evidence.get("provider"),
                "executor": receipt.get("executor"), "external_call": receipt.get("external_call")}

    def tasks(self, *, context):
        self._access(context)
        rows = []
        for task in self._all(context, EntityKind.TASK):
            if task.checkpoint and self._json(context, task.checkpoint).get("source") == "real_model_task":
                rows.append(self.task_detail(context=context, task_id=task.header.entity_id))
        rows.sort(key=lambda x: (x["created_at"], x["id"]), reverse=True)
        return {"enabled": True, "items": rows[:100], "total": len(rows), "actions": [],
                "truncated": len(rows) > 100, "limitations": []}

    def task_reputation(self, context, task, checkpoint):
        """Both scopes this task contributed to, named rather than merged.

        The model that answered and the role it answered under are different
        subjects with different histories. Returning them side by side, each
        carrying its own scope name, is what stops one being read as the other.
        """
        from . import reputation as scopes
        task_class = (checkpoint.get("spec") or {}).get("rubric_key")
        if not task_class:
            return {}
        now = _now()
        views = {}
        for kind, identity in ((EntityKind.MODEL, checkpoint.get("model_id")),
                               (EntityKind.AGENT_ROLE, task.role.entity_id)):
            if not identity:
                continue
            view = scopes.measure(self, context, subject_kind=kind, subject_id=_uuid(identity),
                                  task_class=task_class, now=now)
            views[view["scope"]] = view
        # The decision that authorised the work is a third subject, and it is
        # measured in its own class: being asked a good question and making a
        # good call are not the same thing, and this is what keeps the two
        # numbers from ever being computed from the same rows.
        from .decision_evaluation import RUBRIC as DECISION_RUBRIC
        decision = scopes.measure(self, context, subject_kind=EntityKind.DECISION,
                                  subject_id=_id(context, f"decision:{task.header.entity_id}"),
                                  task_class=DECISION_RUBRIC, now=now)
        views[decision["scope"]] = decision
        return views

    def reputation(self, *, context, subject_kind, subject_id, task_class, window_days=None):
        """One scope's measurement. Scopes are never summed or blended.

        Exposed per subject kind on purpose: asking for "the score" of something
        without saying which scope is the question this split exists to stop.
        """
        from . import reputation as scopes
        self._access(context)
        window = scopes.Window(int(window_days)) if window_days else scopes.Window()
        return scopes.measure(self, context, subject_kind=subject_kind, subject_id=subject_id,
                              task_class=task_class, now=_now(), window=window)

    def evaluations(self, *, context, model_id, rubric_key="json_arithmetic"):
        self._access(context)
        model = self._get(context, EntityKind.MODEL, model_id)
        if rubric_key == APPLICATION_RUBRIC:
            # Read through task_detail so an orphan Evaluation, modified model
            # response or unavailable application artifact cannot earn credit.
            observations = []
            for row in self._all(context, EntityKind.EVALUATION):
                if (row.subject.kind is EntityKind.MODEL
                        and row.subject.entity_id == model.header.entity_id
                        and row.rubric_key == APPLICATION_RUBRIC):
                    detail = self.task_detail(context=context, task_id=row.task.entity_id)
                    proof = detail.get("application_evaluation")
                    if proof is not None:
                        if detail.get("model_id") != str(model.header.entity_id):
                            raise ContractError("model_application_evaluation_mismatch")
                        observations.append(proof)
            return application_reputation(observations)
        observations = []
        for row in self._all(context, EntityKind.EVALUATION):
            # Model performance counts model-subject evaluations only. A role
            # or decision evaluation is a different scope, not a missing one.
            if (row.subject.kind is not EntityKind.MODEL
                    or row.subject.entity_id != model.header.entity_id
                    or row.rubric_key != rubric_key):
                continue
            task = self._get(context, EntityKind.TASK, row.task.entity_id)
            checkpoint = self._json(context, task.checkpoint)
            receipt = self._json(context, checkpoint["receipt"]) if checkpoint.get("receipt") else {}
            observations.append(self._validated_evidence(context, task, checkpoint, receipt, row))
        synthetic = [row for row in observations if row["synthetic"] is True]
        unique = {row["input_sha256"]: row for row in synthetic}
        # A local executor exercises the pipeline, not the configured model.
        # Even three passing inputs must never become a 100% model rating.
        return {**reputation(observations, rubric_key=rubric_key),
            "real_response_count": len(observations) - len(synthetic),
            "synthetic_observations": {"rubric_key": rubric_key, "synthetic": True,
                "source_kind": "synthetic_model_response", "mode": "synthetic_infrastructure",
                "sample_size": len(unique), "task_count": len(synthetic),
                "passed": sum(row["passed"] is True for row in unique.values()),
                "failed": sum(row["passed"] is not True for row in unique.values()),
                "score_pct": None, "routing_effect": "none", "general_model_quality_claim": False,
                "executors": sorted({row["executor"] for row in synthetic if row.get("executor")}),
                "limitation": "Local test executor only; no configured provider or professional model quality verified."}}

    def _application_observation(self, context, task, checkpoint, result):
        """Validate the existing receipt lineage before displaying/rating it.

        No new Evaluation or score is persisted on GET. The source adapter and
        application_result remain the owners of execution/byte verification.
        """
        proof = result.get("evaluation")
        evaluation = self._get(context, EntityKind.EVALUATION,
            _id(context, f"application-evaluation:{task.header.entity_id}"))
        outcome = self._get(context, EntityKind.OUTCOME, result["outcome_id"])
        request = checkpoint["application_request"]
        if (not is_application_observation(proof)
                or evaluation.rubric_key != APPLICATION_RUBRIC
                or str(evaluation.model.entity_id) != checkpoint["model_id"]
                or outcome.task.entity_id != task.header.entity_id
                or proof["task_id"] != str(task.header.entity_id)
                or proof["model_id"] != checkpoint["model_id"]
                or proof["input_sha256"] != digest(request)
                or proof["verification"]["request_sha256"] != request["request_sha256"]
                or APPLICATION_SOURCES[proof["source_kind"]] != request["kind"]):
            raise ContractError("model_application_evaluation_mismatch")
        refs = {str(ref.artifact_id): ref for ref in outcome.evidence}
        if (any(artifact_id not in refs for artifact_id in proof["artifact_ids"])
                or proof["verification"]["sha256"] not in {refs[artifact_id].sha256 for artifact_id in proof["artifact_ids"]}):
            raise ContractError("model_application_evaluation_mismatch")
        return {**proof, "application_kind": request["kind"],
            "evaluation_id": str(evaluation.header.entity_id), "outcome_id": str(outcome.header.entity_id),
            "denominator": "distinct_verified_application_requests", "market_performance_claim": False,
            "general_model_quality_claim": False}

    def start_comparison(self, *, context, payload, idempotency_key, conversation_id=None, message_id=None):
        self._access(context, "comparison")
        key = _key(idempotency_key)
        if not isinstance(payload, dict) or set(payload) - {"title", "model_ids", "rubric_key", "input_text"}:
            raise ContractError("model_comparison_invalid")
        title, model_ids = payload.get("title"), payload.get("model_ids")
        c.require_text(title, limit=80)
        if type(model_ids) is not list or not 2 <= len(model_ids) <= 3:
            raise ContractError("model_comparison_models_invalid")
        ids = [_uuid(x) for x in model_ids]
        if len(set(ids)) != len(ids):
            raise ContractError("model_comparison_models_invalid")
        task_payload = {"rubric_key": payload.get("rubric_key", "json_arithmetic"), "input_text": payload.get("input_text", "")}
        prepared = prepare(**task_payload)
        for model_id in ids:
            model = self._get(context, EntityKind.MODEL, model_id)
            if model.status != "active":
                raise ContractError("model_connection_inactive")
        comparison_id = str(_id(context, "comparison:" + key))
        manifest = {"model_ids": sorted(str(item) for item in ids), "title": title, "spec": prepared,
                    "conversation_id": _chat_token(conversation_id), "message_id": _chat_token(message_id)}
        with _LOCK:
            # The first existing typed Task seals the comparison input/model
            # set. Retry cannot silently append another model to the same run.
            for task in self._all(context, EntityKind.TASK):
                if not task.checkpoint:
                    continue
                checkpoint = self._json(context, task.checkpoint)
                if checkpoint.get("comparison_id") == comparison_id and checkpoint.get("comparison_spec") != manifest:
                    raise ContractError("model_comparison_idempotency_conflict")
            results = [self.start_task(context=context, model_id=model_id, payload=task_payload,
                idempotency_key="comparison." + key + "." + str(model_id), conversation_id=conversation_id,
                message_id=message_id, comparison_id=comparison_id, comparison_title=title, _comparison_spec=manifest)
                for model_id in ids]
        return self._comparison_dto(comparison_id, results)

    @staticmethod
    def _comparison_dto(identity, results):
        kinds = {row["source_kind"] for row in results if row.get("provider_result_received")}
        has_synthetic = "synthetic_model_response" in kinds
        return {"id": identity, "title": results[0].get("comparison_title"),
            "status": "running" if any(row["status"] in _ACTIVE for row in results) else "completed",
            "summary": ("Local test executor results are separate from real-model evidence; no pooled quality score."
                        if has_synthetic else "Actual model responses with independent per-input evidence; no routing change."),
            "synthetic": has_synthetic and len(kinds) == 1, "mixed_provenance": len(kinds) > 1,
            "source_kinds": sorted(kinds), "results": results, "actions": [],
            "fields": {"models": len(results), "completed": sum(row["status"] == "succeeded" for row in results),
                       "failed": sum(row["status"] in {"failed", "blocked", "review", "cancelled"} for row in results)}}

    def experiments(self, *, context):
        grouped = {}
        for row in self.tasks(context=context)["items"]:
            identity = row.get("comparison_id")
            if identity:
                grouped.setdefault(identity, []).append(row)
        items = []
        for identity, results in grouped.items():
            items.append(self._comparison_dto(identity, results))
        return {"enabled": True, "items": items, "actions": ["create"], "limitations": []}

    def judge(self, request):
        """Trusted DomainService callback. Three calls have no shared prompt state."""
        from .domain_contracts import JudgeContext, JudgeResult
        if not isinstance(request, JudgeContext):
            raise ContractError("model_judge_context_required")
        self._access(request.context, "judge")
        if hashlib.sha256(request.packet_json.encode("utf-8")).hexdigest() != request.packet_sha256:
            raise ContractError("model_judge_packet_mismatch")
        try:
            packet = json.loads(request.packet_json)
        except (ValueError, TypeError):
            raise ContractError("model_judge_packet_invalid") from None
        spec = {"rubric_key": "court_vote", "version": VERSION, "input": packet,
                "session_id": str(request.session_id), "case_id": str(request.case_id),
                "packet_sha256": request.packet_sha256, "policy_version": request.policy_version,
                "prompt_version": request.prompt_version}
        key = "judge." + _key(request.run_key)
        previous = self.repository.get(context=request.context, kind=EntityKind.TASK,
            entity_id=_id(request.context, "model-task:" + _key(key)))
        # A new format instruction is sealed into new requests only. Replaying
        # an old receipt must retain its original identity and failed evidence.
        format_version = (self._json(request.context, previous.checkpoint).get("spec", {}).get("response_format_version")
                          if previous is not None else "plain-json-v1")
        if format_version is not None:
            if format_version != "plain-json-v1":
                raise ContractError("model_judge_format_unsupported")
            spec["response_format_version"] = format_version
        if len(json_bytes(spec)) > 12000:
            raise ContractError("model_judge_packet_too_large")
        task = self.start_task(context=request.context, model_id=request.model_id, payload={},
            idempotency_key=key, _sealed_spec=spec)
        result = self.execute(context=request.context, task_id=task["id"])
        if result["status"] != "succeeded":
            raise ContractError(result.get("error_code") or "model_judge_response_invalid")
        vote = json.loads(result["result_text"])
        model = self._get(request.context, EntityKind.MODEL, request.model_id)
        profile = self._json(request.context, model.profile)
        from .test_executor import EXECUTOR, enabled as development_executor_enabled
        diagnostic = result.get("synthetic") is True
        if diagnostic and (not development_executor_enabled(request.context.scope.workspace_id)
                           or result.get("actual_model") != EXECUTOR):
            raise ContractError("model_judge_synthetic_provenance_invalid")
        return JudgeResult(verdict=vote["verdict"], confidence=vote["confidence"], rationale=vote["rationale"],
            provider_key=model.provider_key, model_key=model.model_key,
            model_version=result.get("actual_model") or "provider_version_unreported",
            failure_domain=("local_test_executor:" + EXECUTOR if diagnostic else
                            model.provider_key + ":" + str(urlsplit(profile["base_url"]).hostname)),
            contribution_id=_uuid(result["contribution_id"]))

    def plan_application(self, *, context, model_id, spec, kind, idempotency_key,
                         conversation_id, message_id, _persona=None):
        from .application_evidence import application_spec
        normalized = application_spec(kind, spec)
        return self.start_task(context=context, model_id=model_id, payload={},
            idempotency_key=idempotency_key, conversation_id=conversation_id, message_id=message_id,
            _sealed_spec={"rubric_key": kind + "_spec", "version": VERSION, "input": normalized},
            _persona=_persona)

    def record_application_result(self, *, context, task_id, source_id, verification, artifact_refs):
        from .application_evidence import record_application_result
        return record_application_result(self, context=context, task_id=task_id, source_id=source_id,
                                         verification=verification, artifact_refs=artifact_refs)
