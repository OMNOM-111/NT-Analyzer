"""Stage 2 scaffold: honest reruns + before/runtime/after comparison.

The runtime/backtest mismatch audit (2026-06-16) requires, before any strategy
relaunch:

  * honest backtest reruns under *current contracts* and stress assumptions
    (High fill, slippage 2-3 ticks, real commission), and
  * an explicit before/runtime/after comparison per strategy.

The actual reruns must execute inside NinjaTrader (the bridge). This module is
the deterministic, testable scaffold around them: it builds the stress job
templates that the bridge/queue should run, and normalizes old backtest, runtime
fact and new backtest into a single comparison verdict.

No NinjaTrader dependency. Pure data transforms so they can be unit-tested and
reused by the queue, the AI lab and any reporting surface.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Current front-month contracts the reruns must target (runtime moved off the
# 06-26 profiles documented in the audit).
STRESS_CONTRACTS: Dict[str, str] = {
    "MNQ": "MNQ SEP26",
    "MGC": "MGC AUG26",
    "MES": "MES SEP26",
    "MNG": "MNG AUG26",
}

# Slippage stress ladder for stop-market scalps (audit: slip=1 too optimistic).
STRESS_SLIPPAGE_TICKS: List[int] = [2, 3]

# Commission stress (audit: runtime commission unknown / 0; stress >= $2.50 RT).
STRESS_COMMISSION_TEMPLATES: List[str] = ["NinjaTrader Micro", "Aggressive 2.50 RT"]

# Strategies the audit paused; each must clear the relaunch gate before going
# live again. Sessions are PT trading windows from the existing profiles.
RELAUNCH_TARGET_CELLS: Dict[str, Dict[str, Any]] = {
    "CELL-015": {"root": "MNQ", "timeframe_min": 1, "session_template": "CME US Index Futures RTH"},
    "CELL-016": {"root": "MNQ", "timeframe_min": 1, "session_template": "CME US Index Futures RTH"},
    "CELL-017": {"root": "MNQ", "timeframe_min": 1, "session_template": "CME US Index Futures RTH"},
    "CELL-018": {"root": "MNQ", "timeframe_min": 1, "session_template": "CME US Index Futures RTH"},
    "CELL-001": {"root": "MGC", "timeframe_min": 5, "session_template": "Nymex Metals RTH1"},
    "CELL-002": {"root": "MGC", "timeframe_min": 5, "session_template": "Nymex Metals RTH1"},
    "CELL-003": {"root": "MGC", "timeframe_min": 5, "session_template": "Nymex Metals RTH1"},
    "CELL-004": {"root": "MGC", "timeframe_min": 5, "session_template": "Nymex Metals RTH1"},
    "CELL-005": {"root": "MGC", "timeframe_min": 5, "session_template": "Nymex Metals RTH1"},
}


def current_contract(root: str) -> str:
    """Front-month contract for a root, or the bare root if unknown."""
    return STRESS_CONTRACTS.get(str(root or "").upper(), str(root or "").upper())


def build_rerun_job_templates(cell_id: str,
                              class_name: str,
                              from_utc: str,
                              to_utc: str,
                              parameters: Optional[Dict[str, Any]] = None,
                              timezone: str = "UTC") -> List[Dict[str, Any]]:
    """Build the honest-rerun job payloads for one paused cell.

    One job per (slippage, commission) stress combination, all on the current
    contract with High fill resolution. These payloads are shaped for
    ``jobqueue.CreateJobRequest`` / the bridge job.json execution block.
    """
    cell = RELAUNCH_TARGET_CELLS.get(str(cell_id).upper())
    if cell is None:
        raise ValueError(f"unknown relaunch cell: {cell_id!r}")
    instrument = current_contract(cell["root"])
    jobs: List[Dict[str, Any]] = []
    for slip in STRESS_SLIPPAGE_TICKS:
        for commission_template in STRESS_COMMISSION_TEMPLATES:
            jobs.append({
                "kind": "historical_backtest",
                "origin": {"stage2_rerun": True, "cell_id": str(cell_id).upper()},
                "class_name": class_name,
                "instrument": instrument,
                "timeframe": {"bars_period_type": "Minute", "value": int(cell["timeframe_min"])},
                "period": {"from_utc": from_utc, "to_utc": to_utc},
                "parameters": dict(parameters or {}),
                "execution": {
                    "calculate": "OnBarClose",
                    "is_tick_replay": False,
                    "order_fill_resolution": "High",
                    "slippage_ticks": int(slip),
                    "commission": 0.0,
                    "commission_template": commission_template,
                    "session_template": cell["session_template"],
                    "timezone": timezone,
                    "role": "research",
                },
            })
    return jobs


def _num(value: Any) -> Optional[float]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n


def normalize_backtest_metrics(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize a bridge result.json ``metrics`` block to the common shape."""
    metrics = (result or {}).get("metrics") if isinstance(result, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    return {
        "trades": _num(metrics.get("trade_count")),
        "net_pnl": _num(metrics.get("net_profit")),
        "win_rate": _num(metrics.get("winning_pct")),
        "profit_factor": _num(metrics.get("profit_factor")),
    }


def normalize_runtime_fact(strategy_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize a Performance Center strategy row to the common shape.

    Uses the *scored* (``normal``-category) strategy numbers, i.e. account-level
    / unmapped / rollover trades are already excluded upstream.
    """
    row = strategy_row if isinstance(strategy_row, dict) else {}
    pf_pct = _num(row.get("profit_factor_pct"))
    profit_factor = _num(row.get("profit_factor"))
    if profit_factor is None and pf_pct is not None:
        profit_factor = 1.0 + pf_pct / 100.0
    return {
        "trades": _num(row.get("scored_trade_count")) if row.get("scored_trade_count") is not None else _num(row.get("trades")),
        "net_pnl": _num(row.get("pnl")),
        "win_rate": _num(row.get("win_rate")),
        "profit_factor": profit_factor,
    }


def _delta(after: Optional[float], before: Optional[float]) -> Optional[float]:
    if after is None or before is None:
        return None
    return round(after - before, 4)


def build_comparison(strategy_label: str,
                     old_backtest: Optional[Dict[str, Any]],
                     runtime_row: Optional[Dict[str, Any]],
                     new_backtest: Optional[Dict[str, Any]],
                     min_trades: int = 25) -> Dict[str, Any]:
    """Produce a before/runtime/after comparison with a relaunch verdict.

    * ``before``  — original (optimistic) backtest metrics.
    * ``runtime`` — honest, strictly-attributed runtime fact.
    * ``after``   — new honest backtest under current contract + stress.

    Verdict:
      * ``insufficient``   — not enough scored trades to judge.
      * ``edge_destroyed`` — the honest after-backtest is unprofitable.
      * ``edge_survives``  — after-backtest stays profitable under stress.
    """
    before = normalize_backtest_metrics(old_backtest)
    runtime = normalize_runtime_fact(runtime_row)
    after = normalize_backtest_metrics(new_backtest)

    after_trades = after.get("trades")
    after_pnl = after.get("net_pnl")
    after_pf = after.get("profit_factor")

    if after_trades is None or after_trades < min_trades:
        verdict = "insufficient"
    elif (after_pnl is not None and after_pnl <= 0.0) or (after_pf is not None and after_pf < 1.0):
        verdict = "edge_destroyed"
    else:
        verdict = "edge_survives"

    return {
        "strategy": strategy_label,
        "before": before,
        "runtime": runtime,
        "after": after,
        "deltas": {
            "net_pnl_after_vs_before": _delta(after.get("net_pnl"), before.get("net_pnl")),
            "net_pnl_after_vs_runtime": _delta(after.get("net_pnl"), runtime.get("net_pnl")),
            "win_rate_after_vs_runtime": _delta(after.get("win_rate"), runtime.get("win_rate")),
        },
        "verdict": verdict,
        "relaunch_allowed": verdict == "edge_survives",
    }
