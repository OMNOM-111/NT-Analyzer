"""Role-aware routing and quota failover for external AI agents.

The router never grants execution authority. It selects only a text/embedding
service; deterministic AI Lab gates remain responsible for validation, compile,
backtest, arbitration and manual promotion.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import agent_registry, universal_llm


ROLE_PROVIDER_ORDER: Dict[str, List[str]] = {
    # Benchmark 2026-06-30: GPT-5 mini was the only external model that was
    # both strong across the full suite and deterministic enough for gates.
    "hypothesis": ["azure_foundry", "gemini", "openrouter"],
    "strategy_analyst": ["gemini", "azure_foundry", "openrouter"],
    "coder": ["azure_foundry", "openrouter", "gemini"],
    "code_reviewer": ["azure_foundry", "openrouter", "gemini"],
    "compile_error_fixer": ["azure_foundry", "openrouter", "gemini"],
    "backtest_analyst": ["gemini", "azure_foundry", "openrouter"],
    "risk_manager": ["azure_foundry", "openrouter", "gemini"],
    "optimizer": ["gemini", "azure_foundry", "openrouter"],
    "overfit_detector": ["azure_foundry", "openrouter", "gemini"],
    "final_judge": ["azure_foundry", "openrouter", "gemini"],
    "telegram_assistant": ["gemini", "openrouter", "azure_foundry"],
    "embedding": ["azure_foundry", "openai", "gemini"],
    "general": ["gemini", "openrouter", "azure_foundry"],
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
) -> List[Dict[str, Any]]:
    kind = endpoint_type or ("embeddings" if role == "embedding" else "chat")
    rows = [
        agent for agent in agent_registry.list_agents()
        if agent.get("key_configured")
        and agent.get("endpoint_type") == kind
        and (not enabled_only or agent.get("enabled"))
        and not agent.get("cooldown_active")
    ]
    rows.sort(key=lambda agent: (
        _provider_rank(role, str(agent.get("provider") or "")),
        0 if str(agent.get("role") or "") in {role, "general"} else 1,
        int(agent.get("priority") or 100),
        int(agent.get("requests_today") or 0),
        str(agent.get("account_name") or ""),
    ))
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
    timeout: int = 180,
    purpose: str = "role_request",
    enabled_only: bool = True,
    max_attempts: int = 4,
) -> Dict[str, Any]:
    route = candidates(role, enabled_only=enabled_only)
    if not route:
        raise AgentRouterError(f"Нет доступной enabled-модели для роли {role}.")
    attempts: List[Dict[str, Any]] = []
    last_error = ""
    for agent in route[:max(1, int(max_attempts))]:
        try:
            result = universal_llm.invoke_agent(
                str(agent["id"]), prompt, system_prompt=system_prompt,
                max_output_tokens=max_output_tokens, timeout=timeout,
                allow_disabled=not enabled_only, request_role=role, purpose=purpose,
            )
            # Universal client uses ``response`` for the public test API;
            # AI Lab chat consumers use the conventional ``content`` key.
            # Normalize once at the routing boundary.
            result["content"] = str(result.get("response") or result.get("content") or "")
            result["request_role"] = role
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
