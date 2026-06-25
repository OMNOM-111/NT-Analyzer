"""Research/validation runner for MNQ CELL-019 pre-cash compression breakout.

Targets the standalone NTAMnqPreCashCompressionBreakoutC019 class (new
"Compression Breakout" family). Does NOT use NTAMicroMnqScalpPilot or any
C015/C016 carrier. 5-minute bars, pre-cash ETH window.

Stages: Stage-0 smoke (compact sweep) -> Full -> IS/OOS -> Stress
(slip=2, fee=2.40, slip=2+fee=2.40) -> Current30D.

Outputs are written under
data/research/mnq_cell019_precash_compression_<ts>/.

Usage:
    python run_mnq_cell019_precash_compression_breakout.py            # full pipeline
    python run_mnq_cell019_precash_compression_breakout.py --smoke-only
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402


CLASS_NAME = "NTAMnqPreCashCompressionBreakoutC019"
ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
# Pre-cash window lives in the ETH session; RTH template has no pre-06:30 PT bars.
SESSION_TEMPLATE = "CME US Index Futures ETH"
BARS_PERIOD_VALUE = 5
BASE_TF_SECONDS = 300

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

SMOKE = ("Smoke", "2025-09-01T00:00:00Z", "2025-12-31T23:59:59Z")

FEE_BASE = max(1.90, RL.fee_for(ROOT))
FEE_STRESS = 2.40


def current_window(days: int = 30) -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def base_params() -> Dict[str, Any]:
    return {
        "InstrumentName": ROOT,
        "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": BASE_TF_SECONDS,
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True,
        "EnableShort": True,
        "ConfirmMode": "ReclaimOrContinuation",
        "TradeStartTime": 320,
        "TradeEndTime": 555,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 100,
        "SecondTradeEndTime": 300,
        "ForceFlatTime": 559,
        "EmaFastPeriod": 9,
        "EmaMidPeriod": 21,
        "EmaSlowPeriod": 50,
        "AtrPeriod": 14,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.6,
        "RequireVwapAgreement": True,
        "RequireEmaAgreement": True,
        "RequireEmaSlope": True,
        "CompressionLookbackBars": 8,
        "MaxCompressionRangeTicks": 60,
        "CompressionAtrMult": 1.30,
        "MinCompressionRangeTicks": 8,
        "BreakoutBufferTicks": 2,
        "RetestTicks": 4,
        "RetestTimeoutBars": 4,
        "ReclaimTicks": 1,
        "VolExpansionFactor": 1.20,
        "MinBarRangeTicks": 4,
        "StopBufferTicks": 4,
        "MinStopTicks": 16,
        "MaxStopTicks": 40,
        "AtrStopMult": 1.0,
        "RewardRiskRatio": 1.6,
        "MinTargetTicks": 16,
        "EntryOffsetTicks": 0,
        "EntryTimeoutBars": 3,
        "MoveToBreakevenAtR": 1.0,
        "BreakevenPlusTicks": 2,
        "UseTrailingStop": False,
        "TrailAfterR": 1.5,
        "TrailDistanceTicks": 12,
        "UseTimeStop": True,
        "TimeStopBars": 6,
        "MinProgressR": 0.30,
        "RiskPerTradePct": 0.75,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 80.0,
        "MaxWeeklyLossUsd": 200.0,
        "MaxTradesPerDay": 4,
        "HardMaxTradesPerDay": 6,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 60,
        "RoundTurnCommission": FEE_BASE,
        "SlippageTicks": 1,
    }


def candidate(label: str, **overrides: Any) -> Dict[str, Any]:
    p = base_params()
    p.update(overrides)
    return {"label": label, "params": p}


def candidates() -> List[Dict[str, Any]]:
    """Compact, meaningful Stage-0 sweep (24 variants).

    Dimensions: 3 entry windows x 2 confirm modes x 2 RR x 2 compression ATR
    multipliers. Stop geometry and filters held at sane defaults for smoke.
    """
    out: List[Dict[str, Any]] = []
    windows = [(320, 555), (300, 530), (200, 530)]
    confirm_modes = ["ReclaimOrContinuation", "Retest"]
    rrs = [1.6, 2.0]
    atr_mults = [1.10, 1.40]
    for (start, end) in windows:
        for confirm in confirm_modes:
            for rr in rrs:
                for atr_mult in atr_mults:
                    cm = "rc" if confirm == "ReclaimOrContinuation" else "rt"
                    label = f"w{start}_{end}_{cm}_rr{int(rr * 10):03d}_atr{int(atr_mult * 100):03d}"
                    out.append(candidate(
                        label,
                        TradeStartTime=start,
                        TradeEndTime=end,
                        ForceFlatTime=min(end + 4, 559) if end <= 555 else 559,
                        ConfirmMode=confirm,
                        RewardRiskRatio=rr,
                        CompressionAtrMult=atr_mult,
                    ))
    return out


def submit_job(
    *,
    bundle: Path,
    label: str,
    stage: str,
    period_label: str,
    from_utc: str,
    to_utc: str,
    params: Dict[str, Any],
    fee: float = FEE_BASE,
    slip: int = 1,
) -> Dict[str, Any]:
    p = dict(params)
    p.update({
        "RoundTurnCommission": fee,
        "SlippageTicks": slip,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "InstrumentStatus": "allowed",
        "MaxContractsByCapital": 20,
    })
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=p,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=BARS_PERIOD_VALUE,
        slippage_ticks=slip,
        # ETH template is catalog-flagged supported=false; submit as smoke so the
        # backend does not reject it. Bridge resolves and applies the template.
        role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    row = {
        "stage": stage,
        "label": label,
        "period_label": period_label,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "fee": fee,
        "slip": slip,
        "code": code,
        "job_id": job_id,
        "response": resp,
        "params": p,
    }
    print(f"submit {stage:10s} {label:34s} {period_label:16s} code={code} job={job_id or resp}", flush=True)
    (bundle / "latest_submitted.json").write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    return row


def job_state(job_id: str) -> Optional[str]:
    base = RL.jobs_root()
    for state in ("done", "failed", "cancelled", "running", "pending"):
        if (base / state / job_id).is_dir():
            return state
    if (base / "failed" / ".quarantine" / job_id).is_dir():
        return "failed"
    return None


def wait_for_jobs(rows: List[Dict[str, Any]], timeout_s: int = 21600) -> None:
    remaining = {str(r["job_id"]) for r in rows if r.get("job_id")}
    deadline = time.time() + timeout_s
    last_print = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            if job_state(job_id) in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        now = time.time()
        if now - last_print >= 30 and remaining:
            print(f"waiting: {len(remaining)} CELL-019 jobs still pending/running", flush=True)
            last_print = now
        time.sleep(3)


def trades_from(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return trades
    d = Path(str(report.get("_dir") or ""))
    p = d / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
            return raw["trades"]
    return []


def trade_qty(trade: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(trade.get("quantity") or 1.0)))
    except Exception:
        return 1.0


def adjusted_pnls(trades: Iterable[Dict[str, Any]], fee: float) -> List[float]:
    out: List[float] = []
    for trade in trades:
        out.append(float(trade.get("pnl_currency") or 0.0) - fee * trade_qty(trade))
    return out


def _bar_bucket(ts: str) -> Optional[int]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    epoch = int(dt.timestamp())
    return epoch // BASE_TF_SECONDS


def same_bar_pct(trades: List[Dict[str, Any]]) -> float:
    """Percentage of trades whose entry and exit fall in the same base bar."""
    if not trades:
        return 0.0
    same = 0
    counted = 0
    for t in trades:
        eb = _bar_bucket(str(t.get("entry_time_utc") or ""))
        xb = _bar_bucket(str(t.get("exit_time_utc") or ""))
        if eb is None or xb is None:
            continue
        counted += 1
        if eb == xb:
            same += 1
    return round(same / counted * 100.0, 2) if counted else 0.0


def weekdays(from_utc: str, to_utc: str) -> int:
    start = date.fromisoformat(from_utc[:10])
    end = date.fromisoformat(to_utc[:10])
    if end < start:
        return 0
    total = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            total += 1
        cur += timedelta(days=1)
    return total


def max_consecutive_losses(pnls: Iterable[float]) -> int:
    best = 0
    cur = 0
    for pnl in pnls:
        if pnl < 0.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def summarize(row: Dict[str, Any], report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(row)
    out.pop("response", None)
    out.pop("params", None)
    if not report or "result" not in report:
        out.update({"status": job_state(str(row.get("job_id") or "")) or "missing", "trade_count": 0})
        return out

    trades = trades_from(report)
    fee = float(row.get("fee") or 0.0)
    pnls = adjusted_pnls(trades, fee)
    gross_profit = sum(p for p in pnls if p > 0.0)
    gross_loss = abs(sum(p for p in pnls if p < 0.0))
    adj_net = sum(pnls)
    adj_pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    active_days = Counter(
        str(t.get("entry_time_utc") or t.get("exit_time_utc") or "")[:10]
        for t in trades
        if t.get("entry_time_utc") or t.get("exit_time_utc")
    )
    active_counts = list(active_days.values())
    total_days = weekdays(str(row.get("from_utc")), str(row.get("to_utc")))
    out.update({
        "status": job_state(str(row.get("job_id"))) or "unknown",
        "status_dir": report.get("_dir", ""),
        "trade_count": len(trades),
        "calendar_weekdays": total_days,
        "trades_per_day": round(len(trades) / total_days, 4) if total_days else 0.0,
        "active_days": len(active_counts),
        "trades_per_active_day": round(len(trades) / len(active_counts), 4) if active_counts else 0.0,
        "adj_net": round(adj_net, 2),
        "adj_pf": adj_pf,
        "win_rate": round((sum(1 for p in pnls if p > 0.0) / len(pnls) * 100.0) if pnls else 0.0, 2),
        "avg_trade_after_commission": round(adj_net / len(pnls), 2) if pnls else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_consecutive_losses": max_consecutive_losses(pnls),
        "same_bar_pct": same_bar_pct(trades),
        "gross_profit_after_commission": round(gross_profit, 2),
        "gross_loss_after_commission": round(gross_loss, 2),
    })
    return out


def collect_rows(bundle: Path, rows: List[Dict[str, Any]], filename: str) -> List[Dict[str, Any]]:
    wait_for_jobs(rows)
    summaries: List[Dict[str, Any]] = []
    for row in rows:
        job_id = str(row.get("job_id") or "")
        report = RL.read_job_report(job_id) if job_id else None
        summary = summarize(row, report)
        summaries.append(summary)
        pf = summary.get("adj_pf")
        pf_s = "inf" if pf == math.inf else f"{float(pf or 0.0):.3f}"
        print(
            f"done   {row['stage']:10s} {row['label']:34s} {row['period_label']:16s} "
            f"trades={int(summary.get('trade_count') or 0):>5} "
            f"tpd={float(summary.get('trades_per_day') or 0.0):>6.2f} "
            f"net={float(summary.get('adj_net') or 0.0):>9.2f} "
            f"pf={pf_s:>7s} dd={float(summary.get('max_drawdown') or 0.0):>9.2f} "
            f"sb%={float(summary.get('same_bar_pct') or 0.0):>5.1f}",
            flush=True,
        )
        (bundle / filename).write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    return summaries


def score(row: Dict[str, Any]) -> float:
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("max_drawdown") or 0.0))
    trades = int(row.get("trade_count") or 0)
    if trades <= 0:
        return -999999.0
    pf_capped = min(pf, 3.0) if not math.isinf(pf) else 3.0
    return net + pf_capped * 120.0 + min(trades, 600) * 0.5 - dd * 0.4


def pick_smoke(rows: List[Dict[str, Any]], limit: int) -> List[str]:
    eligible = [
        r for r in rows
        if int(r.get("trade_count") or 0) >= 8
        and float(r.get("adj_net") or 0.0) > 0.0
        and (math.isinf(float(r.get("adj_pf") or 0.0)) or float(r.get("adj_pf") or 0.0) >= 1.10)
    ]
    if not eligible:
        eligible = [r for r in rows if int(r.get("trade_count") or 0) > 0]
    eligible.sort(key=score, reverse=True)
    return [str(r["label"]) for r in eligible[:limit]]


def gates(full: Dict[str, Any], is_: Dict[str, Any], oos: Dict[str, Any],
          stress_combined: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, bool]:
    def f(r: Dict[str, Any], k: str) -> float:
        v = r.get(k)
        if v is None:
            return 0.0
        if v == math.inf:
            return 99.0
        return float(v)
    return {
        "full_net_pos": f(full, "adj_net") > 0.0,
        "full_pf_135": f(full, "adj_pf") >= 1.35,
        "oos_pf_125": f(oos, "adj_pf") >= 1.25,
        "max_dd_pct_15": RL.max_drawdown_within_budget(f(full, "max_drawdown")),
        "stress_combined_nonneg": f(stress_combined, "adj_net") >= 0.0,
        "current30d_nonneg": f(current, "adj_net") >= 0.0,
        "enough_trades": int(full.get("trade_count") or 0) >= 40,
        "is_net_pos": f(is_, "adj_net") > 0.0,
        "low_same_bar": f(full, "same_bar_pct") <= 50.0,
    }


def write_markdown(bundle: Path, final: Dict[str, Any]) -> None:
    def pf(v: Any) -> str:
        try:
            x = float(v)
        except Exception:
            return ""
        return "inf" if math.isinf(x) else f"{x:.3f}"

    lines = [
        "# MNQ CELL-019 Pre-Cash Compression Breakout",
        "",
        f"Bundle: `{bundle.name}`",
        f"Class: `{CLASS_NAME}`",
        f"Session template: `{SESSION_TEMPLATE}` | Timeframe: {BARS_PERIOD_VALUE} Minute",
        "",
    ]
    for section, key in [
        ("Smoke", "smoke_rows"),
        ("Validation (Full/IS/OOS)", "validation_rows"),
        ("Stress", "stress_rows"),
        ("Current30D", "current_rows"),
    ]:
        rows = final.get(key) or []
        if not rows:
            continue
        lines += [
            f"## {section}",
            "",
            "| Label | Period | Trades | TPD | Net | PF | WinRate | Avg | DD | SameBar% |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in sorted(rows, key=score, reverse=True):
            lines.append(
                f"| `{r.get('label','')}` | {r.get('period_label','')} | {int(r.get('trade_count') or 0)} | "
                f"{float(r.get('trades_per_day') or 0.0):.2f} | "
                f"{float(r.get('adj_net') or 0.0):.2f} | {pf(r.get('adj_pf'))} | "
                f"{float(r.get('win_rate') or 0.0):.1f} | "
                f"{float(r.get('avg_trade_after_commission') or 0.0):.2f} | "
                f"{float(r.get('max_drawdown') or 0.0):.2f} | "
                f"{float(r.get('same_bar_pct') or 0.0):.1f} |"
            )
        lines.append("")
    decision = final.get("decision") or {}
    lines += ["## Decision", "", "```json", json.dumps(decision, indent=2, ensure_ascii=False), "```", ""]
    (bundle / "cell019_compression_summary.md").write_text("\n".join(lines), encoding="utf-8")


def run(smoke_only: bool, smoke_top: int) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"mnq_cell019_precash_compression_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    final: Dict[str, Any] = {
        "class_name": CLASS_NAME,
        "instrument": INSTRUMENT,
        "session_template": SESSION_TEMPLATE,
        "bars_period_value": BARS_PERIOD_VALUE,
        "created_utc": RL.utcnow_iso(),
    }

    # ---- Stage 0: smoke -----------------------------------------------------
    smoke_rows_submitted = [
        submit_job(
            bundle=bundle, label=c["label"], stage="smoke",
            period_label=SMOKE[0], from_utc=SMOKE[1], to_utc=SMOKE[2],
            params=c["params"], fee=FEE_BASE, slip=1,
        )
        for c in candidates()
    ]
    smoke_rows = collect_rows(bundle, smoke_rows_submitted, "smoke_rows.json")
    final["smoke_rows"] = smoke_rows
    survivors = pick_smoke(smoke_rows, smoke_top)
    final["smoke_survivors"] = survivors
    (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"smoke survivors: {survivors}", flush=True)

    if smoke_only or not survivors:
        final["decision"] = {
            "status": "smoke_only" if smoke_only else "rejected",
            "reason": "smoke_only flag" if smoke_only else "no smoke survivor passed minimal filters",
        }
        (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_markdown(bundle, final)
        return

    label_to_params = {c["label"]: c["params"] for c in candidates()}

    # ---- Full / IS / OOS ----------------------------------------------------
    val_submitted: List[Dict[str, Any]] = []
    for label in survivors:
        params = label_to_params[label]
        for period_label, frm, to in (FULL, IS, OOS):
            val_submitted.append(submit_job(
                bundle=bundle, label=label, stage="validation",
                period_label=period_label, from_utc=frm, to_utc=to,
                params=params, fee=FEE_BASE, slip=1,
            ))
    validation_rows = collect_rows(bundle, val_submitted, "validation_rows.json")
    final["validation_rows"] = validation_rows

    def by_label_period(rows: List[Dict[str, Any]], label: str, period: str) -> Dict[str, Any]:
        for r in rows:
            if r.get("label") == label and r.get("period_label") == period:
                return r
        return {}

    # Pick the best validated survivor by Full score among those with Full net>0.
    full_candidates = [
        by_label_period(validation_rows, label, "Full")
        for label in survivors
    ]
    full_candidates = [r for r in full_candidates if r and float(r.get("adj_net") or 0.0) > 0.0]
    full_candidates.sort(key=score, reverse=True)
    best_label = str(full_candidates[0]["label"]) if full_candidates else None
    final["best_label"] = best_label

    if not best_label:
        final["decision"] = {
            "status": "rejected",
            "reason": "no survivor produced a positive Full adjusted net",
        }
        (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_markdown(bundle, final)
        return

    best_params = label_to_params[best_label]

    # ---- Stress -------------------------------------------------------------
    stress_submitted = [
        submit_job(bundle=bundle, label=best_label, stage="stress",
                   period_label="slip2", from_utc=FULL[1], to_utc=FULL[2],
                   params=best_params, fee=FEE_BASE, slip=2),
        submit_job(bundle=bundle, label=best_label, stage="stress",
                   period_label="fee240", from_utc=FULL[1], to_utc=FULL[2],
                   params=best_params, fee=FEE_STRESS, slip=1),
        submit_job(bundle=bundle, label=best_label, stage="stress",
                   period_label="slip2_fee240", from_utc=FULL[1], to_utc=FULL[2],
                   params=best_params, fee=FEE_STRESS, slip=2),
    ]
    stress_rows = collect_rows(bundle, stress_submitted, "stress_rows.json")
    final["stress_rows"] = stress_rows

    # ---- Current30D ---------------------------------------------------------
    cur_from, cur_to = current_window(30)
    current_submitted = [
        submit_job(bundle=bundle, label=best_label, stage="current",
                   period_label="Current30D", from_utc=cur_from, to_utc=cur_to,
                   params=best_params, fee=FEE_BASE, slip=1),
    ]
    current_rows = collect_rows(bundle, current_submitted, "current_rows.json")
    final["current_rows"] = current_rows

    # ---- Gates / decision ---------------------------------------------------
    full = by_label_period(validation_rows, best_label, "Full")
    is_ = by_label_period(validation_rows, best_label, "IS")
    oos = by_label_period(validation_rows, best_label, "OOS")
    combined = next((r for r in stress_rows if r.get("period_label") == "slip2_fee240"), {})
    current = current_rows[0] if current_rows else {}

    gate_results = gates(full, is_, oos, combined, current)
    passed = all(gate_results.values())
    final["gate_results"] = gate_results
    final["decision"] = {
        "status": "paper_candidate" if passed else "rejected",
        "best_label": best_label,
        "locked_params": best_params,
        "gates": gate_results,
        "full": full, "is": is_, "oos": oos,
        "stress_combined": combined, "current30d": current,
    }
    (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    write_markdown(bundle, final)
    print(f"DECISION: {final['decision']['status']} (best={best_label})", flush=True)
    print(f"gates: {gate_results}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke-only", action="store_true")
    ap.add_argument("--smoke-top", type=int, default=4)
    args = ap.parse_args()
    run(smoke_only=args.smoke_only, smoke_top=args.smoke_top)


if __name__ == "__main__":
    main()
