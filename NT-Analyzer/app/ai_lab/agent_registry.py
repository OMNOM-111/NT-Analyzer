"""Persistent registry for user-configured external AI agents.

Metadata is kept in a gitignored JSON document.  API keys are stored separately
through Windows DPAPI.  Public functions return masks and configuration flags,
never plaintext credentials.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .. import secure_store
from . import paths
from .io_utils import append_jsonl, read_json, write_json_atomic


MAX_MONTHLY_BUDGET_USD = 20.0
MAX_DAILY_BUDGET_USD = 10.0
MAX_SINGLE_CALL_USD = 0.50
SCHEMA_VERSION = "1.1"
BILLING_MODES = {
    "credit": "Grant / prepaid credit",
    "free_tier": "Free tier",
    "payg": "Paid / pay as you go",
    "unknown": "Not classified",
}
MODEL_PRICING: Dict[tuple[str, str], Dict[str, Any]] = {
    ("deepseek", "deepseek-v4-flash"): {
        "input_price_usd_per_m": 0.14,
        "cached_input_price_usd_per_m": 0.0028,
        "output_price_usd_per_m": 0.28,
        "pricing_status": "configured",
        "pricing_basis": "Official DeepSeek API pricing (cache miss / cache hit / output)",
        "pricing_source_url": "https://api-docs.deepseek.com/quick_start/pricing",
    },
    ("deepseek", "deepseek-v4-pro"): {
        "input_price_usd_per_m": 0.435,
        "cached_input_price_usd_per_m": 0.003625,
        "output_price_usd_per_m": 0.87,
        "pricing_status": "configured",
        "pricing_basis": "Official DeepSeek API pricing (cache miss / cache hit / output)",
        "pricing_source_url": "https://api-docs.deepseek.com/quick_start/pricing",
    },
    ("azure_foundry", "gpt-5-mini"): {
        "input_price_usd_per_m": 0.25,
        "cached_input_price_usd_per_m": 0.025,
        "output_price_usd_per_m": 2.0,
        "pricing_status": "estimated",
        "pricing_basis": "OpenAI public reference; Azure invoice is authoritative",
        "pricing_source_url": "https://platform.openai.com/docs/models/gpt-5-mini",
    },
    ("azure_foundry", "text-embedding-3-small"): {
        "input_price_usd_per_m": 0.02,
        "cached_input_price_usd_per_m": None,
        "output_price_usd_per_m": 0.0,
        "pricing_status": "estimated",
        "pricing_basis": "OpenAI public reference; Azure invoice is authoritative",
        "pricing_source_url": "https://platform.openai.com/docs/models/text-embedding-3-small",
    },
    ("github_models", "openai/gpt-4.1"): {
        "input_price_usd_per_m": 2.0,
        "cached_input_price_usd_per_m": 0.5,
        "output_price_usd_per_m": 8.0,
        "pricing_status": "configured",
        "pricing_basis": "Official GitHub Models direct billing token-unit pricing",
        "pricing_source_url": "https://docs.github.com/en/billing/reference/models-multipliers-and-costs",
    },
    ("github_models", "openai/gpt-4.1-mini"): {
        "input_price_usd_per_m": 0.4,
        "cached_input_price_usd_per_m": 0.1,
        "output_price_usd_per_m": 1.6,
        "pricing_status": "configured",
        "pricing_basis": "Official GitHub Models direct billing token-unit pricing",
        "pricing_source_url": "https://docs.github.com/en/billing/reference/models-multipliers-and-costs",
    },
    ("github_models", "openai/gpt-4o-mini"): {
        "input_price_usd_per_m": 0.15,
        "cached_input_price_usd_per_m": 0.08,
        "output_price_usd_per_m": 0.6,
        "pricing_status": "configured",
        "pricing_basis": "Official GitHub Models direct billing token-unit pricing",
        "pricing_source_url": "https://docs.github.com/en/billing/reference/models-multipliers-and-costs",
    },
    ("github_models", "deepseek/deepseek-r1"): {
        "input_price_usd_per_m": 1.35,
        "cached_input_price_usd_per_m": None,
        "output_price_usd_per_m": 5.4,
        "pricing_status": "configured",
        "pricing_basis": "Official GitHub Models direct billing token-unit pricing",
        "pricing_source_url": "https://docs.github.com/en/billing/reference/models-multipliers-and-costs",
    },
    ("github_models", "microsoft/phi-4"): {
        "input_price_usd_per_m": 0.13,
        "cached_input_price_usd_per_m": None,
        "output_price_usd_per_m": 0.5,
        "pricing_status": "configured",
        "pricing_basis": "Official GitHub Models direct billing token-unit pricing",
        "pricing_source_url": "https://docs.github.com/en/billing/reference/models-multipliers-and-costs",
    },
    ("github_models", "meta/llama-3.3-70b-instruct"): {
        "input_price_usd_per_m": 0.71,
        "cached_input_price_usd_per_m": None,
        "output_price_usd_per_m": 0.71,
        "pricing_status": "configured",
        "pricing_basis": "Official GitHub Models direct billing token-unit pricing",
        "pricing_source_url": "https://docs.github.com/en/billing/reference/models-multipliers-and-costs",
    },
    ("zai", "glm-5.2"): {
        "input_price_usd_per_m": 1.4,
        "cached_input_price_usd_per_m": 0.26,
        "output_price_usd_per_m": 4.4,
        "pricing_status": "configured",
        "pricing_basis": "Official Z.AI general API pricing; trial quota is account-side",
        "pricing_source_url": "https://docs.z.ai/guides/overview/pricing",
    },
}

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "azure_foundry": {
        "label": "Microsoft Foundry / Azure OpenAI",
        "base_url": "",
        "auth_type": "api-key",
        "supports_balance_sync": False,
        "help_url": "https://ai.azure.com/",
        "pricing_url": "https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/",
        "note": "Можно вставить базовый resource URL или полный endpoint из Foundry portal; маршрут определяется автоматически.",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "auth_type": "bearer",
        "supports_balance_sync": False,
        "help_url": "https://platform.openai.com/api-keys",
        "pricing_url": "https://openai.com/api/pricing/",
    },
    "github_models": {
        "label": "GitHub Models",
        "base_url": "https://models.github.ai/inference",
        "auth_type": "bearer",
        "supports_balance_sync": False,
        "help_url": "https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models#experimenting-with-ai-models-using-the-api",
        "pricing_url": "https://docs.github.com/en/billing/managing-billing-for-your-products/about-billing-for-github-models",
        "note": (
            "Используйте GitHub PAT с правом models:read. Copilot Pro даёт "
            "бесплатный rate-limited доступ; paid usage для GitHub Models "
            "включается отдельно и не зависит от способа оплаты Copilot."
        ),
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "auth_type": "bearer",
        "supports_balance_sync": False,
        "help_url": "https://platform.deepseek.com/api_keys",
        "pricing_url": "https://api-docs.deepseek.com/quick_start/pricing",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "auth_type": "bearer",
        "supports_balance_sync": True,
        "help_url": "https://openrouter.ai/settings/keys",
        "pricing_url": "https://openrouter.ai/models?q=free",
        "default_free_model": "openrouter/free",
        "default_code_free_model": "cohere/north-mini-code:free",
        "note": (
            "Бесплатно без баланса: openrouter/free (общая free-модель) или "
            "cohere/north-mini-code:free (код). deepseek/deepseek-v4-flash:free "
            "сейчас недоступен; платный slug: deepseek/deepseek-v4-flash."
        ),
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "auth_type": "x-goog-api-key",
        "supports_balance_sync": False,
        "help_url": "https://aistudio.google.com/app/apikey",
        "pricing_url": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    "zai": {
        "label": "Z.AI / GLM",
        "base_url": "https://api.z.ai/api/paas/v4",
        "auth_type": "bearer",
        "supports_balance_sync": False,
        "help_url": "https://z.ai/manage-apikey/apikey-list",
        "pricing_url": "https://docs.z.ai/guides/overview/pricing",
        "note": (
            "Обычный API использует /api/paas/v4. /api/coding/paas/v4 работает "
            "только с активным GLM Coding Plan. GLM-5.2 тарифицируется; "
            "glm-4.7-flash и glm-4.5-flash бесплатны."
        ),
    },
    "mistral": {
        "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "auth_type": "bearer",
        "supports_balance_sync": False,
        "help_url": "https://console.mistral.ai/api-keys/",
        "pricing_url": "https://mistral.ai/pricing",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "auth_type": "bearer",
        "supports_balance_sync": False,
        "help_url": "https://console.groq.com/keys",
        "pricing_url": "https://groq.com/pricing/",
    },
    "custom": {
        "label": "Custom OpenAI-compatible",
        "base_url": "",
        "auth_type": "bearer",
        "supports_balance_sync": False,
        "help_url": "",
        "pricing_url": "",
        "note": "HTTPS endpoint с /chat/completions или базовый URL API.",
    },
}

ROLES: Dict[str, str] = {
    "orchestrator": "StratForge Orchestrator",
    "chief_agent": "Chief agent / research supervisor",
    "coder": "Coder",
    "strategy_analyst": "Strategy analyst",
    "accountant": "Financial controller / accountant",
    "backtest_analyst": "Backtest analyst",
    "risk_manager": "Risk manager",
    "telegram_assistant": "Telegram assistant",
    "news_analyst": "News analyst",
    "optimizer": "Optimizer",
    "hypothesis_fallback": "Hypothesis fallback",
    "compile_error_fixer_fallback": "Compile error fixer fallback",
    "embedding": "Embedding service",
    "general": "General assistant",
}

ENDPOINT_TYPES = {"chat", "embeddings"}
AUTH_TYPES = {"bearer", "api-key", "x-api-key", "x-goog-api-key"}
OPENROUTER_FREE_MODELS = frozenset({
    "openrouter/free",
    "cohere/north-mini-code:free",
})
ZAI_FREE_MODELS = frozenset({"glm-4.7-flash", "glm-4.5-flash"})
OPENROUTER_DEPRECATED_FREE_MODELS = {
    "deepseek/deepseek-v4-flash:free": "openrouter/free",
    "deepseek/deepseek-chat:free": "openrouter/free",
    "deepseek/deepseek-r1:free": "openrouter/free",
}
_LOCK = threading.RLock()


class AgentRegistryError(RuntimeError):
    """Safe-to-display registry error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def registry_path() -> Path:
    return paths.PROJECT_ROOT / "data" / "integrations" / "ai_agents.registry.json"


