"""Named, model-independent domain experts for the application.

The domain agents are personas over the shared Auto router, not dedicated API
keys.  Financial and trading facts are always calculated by deterministic
code; an LLM may explain those facts but cannot replace or mutate them.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from .. import account_ledger, performance, runtime
from . import agent_router, llm_timeouts, news_agent, registry


MONEY = Decimal("0.01")
PERSONAS: Dict[str, Dict[str, Any]] = {
    "marina": {
        "id": "marina",
        "name": "Марина",
        "title": "AI-финансовый контролёр",
        "role": "accountant",
        "page": "performance.html",
        "aliases": ("марина", "marina", "бухгалтер", "финансовый контролёр", "финансовый контролер"),
        "capabilities": (
            "сверка P&L, комиссий и движения средств",
            "поиск дублей, пропусков и неклассифицированных операций",
            "точные отчёты за выбранный период",
        ),
    },
    "tolik": {
        "id": "tolik",
        "name": "Толик",
        "title": "AI-аналитик стратегий",
        "role": "strategy_analyst",
        "page": "strategies.html",
        "aliases": ("толик", "tolik", "аналитик стратегий", "стратегический аналитик"),
        "capabilities": (
            "контроль жизненного цикла стратегий",
            "сравнение результатов и поиск методологических рисков",
            "рекомендации до новой разработки и повторного теста",
        ),
    },
    "nikita": {
        "id": "nikita",
        "name": "Никита",
        "title": "AI-новостной аналитик",
        "role": "news_analyst",
        "page": "news.html",
        "aliases": ("никита", "nikita", "новостной агент", "аналитик новостей"),
        "capabilities": (
            "анализ опубликованных и предстоящих рыночных событий",
            "оценка влияния на стратегии и инфраструктуру",
            "срочные рекомендации через Telegram без торговых полномочий",
        ),
    },
}

# Management tiers of the orchestrator itself. Unlike the named specialists,
# these have no personal name — each one is a fixed *seniority* of the same
# manager and deliberately forces a model-complexity tier so the owner can
# consciously choose "quick & cheap" versus "strongest reasoning" instead of
# relying on automatic classification.
MANAGEMENT: Dict[str, Dict[str, Any]] = {
    "secretary": {
        "id": "secretary",
        "name": "",
        "title": "Секретарь управляющего",
        "role": "management",
        "level": 1,
        "forced_complexity": "light",
        "aliases": ("секретарь", "secretary"),
        "hint": "Быстрые команды и простые справки — запустил и отпустил",
    },
    "deputy": {
        "id": "deputy",
        "name": "",
        "title": "Заместитель управляющего",
        "role": "management",
        "level": 2,
        "forced_complexity": "standard",
        "aliases": ("заместитель", "зам", "deputy"),
        "hint": "Средние по сложности задачи и обсуждение",
    },
    "manager": {
        "id": "manager",
        "name": "",
        "title": "Управляющий",
        "role": "management",
        "level": 4,
        "forced_complexity": "critical",
        "aliases": ("управляющий", "главный", "директор", "manager"),
        "hint": "Важные решения, полное обсуждение перед запуском",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return result if result.is_finite() else Decimal("0")


def _money(value: Any) -> str:
    return format(_decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP), "f")


def _usd(value: Any) -> str:
    amount = _money(value)
    return f"-${amount[1:]}" if amount.startswith("-") else f"${amount}"


def _period_query(period: str) -> Tuple[str, Optional[str], Optional[str]]:
    key = str(period or "month").strip().lower()
    if key != "quarter" and key != "all":
        return key if key in {"now", "today", "week", "month", "year"} else "month", None, None
    today = date.today()
    start = date(1970, 1, 1) if key == "all" else today - timedelta(days=89)
    return "custom", start.isoformat(), today.isoformat()


def _in_period(stamp: Any, start: str, end: str) -> bool:
    text = str(stamp or "")[:10]
    return bool(text and start <= text <= end)


def list_personas() -> Dict[str, Any]:
    return {
        "ok": True,
        "routing": "auto_by_task_complexity",
        "agents": [dict(row) for row in PERSONAS.values()],
        "management": [dict(row) for row in MANAGEMENT.values()],
    }


def resolve_management(agent: str) -> Optional[Dict[str, Any]]:
    """Return the management tier for an explicit selector id, else ``None``."""
    key = str(agent or "").strip().lower()
    if key in MANAGEMENT:
        return MANAGEMENT[key]
    for profile in MANAGEMENT.values():
        if key and key in profile["aliases"]:
            return profile
    return None


def resolve_persona(message: str, requested_agent: str = "") -> Optional[Dict[str, Any]]:
    requested = str(requested_agent or "").strip().lower()
    if requested in PERSONAS:
        return PERSONAS[requested]
    text = str(message or "").strip().lower()
    # Addressing must be explicit. Ordinary mentions of accounting or a
    # strategy remain with the orchestrator unless the persona name/title is
    # used near the start of the message.
    head = re.sub(r"^[\s@,.:;!-]+", "", text)[:80]
    for profile in PERSONAS.values():
        if any(head.startswith(alias) for alias in profile["aliases"]):
            return profile
    return None


def _complexity(message: str, role: str) -> str:
    text = str(message or "").lower()
    critical = (
        "аудит", "аномал", "свер", "ошиб", "дублик", "расслед", "почему",
        "риск", "переобуч", "методолог", "сравни", "рекоменд", "прогноз",
    )
    light = ("сколько", "сводк", "статус", "сегодня", "за неделю", "покажи", "что там")
    if any(word in text for word in critical):
        return "critical" if role in {"strategy_analyst", "news_analyst"} else "standard"
    if len(text) < 500 and any(word in text for word in light):
        return "light"
    return "standard"


def accounting_snapshot(period: str = "month", account: str = "", *, repair_safe: bool = False,
                        from_date: Optional[str] = None, to_date: Optional[str] = None) -> Dict[str, Any]:
    if str(period or "").lower() == "custom" and from_date and to_date:
        preset, from_date, to_date = "custom", str(from_date)[:10], str(to_date)[:10]
    else:
        preset, from_date, to_date = _period_query(period)
    perf = performance.build_performance_response(
        period=preset, from_date=from_date, to_date=to_date, account_name=account or None,
    )
    resolved = perf.get("period") or {}
    start, end = str(resolved.get("from") or "0000-01-01"), str(resolved.get("to") or "9999-12-31")
    ledger = account_ledger.account_history(account, limit=5000)
    integrity = account_ledger.audit_integrity(account, repair_safe=repair_safe)
    account_rows: List[Dict[str, Any]] = []
    totals = {kind: Decimal("0") for kind in ("deposit", "withdrawal", "transfer", "fee")}
    needs_review = 0
    for row in ledger.get("accounts") or []:
        events = [event for event in row.get("events") or [] if _in_period(event.get("at_utc"), start, end)]
        flows = {kind: Decimal("0") for kind in totals}
        for event in events:
            if event.get("classification_status") == "needs_review":
                needs_review += 1
            if event.get("classification_status") == "classified" and event.get("kind") in flows:
                flows[str(event["kind"])] += _decimal(event.get("amount"))
        for kind, amount in flows.items():
            totals[kind] += amount
        snapshots = [snap for snap in row.get("snapshots") or [] if _in_period(snap.get("at_utc"), start, end)]
        first, last = (snapshots[0] if snapshots else {}), (snapshots[-1] if snapshots else {})
        account_rows.append({
            "account_name": row.get("account_name"),
            "opening_net_liquidation": _money(first.get("net_liquidation")),
            "closing_net_liquidation": _money(last.get("net_liquidation")),
            "net_liquidation_change": _money(_decimal(last.get("net_liquidation")) - _decimal(first.get("net_liquidation"))),
            "cash_flow": {kind: _money(value) for kind, value in flows.items()},
            "needs_review": sum(1 for event in events if event.get("classification_status") == "needs_review"),
            "events": events[-100:],
        })
    summary = perf.get("strategy_summary") or perf.get("summary") or {}
    trading_pnl = _decimal(summary.get("pnl"))
    commission = _decimal(summary.get("commission"))
    cash_flow = sum(totals.values(), Decimal("0"))
    return {
        "ok": True,
        "generated_at_utc": _now(),
        "agent": {key: PERSONAS["marina"][key] for key in ("id", "name", "title", "page")},
        "calculation_authority": "deterministic_decimal_code",
        "period": {**resolved, "requested": str(period or "month")},
        "account": account or "__all__",
        "summary": {
            "trading_pnl": _money(trading_pnl),
            "gross_pnl": _money(summary.get("gross_pnl")),
            "commission": _money(commission),
            "deposits": _money(totals["deposit"]),
            "withdrawals": _money(totals["withdrawal"]),
            "transfers": _money(totals["transfer"]),
            "fees": _money(totals["fee"]),
            "classified_cash_flow": _money(cash_flow),
            "trades": int(summary.get("trades") or 0),
            "wins": int(summary.get("wins") or 0),
            "losses": int(summary.get("losses") or 0),
            "win_rate": summary.get("win_rate"),
            "profit_factor": summary.get("profit_factor"),
            "needs_review": needs_review,
            "integrity_issues": len(integrity.get("issues") or []),
        },
        "accounts": account_rows,
        "strategies": perf.get("strategies") or [],
        "integrity": integrity,
        "limitations": [
            "Broker cash transaction history is not exported by the current bridge; unexplained balance changes remain unclassified until reviewed.",
            "LLM text is advisory. Monetary fields above are calculated from stored executions and ledger events.",
        ],
    }


def strategy_snapshot(period: str = "month") -> Dict[str, Any]:
    perf = performance.build_performance_response(period=period if period in {"today", "week", "month", "year"} else "month")
    experiments = registry.list_experiments(limit=1000)
    runtime_rows = runtime.read_strategies_raw()
    status_counts: Dict[str, int] = {}
    findings: List[Dict[str, Any]] = []
    for exp in experiments:
        status = str(exp.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        analysis = exp.get("analysis") or {}
        flags: List[str] = []
        trades = int(analysis.get("trades_total") or 0)
        years = int(analysis.get("years_tested") or 0)
        pf = analysis.get("pf_after_commission")
        if exp.get("backtests") and years < 2:
            flags.append("tested_less_than_two_years")
        if exp.get("backtests") and trades < 30:
            flags.append("small_trade_sample")
        if pf is not None and float(pf or 0) >= 3:
            flags.append("suspiciously_high_profit_factor")
        if status in {"compile_failed", "pipeline_failed", "failed"}:
            flags.append("technical_failure")
        if flags:
            findings.append({
                "experiment_id": exp.get("experiment_id"), "class_name": exp.get("class_name"),
                "root": exp.get("target_root"), "status": status, "flags": flags,
                "trades": trades, "years_tested": years, "profit_factor": pf,
            })
    enabled = [row for row in runtime_rows if row.get("enabled")]
    finding_counts: Dict[str, int] = {}
    for finding in findings:
        for flag in finding.get("flags") or []:
            finding_counts[str(flag)] = finding_counts.get(str(flag), 0) + 1
    ranking = sorted(
        perf.get("strategies") or [],
        key=lambda row: (_decimal(row.get("pnl")), _decimal(row.get("profit_factor"))), reverse=True,
    )
    return {
        "ok": True,
        "generated_at_utc": _now(),
        "agent": {key: PERSONAS["tolik"][key] for key in ("id", "name", "title", "page")},
        "calculation_authority": "deterministic_application_data",
        "period": perf.get("period"),
        "summary": {
            "experiments": len(experiments), "status_counts": status_counts,
            "runtime_strategies": len(runtime_rows), "enabled_runtime": len(enabled),
            "strategies_with_trades": len(perf.get("strategies") or []),
            "findings": len(findings), "finding_counts": finding_counts,
        },
        "ranking": ranking[:50],
        "findings": findings[:100],
        "recent_experiments": experiments[-100:],
        "runtime": runtime_rows[:200],
    }


def _fact_block(agent_id: str, snapshot: Dict[str, Any]) -> str:
    summary = snapshot.get("summary") or {}
    if agent_id == "marina":
        return (
            f"Точные данные системы: P&L после комиссий {_usd(summary.get('trading_pnl', '0.00'))}; "
            f"валовый P&L {_usd(summary.get('gross_pnl', '0.00'))}; "
            f"комиссии {_usd(summary.get('commission', '0.00'))}; сделок {summary.get('trades', 0)}; "
            f"операций на проверке {summary.get('needs_review', 0)}; нарушений целостности {summary.get('integrity_issues', 0)}."
        )
    if agent_id == "nikita":
        base = (
            f"Данные новостного контура: значимых событий {summary.get('total', 0)}; "
            f"высокого влияния {summary.get('high', 0)}; с углублённым AI-анализом {summary.get('llm_analyzed', 0)}."
        )
        priority = [str(row.get("title") or "").strip() for row in (snapshot.get("items") or []) if row.get("severity") == "high" and row.get("title")][:3]
        if priority:
            base += " Приоритетные опубликованные события: " + "; ".join(priority) + "."
        return base
    base = (
        f"Точные данные системы: экспериментов {summary.get('experiments', 0)}; "
        f"активных runtime-стратегий {summary.get('enabled_runtime', 0)}; "
        f"замечаний контроля качества {summary.get('findings', 0)}."
    )
    counts = summary.get("finding_counts") or {}
    if not counts:
        return base
    top = max(counts, key=lambda key: int(counts.get(key) or 0))
    recommendations = {
        "tested_less_than_two_years": "запустить полный многолетний тест с отдельным OOS-периодом",
        "small_trade_sample": "расширить период теста до достаточной выборки сделок",
        "suspiciously_high_profit_factor": "провести stress- и OOS-проверку подозрительно сильного результата",
        "technical_failure": "сначала устранить технический сбой и повторить тот же тест без изменения гипотезы",
    }
    return base + f" Главный сигнал: {top} — {counts[top]} записей. Следующий проверяемый шаг: {recommendations.get(top, 'разобрать отмеченные записи по приоритету')}."


def _non_numeric_narrative(text: str) -> str:
    """Keep model judgement while preventing it from overriding exact facts."""
    kept: List[str] = []
    for line in str(text or "").splitlines():
        clean = line.strip()
        if not clean:
            continue
        if re.search(r"\d|[$€£¥₽]|\b(единствен\w*|все|всего|никак\w*|большинств\w*|меньш\w*|больше|половин\w*|кажд\w*|оба|обе)\b", clean, re.IGNORECASE):
            continue
        kept.append(clean)
    return "\n".join(kept)


def _llm_view(agent_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded, secret-free decision context; the UI keeps the full report."""
    if agent_id == "marina":
        accounts = []
        for row in snapshot.get("accounts") or []:
            accounts.append({key: value for key, value in row.items() if key != "events"})
        integrity = snapshot.get("integrity") or {}
        return {
            "period": snapshot.get("period"), "account": snapshot.get("account"),
            "summary": snapshot.get("summary"), "accounts": accounts[:20],
            "integrity": {
                "issues": (integrity.get("issues") or [])[:30],
                "requires_review": integrity.get("requires_review"),
                "repair_policy": integrity.get("repair_policy"),
            },
            "strategies": (snapshot.get("strategies") or [])[:15],
            "limitations": snapshot.get("limitations"),
        }
    if agent_id == "nikita":
        return {
            "summary": snapshot.get("summary"),
            "items": (snapshot.get("items") or [])[:20],
            "source_policy": snapshot.get("source_policy"),
            "execution_authority": False,
        }
    return {
        "period": snapshot.get("period"), "summary": snapshot.get("summary"),
        "ranking": (snapshot.get("ranking") or [])[:15],
        "findings": (snapshot.get("findings") or [])[:30],
        "recent_experiments": (snapshot.get("recent_experiments") or [])[-20:],
        "runtime": (snapshot.get("runtime") or [])[:40],
    }


