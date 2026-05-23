"""Research/validation runner for MNQ CELL-015 liquidity sweep reversal.

This runner targets the standalone NTAMnqLiquiditySweepReversalC015 class. It
does not use NTAMicroMnqScalpPilot or the CELL-016 opening-drive carrier stack.
Outputs are written under data/research/mnq_cell015_liquidity_sweep_<ts>/.
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


CLASS_NAME = "NTAMnqLiquiditySweepReversalC015"
ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = RL.session_for(ROOT)

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")


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
        "BaseTimeframeSeconds": 60,
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True,
        "EnableShort": True,
        "SignalMode": "Sweep",
        "TradeStartTime": 635,
        "TradeEndTime": 1245,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1300,
        "EmaFastPeriod": 9,
        "EmaSlowPeriod": 34,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.5,
        "MinAdx": 0.0,
        "MaxAdx": 80.0,
        "UseEmaStretchFilter": False,
        "MinEmaStretchTicks": 0,
        "SweepLookbackBars": 6,
        "FadeSweeps": True,
        "SweepDistanceTicks": 1,
        "ReclaimTicks": 0,
        "OpeningRangeStartTime": 630,
        "OpeningRangeMinutes": 3,
        "OpeningRangeBreakBufferTicks": 0,
        "MinOpeningRangeTicks": 4,
        "MaxOpeningRangeTicks": 160,
        "UseVwapDistanceFilter": True,
        "MinVwapDistanceTicks": 8,
        "MaxVwapDistanceTicks": 120,
        "RequireCloseAgainstSweep": True,
        "MinBarRangeTicks": 4,
        "MinBodyRangePct": 0.10,
        "MinCloseLocationPct": 0.35,
        "MomentumLookbackBars": 2,
        "MomentumBreakTicks": 0,
        "RequireMomentumBreak": False,
        "OpenPressureMinScore": 2,
        "StopBufferTicks": 2,
        "MinStopTicks": 6,
        "MaxStopTicks": 12,
        "AtrStopMult": 0.25,
        "RewardRiskRatio": 1.50,
        "MinTargetTicks": 6,
        "EntryOffsetTicks": 0,
        "EntryTimeoutBars": 2,
        "MoveToBreakevenAtR": 0.80,
        "BreakevenPlusTicks": 1,
        "UseTrailingStop": True,
        "TrailAfterR": 1.20,
        "TrailDistanceTicks": 6,
        "UseTimeStop": True,
        "TimeStopBars": 4,
        "MinProgressR": 0.25,
        "RiskPerTradePct": 0.35,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "DailyLossLimit": 60.0,
        "WeeklyLossLimit": 150.0,
        "MaxTradesPerDay": 18,
        "HardMaxTradesPerDay": 24,
        "MaxConsecutiveLosses": 4,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "RoundTurnCommission": RL.fee_for(ROOT),
        "SlippageTicks": 1,
    }


def candidate(label: str, **overrides: Any) -> Dict[str, Any]:
    p = base_params()
    direction = str(overrides.pop("Direction", "both"))
    p["EnableLong"] = direction in {"long", "both"}
    p["EnableShort"] = direction in {"short", "both"}
    p.update(overrides)
    return {"label": label, "params": p}


def candidates() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # name, score, sweep lookback, momentum lookback, min range, body, close loc,
    # min volume, stop buffer, min stop, max stop, RR, BE, trailing, time stop bars,
    # min progress, daily, weekly, max losses, pause after, pause minutes,
    # max trades, hard max trades
    base_risk = (60.0, 150.0, 8, 0, 15, 30, 40)
    recipes = [
        ("score1_fast_rr250", 1, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 2.50, 0.0, False, 3, 0.20, *base_risk),
        ("score1_fast_rr300", 1, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 3.00, 0.0, False, 3, 0.20, *base_risk),
        ("score1_fast_rr400", 1, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 4.00, 0.0, False, 3, 0.20, *base_risk),
        ("score2_fast_rr300", 2, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 3.00, 0.0, False, 3, 0.20, *base_risk),
        ("score2_fast_rr400", 2, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 4.00, 0.0, False, 3, 0.20, *base_risk),
        ("score2_clean_rr350", 2, 4, 2, 3, 0.05, 0.25, 0.0, 1, 4, 10, 3.50, 0.0, False, 3, 0.20, *base_risk),
        ("score2_clean_rr400", 2, 4, 2, 3, 0.05, 0.25, 0.0, 1, 4, 10, 4.00, 0.0, False, 3, 0.20, *base_risk),
        ("score2_vol08_rr350", 2, 4, 2, 3, 0.05, 0.25, 0.8, 1, 4, 10, 3.50, 0.0, False, 3, 0.20, *base_risk),
        ("score2_vol08_rr400", 2, 4, 2, 3, 0.05, 0.25, 0.8, 1, 4, 10, 4.00, 0.0, False, 3, 0.20, *base_risk),
        ("score3_clean_rr300", 3, 5, 2, 3, 0.05, 0.30, 0.0, 1, 4, 10, 3.00, 0.0, False, 3, 0.20, *base_risk),
        ("score2_be_rr300", 2, 4, 2, 3, 0.05, 0.25, 0.0, 1, 4, 10, 3.00, 0.70, True, 4, 0.30, *base_risk),
        ("score2_wide_rr300", 2, 5, 2, 3, 0.05, 0.25, 0.0, 1, 5, 12, 3.00, 0.0, False, 3, 0.20, *base_risk),
        ("score1_fast_rr300_d45w120", 1, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 3.00, 0.0, False, 3, 0.20, 45.0, 120.0, 3, 2, 20, 20, 25),
        ("score1_fast_rr400_d45w120", 1, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 4.00, 0.0, False, 3, 0.20, 45.0, 120.0, 3, 2, 20, 20, 25),
        ("score1_fast_rr300_lock40", 1, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 3.00, 0.0, False, 3, 0.20, 40.0, 100.0, 2, 1, 20, 15, 20),
        ("score1_fast_rr400_lock40", 1, 3, 1, 2, 0.00, 0.20, 0.0, 1, 4, 10, 4.00, 0.0, False, 3, 0.20, 40.0, 100.0, 2, 1, 20, 15, 20),
        ("score2_be_rr300_d45w120", 2, 4, 2, 3, 0.05, 0.25, 0.0, 1, 4, 10, 3.00, 0.70, True, 4, 0.30, 45.0, 120.0, 3, 2, 20, 20, 25),
        ("score2_be_rr300_lock40", 2, 4, 2, 3, 0.05, 0.25, 0.0, 1, 4, 10, 3.00, 0.70, True, 4, 0.30, 40.0, 100.0, 2, 1, 20, 15, 20),
        ("score2_clean_rr400_d45w120", 2, 4, 2, 3, 0.05, 0.25, 0.0, 1, 4, 10, 4.00, 0.0, False, 3, 0.20, 45.0, 120.0, 3, 2, 20, 20, 25),
        ("score2_clean_rr400_lock40", 2, 4, 2, 3, 0.05, 0.25, 0.0, 1, 4, 10, 4.00, 0.0, False, 3, 0.20, 40.0, 100.0, 2, 1, 20, 15, 20),
    ]
    windows = [(635, 700), (635, 730), (635, 800), (635, 830), (635, 1000)]
    for start, end in windows:
        for recipe_name, score_min, sweep_lookback, momentum_lookback, min_range, min_body, min_close_loc, min_vol, stop_buffer, min_stop, max_stop, rr, be_at_r, trailing, time_stop_bars, min_progress, daily_loss, weekly_loss, max_losses, pause_after, pause_minutes, max_trades, hard_max_trades in recipes:
            out.append(candidate(
                f"short_openpressure_{recipe_name}_{end}",
                Direction="short",
                SignalMode="OpenPressureStopShort",
                TradeStartTime=start,
                TradeEndTime=end,
                SweepLookbackBars=sweep_lookback,
                SweepDistanceTicks=0,
                ReclaimTicks=2,
                MomentumLookbackBars=momentum_lookback,
                MomentumBreakTicks=0,
                OpenPressureMinScore=score_min,
                OpeningRangeStartTime=630,
                OpeningRangeMinutes=3,
                OpeningRangeBreakBufferTicks=1,
                MinOpeningRangeTicks=4,
                MaxOpeningRangeTicks=160,
                UseVwapDistanceFilter=False,
                UseEmaStretchFilter=False,
                MinVolumeFactor=min_vol,
                MinBodyRangePct=min_body,
                MinCloseLocationPct=min_close_loc,
                RequireCloseAgainstSweep=True,
                MinBarRangeTicks=min_range,
                StopBufferTicks=stop_buffer,
                MinStopTicks=min_stop,
                MaxStopTicks=max_stop,
                AtrStopMult=0.0,
                RewardRiskRatio=rr,
                MinTargetTicks=6,
                EntryOffsetTicks=0,
                EntryTimeoutBars=2,
                MoveToBreakevenAtR=be_at_r,
                UseTrailingStop=trailing,
                TrailAfterR=1.0,
                TrailDistanceTicks=6,
                UseTimeStop=True,
                TimeStopBars=time_stop_bars,
                MinProgressR=min_progress,
                RiskPerTradePct=0.50,
                DailyLossLimit=daily_loss,
                WeeklyLossLimit=weekly_loss,
                MaxTradesPerDay=max_trades,
                HardMaxTradesPerDay=hard_max_trades,
                MaxConsecutiveLosses=max_losses,
                PauseAfterConsecutiveLosses=pause_after,
                PauseMinutesAfterLosses=pause_minutes,
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
    fee: float = 1.90,
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
        bars_period_value=1,
        slippage_ticks=slip,
        role="smoke" if stage == "smoke" else "research",
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
    print(f"submit {stage:10s} {label:46s} {period_label:16s} code={code} job={job_id or resp}", flush=True)
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


def wait_for_jobs(rows: List[Dict[str, Any]], timeout_s: int = 14400) -> None:
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
            print(f"waiting: {len(remaining)} CELL-015 jobs still pending/running", flush=True)
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
        "pct_active_days_with_2plus": round(
            sum(1 for x in active_counts if x >= 2) / len(active_counts) * 100.0,
            4,
        ) if active_counts else 0.0,
        "adj_net": round(adj_net, 2),
        "adj_pf": adj_pf,
        "win_rate": round((sum(1 for p in pnls if p > 0.0) / len(pnls) * 100.0) if pnls else 0.0, 2),
        "avg_trade_after_commission": round(adj_net / len(pnls), 2) if pnls else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_consecutive_losses": max_consecutive_losses(pnls),
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
            f"done   {row['stage']:10s} {row['label']:46s} {row['period_label']:16s} "
            f"trades={int(summary.get('trade_count') or 0):>5} "
            f"tpd={float(summary.get('trades_per_day') or 0.0):>6.2f} "
            f"net={float(summary.get('adj_net') or 0.0):>9.2f} "
            f"pf={pf_s:>7s} dd={float(summary.get('max_drawdown') or 0.0):>9.2f}",
            flush=True,
        )
        (bundle / filename).write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    return summaries


def score(row: Dict[str, Any]) -> float:
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("max_drawdown") or 0.0))
    trades = int(row.get("trade_count") or 0)
    tpd = float(row.get("trades_per_day") or 0.0)
    active_2 = float(row.get("pct_active_days_with_2plus") or 0.0)
    if trades <= 0:
        return -999999.0
    return net + min(pf, 3.0) * 120.0 + min(trades, 3000) * 0.35 + tpd * 60.0 + active_2 - dd * 0.35


def pick_smoke(rows: List[Dict[str, Any]], limit: int) -> List[str]:
    eligible = [
        r for r in rows
        if int(r.get("trade_count") or 0) >= 10
        and float(r.get("adj_net") or 0.0) > 0.0
        and float(r.get("adj_pf") or 0.0) >= 1.05
    ]
    if not eligible:
        eligible = [r for r in rows if int(r.get("trade_count") or 0) > 0]
    eligible.sort(key=score, reverse=True)
    return [str(r["label"]) for r in eligible[:limit]]


def core_pass(rows: List[Dict[str, Any]], label: str) -> bool:
    by_period = {r.get("period_label"): r for r in rows if r.get("label") == label}
    full = by_period.get("Full") or {}
    is_ = by_period.get("IS") or {}
    oos = by_period.get("OOS") or {}
    return (
        float(full.get("adj_net") or 0.0) > 0.0
        and float(full.get("adj_pf") or 0.0) >= 1.35
        and abs(float(full.get("max_drawdown") or 0.0)) <= 300.0
        and int(full.get("trade_count") or 0) >= 250
        and float(is_.get("adj_net") or 0.0) > 0.0
        and float(oos.get("adj_net") or 0.0) > 0.0
        and float(oos.get("adj_pf") or 0.0) >= 1.25
    )


def write_markdown(bundle: Path, final: Dict[str, Any]) -> None:
    def pf(v: Any) -> str:
        try:
            x = float(v)
        except Exception:
            return ""
        return "inf" if math.isinf(x) else f"{x:.3f}"

    lines = [
        "# MNQ CELL-015 Open Pressure Stop",
        "",
        f"Bundle: `{bundle}`",
        f"Class: `{CLASS_NAME}`",
        "",
    ]
    for section, rows in [
        ("Smoke", final.get("smoke_rows") or []),
        ("Validation", final.get("validation_rows") or []),
        ("Stress", final.get("stress_rows") or []),
        ("Current", final.get("current_rows") or []),
    ]:
        if not rows:
            continue
        lines += [
            f"## {section}",
            "",
            "| Label | Period | Trades | TPD | Active 2+ % | Net | PF | Avg | DD | Loss streak |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in sorted(rows, key=score, reverse=True):
            lines.append(
                f"| `{r.get('label','')}` | {r.get('period_label','')} | {int(r.get('trade_count') or 0)} | "
                f"{float(r.get('trades_per_day') or 0.0):.2f} | {float(r.get('pct_active_days_with_2plus') or 0.0):.1f} | "
                f"{float(r.get('adj_net') or 0.0):.2f} | {pf(r.get('adj_pf'))} | "
                f"{float(r.get('avg_trade_after_commission') or 0.0):.2f} | "
                f"{float(r.get('max_drawdown') or 0.0):.2f} | {int(r.get('max_consecutive_losses') or 0)} |"
            )
        lines.append("")

    if final.get("gate_decisions"):
        lines += ["## Gate Decisions", "", "| Label | Core | Stress | Current | Decision |", "|---|---:|---:|---:|---|"]
        for d in final["gate_decisions"]:
            lines.append(f"| `{d['label']}` | {d['core_pass']} | {d['stress_pass']} | {d['current_pass']} | {d['decision']} |")
    (bundle / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["smoke", "validation", "stress", "all"], default="all")
    ap.add_argument("--label", action="append")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args(argv[1:])

    bundle = RL.DATA / "research" / f"mnq_cell015_liquidity_sweep_{RL.utcnow_compact()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    all_candidates = candidates()
    selected = [c for c in all_candidates if not args.label or c["label"] in args.label]
    by_label = {c["label"]: c for c in all_candidates}
    cur_from, cur_to = current_window(30)

    final: Dict[str, Any] = {
        "bundle": str(bundle),
        "class_name": CLASS_NAME,
        "cell_id": "CELL-015",
        "display_name": "Scalping Open Pressure Stop MNQ 1m c015",
        "instrument": INSTRUMENT,
        "session_template": SESSION_TEMPLATE,
    }

    if args.stage in ("smoke", "all"):
        rows = [
            submit_job(
                bundle=bundle,
                label=c["label"],
                stage="smoke",
                period_label="Current30D",
                from_utc=cur_from,
                to_utc=cur_to,
                params=c["params"],
            )
            for c in selected
        ]
        (bundle / "smoke_submitted.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        final["smoke_rows"] = collect_rows(bundle, rows, "smoke_rows.json")
        final["selected_after_smoke"] = pick_smoke(final["smoke_rows"], args.limit)
    else:
        final["selected_after_smoke"] = args.label or []

    validation_labels = args.label or final.get("selected_after_smoke") or []
    if args.stage in ("validation", "all") and validation_labels:
        rows = []
        for label in validation_labels:
            c = by_label[label]
            for period_label, fr, to in (FULL, IS, OOS):
                rows.append(submit_job(
                    bundle=bundle,
                    label=label,
                    stage="validation",
                    period_label=period_label,
                    from_utc=fr,
                    to_utc=to,
                    params=c["params"],
                ))
        (bundle / "validation_submitted.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        final["validation_rows"] = collect_rows(bundle, rows, "validation_rows.json")
    else:
        final["validation_rows"] = []

    stress_labels = [label for label in validation_labels if core_pass(final.get("validation_rows") or [], label)]
    if args.stage == "stress" and args.label:
        stress_labels = args.label
    if args.stage in ("stress", "all") and stress_labels:
        rows = []
        for label in stress_labels:
            c = by_label[label]
            for period_label, fee, slip in (
                ("StressSlip2", RL.fee_for(ROOT), 2),
                ("StressFee240", 2.40, 1),
                ("StressSlip2Fee240", 2.40, 2),
            ):
                rows.append(submit_job(
                    bundle=bundle,
                    label=label,
                    stage="stress",
                    period_label=period_label,
                    from_utc=FULL[1],
                    to_utc=FULL[2],
                    params=c["params"],
                    fee=fee,
                    slip=slip,
                ))
            rows.append(submit_job(
                bundle=bundle,
                label=label,
                stage="current",
                period_label="Current30D",
                from_utc=cur_from,
                to_utc=cur_to,
                params=c["params"],
            ))
        (bundle / "stress_submitted.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        collected = collect_rows(bundle, rows, "stress_current_rows.json")
        final["stress_rows"] = [r for r in collected if r.get("stage") == "stress"]
        final["current_rows"] = [r for r in collected if r.get("stage") == "current"]
    else:
        final["stress_rows"] = []
        final["current_rows"] = []

    decisions = []
    for label in validation_labels:
        core = core_pass(final.get("validation_rows") or [], label)
        stress_rows = [r for r in final.get("stress_rows") or [] if r.get("label") == label]
        current_rows = [r for r in final.get("current_rows") or [] if r.get("label") == label]
        stress_pass = bool(stress_rows) and all(float(r.get("adj_net") or 0.0) > 0.0 for r in stress_rows)
        current_pass = bool(current_rows) and all(int(r.get("trade_count") or 0) >= 5 and float(r.get("adj_net") or 0.0) >= 0.0 for r in current_rows)
        decision = "paper_ready" if core and stress_pass and current_pass else (
            "paper_candidate_stress_pending" if core and not stress_rows else "research_only"
        )
        decisions.append({
            "label": label,
            "core_pass": core,
            "stress_pass": stress_pass,
            "current_pass": current_pass,
            "decision": decision,
            "locked_parameters": by_label[label]["params"] if label in by_label else {},
        })
    final["gate_decisions"] = decisions

    (bundle / "summary.json").write_text(json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(bundle, final)
    print(f"summary -> {bundle / 'summary.json'}", flush=True)
    print(f"markdown -> {bundle / 'summary.md'}", flush=True)
    winners = [d for d in decisions if d.get("decision") == "paper_ready"]
    if winners:
        print("PAPER_READY WINNERS:", ", ".join(d["label"] for d in winners), flush=True)
    else:
        print("no paper_ready winner in this run", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
