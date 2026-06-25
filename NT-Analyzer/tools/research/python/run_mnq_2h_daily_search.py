"""Search MNQ 2h+ intraday candidates with daily-frequency bias.

This runner intentionally excludes narrow late-session windows.  Every candidate
has one continuous entry window of at least 120 minutes.  It uses the already
compiled NTAMicroMnqScalpPilot carrier so promising profiles can be run without
waiting for a new NinjaScript compile.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import mnq_scalp_pilot_lib as MS  # noqa: E402
import research_lib as RL  # noqa: E402


ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
CLASS_NAME = "NTAMicroMnqScalpPilot"
ROLE = "smoke"

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

CSV_FIELDS = [
    "stage", "variant", "job_id", "status", "trade_count", "trades_per_day",
    "active_days", "active_days_pct", "adj_net", "adj_pf", "adj_dd",
    "win_pct", "avg_trade", "max_consecutive_losses", "slippage_ticks",
    "round_turn_commission", "window", "module", "direction", "rr",
    "min_stop", "max_stop", "min_volume", "setup_mode",
]


@dataclass(frozen=True)
class Variant:
    name: str
    params: Dict[str, Any]
    window: str
    module: str
    direction: str
    rr: float
    min_stop: int
    max_stop: int
    min_volume: float
    setup_mode: str


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def minutes(hhmm: int) -> int:
    return (hhmm // 100) * 60 + (hhmm % 100)


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
            print(f"waiting: {len(remaining)} MNQ 2h jobs still pending/running", flush=True)
            last_print = now
        if remaining:
            time.sleep(interval_s)


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
        "RoundTurnCommission": RL.fee_for(ROOT),
        "SlippageTicks": 1,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1300,
        "NewsBlackoutTimes": "",
        "NewsBlackoutWindowMin": 5,
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
        "RequireSlowTrend": False,
        "AtrStopMult": 0.30,
        "MoveToBreakevenAtR": 0.7,
        "TrailAfterR": 1.0,
        "UseTimeStop": True,
        "TimeStopBars": 3,
        "MinProgressR": 0.30,
        "EntryOffsetTicks": 0,
        "EntryTimeoutBars": 2,
    })
    return p


def module_params(module: str, direction: str) -> Dict[str, Any]:
    p: Dict[str, Any] = {
        "UseSetupModeFilter": False,
        "EnableVwapReclaim": False,
        "EnableEmaMomentum": False,
        "EnableMicroOrb": False,
        "EnableFailedBreakout": False,
        "EnableLong": direction in {"long", "both"},
        "EnableShort": direction in {"short", "both"},
    }
    if module == "all":
        p.update({
            "UseSetupModeFilter": False,
            "EnableVwapReclaim": True,
            "EnableEmaMomentum": True,
            "EnableMicroOrb": True,
            "EnableFailedBreakout": True,
        })
    elif module == "vwap":
        p.update({
            "UseSetupModeFilter": True,
            "SetupMode": "VwapPullbackScalp",
            "EnableVwapReclaim": True,
        })
    elif module == "ema":
        p.update({
            "UseSetupModeFilter": True,
            "SetupMode": "EmaImpulseScalp",
            "EnableEmaMomentum": True,
        })
    elif module == "orb_retest":
        p.update({
            "UseSetupModeFilter": True,
            "SetupMode": "OrbRetestScalp",
            "EnableMicroOrb": True,
        })
    elif module == "fail":
        p.update({
            "UseSetupModeFilter": True,
            "SetupMode": "FailedOrbReversalScalp",
            "EnableFailedBreakout": True,
        })
    else:
        raise ValueError(module)
    return p


def build_variants(limit: Optional[int] = None) -> List[Variant]:
    windows = [
        (635, 835, 1300),
        (700, 900, 1300),
        (830, 1030, 1300),
        (900, 1100, 1300),
        (1030, 1230, 1300),
        (1045, 1245, 1300),
        (635, 1245, 1300),
    ]
    modules = {
        "all": {
            "directions": ["short", "both"],
            "rrs": [2.0, 3.0, 4.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.7, 0.8, 1.0],
        },
        "vwap": {
            "directions": ["long", "short", "both"],
            "rrs": [1.5, 2.0, 2.5],
            "stops": [(4, 10), (8, 16)],
            "volumes": [0.7, 1.0],
        },
        "fail": {
            "directions": ["long", "short", "both"],
            "rrs": [1.0, 1.25, 1.5, 2.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.0, 0.7],
        },
        "ema": {
            "directions": ["long", "short", "both"],
            "rrs": [1.5, 2.0, 3.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.7, 1.0],
        },
        "orb_retest": {
            "directions": ["long", "short", "both"],
            "rrs": [1.5, 1.75, 2.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.7, 1.0],
        },
    }
    variants: List[Variant] = []
    for start, end, flat in windows:
        duration = minutes(end) - minutes(start)
        if duration < 120:
            raise AssertionError(f"window {start}-{end} is shorter than 120 minutes")
        window_label = f"{start:04d}_{end:04d}"
        for module, spec in modules.items():
            for direction in spec["directions"]:
                for rr in spec["rrs"]:
                    for min_stop, max_stop in spec["stops"]:
                        for vol in spec["volumes"]:
                            params = base_params()
                            params.update(module_params(module, direction))
                            params.update({
                                "TradeStartTime": start,
                                "TradeEndTime": end,
                                "ForceFlatTime": flat,
                                "RewardRiskRatio": rr,
                                "MinStopTicks": min_stop,
                                "MaxStopTicks": max_stop,
                                "MinVolumeFactor": vol,
                                "PullbackLookback": 4 if module in {"vwap", "ema"} else 3,
                            })
                            if module == "fail":
                                params["OrbFailedLookback"] = 3
                            rr_label = str(rr).replace(".", "")
                            vol_label = str(vol).replace(".", "")
                            name = f"{module}_{direction}_{window_label}_s{min_stop}_{max_stop}_rr{rr_label}_v{vol_label}"
                            variants.append(Variant(
                                name=name,
                                params=params,
                                window=f"{start:04d}-{end:04d}",
                                module=module,
                                direction=direction,
                                rr=rr,
                                min_stop=min_stop,
                                max_stop=max_stop,
                                min_volume=vol,
                                setup_mode=str(params.get("SetupMode") or "AllModules"),
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
        bars_period_value=1,
        slippage_ticks=slippage_ticks,
        role=ROLE,
        session_template=RL.session_for(ROOT),
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "") if code == 201 and isinstance(resp, dict) else ""
    print(f"submit {stage:16s} {variant.name:62s} code={code} job={job_id or resp}", flush=True)
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
        exit_time = str(
            trade.get("exit_time_utc")
            or trade.get("exit_time")
            or trade.get("entry_time_utc")
            or trade.get("entry_time")
            or ""
        )
        if len(exit_time) >= 10:
            active_days.add(exit_time[:10])
    gp = sum(p for p in pnls if p > 0)
    gl = sum(p for p in pnls if p < 0)
    net = sum(pnls)
    pf = gp / abs(gl) if gl < 0 else (999.0 if gp > 0 else 0.0)
    eq = peak = dd = 0.0
    max_losses = losses = 0
    wins = 0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
        if p > 0:
            wins += 1
            losses = 0
        elif p < 0:
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
    variant_meta = sub.get("meta") or {}
    row = {
        "stage": sub["stage"],
        "variant": sub["variant"],
        "job_id": sub.get("job_id") or "",
        "status": job_state(sub.get("job_id") or "") or "missing",
        "slippage_ticks": sub["slippage_ticks"],
        "round_turn_commission": sub["round_turn_commission"],
        "window": variant_meta.get("window"),
        "module": variant_meta.get("module"),
        "direction": variant_meta.get("direction"),
        "rr": variant_meta.get("rr"),
        "min_stop": variant_meta.get("min_stop"),
        "max_stop": variant_meta.get("max_stop"),
        "min_volume": variant_meta.get("min_volume"),
        "setup_mode": variant_meta.get("setup_mode"),
    }
    report = RL.read_job_report(row["job_id"])
    if not report or "result" not in report:
        row.update({
            "trade_count": 0, "trades_per_day": 0.0, "active_days": 0,
            "active_days_pct": 0.0, "adj_net": 0.0, "adj_pf": 0.0,
            "adj_dd": 0.0, "win_pct": 0.0, "avg_trade": 0.0,
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
    active = float(row.get("active_days_pct") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    if trades < 8 or net <= 0 or pf < 1.05:
        return -1e9
    return net + 15.0 * min(pf, 3.0) + 0.5 * active - 0.15 * dd


def gates(rows: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
    full = rows.get("Full", {})
    is_row = rows.get("IS", {})
    oos = rows.get("OOS", {})
    slip = rows.get("StressSlip2", {})
    fee = rows.get("StressFee240", {})
    combined = rows.get("StressSlip2Fee240", {})
    current = rows.get("Current30D", {})
    return {
        "window_ge_120_min": True,
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_ge_1_35": float(full.get("adj_pf") or 0.0) >= 1.35,
        "max_dd_pct_15": RL.max_drawdown_within_budget(float(full.get("adj_dd") or 0.0)),
        "full_trades_ge_250": int(full.get("trade_count") or 0) >= 250,
        "full_active_days_ge_25pct": float(full.get("active_days_pct") or 0.0) >= 25.0,
        "is_net_positive": float(is_row.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_ge_1_25": float(oos.get("adj_pf") or 0.0) >= 1.25,
        "stress_slip2_positive": float(slip.get("adj_net") or 0.0) > 0.0,
        "stress_fee240_positive": float(fee.get("adj_net") or 0.0) > 0.0,
        "stress_combined_positive": float(combined.get("adj_net") or 0.0) > 0.0,
        "current30_positive": float(current.get("adj_net") or 0.0) > 0.0,
        "current30_trades_ge_10": int(current.get("trade_count") or 0) >= 10,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--smoke-days", type=int, default=60)
    args = ap.parse_args()

    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mnq_2h_daily_search_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    variants = build_variants(args.limit or None)
    smoke_from, smoke_to = current_window(args.smoke_days)
    print(f"bundle: {bundle}")
    print(f"variants: {len(variants)} smoke={smoke_from}..{smoke_to}")

    smoke_subs = [
        submit_job(v, "Smoke", smoke_from, smoke_to, 1, RL.fee_for(ROOT))
        for v in variants
    ]
    (bundle / "smoke_submissions.json").write_text(json.dumps(smoke_subs, indent=2), encoding="utf-8")
    wait_for_jobs([s.get("job_id") for s in smoke_subs if s.get("job_id")])
    smoke_rows = [row_from_submission(s) for s in smoke_subs]
    smoke_rows.sort(key=score_smoke, reverse=True)
    with (bundle / "smoke_rows.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(smoke_rows)
    (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2), encoding="utf-8")

    selected_names = [r["variant"] for r in smoke_rows if score_smoke(r) > -1e8][:args.top]
    by_name = {v.name: v for v in variants}
    selected = [by_name[n] for n in selected_names]
    print("selected:")
    for r in smoke_rows[:args.top]:
        print(f"  {r['variant']}: trades={r['trade_count']} active={r['active_days_pct']} net={r['adj_net']:.2f} pf={r['adj_pf']:.2f} dd={r['adj_dd']:.2f}")

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
    with (bundle / "validation_rows.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(val_rows)
    (bundle / "validation_rows.json").write_text(json.dumps(val_rows, indent=2), encoding="utf-8")

    decisions: List[Dict[str, Any]] = []
    for variant in selected:
        rows = {r["stage"]: r for r in val_rows if r["variant"] == variant.name}
        gate_values = gates(rows)
        failed = [k for k, v in gate_values.items() if not v]
        decisions.append({
            "variant": variant.name,
            "decision": "paper_ready_candidate" if not failed else "research_only",
            "ready_pass": not failed,
            "failed_gates": failed,
            "gates": gate_values,
            "locked_parameters": variant.params,
            "rows": rows,
        })
    decisions.sort(key=lambda d: (
        1 if d["ready_pass"] else 0,
        float((d.get("rows") or {}).get("Full", {}).get("adj_net") or 0.0),
    ), reverse=True)
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    summary = {
        "bundle": str(bundle),
        "class_name": CLASS_NAME,
        "instrument": INSTRUMENT,
        "minimum_window_minutes": 120,
        "selected": selected_names,
        "ready": [d["variant"] for d in decisions if d["ready_pass"]],
        "best": decisions[0] if decisions else None,
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("decisions:")
    for d in decisions:
        full = d.get("rows", {}).get("Full", {})
        cur = d.get("rows", {}).get("Current30D", {})
        print(f"  {d['variant']}: {d['decision']} full_net={full.get('adj_net')} pf={full.get('adj_pf')} trades={full.get('trade_count')} current30={cur.get('adj_net')} failed={','.join(d['failed_gates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
