"""Knowledge context builder for AI Strategy Lab generation.

The builder intentionally produces a compact, auditable prompt pack. It reads
project lessons, prior AI-CELL outcomes, reference strategy results, user
research, compile/rejection patterns, and a lightweight index of project
strategy sources. The output is small enough for local models and is persisted
per run.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .. import governance
from . import errors, lessons, operator_notes, paths, registry, user_research
from .io_utils import write_json_atomic

TEXT_EXTS = {".md", ".markdown", ".txt", ".json", ".jsonl", ".csv"}
MAX_SOURCE_SNIPPET = 2200
MAX_PROMPT_CONTEXT = 8_000


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(paths.PROJECT_ROOT.resolve()))
    except Exception:
        return str(path)


def _read_text(path: Path, limit: int = MAX_SOURCE_SNIPPET) -> str:
    if not path.exists() or not path.is_file() or path.suffix.lower() not in TEXT_EXTS:
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]
    except OSError:
        return ""


def _add_source(sources: List[Dict[str, Any]], path: Path, kind: str, note: str = "") -> str:
    item = {"kind": kind, "path": str(path), "rel_path": _rel(path), "note": note}
    sources.append(item)
    return item["rel_path"]


def _compact_line(text: str, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _iter_existing(paths_in: Iterable[Path]) -> Iterable[Path]:
    for p in paths_in:
        if p.exists() and p.is_file():
            yield p


def _project_docs() -> List[Path]:
    governance.ensure_governance_files()
    legacy_root = paths.PROJECT_ROOT.parent / "РАЗРАБОТКА СТРАТЕГИЙ"
    candidates = [
        paths.PROJECT_ROOT / "docs" / "governance" / "CHARTER.md",
        paths.PROJECT_ROOT / "docs" / "governance" / "NORTH_STAR_2026.md",
        paths.PROJECT_ROOT / "docs" / "governance" / "ROLES.md",
        paths.PROJECT_ROOT / "docs" / "governance" / "LAWS.md",
        paths.PROJECT_ROOT / "docs" / "governance" / "LOCAL_AI_LAWS.md",
        paths.PROJECT_ROOT / "docs" / "governance" / "REGISTRY_POLICY.md",
        paths.PROJECT_ROOT / "docs" / "governance" / "SYNC_MAP.md",
        paths.PROJECT_ROOT / "docs" / "risk-profile.md",
        paths.PROJECT_ROOT / "docs" / "AI_STRATEGY_LAB_RUN_CONTROLS.md",
        paths.PROJECT_ROOT / "docs" / "AI_STRATEGY_LAB_QUALITY.md",
        legacy_root / "Общие правила разработки стратегий.md",
        legacy_root / "Реестр стратегий.md",
        legacy_root / "Двухэтапный цикл Research Hub и Deploy.md",
        legacy_root / "План перехода стратегий в семьи и новый цикл.md",
    ]
    return list(_iter_existing(candidates))


def _reference_docs() -> List[Path]:
    root = paths.REFERENCE_STRATEGIES_DIR
    names = [
        "WORKING_STRATEGIES_RESULTS_TABLE.md",
        "WORKING_REFERENCE_STRATEGIES_REPORT.md",
        "reference_registry.json",
        "SOURCES.md",
        "ai_lessons/LESSONS_SUMMARY.md",
        "ai_lessons/PATTERN_EVALUATION.md",
        "ai_lessons/FAILED_CEILING.md",
    ]
    docs = list(_iter_existing(root / n for n in names))
    docs.extend(sorted(root.glob("REF-*/normalized_spec.md"))[:12])
    return docs


def _ai_cell_reports() -> List[Path]:
    report_root = paths.AI_LAB_DIR / "experiments"
    return sorted(
        report_root.glob("AI_CELL_*_FULL_DEVELOPMENT_REPORT.md"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )[:8]


def _extract_wex_rows(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("| WEX-"):
            continue
        cols = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
        if len(cols) < 14:
            continue
        rows.append({
            "id": cols[0],
            "strategy": cols[1],
            "compile": cols[4],
            "trades": cols[5],
            "net_after_commission": cols[9],
            "pf_after_commission": cols[10],
            "verdict": cols[13],
        })
    return rows[:20]


def _load_reference_registry() -> List[Dict[str, Any]]:
    path = paths.REFERENCE_STRATEGIES_DIR / "reference_registry.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _reference_shortlist(
    target_root: str,
    *,
    recent: List[Dict[str, Any]],
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Return auditable adaptation candidates, excluding known bad templates."""
    root = (target_root or "").upper()
    failed_families = {
        str(row.get("family") or "").strip().lower()
        for row in recent
        if row.get("status") in {
            "rejected", "validation_failed", "compile_failed",
            "compile_failed_after_fix_loop",
        }
    }
    ranked: List[tuple[float, Dict[str, Any]]] = []
    for row in _load_reference_registry():
        if not row.get("usable_as_reference", False):
            continue
        if not row.get("candidate_for_adaptation", False):
            continue
        if row.get("do_not_use_reason"):
            continue
        instruments = {str(x).upper() for x in (row.get("instrument_candidates") or [])}
        if instruments and root not in instruments:
            continue
        family = str(row.get("strategy_family") or "")
        score = 50.0
        notes = str(row.get("notes") or "")
        if family.lower() not in failed_families:
            score += 20.0
        if any(token in notes.lower() for token in ("near-passed", "close", "direction bias")):
            score += 15.0
        if any(token in family.lower() for token in ("vwap", "liquidity", "session", "reversal")):
            score += 8.0
        if any(token in family.lower() for token in ("crossover", "generic", "breakout")):
            score -= 10.0
        ranked.append((score, {
            "reference_id": row.get("strategy_id"),
            "name": row.get("name"),
            "family": family,
            "timeframe": row.get("timeframe") or [],
            "notes": _compact_line(notes, 220),
            "risk_flags": row.get("risk_flags") or [],
            "score": score,
        }))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("reference_id"))))
    return [row for _, row in ranked[:limit]]


