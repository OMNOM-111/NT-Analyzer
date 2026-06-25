"""Stage 2 runtime/backtest mismatch diagnostic engine.

Produces the full per-strategy mismatch + attribution package required before any
relaunch decision, mining data that already exists locally:

  * acceptance/runtime profile cards  (data/profiles/strategies.json)
  * honest current-contract rerun jobs (artifacts jobs/done/<job_id>/...)
  * strict runtime fact               (app.performance closed trades)
  * raw runtime order/execution flow  (data/runtime/*.jsonl)

It does NOT run NinjaTrader. The reruns were executed separately; this engine
explains *why* historical backtests diverged from runtime across every criterion
the operator listed, enforces strict trade attribution, and emits a decision per
strategy.

Outputs (under <out_dir>):
  * mismatch_<CELL>.json    — full machine-readable per-strategy report
  * mismatch_report.md      — consolidated human-readable report
  * attribution_trades.csv  — every runtime closed trade with strict attribution
  * decisions.csv           — per-strategy verdict
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import ops
from . import performance as perf
from . import rerun_compare as rc

# Paused / problem cells under the relaunch gate (audit 2026-06-16).
TARGET_CELLS = ["CELL-001", "CELL-002", "CELL-003", "CELL-004", "CELL-005",
                "CELL-011", "CELL-015", "CELL-016", "CELL-017", "CELL-018"]

# Strict runtime observation window (PT wall dates) from the audit.
RUNTIME_FROM = "2026-05-13"
RUNTIME_TO = "2026-06-16"

# Minimum scored trades before a strategy decision is statistically meaningful.
MIN_DECISION_TRADES = 25

SEV_CRITICAL = "critical"
SEV_HIGH = "high"
SEV_MEDIUM = "medium"
SEV_LOW = "low"
SEV_INFO = "info"

STATUS_MATCH = "match"
STATUS_MISMATCH = "mismatch"
STATUS_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _cell_digits(cell_id: Any) -> str:
    m = re.search(r"(\d{3})", str(cell_id or ""))
    return m.group(1) if m else ""


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def same_bar_fill_stats(trades: List[Dict[str, Any]],
                        bar_seconds: int = 60) -> Dict[str, Any]:
    """Detect same-bar entry/exit fills in a backtest trade list.

    A scalp whose entry and exit land inside the *same* bar while booking a
    multi-tick target is the signature of High-fill / OnBarClose intrabar
    optimism: NinjaTrader assumes the bar's range filled both the entry and a
    distant target, which real runtime fills cannot reproduce. High same-bar
    rates with positive ticks are the structural cause of inflated backtests.
    """
    total = 0
    same_bar = 0
    same_bar_winners = 0
    tick_sum = 0.0
    for t in trades:
        if not isinstance(t, dict):
            continue
        total += 1
        a = _parse_iso(t.get("entry_time_utc"))
        b = _parse_iso(t.get("exit_time_utc"))
        if a is None or b is None:
            continue
        hold = abs((b - a).total_seconds())
        if hold < bar_seconds:
            same_bar += 1
            ticks = perf._num(t.get("pnl_ticks"))
            pnl = perf._num(t.get("pnl_currency"))
            if (ticks is not None and ticks > 0) or (pnl is not None and pnl > 0):
                same_bar_winners += 1
            if ticks is not None:
                tick_sum += ticks
    frac = (same_bar / total) if total else 0.0
    winner_ratio = (same_bar_winners / same_bar) if same_bar else 0.0
    return {
        "trades": total,
        "same_bar_fills": same_bar,
        "same_bar_fraction": round(frac, 4),
        "same_bar_winners": same_bar_winners,
        "same_bar_winner_ratio": round(winner_ratio, 4),
        "same_bar_avg_ticks": round(tick_sum / same_bar, 2) if same_bar else None,
        # A 1-minute scalp that opens AND closes most of its trades inside a
        # single bar is not runtime-realizable: intrabar High fill decides
        # target-vs-stop from OHLC assumptions, not real tick sequencing. The
        # fraction alone is the optimism signal; the winner ratio is secondary.
        "optimistic_fill_suspected": bool(total >= 5 and frac >= 0.6),
    }


def _criterion(name: str, backtest: Any, runtime: Any, status: str,
               severity: str, evidence: str) -> Dict[str, Any]:
    return {
        "criterion": name,
        "backtest": backtest,
        "runtime": runtime,
        "status": status,
        "severity": severity if status == STATUS_MISMATCH else
                    (SEV_INFO if status == STATUS_MATCH else severity),
        "evidence": evidence,
    }


def _root(value: Any) -> str:
    return perf.rt._instrument_root(value)


def compare_conditions(profile: Dict[str, Any],
                       job: Dict[str, Any],
                       runtime_facts: Dict[str, Any],
                       same_bar: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the full backtest-vs-runtime criteria matrix for one strategy."""
    lp = (profile.get("locked_parameters") or {}) if profile else {}
    jexec = (job.get("execution") or {}) if job else {}
    jparams = ((job.get("strategy") or {}).get("parameters") or {}) if job else {}
    jinstr = str((job or {}).get("instrument") or "")
    jtf = (job.get("timeframe") or {}) if job else {}
    prof_contract = str((profile or {}).get("current_contract") or (profile or {}).get("instrument") or "")
    traded = sorted(runtime_facts.get("traded_contracts") or [])
    out: List[Dict[str, Any]] = []

    # 1. trading windows
    bt_win = f"{jparams.get('TradeStartTime')}-{jparams.get('TradeEndTime')}"
    out.append(_criterion(
        "trading_windows", bt_win,
        {"profile_pt": profile.get("trade_window_pt") if profile else None,
         "observed_pt_exit": runtime_facts.get("observed_pt_window")},
        STATUS_UNKNOWN,
        SEV_MEDIUM,
        "Strategy window minutes-of-day are PT; observed PT span is exit-time "
        "based (includes force-flat/stop-close) so verify entry times stay in window."))

    # 2. session template
    bt_sess = str(jexec.get("session_template") or jparams.get("SessionTemplateName") or "")
    prof_sess = str(lp.get("SessionTemplateName") or (profile.get("execution") or {}).get("session_template") if profile else "")
    out.append(_criterion(
        "session_template", bt_sess, prof_sess,
        STATUS_MATCH if bt_sess and bt_sess == prof_sess else
        (STATUS_MISMATCH if bt_sess and prof_sess else STATUS_UNKNOWN),
        SEV_HIGH,
        "Session template controls RTH bars; a mismatch shifts the whole bar series."))

    # 3. timezone / Pacific Time
    bt_tz = str(jexec.get("timezone") or "")
    out.append(_criterion(
        "timezone_pacific", bt_tz, "windows defined in PT",
        STATUS_MISMATCH if bt_tz.upper() == "UTC" else STATUS_UNKNOWN,
        SEV_HIGH,
        "Backtest timezone=UTC while TradeStart/End are PT minutes; verify the "
        "wrapper converts Time[0] to PT or windows shift by the UTC-PT offset."))

    # 4. fill model
    bt_fill = str(jexec.get("order_fill_resolution") or "")
    out.append(_criterion(
        "fill_model", bt_fill, "real demo fills",
        STATUS_MISMATCH,
        SEV_CRITICAL if same_bar.get("optimistic_fill_suspected") else SEV_HIGH,
        f"High-fill backtest vs real fills. Same-bar fill fraction="
        f"{same_bar.get('same_bar_fraction')} winners={same_bar.get('same_bar_winners')}"
        f"/{same_bar.get('same_bar_fills')}."))

    # 5. High/Standard/tick execution
    out.append(_criterion(
        "execution_granularity",
        {"calculate": jexec.get("calculate"), "tick_replay": jexec.get("is_tick_replay")},
        "live tick-by-tick",
        STATUS_MISMATCH if not jexec.get("is_tick_replay") else STATUS_UNKNOWN,
        SEV_HIGH,
        "OnBarClose + no tick replay cannot model intrabar stop/target ordering "
        "that decides real outcomes."))

    # 6. commissions
    bt_comm = perf._num(jexec.get("round_turn_commission"))
    out.append(_criterion(
        "commission", bt_comm,
        {"telemetry": runtime_facts.get("runtime_commission_seen"), "estimate_used": float(ops.ROUND_TURN_COMMISSION)},
        STATUS_UNKNOWN,
        SEV_MEDIUM,
        "Runtime executions report commission=0; reports estimate; stress >= $2.50 RT."))

    # 7. slippage
    out.append(_criterion(
        "slippage", perf._num(jexec.get("slippage_ticks")),
        runtime_facts.get("runtime_slippage_note"),
        STATUS_UNKNOWN,
        SEV_HIGH,
        "Backtest slippage is a fixed tick assumption; runtime stop-market "
        "slippage is variable and not captured per cell."))

    # 8. rollover / contract
    contracts_3way = {"profile": prof_contract, "backtest": jinstr, "runtime_traded": traded}
    roots = {_root(prof_contract), _root(jinstr)} | {_root(c) for c in traded}
    same_root = len([r for r in roots if r]) <= 1
    exact_match = bool(jinstr) and traded == [jinstr]
    out.append(_criterion(
        "rollover_contract", jinstr, contracts_3way,
        STATUS_MATCH if exact_match else STATUS_MISMATCH,
        SEV_HIGH,
        "3-way contract drift: profile/backtest/runtime must be the exact same "
        "contract month, otherwise behavior and liquidity differ." if not exact_match
        else "Backtest and runtime traded the same contract."))

    # 9. instrument root
    out.append(_criterion(
        "instrument_root", _root(jinstr),
        sorted({_root(c) for c in traded if c}),
        STATUS_MATCH if same_root else STATUS_MISMATCH,
        SEV_CRITICAL, "Instrument root must match."))

    # 10. strategy parameters
    diffs = {}
    for k, v in lp.items():
        if k in jparams and str(jparams[k]) != str(v):
            diffs[k] = {"profile": v, "backtest": jparams[k]}
    out.append(_criterion(
        "strategy_parameters", f"{len(jparams)} params",
        {"diff_count": len(diffs), "diffs": diffs},
        STATUS_MATCH if not diffs else STATUS_MISMATCH,
        SEV_HIGH,
        "Locked profile params must equal the params actually backtested/run."))

    # 11. stop / target logic
    out.append(_criterion(
        "stop_target_logic",
        {"RR": jparams.get("RewardRiskRatio"), "MinStop": jparams.get("MinStopTicks"),
         "MaxStop": jparams.get("MaxStopTicks"), "MinTarget": jparams.get("MinTargetTicks")},
        {"RR": lp.get("RewardRiskRatio"), "MinStop": lp.get("MinStopTicks"),
         "MaxStop": lp.get("MaxStopTicks"), "MinTarget": lp.get("MinTargetTicks")},
        STATUS_MATCH if str(jparams.get("RewardRiskRatio")) == str(lp.get("RewardRiskRatio")) else STATUS_UNKNOWN,
        SEV_HIGH,
        "High RR targets realized in same-bar backtests but rarely in runtime."))

    # 12. order handling (same-bar)
    out.append(_criterion(
        "order_handling", "backtest intrabar fill", "sequential live orders",
        STATUS_MISMATCH if same_bar.get("optimistic_fill_suspected") else STATUS_UNKNOWN,
        SEV_CRITICAL if same_bar.get("optimistic_fill_suspected") else SEV_MEDIUM,
        f"{same_bar.get('same_bar_fills')}/{same_bar.get('trades')} backtest trades "
        f"open+close in one bar (avg {same_bar.get('same_bar_avg_ticks')} ticks)."))

    # 13. rejected orders
    out.append(_criterion(
        "rejected_orders", "n/a (backtest)",
        runtime_facts.get("account_rejected_orders"),
        STATUS_MISMATCH if (runtime_facts.get("account_rejected_orders") or 0) else STATUS_MATCH,
        SEV_MEDIUM, "Rejected orders exist only in runtime; backtest never models them."))

    # 14. partial fills
    out.append(_criterion(
        "partial_fills", "n/a (backtest)",
        runtime_facts.get("account_partial_fills"),
        STATUS_MISMATCH if (runtime_facts.get("account_partial_fills") or 0) else STATUS_MATCH,
        SEV_LOW, "Partial fills exist only in runtime."))

    # 15. unmatched exits
    out.append(_criterion(
        "unmatched_exits", 0, runtime_facts["categories"].get("unmatched", 0),
        STATUS_MISMATCH if runtime_facts["categories"].get("unmatched", 0) else STATUS_MATCH,
        SEV_MEDIUM, "Unmatched exits are excluded from strategy scoring."))

    # 16. account-level collisions
    out.append(_criterion(
        "account_level_collisions", 0,
        {"account_level": runtime_facts["categories"].get("account_level", 0),
         "concurrent_strategies": runtime_facts.get("concurrent_strategies")},
        STATUS_MISMATCH if runtime_facts["categories"].get("account_level", 0) else STATUS_MATCH,
        SEV_HIGH, "Simultaneous MNQ strategies share one account position book."))

    # 17. strategy attribution
    out.append(_criterion(
        "strategy_attribution", "deterministic (single strategy)",
        {"attributed_exec_pct": runtime_facts.get("attributed_exec_pct"),
         "unmapped_trades": runtime_facts["categories"].get("unmapped", 0)},
        STATUS_MISMATCH if (runtime_facts.get("attributed_exec_pct") or 0) < 0.95 else STATUS_MATCH,
        SEV_HIGH, "Runtime exits without attribution cannot be scored to a strategy."))

    # 18. runtime instance mapping
    out.append(_criterion(
        "runtime_instance_mapping", "n/a",
        {"distinct_runtime_instance_ids": runtime_facts.get("distinct_runtime_instance_ids"),
         "rows_with_iid_pct": runtime_facts.get("rows_with_iid_pct")},
        STATUS_MISMATCH if (runtime_facts.get("rows_with_iid_pct") or 0) < 0.95 else STATUS_MATCH,
        SEV_HIGH, "runtime_instance_id missing on runtime rows blocks instance-level proof."))

    # 19. demo vs historical conditions (period/regime)
    bt_period = (job.get("period") or {}) if job else {}
    prof_period = (profile.get("test_period") or {}) if profile else {}
    out.append(_criterion(
        "demo_vs_historical_period",
        {"acceptance_backtest": prof_period, "rerun_backtest": bt_period},
        {"runtime_window": f"{RUNTIME_FROM}..{RUNTIME_TO}"},
        STATUS_MISMATCH,
        SEV_HIGH,
        "Acceptance backtest covered a different (often multi-year) regime than "
        "the 1-month runtime window; edge may be regime-specific."))

    return out