def usage_dir() -> Path:
    return paths.AI_LAB_DIR / "registry" / "agent_usage"


def usage_path(month: Optional[str] = None) -> Path:
    return usage_dir() / f"{month or datetime.now(timezone.utc).strftime('%Y-%m')}.jsonl"


def _secret_id(agent_id: str) -> str:
    return f"ai-agent:{agent_id}"


def _empty_doc() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "updated_at_utc": _now(), "agents": []}


def infer_endpoint_type(provider: str, model: str, base_url: str = "") -> str:
    """Infer chat vs embeddings for provider-owned model families."""
    text = f"{model} {urlparse(str(base_url or '')).path}".lower()
    if "embedding" in text or "embedcontent" in text:
        return "embeddings"
    return "chat"


def normalize_openrouter_model(model: str) -> str:
    """Map deprecated/unavailable OpenRouter free slugs to a working free model."""
    text = str(model or "").strip()
    if not text:
        return text
    lowered = text.lower()
    return OPENROUTER_DEPRECATED_FREE_MODELS.get(lowered, text)


def _is_github_models_host(base_url: str) -> bool:
    host = (urlparse(str(base_url or "")).hostname or "").lower()
    return host == "models.github.ai"


def is_openrouter_free_model(model: str) -> bool:
    lowered = str(model or "").strip().lower()
    if lowered in OPENROUTER_FREE_MODELS:
        return True
    return lowered.endswith(":free")


