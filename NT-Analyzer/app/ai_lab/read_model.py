"""Read model for the AI Lab UI.

Builds the response shapes consumed by /api/ai-lab/{summary,matrix,
experiments,...}. Pure read functions; no side effects.
"""

from __future__ import annotations

from collections import defaultdict
import json
import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import lm_studio, registry, paths
from . import errors as ai_errors
from . import lessons as ai_lessons
from . import user_research
from . import backtest as ai_backtest
from .io_utils import read_json

LANES_PER_ROOT = 15
DEFAULT_ROOTS = ["MNQ", "MGC", "MES", "MCL"]
ZERO_TRADE_STATUS = "zero_trades"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _visible_portfolio_member(e: Dict[str, Any]) -> bool:
    return (
        registry.portfolio_metadata(e).get("is_portfolio_member") is True
        and not registry.promotion_blockers(e)
    )


def summary() -> Dict[str, Any]:
    experiments = registry.list_experiments()
    by_status: Dict[str, int] = defaultdict(int)
    by_root: Dict[str, int] = defaultdict(int)
    running_jobs = 0
    compile_failures = 0
    candidates = 0
    rejects = 0
    champions = 0
    portfolio_members = 0
    for e in experiments:
        st = e.get("status", "draft")
        by_status[st] += 1
        by_root[e.get("target_root", "UNKNOWN")] += 1
        if st == "backtesting":
            running_jobs += 1
        if st == "compile_failed":
            compile_failures += 1
        if st in ("sandbox_candidate", "portfolio_contributor"):
            candidates += 1
        if st == "rejected":
            rejects += 1
        if st in ("champion_candidate", "human_review_candidate"):
            champions += 1
        if _visible_portfolio_member(e):
            portfolio_members += 1

    top = sorted(
        experiments,
        key=lambda e: (e.get("arbitration", {}) or {}).get("score") or -1e9,
        reverse=True,
    )[:5]

    try:
        lm_studio_status = lm_studio.lm_status(allow_probe=False)
    except Exception as e:
        lm_studio_status = {
            "available": False,
            "error": str(e),
            "ready": False,
            "run_allowed": False,
            "status": "server_unavailable",
            "message_ru": "LM Studio недоступна — запустите сервер (порт 1234).",
        }

    ur_files = user_research.all_files()

    return {
        "generated_at_utc": _now(),
        "totals": {
            "experiments": len(experiments),
            "running_jobs": running_jobs,
            "compile_failures": compile_failures,
            "candidates": candidates,
            "rejects": rejects,
            "champions": champions,
            "portfolio_members": portfolio_members,
        },
        "by_status": dict(by_status),
        "by_root": dict(by_root),
        "top": [
            {
                "experiment_id": e["experiment_id"],
                "ai_cell_id": e.get("ai_cell_id"),
                "target_root": e.get("target_root"),
                "status": e.get("status"),
                "score": (e.get("arbitration") or {}).get("score"),
                "class_name": e.get("class_name"),
            }
            for e in top
        ],
        "lm_studio": lm_studio_status,
        "user_research": {
            "files": len(ur_files),
            "last_scan_utc": (registry.load_index().get("user_research_ingest") or {}).get("last_scan_utc"),
        },
        "error_phases": ai_errors.count_by_phase(),
        "lesson_count": sum(1 for _ in ai_lessons.all_lessons(limit=10_000)),
        "safety": {
            "live_trading": "forbidden",
            "auto_paper": "forbidden",
            "historical_only": True,
            "sandbox_only_writes": True,
        },
    }


