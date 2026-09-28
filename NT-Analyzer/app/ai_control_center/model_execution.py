"""Scoped adapter to the existing universal client, budget locks and usage store.

Private accounts cannot enumerate or fall back to the global owner registry.
The server supplies approval limits/pricing, never a browser-provided number.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from uuid import UUID, uuid5

from .. import ai_budgets, secure_store
from ..ai_lab import agent_registry, universal_llm
from .states import ContractError
from .connection_protocol import validate as validate_protocol


def _number(value, maximum):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= maximum:
        raise ContractError("model_budget_exhausted")
    return float(value)


class PrivateRegistry:
    """One exact private account; all mutating hooks stay inside this adapter."""
    def __init__(self, *, context, model, account, profile, limits, secrets, revalidate,
                 usage_reader=None, usage_writer=None, pricing=None):
        self.context, self.model, self.account, self.profile = context, model, account, profile
        validate_protocol(profile)
        self.secrets, self.revalidate = secrets, revalidate
        self.usage_reader = usage_reader or agent_registry.usage_rows
        self.usage_writer = usage_writer or agent_registry.record_usage
        self.agent_id = "aw_model." + str(model.header.entity_id)
        self.disabled = False
        self.daily = _number(limits.get("daily_budget_usd"), agent_registry.MAX_DAILY_BUDGET_USD)
        self.monthly = _number(limits.get("monthly_budget_usd"), agent_registry.MAX_MONTHLY_BUDGET_USD)
        if self.daily > self.monthly:
            raise ContractError("model_budget_exhausted")
        managed = agent_registry.managed_pricing(model.provider_key, model.model_key,
                                                 agent_registry.infer_billing_mode(model.provider_key, model.model_key, 0))
        self.pricing = dict(pricing or managed)
        if self.pricing.get("pricing_status") not in {"free", "configured", "estimated"}:
            raise ContractError("model_pricing_unavailable")
        for name in ("input_price_usd_per_m", "output_price_usd_per_m"):
            value = self.pricing.get(name)
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 10000:
                raise ContractError("model_pricing_unavailable")
        if (not self.pricing["input_price_usd_per_m"] and not self.pricing["output_price_usd_per_m"]
                and self.pricing["pricing_status"] != "free"):
            raise ContractError("model_pricing_unavailable")

    def _own(self, agent_id):
        if agent_id != self.agent_id:
            raise agent_registry.AgentRegistryError("Private model not found.")
        self.revalidate()

    def get_agent(self, agent_id, public=True):
        self._own(agent_id)
        # The agent id names this one connection, so its limits count every
        # call made through it -- its owner's and, when shared, other people's.
        rows = [row for row in self.usage_reader(agent_id=self.agent_id, limit=100_000)
                if row.get("agent_id") == self.agent_id]
        now = datetime.now(timezone.utc)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = day.replace(day=1)
        return {"id": self.agent_id, "name": self.profile["label"], "model": self.model.model_key,
            "provider": self.model.provider_key, "base_url": self.profile["base_url"], "role": "general",
            "account_name": "aw_provider." + str(self.account.header.entity_id),
            "enabled": not self.disabled, "key_configured": True, "endpoint_type": "chat",
            "auth_type": agent_registry.PROVIDERS[self.model.provider_key]["auth_type"],
            "daily_budget_usd": self.daily, "monthly_budget_usd": self.monthly,
            "spend_today_usd": agent_registry._sum_cost(rows, since=day),
            "account_spend_month_usd": agent_registry._sum_cost(rows, since=month),
            "billing_mode": "free_tier" if self.pricing.get("pricing_status") == "free" else "payg",
            **self.pricing}

    def list_agents(self):
        return [self.get_agent(self.agent_id)]

    def get_api_key(self, agent_id):
        self._own(agent_id)
        value = self.secrets.get_secret(self.account.credential.key)
        if not value:
            raise agent_registry.AgentRegistryError("Private model credential unavailable.")
        return value

    def auto_disable(self, agent_id, reason):
        self._own(agent_id)
        self.disabled = True

    def clear_cooldown(self, agent_id):
        self._own(agent_id)

    def record_test(self, agent_id, result):
        self._own(agent_id)
        # Connection status is a typed task observation, never a global edit.

    def record_usage(self, row):
        if row.get("agent_id") != self.agent_id:
            raise agent_registry.AgentRegistryError("Private model usage mismatch.")
        # Accounting must still complete after cancellation/access expiry.
        # The shared ledger's existing safe-field allowlist rejects prompt/key.
        clean = dict(row)
        clean.update(workspace_id=self.context.scope.workspace_id, user_id=str(self.context.user_uuid))
        self.usage_writer(clean)


def shared_registry_binding(model, profile):
    """The owner's registry model behind a shared binding, checked as the owner's own is."""
    registry_id = profile.get("existing_registry_id")
    try:
        row = agent_registry.get_agent(registry_id)
    except agent_registry.AgentRegistryError:
        raise ContractError("model_owner_binding_unavailable") from None
    if (not row.get("enabled") or not row.get("key_configured") or row.get("endpoint_type") != "chat"
            or row.get("pricing_status") not in {"free", "configured", "estimated"}):
        raise ContractError("model_owner_binding_unavailable")
    if row.get("provider") != model.provider_key or row.get("model") != model.model_key:
        raise ContractError("model_owner_binding_changed")
    return registry_id


class ModelExecutor:
    def __init__(self, *, budget_limits, secrets=None, pricing=None, owner_binding=None,
                 usage_reader=None, usage_writer=None):
        self.budget_limits = budget_limits
        self.secrets = secrets or secure_store
        self.pricing = pricing
        self.owner_binding = owner_binding
        self.usage_reader, self.usage_writer = usage_reader, usage_writer

    def __call__(self, *, context, model, account, profile, prompt, system_prompt, request_id,
                 conversation_id, max_output_tokens, purpose, cancelled, admit, shared=None, acting_agent=None):
        with universal_llm.invocation_policy(allow_hidden_retries=False):
            return self._invoke(context=context, model=model, account=account, profile=profile, prompt=prompt,
                system_prompt=system_prompt, request_id=request_id, conversation_id=conversation_id,
                max_output_tokens=max_output_tokens, purpose=purpose, cancelled=cancelled, admit=admit,
                shared=shared, acting_agent=acting_agent)

    def _invoke(self, *, context, model, account, profile, prompt, system_prompt, request_id,
                conversation_id, max_output_tokens, purpose, cancelled, admit, shared=None, acting_agent=None):
        """``shared`` is a revocable call grant on somebody else's connection.

        ``model``/``account``/``profile`` are then the owner's records, read by
        the service; the caller never saw them. The grant is checked with every
        admission, so a share turned off stops the call before transmission.
        """
        def check():
            admit(context, "provider_transmit", 0.0)
            if shared is not None:
                shared.check()
            if callable(cancelled) and cancelled():
                raise ContractError("model_cancelled")

        check()
        credentials = self.secrets
        if shared is not None and hasattr(credentials, "for_owner"):
            from .contracts import ActorKind, ActorRef, RequestContext, TenantScope
            owner = UUID(shared.share["owner_user_uuid"])
            owner_context = RequestContext(scope=TenantScope(environment=context.scope.environment,
                    workspace_id=shared.share["owner_workspace_id"]), user_uuid=owner,
                actor=ActorRef(kind=ActorKind.SERVICE,
                    actor_id=uuid5(UUID("03c9b9db-145e-46af-b498-ccf25f80ff81"), "shared-credential-reader"),
                    on_behalf_of=owner))
            credentials = credentials.for_owner(owner_context)
        if profile.get("credential_source") == "owner_registry_binding":
            return self._owner(context=context, model=model, profile=profile, prompt=prompt,
                system_prompt=system_prompt, conversation_id=conversation_id,
                max_output_tokens=max_output_tokens, purpose=purpose, check=check, admit=admit, request_id=request_id,
                shared=shared, acting_agent=acting_agent)
        if not callable(self.budget_limits):
            raise ContractError("model_budget_exhausted")
        limits = self.budget_limits(context, model, profile)
        if not isinstance(limits, dict):
            raise ContractError("model_budget_exhausted")
        pricing = self.pricing(context, model, profile) if callable(self.pricing) else None
        adapter = PrivateRegistry(context=context, model=model, account=account, profile=profile,
            limits=limits, secrets=credentials, revalidate=check, pricing=pricing,
            usage_reader=self.usage_reader, usage_writer=self.usage_writer)
        if shared is not None:
            adapter.shared_grant = dict(shared.share)
        server_shared = shared is not None and hasattr(self.secrets, "for_owner")
        def record_share(result, status):
            if not server_shared:
                return
            from . import model_sharing
            model_sharing.observe({**result, "request_id": request_id,
                "status": status, "purpose": purpose},
                {"user_id": str(context.user_uuid), "workspace_id": context.scope.workspace_id,
                 "conversation_id": conversation_id, "acting_agent": acting_agent,
                 "request_source": "agent_world." + request_id}, grant=shared.share)
        with universal_llm.registry_scope(adapter):
            try:
                result = self._call(adapter.agent_id, context=context, prompt=prompt, system_prompt=system_prompt,
                    conversation_id=conversation_id, max_output_tokens=max_output_tokens, purpose=purpose,
                    check=check, admit=admit, request_id=request_id, acting_agent=acting_agent)
            except Exception:
                record_share({}, "error")
                raise
            # Some malicious endpoints echo their Authorization credential.
            # Never persist that echo as a model artifact or display it in chat.
            key = credentials.get_secret(account.credential.key)
            if key and key in json.dumps(result, ensure_ascii=False):
                record_share(result, "blocked")
                raise ContractError("model_provider_response_invalid")
            record_share(result, "success")
            return result

    def _owner(self, *, context, model, profile, shared=None, **kwargs):
        if shared is not None:
            # Somebody else's call through the owner's registry binding: the
            # grant, not the caller's identity, is what allows it.
            def resolve(*_):
                shared.check()
                return shared_registry_binding(model, profile)
        elif callable(self.owner_binding):
            resolve = self.owner_binding
        else:
            raise ContractError("model_owner_binding_denied")
        # The root checks current Local owner identity and an exact server
        # allowlist; it returns one registry ID, never a credential.
        agent_id = resolve(context, model, profile)
        if not isinstance(agent_id, str) or not agent_id:
            raise ContractError("model_owner_binding_denied")
        configured = agent_registry.get_agent(agent_id)
        if configured.get("provider") != model.provider_key or configured.get("model") != model.model_key:
            raise ContractError("model_owner_binding_changed")
        if configured.get("pricing_status") not in {"free", "configured", "estimated"}:
            raise ContractError("model_pricing_unavailable")
        previous_check = kwargs["check"]
        def revalidate_binding():
            previous_check()
            if resolve(context, model, profile) != agent_id:
                raise ContractError("model_owner_binding_changed")
            current = agent_registry.get_agent(agent_id)
            if current.get("provider") != model.provider_key or current.get("model") != model.model_key:
                raise ContractError("model_owner_binding_changed")
        kwargs["check"] = revalidate_binding
        result = self._call(agent_id, context=context, **kwargs)
        if shared is not None:
            key = agent_registry.get_api_key(agent_id)
            if key and key in json.dumps(result, ensure_ascii=False):
                raise ContractError("model_provider_response_invalid")
        return result

    @staticmethod
    def _call(agent_id, *, context, prompt, system_prompt, conversation_id, max_output_tokens,
              purpose, check, admit, request_id, acting_agent=None):
        estimate = universal_llm.estimate_request_cost(agent_id, prompt, system_prompt=system_prompt,
                                                      max_output_tokens=max_output_tokens)["estimated_max_cost_usd"]
        check()
        admit(context, "provider_transmit", estimate)
        if not ai_budgets.check_budget(context.scope.workspace_id, estimate).get("ok"):
            raise ContractError("model_budget_exhausted")
        from .. import runtime_env
        usage_user_id = str(context.user_uuid)
        if runtime_env.is_server_environment():
            from .. import account_auth
            user = account_auth.find_active_user_by_uuid(usage_user_id)
            if not user:
                raise ContractError("model_caller_invalid")
            usage_user_id = str(user.get("user_id") or user.get("id") or "")
            if not usage_user_id.isdigit():
                raise ContractError("model_caller_invalid")
        try:
            with universal_llm.usage_scope({"user_id": usage_user_id,
                    "workspace_id": context.scope.workspace_id, "conversation_id": conversation_id,
                    "request_source": "agent_world." + str(request_id), "acting_agent": acting_agent}):
                result = universal_llm.invoke_agent(agent_id, prompt, system_prompt=system_prompt,
                    max_output_tokens=max_output_tokens, timeout=60, request_role="general",
                    purpose=purpose, cache_mode="off")
        except universal_llm.BudgetExceeded:
            raise ContractError("model_budget_exhausted") from None
        except (universal_llm.UniversalLLMError, agent_registry.AgentRegistryError) as exc:
            text = str(exc).lower()
            code = "model_key_invalid" if any(x in text for x in ("401", "403", "credential unavailable")) else (
                "model_not_found" if "404" in text else "model_endpoint_unavailable")
            raise ContractError(code) from None
        result = dict(result)
        result.pop("reasoning", None)
        result.pop("reasoning_content", None)
        configuration = universal_llm._registry().get_agent(agent_id)
        result["cost_known"] = configuration.get("pricing_status") in {"free", "configured", "estimated"}
        return result