def _strategy_source_index(limit: int = 30) -> List[Dict[str, Any]]:
    roots = [
        paths.PROJECT_ROOT / "ninjatrader" / "strategies",
        paths.SOURCE_SNAPSHOTS_DIR,
    ]
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.cs")):
            if len(out) >= limit:
                return out
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                text = p.read_text(encoding="utf-8-sig", errors="replace")[:20_000]
            except OSError:
                continue
            class_match = re.search(r"\bclass\s+([A-Za-z0-9_]+)\s*:\s*Strategy\b", text)
            indicators = sorted(set(re.findall(r"\b(EMA|SMA|RSI|ADX|ATR|VWAP|MACD|MIN|MAX|Bollinger|Stochastics)\s*\(", text)))
            out.append({
                "class_name": class_match.group(1) if class_match else p.stem,
                "rel_path": _rel(p),
                "indicators": indicators[:8],
                "has_risk_shell": all(token in text for token in ("SetStopLoss", "SetProfitTarget")),
                "has_trade_limit": "MaxTradesPerDay" in text or "maxTradesPerDay" in text,
            })
    return out


def _recent_experiment_lessons(target_root: str, limit: int = 12) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for exp in registry.list_experiments(target_root=target_root, limit=limit):
        verdict = exp.get("verdict") or {}
        analysis = exp.get("analysis") or {}
        sanity = exp.get("signal_sanity") or {}
        out.append({
            "experiment_id": exp.get("experiment_id"),
            "ai_cell_id": exp.get("ai_cell_id"),
            "status": exp.get("status"),
            "family": exp.get("family"),
            "hypothesis": _compact_line(exp.get("hypothesis", ""), 180),
            "outcome": verdict.get("outcome"),
            "rejection_code": verdict.get("rejection_code"),
            "trades_total": analysis.get("trades_total"),
            "pf_after_commission": analysis.get("pf_after_commission"),
            "signal_sanity": sanity.get("reason"),
        })
    return out


def _hard_constraints(goal_constraints: Dict[str, Any]) -> List[str]:
    defaults = governance.runtime_defaults()
    freq = goal_constraints.get("trade_frequency")
    max_trade_rule = "Use MaxTradesPerDay <= 3; if user asks high trade count, still cap overtrading and justify."
    if freq == "lower":
        max_trade_rule = "Prefer lower-turnover setups; MaxTradesPerDay <= 2."
    return [
        "Historical research only. Do not start live, paper, demo, account, or runtime trading.",
        "AI_SANDBOX source only; never write production strategy classes or production CELL ids.",
        "Evaluate after commission/slippage; gross metrics are insufficient.",
        "Use RoundTurnCommission >="
        f" {defaults.get('round_turn_commission', 1.90):.2f}, "
        f"SlippageTicks >= {int(defaults.get('slippage_ticks', 1))}, "
        f"{defaults.get('order_fill_resolution', 'High')} fill assumptions.",
        "Always include stop loss, profit target, max daily loss, max trades/day, force-flat/no overnight.",
        max_trade_rule,
        "Reject 0-trade and insufficient-signal ideas before historical backtest.",
        "Do not repeat AI-CELL-005 generic price movement breakout or WEX-006 unlimited churn.",
        "If initial backtest is negative, mutation must change hypothesis/filter, not only parameters.",
    ]


