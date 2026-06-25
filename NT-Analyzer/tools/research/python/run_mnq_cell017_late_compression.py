"""Research MNQ CELL-017 late-window CompressionBreakout candidates.

This runner intentionally avoids the previously rejected CELL-017 families:
VwapPullbackScalp, EmaImpulseScalp, and the old
NTAMnqLateVwapLongScalpC017 deploy wrapper.  It uses the already compiled
SessionEdge carrier wrapper to exercise SetupMode=CompressionBreakout in the
free MNQ late window after c014 stops accepting entries.
"""
from __future__ import annotations

import argparse
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


ROOT = "MNQ"
FRONT = RL.resolve_front_contract(ROOT)
CURRENT_CONTRACT = str(FRONT.get("instrument") or "MNQ 06-26")
SESSION_TEMPLATE = RL.session_for(ROOT)
CELL_ID = "CELL-017"

# Concrete compiled wrapper over NTAMicroSessionEdgeExplorer.  The job params
# below override the MGC defaults and lock SetupMode=CompressionBreakout.
CARRIER_CLASS = "VWAPPullbackMGC5mV1"
DISPLAY_NAME = "Compression Breakout MNQ 1m v1 c017"

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

CSV_FIELDS = [
    "stage", "variant", "class_name", "timeframe", "from_utc", "to_utc", "job_id", "status",
    "trade_count", "trades_per_day", "active_days", "active_days_pct",
    "adj_net", "adj_pf", "adj_dd", "win_pct", "avg_trade",
    "max_consecutive_losses", "same_bar_count", "same_bar_pct",
    "slippage_ticks", "round_turn_commission", "setup_mode", "direction",
    "trade_start", "trade_end", "force_flat", "rr", "min_stop", "max_stop",
    "atr_stop_mult", "min_adx", "min_volume", "compression_lookback",
    "compression_atr_pct", "entry_offset",
]


@dataclass(frozen=True)
class Variant:
    name: str
    timeframe: int
    params: Dict[str, Any]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def current_window(days: Optional[int] = 60) -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = date(2026, 1, 1) if days is None else end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def job_state(job_id: str) -> Optional[str]:
    base = RL.jobs_root()
    for state in ("done", "failed", "cancelled", "running", "pending"):
        if (base / state / job_id).is_dir():
            return state
    if (base / "failed" / ".quarantine" / job_id).is_dir():
        return "failed"
    return None


def wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 21600, interval_s: int = 4) -> None:
    remaining = {j for j in job_ids if j}
    deadline = time.time() + timeout_s
    last_print = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            if job_state(job_id) in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        now = time.time()
        if remaining and now - last_print >= 30:
            print(f"waiting: {len(remaining)} MNQ CELL-017 compression jobs still pending/running", flush=True)
            last_print = now
        if remaining:
            time.sleep(interval_s)


def base_params() -> Dict[str, Any]:
    return {
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "RiskPerTradePct": 0.35,
        "MaxDailyLossPct": 3.0,
        "MaxDailyProfitPct": 0.0,
        "MaxTradesPerDay": 16,
        "MaxConsecutiveLosses": 3,
        "UserMaxContracts": 1,
        "RoundTurnCommission": RL.fee_for(ROOT),
        "SlippageTicks": 1,
        "SetupMode": "CompressionBreakout",
        "EnableLong": True,
        "EnableShort": True,
        "EmaFastPeriod": 50,
        "EmaSlowPeriod": 200,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "MinAdx": 0.0,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.0,
        "PullbackLookback": 3,
        "AtrStopMult": 0.30,
        "MinStopTicks": 4,
        "MaxStopTicks": 10,
        "RewardRiskRatio": 1.50,
        "MoveToBreakevenAtR": 0.0,
        "TrailAfterR": 1.0,
        "EntryTimeoutBars": 2,
        "EntryOffsetTicks": 0,
        "TradeStartTime": 1246,
        "TradeEndTime": 1325,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1330,
        "NewsBlackoutTimes": "",
        "NewsBlackoutWindowMin": 5,
        "UseDailyBiasFilter": False,
        "DailyFastEmaPeriod": 10,
        "DailySlowEmaPeriod": 30,
        "BlockShortsWhenDailyBullish": True,
        "BlockLongsWhenDailyBearish": True,
        "OrbDurationMinutes": 30,
        "OrbBreakoutBuffer": 1,
        "OrbFailedLookback": 3,
        "MeanRevExtensionAtr": 1.5,
        "MeanRevTargetVwap": True,
        "CompressionLookback": 12,
        "CompressionAtrPct": 0.60,
        "RollingVwapBars": 288,
        "Use24hSession": False,
    }