def decide(cell_id: str,
           runtime_pnl: Optional[float],
           scored_trades: int,
           after_best: Optional[float],
           after_worst: Optional[float],
           same_bar: Dict[str, Any],
           critical_mismatches: int) -> Dict[str, Any]:
    """Per-strategy relaunch decision under the audit's relaunch gate."""
    runtime_negative = runtime_pnl is not None and runtime_pnl < 0
    bt_positive = (after_worst is not None and after_worst > 0)

    if scored_trades < MIN_DECISION_TRADES:
        decision = "observation"
        reason = (f"Only {scored_trades} scored runtime trades; sample too small "
                  "for a relaunch decision.")
    elif same_bar.get("optimistic_fill_suspected") and bt_positive and runtime_negative:
        decision = "needs_work"
        reason = ("Backtest edge depends on same-bar/High-fill optimism "
                  f"({same_bar.get('same_bar_fraction')} same-bar) while strict runtime "
                  f"PnL is negative ({runtime_pnl}); root cause is the fill model, not costs.")
    elif runtime_negative and bt_positive:
        decision = "needs_work"
        reason = ("Backtest stays positive but strict runtime fact is negative "
                  f"({runtime_pnl}); systemic cause unresolved.")
    elif runtime_negative:
        decision = "reject_candidate"
        reason = f"Strict runtime PnL negative ({runtime_pnl}) and no surviving backtest edge."
    elif bt_positive and not runtime_negative:
        decision = "relaunch_candidate"
        reason = "Stressed backtest edge survives and runtime fact is not negative."
    else:
        decision = "observation"
        reason = "Inconclusive; keep observing."

    return {
        "cell_id": cell_id,
        "decision": decision,
        "relaunch_allowed": decision == "relaunch_candidate" and critical_mismatches == 0,
        "reason": reason,
        "critical_mismatches": critical_mismatches,
    }


