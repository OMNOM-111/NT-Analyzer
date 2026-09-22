"""Universal, budget-gated client for user-configured AI agents.

Supported transports:

* OpenAI-compatible chat/embeddings (OpenAI, DeepSeek, OpenRouter, Mistral,
  Groq and Custom);
* Microsoft Foundry / Azure OpenAI v1 and legacy deployment URLs;
* Gemini generateContent/embedContent.

Prompt text and API keys are never written to usage logs.
"""
from __future__ import annotations

import json
import hashlib
import contextvars
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import agent_registry, llm_timeouts, response_cache


_REGISTRY_CONTEXT: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "stratforge_llm_registry_context", default=None
)
_ALLOW_HIDDEN_RETRIES: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "stratforge_llm_hidden_retries", default=True
)


def _registry():
    """Internal trusted adapter; ordinary calls retain the existing registry."""
    scoped = _REGISTRY_CONTEXT.get()
    return scoped if scoped is not None else agent_registry


@contextmanager
def registry_scope(scoped_adapter):
    """Bind one validated private registry to this context, never process globals."""
    required = ("get_agent", "list_agents", "get_api_key", "auto_disable",
                "clear_cooldown", "record_usage", "record_test")
    if scoped_adapter is None or not all(callable(getattr(scoped_adapter, name, None)) for name in required):
        raise UniversalLLMError("Invalid scoped model registry.")
    token = _REGISTRY_CONTEXT.set(scoped_adapter)
    try:
        yield scoped_adapter
    finally:
        _REGISTRY_CONTEXT.reset(token)


@contextmanager
def invocation_policy(*, allow_hidden_retries: bool):
    """Trusted bounded callers may forbid another call under one reservation."""
    if type(allow_hidden_retries) is not bool:
        raise UniversalLLMError("Invalid invocation policy.")
    token = _ALLOW_HIDDEN_RETRIES.set(allow_hidden_retries)
    try:
        yield
    finally:
        _ALLOW_HIDDEN_RETRIES.reset(token)


_BUDGET_LOCK = threading.RLock()
_RESERVATIONS: Dict[str, Dict[str, Any]] = {}
_USAGE_CONTEXT: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "stratforge_llm_usage_context", default={}
)
_PARTICIPATION_STEPS: contextvars.ContextVar[Optional[List[Dict[str, Any]]]] = contextvars.ContextVar(
    "stratforge_llm_participation", default=None
)


@contextmanager
def usage_scope(context: Optional[Dict[str, Any]] = None):
    """Attribute nested model calls to the current user and workspace.

    Yields the in-turn participation list so callers can attach the full model
    chain to the public assistant message without reading usage logs.
    """
    clean = {
        key: (context or {}).get(key)
        for key in ("user_id", "user_name", "workspace_id", "conversation_id", "request_source",
                    "acting_agent")
        if (context or {}).get(key) not in (None, "")
    }
    steps: List[Dict[str, Any]] = []
    token = _USAGE_CONTEXT.set(clean)
    part_token = _PARTICIPATION_STEPS.set(steps)
    try:
        yield steps
    finally:
        _PARTICIPATION_STEPS.reset(part_token)
        _USAGE_CONTEXT.reset(token)


def current_participation() -> List[Dict[str, Any]]:
    """Return the participation steps for the active usage_scope, if any."""
    steps = _PARTICIPATION_STEPS.get()
    return list(steps) if isinstance(steps, list) else []


def shared_registry_filter() -> Optional[set]:
    """Which registry models this request may use: None means all of them.

    The sharing rule lives in the AI centre; this module is the one place the
    AI Lab already crosses that boundary, so routing asks here.
    """
    from ..ai_control_center import model_sharing
    return model_sharing.registry_filter(dict(_USAGE_CONTEXT.get() or {}))


def current_usage_context() -> Dict[str, Any]:
    """Return a copy of the active attribution context for legacy adapters."""
    return dict(_USAGE_CONTEXT.get() or {})


def note_participation(step: Dict[str, Any]) -> None:
    """Append one non-LLM participant (domain agent handoff) to the turn chain."""
    steps = _PARTICIPATION_STEPS.get()
    if not isinstance(steps, list) or not isinstance(step, dict):
        return
    agent_id = str(step.get("agent_id") or step.get("id") or "")[:80]
    agent_name = str(step.get("agent_name") or step.get("name") or "")[:80]
    model = str(step.get("model") or step.get("actual_model") or "")[:180]
    key = (agent_id, agent_name, model)
    for existing in steps:
        if (
            str(existing.get("agent_id") or "") == key[0]
            and str(existing.get("agent_name") or "") == key[1]
            and str(existing.get("model") or existing.get("actual_model") or "") == key[2]
        ):
            return
    steps.append({
        "agent_id": agent_id,
        "agent_name": agent_name,
        "role": str(step.get("role") or step.get("title") or "")[:120],
        "title": str(step.get("title") or step.get("role") or "")[:120],
        "model": model,
        "actual_model": str(step.get("actual_model") or model)[:180],
        "provider": str(step.get("provider") or "")[:80],
        "purpose": str(step.get("purpose") or "")[:120],
    })


def _record_usage(row: Dict[str, Any]) -> None:
    context = dict(_USAGE_CONTEXT.get() or {})
    registry = _registry()
    registry.record_usage({**row, **context})
    # A call through somebody else's shared connection is also written to the
    # sharing ledger, naming both people. Accounting above already succeeded
    # and must never be undone by the second write.
    try:
        from ..ai_control_center import model_sharing
        grant = getattr(registry, "shared_grant", None) if registry is not agent_registry else None
        if registry is agent_registry or grant is not None:
            model_sharing.observe(row, context, grant=grant)
    except Exception:
        pass
    steps = _PARTICIPATION_STEPS.get()
    if isinstance(steps, list):
        note_participation({
            "agent_id": row.get("agent_id"),
            "agent_name": row.get("agent_name"),
            "role": row.get("request_role") or row.get("role"),
            "title": row.get("request_role") or row.get("role"),
            "model": row.get("actual_model") or row.get("model"),
            "actual_model": row.get("actual_model") or row.get("model"),
            "provider": row.get("provider"),
            "purpose": row.get("purpose"),
        })