def answer(agent_id: str, message: str, *, period: str = "month", account: str = "") -> Dict[str, Any]:
    profile = PERSONAS.get(str(agent_id or "").lower())
    if not profile:
        raise ValueError("unknown domain agent")
    if profile["id"] == "marina":
        snapshot = accounting_snapshot(period, account)
    elif profile["id"] == "tolik":
        snapshot = strategy_snapshot(period)
    else:
        snapshot = news_agent.snapshot()
    complexity = _complexity(message, str(profile["role"]))
    system_prompt = (
        f"Ты {profile['name']}, {profile['title']} в StratForge AI. Отвечай по-русски, кратко и предметно. "
        "Все числа из DATA являются авторитетными и рассчитаны кодом. НЕ повторяй никакие числа, суммы, проценты, метрики или количественные слова вроде «все», «единственная», «большинство»: приложение добавит факты отдельно. "
        "Отделяй факт от предположения. При аномалии назови риск и безопасный следующий шаг. "
        "Не обещай выполненное действие, если в DATA нет результата этого действия."
    )
    packet = {"owner_message": str(message)[:6000], "DATA": _llm_view(profile["id"], snapshot)}
    result: Dict[str, Any] = {}
    try:
        result = agent_router.invoke_role(
            str(profile["role"]), json.dumps(packet, ensure_ascii=False, default=str)[:19000],
            system_prompt=system_prompt, max_output_tokens=900 if complexity == "critical" else 500,
            timeout=llm_timeouts.ANALYSIS, purpose=f"domain_agent_{profile['id']}", complexity=complexity,
            cache_mode="auto",
        )
        narrative = _non_numeric_narrative(str(result.get("content") or ""))
        model = str(result.get("actual_model") or result.get("model") or "unknown")
        provider = str(result.get("provider") or "")
    except agent_router.AgentRouterError as exc:
        narrative = f"Модель для пояснения сейчас недоступна: {str(exc)[:300]}"
        model, provider = "deterministic report", "local"
    reply = _fact_block(profile["id"], snapshot)
    if narrative:
        reply += "\n\n" + narrative[:7000]
    return {
        "ok": True, "agent": {key: profile[key] for key in ("id", "name", "title", "page")},
        "reply": reply, "snapshot": snapshot, "model": model, "provider": provider,
        "complexity": complexity, "input_tokens": result.get("input_tokens"),
        "cached_input_tokens": result.get("cached_input_tokens"),
        "output_tokens": result.get("output_tokens"), "cost_usd": result.get("cost_usd"),
    }
