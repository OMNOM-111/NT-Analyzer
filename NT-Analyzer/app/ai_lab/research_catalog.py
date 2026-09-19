"""Persistent research projects and their strategy-family evidence tree.

The older :mod:`user_research` module ingests loose files.  This module adds a
first-class project around those files so AI Lab can remember *why* strategies
are being produced, which family they belong to, and when enough negative
evidence has accumulated to stop spending research budget.
"""

from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import paths
from .io_utils import read_json, write_json_atomic


SCHEMA_VERSION = "1.0"
SOURCE_TYPES = {
    "research": "Исследование",
    "collection": "Сборник исследований",
    "personal_idea": "Личная идея",
}
DEFAULT_POLICY: Dict[str, Any] = {
    "min_strategies_to_decide": 5,
    "target_strategies": 8,
    "max_strategies": 10,
    "min_variants_per_strategy": 3,
    "required_profitable_strategies": 1,
    "min_profit_factor": 1.15,
    "min_trades": 100,
    "min_years_tested": 2.0,
}
_CATALOG_NAME = "research_catalog.json"
_LOCK = threading.RLock()

_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
})


class ResearchCatalogError(ValueError):
    """A user-correctable research catalog request error."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _catalog_path() -> Path:
    return paths.REGISTRY_DIR / _CATALOG_NAME


def _load() -> Dict[str, Any]:
    data = read_json(_catalog_path(), default={}) or {}
    rows = data.get("researches")
    if not isinstance(rows, list):
        rows = []
    return {"schema_version": SCHEMA_VERSION, "researches": rows}


def _save(data: Dict[str, Any]) -> None:
    data["schema_version"] = SCHEMA_VERSION
    data["updated_at_utc"] = _now()
    write_json_atomic(_catalog_path(), data)


def _clean_text(value: Any, limit: int = 250_000) -> str:
    text = str(value or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    return text[:limit]


def _as_lines(value: Any, *, limit: int = 30) -> List[str]:
    if isinstance(value, list):
        source: Iterable[Any] = value
    else:
        source = re.split(r"[\n;]+", str(value or ""))
    out: List[str] = []
    seen = set()
    for raw in source:
        item = re.sub(r"^\s*[-*\d.)]+\s*", "", _clean_text(raw, 500)).strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _title_from_content(content: str) -> str:
    for raw in content.splitlines():
        line = re.sub(r"^\s*#+\s*", "", raw).strip(" -\t")
        if line:
            return line[:120]
    return "Новое исследование"


def _summary_from_content(content: str, title: str) -> str:
    paragraphs = [re.sub(r"\s+", " ", p).strip(" #-\t") for p in re.split(r"\n\s*\n", content)]
    for paragraph in paragraphs:
        if paragraph and paragraph.casefold() != title.casefold():
            return paragraph[:360].rstrip()
    return f"Материал «{title}» добавлен в исследовательский контур AI Lab."


def _family_key(value: str, fallback_id: str = "") -> str:
    latin = value.lower().translate(_TRANSLIT)
    tokens = re.findall(r"[a-z0-9]+", latin)
    key = "".join(token[:1].upper() + token[1:] for token in tokens)[:64]
    if not key:
        digits = re.sub(r"\D", "", fallback_id)[-8:]
        key = "Research" + (digits or "Family")
    if key[0].isdigit():
        key = "Research" + key
    return key


def _requested_family_key(payload: Dict[str, Any], family_name: str, research_id: str) -> str:
    explicit = str(payload.get("family_key") or "").strip()
    if explicit and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", explicit):
        return explicit
    return _family_key(explicit or family_name, research_id)


def _policy(value: Any) -> Dict[str, Any]:
    incoming = value if isinstance(value, dict) else {}

    def integer(name: str, low: int, high: int) -> int:
        try:
            parsed = int(incoming.get(name, DEFAULT_POLICY[name]))
        except (TypeError, ValueError):
            parsed = int(DEFAULT_POLICY[name])
        return max(low, min(high, parsed))

    def number(name: str, low: float, high: float) -> float:
        try:
            parsed = float(incoming.get(name, DEFAULT_POLICY[name]))
        except (TypeError, ValueError):
            parsed = float(DEFAULT_POLICY[name])
        return max(low, min(high, parsed))

    minimum = integer("min_strategies_to_decide", 1, 50)
    target = max(minimum, integer("target_strategies", 1, 50))
    maximum = max(target, integer("max_strategies", 1, 50))
    return {
        "min_strategies_to_decide": minimum,
        "target_strategies": target,
        "max_strategies": maximum,
        "min_variants_per_strategy": integer("min_variants_per_strategy", 1, 50),
        "required_profitable_strategies": integer("required_profitable_strategies", 1, 20),
        "min_profit_factor": number("min_profit_factor", 0.1, 10.0),
        "min_trades": integer("min_trades", 1, 100_000),
        "min_years_tested": number("min_years_tested", 0.0, 50.0),
    }


def _next_id(rows: List[Dict[str, Any]]) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"RES-{day}-"
    seq = 0
    for row in rows:
        rid = str(row.get("research_id") or "")
        if rid.startswith(prefix):
            try:
                seq = max(seq, int(rid.rsplit("-", 1)[-1]))
            except ValueError:
                continue
    return f"{prefix}{seq + 1:04d}"


def _knowledge_path(research_id: str) -> Path:
    return paths.USER_RESEARCH_DIR / "curated" / "researches" / f"{research_id}.md"


def _render_ai_markdown(row: Dict[str, Any]) -> str:
    policy = row["evaluation_policy"]
    objectives = row.get("objectives") or ["Проверить исходный материал через независимые торговые гипотезы."]
    hypotheses = row.get("hypotheses") or ["Гипотезы будут сформулированы в ходе первого цикла."]
    linked = row.get("linked_research_ids") or []
    lines = [
        f"# {row['title']}", "",
        "## AI metadata",
        f"- Research ID: {row['research_id']}",
        f"- Type: {SOURCE_TYPES.get(row['source_type'], row['source_type'])}",
        f"- Strategy family: {row['family_name']} (`{row['family_key']}`)",
        f"- Source: {row.get('source_name') or 'manual input'}",
        f"- Content SHA-256: {row['content_sha256']}",
    ]
    if linked:
        lines.append(f"- Linked researches: {', '.join(linked)}")
    lines += ["", "## Краткий вывод", row["summary"], "", "## Цели"]
    lines += [f"- {item}" for item in objectives]
    lines += ["", "## Проверяемые гипотезы"]
    lines += [f"- {item}" for item in hypotheses]
    linked_strategies = [item for item in (row.get("linked_strategies") or []) if isinstance(item, dict)]
    if linked_strategies:
        lines += ["", "## Связанные стратегии и профили"]
        lines += [
            f"- {item.get('name') or item.get('profile_id')} | family={item.get('strategy_family') or row.get('family_key')} | "
            f"status={'archived' if item.get('archived') else item.get('lifecycle') or item.get('status') or 'working'} | "
            f"instrument={item.get('instrument') or item.get('root_family') or 'unknown'} | timeframe={item.get('timeframe') or 'unknown'}"
            for item in linked_strategies
        ]
    lines += [
        "", "## Протокол остановки",
        f"- Минимум стратегий до предварительного решения: {policy['min_strategies_to_decide']}",
        f"- Целевое количество стратегий: {policy['target_strategies']}",
        f"- Жёсткий максимум стратегий: {policy['max_strategies']}",
        f"- Вариантов параметров на стратегию: не менее {policy['min_variants_per_strategy']}",
        f"- Требуется прибыльных стратегий: {policy['required_profitable_strategies']}",
        f"- Порог PF после комиссии: {policy['min_profit_factor']}",
        f"- Минимум сделок: {policy['min_trades']}",
        f"- Минимум лет истории: {policy['min_years_tested']}",
        "- Технические ошибки компиляции/данных не считаются отрицательным торговым результатом.",
        "", "## Исходный материал", row["source_content"] or "Материал не указан.", "",
    ]
    return "\n".join(lines)


def _write_knowledge(row: Dict[str, Any]) -> None:
    target = _knowledge_path(str(row["research_id"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_ai_markdown(row), encoding="utf-8")
    row["knowledge_rel_path"] = target.relative_to(paths.USER_RESEARCH_DIR).as_posix()


def create(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a research and an AI-ready Markdown knowledge document."""
    with _LOCK:
        data = _load()
        rows = data["researches"]
        content = _clean_text(payload.get("content") or payload.get("source_content"))
        supplied_title = _clean_text(payload.get("title"), 120)
        if not content and not supplied_title:
            raise ResearchCatalogError("Укажите название или исходный материал исследования.")
        title = supplied_title or _title_from_content(content)
        source_type = str(payload.get("source_type") or "research")
        if source_type not in SOURCE_TYPES:
            raise ResearchCatalogError("Неизвестный тип исследования.")
        research_id = _next_id(rows)
        family_name = _clean_text(payload.get("family_name"), 120) or title
        now = _now()
        linked = [
            str(value) for value in (payload.get("linked_research_ids") or [])
            if any(str(row.get("research_id")) == str(value) for row in rows)
        ][:50]
        row: Dict[str, Any] = {
            "research_id": research_id,
            "source_type": source_type,
            "title": title,
            "family_name": family_name,
            "family_key": _requested_family_key(payload, family_name, research_id),
            "summary": _clean_text(payload.get("summary"), 500) or _summary_from_content(content, title),
            "objectives": _as_lines(payload.get("objectives")),
            "hypotheses": _as_lines(payload.get("hypotheses")),
            "source_name": _clean_text(payload.get("source_name"), 180),
            "source_format": _clean_text(payload.get("source_format"), 40) or "plain_text",
            "source_content": content,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "linked_research_ids": list(dict.fromkeys(linked)),
            "linked_strategies": [
                dict(item) for item in (payload.get("linked_strategies") or [])
                if isinstance(item, dict)
            ][:500],
            "import_key": _clean_text(payload.get("import_key"), 260),
            "migration_source": _clean_text(payload.get("migration_source"), 120),
            "evaluation_policy": _policy(payload.get("evaluation_policy")),
            "manual_status": str(payload.get("manual_status") or "") if str(payload.get("manual_status") or "") in {"", "active", "paused", "archived"} else "",
            "owner_conclusion": _clean_text(payload.get("owner_conclusion"), 2000),
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        _write_knowledge(row)
        rows.append(row)
        _save(data)
        return detail(research_id, _data=data)


def update(research_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Update editable metadata without losing linked experiment evidence."""
    with _LOCK:
        data = _load()
        row = next((item for item in data["researches"] if item.get("research_id") == research_id), None)
        if row is None:
            raise ResearchCatalogError(f"Исследование не найдено: {research_id}")
        for key, limit in (("title", 120), ("family_name", 120), ("summary", 500),
                           ("source_name", 180), ("owner_conclusion", 2000)):
            if key in payload:
                value = _clean_text(payload.get(key), limit)
                if key in {"title", "family_name"} and not value:
                    raise ResearchCatalogError(f"Поле {key} не может быть пустым.")
                row[key] = value
        if "source_type" in payload:
            value = str(payload.get("source_type") or "")
            if value not in SOURCE_TYPES:
                raise ResearchCatalogError("Неизвестный тип исследования.")
            row["source_type"] = value
        if "source_content" in payload or "content" in payload:
            content = _clean_text(payload.get("source_content") or payload.get("content"))
            row["source_content"] = content
            row["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if "source_format" in payload:
            row["source_format"] = _clean_text(payload.get("source_format"), 40) or "plain_text"
        if "objectives" in payload:
            row["objectives"] = _as_lines(payload.get("objectives"))
        if "hypotheses" in payload:
            row["hypotheses"] = _as_lines(payload.get("hypotheses"))
        if "evaluation_policy" in payload:
            row["evaluation_policy"] = _policy(payload.get("evaluation_policy"))
        if "manual_status" in payload:
            status = str(payload.get("manual_status") or "")
            if status not in {"", "active", "paused", "archived"}:
                raise ResearchCatalogError("Недопустимый ручной статус исследования.")
            row["manual_status"] = status
        if "linked_research_ids" in payload:
            known = {str(item.get("research_id")) for item in data["researches"]}
            row["linked_research_ids"] = list(dict.fromkeys(
                str(value) for value in (payload.get("linked_research_ids") or [])
                if str(value) in known and str(value) != research_id
            ))[:50]
        if "linked_strategies" in payload:
            row["linked_strategies"] = [
                dict(item) for item in (payload.get("linked_strategies") or [])
                if isinstance(item, dict)
            ][:500]
        row["family_key"] = _requested_family_key(
            payload,
            str(row.get("family_name") or row.get("title") or ""),
            research_id,
        ) if "family_key" in payload else str(row.get("family_key") or _family_key(str(row.get("family_name") or ""), research_id))
        row["updated_at_utc"] = _now()
        _write_knowledge(row)
        _save(data)
        return detail(research_id, _data=data)


def _metric(exp: Dict[str, Any], *names: str) -> Optional[float]:
    sources = [
        exp.get("analysis") if isinstance(exp.get("analysis"), dict) else {},
        exp.get("decision") if isinstance(exp.get("decision"), dict) else {},
    ]
    backtests = [item for item in (exp.get("backtests") or []) if isinstance(item, dict)]
    if backtests:
        sources.append(backtests[-1])
    for source in sources:
        for name in names:
            value = source.get(name)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
    return None


def _variant_count(exp: Dict[str, Any]) -> int:
    history = [item for item in (exp.get("iteration_history") or []) if isinstance(item, dict)]
    if history:
        return len(history)
    backtests = [item for item in (exp.get("backtests") or []) if isinstance(item, dict)]
    return max(1, len(backtests))


def _is_technical_failure(exp: Dict[str, Any]) -> bool:
    status = str(exp.get("status") or "")
    return status in {
        "compile_failed", "pipeline_failed", "failed", "blocked_lm_studio",
        "blocked_compile_environment", "blocked_backtest_infrastructure",
    }


def _is_running(exp: Dict[str, Any]) -> bool:
    status = str(exp.get("status") or "")
    return status in {
        "draft", "designing", "draft_ready", "generating", "validating", "compiling",
        "backtesting", "running", "in_progress", "mutating",
    }


def _has_result(exp: Dict[str, Any]) -> bool:
    if _is_technical_failure(exp) or _is_running(exp):
        return False
    return bool(exp.get("analysis") or exp.get("backtests") or exp.get("verdict"))


def _qualifies(exp: Dict[str, Any], policy: Dict[str, Any]) -> bool:
    if _variant_count(exp) < int(policy["min_variants_per_strategy"]):
        return False
    lifecycle_pass = str(exp.get("status") or "") in {"candidate", "champion", "portfolio_contributor"}
    verdict = exp.get("verdict") if isinstance(exp.get("verdict"), dict) else {}
    if lifecycle_pass or str(verdict.get("outcome") or "") in {"candidate", "champion", "accept"}:
        return True
    pf = _metric(exp, "pf_after_commission", "profit_factor", "pf")
    trades = _metric(exp, "trades_total", "trade_count", "trades")
    years = _metric(exp, "years_tested", "years")
    return bool(
        pf is not None and pf >= float(policy["min_profit_factor"])
        and trades is not None and trades >= int(policy["min_trades"])
        and years is not None and years >= float(policy["min_years_tested"])
    )


def _period(exp: Dict[str, Any]) -> Dict[str, Any]:
    backtests = [item for item in (exp.get("backtests") or []) if isinstance(item, dict)]
    evidence = backtests[-1] if backtests else {}
    period = evidence.get("period") if isinstance(evidence.get("period"), dict) else {}
    return {
        "instrument": evidence.get("instrument") or exp.get("target_root"),
        "timeframe": evidence.get("timeframe") or evidence.get("bar_period") or exp.get("timeframe") or "—",
        "from_utc": period.get("from_utc") or evidence.get("from_utc"),
        "to_utc": period.get("to_utc") or evidence.get("to_utc"),
    }


def _strategy_node(exp: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    pf = _metric(exp, "pf_after_commission", "profit_factor", "pf")
    pnl = _metric(exp, "net_profit_after_commission", "net_profit", "net_pnl", "pnl")
    raw_variants = [item for item in (exp.get("iteration_history") or []) if isinstance(item, dict)]
    if not raw_variants:
        raw_variants = [{
            "iteration": 1,
            "status": exp.get("status"),
            "parameters": exp.get("parameters") or {},
            "profit_factor": pf,
            "net_profit": pnl,
        }]
    variants: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_variants, start=1):
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}

        def variant_metric(*names: str) -> Optional[float]:
            for source in (item, metrics, analysis):
                for name in names:
                    if source.get(name) is not None:
                        try:
                            return float(source[name])
                        except (TypeError, ValueError):
                            continue
            return None

        variants.append({
            "iteration": item.get("iteration") or item.get("iteration_idx") or index,
            "status": item.get("status") or item.get("outcome") or exp.get("status"),
            "parameters": item.get("parameters") or {},
            "profit_factor": variant_metric("pf_after_commission", "profit_factor", "pf"),
            "net_profit": variant_metric("net_profit_after_commission", "net_profit", "net_pnl", "pnl"),
        })
    if variants and all(item.get("profit_factor") is None for item in variants):
        variants[-1]["profit_factor"] = pf
        variants[-1]["net_profit"] = pnl
    best_parameter_variant = max(
        variants,
        key=lambda item: (item.get("profit_factor") if item.get("profit_factor") is not None else -999,
                          item.get("net_profit") if item.get("net_profit") is not None else -999999999),
    ) if variants else None
    return {
        "experiment_id": exp.get("experiment_id"),
        "class_name": exp.get("class_name") or exp.get("ai_cell_id") or exp.get("experiment_id"),
        "status": exp.get("status"),
        "hypothesis": exp.get("hypothesis"),
        "qualifies": _qualifies(exp, policy),
        "profit_factor": pf,
        "net_profit": pnl,
        # Deepest equity drop after commission, in account currency (negative).
        "max_drawdown": _metric(exp, "dd_after_commission", "max_drawdown"),
        "variant_count": _variant_count(exp),
        "variants": variants,
        "best_parameter_variant": best_parameter_variant,
        "best_window": _period(exp),
        "inventory_source": "ai_experiment",
        "archived": False,
    }


def _legacy_metric(link: Dict[str, Any], *names: str) -> Optional[float]:
    metrics = link.get("metrics") if isinstance(link.get("metrics"), dict) else {}
    for name in names:
        if metrics.get(name) is not None:
            try:
                return float(metrics[name])
            except (TypeError, ValueError):
                continue
    return None


def _legacy_strategy_node(link: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    pf = _legacy_metric(link, "profit_factor_after_commission", "pf_after_commission", "profit_factor", "pf")
    pnl = _legacy_metric(link, "net_profit_after_commission", "net_profit", "net_pnl", "pnl")
    trades = _legacy_metric(link, "trade_count", "trades_total", "trades")
    archived = bool(link.get("archived"))
    lifecycle = str(link.get("lifecycle") or link.get("status") or "inventory")
    qualifies = bool(
        not archived
        and pf is not None and pf >= float(policy["min_profit_factor"])
        and trades is not None and trades >= int(policy["min_trades"])
        and lifecycle in {"approved_demo", "approved_live", "live", "ready", "candidate", "in_progress"}
    )
    parameters = link.get("parameters") if isinstance(link.get("parameters"), dict) else {}
    parameter_variant = {
        "iteration": 1,
        "status": "archived" if archived else lifecycle,
        "parameters": parameters,
        "profit_factor": pf,
        "net_profit": pnl,
    }
    period = link.get("test_period") if isinstance(link.get("test_period"), dict) else {}
    return {
        "experiment_id": "",
        "profile_id": link.get("profile_id"),
        "class_name": link.get("deploy_strategy_class") or link.get("strategy_class") or link.get("name") or link.get("profile_id"),
        "status": "archived" if archived else lifecycle,
        "hypothesis": link.get("hypothesis") or link.get("notes") or link.get("reason"),
        "qualifies": qualifies,
        "profit_factor": pf,
        "net_profit": pnl,
        "variant_count": 1,
        "variants": [parameter_variant],
        "best_parameter_variant": parameter_variant,
        "best_window": {
            "instrument": link.get("instrument") or link.get("root_family") or "—",
            "timeframe": link.get("timeframe") or "—",
            "from_utc": period.get("from_utc"),
            "to_utc": period.get("to_utc"),
        },
        "inventory_source": "legacy_profile",
        "archived": archived,
        "archive_reason": link.get("reason") or "",
    }


def evaluate(row: Dict[str, Any], experiments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if experiments is None:
        from . import registry  # lazy import keeps the storage modules independent
        experiments = registry.list_experiments(limit=10_000)
    linked = [exp for exp in experiments if str(exp.get("research_id") or "") == str(row["research_id"])]
    policy = _policy(row.get("evaluation_policy"))
    legacy_links = [item for item in (row.get("linked_strategies") or []) if isinstance(item, dict)]
    legacy_nodes = [_legacy_strategy_node(item, policy) for item in legacy_links]
    legacy_evaluated = [
        node for node in legacy_nodes
        if node.get("profit_factor") is not None or node.get("net_profit") is not None or node.get("archived")
    ]
    legacy_qualified = [node for node in legacy_evaluated if node.get("qualifies")]
    evaluated = [exp for exp in linked if _has_result(exp)]
    technical = [exp for exp in linked if _is_technical_failure(exp)]
    running = [exp for exp in linked if _is_running(exp)]
    qualified = [exp for exp in evaluated if _qualifies(exp, policy)]
    non_profitable = [exp for exp in evaluated if exp not in qualified]
    evaluated_total = len(evaluated) + len(legacy_evaluated)
    qualified_total = len(qualified) + len(legacy_qualified)
    non_profitable_total = len(non_profitable) + len(legacy_evaluated) - len(legacy_qualified)
    variant_count = sum(_variant_count(exp) for exp in linked) + len(legacy_nodes)
    variant_ready = sum(
        1 for exp in linked if _variant_count(exp) >= int(policy["min_variants_per_strategy"])
    )

    manual = str(row.get("manual_status") or "")
    if manual in {"active", "paused", "archived"}:
        status = manual
    elif qualified_total >= int(policy["required_profitable_strategies"]) and evaluated_total >= int(policy["min_strategies_to_decide"]):
        status = "validated"
    elif qualified_total:
        status = "promising"
    elif evaluated_total >= int(policy["max_strategies"]) or evaluated_total >= int(policy["target_strategies"]):
        status = "exhausted"
    elif evaluated_total >= int(policy["min_strategies_to_decide"]) and non_profitable_total == evaluated_total:
        status = "at_risk"
    elif linked or legacy_links:
        status = "active"
    else:
        status = "new"

    if status == "validated":
        conclusion = f"Гипотеза подтверждается: {qualified_total} из {evaluated_total} оценённых стратегий прошли пороги исследования."
    elif status == "promising":
        conclusion = f"Найден перспективный результат, но для вывода нужно оценить минимум {policy['min_strategies_to_decide']} стратегий."
    elif status == "exhausted":
        conclusion = f"Направление неактуально по текущим данным: {evaluated_total} стратегий проверено, ни одна не прошла заданные пороги."
    elif status == "at_risk":
        conclusion = f"Предварительно слабый результат: все {evaluated_total} проверенных стратегий убыточны/не прошли пороги. Продолжить до {policy['target_strategies']} (не более {policy['max_strategies']})."
    elif status == "active":
        conclusion = f"Исследование продолжается: оценено {evaluated_total} из целевых {policy['target_strategies']} стратегий."
    elif status == "paused":
        conclusion = "Исследование приостановлено владельцем; накопленные результаты сохранены."
    elif status == "archived":
        conclusion = "Исследование архивировано; контекст и доказательства сохранены для будущих сравнений."
    else:
        conclusion = f"Исследование готово к работе. До предварительного решения нужно проверить минимум {policy['min_strategies_to_decide']} стратегий."

    nodes = [_strategy_node(exp, policy) for exp in linked] + legacy_nodes
    nodes.sort(key=lambda item: (bool(item["qualifies"]), item.get("profit_factor") or -999), reverse=True)
    families: Dict[str, Dict[str, Any]] = {}
    for exp, node in zip(linked, [_strategy_node(exp, policy) for exp in linked]):
        key = str(exp.get("family") or row.get("family_key") or "Unclassified")
        family = families.setdefault(key, {"family_key": key, "family_name": row.get("family_name") or key, "strategies": []})
        family["strategies"].append(node)
    for link, node in zip(legacy_links, legacy_nodes):
        key = str(link.get("strategy_family") or row.get("family_key") or "Unclassified")
        family = families.setdefault(key, {"family_key": key, "family_name": row.get("family_name") or key, "strategies": []})
        family["strategies"].append(node)
    best = nodes[0] if nodes else None
    return {
        "status": status,
        "automatic_conclusion": conclusion,
        "linked_experiments": len(linked),
        "linked_strategy_profiles": len(legacy_links),
        "working_strategies": sum(1 for node in legacy_nodes if not node.get("archived")),
        "archived_strategies": sum(1 for node in legacy_nodes if node.get("archived")),
        "evaluated_strategies": evaluated_total,
        "profitable_strategies": qualified_total,
        "non_profitable_strategies": non_profitable_total,
        "technical_failures": len(technical),
        "running_strategies": len(running),
        "parameter_variants": variant_count,
        "strategies_with_enough_variants": variant_ready,
        "remaining_to_target": max(0, int(policy["target_strategies"]) - evaluated_total),
        "progress_pct": round(min(100.0, evaluated_total / max(1, int(policy["target_strategies"])) * 100.0), 1),
        "best_variant": best,
        "tree": list(families.values()),
    }


def _list_shape(row: Dict[str, Any], experiments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    out = {key: value for key, value in row.items() if key != "source_content"}
    out["evaluation_policy"] = _policy(out.get("evaluation_policy"))
    out["evaluation"] = evaluate(row, experiments)
    return out


_FAMILY_LABELS = {
    "mnq_b1_locked": "MNQ B1 / VWAP Short",
    "mgc_session_edge": "MGC Session Edge / VWAP Pullback",
    "mgc_b1_transfer": "MGC B1 раннего окна",
    "mgc_capitulation_snapback": "MGC Capitulation Snapback",
    "mnq_scalp_legacy": "MNQ ORB и внутрисессионный скальпинг",
    "mnq_liquidity_sweep_standalone": "MNQ Liquidity Sweep",
    "mnq_open_drive_legacy": "MNQ Open Drive Short",
    "session_reclaim_archived": "Session VWAP Reclaim",
    "mnq_session_edge": "MNQ Session Edge / Head & Shoulders",
    "mnq_entropy_transition": "MNQ Entropy Transition Field",
}

_FAMILY_HYPOTHESES = {
    "mnq_b1_locked": "Короткий VWAP/B1-сигнал MNQ способен сохранить edge после комиссии и реалистичного проскальзывания.",
    "mgc_session_edge": "Откат MGC к внутрисессионному балансу/VWAP даёт контролируемый short-edge в активном окне.",
    "mgc_b1_transfer": "Перенос B1 на MGC устойчив в раннем окне при фильтре объёма и фиксированном риске.",
    "mgc_capitulation_snapback": "Капитуляционный импульс MGC создаёт краткосрочный возврат после подтверждения истощения.",
    "mnq_scalp_legacy": "Структура открытия MNQ допускает ORB/retest-скальпинг при строгом ограничении частоты сделок.",
    "mnq_liquidity_sweep_standalone": "Снятие ликвидности у локального экстремума MNQ создаёт торгуемый разворот.",
    "mnq_open_drive_legacy": "Сильный open-drive MNQ сохраняет направленность в первом внутридневном окне.",
    "session_reclaim_archived": "Возврат цены через session VWAP после ложного ухода создаёт повторяемый reclaim-сигнал.",
    "mnq_session_edge": "Комбинация сессионного режима и H&S/divergence на MNQ даёт edge в ограниченных днях и окнах.",
    "mnq_entropy_transition": "Переход энтропийного состояния MNQ заранее отмечает направленный импульс.",
}


def _legacy_strategy_inventory() -> Dict[str, List[Dict[str, Any]]]:
    profiles_doc = read_json(paths.PROJECT_ROOT / "data" / "profiles" / "strategies.json", default={}) or {}
    archive_doc = read_json(paths.PROJECT_ROOT / "data" / "profiles" / "archived_strategies.json", default={}) or {}
    family_doc = read_json(paths.PROJECT_ROOT / "data" / "profiles" / "strategy_families.json", default={}) or {}
    profiles = [item for item in (profiles_doc.get("profiles") or []) if isinstance(item, dict)]
    archive = [item for item in (archive_doc.get("entries") or []) if isinstance(item, dict)]
    archive_by_id = {str(item.get("profile_id") or ""): item for item in archive}
    profile_map = family_doc.get("profile_map") if isinstance(family_doc.get("profile_map"), dict) else {}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    seen = set()

    def add(profile: Dict[str, Any], archive_row: Optional[Dict[str, Any]] = None) -> None:
        profile_id = str(profile.get("profile_id") or (archive_row or {}).get("profile_id") or "")
        if not profile_id or profile_id in seen:
            return
        seen.add(profile_id)
        meta = profile_map.get(profile_id) if isinstance(profile_map.get(profile_id), dict) else {}
        family = str(
            profile.get("strategy_family")
            or (archive_row or {}).get("strategy_family")
            or meta.get("strategy_family")
            or "unclassified_legacy"
        )
        archived = archive_row is not None or str(profile.get("lifecycle") or "") == "archived"
        link = {
            "profile_id": profile_id,
            "name": profile.get("name") or (archive_row or {}).get("name") or profile_id,
            "strategy_class": profile.get("strategy_class") or (archive_row or {}).get("strategy_class"),
            "deploy_strategy_class": profile.get("deploy_strategy_class"),
            "root_family": profile.get("root_family") or meta.get("root_family") or "",
            "strategy_family": family,
            "hub_class": profile.get("hub_class") or meta.get("hub_class") or "",
            "instrument": profile.get("instrument") or (archive_row or {}).get("instrument") or "",
            "timeframe": profile.get("timeframe") or (archive_row or {}).get("timeframe") or "",
            "trade_window": profile.get("trade_window_pt") or "",
            "status": profile.get("status") or "archived",
            "lifecycle": profile.get("lifecycle") or ("archived" if archived else "inventory"),
            "archived": archived,
            "archived_at_utc": (archive_row or {}).get("archived_at_utc"),
            "reason": (archive_row or {}).get("reason") or (profile.get("decision") or {}).get("reason") or "",
            "notes": profile.get("notes") or "",
            "parameters": profile.get("locked_parameters") or {},
            "metrics": profile.get("metrics") or {},
            "test_period": profile.get("test_period") or {},
            "evidence_bundle": profile.get("research_bundle") or (profile.get("validation") or {}).get("bundle") or "",
        }
        grouped.setdefault(family, []).append(link)

    for profile in profiles:
        add(profile, archive_by_id.get(str(profile.get("profile_id") or "")))
    for archived in archive:
        if str(archived.get("profile_id") or "") not in seen:
            add({}, archived)
    return grouped


def _find_imported(rows: List[Dict[str, Any]], import_key: str, source_name: str = "") -> Optional[Dict[str, Any]]:
    for row in rows:
        if str(row.get("import_key") or "") == import_key:
            return row
        if source_name and str(row.get("source_name") or "") == source_name:
            return row
    return None


def bootstrap_existing() -> Dict[str, int]:
    """Idempotently migrate pre-catalog research files and strategy profiles."""
    try:
        if not paths.REGISTRY_DIR.resolve().is_relative_to(paths.PROJECT_ROOT.resolve()):
            return {"created": 0, "updated": 0}
    except (OSError, ValueError):
        return {"created": 0, "updated": 0}

    created = 0
    updated = 0
    source_ids: Dict[str, str] = {}
    incoming = paths.USER_RESEARCH_DIR / "incoming"
    for source in sorted(incoming.glob("*")) if incoming.exists() else []:
        if not source.is_file() or source.suffix.lower() not in {".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml"}:
            continue
        import_key = "user-research:" + source.relative_to(paths.USER_RESEARCH_DIR).as_posix()
        data = _load()
        existing = _find_imported(data["researches"], import_key, source.name)
        if existing:
            source_ids[source.name] = str(existing["research_id"])
            continue
        content = source.read_text(encoding="utf-8", errors="replace")
        is_collection = "разработка стратегий" in source.stem.casefold()
        payload = {
            "source_type": "collection" if is_collection else "research",
            "title": _title_from_content(content),
            "family_name": "Исследования стратегий CME" if is_collection else "RTH Momentum Breakout + VWAP",
            "family_key": "cme_futures_research" if is_collection else "rth_momentum_vwap",
            "content": content,
            "source_name": source.name,
            "source_format": source.suffix.lstrip(".") or "text",
            "import_key": import_key,
            "migration_source": "ai_lab/user_research/incoming",
            "objectives": [
                "Преобразовать выводы материала в проверяемые семейства стратегий.",
                "Проверить результат после комиссии, проскальзывания, IS/OOS и stress-сценариев.",
            ],
            "hypotheses": [
                "Сессионные режимы, VWAP, объём и структура открытия содержат проверяемый intraday edge."
                if not is_collection else
                "Разные классы CME-фьючерсов требуют отдельных режимных семейств, но единого протокола доказательности."
            ],
        }
        research = create(payload)
        source_ids[source.name] = str(research["research_id"])
        created += 1

    grouped = _legacy_strategy_inventory()
    family_ids: Dict[str, str] = {}
    broad_sources = list(source_ids.values())
    rth_source = next((rid for name, rid in source_ids.items() if "Глубокое исследование" in name), "")
    for family, links in sorted(grouped.items()):
        import_key = "legacy-family:" + family
        data = _load()
        existing = _find_imported(data["researches"], import_key)
        active_count = sum(1 for link in links if not link.get("archived"))
        archived_count = len(links) - active_count
        label = _FAMILY_LABELS.get(family) or " ".join(part.capitalize() for part in family.split("_"))
        relevant_sources = list(broad_sources)
        if rth_source and any(token in family for token in ("vwap", "b1", "session", "scalp", "reclaim", "open")):
            relevant_sources = list(dict.fromkeys([rth_source, *relevant_sources]))
        status_line = f"В инвентаре {len(links)} профилей: рабочих {active_count}, архивных {archived_count}."
        if existing:
            if existing.get("linked_strategies") != links or existing.get("linked_research_ids") != relevant_sources:
                update(str(existing["research_id"]), {
                    "linked_strategies": links,
                    "linked_research_ids": relevant_sources,
                })
                updated += 1
            family_ids[family] = str(existing["research_id"])
            continue
        research = create({
            "source_type": "personal_idea",
            "title": label,
            "family_name": label,
            "family_key": family,
            "content": status_line + "\n\n" + "\n".join(
                f"- {link.get('name')} — {'архив' if link.get('archived') else 'рабочая'}; {link.get('reason') or link.get('notes') or 'см. профиль и evidence bundle'}"
                for link in links
            ),
            "summary": status_line + " Профили привязаны к общей личной гипотезе и сохраняют исходные статусы.",
            "objectives": [
                "Сохранить причинную связь между гипотезой, профилями и архивными выводами.",
                "Продолжать новые варианты только в рамках этого семейства.",
            ],
            "hypotheses": [_FAMILY_HYPOTHESES.get(family) or f"Семейство {label} содержит проверяемый торговый edge."],
            "linked_research_ids": relevant_sources,
            "linked_strategies": links,
            "manual_status": "archived" if active_count == 0 else "",
            "source_name": "data/profiles/strategies.json + archived_strategies.json",
            "source_format": "strategy_inventory",
            "import_key": import_key,
            "migration_source": "legacy_strategy_profiles",
        })
        family_ids[family] = str(research["research_id"])
        created += 1

    # Make the original studies useful as navigation roots: from a source card
    # the user can move directly to every family derived from the legacy inventory.
    derived_ids = list(family_ids.values())
    for source_id in source_ids.values():
        source_row = detail(source_id)
        expected_ids = list(dict.fromkeys([*(source_row.get("linked_research_ids") or []), *derived_ids]))
        if source_row.get("linked_research_ids") != expected_ids:
            update(source_id, {"linked_research_ids": expected_ids})
            updated += 1

    evidence_root = paths.PROJECT_ROOT / "data" / "research"
    bundles = sorted(
        item.name for item in evidence_root.iterdir()
        if item.is_dir() and not item.name.startswith("_") and item.name != "logs"
    ) if evidence_root.exists() else []
    if bundles:
        import_key = "legacy-evidence:data/research"
        data = _load()
        existing = _find_imported(data["researches"], import_key)
        payload = {
            "linked_research_ids": list(family_ids.values()),
            "owner_conclusion": f"Сохранено {len(bundles)} исторических пакетов; это доказательная история, а не список готовых к торговле стратегий.",
        }
        if existing:
            expected_ids = list(family_ids.values())
            expected_conclusion = payload["owner_conclusion"]
            if existing.get("linked_research_ids") != expected_ids or existing.get("owner_conclusion") != expected_conclusion:
                update(str(existing["research_id"]), payload)
                updated += 1
        else:
            create({
                "source_type": "collection",
                "title": "Архив исторических прогонов и проверок",
                "family_name": "Историческая доказательная база",
                "family_key": "legacy_research_evidence",
                "content": "Ниже перечислены сохранённые каталоги прогонов:\n\n" + "\n".join(f"- {name}" for name in bundles),
                "summary": f"Автоматически найдено {len(bundles)} каталогов с прежними оптимизациями, validation, stress, wrapper и portfolio-scan проверками.",
                "objectives": ["Не потерять отрицательные и положительные результаты прошлых прогонов.", "Использовать пакеты как evidence, не как автоматическое разрешение на запуск."],
                "hypotheses": ["Новая работа должна учитывать уже выполненные проверки и не повторять закрытые ветки без новых оснований."],
                "linked_research_ids": list(family_ids.values()),
                "manual_status": "archived",
                "source_name": "data/research",
                "source_format": "directory_index",
                "import_key": import_key,
                "migration_source": "legacy_research_bundles",
                "owner_conclusion": f"Сохранено {len(bundles)} исторических пакетов; это доказательная история, а не список готовых к торговле стратегий.",
            })
            created += 1
    return {"created": created, "updated": updated}


def list_researches() -> Dict[str, Any]:
    migration = bootstrap_existing()
    with _LOCK:
        data = _load()
    from . import registry
    experiments = registry.list_experiments(limit=10_000)
    rows = [_list_shape(row, experiments) for row in data["researches"]]
    rows.sort(key=lambda row: str(row.get("updated_at_utc") or row.get("created_at_utc") or ""), reverse=True)
    return {
        "researches": rows,
        "total": len(rows),
        "source_types": SOURCE_TYPES,
        "default_policy": dict(DEFAULT_POLICY),
        "migration": migration,
    }


def detail(research_id: str, *, _data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = _data or _load()
    row = next((item for item in data["researches"] if item.get("research_id") == research_id), None)
    if row is None:
        raise ResearchCatalogError(f"Исследование не найдено: {research_id}")
    out = dict(row)
    out["evaluation_policy"] = _policy(out.get("evaluation_policy"))
    out["evaluation"] = evaluate(row)
    return out


def run_context(research_id: str) -> Dict[str, Any]:
    """Return compact selected-research context suitable for an LLM prompt."""
    row = detail(research_id)
    evaluation = row["evaluation"]
    linked_titles = []
    if row.get("linked_research_ids"):
        data = _load()
        by_id = {item.get("research_id"): item for item in data["researches"]}
        linked_titles = [
            str(by_id[rid].get("title") or rid) for rid in row["linked_research_ids"] if rid in by_id
        ]
    linked_strategies = [
        {
            "profile_id": item.get("profile_id"),
            "name": item.get("name"),
            "status": "archived" if item.get("archived") else item.get("lifecycle") or item.get("status"),
            "reason": str(item.get("reason") or "")[:240],
        }
        for item in (row.get("linked_strategies") or []) if isinstance(item, dict)
    ][:30]
    context = "\n".join([
        f"ACTIVE RESEARCH: {row['research_id']} — {row['title']}",
        f"Research type: {SOURCE_TYPES.get(row['source_type'], row['source_type'])}",
        f"Required strategy family: {row['family_name']} (machine key: {row['family_key']})",
        f"Summary: {row['summary']}",
        f"Objectives: {row.get('objectives') or ['derive testable objectives from the source']}",
        f"Hypotheses: {row.get('hypotheses') or ['formulate distinct hypotheses from the source']}",
        f"Linked research collection: {linked_titles}",
        f"Existing working/archive strategy evidence: {linked_strategies}",
        f"Current evidence: {evaluation['automatic_conclusion']}",
        f"Evaluation policy: {row['evaluation_policy']}",
        "Generate only work that advances this research. Do not silently switch to an unrelated family.",
    ])
    return {
        "research_id": row["research_id"],
        "research_title": row["title"],
        "family_name": row["family_name"],
        "family_key": row["family_key"],
        "knowledge_rel_path": row.get("knowledge_rel_path"),
        "context": context[:8_000],
        "evaluation": evaluation,
    }
