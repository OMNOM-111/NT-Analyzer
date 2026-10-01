"""Trusted server-only model route for recurring owner reports.

The scheduler owns report idempotency and delivery. This adapter only bridges
non-daily generation to existing owner-scoped Agent World model records,
ServerSecrets, budget accounting, and the universal provider client.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from uuid import UUID, uuid5

from .. import account_auth, ai_budgets, permissions, runtime_env, workspaces
from ..production_storage.core import PostgresClient
from . import contracts as c, domain_gateway, server_gateway, server_model_usage
from .connection_protocol import validate as validate_protocol
from .model_execution import ModelExecutor
from .model_service import ModelService
from .postgres_repository import PostgresAgentWorldRepository
from .secret_store import for_context
from .server_secrets import ServerSecrets
from .states import ContractError, EntityKind


_NS = UUID("7932aaf8-3d14-4acf-8230-11aa9170fd6c")


def _subject(scope):
    environment = server_gateway.environment()
    if (environment not in {c.Environment.CANARY, c.Environment.PRODUCTION}
            or not runtime_env.environment_explicit()
            or not runtime_env.is_server_environment()
            or not isinstance(scope, dict)):
        raise ContractError("periodic_owner_server_required")
    try:
        user_id = int(scope.get("user_id") or 0)
        workspace_id = str(scope.get("workspace_id") or "")
        user_uuid = UUID(str(scope.get("user_uuid") or ""))
    except (TypeError, ValueError, AttributeError):
        raise ContractError("periodic_owner_scope_invalid") from None
    matching = [row for row in workspaces.runtime_monitor_scopes()
                if int(row.get("user_id") or 0) == user_id
                and str(row.get("workspace_id") or "") == workspace_id]
    if (len(matching) != 1 or matching[0].get("is_owner") is not True
            or matching[0].get("uses_owner_runtime") is not True
            or matching[0].get("membership_role") != "owner"
            or not server_gateway.configured(workspace_id)):
        raise ContractError("periodic_owner_scope_denied")
    user = account_auth.find_active_user(user_id)
    if (not user or user.get("is_owner") is not True
            or user.get("is_preview_user") or user.get("is_service_account")
            or account_auth.user_uuid_for_legacy_id(user_id) != str(user_uuid)):
        raise ContractError("periodic_owner_identity_inactive")
    workspace = workspaces.require_workspace_writer(user_id, workspace_id=workspace_id)
    if (workspace.get("status") != "active"
            or workspace.get("uses_owner_runtime") is not True
            or int(workspace.get("owner_user_id") or 0) != user_id
            or (workspace.get("membership") or {}).get("role") != "owner"):
        raise ContractError("periodic_owner_scope_denied")
    capabilities = permissions.resolve_for_user_id(user_id, user).get("capabilities") or {}
    if not all(capabilities.get(name) is True for name in ("ai_lab", "ai_pro_models")):
        raise ContractError("periodic_owner_capability_required")
    return c.RequestContext(
        scope=c.TenantScope(environment=environment, workspace_id=workspace_id),
        user_uuid=user_uuid,
        actor=c.ActorRef(kind=c.ActorKind.SERVICE,
            actor_id=uuid5(user_uuid, "periodic-owner-report:" + workspace_id),
            on_behalf_of=user_uuid),
    )


def _repository(context):
    return PostgresAgentWorldRepository(
        PostgresClient(os.environ.get("STRATFORGE_DATABASE_URL", ""), production=True),
        environment=context.scope.environment, read_only=True)


def _admit(scope, expected, context, operation, estimate=0.0):
    current = _subject(scope)
    if current != expected or context != expected or operation not in {"read", "provider_transmit"}:
        raise ContractError("periodic_owner_context_changed")
    if type(estimate) not in {int, float} or not math.isfinite(estimate) or estimate < 0:
        raise ContractError("model_budget_exhausted")
    if not ai_budgets.check_budget(context.scope.workspace_id, float(estimate)).get("ok"):
        raise ContractError("model_budget_exhausted")


def _select(service, context):
    """Select the single active general connection, never an app-role model."""
    candidates = []
    for model in service._all(context, EntityKind.MODEL):
        if model.header.owner_user_uuid != context.user_uuid or model.status != "active":
            continue
        profile = service._json(context, model.profile)
        if (profile.get("source") != "private_model_connection"
                or profile.get("connection_kind") != "model"):
            continue
        account = service._get(context, EntityKind.PROVIDER_ACCOUNT,
                               profile.get("provider_account_id"))
        persona = service._get(context, EntityKind.PERSONA, profile.get("persona_id"))
        if (account.status != "active" or persona.status != "active"
                or account.provider_key != model.provider_key):
            continue
        persona_profile = service._json(context, persona.profile)
        if persona_profile.get("application_role") is not None:
            continue
        validate_protocol(profile)
        service._endpoint(model.provider_key, profile.get("base_url"))
        candidates.append((model, account, profile))
    if len(candidates) != 1:
        raise ContractError("periodic_owner_model_ambiguous" if candidates
                            else "periodic_owner_model_required")
    return candidates[0]


def invoke(*, scope, prompt, system_prompt, max_output_tokens, purpose,
           conversation_id, request_key):
    """Return a scrubbed universal-client-shaped result for one report."""
    if (type(prompt) is not str or not prompt or len(prompt) > 19_000
            or type(system_prompt) is not str or not system_prompt or len(system_prompt) > 4_000
            or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 4_000
            or type(purpose) is not str or not purpose.startswith("orchestrator_")
            or type(request_key) is not str or not 1 <= len(request_key) <= 120):
        raise ContractError("periodic_owner_request_invalid")
    context = _subject(scope)
    repository = _repository(context)
    admission = lambda ctx, operation, estimate=0.0: _admit(
        scope, context, ctx, operation, estimate)
    service = ModelService(repository, admit=admission)
    model, account, profile = _select(service, context)
    secrets = for_context(repository, context)
    if not isinstance(secrets, ServerSecrets) or not secrets.available():
        raise ContractError("model_secure_storage_unavailable")
    executor = ModelExecutor(budget_limits=domain_gateway._private_limits,
        secrets=secrets, usage_reader=server_model_usage.usage_rows,
        usage_writer=lambda _row: None)
    request_id = str(uuid5(_NS, ":".join((context.scope.environment.value,
        context.scope.workspace_id, str(context.user_uuid), request_key))))
    result = executor(context=context, model=model, account=account, profile=profile,
        prompt=prompt, system_prompt=system_prompt, request_id=request_id,
        conversation_id=conversation_id, max_output_tokens=max_output_tokens,
        purpose=purpose, cancelled=lambda: False, admit=admission,
        acting_agent="orchestrator")
    checkpoint = {"task_id": request_id,
        "request_sha256": hashlib.sha256(json.dumps({"prompt": prompt,
            "system_prompt": system_prompt}, sort_keys=True,
            ensure_ascii=True).encode()).hexdigest()}
    receipt = ModelService._clean_receipt(result, checkpoint)
    return {"content": receipt["response"], "actual_model": receipt.get("actual_model"),
        "provider": model.provider_key, "input_tokens": receipt.get("input_tokens"),
        "cached_input_tokens": receipt.get("cached_input_tokens"),
        "output_tokens": receipt.get("output_tokens"), "cost_usd": receipt.get("cost_usd"),
        "request_id": receipt.get("provider_request_id"), "executor": receipt.get("executor"),
        "external_call": receipt.get("external_call")}