def infer_billing_mode(provider: str, model: str, credit_total: float = 0.0) -> str:
    if credit_total > 0:
        return "credit"
    if provider == "github_models":
        return "free_tier"
    if provider == "gemini":
        return "free_tier"
    if provider == "openrouter" and is_openrouter_free_model(model):
        return "free_tier"
    if provider == "zai" and str(model or "").strip().lower() in ZAI_FREE_MODELS:
        return "free_tier"
    return "unknown"


def _default_account_name(provider: str, base_url: str, credit_total: float = 0.0, agent_name: str = "") -> str:
    if provider == "azure_foundry":
        if credit_total > 0:
            return "Azure Student Grant ($100)" if abs(credit_total - 100.0) < 0.001 else "Azure Student Grant"
        host = urlparse(str(base_url or "")).hostname or "Foundry"
        return f"Azure · {host.split('.')[0]}"
    if provider == "github_models":
        return "GitHub Models API"
    if provider == "gemini":
        suffix = str(agent_name or "").replace("Gemini", "").strip(" _-")
        return f"Google AI Studio · {suffix}" if suffix else "Google AI Studio"
    if provider == "zai":
        return "Z.AI API"
    return PROVIDERS.get(provider, {}).get("label") or provider or "AI provider"


def _migrate_doc(doc: Dict[str, Any]) -> bool:
    if str(doc.get("schema_version") or "") == SCHEMA_VERSION:
        return False
    changed = False
    for row in doc.get("agents", []):
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "")
        credit_total = float(row.get("credit_total_usd") or 0)
        row["account_name"] = str(row.get("account_name") or _default_account_name(
            provider, str(row.get("base_url") or ""), credit_total, str(row.get("name") or "")
        ))[:120]
        model = str(row.get("model") or "")
        if provider == "openrouter":
            normalized = normalize_openrouter_model(model)
            if normalized != model:
                row["model"] = normalized
                model = normalized
                changed = True
        row["billing_mode"] = str(row.get("billing_mode") or infer_billing_mode(
            provider, model, credit_total
        ))
        row["rotation_group"] = str(row.get("rotation_group") or (
            "azure-student" if provider == "azure_foundry" and credit_total > 0 else f"{provider}-pool"
        ))[:80]
        row["priority"] = int(row.get("priority") or 100)
        row["endpoint_type"] = infer_endpoint_type(provider, model, str(row.get("base_url") or ""))
        # v1.0 defaults were accidentally restrictive. v1.1 starts in monitor-only mode;
        # zero means "no local monetary gate", not "no money left".
        row["daily_budget_usd"] = 0.0
        row["monthly_budget_usd"] = 0.0
        if str(row.get("disabled_reason") or "").endswith("budget_exceeded"):
            row["disabled_reason"] = "disabled_by_operator"
        has_price = float(row.get("input_price_usd_per_m") or 0) > 0 or float(row.get("output_price_usd_per_m") or 0) > 0
        row["pricing_status"] = "free" if row["billing_mode"] == "free_tier" else "configured" if has_price else "unpriced"
        changed = True
    doc["schema_version"] = SCHEMA_VERSION
    doc["updated_at_utc"] = _now()
    return changed


def _repair_doc(doc: Dict[str, Any]) -> bool:
    """Apply idempotent fixes for provider catalog drift without schema bumps."""
    changed = False
    for row in doc.get("agents", []):
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if provider == "custom" and _is_github_models_host(str(row.get("base_url") or "")):
            row["provider"] = "github_models"
            provider = "github_models"
            if str(row.get("billing_mode") or "").strip().lower() in {"", "unknown"}:
                row["billing_mode"] = "free_tier"
            if str(row.get("rotation_group") or "").strip() in {"", "custom-pool"}:
                row["rotation_group"] = "github-models"
            if str(row.get("pricing_status") or "").strip() in {"", "unpriced"}:
                row["pricing_status"] = "free" if row.get("billing_mode") == "free_tier" else "configured"
            if not str(row.get("pricing_basis") or "").strip() or str(row.get("pricing_basis")) == "Manual/custom configuration":
                row["pricing_basis"] = "GitHub Models free quota by default; paid usage uses GitHub token-unit billing"
            if not str(row.get("pricing_source_url") or "").strip():
                row["pricing_source_url"] = PROVIDERS["github_models"].get("pricing_url") or ""
            changed = True
        if provider == "openrouter":
            normalized = normalize_openrouter_model(model)
            if normalized != model:
                row["model"] = normalized
                model = normalized
                changed = True
            if row.get("billing_mode") in {None, "", "unknown"} and is_openrouter_free_model(model):
                row["billing_mode"] = "free_tier"
                row["pricing_status"] = "free"
                changed = True
    if changed:
        doc["updated_at_utc"] = _now()
    return changed


