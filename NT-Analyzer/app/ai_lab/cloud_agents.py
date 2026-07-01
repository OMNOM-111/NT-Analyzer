"""Controlled paid-model fallback for AI Lab.

The module is deliberately narrow:

* local LM Studio remains the primary provider;
* API execution is opt-in and constrained by monthly/per-run budgets;
* only advisory or repair roles are accepted;
* secrets are stored through :mod:`app.local_secrets` and never returned;
* every paid call writes a cost/audit row without prompt contents;
* cloud output never changes arbitration, governance, paper, or live state.

Only DeepSeek and Gemini have runtime adapters.  Other catalog entries are
comparison-only so the UI can show an honest buy/no-buy price table.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import local_secrets
from . import paths
from .io_utils import append_jsonl


PRICE_VERIFIED_AT = "2026-06-29"
MAX_MONTHLY_BUDGET_USD = 20.0
MAX_PER_RUN_BUDGET_USD = 0.50

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "label": "DeepSeek API",
        "key_env": "NTA_DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys",
        "docs_url": "https://api-docs.deepseek.com/",
        "runtime_supported": True,
    },
    "gemini": {
        "label": "Google Gemini API",
        "key_env": "NTA_GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/app/apikey",
        "docs_url": "https://ai.google.dev/gemini-api/docs",
        "runtime_supported": True,
    },
    "openai": {
        "label": "OpenAI API",
        "key_env": "NTA_OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "docs_url": "https://developers.openai.com/api/docs/",
        "runtime_supported": False,
        "note": "Только сравнение цен; адаптер намеренно не включён в бюджетный fallback.",
    },
}

# USD per 1M text tokens, standard synchronous processing.  Search/tool fees,
# audio/image pricing, taxes, regional premiums, Batch/Flex discounts, and
# long-context premiums are intentionally excluded.
MODEL_CATALOG: Tuple[Dict[str, Any], ...] = (
    {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "input_usd_per_m": 0.14,
        "cached_input_usd_per_m": 0.0028,
        "output_usd_per_m": 0.28,
        "context_tokens": 1_000_000,
        "recommended_for": ["hypothesis_fallback", "compile_error_fixer_fallback"],
        "quality": "лучший базовый вариант по цене",
        "runtime_supported": True,
        "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
    },
    {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "input_usd_per_m": 0.435,
        "cached_input_usd_per_m": 0.003625,
        "output_usd_per_m": 0.87,
        "context_tokens": 1_000_000,
        "recommended_for": ["candidate_second_opinion"],
        "quality": "редкая вторая оценка кандидата",
        "runtime_supported": True,
        "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
    },
    {
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "label": "Gemini 3.1 Flash-Lite",
        "input_usd_per_m": 0.25,
        "cached_input_usd_per_m": 0.025,
        "output_usd_per_m": 1.50,
        "context_tokens": 1_048_576,
        "recommended_for": ["large_log_summarizer", "change_monitor", "telegram_reporter"],
        "quality": "длинный контекст и служебные сводки",
        "runtime_supported": True,
        "source_url": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    {
        "provider": "openai",
        "model": "gpt-5.4-nano",
        "label": "GPT-5.4 nano",
        "input_usd_per_m": 0.20,
        "cached_input_usd_per_m": None,
        "output_usd_per_m": 1.25,
        "context_tokens": 400_000,
        "recommended_for": ["comparison_only"],
        "quality": "сравнение; не подключён",
        "runtime_supported": False,
        "source_url": "https://openai.com/index/introducing-gpt-5-4-mini-and-nano/",
    },
    {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "label": "GPT-5.4 mini",
        "input_usd_per_m": 0.75,
        "cached_input_usd_per_m": 0.075,
        "output_usd_per_m": 4.50,
        "context_tokens": 400_000,
        "recommended_for": ["comparison_only"],
        "quality": "сильнее, но не соответствует текущему бюджету fallback",
        "runtime_supported": False,
        "source_url": "https://openai.com/index/introducing-gpt-5-4-mini-and-nano/",
    },
)

ROLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "hypothesis_fallback": {
        "label": "Резерв гипотезы",
        "purpose": "Повторить hypothesis/spec после некорректного JSON или нарушенного контракта локальной модели.",
        "trigger": "локальная модель вернула invalid JSON / weak spec",
        "execution_path": "wired",
        "automatic": True,
    },
    "compile_error_fixer_fallback": {
        "label": "Резерв исправления C#",
        "purpose": "Исправить полный C# файл, если локальный compile-fix не вернул валидный исходник.",
        "trigger": "локальный compile-fix не дал валидный C#",
        "execution_path": "wired",
        "automatic": True,
    },
    "large_log_summarizer": {
        "label": "Сводка больших журналов",
        "purpose": "Сжимать длинные отчёты, не принимая торговых решений.",
        "trigger": "контекст превышает локальный лимит",
        "execution_path": "reserved",
        "automatic": False,
    },
    "change_monitor": {
        "label": "Монитор изменений",
        "purpose": "Объяснять изменения программы и стратегий по локально подготовленному diff.",
        "trigger": "только после отдельного подключения наблюдателя",
        "execution_path": "reserved",
        "automatic": False,
    },
    "telegram_reporter": {
        "label": "Редактор Telegram-сводок",
        "purpose": "Готовить текст уведомления; отправку выполняет существующий Telegram-сервис.",
        "trigger": "только после отдельного подключения к notifier",
        "execution_path": "reserved",
        "automatic": False,
    },
    "candidate_second_opinion": {
        "label": "Вторая оценка кандидата",
        "purpose": "Редкая advisory-проверка кандидата без права изменить deterministic verdict.",
        "trigger": "status=candidate и ручное разрешение",
        "execution_path": "reserved",
        "automatic": False,
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "mode": "local_first",
    "fallback_enabled": False,
    "monthly_budget_usd": 20.0,
    "per_run_budget_usd": 0.50,
    "role_assignments": {
        "hypothesis_fallback": {"model": "deepseek-v4-flash", "enabled": True},
        "compile_error_fixer_fallback": {"model": "deepseek-v4-flash", "enabled": True},
        "large_log_summarizer": {"model": "gemini-3.1-flash-lite", "enabled": False},
        "change_monitor": {"model": "gemini-3.1-flash-lite", "enabled": False},
        "telegram_reporter": {"model": "gemini-3.1-flash-lite", "enabled": False},
        "candidate_second_opinion": {"model": "deepseek-v4-pro", "enabled": False},
    },
    "provider_checks": {},
}

_IO_LOCK = threading.RLock()
_BUDGET_LOCK = threading.RLock()
_RESERVATIONS: Dict[str, float] = {}


class CloudAgentsError(RuntimeError):
    """Safe-to-display cloud integration error."""


class CloudAgentBlocked(CloudAgentsError):
    """The request was denied by configuration, role, or budget gates."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _settings_path() -> Path:
    return paths.PROJECT_ROOT / "data" / "integrations" / "ai_agents.settings.json"


