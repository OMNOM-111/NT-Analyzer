"""Search MGC evening-session candidates for a free portfolio cell.

Targets the COMEX metals ETH evening reopen after 15:00 PT using the already
compiled VWAPPullbackMGC5mV1 deploy wrapper as the SessionEdge carrier.
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


ROOT = "MGC"
INSTRUMENT = "MGC 06-26"
CLASS_NAME = "VWAPPullbackMGC5mV1"
SESSION_TEMPLATE = "Nymex Metals - Energy ETH"
CELL_ID = "CELL-019"
DISPLAY_NAME = "Scalping Evening MGC 1m/5m v1 c019"
ROLE = "smoke"

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

CSV_FIELDS = [
    "stage", "variant", "job_id", "status", "timeframe", "trade_count",
    "trades_per_day", "active_days", "active_days_pct", "adj_net", "adj_pf",
    "adj_dd", "win_pct", "avg_trade", "max_consecutive_losses",
    "slippage_ticks", "round_turn_commission", "window", "mode", "direction",
    "rr", "min_stop", "max_stop", "min_adx", "min_volume",
]


@dataclass(frozen=True)
class Variant:
    name: str
    timeframe: int
    params: Dict[str, Any]
    window: str
    mode: str
    direction: str
    rr: float
    min_stop: int
    max_stop: int
    min_adx: float
    min_volume: float


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def current_window(days: int = 30) -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def job_state(job_id: str) -> Optional[str]:
    jobs = RL.jobs_root()
    for state in ("done", "failed", "cancelled", "running", "pending"):
        if (jobs / state / job_id).is_dir():
            return state
    if (jobs / "failed" / ".quarantine" / job_id).is_dir():
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
            print(f"waiting: {len(remaining)} MGC CELL-019 jobs still pending/running", flush=True)
            last_print = now
        if remaining:
            time.sleep(interval_s)


def base_params() -> Dict[str, Any]:
    p = RL.base_risk_params(ROOT)
    p.update({
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "RiskPerTradePct": 2.0,
        "MaxDailyLossPct": 2.0,
        "MaxDailyProfitPct": 0.0,
        "MaxTradesPerDay": 10,
        "MaxConsecutiveLosses": 4,
        "UserMaxContracts": 1,
        "RoundTurnCommission": RL.fee_for(ROOT),
        "SlippageTicks": 1,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 0,
        "SecondTradeEndTime": 0,
        "TradeStartTime": 1505,
        "TradeEndTime": 2000,
        "ForceFlatTime": 2005,
        "NewsBlackoutTimes": "",
        "NewsBlackoutWindowMin": 5,
        "EmaFastPeriod": 50,
        "EmaSlowPeriod": 200,
        "AtrPeriod": 14,
        "AdxPeriod": 14,
        "VolumeSmaPeriod": 20,
        "AtrStopMult": 0.55,
        "MoveToBreakevenAtR": 0.8,
        "TrailAfterR": 1.1,
        "UseDailyBiasFilter": False,
        "DailyFastEmaPeriod": 10,
        "DailySlowEmaPeriod": 30,
        "BlockShortsWhenDailyBullish": True,
        "BlockLongsWhenDailyBearish": True,
        "OrbDurationMinutes": 15,
        "OrbBreakoutBuffer": 1,
        "OrbFailedLookback": 3,
        "MeanRevExtensionAtr": 1.0,
        "MeanRevTargetVwap": True,
        "CompressionLookback": 20,
        "CompressionAtrPct": 0.30,
        "RollingVwapBars": 288,
        "Use24hSession": False,
    })
    return p


def build_variants(limit: Optional[int] = None) -> List[Variant]:
    windows = [
        (1505, 2000, 2005),
        (1700, 2100, 2105),
        (1800, 2200, 2205),
    ]
    specs = {
        "VwapPullback": {
            "directions": ["long", "short"],
            "rrs": [2.5, 3.0],
            "stops": [(8, 16), (12, 24)],
            "volumes": [0.0, 0.7],
            "adx": [0.0],
        },
        "VwapMeanReversion": {
            "directions": ["long", "short", "both"],
            "rrs": [1.2, 1.5],
            "stops": [(8, 16), (12, 24)],
            "volumes": [0.0],
            "adx": [0.0],
        },
        "FailedOrbReversal": {
            "directions": ["long", "short", "both"],
            "rrs": [1.5, 2.0],
            "stops": [(8, 16)],
            "volumes": [0.0],
            "adx": [0.0],
        },
        "CompressionBreakout": {
            "directions": ["long", "short", "both"],
            "rrs": [1.8, 2.5],
            "stops": [(8, 16)],
            "volumes": [0.0],
            "adx": [0.0],
        },
    }
    variants: List[Variant] = []
    for tf in (1, 5):
        for start, end, flat in windows:
            window_label = f"{start:04d}_{end:04d}"
            for mode, spec in specs.items():
                for direction in spec["directions"]:
                    for rr in spec["rrs"]:
                        for min_stop, max_stop in spec["stops"]:
                            for vol in spec["volumes"]:
                                for adx in spec["adx"]:
                                    params = base_params()
                                    params.update({
                                        "SetupMode": mode,
                                        "EnableLong": direction in {"long", "both"},
                                        "EnableShort": direction in {"short", "both"},
                                        "TradeStartTime": start,
                                        "TradeEndTime": end,
                                        "ForceFlatTime": flat,
                                        "MinStopTicks": min_stop,
                                        "MaxStopTicks": max_stop,
                                        "RewardRiskRatio": rr,
                                        "MinVolumeFactor": vol,
                                        "MinAdx": adx,
                                        "PullbackLookback": 3,
                                        "EntryOffsetTicks": 0 if mode == "VwapMeanReversion" else 1,
                                        "EntryTimeoutBars": 2,
                                    })
                                    if mode == "VwapMeanReversion":
                                        params["MeanRevExtensionAtr"] = 0.8 if rr <= 1.5 else 1.0
                                        params["MoveToBreakevenAtR"] = 0.0
                                        params["TrailAfterR"] = 0.0
                                    if mode == "CompressionBreakout":
                                        params["CompressionLookback"] = 20
                                        params["CompressionAtrPct"] = 0.30
                                    rr_label = str(rr).replace(".", "")
                                    vol_label = str(vol).replace(".", "")
                                    adx_label = str(adx).replace(".", "")
                                    name = f"{mode.lower()}_{direction}_{tf}m_{window_label}_s{min_stop}_{max_stop}_rr{rr_label}_v{vol_label}_a{adx_label}"
                                    variants.append(Variant(
                                        name=name,
                                        timeframe=tf,
                                        params=params,
                                        window=f"{start:04d}-{end:04d}",
                                        mode=mode,
                                        direction=direction,
                                        rr=rr,
                                        min_stop=min_stop,
                                        max_stop=max_stop,
                                        min_adx=adx,
                                        min_volume=vol,
                                    ))
                                    if limit and len(variants) >= limit:
                                        return variants
    return variants


def submit_job(
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
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=variant.timeframe,
        slippage_ticks=slippage_ticks,
        role=ROLE,
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "") if code == 201 and isinstance(resp, dict) else ""
    print(f"submit {stage:16s} {variant.name:82s} code={code} job={job_id or resp}", flush=True)
    return {
        "stage": stage,
        "variant": variant.name,
        "job_id": job_id,
        "code": code,
        "response": resp,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "slippage_ticks": slippage_ticks,
        "round_turn_commission": fee,
        "params": params,
        "meta": variant.__dict__,
    }


def trades_from_report(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return [t for t in trades if isinstance(t, dict)]
    p = Path(str(report.get("_dir") or "")) / "trades.json"
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
    n = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            n += 1
        cur += timedelta(days=1)
    return max(1, n)


def adjusted_metrics(trades: List[Dict[str, Any]], fee: float, from_utc: str, to_utc: str) -> Dict[str, Any]:
    pnls: List[float] = []
    active_days = set()
    for trade in trades:
        qty = max(1.0, abs(float(trade.get("quantity") or 1.0)))
        pnl = float(trade.get("pnl_currency") or 0.0) - fee * qty
        pnls.append(pnl)
        exit_time = str(trade.get("exit_time_utc") or trade.get("entry_time_utc") or "")
        if len(exit_time) >= 10:
            active_days.add(exit_time[:10])
    gp = sum(p for p in pnls if p > 0)
    gl = sum(p for p in pnls if p < 0)
    pf = gp / abs(gl) if gl < 0 else (999.0 if gp > 0 else 0.0)
    net = sum(pnls)
    eq = peak = dd = 0.0
    wins = losses = max_losses = 0
    for pnl in pnls:
        eq += pnl
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
        if pnl > 0:
            wins += 1
            losses = 0
        elif pnl < 0:
            losses += 1
            max_losses = max(max_losses, losses)
    days = weekdays(from_utc, to_utc)
    return {
        "trade_count": len(pnls),
        "trades_per_day": round(len(pnls) / days, 4),
        "active_days": len(active_days),
        "active_days_pct": round(len(active_days) / days * 100.0, 4),
        "adj_net": round(net, 6),
        "adj_pf": round(pf, 6),
        "adj_dd": round(dd, 6),
        "win_pct": round(wins / len(pnls) * 100.0, 4) if pnls else 0.0,
        "avg_trade": round(net / len(pnls), 6) if pnls else 0.0,
        "max_consecutive_losses": max_losses,
    }


def row_from_submission(sub: Dict[str, Any]) -> Dict[str, Any]:
    meta = sub.get("meta") or {}
    row = {
        "stage": sub["stage"],
        "variant": sub["variant"],
        "job_id": sub.get("job_id") or "",
        "status": job_state(sub.get("job_id") or "") or "missing",
        "timeframe": meta.get("timeframe"),
        "slippage_ticks": sub["slippage_ticks"],
        "round_turn_commission": sub["round_turn_commission"],
        "window": meta.get("window"),
        "mode": meta.get("mode"),
        "direction": meta.get("direction"),
        "rr": meta.get("rr"),
        "min_stop": meta.get("min_stop"),
        "max_stop": meta.get("max_stop"),
        "min_adx": meta.get("min_adx"),
        "min_volume": meta.get("min_volume"),
    }
    report = RL.read_job_report(row["job_id"])
    if not report or "result" not in report:
        row.update({
            "trade_count": 0,
            "trades_per_day": 0.0,
            "active_days": 0,
            "active_days_pct": 0.0,
            "adj_net": 0.0,
            "adj_pf": 0.0,
            "adj_dd": 0.0,
            "win_pct": 0.0,
            "avg_trade": 0.0,
            "max_consecutive_losses": 0,
        })
        return row
    row.update(adjusted_metrics(
        trades_from_report(report),
        float(sub["round_turn_commission"]),
        str(sub["from_utc"]),
        str(sub["to_utc"]),
    ))
    return row


def score_smoke(row: Dict[str, Any]) -> float:
    trades = int(row.get("trade_count") or 0)
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    avg = float(row.get("avg_trade") or 0.0)
    active = float(row.get("active_days_pct") or 0.0)
    if trades < 12 or net <= 0 or pf < 1.05:
        return -1e9
    return net + min(pf, 3.0) * 130.0 + min(trades, 300) * 0.5 + avg * 20.0 + active * 0.4 - dd * 0.35


def gates(rows: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
    full = rows.get("Full", {})
    is_row = rows.get("IS", {})
    oos = rows.get("OOS", {})
    slip = rows.get("StressSlip2", {})
    fee = rows.get("StressFee240", {})
    combined = rows.get("StressSlip2Fee240", {})
    current = rows.get("Current30D", {})
    return {
        "evening_eth_template": True,
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "max_dd_pct_15": RL.max_drawdown_within_budget(float(full.get("adj_dd") or 0.0)),
        "full_trades_ge_80": int(full.get("trade_count") or 0) >= 80,
        "is_net_positive": float(is_row.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee.get("adj_net") or 0.0) > 0.0,
        "stress_combined_positive": float(combined.get("adj_net") or 0.0) > 0.0,
        "current30_nonnegative": float(current.get("adj_net") or 0.0) >= 0.0,
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--smoke-days", type=int, default=60)
    ap.add_argument("--smoke-full", action="store_true")
    ap.add_argument("--only-5m", action="store_true")
    args = ap.parse_args(argv)

    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mgc_cell019_evening_session_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    variants = build_variants(args.limit or None)
    if args.only_5m:
        variants = [v for v in variants if v.timeframe == 5]
    if args.smoke_full:
        smoke_from, smoke_to = FULL[1], FULL[2]
        smoke_stage = "SmokeFull"
    else:
        smoke_from, smoke_to = current_window(args.smoke_days)
        smoke_stage = "Smoke"
    print(f"bundle: {bundle}", flush=True)
    print(f"variants: {len(variants)} smoke={smoke_from}..{smoke_to}", flush=True)

    smoke_subs = [submit_job(v, smoke_stage, smoke_from, smoke_to, 1, RL.fee_for(ROOT)) for v in variants]
    (bundle / "smoke_submissions.json").write_text(json.dumps(smoke_subs, indent=2), encoding="utf-8")
    wait_for_jobs([s.get("job_id") for s in smoke_subs if s.get("job_id")])
    smoke_rows = [row_from_submission(s) for s in smoke_subs]
    smoke_rows.sort(key=score_smoke, reverse=True)
    write_csv(bundle / "smoke_rows.csv", smoke_rows)
    (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2), encoding="utf-8")

    selected_names = [r["variant"] for r in smoke_rows if score_smoke(r) > -1e8][:args.top]
    by_name = {v.name: v for v in variants}
    selected = [by_name[n] for n in selected_names]
    print("selected:", flush=True)
    for row in smoke_rows[:args.top]:
        print(
            f"  {row['variant']}: trades={row['trade_count']} active={row['active_days_pct']} "
            f"net={float(row['adj_net']):.2f} pf={float(row['adj_pf']):.2f} dd={float(row['adj_dd']):.2f}",
            flush=True,
        )

    cur_from, cur_to = current_window(30)
    val_plan = [
        ("Full", FULL[1], FULL[2], 1, RL.fee_for(ROOT)),
        ("IS", IS[1], IS[2], 1, RL.fee_for(ROOT)),
        ("OOS", OOS[1], OOS[2], 1, RL.fee_for(ROOT)),
        ("StressSlip2", FULL[1], FULL[2], 2, RL.fee_for(ROOT)),
        ("StressFee240", FULL[1], FULL[2], 1, 2.40),
        ("StressSlip2Fee240", FULL[1], FULL[2], 2, 2.40),
        ("Current30D", cur_from, cur_to, 1, RL.fee_for(ROOT)),
    ]
    val_subs: List[Dict[str, Any]] = []
    for variant in selected:
        for stage, from_utc, to_utc, slip, fee in val_plan:
            val_subs.append(submit_job(variant, stage, from_utc, to_utc, slip, fee))
    (bundle / "validation_submissions.json").write_text(json.dumps(val_subs, indent=2), encoding="utf-8")
    wait_for_jobs([s.get("job_id") for s in val_subs if s.get("job_id")])
    val_rows = [row_from_submission(s) for s in val_subs]
    write_csv(bundle / "validation_rows.csv", val_rows)
    (bundle / "validation_rows.json").write_text(json.dumps(val_rows, indent=2), encoding="utf-8")

    decisions: List[Dict[str, Any]] = []
    for variant in selected:
        rows = {r["stage"]: r for r in val_rows if r["variant"] == variant.name}
        gate_values = gates(rows)
        failed = [k for k, v in gate_values.items() if not v]
        decisions.append({
            "variant": variant.name,
            "display_name": DISPLAY_NAME,
            "cell_id": CELL_ID,
            "decision": "paper_ready_candidate" if not failed else "research_only",
            "ready_pass": not failed,
            "failed_gates": failed,
            "gates": gate_values,
            "locked_parameters": variant.params,
            "timeframe": variant.timeframe,
            "rows": rows,
        })
    decisions.sort(key=lambda d: (
        1 if d["ready_pass"] else 0,
        float((d.get("rows") or {}).get("Full", {}).get("adj_net") or -math.inf),
    ), reverse=True)
    summary = {
        "bundle": str(bundle),
        "cell_id": CELL_ID,
        "display_name": DISPLAY_NAME,
        "class_name": CLASS_NAME,
        "instrument": INSTRUMENT,
        "session_template": SESSION_TEMPLATE,
        "role_note": "Submitted as role=smoke because the ETH template is catalog-flagged supported=false; bridge resolved and applied it.",
        "selected": selected_names,
        "ready": [d["variant"] for d in decisions if d["ready_pass"]],
        "best": decisions[0] if decisions else None,
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    print("decisions:", flush=True)
    for d in decisions:
        full = d.get("rows", {}).get("Full", {})
        cur = d.get("rows", {}).get("Current30D", {})
        print(
            f"  {d['variant']}: {d['decision']} full_net={full.get('adj_net')} "
            f"pf={full.get('adj_pf')} trades={full.get('trade_count')} "
            f"current30={cur.get('adj_net')} failed={','.join(d['failed_gates'])}",
            flush=True,
        )
    return 0 if any(d.get("ready_pass") for d in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main())