def _read_doc() -> Dict[str, Any]:
    doc = read_json(registry_path(), _empty_doc())
    if not isinstance(doc, dict) or not isinstance(doc.get("agents"), list):
        return _empty_doc()
    dirty = False
    if _migrate_doc(doc):
        dirty = True
    if _repair_doc(doc):
        dirty = True
    if dirty:
        write_json_atomic(registry_path(), doc)
    return doc


def _write_doc(doc: Dict[str, Any]) -> None:
    doc["schema_version"] = SCHEMA_VERSION
    doc["updated_at_utc"] = _now()
    write_json_atomic(registry_path(), doc)


def provider_catalog() -> List[Dict[str, Any]]:
    return [{"id": provider_id, **meta} for provider_id, meta in PROVIDERS.items()]


def role_catalog() -> List[Dict[str, str]]:
    return [{"id": role_id, "label": label} for role_id, label in ROLES.items()]


def managed_pricing(provider: str, model: str, billing_mode: str) -> Dict[str, Any]:
    if billing_mode == "free_tier":
        return {
            "input_price_usd_per_m": 0.0,
            "cached_input_price_usd_per_m": 0.0,
            "output_price_usd_per_m": 0.0,
            "pricing_status": "free",
            "pricing_basis": "Provider free tier",
            "pricing_source_url": PROVIDERS.get(provider, {}).get("pricing_url") or "",
        }
    return dict(MODEL_PRICING.get((provider, model.lower()), {}))


def _safe_float(value: Any, field: str, minimum: float = 0.0, maximum: float = 1_000_000.0) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        raise AgentRegistryError(f"{field} должен быть числом.") from None
    if number < minimum or number > maximum:
        raise AgentRegistryError(f"{field} должен быть от {minimum:g} до {maximum:g}.")
    return round(number, 8)


def _clean_url(value: Any, provider: str) -> str:
    raw = str(value or PROVIDERS[provider].get("base_url") or "").strip().rstrip("/")
    if not raw:
        raise AgentRegistryError("API base URL обязателен.")
    parsed = urlparse(raw)
    if parsed.username or parsed.password:
        raise AgentRegistryError("API base URL не должен содержать credentials.")
    is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (provider == "custom" and is_loopback and parsed.scheme == "http"):
        raise AgentRegistryError("API base URL должен использовать HTTPS; HTTP разрешён только для локального Custom provider.")
    if not parsed.hostname:
        raise AgentRegistryError("Некорректный API base URL.")
    return raw[:500]