def make_variant(
    *,
    start: int,
    end: int,
    flat: int,
    direction: str,
    lookback: int,
    atr_pct: float,
    rr: float,
    stop_min: int,
    stop_max: int,
    volume: float,
    entry_offset: int,
    atr_mult: float,
    be_at_r: float,
) -> Variant:
    params = base_params()
    params.update({
        "TradeStartTime": start,
        "TradeEndTime": end,
        "ForceFlatTime": flat,
        "EnableLong": direction in {"long", "both"},
        "EnableShort": direction in {"short", "both"},
        "CompressionLookback": lookback,
        "CompressionAtrPct": atr_pct,
        "RewardRiskRatio": rr,
        "MinStopTicks": stop_min,
        "MaxStopTicks": stop_max,
        "MinVolumeFactor": volume,
        "EntryOffsetTicks": entry_offset,
        "AtrStopMult": atr_mult,
        "MoveToBreakevenAtR": be_at_r,
    })
    pct_label = str(atr_pct).replace(".", "")
    rr_label = str(rr).replace(".", "")
    name = (
        f"compress_{direction}_{start:04d}_{end:04d}"
        f"_l{lookback}_p{pct_label}_s{stop_min}_{stop_max}"
        f"_rr{rr_label}_v{str(volume).replace('.', '')}"
        f"_o{entry_offset}_a{str(atr_mult).replace('.', '')}"
    )
    if be_at_r > 0:
        name += f"_be{str(be_at_r).replace('.', '')}"
    return Variant(name=name, timeframe=1, params=params)


def build_variants(limit: Optional[int] = None) -> List[Variant]:
    windows = [
        (1246, 1325, 1330),
        (1246, 1315, 1330),
        (1255, 1325, 1330),
        (1300, 1325, 1330),
    ]
    variants: List[Variant] = []
    for start, end, flat in windows:
        for direction in ("both", "long", "short"):
            for lookback in (8, 12, 20):
                for atr_pct in (0.35, 0.60, 0.85):
                    for rr in (1.25, 1.75):
                        for stop_min, stop_max in ((4, 10), (6, 14)):
                            variants.append(make_variant(
                                start=start,
                                end=end,
                                flat=flat,
                                direction=direction,
                                lookback=lookback,
                                atr_pct=atr_pct,
                                rr=rr,
                                stop_min=stop_min,
                                stop_max=stop_max,
                                volume=0.0,
                                entry_offset=0,
                                atr_mult=0.30,
                                be_at_r=0.0,
                            ))

    # A small second pass probes modest volume confirmation and breakeven
    # management without exploding the smoke grid.
    for start, end, flat in ((1246, 1325, 1330), (1300, 1325, 1330)):
        for direction in ("both", "long", "short"):
            for lookback in (8, 12):
                for atr_pct in (0.60, 0.85):
                    for rr in (1.25, 1.75):
                        variants.append(make_variant(
                            start=start,
                            end=end,
                            flat=flat,
                            direction=direction,
                            lookback=lookback,
                            atr_pct=atr_pct,
                            rr=rr,
                            stop_min=4,
                            stop_max=10,
                            volume=0.7,
                            entry_offset=0,
                            atr_mult=0.30,
                            be_at_r=0.7,
                        ))

    if limit is not None:
        variants = variants[:limit]
    return variants