class UniversalLLMError(RuntimeError):
    """Safe-to-display provider/client error."""


class BudgetExceeded(UniversalLLMError):
    """The request was blocked before transmission by a hard budget gate."""


class ProviderResponseError(UniversalLLMError):
    """A provider replied and billed usage, but did not return usable content."""

    def __init__(self, message: str, usage: Dict[str, Any]):
        super().__init__(message)
        self.usage = dict(usage or {})


class _ProductionUsageStorageUnavailable(UniversalLLMError):
    """Durable usage could not be written after an external provider call."""


def _production_budget_scope() -> Optional[Dict[str, Any]]:
    from .. import runtime_env
    from ..production_storage import Scope

    if not (runtime_env.is_production() and runtime_env.environment_explicit()):
        return None
    context = dict(_USAGE_CONTEXT.get() or {})
    workspace_id = str(context.get("workspace_id") or "").strip()
    try:
        user_id = int(context.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if not workspace_id or user_id <= 0:
        raise BudgetExceeded("Production AI request requires a user and workspace scope.")
    try:
        scope = Scope.workspace_scope(workspace_id)
    except ValueError as exc:
        raise BudgetExceeded("Production AI request requires a valid workspace scope.") from exc
    return {"workspace_id": scope.workspace_id, "user_id": user_id}


def require_valid_production_scope() -> Optional[Dict[str, Any]]:
    """Validate the active usage scope before a background caller invokes AI.

    Development returns ``None``. Explicit Production returns the normalized
    user/workspace pair or raises before provider traffic can begin.
    """
    return _production_budget_scope()


def _record_production_usage(
    request_id: str,
    agent: Dict[str, Any],
    *,
    request_role: str,
    purpose: str,
    status: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    prompt_sha256: str,
    scope: Optional[Dict[str, Any]],
) -> bool:
    if scope is None:
        return True
    from .. import ai_budgets

    try:
        result = ai_budgets.record_usage(
            request_id, scope["workspace_id"], scope["user_id"],
            str(agent.get("provider") or ""), str(agent.get("model") or ""),
            str(request_role or agent.get("role") or "general"),
            str(purpose or "agent_request"), status,
            max(0, int(input_tokens)), max(0, int(output_tokens)),
            max(0.0, float(cost_usd)), prompt_sha256,
            document={
                "agent_id": str(agent.get("id") or ""),
                "endpoint_type": str(agent.get("endpoint_type") or ""),
            },
        )
    except Exception:
        return False
    return bool(result.get("ok"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_error(error: BaseException, secret: str = "") -> str:
    text = str(error or "Ошибка AI provider").strip() or "Ошибка AI provider"
    if secret:
        text = text.replace(secret, "[скрыто]")
    text = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [скрыто]", text, flags=re.I)
    text = re.sub(r"([?&](?:key|api_key)=)[^&\s]+", r"\1[скрыто]", text, flags=re.I)
    return text[:700]


def _request_json(
    url: str,
    *,
    method: str = "POST",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = llm_timeouts.ANALYSIS,
    secret: str = "",
) -> Dict[str, Any]:
    if _REGISTRY_CONTEXT.get() is not None:
        from ..ai_control_center.model_transport import PrivateTransportError, request_json
        try:
            return request_json(url, method=method, payload=payload, headers=headers, timeout=timeout)
        except PrivateTransportError as exc:
            raise UniversalLLMError(str(exc)) from None
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            detail_raw = exc.read().decode("utf-8", errors="replace")
            detail_doc = json.loads(detail_raw)
            detail = detail_doc.get("error") if isinstance(detail_doc, dict) else detail_raw
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("code") or str(detail)
        except Exception:
            detail = f"HTTP {exc.code}"
        raise UniversalLLMError(_safe_error(RuntimeError(f"Provider отклонил запрос (HTTP {exc.code}): {detail}"), secret)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UniversalLLMError(_safe_error(RuntimeError(f"Provider недоступен: {exc}"), secret)) from None
    try:
        doc = json.loads(raw)
    except ValueError:
        raise UniversalLLMError("Provider вернул некорректный JSON.") from None
    if not isinstance(doc, dict):
        raise UniversalLLMError("Provider вернул неожиданный формат ответа.")
    return doc


def _headers(agent: Dict[str, Any], api_key: str) -> Dict[str, str]:
    auth = str(agent.get("auth_type") or "bearer")
    if agent.get("provider") == "azure_foundry" or auth == "api-key":
        return {"api-key": api_key}
    if auth == "x-api-key":
        return {"x-api-key": api_key}
    if auth == "x-goog-api-key":
        return {"x-goog-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _join(base: str, suffix: str) -> str:
    return base.rstrip("/") + "/" + suffix.lstrip("/")


def _endpoint(agent: Dict[str, Any]) -> str:
    base = str(agent.get("base_url") or "").strip().rstrip("/")
    kind = agent_registry.infer_endpoint_type(
        str(agent.get("provider") or ""), str(agent.get("model") or ""), base
    )
    route = "chat/completions" if kind == "chat" else "embeddings"
    if (_REGISTRY_CONTEXT.get() is not None and kind == "chat"
            and urllib.parse.urlsplit(base).path.endswith("/responses")):
        return base  # explicit private compatible endpoint; no global change
    provider = str(agent.get("provider") or "")
    if provider == "gemini":
        operation = "generateContent" if kind == "chat" else "embedContent"
        return _join(base, f"models/{urllib.parse.quote(str(agent.get('model') or ''), safe='')}:{operation}")
    if provider == "azure_foundry":
        parsed = urllib.parse.urlsplit(base)
        path = parsed.path.rstrip("/")
        if path.endswith(("/responses", "/chat/completions", "/embeddings")):
            return base
        if "/openai/deployments/" in path:
            path = f"{path}/{route}"
            query = parsed.query or urllib.parse.urlencode({
                "api-version": str(agent.get("api_version") or "2024-10-21")
            })
            return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))
        if path.endswith("/openai/v1") or "/openai/v1/" in path:
            path = path if path.endswith(f"/{route}") else f"{path}/{route}"
            return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))
        path = f"{path}/openai/v1/{route}"
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))
    if urllib.parse.urlsplit(base).path.rstrip("/").endswith(f"/{route}"):
        return base
    return _join(base, route)


