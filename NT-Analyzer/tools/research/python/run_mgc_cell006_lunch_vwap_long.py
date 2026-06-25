"""CELL-006 pivot: MNQ-style narrow lunch VWAP long scalp on SessionEdge carrier."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import run_mgc_cell006_late_session as R  # noqa: E402


R.CLASS_NAME = "VWAPPullbackMGC5mV1"
R.DISPLAY_NAME = "MGC Late Lunch VWAP Long 1m c006"


_ORIG_BASE = R.base_params


def base_params():
    params = _ORIG_BASE()
    params.update({
        "SetupMode": "VwapPullback",
        "EnableLong": True,
        "EnableShort": False,
        "EmaFastPeriod": 9,
        "EmaSlowPeriod": 50,
        "PullbackLookback": 4,
        "MinAdx": 0.0,
        "MinVolumeFactor": 0.7,
        "AtrStopMult": 0.30,
        "MoveToBreakevenAtR": 0.7,
        "TrailAfterR": 1.0,
        "EntryOffsetTicks": 0,
        "MaxTradesPerDay": 6,
        "MaxConsecutiveLosses": 3,
    })
    return params


def full_variants() -> List[R.Variant]:
    out: List[R.Variant] = []
    for start, end in ((1145, 1315), (1200, 1310), (1215, 1300)):
        for stop, rr in ((6, 1.75), (8, 2.0), (10, 2.0)):
            out.append(R.make_variant(
                f"lunch_vwap_long_{start}_{end}_s{stop}_rr{str(rr).replace('.', '')}",
                timeframe=1,
                direction="long",
                TradeStartTime=start,
                TradeEndTime=end,
                MinStopTicks=stop,
                MaxStopTicks=stop,
                RewardRiskRatio=rr,
            ))
    return out


# patched only for make_variant via module attribute at runtime
R.base_params = base_params  # noqa: assigned for make_variant
R.full_variants = full_variants  # noqa: assigned for make_variant


def main(argv: List[str]) -> int:
    top_n = 3
    if "--top" in argv:
        top_n = int(argv[argv.index("--top") + 1])

    bundle = R.RL.DATA / "research" / f"mgc_cell006_lunch_vwap_long_{R.utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    variants = full_variants()
    by_name = {v.name: v for v in variants}

    smoke_from, smoke_to = R.current_window(days=60)
    smoke_submissions = [
        R.submit_job(variant=v, stage="Smoke60D", from_utc=smoke_from, to_utc=smoke_to)
        for v in variants
    ]
    (bundle / "smoke_submissions.json").write_text(
        json.dumps(smoke_submissions, indent=2, ensure_ascii=False), encoding="utf-8")
    R.wait_for_jobs([s.get("job_id") for s in smoke_submissions if s.get("job_id")])
    smoke_rows = [R.summarize(s) for s in smoke_submissions]
    smoke_rows.sort(key=R.score, reverse=True)
    (bundle / "smoke_rows.json").write_text(
        json.dumps(smoke_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    R.write_csv(bundle / "smoke_rows.csv", smoke_rows)

    selected = [r["variant"] for r in smoke_rows if R.score(r) > -499000.0][:top_n]
    if not selected and smoke_rows:
        selected = [smoke_rows[0]["variant"]]
    print("top smoke:", flush=True)
    for row in smoke_rows[:8]:
        print(
            f"  {row['variant']}: net={float(row.get('adj_net') or 0):.2f} "
            f"pf={float(row.get('adj_pf') or 0):.2f} trades={row.get('trade_count')}",
            flush=True,
        )

    stage_defs = [
        ("Full", R.FULL[1], R.FULL[2], 1, R.RL.fee_for(R.ROOT)),
        ("IS", R.IS[1], R.IS[2], 1, R.RL.fee_for(R.ROOT)),
        ("OOS", R.OOS[1], R.OOS[2], 1, R.RL.fee_for(R.ROOT)),
        ("StressSlip2", R.FULL[1], R.FULL[2], 2, R.RL.fee_for(R.ROOT)),
        ("StressFee240", R.FULL[1], R.FULL[2], 1, R.RL.fee_stress(R.ROOT)),
        ("StressSlip2Fee240", R.FULL[1], R.FULL[2], 2, R.RL.fee_stress(R.ROOT)),
        ("Current30D", *R.current_window(days=30), 1, R.RL.fee_for(R.ROOT)),
    ]
    validation_submissions = []
    for name in selected:
        variant = by_name[name]
        for stage, from_utc, to_utc, slip, fee in stage_defs:
            validation_submissions.append(R.submit_job(
                variant=variant, stage=stage, from_utc=from_utc, to_utc=to_utc,
                slippage_ticks=slip, fee=fee,
            ))
    (bundle / "validation_submissions.json").write_text(
        json.dumps(validation_submissions, indent=2, ensure_ascii=False), encoding="utf-8")
    R.wait_for_jobs([s.get("job_id") for s in validation_submissions if s.get("job_id")])
    validation_rows = [R.summarize(s) for s in validation_submissions]
    (bundle / "validation_rows.json").write_text(
        json.dumps(validation_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    R.write_csv(bundle / "validation_rows.csv", validation_rows)

    decisions = []
    for name in selected:
        rows_by_stage = {str(r.get("stage")): r for r in validation_rows if r.get("variant") == name}
        decision = R.gate_decision(rows_by_stage)
        decision.update({
            "variant": name,
            "locked_parameters": by_name[name].params,
            "timeframe": by_name[name].timeframe,
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
    summary = {
        "bundle": str(bundle),
        "hypothesis": "MNQ C017 analog: narrow lunch VWAP long pullback, fast EMA 9/50",
        "class_name": R.CLASS_NAME,
        "decisions": decisions,
        "selected": selected,
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")
    for d in decisions:
        full = (d.get("rows") or {}).get("Full", {})
        print(
            f"  {d['variant']}: {d['decision']} full_net={float(full.get('adj_net') or 0):.2f} "
            f"pf={float(full.get('adj_pf') or 0):.2f}",
            flush=True,
        )
    return 0 if any(d.get("ready_pass") for d in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