# ---------------------------------------------------------------------------
# IO + assembly
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    return ops._project_root()


def load_profiles() -> Dict[str, Dict[str, Any]]:
    p = _project_root() / "data" / "profiles" / "strategies.json"
    doc = ops._read_json(p, {})
    out: Dict[str, Dict[str, Any]] = {}
    for prof in (doc.get("profiles") or []):
        cid = str(prof.get("cell_id") or "")
        if cid and cid not in out:  # first card wins (latest)
            out[cid] = prof
    return out


def load_rerun_index(research_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    doc = ops._read_json(research_dir / "backtest_results.json", {})
    by_cell: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in (doc.get("success") or []):
        by_cell[str(row.get("cell_id") or "")].append(row)
    return by_cell


def _read_job_artifacts(job_id: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    from . import jobqueue as jq
    loc = jq.find_job_dir(job_id)
    if not loc:
        return {}, []
    _state, jdir = loc
    job = ops._read_json(jdir / "job.json", {})
    trades_doc = ops._read_json(jdir / "trades.json", [])
    if isinstance(trades_doc, dict):
        trades = trades_doc.get("trades") or []
    else:
        trades = trades_doc if isinstance(trades_doc, list) else []
    return job, trades


def runtime_facts_for_cell(cell_digits: str,
                           runtime_trades: List[Dict[str, Any]],
                           account_facts: Dict[str, Any]) -> Dict[str, Any]:
    cell_trades = [t for t in runtime_trades if _cell_digits(t.get("cell_id")) == cell_digits]
    cats = Counter(t.get("category") for t in cell_trades)
    times = sorted(str(t.get("time_pt") or "") for t in cell_trades if t.get("time_pt"))
    iid_rows = sum(1 for t in cell_trades if str(t.get("runtime_instance_id") or "").strip())
    normal = [t for t in cell_trades if t.get("category") == perf.TRADE_CATEGORY_NORMAL]
    return {
        "cell_trades": cell_trades,
        "trade_count": len(cell_trades),
        "scored_trade_count": len(normal),
        "scored_pnl": round(sum(float(t.get("pnl") or 0.0) for t in normal), 2),
        "all_pnl": round(sum(float(t.get("pnl") or 0.0) for t in cell_trades), 2),
        "categories": dict(cats),
        "traded_contracts": sorted({str(t.get("instrument") or "") for t in cell_trades if t.get("instrument")}),
        "observed_pt_window": (f"{times[0]}-{times[-1]}" if times else None),
        "distinct_runtime_instance_ids": len({str(t.get("runtime_instance_id") or "") for t in cell_trades if str(t.get("runtime_instance_id") or "").strip()}),
        "rows_with_iid_pct": round(iid_rows / len(cell_trades), 3) if cell_trades else None,
        "runtime_commission_seen": account_facts.get("runtime_commission_seen"),
        "runtime_slippage_note": account_facts.get("runtime_slippage_note"),
        "account_rejected_orders": account_facts.get("rejected_orders"),
        "account_partial_fills": account_facts.get("partial_fills"),
        "attributed_exec_pct": account_facts.get("attributed_exec_pct"),
        "concurrent_strategies": account_facts.get("concurrent_strategies"),
    }


def account_facts() -> Dict[str, Any]:
    rdir = _project_root() / "data" / "runtime"
    rejected = partial = total_exec = attr_exec = 0
    comm_seen = False
    for name, is_exec in (("orders.jsonl", False), ("executions.jsonl", True)):
        path = rdir / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if is_exec:
                total_exec += 1
                if str(o.get("runtime_instance_id") or "").strip() or str(o.get("strategy_class") or "").strip():
                    attr_exec += 1
                if perf._num(o.get("commission")):
                    comm_seen = True
            else:
                st = str(o.get("order_state") or "")
                if st == "Rejected":
                    rejected += 1
                if st == "PartFilled":
                    partial += 1
    return {
        "rejected_orders": rejected,
        "partial_fills": partial,
        "attributed_exec_pct": round(attr_exec / total_exec, 3) if total_exec else None,
        "runtime_commission_seen": comm_seen,
        "runtime_slippage_note": "not captured per cell (telemetry has no slippage field)",
        "concurrent_strategies": "MNQ cells C012-C018 share one account/instrument book",
    }


def attribution_breakdown(cell_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Strict per-strategy attribution: daily / weekly / cycle rollups + per-trade
    rows carrying every field the operator requires, with category labels."""
    def _week(d: str) -> str:
        dt = perf._parse_ymd(d)
        if dt is None:
            return ""
        monday = dt - timedelta(days=dt.weekday())
        return monday.isoformat()

    per_day: Dict[str, float] = defaultdict(float)
    per_week: Dict[str, float] = defaultdict(float)
    per_cycle: Dict[str, float] = defaultdict(float)
    cats = Counter()
    rows = []
    for t in cell_trades:
        cat = str(t.get("category") or "")
        cats[cat] += 1
        pnl = float(t.get("pnl") or 0.0)
        day = str(t.get("date_pt") or "")
        cycle = str(t.get("trading_cycle_id") or "(none)")
        if cat == perf.TRADE_CATEGORY_NORMAL:
            per_day[day] += pnl
            per_week[_week(day)] += pnl
            per_cycle[cycle] += pnl
        rows.append({
            "date_pt": day,
            "entry_strategy_class": t.get("entry_strategy_class"),
            "exit_strategy_class": t.get("strategy_class"),
            "cell_id": t.get("cell_id"),
            "runtime_instance_id": t.get("runtime_instance_id"),
            "trading_cycle_id": t.get("trading_cycle_id"),
            "entry_time_utc": t.get("entry_time_utc"),
            "exit_time_utc": t.get("exit_time_utc"),
            "quantity": t.get("quantity"),
            "gross_pnl": t.get("gross_pnl"),
            "commission": t.get("commission"),
            "net_pnl": t.get("pnl"),
            "category": cat,
            "attribution_status": t.get("attribution_status"),
        })
    return {
        "categories": dict(cats),
        "scored_per_day": {k: round(v, 2) for k, v in sorted(per_day.items())},
        "scored_per_week": {k: round(v, 2) for k, v in sorted(per_week.items())},
        "scored_per_cycle": {k: round(v, 2) for k, v in sorted(per_cycle.items())},
        "trades": rows,
    }


def build_cell_report(cell_id: str,
                      profiles: Dict[str, Dict[str, Any]],
                      rerun_by_cell: Dict[str, List[Dict[str, Any]]],
                      runtime_trades: List[Dict[str, Any]],
                      acct: Dict[str, Any]) -> Dict[str, Any]:
    digits = _cell_digits(cell_id)
    profile = profiles.get(cell_id) or {}
    reruns = rerun_by_cell.get(cell_id) or []
    rfacts = runtime_facts_for_cell(digits, runtime_trades, acct)

    # Representative rerun job: prefer the lowest-slippage 1.90 variant.
    rep = next((r for r in reruns if r.get("slippage_ticks") == 2 and r.get("round_turn_commission") == 1.9), None)
    rep = rep or (reruns[0] if reruns else None)
    job, bt_trades = ({}, [])
    if rep:
        job, bt_trades = _read_job_artifacts(rep.get("job_id"))

    sb = same_bar_fill_stats(bt_trades)
    criteria = compare_conditions(profile, job, rfacts, sb)
    breakdown = attribution_breakdown(rfacts["cell_trades"])

    after_best = max((perf._num(r.get("net_profit")) for r in reruns
                      if perf._num(r.get("net_profit")) is not None), default=None)
    after_worst = min((perf._num(r.get("net_profit")) for r in reruns
                       if perf._num(r.get("net_profit")) is not None), default=None)
    critical = sum(1 for c in criteria if c["status"] == STATUS_MISMATCH and c["severity"] == SEV_CRITICAL)
    decision = decide(cell_id, rfacts["scored_pnl"], rfacts["scored_trade_count"],
                      after_best, after_worst, sb, critical)

    mismatches = [c for c in criteria if c["status"] == STATUS_MISMATCH]
    return {
        "cell_id": cell_id,
        "strategy_class": profile.get("deploy_strategy_class") or profile.get("strategy_class") or (rep or {}).get("class_name"),
        "profile_id": profile.get("profile_id"),
        "notes_id": profile.get("stable_id") or profile.get("runtime_strategy_id"),
        "runtime": {
            "scored_trade_count": rfacts["scored_trade_count"],
            "scored_pnl": rfacts["scored_pnl"],
            "all_pnl": rfacts["all_pnl"],
            "categories": rfacts["categories"],
            "traded_contracts": rfacts["traded_contracts"],
            "observed_pt_window": rfacts["observed_pt_window"],
        },
        "backtest_rerun": {
            "job_id": (rep or {}).get("job_id"),
            "instrument": (rep or {}).get("instrument"),
            "best_net_profit": after_best,
            "worst_net_profit": after_worst,
            "min_trade_count": min((perf._num(r.get("trade_count")) or 0 for r in reruns), default=0),
            "fingerprint_placeholder": any(r.get("fingerprint_placeholder") for r in reruns),
        },
        "same_bar_fill_stats": sb,
        "criteria": criteria,
        "mismatch_count": len(mismatches),
        "critical_mismatch_count": critical,
        "top_causes": [
            {"criterion": c["criterion"], "severity": c["severity"], "evidence": c["evidence"]}
            for c in sorted(mismatches, key=lambda x: ["critical", "high", "medium", "low", "info"].index(x["severity"]))[:6]
        ],
        "attribution": breakdown,
        "decision": decision,
    }


def generate_package(out_dir: Optional[Path] = None) -> Dict[str, Any]:
    research_dir = _project_root() / "data" / "research" / "runtime_mismatch_repair_20260616"
    out_dir = out_dir or (research_dir / "diagnostic")
    out_dir.mkdir(parents=True, exist_ok=True)

    profiles = load_profiles()
    rerun_by_cell = load_rerun_index(research_dir)
    acct = account_facts()
    _res, runtime_trades, _meta, _all = perf._closed_trades_for_request(
        period="custom", from_date=RUNTIME_FROM, to_date=RUNTIME_TO)

    reports = []
    for cell_id in TARGET_CELLS:
        rep = build_cell_report(cell_id, profiles, rerun_by_cell, runtime_trades, acct)
        reports.append(rep)
        slim = {k: v for k, v in rep.items() if k != "attribution"}
        slim["attribution"] = {k: v for k, v in rep["attribution"].items() if k != "trades"}
        (out_dir / f"mismatch_{cell_id}.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    _write_decisions_csv(out_dir / "decisions.csv", reports)
    _write_attribution_csv(out_dir / "attribution_trades.csv", reports)
    (out_dir / "mismatch_report.md").write_text(_render_markdown(reports, acct), encoding="utf-8")

    return {"out_dir": str(out_dir), "cells": [r["cell_id"] for r in reports],
            "reports": reports}


def _write_decisions_csv(path: Path, reports: List[Dict[str, Any]]) -> None:
    cols = ["cell_id", "strategy_class", "scored_trade_count", "scored_runtime_pnl",
            "best_backtest", "worst_backtest", "same_bar_fraction",
            "critical_mismatches", "decision", "relaunch_allowed", "reason"]
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in reports:
        w.writerow({
            "cell_id": r["cell_id"],
            "strategy_class": r["strategy_class"],
            "scored_trade_count": r["runtime"]["scored_trade_count"],
            "scored_runtime_pnl": r["runtime"]["scored_pnl"],
            "best_backtest": r["backtest_rerun"]["best_net_profit"],
            "worst_backtest": r["backtest_rerun"]["worst_net_profit"],
            "same_bar_fraction": r["same_bar_fill_stats"]["same_bar_fraction"],
            "critical_mismatches": r["critical_mismatch_count"],
            "decision": r["decision"]["decision"],
            "relaunch_allowed": r["decision"]["relaunch_allowed"],
            "reason": r["decision"]["reason"],
        })
    path.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


def _write_attribution_csv(path: Path, reports: List[Dict[str, Any]]) -> None:
    cols = ["date_pt", "cell_id", "entry_strategy_class", "exit_strategy_class",
            "runtime_instance_id", "trading_cycle_id", "entry_time_utc", "exit_time_utc",
            "quantity", "gross_pnl", "commission", "net_pnl", "category", "attribution_status"]
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in reports:
        for row in r["attribution"]["trades"]:
            w.writerow(row)
    path.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


def _render_markdown(reports: List[Dict[str, Any]], acct: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Runtime/backtest per-strategy mismatch diagnostic — 2026-06-16")
    lines.append("")
    lines.append("Strict, per-criterion explanation of why historical backtests diverged from "
                 "demo/runtime, with hard trade attribution and a per-strategy decision.")
    lines.append("")
    lines.append(f"Runtime window: {RUNTIME_FROM}..{RUNTIME_TO} PT. "
                 f"Account rejected orders: {acct.get('rejected_orders')}, "
                 f"partial fills: {acct.get('partial_fills')}, "
                 f"attributed executions: {acct.get('attributed_exec_pct')}.")
    lines.append("")
    lines.append("## Decisions")
    lines.append("")
    lines.append("| Cell | Strategy | Scored trades | Runtime PnL | Worst BT | Same-bar % | Decision | Relaunch |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- | --- |")
    for r in reports:
        d = r["decision"]
        lines.append("| {cell} | {cls} | {n} | {rp} | {wb} | {sb} | {dec} | {rl} |".format(
            cell=r["cell_id"], cls=r["strategy_class"],
            n=r["runtime"]["scored_trade_count"], rp=r["runtime"]["scored_pnl"],
            wb=r["backtest_rerun"]["worst_net_profit"],
            sb=f"{r['same_bar_fill_stats']['same_bar_fraction']*100:.0f}%",
            dec=d["decision"], rl="yes" if d["relaunch_allowed"] else "no"))
    lines.append("")
    for r in reports:
        lines.append(f"## {r['cell_id']} — {r['strategy_class']}")
        lines.append("")
        rt = r["runtime"]
        bt = r["backtest_rerun"]
        lines.append(f"- Runtime: {rt['scored_trade_count']} scored trades, strict PnL "
                     f"{rt['scored_pnl']} (all-category {rt['all_pnl']}); categories {rt['categories']}.")
        lines.append(f"- Rerun backtest ({bt['instrument']}): best {bt['best_net_profit']}, "
                     f"worst {bt['worst_net_profit']}, min trades {bt['min_trade_count']}, "
                     f"fingerprint placeholder={bt['fingerprint_placeholder']}.")
        sb = r["same_bar_fill_stats"]
        lines.append(f"- Same-bar fills: {sb['same_bar_fills']}/{sb['trades']} "
                     f"({sb['same_bar_fraction']*100:.0f}%), avg {sb['same_bar_avg_ticks']} ticks, "
                     f"optimistic_fill_suspected={sb['optimistic_fill_suspected']}.")
        lines.append(f"- **Decision: {r['decision']['decision']}** "
                     f"(relaunch_allowed={r['decision']['relaunch_allowed']}). {r['decision']['reason']}")
        lines.append("")
        lines.append("Top causes:")
        for c in r["top_causes"]:
            lines.append(f"  - [{c['severity']}] {c['criterion']}: {c['evidence']}")
        lines.append("")
        lines.append("Full criteria matrix:")
        lines.append("")
        lines.append("| Criterion | Status | Severity | Backtest | Runtime |")
        lines.append("| --- | --- | --- | --- | --- |")
        for c in r["criteria"]:
            lines.append("| {cr} | {st} | {sv} | {bt} | {rt} |".format(
                cr=c["criterion"], st=c["status"], sv=c["severity"],
                bt=_short(c["backtest"]), rt=_short(c["runtime"])))
        lines.append("")
    return "\n".join(lines) + "\n"


def _short(value: Any, limit: int = 70) -> str:
    s = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    s = s.replace("|", "/").replace("\n", " ")
    return s if len(s) <= limit else s[:limit - 1] + "…"


if __name__ == "__main__":
    result = generate_package()
    print(f"package -> {result['out_dir']}")
    for rep in result["reports"]:
        d = rep["decision"]
        print(f"  {rep['cell_id']}: {d['decision']} "
              f"(runtime={rep['runtime']['scored_pnl']}, "
              f"worst_bt={rep['backtest_rerun']['worst_net_profit']}, "
              f"same_bar={rep['same_bar_fill_stats']['same_bar_fraction']})")
