"""Research runner for the MNQ CELL-016 high-frequency scalp candidate.

The runner uses the already-compiled NTAMicroMnqScalpPilot engine and searches
for a slot-safe c016 profile with materially higher trade frequency than the
existing ORB-retest wrappers. It writes evidence under
data/research/mnq_cell016_highfreq_<timestamp>/.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import mnq_scalp_pilot_lib as MS  # noqa: E402


CLASS_NAME = "NTAMicroMnqScalpPilot"
CURRENT_CONTRACT = "MNQ 06-26"
ROOT = "MNQ"

PERIODS: List[Tuple[str, str, str]] = [
    ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
    ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
]
SMOKE = ("Smoke2026", "2026-03-12T00:00:00Z", "2026-05-11T23:59:59Z")


def base_params() -> Dict[str, Any]:
    p = MS.scalp_params(ROOT, "ALL")
    p.update({
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "RiskPerTradePct": 0.35,
        "MaxDailyLossPct": 3.0,
        "MaxDailyLossUsd": 60.0,
        "MaxWeeklyLossUsd": 150.0,
        "MaxDailyProfitPct": 0.0,
        "MaxTradesPerDay": 20,
        "HardMaxTradesPerDay": 25,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "RoundTurnCommission": 1.90,
        "SlippageTicks": 1,
        "TradeStartTime": 635,
        "TradeEndTime": 1245,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1300,
        "NewsBlackoutTimes": "",
        "NewsBlackoutWindowMin": 5,
        "AtrStopMult": 0.30,
        "MinStopTicks": 6,
        "MaxStopTicks": 12,
        "MoveToBreakevenAtR": 0.7,
        "TrailAfterR": 1.0,
        "UseTimeStop": True,
        "TimeStopBars": 3,
        "MinProgressR": 0.30,
        "EntryOffsetTicks": 0,
        "EntryTimeoutBars": 2,
        "OrbStartTime": 630,
        "OrbDurationMinutes": 3,
        "OrbBreakoutBuffer": 1,
        "OrbRetestBars": 5,
        "OrbFailedLookback": 3,
        "EmaFastPeriod": 9,
        "EmaMidPeriod": 21,
        "EmaSlowPeriod": 50,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "MinAdx": 0.0,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.8,
        "PullbackLookback": 3,
        "RequireSlowTrend": False,
        "EmaImpulseLookback": 3,
    })
    return p


def make_params(
    *,
    long: bool,
    short: bool,
    vwap: bool,
    ema: bool,
    orb: bool,
    fail: bool,
    rr: float,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    p = base_params()
    p.update({
        "UseSetupModeFilter": False,
        "EnableLong": long,
        "EnableShort": short,
        "EnableVwapReclaim": vwap,
        "EnableEmaMomentum": ema,
        "EnableMicroOrb": orb,
        "EnableFailedBreakout": fail,
        "RewardRiskRatio": rr,
    })
    if overrides:
        p.update(overrides)
    return p


def candidates() -> List[Dict[str, Any]]:
    def open_window(end_hhmm: int, params: Dict[str, Any]) -> Dict[str, Any]:
        p = dict(params)
        p.update({
            "TradeStartTime": 635,
            "TradeEndTime": end_hhmm,
            "UseSecondTradeWindow": False,
            "ForceFlatTime": 1300,
        })
        return p

    all_short_125 = make_params(long=False, short=True, vwap=True, ema=True, orb=True, fail=True, rr=1.25)
    all_short_150 = make_params(long=False, short=True, vwap=True, ema=True, orb=True, fail=True, rr=1.50)
    ema_fail_short_125 = make_params(long=False, short=True, vwap=False, ema=True, orb=False, fail=True, rr=1.25)
    orb_fail_ls_125 = make_params(long=True, short=True, vwap=False, ema=False, orb=True, fail=True, rr=1.25)
    all_short_150_risk050 = dict(all_short_150)
    all_short_150_risk050["RiskPerTradePct"] = 0.50
    all_short_150_risk050_d40w100 = dict(all_short_150_risk050)
    all_short_150_risk050_d40w100.update({"MaxDailyLossUsd": 40.0, "MaxWeeklyLossUsd": 100.0})
    all_short_150_risk050_d45w120 = dict(all_short_150_risk050)
    all_short_150_risk050_d45w120.update({"MaxDailyLossUsd": 45.0, "MaxWeeklyLossUsd": 120.0})
    all_short_150_risk050_cons2 = dict(all_short_150_risk050)
    all_short_150_risk050_cons2.update({"MaxConsecutiveLosses": 2, "PauseAfterConsecutiveLosses": 1, "PauseMinutesAfterLosses": 20})
    all_short_150_stop4_10 = dict(all_short_150)
    all_short_150_stop4_10.update({"MinStopTicks": 4, "MaxStopTicks": 10})
    all_short_175_stop4_10 = make_params(long=False, short=True, vwap=True, ema=True, orb=True, fail=True, rr=1.75)
    all_short_175_stop4_10.update({"MinStopTicks": 4, "MaxStopTicks": 10})
    all_short_200_stop4_10 = make_params(long=False, short=True, vwap=True, ema=True, orb=True, fail=True, rr=2.00)
    all_short_200_stop4_10.update({"MinStopTicks": 4, "MaxStopTicks": 10})
    all_short_250_stop4_10 = make_params(long=False, short=True, vwap=True, ema=True, orb=True, fail=True, rr=2.50)
    all_short_250_stop4_10.update({"MinStopTicks": 4, "MaxStopTicks": 10})
    all_short_300_stop4_10 = make_params(long=False, short=True, vwap=True, ema=True, orb=True, fail=True, rr=3.00)
    all_short_300_stop4_10.update({"MinStopTicks": 4, "MaxStopTicks": 10})
    all_short_300_stop4_10_d50w120 = dict(all_short_300_stop4_10)
    all_short_300_stop4_10_d50w120.update({"MaxDailyLossUsd": 50.0, "MaxWeeklyLossUsd": 120.0})
    all_short_300_stop4_10_d45w120 = dict(all_short_300_stop4_10)
    all_short_300_stop4_10_d45w120.update({"MaxDailyLossUsd": 45.0, "MaxWeeklyLossUsd": 120.0})
    all_short_300_stop4_10_d40w100 = dict(all_short_300_stop4_10)
    all_short_300_stop4_10_d40w100.update({"MaxDailyLossUsd": 40.0, "MaxWeeklyLossUsd": 100.0})
    all_short_300_stop4_10_cons2 = dict(all_short_300_stop4_10)
    all_short_300_stop4_10_cons2.update({"MaxConsecutiveLosses": 2, "PauseAfterConsecutiveLosses": 1, "PauseMinutesAfterLosses": 20})
    all_short_350_stop4_10 = make_params(long=False, short=True, vwap=True, ema=True, orb=True, fail=True, rr=3.50)
    all_short_350_stop4_10.update({"MinStopTicks": 4, "MaxStopTicks": 10})
    all_short_400_stop4_10 = make_params(long=False, short=True, vwap=True, ema=True, orb=True, fail=True, rr=4.00)
    all_short_400_stop4_10.update({"MinStopTicks": 4, "MaxStopTicks": 10})

    defs: List[Tuple[str, str, Dict[str, Any]]] = [
        ("all_short_rr125", "All modules short-only, tight 6-12 tick box.", all_short_125),
        ("all_short_rr150", "All modules short-only with RR=1.50.", all_short_150),
        ("all_longshort_rr100", "All modules both directions, faster target.", make_params(long=True, short=True, vwap=True, ema=True, orb=True, fail=True, rr=1.00)),
        ("orb_fail_short_rr150", "ORB plus failed-breakout, short-only.", make_params(long=False, short=True, vwap=False, ema=False, orb=True, fail=True, rr=1.50)),
        ("orb_fail_short_rr175", "ORB plus failed-breakout, short-only RR=1.75.", make_params(long=False, short=True, vwap=False, ema=False, orb=True, fail=True, rr=1.75)),
        ("orb_fail_longshort_rr125", "ORB plus failed-breakout both directions.", orb_fail_ls_125),
        ("fail_short_rr075", "Failed-breakout short-only, fast target.", make_params(long=False, short=True, vwap=False, ema=False, orb=False, fail=True, rr=0.75)),
        ("fail_short_rr100", "Failed-breakout short-only.", make_params(long=False, short=True, vwap=False, ema=False, orb=False, fail=True, rr=1.00)),
        ("fail_short_rr125", "Failed-breakout short-only RR=1.25.", make_params(long=False, short=True, vwap=False, ema=False, orb=False, fail=True, rr=1.25)),
        ("fail_short_vol12_rr100", "Failed-breakout short-only with volume filter.", make_params(long=False, short=True, vwap=False, ema=False, orb=False, fail=True, rr=1.00, overrides={"MinVolumeFactor": 1.2})),
        ("fail_long_rr100", "Failed-breakout long-only.", make_params(long=True, short=False, vwap=False, ema=False, orb=False, fail=True, rr=1.00)),
        ("ema_short_rr125", "EMA impulse short-only.", make_params(long=False, short=True, vwap=False, ema=True, orb=False, fail=False, rr=1.25)),
        ("ema_short_trend_rr150", "EMA impulse short-only with slow-trend alignment.", make_params(long=False, short=True, vwap=False, ema=True, orb=False, fail=False, rr=1.50, overrides={"RequireSlowTrend": True})),
        ("vwap_short_rr125", "VWAP reclaim short-only.", make_params(long=False, short=True, vwap=True, ema=False, orb=False, fail=False, rr=1.25)),
        ("vwap_short_vol12_rr150", "VWAP reclaim short-only with volume filter.", make_params(long=False, short=True, vwap=True, ema=False, orb=False, fail=False, rr=1.50, overrides={"MinVolumeFactor": 1.2})),
        ("vwap_fail_short_rr125", "VWAP reclaim plus failed-breakout short-only.", make_params(long=False, short=True, vwap=True, ema=False, orb=False, fail=True, rr=1.25)),
        ("ema_fail_short_rr125", "EMA impulse plus failed-breakout short-only.", ema_fail_short_125),
        ("micro_orb_short_rr150", "MICRO_ORB short-only control.", make_params(long=False, short=True, vwap=False, ema=False, orb=True, fail=False, rr=1.50)),
        ("open_all_short_rr150_0700", "All modules short-only RR=1.50, entries only 06:35-07:00 PT.", open_window(700, all_short_150)),
        ("open_all_short_rr150_0730", "All modules short-only RR=1.50, entries only 06:35-07:30 PT.", open_window(730, all_short_150)),
        ("open_all_short_rr150_0800", "All modules short-only RR=1.50, entries only 06:35-08:00 PT.", open_window(800, all_short_150)),
        ("open_all_short_rr150_0830", "All modules short-only RR=1.50, entries only 06:35-08:30 PT.", open_window(830, all_short_150)),
        ("open_all_short_rr150_0730_risk050", "All modules short-only RR=1.50, 06:35-07:30 PT, RiskPerTradePct=0.50 with UserMaxContracts=1.", open_window(730, all_short_150_risk050)),
        ("open_all_short_rr150_0800_risk050", "All modules short-only RR=1.50, 06:35-08:00 PT, RiskPerTradePct=0.50 with UserMaxContracts=1.", open_window(800, all_short_150_risk050)),
        ("open_all_short_rr150_0730_r050_d40w100", "All modules short-only RR=1.50, 06:35-07:30 PT, RiskPerTradePct=0.50, daily/weekly loss 40/100.", open_window(730, all_short_150_risk050_d40w100)),
        ("open_all_short_rr150_0800_r050_d40w100", "All modules short-only RR=1.50, 06:35-08:00 PT, RiskPerTradePct=0.50, daily/weekly loss 40/100.", open_window(800, all_short_150_risk050_d40w100)),
        ("open_all_short_rr150_0730_r050_d45w120", "All modules short-only RR=1.50, 06:35-07:30 PT, RiskPerTradePct=0.50, daily/weekly loss 45/120.", open_window(730, all_short_150_risk050_d45w120)),
        ("open_all_short_rr150_0800_r050_d45w120", "All modules short-only RR=1.50, 06:35-08:00 PT, RiskPerTradePct=0.50, daily/weekly loss 45/120.", open_window(800, all_short_150_risk050_d45w120)),
        ("open_all_short_rr150_0730_r050_cons2", "All modules short-only RR=1.50, 06:35-07:30 PT, RiskPerTradePct=0.50, max consecutive losses=2.", open_window(730, all_short_150_risk050_cons2)),
        ("open_all_short_rr150_0800_r050_cons2", "All modules short-only RR=1.50, 06:35-08:00 PT, RiskPerTradePct=0.50, max consecutive losses=2.", open_window(800, all_short_150_risk050_cons2)),
        ("open_all_short_rr150_0730_stop4_10", "All modules short-only RR=1.50, 06:35-07:30 PT, 4-10 tick stop box.", open_window(730, all_short_150_stop4_10)),
        ("open_all_short_rr150_0800_stop4_10", "All modules short-only RR=1.50, 06:35-08:00 PT, 4-10 tick stop box.", open_window(800, all_short_150_stop4_10)),
        ("open_all_short_rr175_0730_stop4_10", "All modules short-only RR=1.75, 06:35-07:30 PT, 4-10 tick stop box.", open_window(730, all_short_175_stop4_10)),
        ("open_all_short_rr175_0800_stop4_10", "All modules short-only RR=1.75, 06:35-08:00 PT, 4-10 tick stop box.", open_window(800, all_short_175_stop4_10)),
        ("open_all_short_rr200_0730_stop4_10", "All modules short-only RR=2.00, 06:35-07:30 PT, 4-10 tick stop box.", open_window(730, all_short_200_stop4_10)),
        ("open_all_short_rr200_0800_stop4_10", "All modules short-only RR=2.00, 06:35-08:00 PT, 4-10 tick stop box.", open_window(800, all_short_200_stop4_10)),
        ("open_all_short_rr250_0730_stop4_10", "All modules short-only RR=2.50, 06:35-07:30 PT, 4-10 tick stop box.", open_window(730, all_short_250_stop4_10)),
        ("open_all_short_rr300_0730_stop4_10", "All modules short-only RR=3.00, 06:35-07:30 PT, 4-10 tick stop box.", open_window(730, all_short_300_stop4_10)),
        ("open_all_short_rr300_0730_stop4_10_d50w120", "All modules short-only RR=3.00, 06:35-07:30 PT, 4-10 tick stop box, daily/weekly loss 50/120.", open_window(730, all_short_300_stop4_10_d50w120)),
        ("open_all_short_rr300_0730_stop4_10_d45w120", "All modules short-only RR=3.00, 06:35-07:30 PT, 4-10 tick stop box, daily/weekly loss 45/120.", open_window(730, all_short_300_stop4_10_d45w120)),
        ("open_all_short_rr300_0730_stop4_10_d40w100", "All modules short-only RR=3.00, 06:35-07:30 PT, 4-10 tick stop box, daily/weekly loss 40/100.", open_window(730, all_short_300_stop4_10_d40w100)),
        ("open_all_short_rr300_0730_stop4_10_cons2", "All modules short-only RR=3.00, 06:35-07:30 PT, 4-10 tick stop box, max consecutive losses=2.", open_window(730, all_short_300_stop4_10_cons2)),
        ("open_all_short_rr350_0730_stop4_10", "All modules short-only RR=3.50, 06:35-07:30 PT, 4-10 tick stop box.", open_window(730, all_short_350_stop4_10)),
        ("open_all_short_rr400_0730_stop4_10", "All modules short-only RR=4.00, 06:35-07:30 PT, 4-10 tick stop box.", open_window(730, all_short_400_stop4_10)),
        ("open_all_short_rr125_0730", "All modules short-only RR=1.25, entries only 06:35-07:30 PT.", open_window(730, all_short_125)),
        ("open_all_short_rr125_0830", "All modules short-only RR=1.25, entries only 06:35-08:30 PT.", open_window(830, all_short_125)),
        ("open_ema_fail_short_rr125_0830", "EMA impulse plus failed-breakout short-only, entries only 06:35-08:30 PT.", open_window(830, ema_fail_short_125)),
        ("open_orb_fail_longshort_rr125_0830", "ORB plus failed-breakout both directions, entries only 06:35-08:30 PT.", open_window(830, orb_fail_ls_125)),
    ]
    return [{"label": label, "hypothesis": hyp, "params": params} for label, hyp, params in defs]


def wait_job(job_id: str, timeout_s: int = 1200) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        report = RL.read_job_report(job_id)
        if report and "result" in report:
            return report
        if report and ("error" in report or "failed" in str(report.get("_dir", ""))):
            return report
        time.sleep(2)
    return {"job_id": job_id, "timeout": True}


def trades_from(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return trades
    d = Path(str(report.get("_dir") or ""))
    p = d / "trades.json"
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return raw
            if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
                return raw["trades"]
        except Exception:
            return []
    return []


def adjusted_pnls(trades: Iterable[Dict[str, Any]], fee: float) -> List[float]:
    out: List[float] = []
    for trade in trades:
        qty = int(trade.get("quantity") or 1)
        out.append(float(trade.get("pnl_currency") or 0.0) - fee * max(1, qty))
    return out


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


def summarize(row: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    trades = trades_from(report)
    fee = float(row.get("fee") or 0.0)
    pnls = adjusted_pnls(trades, fee)
    gross_profit = sum(p for p in pnls if p >= 0.0)
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

    days = MS.trading_weekdays(str(row.get("from_utc")), str(row.get("to_utc")))
    active_days = {
        str(t.get("entry_time_utc") or "")[:10]
        for t in trades if t.get("entry_time_utc")
    }
    out = dict(row)
    out.update({
        "status_dir": report.get("_dir", ""),
        "trade_count": len(trades),
        "trades_per_day": round(len(trades) / days, 2),
        "active_days_pct": round(len(active_days) / days * 100.0, 2),
        "adj_net": round(adj_net, 2),
        "adj_pf": adj_pf,
        "win_rate": round((sum(1 for p in pnls if p > 0) / len(pnls) * 100.0) if pnls else 0.0, 2),
        "avg_trade_after_commission": round(adj_net / len(pnls), 2) if pnls else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_consecutive_losses": max_consecutive_losses(pnls),
        "timeout": bool(report.get("timeout")),
        "error": report.get("error") or report.get("result_error"),
    })
    return out


def submit_row(
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
        instrument=CURRENT_CONTRACT,
        params=p,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=slip,
        role="smoke" if stage == "smoke" else "research",
        session_template=RL.session_for(ROOT),
        risk_profile=RL.build_risk_profile_for([CURRENT_CONTRACT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if code == 201 else None
    row = {
        "stage": stage,
        "label": label,
        "period_label": period_label,
        "instrument": CURRENT_CONTRACT,
        "root": ROOT,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "timeframe": "1 Minute",
        "fee": fee,
        "slip": slip,
        "code": code,
        "job_id": job_id,
        "response": resp,
    }
    print(f"submit {stage:10s} {label:32s} {period_label:14s} code={code} job={job_id or resp}", flush=True)
    (bundle / "latest_submitted.json").write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    return row


def run_rows(bundle: Path, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        job_id = row.get("job_id")
        if not job_id:
            out.append(row)
            continue
        report = wait_job(str(job_id))
        summary = summarize(row, report)
        out.append(summary)
        pf = summary.get("adj_pf")
        pf_s = "inf" if pf == math.inf else f"{float(pf or 0.0):.3f}"
        print(
            f"done   {row['stage']:10s} {row['label']:32s} {row['period_label']:14s} "
            f"trades={summary['trade_count']:>4} tpd={summary['trades_per_day']:>5} "
            f"net={summary['adj_net']:>8.2f} pf={pf_s:>7s} dd={summary['max_drawdown']:>8.2f}",
            flush=True,
        )
        (bundle / "latest_summary_rows.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def aggregate(rows: Iterable[Dict[str, Any]], keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(row.get(k) for k in keys), []).append(row)
    for key_values, group in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        rec = {k: v for k, v in zip(keys, key_values)}
        # Stages submit one job per group, but keep aggregation explicit.
        base = group[0]
        rec.update({
            "trade_count": sum(int(r.get("trade_count") or 0) for r in group),
            "trades_per_day": base.get("trades_per_day"),
            "active_days_pct": base.get("active_days_pct"),
            "adj_net": round(sum(float(r.get("adj_net") or 0.0) for r in group), 2),
            "adj_pf": base.get("adj_pf"),
            "win_rate": base.get("win_rate"),
            "avg_trade_after_commission": base.get("avg_trade_after_commission"),
            "max_drawdown": min(float(r.get("max_drawdown") or 0.0) for r in group),
            "max_consecutive_losses": max(int(r.get("max_consecutive_losses") or 0) for r in group),
            "job_ids": [r.get("job_id") for r in group if r.get("job_id")],
        })
        out.append(rec)
    return out


def pick_smoke_labels(rows: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    ranked = []
    for row in rows:
        if int(row.get("trade_count") or 0) <= 0:
            continue
        net = float(row.get("adj_net") or 0.0)
        pf = float(row.get("adj_pf") or 0.0)
        dd = abs(float(row.get("max_drawdown") or 0.0))
        tpd = float(row.get("trades_per_day") or 0.0)
        avg = float(row.get("avg_trade_after_commission") or 0.0)
        score = net + (pf - 1.0) * 50.0 + min(tpd, 5.0) * 12.0 + avg * 20.0 - max(0.0, dd - 80.0) * 0.5
        if net > 0.0 and pf >= 1.10:
            ranked.append((score, str(row["label"]), row))
    ranked.sort(reverse=True, key=lambda x: x[0])
    return [label for _, label, _ in ranked[:limit]]


def pass_core(rows: List[Dict[str, Any]], label: str) -> bool:
    by_period = {r["period_label"]: r for r in rows if r.get("label") == label}
    full = by_period.get("Full")
    is_ = by_period.get("IS")
    oos = by_period.get("OOS")
    if not full or not is_ or not oos:
        return False
    return (
        float(full.get("adj_net") or 0.0) > 0.0
        and float(full.get("adj_pf") or 0.0) >= 1.25
        and int(full.get("trade_count") or 0) >= 100
        and float(full.get("max_drawdown") or 0.0) >= -300.0
        and float(is_.get("adj_net") or 0.0) > 0.0
        and float(oos.get("adj_net") or 0.0) > 0.0
        and float(oos.get("adj_pf") or 0.0) >= 1.15
    )


def write_markdown(bundle: Path, final: Dict[str, Any]) -> None:
    def fmt_pf(v: Any) -> str:
        try:
            x = float(v)
        except Exception:
            return ""
        return "inf" if math.isinf(x) else f"{x:.3f}"

    lines = [
        "# MNQ CELL-016 High-Frequency Research",
        "",
        f"Bundle: `{bundle}`",
        "",
        "## Candidates",
        "",
        "| Label | Hypothesis |",
        "|---|---|",
    ]
    for c in candidates():
        lines.append(f"| `{c['label']}` | {c['hypothesis']} |")

    for section, rows in [
        ("Smoke", final.get("smoke_agg") or []),
        ("Validation", final.get("validation_agg") or []),
        ("Stress", final.get("stress_agg") or []),
    ]:
        if not rows:
            continue
        lines += ["", f"## {section}", "", "| Label | Period | Trades | TPD | Active days % | Adj net | Adj PF | Avg | Max DD | Loss streak |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            lines.append(
                f"| `{r.get('label','')}` | {r.get('period_label','')} | {r.get('trade_count',0)} | "
                f"{r.get('trades_per_day',0)} | {r.get('active_days_pct',0)} | "
                f"{float(r.get('adj_net') or 0.0):.2f} | {fmt_pf(r.get('adj_pf'))} | "
                f"{float(r.get('avg_trade_after_commission') or 0.0):.2f} | "
                f"{float(r.get('max_drawdown') or 0.0):.2f} | {r.get('max_consecutive_losses',0)} |"
            )

    if final.get("gate_decisions"):
        lines += ["", "## Gate Decisions", "", "| Label | Core gates | Stress positive | Decision |", "|---|---:|---:|---|"]
        for d in final["gate_decisions"]:
            lines.append(f"| `{d['label']}` | {d['core_gates']} | {d['stress_positive']} | {d['decision']} |")

    (bundle / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["smoke", "validation", "stress", "all"], default="all")
    ap.add_argument("--label", action="append", help="Candidate label. Can be repeated.")
    args = ap.parse_args(argv[1:])

    bundle = RL.DATA / "research" / f"mnq_cell016_highfreq_{RL.utcnow_compact()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    final: Dict[str, Any] = {
        "bundle": str(bundle),
        "class_name": CLASS_NAME,
        "current_contract": CURRENT_CONTRACT,
        "cell_id": "CELL-016",
        "display_name": "Scalping Failed Break MNQ 1m v1 c016",
    }

    selected = [c for c in candidates() if not args.label or c["label"] in args.label]

    if args.stage in ("smoke", "all"):
        label, fr, to = SMOKE
        smoke_rows = [
            submit_row(
                bundle=bundle,
                label=c["label"],
                stage="smoke",
                period_label=label,
                from_utc=fr,
                to_utc=to,
                params=c["params"],
            )
            for c in selected
        ]
        final["smoke_rows"] = run_rows(bundle, smoke_rows)
        final["smoke_agg"] = aggregate(final["smoke_rows"], ("label", "period_label"))
        final["selected_after_smoke"] = pick_smoke_labels(final["smoke_agg"])
    else:
        final["selected_after_smoke"] = args.label or []

    validation_labels = args.label or final.get("selected_after_smoke") or []
    if args.stage in ("validation", "all") and validation_labels:
        by_label = {c["label"]: c for c in candidates()}
        rows: List[Dict[str, Any]] = []
        for label in validation_labels:
            c = by_label[label]
            for period_label, fr, to in PERIODS:
                rows.append(submit_row(
                    bundle=bundle,
                    label=label,
                    stage="validation",
                    period_label=period_label,
                    from_utc=fr,
                    to_utc=to,
                    params=c["params"],
                ))
        final["validation_rows"] = run_rows(bundle, rows)
        final["validation_agg"] = aggregate(final["validation_rows"], ("label", "period_label"))
    else:
        final["validation_agg"] = []

    if args.stage == "stress" and args.label:
        stress_labels = args.label
    else:
        stress_labels = [
            label for label in validation_labels
            if pass_core(final.get("validation_agg") or [], label)
        ]
    if args.stage in ("stress", "all") and stress_labels:
        by_label = {c["label"]: c for c in candidates()}
        rows = []
        for label in stress_labels:
            c = by_label[label]
            for period_label, fee, slip in [
                ("StressSlip2", 1.90, 2),
                ("StressFee240", 2.40, 1),
                ("StressSlip2Fee240", 2.40, 2),
            ]:
                rows.append(submit_row(
                    bundle=bundle,
                    label=label,
                    stage="stress",
                    period_label=period_label,
                    from_utc=PERIODS[0][1],
                    to_utc=PERIODS[0][2],
                    params=c["params"],
                    fee=fee,
                    slip=slip,
                ))
        final["stress_rows"] = run_rows(bundle, rows)
        final["stress_agg"] = aggregate(final["stress_rows"], ("label", "period_label"))
    else:
        final["stress_agg"] = []

    gate_decisions = []
    for label in validation_labels:
        core = pass_core(final.get("validation_agg") or [], label)
        stress_rows = [r for r in final.get("stress_agg") or [] if r.get("label") == label]
        stress_positive = bool(stress_rows) and all(float(r.get("adj_net") or 0.0) > 0.0 for r in stress_rows)
        decision = "paper_candidate; eligible for wrapper/profile promotion" if core and stress_positive else (
            "research_candidate; core gates passed, stress failed or pending" if core else
            "rejected_or_research_only; core gates failed"
        )
        gate_decisions.append({
            "label": label,
            "core_gates": core,
            "stress_positive": stress_positive,
            "decision": decision,
        })
    final["gate_decisions"] = gate_decisions

    (bundle / "summary.json").write_text(json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(bundle, final)
    print(f"summary -> {bundle / 'summary.json'}", flush=True)
    print(f"markdown -> {bundle / 'summary.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