def matrix(roots: Optional[List[str]] = None, lanes: int = LANES_PER_ROOT) -> Dict[str, Any]:
    roots = roots or DEFAULT_ROOTS
    experiments = registry.list_experiments()
    by_root: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in experiments:
        by_root[e.get("target_root", "UNKNOWN")].append(e)

    rows = []
    for root in roots:
        items = sorted(by_root.get(root, []), key=lambda e: e.get("ai_cell_id") or "")
        cells = []
        for slot in range(1, lanes + 1):
            cell_id = f"AI-CELL-{root}-{slot:03d}"
            match = next((e for e in items if e.get("ai_cell_id") == cell_id), None)
            cells.append({
                "slot": slot,
                "ai_cell_id": cell_id,
                "experiment_id": match["experiment_id"] if match else None,
                "status": match.get("status") if match else "empty",
                "history_status": _history_status(match) if match else "empty",
                "score": (match.get("arbitration") or {}).get("score") if match else None,
                "class_name": match.get("class_name") if match else None,
                "family": match.get("family") if match else None,
                **(registry.portfolio_metadata(match) if match else {
                    "is_experiment": False,
                    "is_portfolio_member": False,
                    "portfolio_status": None,
                    "source_experiment_id": None,
                }),
            })
        rows.append({"root": root, "cells": cells})
    return {"generated_at_utc": _now(), "lanes": lanes, "rows": rows}


def _latest_backtest(e: Dict[str, Any]) -> Dict[str, Any]:
    bts = e.get("backtests") or []
    if not bts:
        return {}
    last = bts[-1]
    return last if isinstance(last, dict) else {}


def _history_status(e: Optional[Dict[str, Any]]) -> str:
    if not e:
        return "unknown"
    if registry.is_zero_trade_experiment(e):
        return ZERO_TRADE_STATUS
    return str(e.get("status") or "draft")


def _portfolio_action_state(e: Dict[str, Any]) -> Dict[str, Any]:
    blockers = registry.promotion_blockers(e)
    return {
        "portfolio_eligible": not blockers,
        "portfolio_blockers": blockers,
    }


def _report_path_for(e: Dict[str, Any]) -> Optional[str]:
    eid = str(e.get("experiment_id") or "")
    cid = str(e.get("ai_cell_id") or "")
    candidates = []
    if cid:
        candidates.append(registry.paths.AI_LAB_DIR / "experiments" / f"{cid.replace('-', '_')}_FULL_DEVELOPMENT_REPORT.md")
    if eid:
        candidates.append(registry.paths.AI_LAB_DIR / "experiments" / f"{eid}_REPORT.md")
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def experiment_row(e: Dict[str, Any]) -> Dict[str, Any]:
    """Normalized UI row for AI experiment history and portfolio views."""
    a = e.get("analysis") or {}
    arb = e.get("arbitration") or {}
    compile_info = e.get("compile") or {}
    verdict = e.get("verdict") or {}
    latest_bt = _latest_backtest(e)
    portfolio_meta = registry.portfolio_metadata(e)
    source = e.get("strategy_source") or {}
    model_chain = e.get("model_chain") or []
    model_roles_used = []
    for item in model_chain:
        if isinstance(item, dict):
            role = item.get("role") or "model"
            model = item.get("selected_model") or item.get("model") or item.get("configured_primary") or ""
            fallback = " fallback" if item.get("fallback_used") else ""
            model_roles_used.append(f"{role}:{model}{fallback}".strip(":"))
        elif item:
            model_roles_used.append(str(item))
    row = {
        "experiment_id": e["experiment_id"],
        "ai_cell_id": e.get("ai_cell_id"),
        "class_name": e.get("class_name"),
        "target_root": e.get("target_root"),
        "family": e.get("family"),
        "status": e.get("status"),
        "history_status": _history_status(e),
        "origin": "AI",
        "is_experiment": True,
        "compile_status": compile_info.get("last_status"),
        "compile_attempts": compile_info.get("attempts"),
        "backtest_status": latest_bt.get("status") or ("none" if not latest_bt else None),
        "job_id": latest_bt.get("job_id"),
        "verdict": verdict.get("outcome"),
        "rejection_code": verdict.get("rejection_code"),
        "model_roles_used": ", ".join(model_roles_used),
        "knowledge_context_path": (e.get("knowledge_context") or {}).get("path")
            or (e.get("memory_intake") or {}).get("knowledge_context_path"),
        "knowledge_sources_count": len((e.get("knowledge_context") or {}).get("sources_read") or []),
        "report_path": _report_path_for(e),
        "source_code_link": source.get("mirror_path") or source.get("sandbox_path"),
        "avg_per_day": a.get("avg_per_day"),
        "avg_per_week": a.get("avg_per_week"),
        "avg_per_month": a.get("avg_per_month"),
        "avg_per_quarter": a.get("avg_per_quarter"),
        "avg_per_year": a.get("avg_per_year"),
        "monthly_growth_pct": a.get("monthly_growth_pct"),
        "quarterly_growth_pct": a.get("quarterly_growth_pct"),
        "annualized_growth_estimate_pct": a.get("annualized_growth_estimate_pct"),
        "compounded_growth_estimate_pct": a.get("compounded_growth_estimate_pct"),
        "trades_per_day": a.get("trades_per_day"),
        "trades_per_week": a.get("trades_per_week"),
        "trades_per_month": a.get("trades_per_month"),
        "trades_total": a.get("trades_total"),
        "trade_count": a.get("trades_total"),
        "years_tested": a.get("years_tested"),
        "pf_after_commission": a.get("pf_after_commission"),
        "dd_after_commission": a.get("dd_after_commission"),
        "profitable_months_pct": a.get("profitable_months_pct"),
        "profitable_quarters_pct": a.get("profitable_quarters_pct"),
        "profitable_years_pct": a.get("profitable_years_pct"),
        "stress_pass_flag": a.get("stress_pass_flag"),
        "ai_arbitration_score": arb.get("score"),
        "error_count": len([1 for h in registry.history_for(e["experiment_id"]) if h.get("kind") == "error"]),
        "lineage": e.get("lineage") or [],
    }
    row.update(portfolio_meta)
    row.update(_portfolio_action_state(e))
    return row