def submit_job(
    *,
    variant: Variant,
    stage: str,
    from_utc: str,
    to_utc: str,
    slippage_ticks: int = 1,
    fee: float = 1.90,
) -> Dict[str, Any]:
    params = dict(variant.params)
    params["SlippageTicks"] = slippage_ticks
    params["RoundTurnCommission"] = fee
    body = RL.build_job_body(
        class_name=CARRIER_CLASS,
        instrument=CURRENT_CONTRACT,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=variant.timeframe,
        slippage_ticks=slippage_ticks,
        role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([CURRENT_CONTRACT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "") if code == 201 and isinstance(resp, dict) else ""
    print(
        f"submit {stage:18s} {variant.name:72s} code={code} job={job_id or resp}",
        flush=True,
    )
    return {
        "stage": stage,
        "variant": variant.name,
        "class_name": CARRIER_CLASS,
        "timeframe": variant.timeframe,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "slippage_ticks": slippage_ticks,
        "round_turn_commission": fee,
        "params": params,
        "code": code,
        "response": resp,
        "job_id": job_id,
    }


def trades_from_report(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return [t for t in trades if isinstance(t, dict)]
    directory = Path(str(report.get("_dir") or ""))
    p = directory / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [t for t in raw if isinstance(t, dict)]
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
            return [t for t in raw["trades"] if isinstance(t, dict)]
    return []


def weekdays(from_utc: str, to_utc: str) -> int:
    start = date.fromisoformat(from_utc[:10])
    end = date.fromisoformat(to_utc[:10])
    total = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            total += 1
        cur += timedelta(days=1)
    return total


def trade_qty(trade: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(trade.get("quantity") or 1.0)))
    except Exception:
        return 1.0


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


def direction_from(params: Dict[str, Any]) -> str:
    if params.get("EnableLong") and params.get("EnableShort"):
        return "both"
    return "long" if params.get("EnableLong") else "short"


def same_bar_count(trades: List[Dict[str, Any]]) -> int:
    total = 0
    for trade in trades:
        entry = str(trade.get("entry_time_utc") or "")
        exit_ = str(trade.get("exit_time_utc") or "")
        if entry and exit_ and entry == exit_:
            total += 1
    return total


def summarize(submission: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(submission.get("job_id") or "")
    report = RL.read_job_report(job_id) if job_id else None
    row = dict(submission)
    params = row.get("params") or {}
    row.update({
        "status": job_state(job_id) if job_id else "missing",
        "setup_mode": str(params.get("SetupMode") or ""),
        "direction": direction_from(params),
        "trade_start": params.get("TradeStartTime"),
        "trade_end": params.get("TradeEndTime"),
        "force_flat": params.get("ForceFlatTime"),
        "rr": params.get("RewardRiskRatio"),
        "min_stop": params.get("MinStopTicks"),
        "max_stop": params.get("MaxStopTicks"),
        "atr_stop_mult": params.get("AtrStopMult"),
        "min_adx": params.get("MinAdx"),
        "min_volume": params.get("MinVolumeFactor"),
        "compression_lookback": params.get("CompressionLookback"),
        "compression_atr_pct": params.get("CompressionAtrPct"),
        "entry_offset": params.get("EntryOffsetTicks"),
    })
    if not report or "result" not in report:
        row.update({
            "trade_count": 0,
            "adj_net": 0.0,
            "adj_pf": 0.0,
            "adj_dd": 0.0,
            "same_bar_count": 0,
            "same_bar_pct": 0.0,
        })
        return row

    fee = float(row.get("round_turn_commission") or 0.0)
    trades = trades_from_report(report)
    pnls = [float(t.get("pnl_currency") or 0.0) - fee * trade_qty(t) for t in trades]
    gross_profit = sum(p for p in pnls if p > 0.0)
    gross_loss = abs(sum(p for p in pnls if p < 0.0))
    adj_pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    active_days = {
        str(t.get("entry_time_utc") or t.get("exit_time_utc") or "")[:10]
        for t in trades
        if t.get("entry_time_utc") or t.get("exit_time_utc")
    }
    day_count = weekdays(str(row.get("from_utc")), str(row.get("to_utc")))
    count = len(pnls)
    adj_net = sum(pnls)
    same_bar = same_bar_count(trades)
    row.update({
        "trade_count": count,
        "trades_per_day": round(count / day_count, 4) if day_count else 0.0,
        "active_days": len(active_days),
        "active_days_pct": round(len(active_days) / day_count * 100.0, 4) if day_count else 0.0,
        "adj_net": round(adj_net, 6),
        "adj_pf": round(adj_pf, 6) if math.isfinite(adj_pf) else 999.0,
        "adj_dd": round(dd, 6),
        "win_pct": round((sum(1 for p in pnls if p > 0.0) / count * 100.0) if count else 0.0, 4),
        "avg_trade": round(adj_net / count, 6) if count else 0.0,
        "max_consecutive_losses": max_consecutive_losses(pnls),
        "same_bar_count": same_bar,
        "same_bar_pct": round((same_bar / count * 100.0) if count else 0.0, 4),
    })
    return row


def score(row: Dict[str, Any]) -> float:
    trades = float(row.get("trade_count") or 0.0)
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    same_pct = float(row.get("same_bar_pct") or 0.0)
    avg = float(row.get("avg_trade") or 0.0)
    if trades <= 0:
        return -999999.0
    if net <= 0.0 or pf < 1.05:
        return -500000.0 + net - dd
    return net + min(pf, 3.0) * 150.0 + min(trades, 250.0) * 0.8 + avg * 20.0 - dd * 0.45 - same_pct * 2.0


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def gate_decision(rows_by_stage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    full = rows_by_stage.get("Full") or {}
    is_row = rows_by_stage.get("IS") or {}
    oos = rows_by_stage.get("OOS") or {}
    slip2 = rows_by_stage.get("StressSlip2") or {}
    fee240 = rows_by_stage.get("StressFee240") or {}
    combined = rows_by_stage.get("StressSlip2Fee240") or {}
    current30 = rows_by_stage.get("Current30D") or {}
    gates = {
        "full_net_ge_300": float(full.get("adj_net") or 0.0) >= 300.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "max_dd_pct_15": RL.max_drawdown_within_budget(float(full.get("adj_dd") or 0.0)),
        "full_trades_ge_80": int(full.get("trade_count") or 0) >= 80,
        "full_same_bar_pct_le_70": float(full.get("same_bar_pct") or 0.0) <= 70.0,
        "is_net_positive": float(is_row.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip2.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee240.get("adj_net") or 0.0) > 0.0,
        "stress_combined_positive": float(combined.get("adj_net") or 0.0) > 0.0,
        "current30_net_ge_25": float(current30.get("adj_net") or 0.0) >= 25.0,
        "current30_trades_ge_5": int(current30.get("trade_count") or 0) >= 5,
    }
    return {
        "ready_pass": all(gates.values()),
        "decision": "paper_ready" if all(gates.values()) else "research_only",
        "failed_gates": [k for k, v in gates.items() if not v],
        "gates": gates,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=8, help="number of smoke winners to validate")
    parser.add_argument("--smoke-limit", type=int, default=0, help="cap smoke variants for quick checks")
    parser.add_argument("--only", default="", help="comma-separated variant names to run/validate")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    smoke_limit = args.smoke_limit if args.smoke_limit and args.smoke_limit > 0 else None
    variants = build_variants(limit=smoke_limit)
    by_name = {v.name: v for v in variants}

    only = [x.strip() for x in args.only.split(",") if x.strip()]
    if only:
        missing = [name for name in only if name not in by_name]
        if missing:
            raise RuntimeError(f"variant not found: {missing}")
        variants = [by_name[name] for name in only]

    bundle = RL.DATA / "research" / f"mnq_cell017_late_compression_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)
    print(f"carrier: {CARRIER_CLASS} instrument={CURRENT_CONTRACT} session={SESSION_TEMPLATE}", flush=True)
    print(f"smoke variants: {len(variants)}", flush=True)

    smoke_from, smoke_to = current_window(days=60)
    smoke_submissions = [
        submit_job(variant=v, stage="Smoke60D", from_utc=smoke_from, to_utc=smoke_to)
        for v in variants
    ]
    (bundle / "smoke_submissions.json").write_text(
        json.dumps(smoke_submissions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    wait_for_jobs([s.get("job_id") for s in smoke_submissions if s.get("job_id")])

    smoke_rows = [summarize(s) for s in smoke_submissions]
    smoke_rows.sort(key=score, reverse=True)
    (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "smoke_rows.csv", smoke_rows)

    selected = [r["variant"] for r in smoke_rows if score(r) > -499000.0][:args.top]
    print("top smoke rows:", flush=True)
    for row in smoke_rows[:12]:
        print(
            f"  {row['variant']}: trades={row['trade_count']} "
            f"net={float(row.get('adj_net') or 0.0):.2f} pf={float(row.get('adj_pf') or 0.0):.2f} "
            f"dd={float(row.get('adj_dd') or 0.0):.2f} same_bar={float(row.get('same_bar_pct') or 0.0):.1f}%",
            flush=True,
        )
    print(f"selected for validation: {selected}", flush=True)

    stage_defs = [
        ("Full", FULL[1], FULL[2], 1, RL.fee_for(ROOT)),
        ("IS", IS[1], IS[2], 1, RL.fee_for(ROOT)),
        ("OOS", OOS[1], OOS[2], 1, RL.fee_for(ROOT)),
        ("StressSlip2", FULL[1], FULL[2], 2, RL.fee_for(ROOT)),
        ("StressFee240", FULL[1], FULL[2], 1, RL.fee_stress(ROOT)),
        ("StressSlip2Fee240", FULL[1], FULL[2], 2, RL.fee_stress(ROOT)),
        ("Current30D", *current_window(days=30), 1, RL.fee_for(ROOT)),
    ]

    validation_submissions: List[Dict[str, Any]] = []
    for name in selected:
        variant = by_name[name]
        for stage, from_utc, to_utc, slip, fee in stage_defs:
            validation_submissions.append(submit_job(
                variant=variant,
                stage=stage,
                from_utc=from_utc,
                to_utc=to_utc,
                slippage_ticks=slip,
                fee=fee,
            ))
    (bundle / "validation_submissions.json").write_text(
        json.dumps(validation_submissions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    wait_for_jobs([s.get("job_id") for s in validation_submissions if s.get("job_id")])

    validation_rows = [summarize(s) for s in validation_submissions]
    (bundle / "validation_rows.json").write_text(
        json.dumps(validation_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_csv(bundle / "validation_rows.csv", validation_rows)

    decisions: List[Dict[str, Any]] = []
    for name in selected:
        rows_by_stage = {str(r.get("stage")): r for r in validation_rows if r.get("variant") == name}
        decision = gate_decision(rows_by_stage)
        decision.update({
            "variant": name,
            "class_name": CARRIER_CLASS,
            "timeframe": 1,
            "locked_parameters": by_name[name].params,
            "rows": rows_by_stage,
        })
        decisions.append(decision)
    decisions.sort(
        key=lambda d: (
            bool(d.get("ready_pass")),
            float((d.get("rows") or {}).get("Full", {}).get("adj_net") or 0.0),
            float((d.get("rows") or {}).get("OOS", {}).get("adj_pf") or 0.0),
        ),
        reverse=True,
    )

    summary = {
        "bundle": str(bundle),
        "cell_id": CELL_ID,
        "display_name": DISPLAY_NAME,
        "instrument": CURRENT_CONTRACT,
        "session_template": SESSION_TEMPLATE,
        "carrier_class": CARRIER_CLASS,
        "hypothesis": "late low-volatility compression breakout after C014 entry cutoff",
        "excluded_families": ["VwapPullbackScalp", "EmaImpulseScalp", "NTAMnqLateVwapLongScalpC017"],
        "free_windows_pt": ["12:46-13:25", "12:46-13:15", "12:55-13:25", "13:00-13:25"],
        "flat_time_pt": "13:30",
        "anti_weak_edge_gates": {
            "full_net_min": 300.0,
            "full_trade_count_min": 80,
            "current30_net_min": 25.0,
            "current30_trade_count_min": 5,
        },
        "selected": selected,
        "decisions": decisions,
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")

    print("decisions:", flush=True)
    for d in decisions:
        full = (d.get("rows") or {}).get("Full", {})
        oos = (d.get("rows") or {}).get("OOS", {})
        cur = (d.get("rows") or {}).get("Current30D", {})
        print(
            f"  {d['variant']}: {d['decision']} full_net={float(full.get('adj_net') or 0.0):.2f} "
            f"full_pf={float(full.get('adj_pf') or 0.0):.2f} full_trades={int(full.get('trade_count') or 0)} "
            f"oos_pf={float(oos.get('adj_pf') or 0.0):.2f} current30={float(cur.get('adj_net') or 0.0):.2f} "
            f"failed={','.join(d.get('failed_gates') or [])}",
            flush=True,
        )
    return 0 if any(d.get("ready_pass") for d in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