def _usage_dir() -> Path:
    return paths.AI_LAB_DIR / "registry" / "cloud_usage"


def _usage_path(month: Optional[str] = None) -> Path:
    return _usage_dir() / f"{month or _month_key()}.jsonl"


def _catalog_map() -> Dict[str, Dict[str, Any]]:
    return {str(row["model"]): dict(row) for row in MODEL_CATALOG}


def catalog() -> List[Dict[str, Any]]:
    """Return public pricing rows with a comparable example request cost."""
    rows: List[Dict[str, Any]] = []
    for source in MODEL_CATALOG:
        row = dict(source)
        # Representative fallback: 25k input + 3k output tokens, no cache hit.
        row["example_input_tokens"] = 25_000
        row["example_output_tokens"] = 3_000
        row["example_cost_usd"] = round(
            (25_000 * float(row["input_usd_per_m"]) + 3_000 * float(row["output_usd_per_m"])) / 1_000_000,
            6,
        )
        row["price_verified_at"] = PRICE_VERIFIED_AT
        rows.append(row)
    return rows


def load_settings() -> Dict[str, Any]:
    out = copy.deepcopy(DEFAULT_SETTINGS)
    path = _settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        return out
    if raw.get("mode") == "local_first":
        out["mode"] = "local_first"
    if isinstance(raw.get("fallback_enabled"), bool):
        out["fallback_enabled"] = raw["fallback_enabled"]
    for key, ceiling in (
        ("monthly_budget_usd", MAX_MONTHLY_BUDGET_USD),
        ("per_run_budget_usd", MAX_PER_RUN_BUDGET_USD),
    ):
        try:
            out[key] = max(0.0, min(ceiling, float(raw.get(key, out[key]))))
        except (TypeError, ValueError):
            pass
    incoming_roles = raw.get("role_assignments")
    catalog_by_model = _catalog_map()
    if isinstance(incoming_roles, dict):
        for role, assignment in incoming_roles.items():
            if role not in ROLE_DEFINITIONS or not isinstance(assignment, dict):
                continue
            model = str(assignment.get("model") or "")
            if model in catalog_by_model and catalog_by_model[model].get("runtime_supported"):
                out["role_assignments"][role]["model"] = model
            if isinstance(assignment.get("enabled"), bool):
                out["role_assignments"][role]["enabled"] = assignment["enabled"]
    checks = raw.get("provider_checks")
    if isinstance(checks, dict):
        out["provider_checks"] = {
            str(provider): {
                "ok": bool(value.get("ok")),
                "checked_at_utc": str(value.get("checked_at_utc") or ""),
                "message": str(value.get("message") or "")[:300],
            }
            for provider, value in checks.items()
            if provider in PROVIDERS and isinstance(value, dict)
        }
    return out


