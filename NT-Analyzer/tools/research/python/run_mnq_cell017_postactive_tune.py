"""Targeted post-active tuning for reopened MNQ CELL-017.

The broad free-window sweep found a near-candidate in 12:46-13:25 PT:
Full/OOS/frequency were positive, but combined stress failed after the account
risk budget stopped accepting trades.  This runner searches nearby windows and
geometry with smoke already run under combined costs (slip=2, fee=2.40), then
validates the best variants with the same gates as the broad sweep.
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
import run_mnq_cell017_free_window_sweep as FREE  # noqa: E402


BUNDLE_PREFIX = "mnq_cell017_postactive_tune"
CELL_ID = "CELL-017"
DISPLAY_NAME = "Scalping Post-Active MNQ 1m v1 c017"
PROFILE_ID = "mnq_postactive_allmodules_1m_c017_ready_v1"

CSV_FIELDS = FREE.CSV_FIELDS + [
    "risk_pct",
    "window_group",
    "free_window",
]


def build_variants(limit: Optional[int] = None) -> List[FREE.BASE.Variant]:
    windows = [
        ("post_active", 1246, 1325, 1330, 1245),
        ("post_active", 1246, 1315, 1330, 1245),
        ("post_active", 1246, 1305, 1330, 1245),
        ("post_active", 1250, 1325, 1330, 1245),
        ("post_active", 1255, 1325, 1330, 1255),
        ("post_active", 1301, 1325, 1330, 1300),
    ]
    directions = ["both", "long"]
    rrs = [3.5, 4.0, 5.0, 6.0]
    stops = [(4, 10), (6, 12), (8, 16)]
    volumes = [0.5, 0.7, 1.0]
    risk_pcts = [0.35, 0.50, 0.75]
    variants: List[FREE.BASE.Variant] = []

    for group, start, end, flat, orb_start in windows:
        if not FREE.is_free_window(start, end):
            raise AssertionError(f"window {start:04d}-{end:04d} overlaps occupied portfolio blocks")
        window_label = f"{start:04d}_{end:04d}"
        for direction in directions:
            for rr in rrs:
                for min_stop, max_stop in stops:
                    for vol in volumes:
                        for risk_pct in risk_pcts:
                            params = FREE.BASE.base_params()
                            params.update(FREE.BASE.module_params("all", direction))
                            params.update({
                                "UseSetupModeFilter": False,
                                "TradeStartTime": start,
                                "TradeEndTime": end,
                                "ForceFlatTime": flat,
                                "OrbStartTime": orb_start,
                                "RewardRiskRatio": rr,
                                "MinStopTicks": min_stop,
                                "MaxStopTicks": max_stop,
                                "MinVolumeFactor": vol,
                                "RiskPerTradePct": risk_pct,
                                "PullbackLookback": 3,
                                "NewsBlackoutTimes": "",
                            })
                            rr_label = str(rr).replace(".", "")
                            vol_label = str(vol).replace(".", "")
                            risk_label = str(risk_pct).replace(".", "")
                            name = (
                                f"all_{direction}_{window_label}_s{min_stop}_{max_stop}_"
                                f"rr{rr_label}_v{vol_label}_r{risk_label}"
                            )
                            variant = FREE.BASE.Variant(
                                name=name,
                                params=params,
                                window=f"{FREE.fmt_hhmm(start)}-{FREE.fmt_hhmm(end)}",
                                module="all",
                                direction=direction,
                                rr=rr,
                                min_stop=min_stop,
                                max_stop=max_stop,
                                min_volume=vol,
                                setup_mode="AllModules",
                                orb_start=orb_start,
                            )
                            object.__setattr__(variant, "risk_pct", risk_pct)
                            object.__setattr__(variant, "window_group", group)
                            object.__setattr__(variant, "free_window", True)
                            variants.append(variant)
                            if limit and len(variants) >= limit:
                                return variants
    return variants


def row_from_submission(sub: Dict[str, Any]) -> Dict[str, Any]:
    row = FREE.row_from_submission(sub)
    meta = sub.get("meta") or {}
    row["risk_pct"] = meta.get("risk_pct")
    row["window_group"] = meta.get("window_group") or ""
    row["free_window"] = bool(meta.get("free_window", False))
    return row


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def score_combined_smoke(row: Dict[str, Any]) -> float:
    trades = int(row.get("trade_count") or 0)
    tpd = float(row.get("trades_per_day") or 0.0)
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    avg = float(row.get("avg_trade") or 0.0)
    if trades < 40 or tpd < 2.0 or net <= 0.0 or pf <= 1.0:
        return -1e9
    return net + min(tpd, 8.0) * 200.0 + min(pf, 3.0) * 120.0 + avg * 40.0 - dd * 0.25


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--smoke-days", type=int, default=60)
    args = ap.parse_args(argv)

    bundle = RL.PROJECT_ROOT / "data" / "research" / f"{BUNDLE_PREFIX}_{FREE.BASE.utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    variants = build_variants(args.limit or None)
    smoke_from, smoke_to = FREE.BASE.current_window(args.smoke_days)
    print(f"bundle: {bundle}", flush=True)
    print(f"variants: {len(variants)} combined_smoke={smoke_from}..{smoke_to}", flush=True)

    smoke_subs = [
        FREE.BASE.submit_job(v, "CombinedSmoke60D", smoke_from, smoke_to, 2, 2.40)
        for v in variants
    ]
    (bundle / "smoke_submissions.json").write_text(json.dumps(smoke_subs, indent=2), encoding="utf-8")
    FREE.BASE.wait_for_jobs([s.get("job_id") for s in smoke_subs if s.get("job_id")])
    smoke_rows = [row_from_submission(s) for s in smoke_subs]
    smoke_rows.sort(key=score_combined_smoke, reverse=True)
    write_csv(bundle / "smoke_rows.csv", smoke_rows)
    (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2), encoding="utf-8")

    selected_names = [r["variant"] for r in smoke_rows if score_combined_smoke(r) > -1e8][:args.top]
    by_name = {v.name: v for v in variants}
    selected = [by_name[name] for name in selected_names]
    print("selected:", flush=True)
    for row in smoke_rows[:args.top]:
        print(
            f"  {row['variant']}: window={row['window']} rr={row['rr']} "
            f"risk={row.get('risk_pct')} trades={row['trade_count']} "
            f"tpd={float(row['trades_per_day']):.2f} net={float(row['adj_net']):.2f} "
            f"pf={float(row['adj_pf']):.2f} dd={float(row['adj_dd']):.2f}",
            flush=True,
        )

    cur_from, cur_to = FREE.BASE.current_window(30)
    val_plan = [
        ("Full", FREE.BASE.FULL[1], FREE.BASE.FULL[2], 1, RL.fee_for(FREE.BASE.ROOT)),
        ("IS", FREE.BASE.IS[1], FREE.BASE.IS[2], 1, RL.fee_for(FREE.BASE.ROOT)),
        ("OOS", FREE.BASE.OOS[1], FREE.BASE.OOS[2], 1, RL.fee_for(FREE.BASE.ROOT)),
        ("StressSlip2", FREE.BASE.FULL[1], FREE.BASE.FULL[2], 2, RL.fee_for(FREE.BASE.ROOT)),
        ("StressFee240", FREE.BASE.FULL[1], FREE.BASE.FULL[2], 1, 2.40),
        ("StressSlip2Fee240", FREE.BASE.FULL[1], FREE.BASE.FULL[2], 2, 2.40),
        ("Current30D", cur_from, cur_to, 1, RL.fee_for(FREE.BASE.ROOT)),
    ]
    val_subs: List[Dict[str, Any]] = []
    for variant in selected:
        for stage, from_utc, to_utc, slip, fee in val_plan:
            val_subs.append(FREE.BASE.submit_job(variant, stage, from_utc, to_utc, slip, fee))
    (bundle / "validation_submissions.json").write_text(json.dumps(val_subs, indent=2), encoding="utf-8")
    FREE.BASE.wait_for_jobs([s.get("job_id") for s in val_subs if s.get("job_id")])
    val_rows = [row_from_submission(s) for s in val_subs]
    write_csv(bundle / "validation_rows.csv", val_rows)
    (bundle / "validation_rows.json").write_text(json.dumps(val_rows, indent=2), encoding="utf-8")

    decisions: List[Dict[str, Any]] = []
    for variant in selected:
        rows = {r["stage"]: r for r in val_rows if r["variant"] == variant.name}
        gate_values = FREE.gates(rows)
        failed = [key for key, value in gate_values.items() if not value]
        decisions.append({
            "variant": variant.name,
            "profile_id": PROFILE_ID,
            "display_name": DISPLAY_NAME,
            "cell_id": CELL_ID,
            "decision": "paper_ready_candidate" if not failed else "research_only",
            "ready_pass": not failed,
            "failed_gates": failed,
            "gates": gate_values,
            "locked_parameters": variant.params,
            "rows": rows,
        })
    decisions.sort(key=lambda d: (
        1 if d["ready_pass"] else 0,
        float((d.get("rows") or {}).get("StressSlip2Fee240", {}).get("adj_net") or -math.inf),
        float((d.get("rows") or {}).get("Full", {}).get("adj_net") or -math.inf),
    ), reverse=True)
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    summary = {
        "bundle": str(bundle),
        "cell_id": CELL_ID,
        "profile_id": PROFILE_ID,
        "display_name": DISPLAY_NAME,
        "class_name": FREE.BASE.CLASS_NAME,
        "instrument": FREE.BASE.INSTRUMENT,
        "session_template": FREE.BASE.SESSION_TEMPLATE,
        "selected": selected_names,
        "ready": [d["variant"] for d in decisions if d["ready_pass"]],
        "best": decisions[0] if decisions else None,
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("decisions:", flush=True)
    for decision in decisions:
        rows = decision.get("rows") or {}
        full = rows.get("Full", {})
        oos = rows.get("OOS", {})
        stress = rows.get("StressSlip2Fee240", {})
        current = rows.get("Current30D", {})
        print(
            f"  {decision['variant']}: {decision['decision']} window={full.get('window')} "
            f"risk={(decision.get('locked_parameters') or {}).get('RiskPerTradePct')} "
            f"full_net={full.get('adj_net')} full_tpd={full.get('trades_per_day')} "
            f"oos={oos.get('adj_net')} stress={stress.get('adj_net')} "
            f"current30={current.get('adj_net')} failed={','.join(decision['failed_gates'])}",
            flush=True,
        )
    return 0 if summary["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