def _acceptance_gates(goal_constraints: Dict[str, Any]) -> List[str]:
    return [
        "static validator passes before writing sandbox source",
        "compile/catalog passes with real NT diagnostics captured on failure",
        "signal sanity produces enough theoretical signals",
        "smoke backtest completes before Full/IS/OOS",
        "net after commission > 0 and PF after commission >= 1.05 for candidate consideration",
        "reasonable drawdown versus selected budget/capital",
        "manual portfolio approval required after candidate verdict",
    ]


def _rejection_gates() -> List[str]:
    return [
        "compile_failed_after_fix_loop",
        "0 trades or zero theoretical signals",
        "negative net after commission after allowed mutation/new-cell budget",
        "PF after commission < 1.0",
        "overtrading/commission drag destroys gross edge",
        "uses forbidden NT8/account/live APIs",
        "blocked real environment issue with exact blocker recorded",
    ]


def _north_star_lines() -> List[str]:
    """Compact mission block so every generation knows what the strategy is for."""
    try:
        from .. import governance
        north = (governance.read_goals() or {}).get("north_star") or {}
    except Exception:
        north = {}
    target = north.get("target_usd") or 100000
    deadline = north.get("deadline") or "2026-12-31"
    return [
        "PROJECT NORTH STAR (why this strategy exists):",
        f"- Goal: ${target:,} realized after-commission PnL from approved_demo/"
        f"approved_live runtime strategies by {deadline}.",
        "- Every strategy must contribute a real, repeatable edge toward this goal.",
        "- Development doctrine: name the market regime and entry confirmation; "
        "produce enough quality signals for statistical significance WITHOUT "
        "overtrading against commission; positive economics AFTER costs; use the "
        "approved references and user research as the edge source; iterate on "
        "near-misses instead of abandoning them.",
        "- The goal never overrides risk/compile/backtest/promotion gates.",
        "",
    ]


