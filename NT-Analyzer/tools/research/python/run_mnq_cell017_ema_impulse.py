"""Research runner for MNQ CELL-017 pure EMA impulse momentum.

The candidate is intentionally not a C015/C016 retune:
  * no liquidity/open-pressure score;
  * no ORB continuation/retest module;
  * only NTAMicroMnqScalpPilot.EmaImpulseScalp is enabled.

Outputs a reproducible bundle under data/research/mnq_cell017_ema_impulse_<ts>/.
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import mnq_scalp_pilot_lib as MS  # noqa: E402


CLASS_NAME = "NTAMicroMnqScalpPilot"
ROOT = "MNQ"
CURRENT_CONTRACT = "MNQ 06-26"
SESSION_TEMPLATE = RL.session_for(ROOT)
ROLE = "research"
USAGE = """\
Usage:
  python tools/research/python/run_mnq_cell017_ema_impulse.py [--top N]
  python tools/research/python/run_mnq_cell017_ema_impulse.py --only variant_a,variant_b

Runs MNQ CELL-017 pure EMA impulse research through NT-Analyzer/NinjaTrader jobs.
The process creates a bundle under data/research/mnq_cell017_ema_impulse_<utc>.
"""

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

CSV_FIELDS = [
    "stage",
    "variant",
    "job_ids",
    "contracts",
    "from_utc",
    "to_utc",
    "trade_count",
    "trades_per_day",
    "active_days_pct",
    "adj_net",
    "adj_pf",
    "adj_dd",
    "win_pct",
    "avg_trade",
    "max_consecutive_losses",
    "same_bar_pct",
    "slippage_ticks",
    "round_turn_commission",
    "trade_start",
    "trade_end",
    "direction",
    "rr",
    "min_stop",
    "max_stop",
    "require_slow_trend",
    "time_stop_bars",
    "min_volume_factor",
]


@dataclass(frozen=True)
class Variant:
    name: str
    params: Dict[str, Any]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def current_window(days: Optional[int] = None) -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    if days is None:
        start_day = date(2026, 1, 1)
    else:
        start_day = end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def job_state(job_id: str) -> Optional[str]:
    jobs = RL.jobs_root()
    for sub in ("done", "failed", "cancelled", "running", "pending"):
        if (jobs / sub / job_id).is_dir():
            return sub
    if (jobs / "failed" / ".quarantine" / job_id).is_dir():
        return "failed"
    return None


def wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 21600, interval_s: int = 4) -> Dict[str, str]:
    remaining = set(j for j in job_ids if j)
    states: Dict[str, str] = {}
    deadline = time.time() + timeout_s
    last_print = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            state = job_state(job_id)
            if state in {"done", "failed", "cancelled"}:
                states[job_id] = state
                remaining.remove(job_id)
        now = time.time()
        if remaining and now - last_print >= 30:
            print(f"waiting: {len(remaining)} CELL-017 EMA jobs still pending/running")
            last_print = now
        if remaining:
            time.sleep(interval_s)
    return states


def trade_qty(trade: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(trade.get("quantity") or 1.0)))
    except Exception:
        return 1.0


def adjusted_pnl(trade: Dict[str, Any], fee: float) -> float:
    return float(trade.get("pnl_currency") or 0.0) - fee * trade_qty(trade)


def trade_key(trade: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        trade.get("entry_time_utc"),
        trade.get("exit_time_utc"),
        trade.get("direction"),
        round(float(trade.get("entry_price") or 0.0), 4),
        round(float(trade.get("exit_price") or 0.0), 4),
        int(float(trade.get("quantity") or 1.0)),
        round(float(trade.get("pnl_currency") or 0.0), 4),
    )


def dedupe_trades(trades: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for trade in trades:
        key = trade_key(trade)
        if key in seen:
            continue
        seen.add(key)
        out.append(trade)
    out.sort(key=lambda t: str(t.get("entry_time_utc") or t.get("exit_time_utc") or ""))
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


def aggregate_metrics(trades: List[Dict[str, Any]], fee: float, from_utc: str, to_utc: str) -> Dict[str, Any]:
    pnls = [adjusted_pnl(t, fee) for t in trades]
    gross_profit = sum(p for p in pnls if p > 0.0)
    gross_loss = abs(sum(p for p in pnls if p < 0.0))
    adj_net = sum(pnls)
    adj_pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)

    equity = 0.0
    peak = 0.0
    adj_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        adj_dd = min(adj_dd, equity - peak)

    days = MS.trading_weekdays(from_utc, to_utc)
    active_days = {
        str(t.get("entry_time_utc") or t.get("exit_time_utc") or "")[:10]
        for t in trades
        if t.get("entry_time_utc") or t.get("exit_time_utc")
    }
    same_bar = sum(
        1 for t in trades
        if t.get("entry_time_utc") and t.get("entry_time_utc") == t.get("exit_time_utc")
    )
    count = len(trades)
    return {
        "trade_count": count,
        "trades_per_day": round(count / days, 4),
        "active_days_pct": round(len(active_days) / days * 100.0, 4),
        "adj_net": round(adj_net, 6),
        "adj_pf": round(adj_pf, 6) if math.isfinite(adj_pf) else 999.0,
        "adj_dd": round(adj_dd, 6),
        "win_pct": round((sum(1 for p in pnls if p > 0.0) / count * 100.0) if count else 0.0, 4),
        "avg_trade": round(adj_net / count, 6) if count else 0.0,
        "max_consecutive_losses": max_consecutive_losses(pnls),
        "same_bar_pct": round(same_bar / count * 100.0, 4) if count else 0.0,
    }


def trades_from_report(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return [t for t in trades if isinstance(t, dict)]
    directory = Path(str(report.get("_dir") or ""))
    p = directory / "trades.json"
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(raw, list):
            return [t for t in raw if isinstance(t, dict)]
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
            return [t for t in raw["trades"] if isinstance(t, dict)]
    return []


def base_params() -> Dict[str, Any]:
    params = MS.scalp_params(ROOT, "EMA_MOMENTUM")
    params.update({
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
        "MaxTradesPerDay": 10,
        "HardMaxTradesPerDay": 12,
        "MaxConsecutiveLosses": 4,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "RoundTurnCommission": RL.fee_for(ROOT),
        "SlippageTicks": 1,
        "UseSetupModeFilter": True,
        "SetupMode": "EmaImpulseScalp",
        "EnableVwapReclaim": False,
        "EnableEmaMomentum": True,
        "EnableMicroOrb": False,
        "EnableFailedBreakout": False,
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
        "AtrStopMult": 0.30,
        "MinStopTicks": 6,
        "MaxStopTicks": 12,
        "RewardRiskRatio": 1.50,
        "MoveToBreakevenAtR": 0.7,
        "TrailAfterR": 1.0,
        "UseTimeStop": True,
        "TimeStopBars": 3,
        "MinProgressR": 0.30,
        "EntryTimeoutBars": 2,
        "EntryOffsetTicks": 0,
        "TradeStartTime": 835,
        "TradeEndTime": 1000,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1245,
        "NewsBlackoutTimes": "",
        "NewsBlackoutWindowMin": 5,
        "OrbStartTime": 630,
        "OrbDurationMinutes": 3,
        "OrbBreakoutBuffer": 1,
        "OrbRetestBars": 5,
        "OrbFailedLookback": 3,
        "EmaImpulseLookback": 3,
    })
    return params


def make_variant(
    *,
    direction: str,
    window: Tuple[int, int],
    rr: float,
    stop_box: Tuple[int, int],
    require_slow_trend: bool,
    time_stop_bars: int,
    min_volume_factor: float,
    min_adx: float = 0.0,
) -> Variant:
    params = base_params()
    params.update({
        "EnableLong": direction in {"long", "both"},
        "EnableShort": direction in {"short", "both"},
        "TradeStartTime": window[0],
        "TradeEndTime": window[1],
        "ForceFlatTime": 1245,
        "RewardRiskRatio": rr,
        "MinStopTicks": stop_box[0],
        "MaxStopTicks": stop_box[1],
        "RequireSlowTrend": require_slow_trend,
        "TimeStopBars": time_stop_bars,
        "MinVolumeFactor": min_volume_factor,
        "MinAdx": min_adx,
    })
    name = (
        f"ema_{direction}_t{window[0]}_{window[1]}"
        f"_rr{str(rr).replace('.', '')}_s{stop_box[0]}_{stop_box[1]}"
        f"_trend{1 if require_slow_trend else 0}"
        f"_ts{time_stop_bars}_vol{str(min_volume_factor).replace('.', '')}"
    )
    return Variant(name=name, params=params)


def full_variants() -> List[Variant]:
    out: List[Variant] = []
    # Short side is prioritized because the existing MNQ research shows the
    # short EMA module has the stronger current-regime smoke, while this grid
    # avoids C015/C016 open-pressure/ORB logic.
    for window in ((735, 930), (835, 1000), (930, 1130), (1030, 1200)):
        for require_trend in (False, True):
            for rr in (1.5, 2.0, 2.5):
                for stop_box in ((4, 10), (6, 12)):
                    out.append(make_variant(
                        direction="short",
                        window=window,
                        rr=rr,
                        stop_box=stop_box,
                        require_slow_trend=require_trend,
                        time_stop_bars=3,
                        min_volume_factor=0.8,
                    ))

    # Smaller long-side scout, kept separate so a long-only edge can surface
    # without turning the search into another all-module high-frequency profile.
    for window in ((835, 1000), (930, 1130), (1030, 1200)):
        for require_trend in (False, True):
            for rr in (1.25, 1.5):
                out.append(make_variant(
                    direction="long",
                    window=window,
                    rr=rr,
                    stop_box=(6, 12),
                    require_slow_trend=require_trend,
                    time_stop_bars=3,
                    min_volume_factor=0.8,
                ))
    return out


def submit_job(
    *,
    variant: Variant,
    stage: str,
    instrument: str,
    from_utc: str,
    to_utc: str,
    slippage_ticks: int = 1,
    fee: float = 1.90,
) -> Dict[str, Any]:
    params = dict(variant.params)
    params["SlippageTicks"] = slippage_ticks
    params["RoundTurnCommission"] = fee
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=instrument,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=slippage_ticks,
        role=ROLE,
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([instrument]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "") if code == 201 and isinstance(resp, dict) else ""
    print(f"submit {stage:16s} {variant.name:62s} {instrument:9s} code={code} job={job_id or resp}")
    return {
        "stage": stage,
        "variant": variant.name,
        "instrument": instrument,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "slippage_ticks": slippage_ticks,
        "round_turn_commission": fee,
        "params": params,
        "code": code,
        "response": resp,
        "job_id": job_id,
    }


def summarize_stage(variant: Variant, stage: str, submissions: List[Dict[str, Any]]) -> Dict[str, Any]:
    trades: List[Dict[str, Any]] = []
    job_ids: List[str] = []
    contracts: List[str] = []
    from_utc = submissions[0]["from_utc"] if submissions else ""
    to_utc = submissions[0]["to_utc"] if submissions else ""
    fee = float(submissions[0].get("round_turn_commission") or 1.90) if submissions else 1.90
    slip = int(submissions[0].get("slippage_ticks") or 1) if submissions else 1

    for sub in submissions:
        job_id = str(sub.get("job_id") or "")
        if job_id:
            job_ids.append(job_id)
        if sub.get("instrument"):
            contracts.append(str(sub["instrument"]))
        report = RL.read_job_report(job_id) if job_id else None
        if report and "result" in report:
            trades.extend(trades_from_report(report))

    clean_trades = dedupe_trades(trades)
    metrics = aggregate_metrics(clean_trades, fee, from_utc, to_utc)
    params = variant.params
    return {
        "stage": stage,
        "variant": variant.name,
        "job_ids": ",".join(job_ids),
        "contracts": ",".join(sorted(set(contracts))),
        "from_utc": from_utc,
        "to_utc": to_utc,
        "slippage_ticks": slip,
        "round_turn_commission": fee,
        "trade_start": params.get("TradeStartTime"),
        "trade_end": params.get("TradeEndTime"),
        "direction": "both" if params.get("EnableLong") and params.get("EnableShort") else ("long" if params.get("EnableLong") else "short"),
        "rr": params.get("RewardRiskRatio"),
        "min_stop": params.get("MinStopTicks"),
        "max_stop": params.get("MaxStopTicks"),
        "require_slow_trend": params.get("RequireSlowTrend"),
        "time_stop_bars": params.get("TimeStopBars"),
        "min_volume_factor": params.get("MinVolumeFactor"),
        **metrics,
    }


def score_smoke(row: Dict[str, Any]) -> float:
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    trades = float(row.get("trade_count") or 0.0)
    avg = float(row.get("avg_trade") or 0.0)
    if net <= 0.0 or pf < 1.15 or trades < 20:
        return -999999.0 + net - dd
    # Prefer later windows when score is otherwise close to avoid C015/C016 overlap.
    late_bonus = max(0.0, float(row.get("trade_start") or 0) - 735.0) / 20.0
    return net * min(pf, 3.0) + avg * 50.0 - dd * 0.25 + late_bonus


def gate_decision(rows_by_stage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    full = rows_by_stage.get("Full") or {}
    is_row = rows_by_stage.get("IS") or {}
    oos = rows_by_stage.get("OOS") or {}
    slip2 = rows_by_stage.get("StressSlip2") or {}
    fee240 = rows_by_stage.get("StressFee240") or {}
    combined = rows_by_stage.get("StressSlip2Fee240") or {}
    ytd = rows_by_stage.get("YTD2026") or {}
    current30 = rows_by_stage.get("Current30D") or {}
    gates = {
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "max_dd_pct_15": RL.max_drawdown_within_budget(float(full.get("adj_dd") or 0.0)),
        "full_trades_ge_50": int(full.get("trade_count") or 0) >= 50,
        "is_net_positive": float(is_row.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip2.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee240.get("adj_net") or 0.0) > 0.0,
        "stress_combined_nonnegative": float(combined.get("adj_net") or -999999.0) >= 0.0,
        "ytd2026_not_negative": float(ytd.get("adj_net") or 0.0) >= 0.0,
        "current30_not_negative": float(current30.get("adj_net") or 0.0) >= 0.0,
    }
    ready = all(gates.values())
    return {
        "ready_pass": ready,
        "decision": "paper_ready" if ready else "rejected_or_research_only",
        "failed_gates": [k for k, v in gates.items() if not v],
        "gates": gates,
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: List[str]) -> int:
    if any(arg in {"-h", "--help"} for arg in argv):
        print(USAGE)
        return 0

    top_n = 3
    if "--top" in argv:
        i = argv.index("--top")
        top_n = int(argv[i + 1])
    only_names: List[str] = []
    if "--only" in argv:
        i = argv.index("--only")
        only_names = [x.strip() for x in str(argv[i + 1]).split(",") if x.strip()]

    bundle = RL.DATA / "research" / f"mnq_cell017_ema_impulse_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}")

    variants = full_variants()
    by_variant = {v.name: v for v in variants}
    unknown = [name for name in only_names if name not in by_variant]
    if unknown:
        raise SystemExit(f"unknown --only variants: {unknown}")

    smoke_from, smoke_to = current_window(days=60)
    if only_names:
        smoke_rows: List[Dict[str, Any]] = []
        selected_names = only_names
        (bundle / "smoke_rows.json").write_text("[]\n", encoding="utf-8")
        write_csv(bundle / "smoke_rows.csv", smoke_rows)
    else:
        smoke_submissions: List[Dict[str, Any]] = []
        for variant in variants:
            smoke_submissions.append(submit_job(
                variant=variant,
                stage="Smoke2026",
                instrument=CURRENT_CONTRACT,
                from_utc=smoke_from,
                to_utc=smoke_to,
            ))
        (bundle / "smoke_submissions.json").write_text(json.dumps(smoke_submissions, indent=2, ensure_ascii=False), encoding="utf-8")
        wait_for_jobs([s.get("job_id") for s in smoke_submissions if s.get("job_id")])

        smoke_rows = [
            summarize_stage(by_variant[str(name)], "Smoke2026", [s for s in smoke_submissions if s.get("variant") == name])
            for name in sorted(by_variant)
        ]
        smoke_rows.sort(key=score_smoke, reverse=True)
        (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2, ensure_ascii=False), encoding="utf-8")
        write_csv(bundle / "smoke_rows.csv", smoke_rows)

        print("top smoke rows:")
        for row in smoke_rows[:10]:
            print(
                f"  {row['variant']}: trades={row['trade_count']} net={row['adj_net']:.2f} "
                f"pf={row['adj_pf']:.2f} dd={row['adj_dd']:.2f} avg={row['avg_trade']:.2f}"
            )

        candidates = [row for row in smoke_rows if score_smoke(row) > -999000.0][:top_n]
        selected_names = [str(r["variant"]) for r in candidates]
    print(f"selected for validation: {selected_names}")

    stage_defs: List[Tuple[str, str, str, List[str], int, float]] = [
        ("Full", FULL[1], FULL[2], MS.contracts_for_period(ROOT, FULL[1], FULL[2]), 1, RL.fee_for(ROOT)),
        ("IS", IS[1], IS[2], MS.contracts_for_period(ROOT, IS[1], IS[2]), 1, RL.fee_for(ROOT)),
        ("OOS", OOS[1], OOS[2], MS.contracts_for_period(ROOT, OOS[1], OOS[2]), 1, RL.fee_for(ROOT)),
        ("StressSlip2", FULL[1], FULL[2], MS.contracts_for_period(ROOT, FULL[1], FULL[2]), 2, RL.fee_for(ROOT)),
        ("StressFee240", FULL[1], FULL[2], MS.contracts_for_period(ROOT, FULL[1], FULL[2]), 1, RL.fee_stress(ROOT)),
        ("StressSlip2Fee240", FULL[1], FULL[2], MS.contracts_for_period(ROOT, FULL[1], FULL[2]), 2, RL.fee_stress(ROOT)),
    ]
    ytd_from, ytd_to = current_window(days=None)
    cur_from, cur_to = current_window(days=30)
    stage_defs.extend([
        ("YTD2026", ytd_from, ytd_to, [CURRENT_CONTRACT], 1, RL.fee_for(ROOT)),
        ("Current30D", cur_from, cur_to, [CURRENT_CONTRACT], 1, RL.fee_for(ROOT)),
    ])

    validation_submissions: List[Dict[str, Any]] = []
    for name in selected_names:
        variant = by_variant[name]
        for stage, from_utc, to_utc, instruments, slip, fee in stage_defs:
            for instrument in instruments:
                validation_submissions.append(submit_job(
                    variant=variant,
                    stage=stage,
                    instrument=instrument,
                    from_utc=from_utc,
                    to_utc=to_utc,
                    slippage_ticks=slip,
                    fee=fee,
                ))
    (bundle / "validation_submissions.json").write_text(json.dumps(validation_submissions, indent=2, ensure_ascii=False), encoding="utf-8")
    wait_for_jobs([s.get("job_id") for s in validation_submissions if s.get("job_id")])

    validation_rows: List[Dict[str, Any]] = []
    for name in selected_names:
        variant = by_variant[name]
        for stage, _from, _to, _instruments, _slip, _fee in stage_defs:
            validation_rows.append(summarize_stage(
                variant,
                stage,
                [s for s in validation_submissions if s.get("variant") == name and s.get("stage") == stage],
            ))
    (bundle / "validation_rows.json").write_text(json.dumps(validation_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "validation_rows.csv", validation_rows)

    decisions: List[Dict[str, Any]] = []
    for name in selected_names:
        rows_by_stage = {str(r.get("stage")): r for r in validation_rows if r.get("variant") == name}
        decision = gate_decision(rows_by_stage)
        decision.update({
            "variant": name,
            "locked_parameters": by_variant[name].params,
            "rows": rows_by_stage,
        })
        decisions.append(decision)
    decisions.sort(
        key=lambda d: (
            bool(d.get("ready_pass")),
            float((d.get("rows") or {}).get("OOS", {}).get("adj_pf") or 0.0),
            float((d.get("rows") or {}).get("Full", {}).get("adj_net") or 0.0),
        ),
        reverse=True,
    )
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "manifest.json").write_text(json.dumps({
        "bundle": str(bundle),
        "class_name": CLASS_NAME,
        "cell_id": "CELL-017",
        "display_name": "Scalping MNQ 1m v1 c017",
        "hypothesis": "Pure EMA impulse pullback/momentum on MNQ 1m; no C015/C016 open-pressure, liquidity sweep, ORB continuation, or ORB retest module.",
        "current_contract": CURRENT_CONTRACT,
        "session_template": SESSION_TEMPLATE,
        "role": ROLE,
        "smoke_period": [smoke_from, smoke_to],
        "selected": selected_names,
        "stage_defs": stage_defs,
        "decisions": decisions,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print("decisions:")
    for dec in decisions:
        full = (dec.get("rows") or {}).get("Full", {})
        oos = (dec.get("rows") or {}).get("OOS", {})
        print(
            f"  {dec['variant']}: {dec['decision']} "
            f"full_net={float(full.get('adj_net') or 0.0):.2f} full_pf={float(full.get('adj_pf') or 0.0):.2f} "
            f"oos_pf={float(oos.get('adj_pf') or 0.0):.2f} failed={','.join(dec.get('failed_gates') or [])}"
        )
    return 0 if any(d.get("ready_pass") for d in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