def performance_board() -> Dict[str, Any]:
    """AI experiment history board: every experiment, not selected portfolio."""
    rows: List[Dict[str, Any]] = []
    for e in registry.list_experiments():
        rows.append(experiment_row(e))
    rows.sort(key=lambda r: (r.get("ai_arbitration_score") or -1e9), reverse=True)
    return {
        "generated_at_utc": _now(),
        "view": "experiment_history",
        "rows": rows,
    }


def model_performance(days: int = 30) -> Dict[str, Any]:
    """Aggregate auditable LM round trips by model and role."""
    paths.ensure_dirs()
    files = sorted(paths.PROMPTS_LOG_DIR.glob("*.jsonl"))[-max(1, min(int(days), 365)):]
    records: List[Dict[str, Any]] = []
    for path in files:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    records.append(row)
        except OSError:
            continue

    groups: Dict[str, Dict[str, Any]] = {}
    role_groups: Dict[str, Dict[str, Any]] = {}
    experiment_index = {str(row.get("experiment_id")): row for row in registry.list_experiments() if row.get("experiment_id")}

    def add(target: Dict[str, Dict[str, Any]], key: str, row: Dict[str, Any]) -> None:
        item = target.setdefault(key or "unknown", {
            "key": key or "unknown", "requests": 0, "successes": 0, "errors": 0,
            "latencies": [], "prompt_tokens": 0, "completion_tokens": 0,
            "total_tokens": 0, "response_chars": 0, "experiments": set(),
        })
        item["requests"] += 1
        success = row.get("success") if "success" in row else not bool(row.get("error"))
        item["successes" if success else "errors"] += 1
        try:
            item["latencies"].append(float(row.get("elapsed_sec") or 0))
        except (TypeError, ValueError):
            pass
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                item[name] += int(usage.get(name) or 0)
            except (TypeError, ValueError):
                pass
        item["response_chars"] += int(row.get("response_chars") or len(str(row.get("response_preview") or "")))
        if row.get("experiment_id"):
            item["experiments"].add(str(row["experiment_id"]))

    for row in records:
        add(groups, str(row.get("model") or "unknown"), row)
        add(role_groups, str(row.get("role") or "unknown"), row)

    def finish(source: Dict[str, Dict[str, Any]], label: str) -> List[Dict[str, Any]]:
        result = []
        for item in source.values():
            latencies = sorted(item.pop("latencies"))
            experiments = item.pop("experiments")
            requests = item["requests"]
            item[label] = item.pop("key")
            item["success_rate_pct"] = round(item["successes"] / requests * 100, 1) if requests else None
            item["avg_latency_sec"] = round(statistics.mean(latencies), 2) if latencies else None
            p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
            item["p95_latency_sec"] = round(latencies[p95_index], 2) if latencies else None
            item["experiment_count"] = len(experiments)
            linked = [experiment_index[eid] for eid in experiments if eid in experiment_index]
            terminal = [row for row in linked if str(row.get("status") or "") not in {"draft", "designing", "draft_ready", "generating", "awaiting_compile", "backtesting", "analyzing"}]
            accepted = [row for row in terminal if str(row.get("status") or "") in {"sandbox_candidate", "champion_candidate", "human_review_candidate", "portfolio_contributor"}]
            scores = [float((row.get("arbitration") or {}).get("score")) for row in linked if (row.get("arbitration") or {}).get("score") is not None]
            item["terminal_experiments"] = len(terminal)
            item["accepted_experiments"] = len(accepted)
            item["result_rate_pct"] = round(len(accepted) / len(terminal) * 100, 1) if terminal else None
            item["avg_arbitration_score"] = round(statistics.mean(scores), 1) if scores else None
            item["tokens_reported"] = item["total_tokens"] > 0
            result.append(item)
        result.sort(key=lambda row: (-row["requests"], str(row[label])))
        return result

    return {
        "generated_at_utc": _now(),
        "window_days": max(1, min(int(days), 365)),
        "log_files": len(files),
        "requests": len(records),
        "models": finish(groups, "model"),
        "roles": finish(role_groups, "role"),
        "latest": records[-20:][::-1],
    }