def _uses_responses_api(url: str) -> bool:
    return urllib.parse.urlsplit(url).path.rstrip("/").endswith("/responses")


def _estimated_input_tokens(prompt: str, system_prompt: str = "") -> int:
    # One token per UTF-8 byte is intentionally conservative.
    return max(1, len(prompt.encode("utf-8")) + len(system_prompt.encode("utf-8")) + 64)


def _response_cache_allowed(purpose: str, mode: str) -> bool:
    normalized = str(mode or "auto").strip().lower()
    if normalized == "off":
        return False
    if normalized in {"on", "read_write"}:
        return True
    value = str(purpose or "").lower()
    return any(marker in value for marker in (
        "analysis", "audit", "review", "qa", "benchmark", "backtest_committee",
    )) and not any(marker in value for marker in (
        "connection", "generation", "mutation", "news", "orchestrator_chat",
    ))


def _cost(agent: Dict[str, Any], input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    cached = max(0, min(int(input_tokens), int(cached_tokens)))
    uncached = max(0, int(input_tokens) - cached)
    cached_rate = agent.get("cached_input_price_usd_per_m")
    if cached_rate is None:
        uncached += cached
        cached = 0
        cached_rate = 0.0
    return (
        uncached * float(agent.get("input_price_usd_per_m") or 0)
        + cached * float(cached_rate or 0)
        + max(0, int(output_tokens)) * float(agent.get("output_price_usd_per_m") or 0)
    ) / 1_000_000


def estimate_request_cost(agent_id: str, prompt: str, *, system_prompt: str = "", max_output_tokens: int = 256) -> Dict[str, Any]:
    agent = _registry().get_agent(agent_id)
    input_tokens = _estimated_input_tokens(prompt, system_prompt)
    output_tokens = 0 if agent.get("endpoint_type") == "embeddings" else max(1, min(int(max_output_tokens), 16_384))
    return {
        "estimated_input_tokens": input_tokens,
        "max_output_tokens": output_tokens,
        "estimated_max_cost_usd": round(_cost(agent, input_tokens, output_tokens), 8),
    }


def _reserve(agent: Dict[str, Any], estimate: float, *, allow_disabled: bool) -> str:
    agent_id = str(agent["id"])
    if not allow_disabled and not agent.get("enabled"):
        raise BudgetExceeded("Агент выключен.")
    if not agent.get("key_configured"):
        raise BudgetExceeded("API-ключ агента не настроен.")
    if estimate > agent_registry.MAX_SINGLE_CALL_USD + 1e-12:
        _registry().auto_disable(agent_id, "single_call_budget_exceeded")
        raise BudgetExceeded(f"Оценка запроса превышает hard cap ${agent_registry.MAX_SINGLE_CALL_USD:.2f} на вызов.")
    with _BUDGET_LOCK:
        reserved_day = sum(float(item["cost"]) for item in _RESERVATIONS.values() if item["agent_id"] == agent_id)
        peer_ids = {
            str(row.get("id") or "") for row in _registry().list_agents()
            if str(row.get("provider") or "") == str(agent.get("provider") or "")
            and str(row.get("account_name") or "") == str(agent.get("account_name") or "")
        }
        reserved_account = sum(
            float(item["cost"]) for item in _RESERVATIONS.values()
            if str(item.get("agent_id") or "") in peer_ids
        )
        daily_limit = float(agent.get("daily_budget_usd") or 0)
        monthly_limit = float(agent.get("monthly_budget_usd") or 0)
        if daily_limit > 0 and float(agent.get("spend_today_usd") or 0) + reserved_day + estimate > daily_limit + 1e-12:
            _registry().auto_disable(agent_id, "daily_budget_exceeded")
            raise BudgetExceeded("Дневной бюджет агента исчерпан; агент автоматически отключён.")
        if monthly_limit > 0 and float(agent.get("account_spend_month_usd") or 0) + reserved_account + estimate > monthly_limit + 1e-12:
            _registry().auto_disable(agent_id, "monthly_budget_exceeded")
            raise BudgetExceeded("Месячный бюджет агента исчерпан; агент автоматически отключён.")
        credit = agent.get("credit_remaining_estimated_usd")
        if credit is not None and float(credit) < reserved_day + estimate - 1e-12:
            _registry().auto_disable(agent_id, "credit_exhausted")
            raise BudgetExceeded("Расчётный остаток гранта/кредита исчерпан; агент автоматически отключён.")
        reservation_id = uuid.uuid4().hex
        _RESERVATIONS[reservation_id] = {"agent_id": agent_id, "cost": estimate}
        return reservation_id


def _release(reservation_id: str) -> None:
    with _BUDGET_LOCK:
        _RESERVATIONS.pop(reservation_id, None)


def active_requests() -> List[Dict[str, Any]]:
    """Return sanitized in-flight request metadata for local monitoring."""
    with _BUDGET_LOCK:
        return [
            {key: value for key, value in row.items() if key != "cost"}
            for row in _RESERVATIONS.values()
            if row.get("started_at_utc")
        ]


def _openai_compatible(
    agent: Dict[str, Any], api_key: str, prompt: str, system_prompt: str,
    max_output_tokens: int, timeout: int, *, request_role: str = "", purpose: str = "",
) -> Tuple[str, Dict[str, Any]]:
    kind = agent_registry.infer_endpoint_type(
        str(agent.get("provider") or ""), str(agent.get("model") or ""), str(agent.get("base_url") or "")
    )
    endpoint = _endpoint(agent)
    if kind == "embeddings":
        payload: Dict[str, Any] = {"model": agent["model"], "input": prompt}
        if "/openai/deployments/" in urllib.parse.urlsplit(endpoint).path:
            payload.pop("model", None)
    elif _uses_responses_api(endpoint):
        payload = {"model": agent["model"], "input": prompt, "max_output_tokens": max_output_tokens}
        if system_prompt:
            payload["instructions"] = system_prompt
        if str(agent.get("model") or "").lower().startswith("gpt-5"):
            payload["reasoning"] = {"effort": "minimal"}
            payload["text"] = {"verbosity": "low"}
    else:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": agent["model"], "messages": messages, "temperature": 0.0, "stream": False}
        token_field = "max_completion_tokens" if agent.get("provider") in {"openai", "azure_foundry"} else "max_tokens"
        payload[token_field] = max_output_tokens
        if agent.get("provider") == "zai":
            # GLM enables dynamic thinking by default. Short service contracts
            # can otherwise consume the output allowance in reasoning_content
            # and return an empty visible answer.
            payload["thinking"] = {"type": "disabled"}
        if agent.get("provider") == "deepseek":
            critical_roles = {"chief_agent", "orchestrator", "final_judge", "risk_manager", "overfit_detector"}
            thinking = request_role in critical_roles and purpose != "connection_test"
            payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
            payload["user_id"] = "nt-analyzer"
            if thinking:
                payload.pop("temperature", None)
                payload["reasoning_effort"] = "max"
    if agent.get("provider") == "openai" and system_prompt:
        digest = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:24]
        payload["prompt_cache_key"] = f"nt-analyzer-{digest}"
    doc = _request_json(
        endpoint, payload=payload, headers=_headers(agent, api_key),
        timeout=timeout, secret=api_key,
    )
    raw_usage = doc.get("usage") if isinstance(doc.get("usage"), dict) else {}
    details = raw_usage.get("prompt_tokens_details") if isinstance(raw_usage.get("prompt_tokens_details"), dict) else {}
    usage = {
        "input_tokens": int(raw_usage.get("prompt_tokens") or raw_usage.get("input_tokens") or 0),
        "cached_input_tokens": int(details.get("cached_tokens") or raw_usage.get("prompt_cache_hit_tokens") or 0),
        "cache_miss_tokens": int(raw_usage.get("prompt_cache_miss_tokens") or 0),
        "output_tokens": int(raw_usage.get("completion_tokens") or raw_usage.get("output_tokens") or 0),
        "actual_model": str(doc.get("model") or agent.get("model") or ""),
    }
    if kind == "embeddings":
        try:
            dimensions = len(doc["data"][0]["embedding"])
        except (KeyError, IndexError, TypeError):
            raise UniversalLLMError("Provider не вернул embedding vector.") from None
        usage["dimensions"] = dimensions
        return f"Embedding получен: {dimensions} dimensions.", usage
    if _uses_responses_api(endpoint):
        content = doc.get("output_text")
        if not content:
            content = "".join(
                str(part.get("text") or "")
                for item in (doc.get("output") or []) if isinstance(item, dict)
                for part in (item.get("content") or []) if isinstance(part, dict)
                and str(part.get("type") or "") in {"output_text", "text"}
            )
    else:
        try:
            content = doc["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise UniversalLLMError("Provider не вернул chat response.") from None
    if isinstance(content, list):
        content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    text = str(content or "").strip()
    # Capture the provider's native chain-of-thought when it is returned
    # alongside a visible answer. This is already generated and billed, so
    # surfacing it costs nothing extra. It is kept out of usage logs (the log
    # row copies only explicit numeric fields) and is used by the app chat to
    # show a live "thinking" block. Telegram never receives it.
    try:
        reasoning_text = str(doc["choices"][0]["message"].get("reasoning_content") or "")
    except (KeyError, IndexError, TypeError):
        reasoning_text = ""
    if reasoning_text:
        usage["reasoning_content"] = reasoning_text[:20000]
    if not text and _uses_responses_api(endpoint) and doc.get("incomplete_details"):
        reason = doc.get("incomplete_details")
        raise UniversalLLMError(f"Provider не завершил response: {reason}") from None
    if not text:
        reasoning = ""
        try:
            reasoning = str(doc["choices"][0]["message"].get("reasoning_content") or "")
        except (KeyError, IndexError, TypeError):
            pass
        if (reasoning and agent.get("provider") == "deepseek" and _REGISTRY_CONTEXT.get() is None
                and _ALLOW_HIDDEN_RETRIES.get()):
            # Some DeepSeek gateways consume the complete allowance in hidden
            # reasoning and return no final answer. Retry once in concise mode;
            # both attempts remain included in usage/cost accounting.
            retry_payload = dict(payload)
            retry_payload["thinking"] = {"type": "disabled"}
            retry_payload.pop("reasoning_effort", None)
            retry_doc = _request_json(
                endpoint, payload=retry_payload, headers=_headers(agent, api_key),
                timeout=timeout, secret=api_key,
            )
            retry_raw = retry_doc.get("usage") if isinstance(retry_doc.get("usage"), dict) else {}
            retry_details = retry_raw.get("prompt_tokens_details") if isinstance(retry_raw.get("prompt_tokens_details"), dict) else {}
            usage["input_tokens"] += int(retry_raw.get("prompt_tokens") or retry_raw.get("input_tokens") or 0)
            usage["cached_input_tokens"] += int(retry_details.get("cached_tokens") or retry_raw.get("prompt_cache_hit_tokens") or 0)
            usage["cache_miss_tokens"] += int(retry_raw.get("prompt_cache_miss_tokens") or 0)
            usage["output_tokens"] += int(retry_raw.get("completion_tokens") or retry_raw.get("output_tokens") or 0)
            usage["actual_model"] = str(retry_doc.get("model") or usage.get("actual_model") or agent.get("model") or "")
            try:
                retry_content = retry_doc["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                retry_content = ""
            if isinstance(retry_content, list):
                retry_content = "".join(
                    str(item.get("text") or "") for item in retry_content if isinstance(item, dict)
                )
            text = str(retry_content or "").strip()
            if text:
                return text, usage
        note = (
            "Provider израсходовал output allowance на reasoning и не вернул финальный ответ; "
            "увеличьте max_output_tokens."
            if reasoning else "Provider вернул пустой chat response."
        )
        raise ProviderResponseError(note, usage)
    return text, usage


def _request_stream(
    url: str,
    *,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = llm_timeouts.ANALYSIS,
    secret: str = "",
):
    """Yield raw SSE lines from an OpenAI-compatible streaming chat endpoint.

    The provider bills exactly one request regardless of transport; streaming
    only changes *when* the already-generated tokens arrive.
    """
    if _REGISTRY_CONTEXT.get() is not None:
        raise UniversalLLMError("Private model streaming is not supported.")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            detail_raw = exc.read().decode("utf-8", errors="replace")
            detail_doc = json.loads(detail_raw)
            detail = detail_doc.get("error") if isinstance(detail_doc, dict) else detail_raw
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("code") or str(detail)
        except Exception:
            detail = f"HTTP {exc.code}"
        raise UniversalLLMError(_safe_error(RuntimeError(f"Provider отклонил запрос (HTTP {exc.code}): {detail}"), secret)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UniversalLLMError(_safe_error(RuntimeError(f"Provider недоступен: {exc}"), secret)) from None
    try:
        with response:
            for raw in response:
                yield raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UniversalLLMError(_safe_error(RuntimeError(f"Provider прервал поток: {exc}"), secret)) from None


def _openai_compatible_stream(
    agent: Dict[str, Any], api_key: str, prompt: str, system_prompt: str,
    max_output_tokens: int, timeout: int, *, request_role: str = "", purpose: str = "",
    on_reasoning: Optional[Callable[[str], None]] = None,
    on_content: Optional[Callable[[str], None]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Streaming variant of :func:`_openai_compatible` for chat endpoints.

    Separates the provider's native ``reasoning_content`` (thinking) deltas from
    visible ``content`` deltas and forwards each to the supplied callbacks so the
    app chat can render a live "thinking" block. Usage/cost accounting matches
    the non-streaming path (a single billed request). Only used when a callback
    is provided; every other caller keeps the synchronous transport untouched.
    """
    endpoint = _endpoint(agent)
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload: Dict[str, Any] = {
        "model": agent["model"], "messages": messages, "temperature": 0.0,
        "stream": True, "stream_options": {"include_usage": True},
    }
    token_field = "max_completion_tokens" if agent.get("provider") in {"openai", "azure_foundry"} else "max_tokens"
    payload[token_field] = max_output_tokens
    if agent.get("provider") == "zai":
        payload["thinking"] = {"type": "disabled"}
    if agent.get("provider") == "deepseek":
        critical_roles = {"chief_agent", "orchestrator", "final_judge", "risk_manager", "overfit_detector"}
        thinking = request_role in critical_roles and purpose != "connection_test"
        payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
        payload["user_id"] = "nt-analyzer"
        if thinking:
            payload.pop("temperature", None)
            payload["reasoning_effort"] = "max"
    if agent.get("provider") == "openai" and system_prompt:
        digest = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:24]
        payload["prompt_cache_key"] = f"nt-analyzer-{digest}"

    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    usage: Dict[str, Any] = {
        "input_tokens": 0, "cached_input_tokens": 0, "cache_miss_tokens": 0,
        "output_tokens": 0, "actual_model": str(agent.get("model") or ""),
    }
    for raw_line in _request_stream(
        endpoint, payload=payload, headers=_headers(agent, api_key),
        timeout=timeout, secret=api_key,
    ):
        line = raw_line.strip()
        if not line or not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except ValueError:
            continue
        if not isinstance(chunk, dict):
            continue
        chunk_usage = chunk.get("usage")
        if isinstance(chunk_usage, dict):
            cdetails = chunk_usage.get("prompt_tokens_details") if isinstance(chunk_usage.get("prompt_tokens_details"), dict) else {}
            usage["input_tokens"] = int(chunk_usage.get("prompt_tokens") or chunk_usage.get("input_tokens") or usage["input_tokens"])
            usage["cached_input_tokens"] = int(cdetails.get("cached_tokens") or chunk_usage.get("prompt_cache_hit_tokens") or usage["cached_input_tokens"])
            usage["cache_miss_tokens"] = int(chunk_usage.get("prompt_cache_miss_tokens") or usage["cache_miss_tokens"])
            usage["output_tokens"] = int(chunk_usage.get("completion_tokens") or chunk_usage.get("output_tokens") or usage["output_tokens"])
        if chunk.get("model"):
            usage["actual_model"] = str(chunk.get("model"))
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first = choices[0] if isinstance(choices[0], dict) else {}
        delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
        piece_reasoning = delta.get("reasoning_content")
        if piece_reasoning:
            reasoning_parts.append(str(piece_reasoning))
            if on_reasoning:
                try:
                    on_reasoning(str(piece_reasoning))
                except Exception:
                    pass
        piece_content = delta.get("content")
        if piece_content:
            content_parts.append(str(piece_content))
            if on_content:
                try:
                    on_content(str(piece_content))
                except Exception:
                    pass
    reasoning_text = "".join(reasoning_parts)
    if reasoning_text:
        usage["reasoning_content"] = reasoning_text[:20000]
    text = "".join(content_parts).strip()
    if not text:
        if reasoning_text and agent.get("provider") == "deepseek":
            # Streaming spent the allowance on reasoning with no visible answer.
            # Retry once in concise, non-streaming mode (same guard the sync
            # path uses); both attempts stay in usage/cost accounting.
            retry_text, retry_usage = _openai_compatible(
                agent, api_key, prompt, system_prompt, max_output_tokens, timeout,
                request_role="", purpose="connection_test",
            )
            for field in ("input_tokens", "cached_input_tokens", "cache_miss_tokens", "output_tokens"):
                usage[field] = int(usage.get(field) or 0) + int(retry_usage.get(field) or 0)
            usage["actual_model"] = str(retry_usage.get("actual_model") or usage.get("actual_model") or "")
            if retry_text:
                return retry_text, usage
        note = (
            "Provider израсходовал output allowance на reasoning и не вернул финальный ответ; "
            "увеличьте max_output_tokens."
            if reasoning_text else "Provider вернул пустой chat response."
        )
        raise ProviderResponseError(note, usage)
    return text, usage


def _gemini(
    agent: Dict[str, Any], api_key: str, prompt: str, system_prompt: str,
    max_output_tokens: int, timeout: int,
) -> Tuple[str, Dict[str, Any]]:
    kind = agent_registry.infer_endpoint_type("gemini", str(agent.get("model") or ""), str(agent.get("base_url") or ""))
    if kind == "embeddings":
        payload: Dict[str, Any] = {"content": {"parts": [{"text": prompt}]}}
    else:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": max_output_tokens,
                # Gemini 2.5 Flash enables dynamic thinking by default. For
                # short, structured agent contracts it consumed nearly the
                # entire output allowance and truncated the visible JSON.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    doc = _request_json(
        _endpoint(agent), payload=payload, headers=_headers(agent, api_key),
        timeout=timeout, secret=api_key,
    )
    raw_usage = doc.get("usageMetadata") if isinstance(doc.get("usageMetadata"), dict) else {}
    usage = {
        "input_tokens": int(raw_usage.get("promptTokenCount") or 0),
        "cached_input_tokens": int(raw_usage.get("cachedContentTokenCount") or 0),
        "output_tokens": int(raw_usage.get("candidatesTokenCount") or 0) + int(raw_usage.get("thoughtsTokenCount") or 0),
        "actual_model": str(doc.get("modelVersion") or agent.get("model") or ""),
    }
    if kind == "embeddings":
        try:
            dimensions = len(doc["embedding"]["values"])
        except (KeyError, TypeError):
            raise UniversalLLMError("Gemini не вернул embedding vector.") from None
        usage["dimensions"] = dimensions
        return f"Embedding получен: {dimensions} dimensions.", usage
    try:
        parts = doc["candidates"][0]["content"]["parts"]
        content = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
    except (KeyError, IndexError, TypeError):
        content = ""
    if not content:
        raise UniversalLLMError("Gemini не вернул текстовый response.")
    return content, usage


def invoke_agent(
    agent_id: str,
    prompt: str,
    *,
    system_prompt: str = "",
    max_output_tokens: int = 256,
    timeout: int = llm_timeouts.ANALYSIS,
    allow_disabled: bool = False,
    request_role: str = "",
    purpose: str = "",
    cache_mode: str = "auto",
    on_reasoning: Optional[Callable[[str], None]] = None,
    on_content: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt or len(clean_prompt) > 20_000:
        raise UniversalLLMError("Test prompt обязателен и должен быть короче 20 000 символов.")
    agent = _registry().get_agent(agent_id)
    if _REGISTRY_CONTEXT.get() is None:
        # The global registry holds the owner's own connections. A request made
        # for anybody else may use only the ones the owner has shared.
        from ..ai_control_center import model_sharing
        if not model_sharing.registry_allowed(agent_id, dict(_USAGE_CONTEXT.get() or {})):
            raise UniversalLLMError("Эта модель не открыта для общего доступа.")
    resolved_type = agent_registry.infer_endpoint_type(
        str(agent.get("provider") or ""), str(agent.get("model") or ""), str(agent.get("base_url") or "")
    )
    if resolved_type == "embeddings":
        max_output = 0
    else:
        # DeepSeek critical reasoning includes hidden thinking tokens in the
        # completion allowance. A 4096 cap repeatedly cut otherwise valid
        # executive answers mid-sentence, so critical DeepSeek calls get the
        # provider-supported 8192-token envelope. Other routine calls retain
        # the smaller bound.
        critical_deepseek = (
            str(agent.get("provider") or "") == "deepseek"
            and str(request_role or "") in {
                "chief_agent", "orchestrator", "final_judge",
                "risk_manager", "overfit_detector",
            }
        )
        cap = 8192 if critical_deepseek else 4096
        max_output = max(1, min(int(max_output_tokens), cap))
    estimate_info = estimate_request_cost(agent_id, clean_prompt, system_prompt=system_prompt, max_output_tokens=max_output)
    request_id = f"REQ-{uuid.uuid4().hex[:16].upper()}"
    started = time.time()
    production_scope = _production_budget_scope()
    prompt_sha256 = hashlib.sha256(
        (system_prompt + "\n" + clean_prompt).encode("utf-8")
    ).hexdigest()
    cache_workspace_id = (
        production_scope["workspace_id"]
        if production_scope is not None
        else str((_USAGE_CONTEXT.get() or {}).get("workspace_id") or "")
    )
    cache_key = ""
    if _REGISTRY_CONTEXT.get() is None and resolved_type == "chat" and _response_cache_allowed(purpose, cache_mode):
        cache_key = response_cache.make_key(
            agent_id=agent_id, model=str(agent.get("model") or ""),
            system_prompt=system_prompt, prompt=clean_prompt,
            max_output_tokens=max_output,
            workspace_id=cache_workspace_id,
        )
        cached_result = response_cache.get(cache_key)
        if cached_result:
            saved_input = int(
                cached_result.get("source_input_tokens")
                or cached_result.get("input_tokens")
                or estimate_info["estimated_input_tokens"]
            )
            saved_output = int(
                cached_result.get("source_output_tokens")
                or cached_result.get("output_tokens")
                or 0
            )
            actual_model = str(cached_result.get("actual_model") or agent.get("model") or "")
            row = {
                "timestamp_utc": _now(), "request_id": request_id,
                "agent_id": agent_id, "agent_name": agent["name"],
                "provider": agent["provider"], "account_name": agent.get("account_name"),
                "billing_mode": agent.get("billing_mode"), "rotation_group": agent.get("rotation_group"),
                "model": agent["model"], "actual_model": actual_model,
                "role": agent["role"], "request_role": str(request_role or agent["role"])[:80],
                "purpose": str(purpose or "agent_request")[:120], "endpoint_type": resolved_type,
                "input_tokens": 0, "cached_input_tokens": 0, "cache_miss_tokens": 0,
                "application_cache_hit": True,
                "application_cache_saved_input_tokens": saved_input,
                "application_cache_saved_output_tokens": saved_output,
                "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
                "cost_known": True, "cost_estimated": False,
                "pricing_basis": "Process-local exact response cache",
                "status": "success", "elapsed_sec": round(time.time() - started, 3), "error": None,
            }
            _record_usage(row)
            if not _record_production_usage(
                request_id, agent, request_role=request_role, purpose=purpose,
                status="cache_hit", input_tokens=0, output_tokens=0, cost_usd=0.0,
                prompt_sha256=prompt_sha256, scope=production_scope,
            ):
                raise BudgetExceeded("Production AI usage storage is unavailable.")
            return {
                "ok": True, "status": "success", "request_id": request_id,
                "agent_id": agent_id, "agent_name": agent["name"],
                "provider": agent["provider"], "model": agent["model"], "actual_model": actual_model,
                "response": str(cached_result.get("response") or "")[:30000],
                "input_tokens": 0, "cached_input_tokens": 0, "cache_miss_tokens": 0,
                "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
                "application_cache_hit": True,
                "application_cache_saved_input_tokens": saved_input,
                "application_cache_saved_output_tokens": saved_output,
                "elapsed_sec": row["elapsed_sec"],
            }
    estimate = float(estimate_info["estimated_max_cost_usd"])
    reservation_id = _reserve(agent, estimate, allow_disabled=allow_disabled)
    durable_reserved = False
    if production_scope is not None:
        from .. import ai_budgets

        try:
            durable_reservation = ai_budgets.reserve(
                request_id, production_scope["workspace_id"], production_scope["user_id"],
                str(agent.get("provider") or ""), str(agent.get("model") or ""),
                str(request_role or agent.get("role") or "general"), estimate,
                prompt_sha256,
            )
        except Exception:
            durable_reservation = {"ok": False, "code": "storage_unavailable"}
        if not durable_reservation.get("ok"):
            _release(reservation_id)
            recorded = _record_production_usage(
                request_id, agent, request_role=request_role, purpose=purpose,
                status="blocked", input_tokens=0, output_tokens=0, cost_usd=0.0,
                prompt_sha256=prompt_sha256, scope=production_scope,
            )
            code = str(durable_reservation.get("code") or "storage_unavailable")
            if not recorded:
                code = "storage_unavailable"
            raise BudgetExceeded("Production AI budget denied: " + code)
        durable_reserved = True
    with _BUDGET_LOCK:
        _RESERVATIONS[reservation_id].update({
            "request_id": request_id,
            "agent_id": agent_id,
            "agent_name": agent.get("name"),
            "account_name": agent.get("account_name"),
            "provider": agent.get("provider"),
            "model": agent.get("model"),
            "request_role": str(request_role or agent.get("role") or "general")[:80],
            "purpose": str(purpose or "agent_request")[:120],
            "started_at_utc": _now(),
        })
    api_key = ""
    usage: Dict[str, Any] = {}
    durable_usage_recorded = False
    provider_attempted = False
    try:
        api_key = _registry().get_api_key(agent_id)
        # Stream only when a caller explicitly wants live reasoning/content
        # (the app chat SSE endpoint). Every other caller — Telegram, missions,
        # background jobs — keeps the untouched synchronous transport.
        want_stream = (
            bool(on_reasoning or on_content)
            and agent.get("provider") != "gemini"
            and resolved_type == "chat"
            and not _uses_responses_api(_endpoint(agent))
        )
        provider_attempted = True
        if agent.get("provider") == "gemini":
            response_text, usage = _gemini(agent, api_key, clean_prompt, system_prompt, max_output, timeout)
        elif want_stream:
            response_text, usage = _openai_compatible_stream(
                agent, api_key, clean_prompt, system_prompt, max_output, timeout,
                request_role=str(request_role or agent.get("role") or "general"),
                purpose=str(purpose or "agent_request"),
                on_reasoning=on_reasoning, on_content=on_content,
            )
        else:
            response_text, usage = _openai_compatible(
                agent, api_key, clean_prompt, system_prompt, max_output, timeout,
                request_role=str(request_role or agent.get("role") or "general"),
                purpose=str(purpose or "agent_request"),
            )
        reasoning_out = str(usage.get("reasoning_content") or "")
        # Providers that return their full reasoning only at the end (no live
        # stream) still deliver it once so the chat can show the block.
        if reasoning_out and on_reasoning and not want_stream:
            try:
                on_reasoning(reasoning_out)
            except Exception:
                pass
        estimated_input = int(estimate_info["estimated_input_tokens"])
        reported_input = int(usage.get("input_tokens") or 0)
        reported_output = int(usage.get("output_tokens") or 0)
        input_tokens = reported_input or estimated_input
        output_tokens = reported_output or max_output
        cached_tokens = int(usage.get("cached_input_tokens") or 0) if reported_input else 0
        cost = _cost(agent, input_tokens, output_tokens, cached_tokens)
        pricing_status = str(agent.get("pricing_status") or "unpriced")
        actual_model = str(usage.get("actual_model") or agent["model"])
        row = {
            "timestamp_utc": _now(), "request_id": request_id,
            "agent_id": agent_id, "agent_name": agent["name"],
            "provider": agent["provider"], "account_name": agent.get("account_name"),
            "billing_mode": agent.get("billing_mode"), "rotation_group": agent.get("rotation_group"),
            "model": agent["model"], "actual_model": actual_model,
            "role": agent["role"], "request_role": str(request_role or agent["role"])[:80],
            "purpose": str(purpose or "agent_request")[:120], "endpoint_type": resolved_type,
            "input_tokens": input_tokens, "cached_input_tokens": cached_tokens,
            "cache_miss_tokens": int(usage.get("cache_miss_tokens") or max(0, input_tokens - cached_tokens)),
            "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost, 8), "cost_known": pricing_status != "unpriced",
            "cost_estimated": pricing_status == "estimated", "pricing_basis": agent.get("pricing_basis"),
            "status": "success",
            "elapsed_sec": round(time.time() - started, 3), "error": None,
        }
        _record_usage(row)
        durable_usage_recorded = _record_production_usage(
            request_id, agent, request_role=request_role, purpose=purpose,
            status="success", input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=row["cost_usd"], prompt_sha256=prompt_sha256,
            scope=production_scope,
        )
        if not durable_usage_recorded:
            raise _ProductionUsageStorageUnavailable()
        if cache_key:
            response_cache.set(cache_key, {
                "response": response_text, "actual_model": actual_model,
                "input_tokens": input_tokens, "output_tokens": output_tokens,
            })
        _registry().clear_cooldown(agent_id)
        fresh = _registry().get_agent(agent_id)
        if (
            (float(fresh.get("daily_budget_usd") or 0) > 0 and float(fresh.get("spend_today_usd") or 0) >= float(fresh.get("daily_budget_usd") or 0))
            or (float(fresh.get("monthly_budget_usd") or 0) > 0 and float(fresh.get("account_spend_month_usd") or 0) >= float(fresh.get("monthly_budget_usd") or 0))
            or (fresh.get("credit_remaining_estimated_usd") == 0 and agent.get("pricing_status") in {"free", "configured", "estimated"})
        ):
            _registry().auto_disable(agent_id, "budget_reached_after_request")
        return {
            "ok": True, "status": "success", "request_id": request_id,
            "agent_id": agent_id, "agent_name": agent["name"],
            "provider": agent["provider"], "model": agent["model"], "actual_model": actual_model,
            "response": response_text[:30000],
            "reasoning": reasoning_out[:20000],
            "dimensions": usage.get("dimensions"),
            "input_tokens": input_tokens, "cached_input_tokens": cached_tokens,
            "cache_miss_tokens": row["cache_miss_tokens"],
            "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
            "cost_usd": row["cost_usd"], "cost_estimated": row["cost_estimated"],
            "pricing_basis": row["pricing_basis"], "elapsed_sec": row["elapsed_sec"],
            "application_cache_hit": False,
        }
    except _ProductionUsageStorageUnavailable:
        raise UniversalLLMError("Production AI usage storage is unavailable.") from None
    except (UniversalLLMError, agent_registry.AgentRegistryError) as exc:
        error = _safe_error(exc, api_key)
        failure_usage = getattr(exc, "usage", {}) if isinstance(exc, ProviderResponseError) else {}
        input_tokens = int(
            failure_usage.get("input_tokens")
            or (estimate_info["estimated_input_tokens"] if provider_attempted else 0)
        )
        cached_tokens = int(failure_usage.get("cached_input_tokens") or 0)
        output_tokens = int(failure_usage.get("output_tokens") or 0)
        failure_cost = _cost(agent, input_tokens, output_tokens, cached_tokens)
        row = {
            "timestamp_utc": _now(), "request_id": request_id,
            "agent_id": agent_id, "agent_name": agent["name"],
            "provider": agent["provider"], "account_name": agent.get("account_name"),
            "billing_mode": agent.get("billing_mode"), "rotation_group": agent.get("rotation_group"),
            "model": agent["model"], "role": agent["role"],
            "request_role": str(request_role or agent["role"])[:80],
            "purpose": str(purpose or "agent_request")[:120], "endpoint_type": resolved_type,
            "input_tokens": input_tokens, "cached_input_tokens": cached_tokens,
            "cache_miss_tokens": int(failure_usage.get("cache_miss_tokens") or max(0, input_tokens - cached_tokens)),
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens, "cost_usd": round(failure_cost, 8),
            "cost_known": str(agent.get("pricing_status") or "unpriced") != "unpriced",
            "cost_estimated": agent.get("pricing_status") == "estimated",
            "pricing_basis": agent.get("pricing_basis"), "status": "error",
            "elapsed_sec": round(time.time() - started, 3), "error": error,
        }
        _record_usage(row)
        durable_usage_recorded = _record_production_usage(
            request_id, agent, request_role=request_role, purpose=purpose,
            status="error", input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=row["cost_usd"], prompt_sha256=prompt_sha256,
            scope=production_scope,
        )
        if production_scope is not None and not durable_usage_recorded:
            error = "Production AI usage storage is unavailable."
        raise UniversalLLMError(error) from None
    finally:
        _release(reservation_id)
        if production_scope is not None and durable_reserved and not durable_usage_recorded:
            try:
                from .. import ai_budgets
                ai_budgets.cancel_reservation(
                    request_id, production_scope["workspace_id"],
                )
            except Exception:
                pass


def test_connection(agent_id: str, prompt: str = "") -> Dict[str, Any]:
    test_prompt = str(prompt or "Reply with exactly: CONNECTION_OK").strip()[:1000]
    try:
        result = invoke_agent(
            agent_id, test_prompt,
            system_prompt="This is a connection test. Return a short response only.",
            max_output_tokens=128, timeout=llm_timeouts.CONNECTION_TEST, allow_disabled=True,
            request_role="connection_test", purpose="connection_test",
        )
        result["status"] = "connected"
        _registry().record_test(agent_id, result)
        return result
    except (UniversalLLMError, BudgetExceeded) as exc:
        result = {"ok": False, "status": "error", "error": str(exc)}
        _registry().record_test(agent_id, result)
        return result


def sync_credit_balance(agent_id: str) -> Dict[str, Any]:
    """Synchronize provider balance where a normal inference key supports it.

    Azure/OpenAI/Gemini billing requires separate billing/admin authorization,
    so those providers intentionally remain manual/local estimates.
    """
    if _REGISTRY_CONTEXT.get() is not None:
        raise UniversalLLMError("Private model balance synchronization is not supported.")
    agent = _registry().get_agent(agent_id, public=False)
    if agent.get("provider") != "openrouter":
        raise UniversalLLMError(
            "Автоматический balance API недоступен для этого provider; внесите фактический остаток из billing portal через Edit Agent."
        )
    api_key = _registry().get_api_key(agent_id)
    doc = _request_json(
        "https://openrouter.ai/api/v1/credits", method="GET",
        headers={"Authorization": f"Bearer {api_key}"}, timeout=30, secret=api_key,
    )
    data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
    total = float(data.get("total_credits") or 0)
    used = float(data.get("total_usage") or 0)
    return agent_registry.update_agent(agent_id, {
        "credit_total_usd": total,
        "credit_remaining_reported_usd": max(0.0, total - used),
        "credit_reported_at_utc": _now(),
    })
