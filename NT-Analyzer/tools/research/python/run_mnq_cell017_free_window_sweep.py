"""Broad free-window MNQ sweep for CELL-017.

CELL-017 is no longer constrained to the previous late-session slot.  This
runner searches non-overlapping MNQ windows outside the current approved
portfolio entry blocks and validates the best NTAMicroMnqScalpPilot carrier
profiles against the promotion gates requested for the reopened slot:

- Full net > 0 after commission/slippage
- OOS net > 0 after commission/slippage
- stress variants do not go negative
- Full frequency >= roughly 2 trades/day

The search intentionally uses the compiled carrier first.  A passing profile can
then be promoted into a dedicated C017 wrapper with identical locked defaults.
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
import run_mnq_cell019_evening_session as BASE  # noqa: E402


CELL_ID = "CELL-017"
PROFILE_ID = "mnq_free_window_scalp_1m_c017_ready_v1"
DISPLAY_NAME = "Scalping Free Window MNQ 1m v1 c017"
BUNDLE_PREFIX = "mnq_cell017_free_window_sweep"

# Entry windows already claimed by approved/rejected MNQ/MGC paper portfolio
# profiles.  CELL-017 candidates below are outside these entry blocks.
OCCUPIED_ENTRY_WINDOWS = [
    {"label": "MGC active paper windows", "start": "06:00", "end": "12:00"},
    {"label": "MNQ active paper windows", "start": "06:35", "end": "12:45"},
]

CSV_FIELDS = BASE.CSV_FIELDS + [
    "window_group",
    "free_window",
]


def mm(hhmm: int) -> int:
    return (hhmm // 100) * 60 + (hhmm % 100)


def fmt_hhmm(hhmm: int) -> str:
    return f"{hhmm // 100:02d}:{hhmm % 100:02d}"


def is_free_window(start: int, end: int) -> bool:
    """Return True when a non-wrapping interval does not overlap occupied blocks."""
    start_m = mm(start)
    end_m = mm(end)
    occupied = [(mm(600), mm(1200)), (mm(635), mm(1245))]
    return all(end_m <= a or start_m >= b for a, b in occupied)


def build_variants(limit: Optional[int] = None) -> List[BASE.Variant]:
    windows = [
        # Overnight / early pre-open.  Force flat before MGC 06:00 and MNQ 06:35.
        ("preopen", 30, 300, 305, 30),
        ("preopen", 100, 400, 405, 100),
        ("preopen", 200, 500, 505, 200),
        ("preopen", 300, 555, 559, 300),
        ("preopen", 400, 555, 559, 400),
        # Small post-active tail.  Kept in the sweep for completeness; frequency
        # gate makes weak narrow edges ineligible for promotion.
        ("post_active", 1246, 1325, 1330, 1245),
        ("post_active", 1301, 1325, 1330, 1300),
        # CME index ETH evening reopen and later quiet sessions.
        ("evening", 1505, 1800, 1805, 1500),
        ("evening", 1700, 2000, 2005, 1700),
        ("evening", 2000, 2300, 2305, 2000),
    ]
    specs: Dict[str, Dict[str, Any]] = {
        "all": {
            "directions": ["both", "short", "long"],
            "rrs": [3.0, 4.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.5, 0.7],
        },
        "fail": {
            "directions": ["both", "short", "long"],
            "rrs": [1.25, 1.5, 2.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.0, 0.7],
        },
        "orb_retest": {
            "directions": ["both", "short", "long"],
            "rrs": [1.75, 2.5],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.7],
        },
        "vwap": {
            "directions": ["both", "long", "short"],
            "rrs": [2.0, 3.0],
            "stops": [(4, 10), (6, 14)],
            "volumes": [0.5, 0.7],
        },
        "ema": {
            "directions": ["both", "long", "short"],
            "rrs": [3.0, 4.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.7],
        },
    }
    variants: List[BASE.Variant] = []
    for group, start, end, flat, orb_start in windows:
        if not is_free_window(start, end):
            raise AssertionError(f"window {start:04d}-{end:04d} overlaps occupied portfolio blocks")
        window_label = f"{start:04d}_{end:04d}"
        for module, spec in specs.items():
            for direction in spec["directions"]:
                for rr in spec["rrs"]:
                    for min_stop, max_stop in spec["stops"]:
                        for vol in spec["volumes"]:
                            params = BASE.base_params()
                            params.update(BASE.module_params(module, direction))
                            params.update({
                                "TradeStartTime": start,
                                "TradeEndTime": end,
                                "ForceFlatTime": flat,
                                "OrbStartTime": orb_start,
                                "RewardRiskRatio": rr,
                                "MinStopTicks": min_stop,
                                "MaxStopTicks": max_stop,
                                "MinVolumeFactor": vol,
                                "PullbackLookback": 4 if module in {"vwap", "ema"} else 3,
                                "NewsBlackoutTimes": "",
                            })
                            if module == "fail":
                                params["OrbFailedLookback"] = 4
                                params["TimeStopBars"] = 4
                                params["MinProgressR"] = 0.20
                            if module == "all":
                                params["UseSetupModeFilter"] = False
                            rr_label = str(rr).replace(".", "")
                            vol_label = str(vol).replace(".", "")
                            name = (
                                f"{module}_{direction}_{window_label}_"
                                f"s{min_stop}_{max_stop}_rr{rr_label}_v{vol_label}"
                            )
                            variant = BASE.Variant(
                                name=name,
                                params=params,
                                window=f"{fmt_hhmm(start)}-{fmt_hhmm(end)}",
                                module=module,
                                direction=direction,
                                rr=rr,
                                min_stop=min_stop,
                                max_stop=max_stop,
                                min_volume=vol,
                                setup_mode=str(params.get("SetupMode") or "AllModules"),
                                orb_start=orb_start,
                            )
                            object.__setattr__(variant, "window_group", group)
                            object.__setattr__(variant, "free_window", True)
                            variants.append(variant)
                            if limit and len(variants) >= limit:
                                return variants
    return variants


def row_from_submission(sub: Dict[str, Any]) -> Dict[str, Any]:
    row = BASE.row_from_submission(sub)
    meta = sub.get("meta") or {}
    row["window_group"] = meta.get("window_group") or ""
    row["free_window"] = bool(meta.get("free_window", False))
    return row


def incomplete_row_from_submission(sub: Dict[str, Any], status: str) -> Dict[str, Any]:
    meta = sub.get("meta") or {}
    return {
        "stage": sub["stage"],
        "variant": sub["variant"],
        "job_id": sub.get("job_id") or "",
        "status": status,
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
        "slippage_ticks": sub["slippage_ticks"],
        "round_turn_commission": sub["round_turn_commission"],
        "window": meta.get("window"),
        "module": meta.get("module"),
        "direction": meta.get("direction"),
        "rr": meta.get("rr"),
        "min_stop": meta.get("min_stop"),
        "max_stop": meta.get("max_stop"),
        "min_volume": meta.get("min_volume"),
        "setup_mode": meta.get("setup_mode"),
        "orb_start": meta.get("orb_start"),
        "window_group": meta.get("window_group") or "",
        "free_window": bool(meta.get("free_window", False)),
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def score_smoke(row: Dict[str, Any]) -> float:
    trades = int(row.get("trade_count") or 0)
    tpd = float(row.get("trades_per_day") or 0.0)
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    avg = float(row.get("avg_trade") or 0.0)
    active = float(row.get("active_days_pct") or 0.0)
    if trades < 20 or tpd < 0.35 or net <= 0.0 or pf < 1.03:
        return -1e9
    return net + min(tpd, 5.0) * 150.0 + min(pf, 3.0) * 100.0 + avg * 35.0 + active * 0.3 - dd * 0.3


def gates(rows: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
    full = rows.get("Full", {})
    is_row = rows.get("IS", {})
    oos = rows.get("OOS", {})
    slip = rows.get("StressSlip2", {})
    fee = rows.get("StressFee240", {})
    combined = rows.get("StressSlip2Fee240", {})
    current = rows.get("Current30D", {})
    return {
        "free_non_overlapping_window": bool(full.get("free_window", False)),
        "full_net_positive": float(full.get("adj_net") or 0.0) > 0.0,
        "full_pf_gt_1": float(full.get("adj_pf") or 0.0) > 1.0,
        "full_trades_per_day_ge_2": float(full.get("trades_per_day") or 0.0) >= 2.0,
        "is_net_positive": float(is_row.get("adj_net") or 0.0) > 0.0,
        "oos_net_positive": float(oos.get("adj_net") or 0.0) > 0.0,
        "oos_pf_gt_1": float(oos.get("adj_pf") or 0.0) > 1.0,
        "stress_slip2_nonnegative": float(slip.get("adj_net") or 0.0) >= 0.0,
        "stress_fee240_nonnegative": float(fee.get("adj_net") or 0.0) >= 0.0,
        "stress_combined_nonnegative": float(combined.get("adj_net") or 0.0) >= 0.0,
        "current30_life_check_nonnegative": float(current.get("adj_net") or 0.0) >= 0.0,
        "current30_life_check_trades_ge_10": int(current.get("trade_count") or 0) >= 10,
    }


def top_by_window(decisions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for decision in decisions:
        full = (decision.get("rows") or {}).get("Full", {})
        key = str(full.get("window") or "unknown")
        cur = best.get(key)
        if not cur:
            best[key] = decision
            continue
        cur_full = (cur.get("rows") or {}).get("Full", {})
        cur_key = (
            1 if cur.get("ready_pass") else 0,
            float(cur_full.get("adj_net") or -math.inf),
            float(cur_full.get("trades_per_day") or 0.0),
        )
        new_key = (
            1 if decision.get("ready_pass") else 0,
            float(full.get("adj_net") or -math.inf),
            float(full.get("trades_per_day") or 0.0),
        )
        if new_key > cur_key:
            best[key] = decision
    return [best[key] for key in sorted(best)]


def write_summary_md(path: Path, summary: Dict[str, Any], decisions: List[Dict[str, Any]]) -> None:
    lines = [
        "# CELL-017 free-window broad sweep",
        "",
        f"- bundle: `{summary['bundle']}`",
        f"- cell: `{CELL_ID}`",
        f"- carrier: `{BASE.CLASS_NAME}`",
        f"- instrument: `{BASE.INSTRUMENT}`",
        f"- session template: `{BASE.SESSION_TEMPLATE}`",
        f"- selected variants: `{len(summary['selected'])}`",
        f"- ready variants: `{len(summary['ready'])}`",
        "",
        "## Occupied entry windows",
        "",
    ]
    for item in OCCUPIED_ENTRY_WINDOWS:
        lines.append(f"- {item['label']}: {item['start']}-{item['end']} PT")
    lines.extend([
        "",
        "## Best candidate per window",
        "",
        "| window | module | direction | variant | Full net | Full PF | Full trades/day | OOS net | combined stress | failed gates |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ])
    for decision in top_by_window(decisions):
        rows = decision.get("rows") or {}
        full = rows.get("Full", {})
        oos = rows.get("OOS", {})
        combined = rows.get("StressSlip2Fee240", {})
        failed = ", ".join(decision.get("failed_gates") or []) or "PASS"
        lines.append(
            f"| {full.get('window')} | {full.get('module')} | {full.get('direction')} | "
            f"`{decision.get('variant')}` | {float(full.get('adj_net') or 0.0):.2f} | "
            f"{float(full.get('adj_pf') or 0.0):.3f} | {float(full.get('trades_per_day') or 0.0):.2f} | "
            f"{float(oos.get('adj_net') or 0.0):.2f} | "
            f"{float(combined.get('adj_net') or 0.0):.2f} | {failed} |"
        )
    lines.extend([
        "",
        "## Promotion decision",
        "",
    ])
    if summary["ready"]:
        lines.append(f"Ready candidate(s): {', '.join(f'`{x}`' for x in summary['ready'])}.")
    else:
        lines.append("No ready candidate in this sweep. CELL-017 must remain free unless a new engine passes.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--smoke-days", type=int, default=60)
    ap.add_argument("--resume-bundle", default="")
    ap.add_argument("--allow-incomplete-smoke", action="store_true")
    args = ap.parse_args(argv)

    variants = build_variants(args.limit or None)
    if args.resume_bundle:
        bundle = Path(args.resume_bundle)
        if not bundle.is_absolute():
            bundle = Path.cwd() / bundle
        smoke_subs = json.loads((bundle / "smoke_submissions.json").read_text(encoding="utf-8"))
        print(f"bundle: {bundle}", flush=True)
        print(f"resume smoke submissions: {len(smoke_subs)}", flush=True)
        incomplete = [
            {
                "job_id": s.get("job_id") or "",
                "variant": s.get("variant") or "",
                "status": BASE.job_state(s.get("job_id") or "") or "missing",
            }
            for s in smoke_subs
            if (BASE.job_state(s.get("job_id") or "") or "missing") not in {"done", "failed", "cancelled"}
        ]
        if incomplete and not args.allow_incomplete_smoke:
            BASE.wait_for_jobs([s.get("job_id") for s in smoke_subs if s.get("job_id")])
        if incomplete and args.allow_incomplete_smoke:
            (bundle / "incomplete_smoke_jobs.json").write_text(
                json.dumps(incomplete, indent=2),
                encoding="utf-8",
            )
            print(f"allowing incomplete smoke jobs: {len(incomplete)}", flush=True)
    else:
        bundle = RL.PROJECT_ROOT / "data" / "research" / f"{BUNDLE_PREFIX}_{BASE.utc_stamp()}"
        bundle.mkdir(parents=True, exist_ok=True)
        smoke_from, smoke_to = BASE.current_window(args.smoke_days)
        print(f"bundle: {bundle}", flush=True)
        print(f"variants: {len(variants)} smoke={smoke_from}..{smoke_to}", flush=True)
        smoke_subs = [
            BASE.submit_job(v, "Smoke", smoke_from, smoke_to, 1, RL.fee_for(BASE.ROOT))
            for v in variants
        ]
        (bundle / "smoke_submissions.json").write_text(json.dumps(smoke_subs, indent=2), encoding="utf-8")
        BASE.wait_for_jobs([s.get("job_id") for s in smoke_subs if s.get("job_id")])

    smoke_rows = []
    for sub in smoke_subs:
        status = BASE.job_state(sub.get("job_id") or "") or "missing"
        if status == "done":
            smoke_rows.append(row_from_submission(sub))
        else:
            smoke_rows.append(incomplete_row_from_submission(sub, status))
    smoke_rows.sort(key=score_smoke, reverse=True)
    write_csv(bundle / "smoke_rows.csv", smoke_rows)
    (bundle / "smoke_rows.json").write_text(json.dumps(smoke_rows, indent=2), encoding="utf-8")

    selected_names = [r["variant"] for r in smoke_rows if score_smoke(r) > -1e8][:args.top]
    by_name = {v.name: v for v in variants}
    selected = [by_name[n] for n in selected_names]
    print("selected:", flush=True)
    for row in smoke_rows[:args.top]:
        print(
            f"  {row['variant']}: window={row['window']} module={row['module']} "
            f"trades={row['trade_count']} tpd={float(row['trades_per_day']):.2f} "
            f"net={float(row['adj_net']):.2f} pf={float(row['adj_pf']):.2f} "
            f"dd={float(row['adj_dd']):.2f}",
            flush=True,
        )

    cur_from, cur_to = BASE.current_window(30)
    val_plan = [
        ("Full", BASE.FULL[1], BASE.FULL[2], 1, RL.fee_for(BASE.ROOT)),
        ("IS", BASE.IS[1], BASE.IS[2], 1, RL.fee_for(BASE.ROOT)),
        ("OOS", BASE.OOS[1], BASE.OOS[2], 1, RL.fee_for(BASE.ROOT)),
        ("StressSlip2", BASE.FULL[1], BASE.FULL[2], 2, RL.fee_for(BASE.ROOT)),
        ("StressFee240", BASE.FULL[1], BASE.FULL[2], 1, 2.40),
        ("StressSlip2Fee240", BASE.FULL[1], BASE.FULL[2], 2, 2.40),
        ("Current30D", cur_from, cur_to, 1, RL.fee_for(BASE.ROOT)),
    ]
    val_subs: List[Dict[str, Any]] = []
    for variant in selected:
        for stage, from_utc, to_utc, slip, fee in val_plan:
            val_subs.append(BASE.submit_job(variant, stage, from_utc, to_utc, slip, fee))
    (bundle / "validation_submissions.json").write_text(json.dumps(val_subs, indent=2), encoding="utf-8")
    BASE.wait_for_jobs([s.get("job_id") for s in val_subs if s.get("job_id")])
    val_rows = [row_from_submission(s) for s in val_subs]
    write_csv(bundle / "validation_rows.csv", val_rows)
    (bundle / "validation_rows.json").write_text(json.dumps(val_rows, indent=2), encoding="utf-8")

    decisions: List[Dict[str, Any]] = []
    for variant in selected:
        rows = {r["stage"]: r for r in val_rows if r["variant"] == variant.name}
        gate_values = gates(rows)
        failed = [key for key, value in gate_values.items() if not value]
        decision = "paper_ready_candidate" if not failed else "research_only"
        decisions.append({
            "variant": variant.name,
            "profile_id": PROFILE_ID,
            "display_name": DISPLAY_NAME,
            "cell_id": CELL_ID,
            "decision": decision,
            "ready_pass": not failed,
            "failed_gates": failed,
            "gates": gate_values,
            "locked_parameters": variant.params,
            "rows": rows,
        })
    decisions.sort(key=lambda d: (
        1 if d["ready_pass"] else 0,
        float((d.get("rows") or {}).get("Full", {}).get("adj_net") or -math.inf),
        float((d.get("rows") or {}).get("Full", {}).get("trades_per_day") or 0.0),
    ), reverse=True)
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    summary = {
        "bundle": str(bundle),
        "cell_id": CELL_ID,
        "profile_id": PROFILE_ID,
        "display_name": DISPLAY_NAME,
        "class_name": BASE.CLASS_NAME,
        "instrument": BASE.INSTRUMENT,
        "session_template": BASE.SESSION_TEMPLATE,
        "occupied_entry_windows": OCCUPIED_ENTRY_WINDOWS,
        "selected": selected_names,
        "ready": [d["variant"] for d in decisions if d["ready_pass"]],
        "best": decisions[0] if decisions else None,
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_summary_md(bundle / "summary.md", summary, decisions)
    print("decisions:", flush=True)
    for d in decisions:
        full = d.get("rows", {}).get("Full", {})
        oos = d.get("rows", {}).get("OOS", {})
        stress = d.get("rows", {}).get("StressSlip2Fee240", {})
        cur = d.get("rows", {}).get("Current30D", {})
        print(
            f"  {d['variant']}: {d['decision']} window={full.get('window')} "
            f"full_net={full.get('adj_net')} full_tpd={full.get('trades_per_day')} "
            f"oos={oos.get('adj_net')} stress={stress.get('adj_net')} "
            f"current30={cur.get('adj_net')} failed={','.join(d['failed_gates'])}",
            flush=True,
        )
    return 0 if any(d.get("ready_pass") for d in decisions) else 1


if __name__ == "__main__":
    raise SystemExit(main())
