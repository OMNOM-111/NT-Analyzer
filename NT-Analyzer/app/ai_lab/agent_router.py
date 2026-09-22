"""Role-aware routing and quota failover for external AI agents.

The router never grants execution authority. It selects only a text/embedding
service; deterministic AI Lab gates remain responsible for validation, compile,
backtest, arbitration and manual promotion.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from . import agent_registry, llm_timeouts, universal_llm


ROLE_PROVIDER_ORDER: Dict[str, List[str]] = {
    # Benchmark 2026-06-30: GPT-5 mini was the only external model that was
    # both strong across the full suite and deterministic enough for gates.
    "orchestrator": ["gemini", "zai", "openrouter", "azure_foundry", "deepseek", "github_models"],
    "chief_agent": ["deepseek", "azure_foundry", "gemini", "zai", "openrouter", "github_models"],
    "hypothesis": ["azure_foundry", "gemini", "zai", "openrouter", "deepseek", "github_models"],
    "strategy_analyst": ["gemini", "zai", "openrouter", "azure_foundry", "github_models"],
    "accountant": ["gemini", "zai", "openrouter", "azure_foundry", "deepseek", "github_models"],
    "news_analyst": ["gemini", "zai", "openrouter", "azure_foundry", "deepseek", "github_models"],
    "coder": ["azure_foundry", "openrouter", "gemini", "zai", "github_models"],
    "code_reviewer": ["azure_foundry", "openrouter", "gemini", "zai", "github_models"],
    "compile_error_fixer": ["azure_foundry", "openrouter", "gemini", "zai", "github_models"],
    "backtest_analyst": ["gemini", "zai", "openrouter", "azure_foundry", "github_models"],
    "risk_manager": ["azure_foundry", "openrouter", "gemini", "zai", "github_models"],
    "optimizer": ["gemini", "zai", "openrouter", "azure_foundry", "github_models"],
    "overfit_detector": ["azure_foundry", "openrouter", "gemini", "zai", "github_models"],
    "final_judge": ["deepseek", "azure_foundry", "openrouter", "gemini", "zai", "github_models"],
    # A dedicated compact instruction model is configured on GitHub Models;
    # prefer it for low-token intent repair before borrowing unrelated roles.
    "telegram_assistant": ["github_models", "gemini", "zai", "openrouter", "azure_foundry"],
    # Victor's probabilistic step is limited to understanding the owner's
    # meaning. The configured GPT-5 mini won the project's instruction-routing
    # benchmark; deterministic application handlers still own execution.
    "vitek_dispatcher": ["azure_foundry", "github_models", "gemini", "zai", "openrouter", "deepseek"],
    "embedding": ["azure_foundry", "openai", "gemini", "github_models"],
    "general": ["gemini", "zai", "openrouter", "azure_foundry", "deepseek", "github_models"],
}

COMPLEXITY_PROVIDER_ORDER: Dict[str, List[str]] = {
    "light": ["gemini", "zai", "openrouter", "azure_foundry", "deepseek", "github_models"],
    "standard": ["gemini", "zai", "deepseek", "azure_foundry", "openrouter", "github_models"],
    "critical": ["deepseek", "azure_foundry", "gemini", "zai", "openrouter", "github_models"],
}


class AgentRouterError(RuntimeError):
    """Safe routing failure without prompt/key content."""


def _provider_rank(role: str, provider: str) -> int:
    order = ROLE_PROVIDER_ORDER.get(role, ROLE_PROVIDER_ORDER["general"])
    try:
        return order.index(provider)
    except ValueError:
        return len(order) + 10


def candidates(
    role: str,
    *,
    enabled_only: bool = True,
    endpoint_type: Optional[str] = None,
    complexity: str = "auto",
    allow_paid: bool = True,
) -> List[Dict[str, Any]]:
    kind = endpoint_type or ("embeddings" if role == "embedding" else "chat")
    rows = [
        agent for agent in agent_registry.list_agents()
        if agent.get("key_configured")
        and agent.get("endpoint_type") == kind
        and (not enabled_only or agent.get("enabled"))
        and not agent.get("cooldown_active")
        and (allow_paid or agent.get("billing_mode") == "free_tier")
    ]
    # Somebody other than the owner is routed only among shared connections;
    # the invocation itself refuses the rest again.
    allowed = universal_llm.shared_registry_filter()
    if allowed is not None:
        rows = [agent for agent in rows if str(agent.get("id") or "") in allowed]
    level = str(complexity or "auto").strip().lower()
    provider_order = COMPLEXITY_PROVIDER_ORDER.get(level)
    def provider_rank(agent: Dict[str, Any]) -> int:
        provider = str(agent.get("provider") or "")
        if provider_order is None:
            return _provider_rank(role, provider)
        try:
            return provider_order.index(provider)
        except ValueError:
            return len(provider_order) + 10
    def model_rank(agent: Dict[str, Any]) -> int:
        model = str(agent.get("model") or "").lower()
        if level == "critical":
            return 0 if model == "deepseek-v4-pro" else 1 if model == "deepseek-v4-flash" else 2
        return 0 if model == "deepseek-v4-flash" else 1 if model == "deepseek-v4-pro" else 0
    rows.sort(key=lambda agent: (
        provider_rank(agent),
        model_rank(agent),
        0 if str(agent.get("role") or "") in {role, "general"} else 1,
        int(agent.get("priority") or 100),
        int(agent.get("requests_today") or 0),
        str(agent.get("account_name") or ""),
    ))
    # Star-rating re-rank + exploration on top of safe gated candidates only.
    try:
        from . import ai_ratings
        # ``usage_scope`` is the request-wide source of truth for tenant
        # attribution. Ratings from one workspace must not steer another.
        usage_context = universal_llm._USAGE_CONTEXT.get()  # noqa: SLF001
        workspace_id = str((usage_context or {}).get("workspace_id") or "")
        # Unscoped/global ratings are legacy data and must not influence a
        # tenant request (or a process-wide maintenance call). Only a concrete
        # request workspace may opt into learned routing.
        if workspace_id:
            rows = ai_ratings.rank_agents(
                role, rows, explore=True, workspace_id=workspace_id,
            )
    except Exception:
        pass
    return rows


def _retryable(error: str) -> bool:
    text = str(error or "").lower()
    return any(marker in text for marker in (
        "http 429", "rate limit", "quota", "resource_exhausted", "too many requests",
        "http 500", "http 502", "http 503", "http 504", "timeout", "timed out",
        "temporarily", "provider недоступен",
    ))


def invoke_role(
    role: str,
    prompt: str,
    *,
    system_prompt: str = "",
    max_output_tokens: int = 1024,
    timeout: int = llm_timeouts.ANALYSIS,
    purpose: str = "role_request",
    enabled_only: bool = True,
    max_attempts: int = 12,
    complexity: str = "auto",
    cache_mode: str = "auto",
    allow_paid: bool = True,
    on_reasoning: Optional[Callable[[str], None]] = None,
    on_content: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    route = candidates(
        role, enabled_only=enabled_only, complexity=complexity,
        allow_paid=allow_paid,
    )
    if not route:
        if universal_llm.shared_registry_filter() is not None:
            raise AgentRouterError("Нет доступной модели: подключите свою модель или дождитесь, "
                                   "когда владелец откроет общую.")
        raise AgentRouterError(f"Нет доступной enabled-модели для роли {role}.")
    attempts: List[Dict[str, Any]] = []
    last_error = ""
    for agent in route[:max(1, int(max_attempts))]:
        try:
            result = universal_llm.invoke_agent(
                str(agent["id"]), prompt, system_prompt=system_prompt,
                max_output_tokens=max_output_tokens, timeout=timeout,
                allow_disabled=not enabled_only, request_role=role, purpose=purpose,
                cache_mode=cache_mode,
                on_reasoning=on_reasoning, on_content=on_content,
            )
            # Universal client uses ``response`` for the public test API;
            # AI Lab chat consumers use the conventional ``content`` key.
            # Normalize once at the routing boundary.
            result["content"] = str(result.get("response") or result.get("content") or "")
            result["request_role"] = role
            # Persist the route that actually served the response, rather than
            # a visible persona name that the rating router cannot match.
            result["routing_role_id"] = role
            result["routing_model_id"] = str(
                result.get("actual_model") or result.get("model") or agent.get("model") or "unknown"
            )
            result["routing_provider"] = str(result.get("provider") or agent.get("provider") or "")
            result["routing_agent_id"] = str(agent.get("id") or "")
            result["complexity"] = complexity
            result["route_attempts"] = attempts + [{
                "agent_id": agent["id"], "account_name": agent.get("account_name"),
                "provider": agent.get("provider"), "model": agent.get("model"), "status": "success",
            }]
            return result
        except universal_llm.UniversalLLMError as exc:
            last_error = str(exc)
            attempts.append({
                "agent_id": agent["id"], "account_name": agent.get("account_name"),
                "provider": agent.get("provider"), "model": agent.get("model"),
                "status": "error", "error": last_error[:300],
            })
            if _retryable(last_error):
                seconds = 3600 if any(marker in last_error.lower() for marker in ("429", "quota", "rate limit")) else 300
                agent_registry.set_cooldown(str(agent["id"]), seconds, "quota_or_provider_error")
            continue
    raise AgentRouterError(
        f"Все доступные модели роли {role} завершились ошибкой: {last_error or 'unknown provider error'}"
    )


def invoke_messages(
    role: str,
    messages: List[Dict[str, str]],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Route a conventional chat message list without persisting its text."""
    system_parts: List[str] = []
    conversation: List[str] = []
    for message in messages or []:
        content = str(message.get("content") or "")
        if message.get("role") == "system":
            system_parts.append(content)
        else:
            conversation.append(f"{message.get('role', 'user')}: {content}")
    return invoke_role(
        role,
        "\n\n".join(conversation),
        system_prompt="\n\n".join(system_parts),
        **kwargs,
    )


def status() -> Dict[str, Any]:
    return {
        "active_requests": universal_llm.active_requests(),
        "routing_mode": "automatic_complexity",
        "complexity_provider_order": COMPLEXITY_PROVIDER_ORDER,
        "roles": {
            role: [
                {
                    "agent_id": row.get("id"), "account_name": row.get("account_name"),
                    "provider": row.get("provider"), "model": row.get("model"),
                    "rotation_group": row.get("rotation_group"), "priority": row.get("priority"),
                }
                for row in candidates(role)
            ]
            for role in ROLE_PROVIDER_ORDER
        },
        "safety": {
            "historical_only": True,
            "paper_live_authority": False,
            "promotion_authority": False,
        },
    }