def portfolio_board() -> Dict[str, Any]:
    """AI selected portfolio: explicit manual membership only."""
    rows = [
        experiment_row(e)
        for e in registry.list_experiments()
        if _visible_portfolio_member(e)
    ]
    rows.sort(key=lambda r: (r.get("approved_at") or r.get("promoted_at") or ""), reverse=True)
    return {
        "generated_at_utc": _now(),
        "view": "selected_portfolio",
        "rows": rows,
        "allowed_portfolio_states": sorted(registry.PORTFOLIO_APPROVAL_STATES),
        "history_only_statuses": sorted(registry.PORTFOLIO_BLOCKED_STATUSES),
    }


def calendar() -> Dict[str, Any]:
    """AI research calendar: aggregate AI-only monthly PnL across experiments."""
    by_month: Dict[str, float] = defaultdict(float)
    contributions: Dict[str, List[str]] = defaultdict(list)
    for e in registry.list_experiments():
        a = e.get("analysis") or {}
        avg_month = a.get("avg_per_month")
        if avg_month is None:
            continue
        years_tested = a.get("years_tested") or 0
        approx_months = max(1, int(round((years_tested or 0) * 12)))
        for i in range(approx_months):
            month_key = f"M-{i:02d}"
            by_month[month_key] += float(avg_month)
            contributions[month_key].append(e["experiment_id"])
    return {
        "generated_at_utc": _now(),
        "by_relative_month": [
            {"month": k, "ai_total_pnl": v, "experiments": contributions[k]}
            for k, v in sorted(by_month.items())
        ],
    }


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    f = _as_float(value)
    return int(f) if f is not None else None


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    s = str(value)
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _trade_time(trade: Dict[str, Any]) -> Optional[datetime]:
    for key in (
        "exit_time_utc", "exitTimeUtc", "exit_time", "exitTime", "time", "exit_utc",
        "entry_time_utc", "entryTimeUtc", "entry_time", "entryTime",
    ):
        dt = _parse_iso(trade.get(key))
        if dt:
            return dt
    return None


def _trade_pnl(trade: Dict[str, Any]) -> float:
    for key in (
        "pnl_currency", "pnlCurrency", "profit_currency", "profitCurrency",
        "profit", "pnl", "net_profit", "netProfit", "ProfitCurrency",
    ):
        v = _as_float(trade.get(key))
        if v is not None:
            return v
    return 0.0


