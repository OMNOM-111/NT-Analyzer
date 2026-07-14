"""Deterministic first-pass intent classification for Orchestrator requests.

The classifier is deliberately small and local.  It does not make decisions
about trading safety; it only identifies application capabilities which can be
dispatched without relying on a model to remember a persona name.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Optional

from . import command_language


MODEL_CAPABILITIES = frozenset({
    "chart_snapshot", "chart_draw", "chart_open", "chart_clear",
    "accounting_report", "strategy_report", "news_report",
    "deliver_report", "start_backtest",
})


def _normalized(value: Any) -> str:
    return command_language.normalize_command(value).lower()


def _root(text: str) -> str:
    return command_language.resolve_instrument(text)


def _period(text: str) -> str:
    if any(word in text for word in ("сегодня", "за день", "дневн")):
        return "today"
    if any(word in text for word in ("недел", "weekly")):
        return "week"
    if any(word in text for word in ("квартал", "quarter")):
        return "quarter"
    if any(word in text for word in ("год", "year")):
        return "year"
    if any(word in text for word in ("все время", "всё время", "all time")):
        return "all"
    return "month"


def classify(message: Any) -> Dict[str, Any]:
    """Return a stable category/capability hint for one owner message."""
    text = _normalized(message)
    root = _root(text)
    base: Dict[str, Any] = {
        "category": "conversation",
        "capability": "",
        "confidence": 0.0,
        "period": _period(text),
        "target_root": root,
        "normalized_message": text,
        "resolver": "deterministic",
    }
    if not text:
        return base

    if (
        any(word in text for word in ("запомни", "всегда", "по умолчанию", "правило"))
        and "покаж" in text
        and any(word in text for word in ("снимок", "скрин", "график", "пришл"))
    ):
        return {**base, "category": "owner_rule", "capability": "", "confidence": 1.0}

    chart_word = any(word in text for word in ("график", "чарт", "chart", "рабочий стол"))
    show_word = any(word in text for word in (
        "покажи", "показать", "покажите", "выведи", "вывести", "отобрази",
        "продемонстр", "дай посмотреть", "хочу увидеть", "где график", "show",
    ))
    send_word = any(word in text for word in ("пришли", "пришлите", "скинь", "отправь", "дай"))
    if (
        any(word in text for word in ("снимок", "скрин", "snapshot", "screenshot"))
        and (root or chart_word or send_word)
    ) or (show_word and (root or chart_word)) or (send_word and chart_word):
        return {**base, "category": "chart_action", "capability": "chart_snapshot", "confidence": 1.0}
    if any(word in text for word in ("убери отмет", "очисти график", "стереть отмет", "clear chart")):
        return {**base, "category": "chart_action", "capability": "chart_clear", "confidence": 1.0}
    if any(word in text for word in ("поставь лини", "нарисуй", "отметь", "уровень")) and (root or chart_word):
        return {**base, "category": "chart_action", "capability": "chart_draw", "confidence": 0.98}
    if any(word in text for word in ("открой график", "открыть график", "перейди на график", "open chart")):
        return {**base, "category": "chart_action", "capability": "chart_open", "confidence": 0.98}
    if chart_word and root:
        return {**base, "category": "chart_action", "capability": "chart_snapshot", "confidence": 0.9}

    backtest_word = any(word in text for word in ("бэктест", "бек-тест", "бек тест", "backtest"))
    start_word = any(word in text for word in ("запусти", "запускай", "начни", "сделай", "прогони", "run ", "start "))
    if backtest_word and start_word:
        return {**base, "category": "backtest_action", "capability": "start_backtest", "confidence": 1.0}

    report_word = any(word in text for word in ("отчет", "отчёт", "сводк", "результат", "report"))
    finance_word = any(word in text for word in (
        "финанс", "бухгалт", "p&l", "пнл", "п&л", "комисси", "баланс", "доход", "расход", "прибыл", "убыт",
    ))
    strategy_word = any(word in text for word in ("стратег", "эксперимент", "бэктест", "backtest", "оверфит", "просадк"))
    news_word = any(word in text for word in ("новост", "календар", "fomc", "nfp", "cpi", "макро"))

    if finance_word and (report_word or any(word in text for word in ("покажи", "пришли", "сколько", "статус"))):
        return {**base, "category": "accounting_query", "capability": "accounting_report", "confidence": 0.98}
    if strategy_word and (report_word or any(word in text for word in ("покажи", "пришли", "статус", "проверь"))):
        return {**base, "category": "strategy_query", "capability": "strategy_report", "confidence": 0.96}
    if news_word:
        return {**base, "category": "news_query", "capability": "news_report", "confidence": 0.96}
    if report_word and any(word in text for word in ("пришли", "покажи", "сделай", "подготов", "сформируй", "дай")):
        return {**base, "category": "report_request", "capability": "deliver_report", "confidence": 0.94}
    if finance_word:
        return {**base, "category": "accounting_query", "capability": "accounting_report", "confidence": 0.82}
    if strategy_word and any(word in text for word in ("статус", "какие итог", "проверь", "покажи результат")):
        return {**base, "category": "strategy_query", "capability": "strategy_report", "confidence": 0.82}
    if strategy_word and any(word in text for word in ("разработ", "исслед", "создай", "запусти")):
        return {**base, "category": "research_action", "capability": "", "confidence": 0.75}
    return base


def is_refusal(text: Any) -> bool:
    low = _normalized(text)
    return any(phrase in low for phrase in (
        "не могу выполнить", "не могу сделать", "нет полномоч", "не имею полномоч",
        "вне моих возможностей", "у меня нет такой функции", "это не моя задача",
    ))


def resolve_followup(message: Any, history: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn «а сейчас?»/«повтори» into a deterministic retry of the last task."""
    current = classify(message)
    if current.get("capability"):
        return current
    low = _normalized(message).rstrip("?!.")
    if low not in {
        "а сейчас", "сейчас", "ну а сейчас", "получилось", "теперь получилось",
        "повтори", "попробуй еще раз", "попробуй ещё раз", "еще раз", "ещё раз",
    }:
        return current
    rows = [row for row in history if isinstance(row, dict)][-12:]
    failure_seen = False
    for row in reversed(rows):
        if row.get("role") != "assistant":
            continue
        actions = [item for item in (row.get("actions") or []) if isinstance(item, dict)]
        if any(str(item.get("status") or "") in {"blocked", "error", "failed", "needs_input"} for item in actions):
            failure_seen = True
            break
        content = str(row.get("content") or "")
        if is_refusal(content) or "не выполн" in _normalized(content) or "bridge" in content.lower():
            failure_seen = True
            break
    if not failure_seen:
        return current
    for row in reversed(rows):
        if row.get("role") != "user":
            continue
        previous = classify(row.get("content") or "")
        if previous.get("capability"):
            return {**previous, "confidence": 1.0, "followup_retry": True}
    return current