def build_context(
    target_root: str,
    *,
    user_goal: str = "",
    goal_constraints: Optional[Dict[str, Any]] = None,
    experiment_id: Optional[str] = None,
    max_prompt_chars: int = MAX_PROMPT_CONTEXT,
) -> Dict[str, Any]:
    paths.ensure_dirs()
    goal_constraints = goal_constraints or {}
    sources: List[Dict[str, Any]] = []
    source_summaries: List[str] = []
    wex_rows: List[Dict[str, Any]] = []

    for p in _reference_docs():
        rel = _add_source(sources, p, "reference_strategy")
        text = _read_text(p)
        if p.name == "WORKING_STRATEGIES_RESULTS_TABLE.md":
            wex_rows = _extract_wex_rows(text)
        # The registry is parsed through the strict shortlist filter below.
        # Do not leak excluded/do-not-use rows back into the model via a raw
        # source excerpt.
        if text and p.name != "reference_registry.json":
            source_summaries.append(f"## {rel}\n{_compact_line(text, 900)}")

    for p in _ai_cell_reports():
        rel = _add_source(sources, p, "ai_cell_report")
        text = _read_text(p)
        if text:
            source_summaries.append(f"## {rel}\n{_compact_line(text, 900)}")

    for p in _project_docs():
        rel = _add_source(sources, p, "project_strategy_doc")
        text = _read_text(p)
        if text:
            source_summaries.append(f"## {rel}\n{_compact_line(text, 700)}")

    scan = user_research.scan()
    user_research_refs: List[str] = []
    research_paths = list(scan.get("new", []) + scan.get("changed", []))
    if not research_paths:
        # A file stops being "new" after the first scan, but it does not stop
        # being relevant. Strategic dialogue and later runs must still read the
        # owner's current research corpus.
        research_paths = [
            str(row.get("rel_path") or "")
            for row in user_research.all_files()
            if str(row.get("rel_path") or "")
        ]
    for rel_path in research_paths[:8]:
        text, _meta = user_research.read_file(rel_path, max_bytes=5000)
        if text:
            user_research_refs.append(rel_path)
            source_summaries.append(f"## user_research/{rel_path}\n{_compact_line(text, 700)}")

    recent = _recent_experiment_lessons(target_root, limit=8)
    reference_shortlist = _reference_shortlist(target_root, recent=recent)
    repeated_errors = errors.top_repeated_patterns(threshold=2)[:10]
    lesson_rows = lessons.all_lessons(limit=20)
    global_notes = operator_notes.list_global_notes(limit=20)
    project_sources = _strategy_source_index(limit=20)
    hard = _hard_constraints(goal_constraints)
    acceptance = _acceptance_gates(goal_constraints)
    rejection = _rejection_gates()

    goal_lines = _north_star_lines()

    prompt_parts = [
        "KNOWLEDGE_CONTEXT: required before strategy generation.",
        f"Target root: {target_root}",
        f"User goal: {user_goal or 'auto'}",
        f"Parsed constraints: {json.dumps(goal_constraints, ensure_ascii=False, sort_keys=True)}",
        "",
        *goal_lines,
        "Hard constraints:",
        *[f"- {x}" for x in hard],
        "",
        "Key project lessons to apply now:",
        "- AI-CELL-004 produced 0 trades: do signal sanity before historical jobs.",
        "- AI-CELL-005 compiled/backtested but was negative after commission: do not repeat generic price movement/breakout churn.",
        "- AI-CELL-006 compiled but failed signal sanity with 0 theoretical signals: avoid over-filtered pullback logic.",
        "- WEX-007 Donchian had the best gross edge but failed after $1.90 commission; reduce turnover or improve filter quality.",
        "- WEX-006 MACD/RSI overtraded heavily; unlimited entries are forbidden.",
        "- WEX rows are negative baselines, not templates to copy. A new idea must state what structural defect it changes.",
        "- Generic price/Donchian/EMA breakout without a named market regime and confirmation is forbidden.",
        "",
        "Approved reference shortlist (choose exactly one reference_id):",
        *[
            f"- {r['reference_id']} {r['name']} | family={r['family']} | "
            f"timeframe={','.join(r['timeframe'])} | notes={r['notes']} | "
            f"risk_flags={','.join(r['risk_flags']) or 'none'}"
            for r in reference_shortlist
        ],
        "",
        "Reference strategy results:",
        *[
            f"- {r['id']} {r['strategy']}: trades={r['trades']}, net_after_comm={r['net_after_commission']}, "
            f"pf_after={r['pf_after_commission']}, verdict={r['verdict']}"
            for r in wex_rows[:8]
        ],
        "",
        "Recent AI experiment memory:",
        *[
            f"- {r['ai_cell_id']} / {r['experiment_id']}: status={r['status']}, family={r['family']}, "
            f"outcome={r['outcome']}, code={r['rejection_code']}, trades={r['trades_total']}, "
            f"pf_after={r['pf_after_commission']}, sanity={r['signal_sanity']}, hypothesis={r['hypothesis']}"
            for r in recent
        ],
        "",
        "Repeated compile/API mistakes to avoid:",
        *[
            f"- {p.get('phase')}/{p.get('error_type')} x{p.get('count')}: {p.get('normalized_pattern')}"
            for p in repeated_errors
        ],
        "",
        "Stored lessons:",
        *[
            f"- {l.get('summary')} | rule={l.get('rule') or ''}"
            for l in lesson_rows[:12]
        ],
        "",
        "Global operator rules (highest priority — apply ALL):",
        *([f"- [{n.get('priority')}] {n.get('text')}" for n in global_notes]
          if global_notes else ["- (none recorded yet)"]),
        "",
        "Acceptance gates:",
        *[f"- {x}" for x in acceptance],
        "",
        "Rejection gates:",
        *[f"- {x}" for x in rejection],
        "",
        "Project/source strategy examples index:",
        *[
            f"- {s['class_name']} ({s['rel_path']}), indicators={','.join(s['indicators']) or 'n/a'}, "
            f"risk_shell={s['has_risk_shell']}, trade_limit={s['has_trade_limit']}"
            for s in project_sources[:10]
        ],
        "",
        "Source excerpts summary:",
        *source_summaries[:5],
    ]
    prompt_context = "\n".join(prompt_parts)
    if len(prompt_context) > max_prompt_chars:
        prompt_context = prompt_context[:max_prompt_chars] + "\n[knowledge_context truncated by size guard]"

    context: Dict[str, Any] = {
        "schema_version": "1.0",
        "built_at_utc": _now(),
        "target_root": target_root,
        "user_goal": user_goal,
        "goal_constraints": goal_constraints,
        "context_required": True,
        "hard_constraints": hard,
        "acceptance_gates": acceptance,
        "rejection_gates": rejection,
        "reference_examples": wex_rows,
        "reference_shortlist": reference_shortlist,
        "recent_experiments": recent,
        "project_strategy_examples": project_sources,
        "repeated_errors": repeated_errors,
        "lessons": lesson_rows[:30],
        "global_operator_notes": global_notes,
        "user_research_refs": user_research_refs,
        "source_excerpt_summaries": source_summaries[:12],
        "source_refs": sources,
        "prompt_context": prompt_context,
    }
    if experiment_id:
        out_path = paths.RUNS_DIR / f"{experiment_id}_knowledge_context.json"
        write_json_atomic(out_path, context)
        context["path"] = str(out_path)
    return context
