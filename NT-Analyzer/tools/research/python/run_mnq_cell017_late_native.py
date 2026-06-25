"""MNQ-native late-window research for CELL-017.

Equivalent replacement for the older run_mnq_cell017_late_session.py sweep, but
without rejected/forbidden late-C017 families:

- no VwapPullbackScalp
- no EmaImpulseScalp
- no NTAMnqLateVwapLongScalpC017 wrapper

Uses compiled MNQ-native carriers only:

- NTAMicroMnqScalpPilot: OrbContinuationScalp, OrbRetestScalp,
  FailedOrbReversalScalp
- NTAMnqLiquiditySweepReversalC015: Sweep, OrbFailure, Momentum,
  OpenPressureStopShort
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import run_mnq_cell017_late_session as BASE  # noqa: E402


CELL_ID = "CELL-017"
DISPLAY_NAME = "MNQ Late Native Sweep 1m v1 c017"

CSV_FIELDS = BASE.CSV_FIELDS + [
    "same_bar_count",
    "same_bar_pct",
    "module_family",
]


def make_scalp_variant(
    *,
    setup_mode: str,
    family: str,
    start: int,
    end: int,
    flat: int,
    direction: str,
    rr: float,
    stop_min: int,
    stop_max: int,
    volume: float,
    orb_duration: int,
    orb_retest_bars: int,
    orb_failed_lookback: int,
) -> BASE.Variant:
    rr_label = str(rr).replace(".", "")
    name = (
        f"{family}_{direction}_{start:04d}_{end:04d}"
        f"_or{orb_duration}_rt{orb_retest_bars}_fl{orb_failed_lookback}"
        f"_s{stop_min}_{stop_max}_rr{rr_label}_v{str(volume).replace('.', '')}"
    )
    return BASE.make_scalp(
        name,
        start=start,
        end=end,
        flat=flat,
        setup_mode=setup_mode,
        direction=direction,
        overrides={
            "RewardRiskRatio": rr,
            "MinStopTicks": stop_min,
            "MaxStopTicks": stop_max,
            "MinVolumeFactor": volume,
            "OrbDurationMinutes": orb_duration,
            "OrbRetestBars": orb_retest_bars,
            "OrbFailedLookback": orb_failed_lookback,
            "MoveToBreakevenAtR": 0.0,
            "TrailAfterR": 1.0,
            "UseTimeStop": True,
            "TimeStopBars": 3,
            "MinProgressR": 0.20,
            "EntryOffsetTicks": 0,
            "MaxTradesPerDay": 16,
            "HardMaxTradesPerDay": 20,
        },
    )


def make_sweep_variant(
    *,
    signal_mode: str,
    family: str,
    start: int,
    end: int,
    flat: int,
    direction: str,
    rr: float,
    stop_min: int,
    stop_max: int,
    lookback: int,
    momentum_lookback: int,
    fade_sweeps: bool,
    open_pressure_score: int,
    opening_range_minutes: int,
) -> BASE.Variant:
    rr_label = str(rr).replace(".", "")
    fade_label = "fade" if fade_sweeps else "break"
    name = (
        f"{family}_{direction}_{start:04d}_{end:04d}"
        f"_lb{lookback}_ml{momentum_lookback}_{fade_label}"
        f"_or{opening_range_minutes}_s{stop_min}_{stop_max}_rr{rr_label}"
    )
    return BASE.make_sweep(
        name,
        start=start,
        end=end,
        flat=flat,
        direction=direction,
        signal_mode=signal_mode,
        overrides={
            "RewardRiskRatio": rr,
            "SweepLookbackBars": lookback,
            "MomentumLookbackBars": momentum_lookback,
            "FadeSweeps": fade_sweeps,
            "OpenPressureMinScore": open_pressure_score,
            "OpeningRangeStartTime": start,
            "OpeningRangeMinutes": opening_range_minutes,
            "MinStopTicks": stop_min,
            "MaxStopTicks": stop_max,
            "MinTargetTicks": max(6, int(round(stop_min * rr))),
            "RequireCloseAgainstSweep": True,
            "RequireMomentumBreak": signal_mode == "Momentum",
            "MoveToBreakevenAtR": 0.0,
            "UseTrailingStop": False,
            "UseTimeStop": True,
            "TimeStopBars": 3,
            "MinProgressR": 0.20,
            "EntryOffsetTicks": 0,
            "MaxTradesPerDay": 16,
            "HardMaxTradesPerDay": 20,
        },
    )


def build_variants(limit: Optional[int] = None) -> List[BASE.Variant]:
    windows = [
        (1246, 1325, 1330),
        (1246, 1315, 1330),
        (1255, 1325, 1330),
        (1300, 1325, 1330),
    ]
    variants: List[BASE.Variant] = []

    for start, end, flat in windows:
        for direction in ("short", "both", "long"):
            for rr in (1.25, 1.75, 2.50):
                for stop_min, stop_max in ((4, 10), (6, 12)):
                    variants.append(make_scalp_variant(
                        setup_mode="OrbContinuationScalp",
                        family="mnqpilot_orbcont",
                        start=start,
                        end=end,
                        flat=flat,
                        direction=direction,
                        rr=rr,
                        stop_min=stop_min,
                        stop_max=stop_max,
                        volume=0.7,
                        orb_duration=3,
                        orb_retest_bars=5,
                        orb_failed_lookback=3,
                    ))

        for direction in ("short", "both"):
            for rr in (1.25, 1.75):
                for stop_min, stop_max in ((4, 10), (6, 12)):
                    variants.append(make_scalp_variant(
                        setup_mode="OrbRetestScalp",
                        family="mnqpilot_orbretest",
                        start=start,
                        end=end,
                        flat=flat,
                        direction=direction,
                        rr=rr,
                        stop_min=stop_min,
                        stop_max=stop_max,
                        volume=0.7,
                        orb_duration=3,
                        orb_retest_bars=5,
                        orb_failed_lookback=3,
                    ))

        for direction in ("both", "short", "long"):
            for rr in (1.25, 1.75, 2.00):
                for stop_min, stop_max in ((4, 10), (6, 14)):
                    for volume in (0.0, 0.7):
                        variants.append(make_scalp_variant(
                            setup_mode="FailedOrbReversalScalp",
                            family="mnqpilot_failrev",
                            start=start,
                            end=end,
                            flat=flat,
                            direction=direction,
                            rr=rr,
                            stop_min=stop_min,
                            stop_max=stop_max,
                            volume=volume,
                            orb_duration=3,
                            orb_retest_bars=5,
                            orb_failed_lookback=4,
                        ))

        for direction in ("both", "short", "long"):
            for rr in (1.50, 2.00):
                for lookback in (3, 5, 8):
                    for fade_sweeps in (True, False):
                        variants.append(make_sweep_variant(
                            signal_mode="Sweep",
                            family="c015_sweep",
                            start=start,
                            end=end,
                            flat=flat,
                            direction=direction,
                            rr=rr,
                            stop_min=4,
                            stop_max=10,
                            lookback=lookback,
                            momentum_lookback=1,
                            fade_sweeps=fade_sweeps,
                            open_pressure_score=1,
                            opening_range_minutes=3,
                        ))

        for direction in ("both", "short", "long"):
            for rr in (1.50, 2.50):
                for opening_range_minutes in (3, 5, 10):
                    variants.append(make_sweep_variant(
                        signal_mode="OrbFailure",
                        family="c015_orbfailure",
                        start=start,
                        end=end,
                        flat=flat,
                        direction=direction,
                        rr=rr,
                        stop_min=4,
                        stop_max=10,
                        lookback=3,
                        momentum_lookback=1,
                        fade_sweeps=True,
                        open_pressure_score=1,
                        opening_range_minutes=opening_range_minutes,
                    ))

        for direction in ("short", "long", "both"):
            for rr in (1.25, 1.75):
                for momentum_lookback in (1, 2):
                    variants.append(make_sweep_variant(
                        signal_mode="Momentum",
                        family="c015_momentum",
                        start=start,
                        end=end,
                        flat=flat,
                        direction=direction,
                        rr=rr,
                        stop_min=5,
                        stop_max=12,
                        lookback=3,
                        momentum_lookback=momentum_lookback,
                        fade_sweeps=True,
                        open_pressure_score=1,
                        opening_range_minutes=3,
                    ))

        for rr in (2.00, 3.00, 4.00):
            for lookback in (3, 5):
                for score in (1, 2):
                    variants.append(make_sweep_variant(
                        signal_mode="OpenPressureStopShort",
                        family="c015_openpressure",
                        start=start,
                        end=end,
                        flat=flat,
                        direction="short",
                        rr=rr,
                        stop_min=4,
                        stop_max=10,
                        lookback=lookback,
                        momentum_lookback=1,
                        fade_sweeps=True,
                        open_pressure_score=score,
                        opening_range_minutes=3,
                    ))

    if limit is not None:
        variants = variants[:limit]
    return variants


def module_family(name: str) -> str:
    parts = name.split("_")
    if len(parts) >= 2 and parts[0] == "mnqpilot":
        return "_".join(parts[:2])
    if len(parts) >= 2 and parts[0] == "c015":
        return "_".join(parts[:2])
    return parts[0] if parts else ""


def same_bar_count(trades: List[Dict[str, Any]]) -> int:
    total = 0
    for trade in trades:
        entry = str(trade.get("entry_time_utc") or "")
        exit_ = str(trade.get("exit_time_utc") or "")
        if entry and exit_ and entry == exit_:
            total += 1
    return total


def summarize(submission: Dict[str, Any]) -> Dict[str, Any]:
    row = BASE.summarize(submission)
    row["module_family"] = module_family(str(row.get("variant") or ""))
    job_id = str(submission.get("job_id") or "")
    report = RL.read_job_report(job_id) if job_id else None
    trades = BASE.trades_from_report(report) if report else []
    same = same_bar_count(trades)
    count = int(row.get("trade_count") or 0)
    row["same_bar_count"] = same
    row["same_bar_pct"] = round((same / count * 100.0) if count else 0.0, 4)
    return row


def score(row: Dict[str, Any]) -> float:
    trades = float(row.get("trade_count") or 0.0)
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    avg = float(row.get("avg_trade") or 0.0)
    same_pct = float(row.get("same_bar_pct") or 0.0)
    if trades <= 0:
        return -999999.0
    if net <= 0.0 or pf < 1.05:
        return -500000.0 + net - dd
    return net + min(pf, 3.0) * 150.0 + min(trades, 250.0) * 0.8 + avg * 20.0 - dd * 0.45 - same_pct * 1.5


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
    parser.add_argument("--top", type=int, default=12, help="number of smoke winners to validate")
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

    bundle = RL.DATA / "research" / f"mnq_cell017_late_native_{BASE.utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)
    print(f"instrument={BASE.CURRENT_CONTRACT} session={BASE.SESSION_TEMPLATE}", flush=True)
    print(f"smoke variants: {len(variants)}", flush=True)

    smoke_from, smoke_to = BASE.current_window(days=60)
    smoke_submissions = [
        BASE.submit_job(variant=v, stage="Smoke60D", from_utc=smoke_from, to_utc=smoke_to)
        for v in variants
    ]
    (bundle / "smoke_submissions.json").write_text(
        json.dumps(smoke_submissions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    BASE.wait_for_jobs([s.get("job_id") for s in smoke_submissions if s.get("job_id")])

    smoke_rows = [summarize(s) for s in smoke_submissions]
    smoke_rows.sort(key=score, reverse=True)
    (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(bundle / "smoke_rows.csv", smoke_rows)

    selected = [r["variant"] for r in smoke_rows if score(r) > -499000.0][:args.top]
    print("top smoke rows:", flush=True)
    for row in smoke_rows[:16]:
        print(
            f"  {row['variant']}: class={row['class_name']} family={row.get('module_family')} "
            f"trades={row['trade_count']} net={float(row.get('adj_net') or 0.0):.2f} "
            f"pf={float(row.get('adj_pf') or 0.0):.2f} dd={float(row.get('adj_dd') or 0.0):.2f} "
            f"same_bar={float(row.get('same_bar_pct') or 0.0):.1f}%",
            flush=True,
        )
    print(f"selected for validation: {selected}", flush=True)

    stage_defs = [
        ("Full", BASE.FULL[1], BASE.FULL[2], 1, RL.fee_for(BASE.ROOT)),
        ("IS", BASE.IS[1], BASE.IS[2], 1, RL.fee_for(BASE.ROOT)),
        ("OOS", BASE.OOS[1], BASE.OOS[2], 1, RL.fee_for(BASE.ROOT)),
        ("StressSlip2", BASE.FULL[1], BASE.FULL[2], 2, RL.fee_for(BASE.ROOT)),
        ("StressFee240", BASE.FULL[1], BASE.FULL[2], 1, RL.fee_stress(BASE.ROOT)),
        ("StressSlip2Fee240", BASE.FULL[1], BASE.FULL[2], 2, RL.fee_stress(BASE.ROOT)),
        ("Current30D", *BASE.current_window(days=30), 1, RL.fee_for(BASE.ROOT)),
    ]

    validation_submissions: List[Dict[str, Any]] = []
    for name in selected:
        variant = by_name[name]
        for stage, from_utc, to_utc, slip, fee in stage_defs:
            validation_submissions.append(BASE.submit_job(
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
    BASE.wait_for_jobs([s.get("job_id") for s in validation_submissions if s.get("job_id")])

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
            "class_name": by_name[name].class_name,
            "timeframe": by_name[name].timeframe,
            "module_family": module_family(name),
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
        "instrument": BASE.CURRENT_CONTRACT,
        "session_template": BASE.SESSION_TEMPLATE,
        "hypothesis": "MNQ-native late ORB/retest/failed-breakout plus C015 sweep/orb-failure/momentum/open-pressure",
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
        combined = (d.get("rows") or {}).get("StressSlip2Fee240", {})
        print(
            f"  {d['variant']}: {d['decision']} full_net={float(full.get('adj_net') or 0.0):.2f} "
            f"full_pf={float(full.get('adj_pf') or 0.0):.2f} full_trades={int(full.get('trade_count') or 0)} "
            f"oos_pf={float(oos.get('adj_pf') or 0.0):.2f} combined={float(combined.get('adj_net') or 0.0):.2f} "
            f"current30={float(cur.get('adj_net') or 0.0):.2f} failed={','.join(d.get('failed_gates') or [])}",
            flush=True,
        )
    return 0 if any(d.get("ready_pass") for d in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
