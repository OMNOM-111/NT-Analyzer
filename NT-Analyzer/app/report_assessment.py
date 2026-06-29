"""Shared report frequency and statistical-confidence assessment.

The assessment deliberately separates sample trust from profitability. A losing
report can have high statistical confidence, while a profitable one-trade report
must remain low-confidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _date(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def period_days(period: Any) -> Optional[float]:
    if not isinstance(period, dict):
        return None
    start = _date(period.get("from_utc"))
    end = _date(period.get("to_utc"))
    if start is None or end is None or end <= start:
        return None
    return max(1.0, (end - start).total_seconds() / 86400.0)


def frequency_assessment(trade_count: Any, period: Any) -> Dict[str, Any]:
    trades = max(0.0, _number(trade_count) or 0.0)
    days = period_days(period)
    weeks = max(1.0 / 7.0, days / 7.0) if days is not None else None
    per_week = trades / weeks if weeks else None
    if per_week is None:
        key, label = "unknown", "частота неизвестна"
        expectation = "Нужен корректный период отчёта."
        risk = "не определён"
        profit = "не определена"
    elif per_week < 2.0:
        key, label = "rare", "редко"
        expectation = "Менее 2 сделок в неделю. Требуется высокая прибыль на сделку и устойчивый результат."
        risk = "низкий"
        profit = "высокая"
    elif per_week <= 7.0:
        key, label = "normal", "нормально"
        expectation = "2–7 сделок в неделю. Ожидаются хорошая прибыль и средний контролируемый риск."
        risk = "средний"
        profit = "хорошая"
    else:
        key, label = "frequent", "часто"
        expectation = "Более 7 сделок в неделю. Допустима меньшая прибыль на сделку, но требуется контроль переторговки."
        risk = "умеренно повышенный"
        profit = "минимально допустимая"
    return {
        "key": key,
        "label": label,
        "trades_per_week": round(per_week, 3) if per_week is not None else None,
        "period_days": round(days, 2) if days is not None else None,
        "risk_expectation": risk,
        "profit_expectation": profit,
        "explanation": expectation,
    }


def confidence_assessment(trade_count: Any, period: Any, metrics: Any = None) -> Dict[str, Any]:
    trades = max(0, int(_number(trade_count) or 0))
    days = period_days(period)
    reasons = []
    if trades <= 0:
        return {"score": 0, "level": "insufficient", "label": "нет данных", "reasons": ["нет завершённых сделок"]}

    if trades >= 200:
        score = 90
    elif trades >= 100:
        score = 82
    elif trades >= 50:
        score = 72
    elif trades >= 20:
        score = 58
    elif trades >= 10:
        score = 42
    elif trades >= 5:
        score = 28
    else:
        score = 14
    reasons.append(f"размер выборки: {trades} сделок")

    if days is None:
        score -= 8
        reasons.append("период отчёта не определён")
    else:
        weeks = days / 7.0
        if weeks >= 26:
            score += 8
        elif weeks >= 12:
            score += 5
        elif weeks >= 4:
            score += 2
        elif weeks < 2:
            score -= 10
        reasons.append(f"покрытие периода: {days:.0f} дней")

    metric_doc = metrics if isinstance(metrics, dict) else {}
    required = ("winning_pct", "profit_factor", "max_drawdown")
    present = sum(1 for key in required if metric_doc.get(key) is not None)
    if present == len(required):
        score += 3
        reasons.append("основные метрики заполнены")
    elif present == 0:
        score -= 5
        reasons.append("основные метрики отсутствуют")

    if trades < 5:
        score = min(score, 18)
    elif trades < 10:
        score = min(score, 28)
    elif trades < 20:
        score = min(score, 42)
    elif trades < 50:
        score = min(score, 65)
    score = max(0, min(100, round(score)))
    if score >= 75:
        level, label = "high", "высокое"
    elif score >= 45:
        level, label = "medium", "среднее"
    elif score >= 25:
        level, label = "low", "низкое"
    else:
        level, label = "very_low", "очень низкое"
    return {"score": score, "level": level, "label": label, "reasons": reasons}


def assess_report(trade_count: Any, period: Any, metrics: Any = None) -> Dict[str, Any]:
    return {
        "frequency": frequency_assessment(trade_count, period),
        "confidence": confidence_assessment(trade_count, period, metrics),
    }
