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
        "aliases": ("марина", "марин", "маришк", "marina", "бухгалтер", "финансовый контролёр", "финансовый контролер"),
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
        "aliases": ("толик", "толя", "толян", "анатолий", "tolik", "anatoly", "аналитик стратегий", "стратегический аналитик"),
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
        "aliases": ("никита", "никит", "nikita", "новостной агент", "аналитик новостей"),
        "capabilities": (
            "анализ опубликованных и предстоящих рыночных событий",
            "оценка влияния на стратегии и инфраструктуру",
            "срочные рекомендации через Telegram без торговых полномочий",
        ),
    },
    "ivan": {
        "id": "ivan",
        "name": "Иван",
        "title": "AI-оператор графиков",
        "role": "chart_operator",
        "page": "desktop.html",
        "aliases": ("иван", "ваня", "вань", "ванюш", "иваныч", "ivan", "vanya", "график", "графист", "оператор графиков", "рабочий стол"),
        "capabilities": (
            "рисует линии и отметки на графиках по команде из чата",
            "следит за достижением цены за заданный срок",
            "делает снимок графика и присылает отчёт в чат",
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


# Domain keyword signals used only to decide a *handoff* once a specialist is
# already addressed. They must be specific enough that the responsible expert
# takes over a misdirected request, and forgiving enough that a request which
# also touches the addressed expert's own domain stays with them.
_DOMAIN_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "marina": (
        "бухгалт", "комисси", "депозит", "вывод средств", "вывод денег", "сверк",
        "проводк", "ведомост", "движени средств", "сальдо", "остаток на счёт",
        "остаток на счет", "прибыл", "убыт", "пнл", "p&l", "п&л", "доход", "расход",
        "налог", "дивиденд", "касс", "баланс счёт", "баланс счет", "финансов отчёт",
        "финансов отчет", "заработа", "потеря",
    ),
    "nikita": (
        "новост", "макроэконом", "экономическ календар", "календар событ",
        "заседани фрс", "нонфарм", "инфляц", "cpi", "nfp", "фомс", "fomc",
    ),
    "tolik": (
        "стратег", "бэктест", "backtest", "эксперимент", "переобуч", "оверфит",
        "overfit", "walk-forward", "walk forward", "out-of-sample", "просадк",
        "профит-фактор", "profit factor", "гипотез", "мутаци",
    ),
}


def chart_command_persona(message: str) -> str:
    """Return ``"ivan"`` when the message is a concrete desktop chart command.

    Used to route chart work to the operator even when the owner did not name
    anyone: drawing/opening/clearing a level or asking for a chart snapshot is
    exclusively Иван's job and the orchestrator cannot perform it.

    Deliberately conservative: a bare number without an instrument root (which
    could be an account id, a job id or an amount) is NOT treated as a chart
    command, so unrelated operational messages are never hijacked.
    """
    low = str(message or "").lower()
    has_chart_word = any(word in low for word in ("график", "снимок", "скрин", "рабочий стол"))
    intent = parse_chart_intent(message)
    action = str(intent.get("action") or "")
    root = bool(intent.get("root"))
    if action == "clear" and (root or has_chart_word):
        return "ivan"
    if action in {"draw", "open"} and root:
        return "ivan"
    if action == "snapshot" and (root or has_chart_word):
        return "ivan"
    return ""


def _domain_signals(message: str) -> List[str]:
    """Return the specialist domains a message clearly touches (priority order)."""
    low = str(message or "").lower()
    signals: List[str] = []
    if chart_command_persona(message):
        signals.append("ivan")
    for agent_id in ("marina", "nikita", "tolik"):
        if any(word in low for word in _DOMAIN_KEYWORDS[agent_id]):
            signals.append(agent_id)
    return signals


def route_specialist(addressed_id: str, message: str) -> Tuple[str, str]:
    """Resolve the responsible specialist for a message addressed to ``addressed_id``.

    Returns ``(responder_id, handoff_from_id)``. When the request clearly belongs
    to the addressed expert (or to nobody in particular) it stays with them and
    ``handoff_from`` is empty. When it unambiguously belongs to a different
    expert, that expert takes over and ``handoff_from`` names the misaddressed
    one so the reply can politely note the correction. Specialists never refuse.
    """
    addressed = str(addressed_id or "").lower()
    if addressed not in PERSONAS:
        return addressed, ""
    signals = _domain_signals(message)
    if not signals or addressed in signals:
        return addressed, ""
    return signals[0], addressed


def _domain_scope_phrase(agent_id: str) -> str:
    return {
        "marina": "по бухгалтерии и финансам",
        "tolik": "по стратегиям и исследованиям",
        "nikita": "по новостям и рыночным событиям",
        "ivan": "по графикам",
    }.get(str(agent_id or ""), "по этому вопросу")


def _handoff_note(from_id: str, to_id: str) -> str:
    from_name = PERSONAS.get(str(from_id or ""), {}).get("name") or "другой агент"
    to_name = PERSONAS.get(str(to_id or ""), {}).get("name") or "ответственный"
    return (
        f"Дмитрий Сергеевич, это не {from_name} — {_domain_scope_phrase(to_id)} "
        f"отвечаю я, {to_name}."
    )


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


# =========================  CHART OPERATOR (Иван)  =========================
# Instrument roots the desktop supports, each with Russian/English aliases so
# a spoken command like "поставь линию на нэсдак 21500" resolves to a root.
_CHART_ROOTS: Dict[str, Tuple[str, ...]] = {
    "MBT": ("mbt", "битк", "биткоин", "bitcoin", "btc"),
    "MET": ("met", "эфир", "эфириум", "ether", "eth"),
    "MNQ": ("mnq", "насдак", "нэсдак", "наздак", "nasdaq", "нэсдэк"),
    "MES": ("mes", "сипи", "сп500", "s&p", "sp500", "эсенпи"),
    "MYM": ("mym", "доу", "dow"),
    "M2K": ("m2k", "рассел", "russell"),
    "RTY": ("rty",),
    "MCL": ("mcl", "нефт", "нефть", "oil", "crude"),
    "MNG": ("mng", "газ", "natural gas", "henry hub"),
    "MGC": ("mgc", "золот", "золото", "gold"),
    "SIL": ("sil", "серебр", "серебро", "silver"),
    "MHG": ("mhg", "медь", "copper"),
    "6E": ("евро", "euro", "eurusd", "eur"),
    "6B": ("фунт", "pound", "gbp"),
    "6J": ("иена", "йена", "yen", "jpy"),
    "6A": ("осси", "aud", "australian"),
    "6C": ("канадск", "cad", "canadian"),
    "ZC": ("кукуруз", "corn"),
    "ZW": ("пшениц", "wheat"),
    "ZS": ("соя", "соев", "soybean"),
    "ZN": ("трежерис", "10-year", "10 year", "ust"),
    "ZB": ("бонд", "bond"),
}
_ROOT_TOKENS = set(_CHART_ROOTS.keys())

_DRAWING_ALIASES: Tuple[Tuple[str, str], ...] = (
    ("стрелк", "arrow"), ("arrow", "arrow"),
    ("точк", "point"), ("метк", "point"), ("отмет", "point"), ("point", "point"), ("dot", "point"),
    ("флаг", "flag"), ("flag", "flag"),
    ("цел", "target"), ("мишен", "target"), ("target", "target"),
    ("подпис", "label"), ("label", "label"), ("ярлык", "label"),
    ("лини", "line"), ("уровн", "line"), ("линеечк", "line"), ("line", "line"), ("level", "line"),
)


def _resolve_chart_root(text: str) -> str:
    low = " " + str(text or "").lower() + " "
    best_root, best_len = "", 0
    for root, aliases in _CHART_ROOTS.items():
        for alias in aliases:
            if alias in low and len(alias) > best_len:
                best_root, best_len = root, len(alias)
    if best_root:
        return best_root
    # explicit uppercase root token in the original message
    for token in re.findall(r"[A-Za-z0-9]{2,4}", str(text or "")):
        if token.upper() in _ROOT_TOKENS:
            return token.upper()
    return ""


def _extract_duration_minutes(text: str) -> Tuple[Optional[int], str]:
    """Return (minutes, matched_substring) for phrases like 'за 60 минут'."""
    low = str(text or "").lower()
    pat = re.compile(r"(\d+(?:[.,]\d+)?)\s*(секунд\w*|сек\b|мин\w*|час\w*|ч\b|дн\w*|день|сут\w*|недел\w*)")
    for m in pat.finditer(low):
        value = float(m.group(1).replace(",", "."))
        unit = m.group(2)
        if unit.startswith("сек") or unit == "сек":
            minutes = max(1, round(value / 60))
        elif unit.startswith("мин"):
            minutes = round(value)
        elif unit.startswith("час") or unit == "ч":
            minutes = round(value * 60)
        elif unit.startswith("недел"):
            minutes = round(value * 60 * 24 * 7)
        else:  # дни / сутки
            minutes = round(value * 60 * 24)
        return max(1, min(525600, int(minutes))), m.group(0)
    return None, ""


def _extract_price(text: str, exclude: Any = "") -> Optional[float]:
    cleaned = str(text or "")
    spans = exclude if isinstance(exclude, (list, tuple, set)) else [exclude]
    for span in spans:
        span = str(span or "").strip()
        if span:
            cleaned = cleaned.replace(span, " ")
    # remove known root tokens so digits inside a symbol are not mistaken for price
    for token in re.findall(r"[A-Za-z0-9]{2,4}", cleaned):
        if token.upper() in _ROOT_TOKENS:
            cleaned = cleaned.replace(token, " ")
    # thousands with spaces (21 500) or plain / decimal numbers
    grouped = re.search(r"\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?", cleaned)
    if grouped:
        try:
            return float(grouped.group(0).replace("\u00a0", "").replace(" ", "").replace(",", "."))
        except ValueError:
            pass
    for m in re.finditer(r"\d+(?:[.,]\d+)?", cleaned):
        try:
            value = float(m.group(0).replace(",", "."))
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def _extract_delay_seconds(text: str) -> Tuple[Optional[int], str]:
    """Return (seconds, matched) for a *delay* like 'через 30 секунд' / 'через минуту'.

    Distinct from a watch window ('за N минут'): a delay uses через/спустя/in.
    """
    low = str(text or "").lower()
    pat = re.compile(r"(?:через|спустя|in)\s+(\d+(?:[.,]\d+)?)\s*(секунд\w*|сек\b|мин\w*|час\w*|ч\b)")
    m = pat.search(low)
    if m:
        value = float(m.group(1).replace(",", "."))
        unit = m.group(2)
        if unit.startswith("сек") or unit == "сек":
            secs = value
        elif unit.startswith("мин"):
            secs = value * 60
        else:
            secs = value * 3600
        return max(1, min(31 * 24 * 3600, int(round(secs)))), m.group(0)
    # number-less forms: "через минуту", "через час", "через секунду"
    for phrase, secs in (("через секунд", 5), ("спустя секунд", 5),
                         ("через полминуты", 30), ("через минуту", 60), ("спустя минуту", 60),
                         ("через час", 3600), ("спустя час", 3600)):
        if phrase in low:
            return secs, phrase
    return None, ""


def _extract_timeframe(text: str) -> str:
    low = str(text or "").lower()
    m = re.search(r"\b(\d+)\s*(m|м|мин|h|ч|час)\b", low)
    if m:
        num = m.group(1)
        unit = m.group(2)
        if unit in ("h", "ч", "час"):
            return f"{num}h"
        return f"{num}m"
    if "дневн" in low or "1d" in low or "1д" in low:
        return "1D"
    return ""


def parse_chart_intent(message: str) -> Dict[str, Any]:
    """Deterministically extract a chart operation from an owner command."""
    text = str(message or "").strip()
    low = text.lower()
    intent: Dict[str, Any] = {"action": "", "root": _resolve_chart_root(text)}

    if any(word in low for word in ("очист", "убер", "сотр", "удали все", "clear")):
        intent["action"] = "clear"
        return intent

    delay_seconds, delay_span = _extract_delay_seconds(text)
    dur_minutes, dur_span = _extract_duration_minutes(text)
    # If the same phrase matched both, it is a delay ("через N"), not a window.
    if delay_span and dur_span and (dur_span in delay_span or delay_span in dur_span):
        dur_minutes = None
    price = _extract_price(text, exclude=[delay_span, dur_span])
    want_snapshot = any(word in low for word in (
        "снимок", "снимк", "скрин", "скриншот", "сфотограф", "фото", "снять график"))
    want_report = want_snapshot or any(word in low for word in (
        "отчит", "отчёт", "отчет", "сообщи", "сообщить", "уведоми", "доложи", "пришли", "report"))
    want_open = any(word in low for word in (
        "открой", "открыть", "покажи", "показать", "выведи", "вывести", "open", "загрузи"))

    drawing_type = "line"
    for needle, mapped in _DRAWING_ALIASES:
        if needle in low:
            drawing_type = mapped
            break
    if drawing_type == "arrow":
        if "вниз" in low or "down" in low or "падени" in low or "продаж" in low or "шорт" in low:
            drawing_type = "arrow_down"
        elif "вверх" in low or "up" in low or "рост" in low or "покупк" in low or "лонг" in low:
            drawing_type = "arrow_up"

    # Bare snapshot request without a price level → snapshot of a chart (the
    # named instrument, or the currently active one), now or after a delay.
    if want_snapshot and price is None:
        intent["action"] = "snapshot"
        intent["delay_seconds"] = delay_seconds or 0
        intent["timeframe"] = _extract_timeframe(text)
        return intent

    # "Открой график MNQ" (без снимка) → just open + fit the chart.
    if want_open and price is None and intent.get("root"):
        intent["action"] = "open"
        intent["timeframe"] = _extract_timeframe(text)
        return intent

    if price is not None:
        report_mode = "touch"
        if dur_minutes:
            # "дойдёт или не дойдёт — отчитайся" → report on both outcomes.
            report_mode = "both" if want_report else "touch"
        # Иван reports with a chart snapshot — that IS his report, so any request
        # to watch / report a level uses the snapshot rule (image + text to chat).
        rule = "snapshot" if want_report else "none"
        intent.update({
            "action": "draw",
            "type": drawing_type,
            "price": price,
            "timeframe": _extract_timeframe(text),
            "duration_minutes": dur_minutes or 0,
            "rule": rule,
            "report_mode": report_mode,
            "snapshot": rule == "snapshot",
        })
        return intent

    return intent


_DRAWING_HUMAN = {
    "line": "горизонтальную линию", "point": "точку", "arrow": "стрелку",
    "arrow_up": "стрелку вверх", "arrow_down": "стрелку вниз",
    "flag": "флажок", "target": "цель", "label": "подпись",
}


def _fmt_price(value: float) -> str:
    if value == int(value):
        return f"{int(value)}"
    return f"{value:g}"


def _fmt_duration(minutes: int) -> str:
    if minutes % (60 * 24) == 0:
        days = minutes // (60 * 24)
        return f"{days} дн."
    if minutes % 60 == 0:
        return f"{minutes // 60} ч."
    return f"{minutes} мин."


def _fmt_delay(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds} сек."
    if seconds % 3600 == 0:
        return f"{seconds // 3600} ч."
    if seconds % 60 == 0:
        return f"{seconds // 60} мин."
    return f"{seconds // 60} мин. {seconds % 60} сек."


def chart_task_acknowledgement(*, instrument: str = "", price: Any = None,
                               drawing_type: str = "line", label: str = "",
                               delay_seconds: int = 0, duration_minutes: int = 0,
                               report_mode: str = "touch", action: str = "snapshot") -> str:
    """Иван's spoken confirmation of a task configured from the desktop editor.

    Mirrors the phrasing of :func:`chart_operator_answer` so a поручение created
    with the on-chart drawing editor reads the same as one dictated in the chat.
    """
    root = " ".join(str(instrument or "").strip().upper().split())
    delay = int(delay_seconds or 0)
    duration = int(duration_minutes or 0)
    mode = str(report_mode or "touch").strip().lower()
    lines: List[str] = []
    try:
        level = float(price) if price is not None and str(price) != "" else None
    except (TypeError, ValueError):
        level = None

    if str(action) == "agent":
        where = f" на {root}" if root else ""
        lvl = f" по уровню {_fmt_price(level)}" if level is not None else ""
        lines.append(f"Принял поручение{where}{lvl}. Беру в работу и отчитаюсь в этот чат.")
        if duration:
            lines.append(f"Слежу {_fmt_duration(duration)} и вернусь с результатом.")
        return "\n".join(lines)

    human = _DRAWING_HUMAN.get(str(drawing_type or "line"), "отметку")
    if level is not None and root:
        lines.append(f"Готово — ставлю {human} на {root} по уровню {_fmt_price(level)}.")
    elif root:
        lines.append(f"Принял задачу по {root}.")
    else:
        lines.append("Принял задачу по активному графику.")

    if delay:
        lines.append(f"Сделаю снимок через {_fmt_delay(delay)} и пришлю его в этот чат.")
    elif level is not None and duration:
        if mode == "both":
            lines.append(
                f"Слежу {_fmt_duration(duration)}: как только цена коснётся уровня — пришлю снимок "
                "графика в этот чат; если не дойдёт за это время — тоже пришлю снимок и сообщу, "
                "что уровень не достигнут.")
        elif mode == "expire":
            lines.append(
                f"Если за {_fmt_duration(duration)} цена не дойдёт до уровня — пришлю снимок графика "
                "и сообщу, что уровень не достигнут.")
        else:
            lines.append(
                f"Как только цена коснётся уровня в течение {_fmt_duration(duration)} — пришлю снимок "
                "графика в этот чат.")
    elif level is not None:
        lines.append("Как только цена коснётся уровня — пришлю снимок графика в этот чат.")
    else:
        lines.append("Сделаю снимок и пришлю его в этот чат.")
    lines.append("⚠️ Для рисования и снимков «Рабочий стол» должен быть открыт в приложении.")
    return "\n".join(lines)


def chart_operator_answer(message: str, *, conversation_id: str = "") -> Dict[str, Any]:
    """Иван — turns a chat command into a live chart action via the command queue."""
    from .. import market_data  # local import avoids any import cycle at load time

    profile = PERSONAS["ivan"]
    intent = parse_chart_intent(message)
    action = intent.get("action")
    reply_lines: List[str] = []
    queued: List[str] = []

    def _base_result(reply: str) -> Dict[str, Any]:
        return {
            "ok": True, "agent": {key: profile[key] for key in ("id", "name", "title", "page")},
            "reply": reply, "snapshot": {}, "model": "chart operator", "provider": "local",
            "complexity": "light", "actions": queued,
        }

    if action == "clear":
        try:
            market_data.enqueue_chart_command({
                "type": "clear", "instrument": intent.get("root") or "",
                "conversation_id": conversation_id, "agent_id": "ivan",
                "note": "Убрать отметки с графиков",
            })
            queued.append("clear")
        except market_data.MarketDataError:
            pass
        return _base_result(
            "Убрал отметки" + (f" по {intent['root']}" if intent.get("root") else " со всех графиков")
            + ". Если «Рабочий стол» открыт — изменения уже применены.")

    if action == "snapshot":
        delay = int(intent.get("delay_seconds") or 0)
        root = intent.get("root") or ""
        market_data.enqueue_chart_command({
            "type": "snapshot", "instrument": root, "timeframe": intent.get("timeframe") or "",
            "delay_seconds": delay,
            "conversation_id": conversation_id, "agent_id": "ivan",
            "note": message[:400],
            "payload": {"fit": True},
        })
        queued.append("snapshot")
        target = root if root else "текущего графика"
        when = f"через {_fmt_delay(delay)}" if delay else "сейчас"
        return _base_result(
            f"Принял. Сделаю снимок {target} {when} и пришлю его в этот чат.\n"
            "⚠️ «Рабочий стол» должен быть открыт в приложении.")

    if action == "open":
        root = intent.get("root") or ""
        market_data.enqueue_chart_command({
            "type": "open", "instrument": root, "timeframe": intent.get("timeframe") or "",
            "conversation_id": conversation_id, "agent_id": "ivan",
            "note": message[:400], "payload": {"fit": True},
        })
        queued.append("open")
        return _base_result(
            f"Открываю график {root} и настраиваю удобный вид. Скажите «сделай снимок», если нужно прислать его в чат.")

    if action == "draw":
        root = intent.get("root")
        price = intent.get("price")
        if not root:
            return _base_result(
                "Понял уровень " + _fmt_price(float(price)) + ", но не разобрал инструмент. "
                "Уточните, например: «поставь линию на MNQ " + _fmt_price(float(price)) + "».")
        payload = {
            "drawing": {
                "type": intent.get("type") or "line",
                "price": float(price),
                "label": f"{profile['name']}: {_fmt_price(float(price))}",
                "color": "#4fd1e0",
                "duration_minutes": int(intent.get("duration_minutes") or 0),
                "rule": intent.get("rule") or "none",
                "report_mode": intent.get("report_mode") or "touch",
                "snapshot": bool(intent.get("snapshot")),
            },
        }
        market_data.enqueue_chart_command({
            "type": "draw", "instrument": root, "timeframe": intent.get("timeframe") or "",
            "payload": payload, "conversation_id": conversation_id, "agent_id": "ivan",
            "note": message[:400],
        })
        queued.append("draw")
        human = _DRAWING_HUMAN.get(intent.get("type") or "line", "отметку")
        reply_lines.append(f"Готово — ставлю {human} на {root} по уровню {_fmt_price(float(price))}.")
        rule = intent.get("rule")
        if rule == "snapshot" or intent.get("snapshot"):
            if intent.get("duration_minutes"):
                if intent.get("report_mode") == "both":
                    reply_lines.append(
                        f"Слежу {_fmt_duration(int(intent['duration_minutes']))}: как только цена коснётся уровня — "
                        "пришлю снимок графика в этот чат; если не дойдёт за это время — тоже пришлю снимок и сообщу, что уровень не достигнут.")
                else:
                    reply_lines.append(
                        f"Как только цена коснётся уровня в течение {_fmt_duration(int(intent['duration_minutes']))} — "
                        "пришлю снимок графика в этот чат.")
            else:
                reply_lines.append("Как только цена коснётся уровня — пришлю снимок графика в этот чат.")
        elif rule == "agent":
            if intent.get("duration_minutes"):
                reply_lines.append(
                    f"Слежу {_fmt_duration(int(intent['duration_minutes']))} и отчитаюсь о достижении уровня в этот чат.")
            else:
                reply_lines.append("Отчитаюсь в этот чат, как только цена коснётся уровня.")
        reply_lines.append("⚠️ Для рисования и снимков «Рабочий стол» должен быть открыт в приложении.")
        return _base_result("\n".join(reply_lines))

    # No actionable command recognised — explain capabilities briefly.
    return _base_result(
        "Я — Иван, оператор графиков. Управляю «Рабочим столом» по вашим командам:\n"
        "• «поставь линию на MNQ 21500» — нарисую уровень на графике;\n"
        "• «отметь 21500 на MNQ, если дойдёт за 60 минут — снимок в чат» — поставлю уровень, буду следить и пришлю снимок;\n"
        "• «сделай снимок MES» — пришлю текущий снимок графика;\n"
        "• «убери отметки с MNQ» — очищу разметку.\n"
        "Скажите инструмент и цену — и я всё сделаю.")


def answer(agent_id: str, message: str, *, period: str = "month", account: str = "",
           conversation_id: str = "") -> Dict[str, Any]:
    addressed = str(agent_id or "").lower()
    if addressed not in PERSONAS:
        raise ValueError("unknown domain agent")
    # A misaddressed request is handled by the responsible specialist, who
    # politely notes the correction. No specialist ever refuses a request that
    # belongs to a colleague; it is simply routed to the right person.
    responder_id, handoff_from = route_specialist(addressed, message)
    profile = PERSONAS[responder_id]
    if profile["id"] == "ivan":
        result = chart_operator_answer(message, conversation_id=conversation_id)
        if handoff_from:
            result["reply"] = _handoff_note(handoff_from, responder_id) + "\n\n" + str(result.get("reply") or "")
            result["handoff_from"] = handoff_from
        return result
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
    if handoff_from:
        reply = _handoff_note(handoff_from, profile["id"]) + "\n\n" + reply
    return {
        "ok": True, "agent": {key: profile[key] for key in ("id", "name", "title", "page")},
        "reply": reply, "snapshot": snapshot, "model": model, "provider": provider,
        "complexity": complexity, "input_tokens": result.get("input_tokens"),
        "cached_input_tokens": result.get("cached_input_tokens"),
        "output_tokens": result.get("output_tokens"), "cost_usd": result.get("cost_usd"),
        "handoff_from": handoff_from or None,
    }