def _save_settings(settings: Dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def update_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist non-secret budgets, enablement, and role routes."""
    if not isinstance(changes, dict):
        raise CloudAgentsError("Настройки должны быть JSON-объектом.")
    with _IO_LOCK:
        settings = load_settings()
        if "fallback_enabled" in changes:
            if not isinstance(changes["fallback_enabled"], bool):
                raise CloudAgentsError("fallback_enabled должен быть true или false.")
            settings["fallback_enabled"] = changes["fallback_enabled"]
        for key, ceiling, label in (
            ("monthly_budget_usd", MAX_MONTHLY_BUDGET_USD, "Месячный лимит"),
            ("per_run_budget_usd", MAX_PER_RUN_BUDGET_USD, "Лимит на цикл"),
        ):
            if key not in changes:
                continue
            try:
                value = float(changes[key])
            except (TypeError, ValueError):
                raise CloudAgentsError(f"{label} должен быть числом.") from None
            if value < 0 or value > ceiling:
                raise CloudAgentsError(f"{label} должен быть от $0 до ${ceiling:.2f}.")
            settings[key] = round(value, 4)
        assignments = changes.get("role_assignments")
        catalog_by_model = _catalog_map()
        if assignments is not None:
            if not isinstance(assignments, dict):
                raise CloudAgentsError("role_assignments должен быть объектом.")
            for role, assignment in assignments.items():
                if role not in ROLE_DEFINITIONS:
                    raise CloudAgentsError(f"Неизвестная роль: {role}")
                if not isinstance(assignment, dict):
                    raise CloudAgentsError(f"Настройка роли {role} должна быть объектом.")
                current = dict(settings["role_assignments"][role])
                if "model" in assignment:
                    model = str(assignment.get("model") or "")
                    model_row = catalog_by_model.get(model)
                    if not model_row or not model_row.get("runtime_supported"):
                        raise CloudAgentsError(f"Модель {model or 'не указана'} не поддержана для выполнения.")
                    current["model"] = model
                if "enabled" in assignment:
                    if not isinstance(assignment["enabled"], bool):
                        raise CloudAgentsError(f"enabled для {role} должен быть true или false.")
                    current["enabled"] = assignment["enabled"]
                settings["role_assignments"][role] = current
        settings["updated_at_utc"] = _now()
        _save_settings(settings)
    return status()


def _safe_error(error: BaseException, secret: str = "") -> str:
    text = str(error or "Ошибка API").strip() or "Ошибка API"
    if secret:
        text = text.replace(secret, "[скрыто]")
    text = re.sub(r"([?&]key=)[^&\s]+", r"\1[скрыто]", text, flags=re.I)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [скрыто]", text, flags=re.I)
    return text[:500]


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
    secret: str = "",
) -> Dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            detail = json.loads(body)
            message = detail.get("error") if isinstance(detail, dict) else body
            if isinstance(message, dict):
                message = message.get("message") or message.get("status") or str(message)
        except Exception:
            message = f"HTTP {exc.code}"
        raise CloudAgentsError(_safe_error(RuntimeError(f"API отклонил запрос: {message}"), secret)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CloudAgentsError(_safe_error(RuntimeError(f"API недоступен: {exc}"), secret)) from None
    try:
        doc = json.loads(raw)
    except ValueError:
        raise CloudAgentsError("API вернул некорректный JSON.") from None
    if not isinstance(doc, dict):
        raise CloudAgentsError("API вернул неожиданный формат ответа.")
    return doc


def _provider_key(provider: str, key_override: str = "") -> str:
    meta = PROVIDERS.get(provider)
    if not meta:
        raise CloudAgentsError(f"Неизвестный провайдер: {provider}")
    return str(key_override or os.environ.get(str(meta["key_env"])) or "").strip()


def test_provider(provider: str, *, key_override: str = "") -> Dict[str, Any]:
    """Validate credentials with a non-inference model-list request."""
    provider = str(provider or "").strip().lower()
    meta = PROVIDERS.get(provider)
    if not meta or not meta.get("runtime_supported"):
        raise CloudAgentsError("Этот провайдер пока доступен только для сравнения цен.")
    key = _provider_key(provider, key_override)
    if len(key) < 12:
        raise CloudAgentsError("API-ключ пустой или выглядит неполным.")
    if provider == "deepseek":
        doc = _request_json(
            "https://api.deepseek.com/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
            secret=key,
        )
        ids = [str(row.get("id")) for row in doc.get("data", []) if isinstance(row, dict) and row.get("id")]
    else:
        encoded_key = urllib.parse.quote(key, safe="")
        doc = _request_json(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={encoded_key}",
            timeout=20,
            secret=key,
        )
        ids = [str(row.get("name") or "").replace("models/", "") for row in doc.get("models", []) if isinstance(row, dict)]
    expected = [row["model"] for row in MODEL_CATALOG if row["provider"] == provider and row.get("runtime_supported")]
    return {
        "ok": True,
        "provider": provider,
        "checked_at_utc": _now(),
        "available_models": [model for model in expected if model in ids],
        "message": f"Ключ принят; API вернул {len(ids)} моделей.",
    }


def configure_provider(provider: str, api_key: str) -> Dict[str, Any]:
    """Test a supplied key first, then persist it without returning it."""
    provider = str(provider or "").strip().lower()
    key = str(api_key or "").strip()
    check = test_provider(provider, key_override=key)
    env_name = str(PROVIDERS[provider]["key_env"])
    if not local_secrets.update({env_name: key}):
        raise CloudAgentsError("Не удалось сохранить ключ в локальном хранилище секретов.")
    with _IO_LOCK:
        settings = load_settings()
        settings.setdefault("provider_checks", {})[provider] = {
            "ok": True,
            "checked_at_utc": check["checked_at_utc"],
            "message": check["message"],
        }
        settings["updated_at_utc"] = _now()
        _save_settings(settings)
    return status()


def recheck_provider(provider: str) -> Dict[str, Any]:
    provider = str(provider or "").strip().lower()
    try:
        check = test_provider(provider)
    except CloudAgentsError as exc:
        check = {"ok": False, "checked_at_utc": _now(), "message": str(exc)}
    with _IO_LOCK:
        settings = load_settings()
        settings.setdefault("provider_checks", {})[provider] = {
            "ok": bool(check.get("ok")),
            "checked_at_utc": str(check.get("checked_at_utc") or _now()),
            "message": str(check.get("message") or "")[:300],
        }
        settings["updated_at_utc"] = _now()
        _save_settings(settings)
    if not check.get("ok"):
        raise CloudAgentsError(str(check.get("message") or "Проверка API не пройдена."))
    return status()


def disconnect_provider(provider: str) -> Dict[str, Any]:
    provider = str(provider or "").strip().lower()
    meta = PROVIDERS.get(provider)
    if not meta or not meta.get("runtime_supported"):
        raise CloudAgentsError("Неизвестный или неподдерживаемый провайдер.")
    if not local_secrets.update({str(meta["key_env"]): None}):
        raise CloudAgentsError("Не удалось удалить ключ из локального хранилища.")
    with _IO_LOCK:
        settings = load_settings()
        settings.setdefault("provider_checks", {}).pop(provider, None)
        settings["updated_at_utc"] = _now()
        _save_settings(settings)
    return status()


def _usage_rows(month: Optional[str] = None, limit: int = 5000) -> List[Dict[str, Any]]:
    path = _usage_path(month)
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines()[-max(1, limit):]:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows


def _spend(rows: List[Dict[str, Any]], experiment_id: Optional[str] = None) -> float:
    total = 0.0
    for row in rows:
        if experiment_id is not None and str(row.get("experiment_id") or "") != experiment_id:
            continue
        try:
            total += max(0.0, float(row.get("cost_usd") or 0.0))
        except (TypeError, ValueError):
            pass
    return total


def status() -> Dict[str, Any]:
    settings = load_settings()
    rows = _usage_rows(limit=5000)
    spent = _spend(rows)
    budget = float(settings["monthly_budget_usd"])
    catalog_by_model = _catalog_map()
    provider_rows: List[Dict[str, Any]] = []
    provider_configured: Dict[str, bool] = {}
    for provider, meta in PROVIDERS.items():
        configured = bool(os.environ.get(str(meta["key_env"])))
        provider_configured[provider] = configured
        check = (settings.get("provider_checks") or {}).get(provider) or {}
        provider_rows.append({
            "id": provider,
            "label": meta["label"],
            "configured": configured,
            "runtime_supported": bool(meta.get("runtime_supported")),
            "last_check_ok": bool(check.get("ok")) if check else None,
            "last_checked_at_utc": str(check.get("checked_at_utc") or ""),
            "last_check_message": str(check.get("message") or ""),
            "key_url": meta["key_url"],
            "docs_url": meta["docs_url"],
            "note": str(meta.get("note") or ""),
        })
    roles: List[Dict[str, Any]] = []
    runnable_roles = 0
    for role, definition in ROLE_DEFINITIONS.items():
        assignment = dict(settings["role_assignments"][role])
        model_row = catalog_by_model[assignment["model"]]
        provider = str(model_row["provider"])
        ready = bool(
            settings["fallback_enabled"]
            and assignment.get("enabled")
            and definition["execution_path"] == "wired"
            and provider_configured.get(provider)
            and budget > spent
            and float(settings["per_run_budget_usd"]) > 0
        )
        if ready:
            runnable_roles += 1
        roles.append({
            "id": role,
            **definition,
            **assignment,
            "provider": provider,
            "provider_label": PROVIDERS[provider]["label"],
            "provider_configured": provider_configured.get(provider, False),
            "ready": ready,
        })
    blocked_reasons: List[str] = []
    if not settings["fallback_enabled"]:
        blocked_reasons.append("Платный fallback выключен оператором.")
    if not any(provider_configured[p] for p in ("deepseek", "gemini")):
        blocked_reasons.append("Не настроен ни один поддерживаемый API-ключ.")
    if budget <= spent:
        blocked_reasons.append("Месячный бюджет исчерпан.")
    if float(settings["per_run_budget_usd"]) <= 0:
        blocked_reasons.append("Лимит на цикл равен нулю.")
    public_usage = []
    for row in rows[-100:]:
        public_usage.append({
            key: row.get(key)
            for key in (
                "timestamp_utc", "experiment_id", "provider", "model", "role",
                "purpose", "fallback_reason", "status", "input_tokens",
                "cached_input_tokens", "output_tokens", "total_tokens",
                "cost_usd", "elapsed_sec", "error",
            )
        })
    return {
        "configured": any(
            provider_configured.get(provider, False)
            for provider, meta in PROVIDERS.items()
            if meta.get("runtime_supported")
        ),
        "mode": "local_first",
        "fallback_enabled": bool(settings["fallback_enabled"]),
        "execution_enabled": runnable_roles > 0,
        "budget_usd": round(budget, 4),
        "monthly_budget_usd": round(budget, 4),
        "per_run_budget_usd": round(float(settings["per_run_budget_usd"]), 4),
        "spent_usd": round(spent, 6),
        "remaining_usd": round(max(0.0, budget - spent), 6),
        "billing_period_utc": _month_key(),
        "providers": provider_rows,
        "roles": roles,
        "catalog": catalog(),
        "agents": public_usage,
        "usage": public_usage,
        "blocked_reasons": blocked_reasons,
        "price_verified_at": PRICE_VERIFIED_AT,
        "pricing_note": "USD за 1M текстовых токенов, standard API; фактический счёт провайдера имеет приоритет.",
        "governance": {
            "local_first": True,
            "api_output_is_verdict": False,
            "live_or_paper_access": False,
            "human_promotion_required": True,
            "monthly_hard_cap_usd": MAX_MONTHLY_BUDGET_USD,
            "per_run_hard_cap_usd": MAX_PER_RUN_BUDGET_USD,
        },
        "note": "API используется только как узкий fallback после локальной модели.",
    }


def _estimated_tokens(messages: List[Dict[str, str]]) -> int:
    # One token per UTF-8 byte is intentionally conservative for mixed Russian,
    # English, JSON and C# prompts.  It over-reserves rather than allowing a
    # tokenizer mismatch to breach a hard budget before provider usage arrives.
    prompt_bytes = sum(
        len(str(message.get("content") or "").encode("utf-8")) + 16
        for message in messages
    )
    return max(1, prompt_bytes)


def _cost(model_row: Dict[str, Any], input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    cached = max(0, min(int(input_tokens), int(cached_tokens)))
    uncached = max(0, int(input_tokens) - cached)
    cached_rate = model_row.get("cached_input_usd_per_m")
    if cached_rate is None:
        uncached += cached
        cached = 0
        cached_rate = 0.0
    return (
        uncached * float(model_row["input_usd_per_m"])
        + cached * float(cached_rate)
        + max(0, int(output_tokens)) * float(model_row["output_usd_per_m"])
    ) / 1_000_000


def _reserve_budget(role: str, experiment_id: str, estimate: float) -> str:
    settings = load_settings()
    definition = ROLE_DEFINITIONS.get(role)
    assignment = (settings.get("role_assignments") or {}).get(role)
    if not definition or not assignment:
        raise CloudAgentBlocked(f"Cloud-роль не разрешена: {role}")
    if definition.get("execution_path") != "wired":
        raise CloudAgentBlocked(f"Роль {role} ещё не подключена к runtime.")
    if not settings.get("fallback_enabled"):
        raise CloudAgentBlocked("Платный fallback выключен.")
    if not assignment.get("enabled"):
        raise CloudAgentBlocked(f"Платная роль {role} выключена.")
    model_row = _catalog_map().get(str(assignment.get("model") or ""))
    if not model_row or not model_row.get("runtime_supported"):
        raise CloudAgentBlocked("Для роли выбрана неподдерживаемая модель.")
    provider = str(model_row["provider"])
    if not _provider_key(provider):
        raise CloudAgentBlocked(f"API-ключ {PROVIDERS[provider]['label']} не настроен.")
    rows = _usage_rows(limit=5000)
    with _BUDGET_LOCK:
        reserved_total = sum(_RESERVATIONS.values())
        reserved_run = sum(
            amount for key, amount in _RESERVATIONS.items()
            if key.startswith(f"{experiment_id}:")
        )
        if _spend(rows) + reserved_total + estimate > float(settings["monthly_budget_usd"]) + 1e-12:
            raise CloudAgentBlocked("Вызов заблокирован месячным бюджетом API.")
        if _spend(rows, experiment_id) + reserved_run + estimate > float(settings["per_run_budget_usd"]) + 1e-12:
            raise CloudAgentBlocked("Вызов заблокирован лимитом API на один цикл.")
        reservation_id = f"{experiment_id}:{role}:{time.time_ns()}"
        _RESERVATIONS[reservation_id] = estimate
        return reservation_id


def _release_budget(reservation_id: str) -> None:
    with _BUDGET_LOCK:
        _RESERVATIONS.pop(reservation_id, None)


def _deepseek_chat(
    model: str,
    messages: List[Dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> Tuple[str, Dict[str, int], Dict[str, Any]]:
    key = _provider_key("deepseek")
    doc = _request_json(
        "https://api.deepseek.com/chat/completions",
        method="POST",
        payload={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        },
        headers={"Authorization": f"Bearer {key}"},
        timeout=timeout,
        secret=key,
    )
    try:
        content = str(doc["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        raise CloudAgentsError("DeepSeek не вернул текстовый ответ.") from None
    raw_usage = doc.get("usage") if isinstance(doc.get("usage"), dict) else {}
    details = raw_usage.get("prompt_tokens_details") if isinstance(raw_usage.get("prompt_tokens_details"), dict) else {}
    usage = {
        "input_tokens": int(raw_usage.get("prompt_tokens") or 0),
        "cached_input_tokens": int(
            raw_usage.get("prompt_cache_hit_tokens")
            or details.get("cached_tokens")
            or 0
        ),
        "output_tokens": int(raw_usage.get("completion_tokens") or 0),
    }
    return content, usage, doc


def _gemini_chat(
    model: str,
    messages: List[Dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> Tuple[str, Dict[str, int], Dict[str, Any]]:
    key = _provider_key("gemini")
    system_parts: List[Dict[str, str]] = []
    contents: List[Dict[str, Any]] = []
    for message in messages:
        text = str(message.get("content") or "")
        if message.get("role") == "system":
            system_parts.append({"text": text})
        else:
            contents.append({
                "role": "model" if message.get("role") == "assistant" else "user",
                "parts": [{"text": text}],
            })
    payload: Dict[str, Any] = {
        "contents": contents or [{"role": "user", "parts": [{"text": "Respond briefly."}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    encoded_key = urllib.parse.quote(key, safe="")
    doc = _request_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent?key={encoded_key}",
        method="POST",
        payload=payload,
        timeout=timeout,
        secret=key,
    )
    try:
        parts_out = doc["candidates"][0]["content"]["parts"]
        content = "".join(str(part.get("text") or "") for part in parts_out if isinstance(part, dict))
    except (KeyError, IndexError, TypeError):
        content = ""
    if not content:
        raise CloudAgentsError("Gemini не вернул текстовый ответ.")
    raw_usage = doc.get("usageMetadata") if isinstance(doc.get("usageMetadata"), dict) else {}
    usage = {
        "input_tokens": int(raw_usage.get("promptTokenCount") or 0),
        "cached_input_tokens": int(raw_usage.get("cachedContentTokenCount") or 0),
        "output_tokens": int(raw_usage.get("candidatesTokenCount") or 0)
        + int(raw_usage.get("thoughtsTokenCount") or 0),
    }
    return content, usage, doc


def invoke(
    role: str,
    messages: List[Dict[str, str]],
    *,
    fallback_reason: str,
    experiment_id: Optional[str] = None,
    purpose: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    timeout: int = 180,
) -> Dict[str, Any]:
    """Run one budget-gated paid fallback request and append an audit row."""
    if not isinstance(messages, list) or not messages:
        raise CloudAgentBlocked("Cloud-вызов требует непустой список сообщений.")
    settings = load_settings()
    assignment = (settings.get("role_assignments") or {}).get(role) or {}
    model = str(assignment.get("model") or "")
    model_row = _catalog_map().get(model)
    if not model_row:
        raise CloudAgentBlocked(f"Для роли {role} не выбрана модель.")
    provider = str(model_row["provider"])
    run_id = str(experiment_id or "manual")
    estimated_input = _estimated_tokens(messages)
    bounded_max_tokens = max(1, min(int(max_tokens), 16_384))
    estimate = _cost(model_row, estimated_input, bounded_max_tokens, 0)
    reservation_id = _reserve_budget(role, run_id, estimate)
    started = time.time()
    prompt_hash = hashlib.sha256(
        json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    try:
        if provider == "deepseek":
            content, usage, _raw = _deepseek_chat(
                model, messages, temperature=temperature,
                max_tokens=bounded_max_tokens, timeout=timeout,
            )
        elif provider == "gemini":
            content, usage, _raw = _gemini_chat(
                model, messages, temperature=temperature,
                max_tokens=bounded_max_tokens, timeout=timeout,
            )
        else:
            raise CloudAgentBlocked(f"Runtime-адаптер {provider} не поддержан.")
        reported_input = int(usage.get("input_tokens") or 0)
        reported_output = int(usage.get("output_tokens") or 0)
        input_tokens = reported_input or estimated_input
        cached_tokens = int(usage.get("cached_input_tokens") or 0) if reported_input else 0
        # Missing provider usage is not treated as free/cheap: reserve the full
        # permitted output so the next call cannot spend an untracked balance.
        output_tokens = reported_output or bounded_max_tokens
        cost_usd = _cost(model_row, input_tokens, output_tokens, cached_tokens)
        row = {
            "timestamp_utc": _now(),
            "experiment_id": experiment_id,
            "provider": provider,
            "model": model,
            "role": role,
            "purpose": str(purpose or role),
            "fallback_reason": str(fallback_reason or "local_failure")[:300],
            "status": "completed",
            "prompt_hash": prompt_hash,
            "prompt_chars": sum(len(str(item.get("content") or "")) for item in messages),
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost_usd, 8),
            "estimated_reservation_usd": round(estimate, 8),
            "elapsed_sec": round(time.time() - started, 3),
            "api_output_is_verdict": False,
            "live_or_paper_access": False,
            "error": None,
        }
        append_jsonl(_usage_path(), row)
        return {
            "content": content,
            "provider": provider,
            "model": model,
            "role": role,
            "usage": usage,
            "cost_usd": row["cost_usd"],
            "elapsed_sec": row["elapsed_sec"],
            "source": "cloud_fallback",
        }
    except CloudAgentBlocked:
        raise
    except CloudAgentsError as exc:
        row = {
            "timestamp_utc": _now(),
            "experiment_id": experiment_id,
            "provider": provider,
            "model": model,
            "role": role,
            "purpose": str(purpose or role),
            "fallback_reason": str(fallback_reason or "local_failure")[:300],
            "status": "failed",
            "prompt_hash": prompt_hash,
            "prompt_chars": sum(len(str(item.get("content") or "")) for item in messages),
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "estimated_reservation_usd": round(estimate, 8),
            "elapsed_sec": round(time.time() - started, 3),
            "api_output_is_verdict": False,
            "live_or_paper_access": False,
            "error": _safe_error(exc),
        }
        append_jsonl(_usage_path(), row)
        raise
    finally:
        _release_budget(reservation_id)