def _looks_operational(text: str) -> bool:
    return any(token in text for token in (
        "покаж", "пришл", "скинь", "отправ", "открой", "вывед", "сделай",
        "постав", "нарис", "отмет", "убер", "очист", "запуст", "прогон",
        "проверь", "подготов", "сформируй", "дай ", "show", "send ",
        "open ", "run ", "start ", "report", "chart", "график", "бэктест",
    ))


def _model_json(content: Any) -> Optional[Dict[str, Any]]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        doc = json.loads(match.group(0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def resolve_intent(message: Any, history: Iterable[Dict[str, Any]], *,
                   use_model: bool = True) -> Dict[str, Any]:
    """Resolve an operation with a cheap semantic fallback when rules are unsure.

    The model may select only an existing capability.  It never executes an
    action and its output is discarded unless the schema, allowlist and
    confidence threshold all pass.  Obvious commands therefore remain instant
    and network-independent, while natural speech has a second chance before it
    falls through to the full Orchestrator dialogue model.
    """
    current = resolve_followup(message, history)
    if current.get("capability") or not use_model:
        return current
    normalized = str(current.get("normalized_message") or _normalized(message))
    if not _looks_operational(normalized):
        return current
    try:
        from . import agent_router, llm_timeouts
        recent = [
            {"role": str(row.get("role") or ""), "content": str(row.get("content") or "")[:500]}
            for row in list(history or [])[-4:] if isinstance(row, dict)
        ]
        prompt = json.dumps({
            "message": normalized,
            "recent_context": recent,
            "allowed_capabilities": sorted(MODEL_CAPABILITIES),
            "supported_instruments": list(command_language.supported_roots()),
        }, ensure_ascii=False)
        system = (
            "You are a fast Russian/English command intent resolver for a trading research app. "
            "Understand colloquial speech, dictation errors, mixed Cyrillic/Latin futures symbols, "
            "and the user's literal requested operation. Return one JSON object only: "
            "{capability,target_root,confidence}. capability must be one allowed value or empty. "
            "Never turn 'show/send chart' into drawing a price level. Never invent an instrument."
        )
        result = agent_router.invoke_role(
            "telegram_assistant", prompt, system_prompt=system,
            max_output_tokens=220, timeout=min(10, llm_timeouts.ANALYSIS),
            purpose="orchestrator_intent_resolution", complexity="auto",
            cache_mode="off", allow_paid=False, max_attempts=2,
        )
        parsed = _model_json(result.get("content"))
    except Exception:
        return current
    capability = str((parsed or {}).get("capability") or "").strip()
    try:
        confidence = float((parsed or {}).get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    root = command_language.resolve_instrument((parsed or {}).get("target_root") or "")
    if capability not in MODEL_CAPABILITIES or confidence < 0.72:
        return current
    return {
        **current,
        "category": "model_resolved_action",
        "capability": capability,
        "confidence": min(1.0, confidence),
        "target_root": root or str(current.get("target_root") or ""),
        "resolver": "semantic_model",
        "resolver_model": str(result.get("actual_model") or result.get("model") or ""),
        "resolver_provider": str(result.get("provider") or ""),
    }
