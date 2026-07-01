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
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import agent_registry


_BUDGET_LOCK = threading.RLock()
_RESERVATIONS: Dict[str, Dict[str, Any]] = {}


class UniversalLLMError(RuntimeError):
    """Safe-to-display provider/client error."""


class BudgetExceeded(UniversalLLMError):
    """The request was blocked before transmission by a hard budget gate."""


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
    timeout: int = 90,
    secret: str = "",
) -> Dict[str, Any]:
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
    agent = agent_registry.get_agent(agent_id)
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
        agent_registry.auto_disable(agent_id, "single_call_budget_exceeded")
        raise BudgetExceeded(f"Оценка запроса превышает hard cap ${agent_registry.MAX_SINGLE_CALL_USD:.2f} на вызов.")
    with _BUDGET_LOCK:
        reserved_day = sum(float(item["cost"]) for item in _RESERVATIONS.values() if item["agent_id"] == agent_id)
        daily_limit = float(agent.get("daily_budget_usd") or 0)
        monthly_limit = float(agent.get("monthly_budget_usd") or 0)
        if daily_limit > 0 and float(agent.get("spend_today_usd") or 0) + reserved_day + estimate > daily_limit + 1e-12:
            agent_registry.auto_disable(agent_id, "daily_budget_exceeded")
            raise BudgetExceeded("Дневной бюджет агента исчерпан; агент автоматически отключён.")
        if monthly_limit > 0 and float(agent.get("spend_month_usd") or 0) + reserved_day + estimate > monthly_limit + 1e-12:
            agent_registry.auto_disable(agent_id, "monthly_budget_exceeded")
            raise BudgetExceeded("Месячный бюджет агента исчерпан; агент автоматически отключён.")
        credit = agent.get("credit_remaining_estimated_usd")
        if credit is not None and float(credit) < reserved_day + estimate - 1e-12:
            agent_registry.auto_disable(agent_id, "credit_exhausted")
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
    max_output_tokens: int, timeout: int,
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
    doc = _request_json(
        endpoint, payload=payload, headers=_headers(agent, api_key),
        timeout=timeout, secret=api_key,
    )
    raw_usage = doc.get("usage") if isinstance(doc.get("usage"), dict) else {}
    details = raw_usage.get("prompt_tokens_details") if isinstance(raw_usage.get("prompt_tokens_details"), dict) else {}
    usage = {
        "input_tokens": int(raw_usage.get("prompt_tokens") or raw_usage.get("input_tokens") or 0),
        "cached_input_tokens": int(details.get("cached_tokens") or raw_usage.get("prompt_cache_hit_tokens") or 0),
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
    if not text and _uses_responses_api(endpoint) and doc.get("incomplete_details"):
        reason = doc.get("incomplete_details")
        raise UniversalLLMError(f"Provider не завершил response: {reason}") from None
    if not text:
        raise UniversalLLMError("Provider вернул пустой chat response.")
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
    timeout: int = 90,
    allow_disabled: bool = False,
    request_role: str = "",
    purpose: str = "",
) -> Dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt or len(clean_prompt) > 20_000:
        raise UniversalLLMError("Test prompt обязателен и должен быть короче 20 000 символов.")
    agent = agent_registry.get_agent(agent_id)
    resolved_type = agent_registry.infer_endpoint_type(
        str(agent.get("provider") or ""), str(agent.get("model") or ""), str(agent.get("base_url") or "")
    )
    max_output = 0 if resolved_type == "embeddings" else max(1, min(int(max_output_tokens), 4096))
    estimate_info = estimate_request_cost(agent_id, clean_prompt, system_prompt=system_prompt, max_output_tokens=max_output)
    estimate = float(estimate_info["estimated_max_cost_usd"])
    reservation_id = _reserve(agent, estimate, allow_disabled=allow_disabled)
    request_id = f"REQ-{uuid.uuid4().hex[:16].upper()}"
    started = time.time()
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
    try:
        api_key = agent_registry.get_api_key(agent_id)
        if agent.get("provider") == "gemini":
            response_text, usage = _gemini(agent, api_key, clean_prompt, system_prompt, max_output, timeout)
        else:
            response_text, usage = _openai_compatible(agent, api_key, clean_prompt, system_prompt, max_output, timeout)
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
            "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost, 8), "cost_known": pricing_status != "unpriced",
            "cost_estimated": pricing_status == "estimated", "pricing_basis": agent.get("pricing_basis"),
            "status": "success",
            "elapsed_sec": round(time.time() - started, 3), "error": None,
        }
        agent_registry.record_usage(row)
        agent_registry.clear_cooldown(agent_id)
        fresh = agent_registry.get_agent(agent_id)
        if (
            (float(fresh.get("daily_budget_usd") or 0) > 0 and float(fresh.get("spend_today_usd") or 0) >= float(fresh.get("daily_budget_usd") or 0))
            or (float(fresh.get("monthly_budget_usd") or 0) > 0 and float(fresh.get("spend_month_usd") or 0) >= float(fresh.get("monthly_budget_usd") or 0))
            or (fresh.get("credit_remaining_estimated_usd") == 0 and agent.get("pricing_status") in {"free", "configured", "estimated"})
        ):
            agent_registry.auto_disable(agent_id, "budget_reached_after_request")
        return {
            "ok": True, "status": "success", "request_id": request_id,
            "agent_id": agent_id, "agent_name": agent["name"],
            "provider": agent["provider"], "model": agent["model"], "actual_model": actual_model,
            "response": response_text[:30000],
            "dimensions": usage.get("dimensions"),
            "input_tokens": input_tokens, "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
            "cost_usd": row["cost_usd"], "cost_estimated": row["cost_estimated"],
            "pricing_basis": row["pricing_basis"], "elapsed_sec": row["elapsed_sec"],
        }
    except (UniversalLLMError, agent_registry.AgentRegistryError) as exc:
        error = _safe_error(exc, api_key)
        row = {
            "timestamp_utc": _now(), "request_id": request_id,
            "agent_id": agent_id, "agent_name": agent["name"],
            "provider": agent["provider"], "account_name": agent.get("account_name"),
            "billing_mode": agent.get("billing_mode"), "rotation_group": agent.get("rotation_group"),
            "model": agent["model"], "role": agent["role"],
            "request_role": str(request_role or agent["role"])[:80],
            "purpose": str(purpose or "agent_request")[:120], "endpoint_type": resolved_type,
            "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "cost_usd": 0.0,
            "cost_known": str(agent.get("pricing_status") or "unpriced") != "unpriced",
            "cost_estimated": agent.get("pricing_status") == "estimated",
            "pricing_basis": agent.get("pricing_basis"), "status": "error",
            "elapsed_sec": round(time.time() - started, 3), "error": error,
        }
        agent_registry.record_usage(row)
        raise UniversalLLMError(error) from None
    finally:
        _release(reservation_id)


def test_connection(agent_id: str, prompt: str = "") -> Dict[str, Any]:
    test_prompt = str(prompt or "Reply with exactly: CONNECTION_OK").strip()[:1000]
    try:
        result = invoke_agent(
            agent_id, test_prompt,
            system_prompt="This is a connection test. Return a short response only.",
            max_output_tokens=512, timeout=45, allow_disabled=True,
        )
        result["status"] = "connected"
        agent_registry.record_test(agent_id, result)
        return result
    except (UniversalLLMError, BudgetExceeded) as exc:
        result = {"ok": False, "status": "error", "error": str(exc)}
        agent_registry.record_test(agent_id, result)
        return result


def sync_credit_balance(agent_id: str) -> Dict[str, Any]:
    """Synchronize provider balance where a normal inference key supports it.

    Azure/OpenAI/Gemini billing requires separate billing/admin authorization,
    so those providers intentionally remain manual/local estimates.
    """
    agent = agent_registry.get_agent(agent_id, public=False)
    if agent.get("provider") != "openrouter":
        raise UniversalLLMError(
            "Автоматический balance API недоступен для этого provider; внесите фактический остаток из billing portal через Edit Agent."
        )
    api_key = agent_registry.get_api_key(agent_id)
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