def _normalize_trade(trade: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(trade)
    dt = _trade_time(trade)
    pnl = _trade_pnl(trade)
    if dt:
        iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        out.setdefault("time_pt", trade.get("exit_time_pt") or trade.get("entry_time_pt") or iso)
        out.setdefault("exit_time", iso)
        out.setdefault("entry_time", trade.get("entry_time_utc") or trade.get("entryTimeUtc") or iso)
    out.setdefault("action", trade.get("action") or trade.get("side") or trade.get("direction") or "")
    out.setdefault("pnl", pnl)
    out.setdefault("profit", pnl)
    return out


def _series_from_trades(
    trades: List[Dict[str, Any]],
    experiment_id: str,
    class_name: Optional[str],
) -> Dict[str, Any]:
    parsed = []
    for trade in trades:
        dt = _trade_time(trade)
        if dt:
            parsed.append((dt, _trade_pnl(trade)))
    parsed.sort(key=lambda x: x[0])

    by_day: Dict[str, float] = defaultdict(float)
    equity_points = []
    drawdown_rows = []
    cumulative = 0.0
    peak = 0.0
    for dt, pnl in parsed:
        day = dt.strftime("%Y-%m-%d")
        cumulative += pnl
        by_day[day] += pnl
        peak = max(peak, cumulative)
        dd = cumulative - peak
        equity_points.append({"date": day, "value": cumulative})
        drawdown_rows.append({"label": day, "date": day, "pnl": dd})

    equity = []
    if equity_points:
        equity = [{
            "key": experiment_id,
            "strategy": class_name or experiment_id,
            "color": "#58d889",
            "points": equity_points,
        }]
    daily = [{"date": day, "pnl": pnl} for day, pnl in sorted(by_day.items())]
    # Drawdown chart is a bar chart; show the largest drawdowns first.
    drawdown = sorted(drawdown_rows, key=lambda r: r["pnl"])[:60]
    return {"daily": daily, "equity_curve": equity, "drawdown_series": drawdown}


def _normalize_equity_curve(raw: Any, experiment_id: str, class_name: Optional[str]) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        return []
    if isinstance(raw[0], dict) and isinstance(raw[0].get("points"), list):
        return raw
    points = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        date = _first_present(row.get("date"), row.get("time"), row.get("timestamp"))
        value = _as_float(_first_present(row.get("value"), row.get("equity"), row.get("pnl")))
        if date is not None and value is not None:
            points.append({"date": str(date)[:10], "value": value})
    if not points:
        return []
    return [{
        "key": experiment_id,
        "strategy": class_name or experiment_id,
        "color": "#58d889",
        "points": points,
    }]


def _normalize_pnl_rows(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        date = _first_present(row.get("date"), row.get("day"), row.get("time"), row.get("label"))
        pnl = _as_float(_first_present(row.get("pnl"), row.get("value"), row.get("dd"), row.get("drawdown")))
        if date is not None and pnl is not None:
            rows.append({"label": str(date)[:10], "date": str(date)[:10], "pnl": pnl})
    return rows


def backtest_payload(experiment_id: str) -> Dict[str, Any]:
    """Build a UI payload for the latest backtest of an experiment.

    Reads jobs/done/<job_id>/{result.json,trades.json,job.json} directly so
    the AI page can render equity, daily PnL, drawdown, metrics, trades.
    """
    exp = registry.read_experiment(experiment_id)
    if not exp:
        return {"ok": False, "reason": "experiment not found"}
    bts = exp.get("backtests") or []
    if not bts:
        return {"ok": False, "reason": "no backtests"}
    job_id = (bts[-1] or {}).get("job_id")
    if not job_id:
        return {"ok": False, "reason": "no job_id"}
    job_dir = ai_backtest.find_job_dir(job_id)
    if not job_dir:
        return {"ok": False, "reason": "job dir not found", "job_id": job_id}

    result = read_json(job_dir / "result.json", default={}) or {}
    job = read_json(job_dir / "job.json", default={}) or {}
    trades_doc = read_json(job_dir / "trades.json", default={}) or {}
    raw_trades = trades_doc.get("trades") if isinstance(trades_doc, dict) else trades_doc
    if not isinstance(raw_trades, list):
        raw_trades = []
    trades = [_normalize_trade(t) for t in raw_trades if isinstance(t, dict)]

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    result_metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    fallback_series = _series_from_trades(trades, experiment_id, exp.get("class_name"))

    net_pnl = _as_float(_first_present(
        summary.get("net_pnl"), summary.get("Net PnL"),
        result_metrics.get("net_profit_after_commission"), result_metrics.get("net_profit"),
        result.get("net_pnl"), result.get("net_profit"),
    ))
    if net_pnl is None and trades:
        net_pnl = sum(_trade_pnl(t) for t in trades)
    trades_total = _as_int(_first_present(
        summary.get("trades_total"), summary.get("Total # of Trades"),
        result_metrics.get("trade_count"), result_metrics.get("trades_total"),
        result.get("trade_count"), result.get("trades_total"),
    ))
    if trades_total is None:
        trades_total = len(trades)
    metrics = {
        "net_pnl": net_pnl,
        "trades_total": trades_total,
        "profit_factor": _as_float(_first_present(
            summary.get("profit_factor"), summary.get("Profit Factor"),
            result_metrics.get("profit_factor"), result.get("profit_factor"),
        )),
        "max_drawdown": _as_float(_first_present(
            summary.get("max_drawdown"), summary.get("Max. Drawdown"),
            result_metrics.get("max_drawdown"), result.get("max_drawdown"),
        )),
        "win_rate_pct": _as_float(_first_present(
            summary.get("win_rate_pct"), summary.get("Percent Profitable"),
            result_metrics.get("winning_pct"), result_metrics.get("win_rate_pct"),
            result.get("winning_pct"), result.get("win_rate_pct"),
        )),
        "sharpe": _as_float(_first_present(
            summary.get("sharpe"), summary.get("Sharpe Ratio"),
            result_metrics.get("sharpe"), result.get("sharpe"),
        )),
    }

    summary_out = dict(summary or result_metrics)
    summary_out.update({k: v for k, v in metrics.items() if v is not None})

    equity_curve = _normalize_equity_curve(
        result.get("equity_curve"), experiment_id, exp.get("class_name")
    ) or fallback_series["equity_curve"]
    daily = _normalize_pnl_rows(result.get("daily") or result.get("daily_pnl")) or fallback_series["daily"]
    drawdown_series = (
        _normalize_pnl_rows(result.get("drawdown_series") or result.get("drawdown"))
        or fallback_series["drawdown_series"]
    )

    return {
        "ok": True,
        "experiment_id": experiment_id,
        "job_id": job_id,
        "summary": summary_out,
        "metrics": metrics,
        "daily": daily,
        "equity_curve": equity_curve,
        "drawdown_series": drawdown_series,
        "trades": trades[-200:],
        "job_url": f"/ui/index.html?job={job_id}",
        "origin": "AI",
    }


def lifecycle_cards() -> Dict[str, Any]:
    """AI Lab strategies projected onto the 4-stage portfolio lifecycle board.

    Aggregates experiments to one card per ``ai_cell_id`` (latest attempt) and
    maps the AI status onto trial / approved_demo / approved_live /
    failed_archived so AI-built strategies appear next to production ones under
    the "AI / LM Studio" origin filter.
    """
    from .. import strategy_lifecycle as sl

    experiments = registry.list_experiments()
    by_cell: Dict[str, Dict[str, Any]] = {}
    counts: Dict[str, int] = defaultdict(int)
    for e in experiments:
        cid = str(e.get("ai_cell_id") or e.get("experiment_id") or "")
        if not cid:
            continue
        counts[cid] += 1
        cur = by_cell.get(cid)
        stamp = e.get("updated_at_utc") or e.get("created_at_utc") or ""
        cur_stamp = (cur.get("updated_at_utc") or cur.get("created_at_utc") or "") if cur else ""
        if cur is None or stamp >= cur_stamp:
            by_cell[cid] = e

    cards: List[Dict[str, Any]] = []
    for cid, e in by_cell.items():
        status = e.get("status")
        lifecycle = sl.lifecycle_for_ai_status(status)
        verdict = e.get("verdict") or {}
        reasons = verdict.get("reasons") or []
        reason = "; ".join(str(r) for r in reasons) or verdict.get("rejection_code") \
            or sl.ai_status_label_ru(status)
        card: Dict[str, Any] = {
            "profile_id": e.get("experiment_id"),
            "experiment_id": e.get("experiment_id"),
            "cell_id": cid,
            "name": e.get("class_name") or cid,
            "instrument": e.get("target_root") or "",
            "timeframe": "",
            "strategy_family": e.get("family"),
            "origin": sl.ORIGIN_AI_LAB,
            "origin_label": sl.ORIGIN_LABELS[sl.ORIGIN_AI_LAB],
            "is_ai_lab": True,
            "lifecycle": lifecycle,
            "lifecycle_label": sl.LIFECYCLE_LABELS[lifecycle],
            "ai_status": status,
            "ai_status_label": sl.ai_status_label_ru(status),
            "attempts": counts[cid],
            "updated_at_utc": e.get("updated_at_utc") or e.get("created_at_utc"),
        }
        if lifecycle == sl.FAILED_ARCHIVED:
            card["archive_reason"] = reason
            card["failed_archive"] = {
                "reason": reason,
                "removal_method": "ai_quarantine",
                "removed_from_ninjatrader": True,
                "ai_status": status,
            }
        elif lifecycle == sl.TRIAL:
            card["trial_progress"] = {
                "state": "running",
                "label": sl.ai_status_label_ru(status),
                "remaining_days": None, "percent": None, "basis": "ai_pipeline",
            }
            card["portfolio_reserved"] = True
        cards.append(card)

    cards.sort(key=lambda c: (sl.LIFECYCLE_ORDER.index(c["lifecycle"]),
                              str(c.get("instrument") or ""), str(c.get("name") or "")))
    by_lifecycle: Dict[str, int] = defaultdict(int)
    for c in cards:
        by_lifecycle[c["lifecycle"]] += 1
    return {
        "generated_at_utc": _now(),
        "count": len(cards),
        "by_lifecycle": dict(by_lifecycle),
        "cards": cards,
    }


def cell_history(ai_cell_id: str) -> Dict[str, Any]:
    """All AI experiments ever tried for one ``ai_cell_id`` (attempt history).

    Mirrors the production cell history: every variant tried for a cell, with its
    lifecycle stage and reject reason, so the operator can see e.g. "100 tries
    failed, the 101st passed".
    """
    from .. import strategy_lifecycle as sl

    cid = str(ai_cell_id or "").strip().upper()
    attempts: List[Dict[str, Any]] = []
    for e in registry.list_experiments():
        if str(e.get("ai_cell_id") or "").strip().upper() != cid:
            continue
        status = e.get("status")
        verdict = e.get("verdict") or {}
        reasons = verdict.get("reasons") or []
        analysis = e.get("analysis") or {}
        attempts.append({
            "experiment_id": e.get("experiment_id"),
            "ai_cell_id": e.get("ai_cell_id"),
            "name": e.get("class_name") or e.get("experiment_id"),
            "class_name": e.get("class_name"),
            "instrument": e.get("target_root"),
            "family": e.get("family"),
            "lifecycle": sl.lifecycle_for_ai_status(status),
            "lifecycle_label": sl.LIFECYCLE_LABELS[sl.lifecycle_for_ai_status(status)],
            "ai_status": status,
            "ai_status_label": sl.ai_status_label_ru(status),
            "verdict": verdict.get("outcome"),
            "rejection_code": verdict.get("rejection_code"),
            "reason": "; ".join(str(r) for r in reasons) or verdict.get("rejection_code") or "",
            "net_pnl": analysis.get("net_pnl") or analysis.get("avg_per_month"),
            "trade_count": analysis.get("trade_count"),
            "created_at_utc": e.get("created_at_utc"),
            "updated_at_utc": e.get("updated_at_utc"),
            "report_path": _report_path_for(e),
        })
    attempts.sort(key=lambda a: str(a.get("created_at_utc") or ""))
    by_lifecycle: Dict[str, int] = defaultdict(int)
    for a in attempts:
        by_lifecycle[a["lifecycle"]] += 1
    return {
        "ai_cell_id": cid,
        "count": len(attempts),
        "by_lifecycle": dict(by_lifecycle),
        "attempts": attempts,
    }
