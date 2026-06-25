"""Research MNQ CELL-017 late-window SessionEdge ORB candidates.

Second CELL-017 hypothesis after CompressionBreakout failed promotion gates:
build a small local opening range inside the late free window, then trade either
range continuation or failed-range reversal.  This keeps the run away from the
previously rejected VwapPullbackScalp / EmaImpulseScalp / late VWAP wrapper.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import run_mnq_cell017_late_compression as BASE  # noqa: E402


CELL_ID = "CELL-017"
DISPLAY_NAME = "Late ORB MNQ 1m v1 c017"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def base_params() -> Dict[str, Any]:
    params = BASE.base_params()
    params.update({
        "SetupMode": "OrbContinuation",
        "MinVolumeFactor": 0.0,
        "MinAdx": 0.0,
        "MoveToBreakevenAtR": 0.0,
        "TrailAfterR": 1.0,
        "EntryOffsetTicks": 0,
        "OrbDurationMinutes": 5,
        "OrbBreakoutBuffer": 0,
        "OrbFailedLookback": 3,
        "CompressionLookback": 30,
        "CompressionAtrPct": 0.30,
    })
    return params


def make_variant(
    *,
    mode: str,
    start: int,
    end: int,
    flat: int,
    direction: str,
    orb_minutes: int,
    rr: float,
    stop_min: int,
    stop_max: int,
    failed_lookback: int,
) -> BASE.Variant:
    params = base_params()
    params.update({
        "SetupMode": mode,
        "TradeStartTime": start,
        "TradeEndTime": end,
        "ForceFlatTime": flat,
        "EnableLong": direction in {"long", "both"},
        "EnableShort": direction in {"short", "both"},
        "OrbDurationMinutes": orb_minutes,
        "OrbFailedLookback": failed_lookback,
        "RewardRiskRatio": rr,
        "MinStopTicks": stop_min,
        "MaxStopTicks": stop_max,
    })
    mode_label = "orbcont" if mode == "OrbContinuation" else "orbfail"
    rr_label = str(rr).replace(".", "")
    name = (
        f"{mode_label}_{direction}_{start:04d}_{end:04d}"
        f"_or{orb_minutes}_fl{failed_lookback}_s{stop_min}_{stop_max}_rr{rr_label}"
    )
    return BASE.Variant(name=name, timeframe=1, params=params)


def build_variants(limit: Optional[int] = None) -> List[BASE.Variant]:
    windows = [
        (1246, 1325, 1330),
        (1246, 1315, 1330),
        (1300, 1325, 1330),
    ]
    variants: List[BASE.Variant] = []
    for start, end, flat in windows:
        for mode in ("OrbContinuation", "FailedOrbReversal"):
            for direction in ("both", "long", "short"):
                for orb_minutes in (3, 5, 10):
                    for rr in (1.25, 1.75, 2.50):
                        for stop_min, stop_max in ((4, 10), (6, 14)):
                            failed_lookback = 5 if mode == "FailedOrbReversal" else 3
                            variants.append(make_variant(
                                mode=mode,
                                start=start,
                                end=end,
                                flat=flat,
                                direction=direction,
                                orb_minutes=orb_minutes,
                                rr=rr,
                                stop_min=stop_min,
                                stop_max=stop_max,
                                failed_lookback=failed_lookback,
                            ))
    if limit is not None:
        variants = variants[:limit]
    return variants


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

    bundle = RL.DATA / "research" / f"mnq_cell017_late_orb_sessionedge_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)
    print(f"carrier: {BASE.CARRIER_CLASS} instrument={BASE.CURRENT_CONTRACT} session={BASE.SESSION_TEMPLATE}", flush=True)
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

    smoke_rows = [BASE.summarize(s) for s in smoke_submissions]
    smoke_rows.sort(key=BASE.score, reverse=True)
    (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    BASE.write_csv(bundle / "smoke_rows.csv", smoke_rows)

    selected = [r["variant"] for r in smoke_rows if BASE.score(r) > -499000.0][:args.top]
    print("top smoke rows:", flush=True)
    for row in smoke_rows[:12]:
        print(
            f"  {row['variant']}: mode={row.get('setup_mode')} trades={row['trade_count']} "
            f"net={float(row.get('adj_net') or 0.0):.2f} pf={float(row.get('adj_pf') or 0.0):.2f} "
            f"dd={float(row.get('adj_dd') or 0.0):.2f} same_bar={float(row.get('same_bar_pct') or 0.0):.1f}%",
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

    validation_rows = [BASE.summarize(s) for s in validation_submissions]
    (bundle / "validation_rows.json").write_text(
        json.dumps(validation_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    BASE.write_csv(bundle / "validation_rows.csv", validation_rows)

    decisions: List[Dict[str, Any]] = []
    for name in selected:
        rows_by_stage = {str(r.get("stage")): r for r in validation_rows if r.get("variant") == name}
        decision = BASE.gate_decision(rows_by_stage)
        decision.update({
            "variant": name,
            "class_name": BASE.CARRIER_CLASS,
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
        "instrument": BASE.CURRENT_CONTRACT,
        "session_template": BASE.SESSION_TEMPLATE,
        "carrier_class": BASE.CARRIER_CLASS,
        "hypothesis": "late local OR continuation / failed OR reversal after C014 entry cutoff",
        "excluded_families": ["VwapPullbackScalp", "EmaImpulseScalp", "NTAMnqLateVwapLongScalpC017"],
        "free_windows_pt": ["12:46-13:25", "12:46-13:15", "13:00-13:25"],
        "flat_time_pt": "13:30",
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