def _clean_time(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = _parse_time(text)
    if not parsed:
        raise AgentRegistryError(f"{field} должен быть ISO datetime/date.")
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _validated(payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    source = {**(existing or {}), **(payload or {})}
    name = str(source.get("name") or "").strip()
    if not name or len(name) > 80:
        raise AgentRegistryError("Agent name обязателен и должен быть короче 80 символов.")
    provider = str(source.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise AgentRegistryError(f"Неподдерживаемый provider: {provider or 'не указан'}")
    model = str(source.get("model") or "").strip()
    if provider == "openrouter":
        model = normalize_openrouter_model(model)
    if not model or len(model) > 180:
        raise AgentRegistryError("Model/deployment name обязателен.")
    inferred_endpoint = infer_endpoint_type(provider, model, str(source.get("base_url") or ""))
    role = str(source.get("role") or ("embedding" if inferred_endpoint == "embeddings" else "general")).strip().lower()
    if provider != "custom" and inferred_endpoint == "embeddings":
        role = "embedding"
    if role not in ROLES:
        raise AgentRegistryError(f"Неподдерживаемая роль: {role}")
    endpoint_type = inferred_endpoint if provider != "custom" else str(source.get("endpoint_type") or inferred_endpoint).strip().lower()
    if endpoint_type not in ENDPOINT_TYPES:
        raise AgentRegistryError("endpoint_type должен быть chat или embeddings.")
    auth_type = str(source.get("auth_type") or PROVIDERS[provider]["auth_type"]).strip().lower()
    if auth_type not in AUTH_TYPES:
        raise AgentRegistryError("Неподдерживаемый способ авторизации.")
    input_price = _safe_float(source.get("input_price_usd_per_m"), "Input price", 0, 10_000)
    output_price = _safe_float(source.get("output_price_usd_per_m"), "Output price", 0, 10_000)
    cached_price_raw = source.get("cached_input_price_usd_per_m")
    cached_price = None if cached_price_raw in (None, "") else _safe_float(cached_price_raw, "Cached input price", 0, 10_000)
    daily = _safe_float(source.get("daily_budget_usd", 0), "Daily budget", 0, MAX_DAILY_BUDGET_USD)
    monthly = _safe_float(source.get("monthly_budget_usd", 0), "Monthly budget", 0, MAX_MONTHLY_BUDGET_USD)
    if daily > monthly and monthly > 0:
        raise AgentRegistryError("Daily budget не может превышать monthly budget.")
    credit_total = _safe_float(source.get("credit_total_usd", 0), "Credit/grant total", 0, 1_000_000)
    account_name = str(source.get("account_name") or _default_account_name(
        provider, str(source.get("base_url") or ""), credit_total, name
    )).strip()
    if not account_name or len(account_name) > 120:
        raise AgentRegistryError("Account / quota name обязателен и должен быть короче 120 символов.")
    billing_mode = str(source.get("billing_mode") or infer_billing_mode(
        provider, model, credit_total
    )).strip().lower()
    if provider == "zai" and model.lower() in ZAI_FREE_MODELS:
        billing_mode = "free_tier"
    if billing_mode not in BILLING_MODES:
        raise AgentRegistryError("Неподдерживаемый billing mode.")
    rotation_group = str(source.get("rotation_group") or f"{provider}-pool").strip()[:80]
    try:
        priority = int(source.get("priority") or 100)
    except (TypeError, ValueError):
        raise AgentRegistryError("Priority должен быть целым числом.") from None
    if priority < 1 or priority > 1000:
        raise AgentRegistryError("Priority должен быть от 1 до 1000.")
    central_pricing = managed_pricing(provider, model, billing_mode)
    if central_pricing:
        input_price = float(central_pricing["input_price_usd_per_m"])
        cached_price = central_pricing["cached_input_price_usd_per_m"]
        output_price = float(central_pricing["output_price_usd_per_m"])
    reported_raw = source.get("credit_remaining_reported_usd")
    reported = None if reported_raw in (None, "") else _safe_float(reported_raw, "Reported credit remaining", 0, 1_000_000)
    enabled = bool(source.get("enabled", False))
    return {
        **(existing or {}),
        "name": name,
        "provider": provider,
        "account_name": account_name,
        "billing_mode": billing_mode,
        "rotation_group": rotation_group,
        "priority": priority,
        "base_url": _clean_url(source.get("base_url"), provider),
        "model": model,
        "role": role,
        "purpose": str(source.get("purpose") or ROLES[role]).strip()[:500],
        "endpoint_type": endpoint_type,
        "auth_type": auth_type,
        "api_version": str(source.get("api_version") or "").strip()[:80],
        "enabled": enabled,
        "input_price_usd_per_m": input_price,
        "cached_input_price_usd_per_m": cached_price,
        "output_price_usd_per_m": output_price,
        "pricing_status": central_pricing.get("pricing_status") or ("configured" if input_price > 0 or output_price > 0 else "unpriced"),
        "pricing_basis": central_pricing.get("pricing_basis") or "Manual/custom configuration",
        "pricing_source_url": central_pricing.get("pricing_source_url") or PROVIDERS[provider].get("pricing_url") or "",
        "daily_budget_usd": daily,
        "monthly_budget_usd": monthly,
        "credit_total_usd": credit_total,
        "credit_started_at_utc": _clean_time(source.get("credit_started_at_utc"), "Credit start"),
        "credit_expires_at_utc": _clean_time(source.get("credit_expires_at_utc"), "Credit expiry"),
        "credit_remaining_reported_usd": reported,
        "credit_reported_at_utc": (
            _clean_time(source.get("credit_reported_at_utc"), "Credit balance timestamp") or _now()
        ) if reported is not None else "",
        "notes": str(source.get("notes") or "").strip()[:1000],
    }


def _raw_agents() -> List[Dict[str, Any]]:
    return [dict(row) for row in _read_doc().get("agents", []) if isinstance(row, dict)]


def _usage_files() -> Iterable[Path]:
    directory = usage_dir()
    return sorted(directory.glob("*.jsonl")) if directory.is_dir() else []


def usage_rows(*, agent_id: Optional[str] = None, limit: int = 5000) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in _usage_files():
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if agent_id and str(row.get("agent_id") or "") != agent_id:
                continue
            rows.append(row)
    return rows[-max(1, limit):]


def _sum_cost(rows: Iterable[Dict[str, Any]], *, since: Optional[datetime] = None) -> float:
    total = 0.0
    for row in rows:
        stamp = _parse_time(row.get("timestamp_utc"))
        if since and (not stamp or stamp < since):
            continue
        try:
            total += max(0.0, float(row.get("cost_usd") or 0))
        except (TypeError, ValueError):
            continue
    return total


def _public_agent(
    raw: Dict[str, Any],
    all_usage: Optional[List[Dict[str, Any]]] = None,
    raw_agents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    agent_id = str(raw.get("id") or "")
    all_rows = all_usage if all_usage is not None else usage_rows(limit=100_000)
    rows = [row for row in all_rows if str(row.get("agent_id") or "") == agent_id]
    account_name = str(raw.get("account_name") or "")
    peers = [
        item for item in (raw_agents or [raw])
        if str(item.get("provider") or "") == str(raw.get("provider") or "")
        and str(item.get("account_name") or "") == account_name
    ]
    peer_ids = {str(item.get("id") or "") for item in peers}
    account_rows = [row for row in all_rows if str(row.get("agent_id") or "") in peer_ids]
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    daily_spend = _sum_cost(rows, since=day_start)
    monthly_spend = _sum_cost(rows, since=month_start)
    account_monthly_spend = _sum_cost(account_rows, since=month_start)
    all_spend = _sum_cost(rows)
    reported_peer = max(
        (item for item in peers if item.get("credit_remaining_reported_usd") is not None),
        key=lambda item: _parse_time(item.get("credit_reported_at_utc")) or datetime.min.replace(tzinfo=timezone.utc),
        default=None,
    )
    reported = reported_peer.get("credit_remaining_reported_usd") if reported_peer else None
    reported_at = _parse_time(reported_peer.get("credit_reported_at_utc")) if reported_peer else None
    credit_starts = [stamp for stamp in (_parse_time(item.get("credit_started_at_utc")) for item in peers) if stamp]
    credit_start = min(credit_starts) if credit_starts else None
    credit_total = max((float(item.get("credit_total_usd") or 0) for item in peers), default=0.0)
    if reported is not None:
        credit_spend = _sum_cost(account_rows, since=reported_at) if reported_at else 0.0
        credit_remaining = max(0.0, float(reported) - credit_spend)
        credit_source = "reported_plus_local_usage"
    elif credit_total > 0:
        credit_spend = _sum_cost(account_rows, since=credit_start) if credit_start else _sum_cost(account_rows)
        credit_remaining = max(0.0, credit_total - credit_spend)
        credit_source = "local_estimate"
    else:
        credit_spend = 0.0
        credit_remaining = None
        credit_source = "not_configured"
    key_mask = ""
    key_error = ""
    try:
        key_mask = secure_store.secret_mask(_secret_id(agent_id))
    except secure_store.SecureStoreError as exc:
        key_error = str(exc)
    public = dict(raw)
    central_pricing = managed_pricing(
        str(raw.get("provider") or ""),
        str(raw.get("model") or ""),
        str(raw.get("billing_mode") or "unknown"),
    )
    if central_pricing:
        public.update(central_pricing)
    public.update({
        "key_configured": bool(key_mask),
        "key_mask": key_mask,
        "key_storage_error": key_error,
        "spend_today_usd": round(daily_spend, 8),
        "spend_month_usd": round(monthly_spend, 8),
        "account_spend_month_usd": round(account_monthly_spend, 8),
        "spend_all_time_usd": round(all_spend, 8),
        "remaining_daily_budget_usd": None if float(raw.get("daily_budget_usd") or 0) <= 0 else round(max(0.0, float(raw.get("daily_budget_usd") or 0) - daily_spend), 8),
        "remaining_monthly_budget_usd": None if float(raw.get("monthly_budget_usd") or 0) <= 0 else round(max(0.0, float(raw.get("monthly_budget_usd") or 0) - account_monthly_spend), 8),
        "monthly_budget_scope": "provider_account",
        "budget_mode": "monitor_only" if float(raw.get("daily_budget_usd") or 0) <= 0 and float(raw.get("monthly_budget_usd") or 0) <= 0 else "limited",
        "account_models": len(peers),
        "credit_tracked_spend_usd": round(credit_spend, 8),
        "credit_total_usd": round(credit_total, 8),
        "credit_used_pct": None if credit_total <= 0 else round(min(100.0, credit_spend / credit_total * 100.0), 6),
        "credit_remaining_reported_usd": reported,
        "credit_remaining_estimated_usd": None if credit_remaining is None else round(credit_remaining, 8),
        "credit_balance_source": credit_source,
        "requests_today": sum(1 for row in rows if (_parse_time(row.get("timestamp_utc")) or datetime.min.replace(tzinfo=timezone.utc)) >= day_start),
        "requests_month": sum(1 for row in rows if (_parse_time(row.get("timestamp_utc")) or datetime.min.replace(tzinfo=timezone.utc)) >= month_start),
        "cooldown_active": bool(_parse_time(raw.get("cooldown_until_utc")) and _parse_time(raw.get("cooldown_until_utc")) > now),
    })
    return public


def list_agents() -> List[Dict[str, Any]]:
    rows = usage_rows(limit=100_000)
    raw_agents = _raw_agents()
    return [_public_agent(raw, rows, raw_agents) for raw in raw_agents]


def get_agent(agent_id: str, *, public: bool = True) -> Dict[str, Any]:
    wanted = str(agent_id or "").strip()
    raw_agents = _raw_agents()
    for row in raw_agents:
        if str(row.get("id")) == wanted:
            return _public_agent(row, usage_rows(limit=100_000), raw_agents) if public else row
    raise AgentRegistryError("AI agent не найден.")


def create_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    api_key = str((payload or {}).get("api_key") or "").strip()
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        raise AgentRegistryError("Введите реальный API-ключ через интерфейс приложения.")
    if not secure_store.available():
        raise AgentRegistryError("Windows DPAPI недоступен; создание агента с ключом заблокировано.")
    clean = _validated(payload or {})
    agent_id = f"AGT-{uuid.uuid4().hex[:12].upper()}"
    now = _now()
    clean.update({
        "id": agent_id,
        "created_at_utc": now,
        "updated_at_utc": now,
        "last_test": None,
        "last_used_at_utc": "",
        "disabled_reason": "" if clean["enabled"] else "disabled_by_operator",
    })
    with _LOCK:
        doc = _read_doc()
        if any(str(row.get("name") or "").lower() == clean["name"].lower() for row in doc["agents"] if isinstance(row, dict)):
            raise AgentRegistryError("Агент с таким именем уже существует.")
        try:
            secure_store.set_secret(_secret_id(agent_id), api_key)
            doc["agents"].append(clean)
            _write_doc(doc)
        except Exception:
            try:
                secure_store.delete_secret(_secret_id(agent_id))
            except Exception:
                pass
            raise
    return get_agent(agent_id)


def update_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        index = next((i for i, row in enumerate(doc["agents"]) if isinstance(row, dict) and str(row.get("id")) == agent_id), None)
        if index is None:
            raise AgentRegistryError("AI agent не найден.")
        existing = dict(doc["agents"][index])
        clean = _validated(payload or {}, existing)
        clean.update({
            "id": existing["id"],
            "created_at_utc": existing.get("created_at_utc") or _now(),
            "updated_at_utc": _now(),
            "last_test": existing.get("last_test"),
            "last_used_at_utc": existing.get("last_used_at_utc") or "",
            "disabled_reason": "" if clean["enabled"] else str(existing.get("disabled_reason") or "disabled_by_operator"),
        })
        api_key = str((payload or {}).get("api_key") or "").strip()
        if api_key:
            if api_key == "YOUR_API_KEY_HERE":
                raise AgentRegistryError("Placeholder нельзя сохранять как API-ключ.")
            secure_store.set_secret(_secret_id(agent_id), api_key)
        doc["agents"][index] = clean
        _write_doc(doc)
    return get_agent(agent_id)


def delete_agent(agent_id: str) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        before = len(doc["agents"])
        doc["agents"] = [row for row in doc["agents"] if not isinstance(row, dict) or str(row.get("id")) != agent_id]
        if len(doc["agents"]) == before:
            raise AgentRegistryError("AI agent не найден.")
        secure_store.delete_secret(_secret_id(agent_id))
        _write_doc(doc)
    return {"ok": True, "deleted": agent_id}


def set_enabled(agent_id: str, enabled: bool, *, reason: str = "operator") -> Dict[str, Any]:
    if not isinstance(enabled, bool):
        raise AgentRegistryError("enabled должен быть true или false.")
    with _LOCK:
        doc = _read_doc()
        for index, row in enumerate(doc["agents"]):
            if not isinstance(row, dict) or str(row.get("id")) != agent_id:
                continue
            if enabled:
                try:
                    if not secure_store.get_secret(_secret_id(agent_id)):
                        raise AgentRegistryError("Нельзя включить агента без API-ключа.")
                except secure_store.SecureStoreError as exc:
                    raise AgentRegistryError(str(exc)) from None
            updated = dict(row)
            updated["enabled"] = enabled
            updated["disabled_reason"] = "" if enabled else str(reason or "disabled_by_operator")[:200]
            updated["updated_at_utc"] = _now()
            doc["agents"][index] = updated
            _write_doc(doc)
            return get_agent(agent_id)
    raise AgentRegistryError("AI agent не найден.")


def auto_disable(agent_id: str, reason: str) -> None:
    try:
        set_enabled(agent_id, False, reason=reason)
    except AgentRegistryError:
        pass


def set_cooldown(agent_id: str, seconds: int, reason: str) -> Dict[str, Any]:
    until = datetime.now(timezone.utc) + timedelta(seconds=max(1, min(int(seconds), 86_400)))
    with _LOCK:
        doc = _read_doc()
        for index, row in enumerate(doc["agents"]):
            if not isinstance(row, dict) or str(row.get("id")) != agent_id:
                continue
            updated = dict(row)
            updated["cooldown_until_utc"] = until.isoformat(timespec="seconds").replace("+00:00", "Z")
            updated["cooldown_reason"] = str(reason or "provider_cooldown")[:200]
            updated["updated_at_utc"] = _now()
            doc["agents"][index] = updated
            _write_doc(doc)
            return get_agent(agent_id)
    raise AgentRegistryError("AI agent не найден.")


def clear_cooldown(agent_id: str) -> None:
    with _LOCK:
        doc = _read_doc()
        for index, row in enumerate(doc["agents"]):
            if not isinstance(row, dict) or str(row.get("id")) != agent_id:
                continue
            if not row.get("cooldown_until_utc") and not row.get("cooldown_reason"):
                return
            updated = dict(row)
            updated["cooldown_until_utc"] = ""
            updated["cooldown_reason"] = ""
            updated["updated_at_utc"] = _now()
            doc["agents"][index] = updated
            _write_doc(doc)
            return


def get_api_key(agent_id: str) -> str:
    try:
        key = secure_store.get_secret(_secret_id(agent_id))
    except secure_store.SecureStoreError as exc:
        raise AgentRegistryError(str(exc)) from None
    if not key:
        raise AgentRegistryError("API-ключ агента не настроен.")
    return key


def record_usage(row: Dict[str, Any]) -> None:
    safe = {
        key: row.get(key)
        for key in (
            "timestamp_utc", "request_id", "agent_id", "agent_name", "provider",
            "account_name", "billing_mode", "rotation_group", "model", "role",
            "actual_model", "endpoint_type", "input_tokens", "cached_input_tokens", "cache_miss_tokens", "output_tokens",
            "application_cache_hit", "application_cache_saved_input_tokens", "application_cache_saved_output_tokens",
            "total_tokens", "cost_usd", "cost_known", "cost_estimated", "pricing_basis",
            "request_role", "purpose", "status", "elapsed_sec", "error",
            "user_id", "user_name", "workspace_id", "conversation_id", "request_source",
        )
    }
    append_jsonl(usage_path(), safe)
    with _LOCK:
        doc = _read_doc()
        for index, agent in enumerate(doc["agents"]):
            if isinstance(agent, dict) and str(agent.get("id")) == str(row.get("agent_id")):
                updated = dict(agent)
                updated["last_used_at_utc"] = str(row.get("timestamp_utc") or _now())
                doc["agents"][index] = updated
                _write_doc(doc)
                break


def record_test(agent_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        doc = _read_doc()
        for index, agent in enumerate(doc["agents"]):
            if not isinstance(agent, dict) or str(agent.get("id")) != agent_id:
                continue
            updated = dict(agent)
            updated["last_test"] = {
                "ok": bool(result.get("ok")),
                "tested_at_utc": _now(),
                "status": str(result.get("status") or ""),
                "error": str(result.get("error") or "")[:500],
                "elapsed_sec": result.get("elapsed_sec"),
            }
            updated["updated_at_utc"] = _now()
            doc["agents"][index] = updated
            _write_doc(doc)
            return get_agent(agent_id)
    raise AgentRegistryError("AI agent не найден.")


def summary() -> Dict[str, Any]:
    agents = list_agents()
    recent = usage_rows(limit=200)[-100:]
    provider_totals: Dict[str, Dict[str, Any]] = {}
    model_totals: Dict[str, Dict[str, Any]] = {}
    account_totals: Dict[str, Dict[str, Any]] = {}
    user_totals: Dict[str, Dict[str, Any]] = {}
    workspace_totals: Dict[str, Dict[str, Any]] = {}
    agents_by_id = {str(agent.get("id") or ""): agent for agent in agents}
    for row in usage_rows(limit=100_000):
        cost = float(row.get("cost_usd") or 0)
        tokens = int(row.get("total_tokens") or 0)
        input_tokens = int(row.get("input_tokens") or 0)
        cached_tokens = int(row.get("cached_input_tokens") or 0)
        app_saved = int(row.get("application_cache_saved_input_tokens") or 0)
        for bucket, key in (
            (provider_totals, str(row.get("provider") or "unknown")),
            (model_totals, str(row.get("model") or "unknown")),
            (account_totals, str(row.get("account_name") or agents_by_id.get(str(row.get("agent_id") or ""), {}).get("account_name") or "unknown")),
            (user_totals, str(row.get("user_id") or "system")),
            (workspace_totals, str(row.get("workspace_id") or "system")),
        ):
            item = bucket.setdefault(key, {"id": key, "requests": 0, "tokens": 0, "input_tokens": 0, "cached_input_tokens": 0, "application_cache_saved_input_tokens": 0, "cost_usd": 0.0, "unpriced_requests": 0})
            if bucket is user_totals and row.get("user_name"):
                item["name"] = str(row.get("user_name"))[:120]
            item["requests"] += 1
            item["tokens"] += tokens
            item["input_tokens"] += input_tokens
            item["cached_input_tokens"] += cached_tokens
            item["application_cache_saved_input_tokens"] += app_saved
            effective_input = item["input_tokens"] + item["application_cache_saved_input_tokens"]
            effective_cached = item["cached_input_tokens"] + item["application_cache_saved_input_tokens"]
            item["provider_cache_hit_pct"] = round(item["cached_input_tokens"] / item["input_tokens"] * 100.0, 2) if item["input_tokens"] else 0.0
            item["effective_cache_hit_pct"] = round(effective_cached / effective_input * 100.0, 2) if effective_input else 0.0
            item["cache_hit_pct"] = item["effective_cache_hit_pct"]
            item["cost_usd"] = round(item["cost_usd"] + cost, 8)
            if row.get("cost_known") is False:
                item["unpriced_requests"] += 1
    return {
        "agents": agents,
        "providers": provider_catalog(),
        "roles": role_catalog(),
        "endpoint_types": sorted(ENDPOINT_TYPES),
        "billing_modes": [{"id": key, "label": label} for key, label in BILLING_MODES.items()],
        "storage": {
            "available": secure_store.available(),
            "backend": secure_store.backend_name(),
            "encrypted": secure_store.available(),
        },
        "limits": {
            "max_daily_budget_usd": MAX_DAILY_BUDGET_USD,
            "max_monthly_budget_usd": MAX_MONTHLY_BUDGET_USD,
            "max_single_call_usd": MAX_SINGLE_CALL_USD,
        },
        "totals": {
            "agents": len(agents),
            "enabled": sum(1 for agent in agents if agent.get("enabled")),
            "spend_today_usd": round(sum(float(agent.get("spend_today_usd") or 0) for agent in agents), 8),
            "spend_month_usd": round(sum(float(agent.get("spend_month_usd") or 0) for agent in agents), 8),
            "input_tokens": sum(int(row.get("input_tokens") or 0) for row in recent),
            "cached_input_tokens": sum(int(row.get("cached_input_tokens") or 0) for row in recent),
            "application_cache_saved_input_tokens": sum(int(row.get("application_cache_saved_input_tokens") or 0) for row in recent),
            "application_cache_hits": sum(1 for row in recent if row.get("application_cache_hit")),
            "provider_cache_hit_pct": round(
                sum(int(row.get("cached_input_tokens") or 0) for row in recent)
                / max(1, sum(int(row.get("input_tokens") or 0) for row in recent)) * 100.0, 2),
            "cache_hit_pct": round(
                (sum(int(row.get("cached_input_tokens") or 0) for row in recent)
                 + sum(int(row.get("application_cache_saved_input_tokens") or 0) for row in recent))
                / max(1, sum(int(row.get("input_tokens") or 0) for row in recent)
                      + sum(int(row.get("application_cache_saved_input_tokens") or 0) for row in recent)) * 100.0, 2),
        },
        "usage": recent,
        "by_provider": sorted(provider_totals.values(), key=lambda row: row["cost_usd"], reverse=True),
        "by_model": sorted(model_totals.values(), key=lambda row: row["cost_usd"], reverse=True),
        "by_account": sorted(account_totals.values(), key=lambda row: row["cost_usd"], reverse=True),
        "by_user": sorted(user_totals.values(), key=lambda row: row["cost_usd"], reverse=True),
        "by_workspace": sorted(workspace_totals.values(), key=lambda row: row["cost_usd"], reverse=True),
        "security_note": "Ключи зашифрованы Windows DPAPI для текущего пользователя и никогда не возвращаются API.",
    }
