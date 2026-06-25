"""MNQ Research Hub ladder for Head & Shoulders with RSI divergence.

This runner uses the already stable class name `NTAMnqResearchHub` and switches
only Mode/parameters. A deploy wrapper must be created separately only if the
final gates pass.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import research_lib as RL  # noqa: E402
import run_mnq_cell020_session_edge_ladder as base  # noqa: E402


base.CLASS_NAME = "NTAMnqResearchHub"
base.BUNDLE_PREFIX = "mnq_head_shoulders_research"

WINDOWS: Dict[str, Dict[str, int]] = {
    "openA": {"RangeStartTime": 0, "RangeEndTime": 630,
              "TradeStartTime": 635, "TradeEndTime": 800, "ForceFlatTime": 805},
    "rthA": {"RangeStartTime": 0, "RangeEndTime": 630,
             "TradeStartTime": 635, "TradeEndTime": 930, "ForceFlatTime": 935},
    "rthMid": {"RangeStartTime": 0, "RangeEndTime": 800,
               "TradeStartTime": 805, "TradeEndTime": 1030, "ForceFlatTime": 1035},
    "rthB": {"RangeStartTime": 0, "RangeEndTime": 930,
             "TradeStartTime": 935, "TradeEndTime": 1245, "ForceFlatTime": 1250},
    "pmB": {"RangeStartTime": 1200, "RangeEndTime": 1300,
            "TradeStartTime": 1305, "TradeEndTime": 1500, "ForceFlatTime": 1504},
}

STRUCTURES: Dict[str, Dict[str, Any]] = {
    "loose": {
        "PullbackTicks": 48, "DriveTicks": 20, "FailReturnTicks": 3,
        "RejectWickTicks": 2, "RewardRiskRatio": 0.8, "EntryOffsetTicks": 10,
    },
    "balanced": {
        "PullbackTicks": 32, "DriveTicks": 32, "FailReturnTicks": 5,
        "RejectWickTicks": 4, "RewardRiskRatio": 1.0, "EntryOffsetTicks": 10,
    },
    "strict": {
        "PullbackTicks": 20, "DriveTicks": 40, "FailReturnTicks": 7,
        "RejectWickTicks": 6, "RewardRiskRatio": 1.0, "EntryOffsetTicks": 10,
    },
    "deep": {
        "PullbackTicks": 40, "DriveTicks": 60, "FailReturnTicks": 5,
        "RejectWickTicks": 2, "RewardRiskRatio": 0.8, "EntryOffsetTicks": 10,
    },
    "quality": {
        "PullbackTicks": 48, "DriveTicks": 24, "FailReturnTicks": 4,
        "RejectWickTicks": 4, "ReclaimBufferTicks": 8,
        "RewardRiskRatio": 1.25, "MinTargetTicks": 20, "EntryOffsetTicks": 10,
    },
    "filtered": {
        "PullbackTicks": 48, "DriveTicks": 24, "FailReturnTicks": 4,
        "RejectWickTicks": 4, "ReclaimBufferTicks": 8,
        "RewardRiskRatio": 1.25, "MinTargetTicks": 20, "EntryOffsetTicks": 10,
        "RequireVwapAgreement": True, "RequireEmaAgreement": True,
        "MinVolumeFactor": 0.5,
    },
    "highr": {
        "PullbackTicks": 64, "DriveTicks": 32, "FailReturnTicks": 5,
        "RejectWickTicks": 4, "ReclaimBufferTicks": 10,
        "RewardRiskRatio": 1.5, "MinTargetTicks": 28,
        "MaxStopTicks": 80, "EntryOffsetTicks": 10,
    },
    "live_loose": {
        "Mode": "HeadAndShouldersLive",
        "PullbackTicks": 72, "DriveTicks": 16, "FailReturnTicks": 2,
        "RejectWickTicks": 3, "ReclaimBufferTicks": 2,
        "RewardRiskRatio": 0.65, "MinTargetTicks": 8,
        "MaxStopTicks": 180, "EntryOffsetTicks": 4,
    },
    "live_balanced": {
        "Mode": "HeadAndShouldersLive",
        "PullbackTicks": 56, "DriveTicks": 24, "FailReturnTicks": 4,
        "RejectWickTicks": 4, "ReclaimBufferTicks": 4,
        "RewardRiskRatio": 0.85, "MinTargetTicks": 12,
        "MaxStopTicks": 160, "EntryOffsetTicks": 4,
    },
    "live_quality": {
        "Mode": "HeadAndShouldersLive",
        "PullbackTicks": 44, "DriveTicks": 32, "FailReturnTicks": 5,
        "RejectWickTicks": 6, "ReclaimBufferTicks": 6,
        "RewardRiskRatio": 1.0, "MinTargetTicks": 16,
        "MaxStopTicks": 140, "EntryOffsetTicks": 4,
    },
    "live_vwap": {
        "Mode": "HeadAndShouldersLive",
        "PullbackTicks": 56, "DriveTicks": 24, "FailReturnTicks": 4,
        "RejectWickTicks": 5, "ReclaimBufferTicks": 4,
        "RewardRiskRatio": 0.85, "MinTargetTicks": 12,
        "MaxStopTicks": 160, "EntryOffsetTicks": 4,
        "RequireVwapAgreement": True,
    },
    "live_confirmed": {
        "Mode": "HeadAndShouldersLive",
        "PullbackTicks": 48, "DriveTicks": 28, "FailReturnTicks": 5,
        "RejectWickTicks": 6, "ReclaimBufferTicks": 6,
        "RewardRiskRatio": 0.9, "MinTargetTicks": 14,
        "MaxStopTicks": 150, "EntryOffsetTicks": 4,
        "RequireVwapAgreement": True, "RequireEmaAgreement": True,
        "MinVolumeFactor": 0.55,
    },
    "live_exhaust": {
        "Mode": "HeadAndShouldersLive",
        "PullbackTicks": 40, "DriveTicks": 36, "FailReturnTicks": 7,
        "RejectWickTicks": 8, "ReclaimBufferTicks": 6,
        "RewardRiskRatio": 1.0, "MinTargetTicks": 16,
        "MaxStopTicks": 140, "EntryOffsetTicks": 4,
        "RequireVwapAgreement": True, "RequireEmaAgreement": True,
        "RequireEmaStack": True, "MinVolumeFactor": 0.50,
        "MaxTradesPerDay": 2, "HardMaxTradesPerDay": 3,
    },
    "live_wedfri_730": {
        "Mode": "HeadAndShouldersLive",
        "PullbackTicks": 48, "DriveTicks": 28, "FailReturnTicks": 5,
        "RejectWickTicks": 6, "ReclaimBufferTicks": 6,
        "RewardRiskRatio": 0.9, "MinTargetTicks": 14,
        "MaxStopTicks": 150, "EntryOffsetTicks": 4,
        "RequireVwapAgreement": True, "RequireEmaAgreement": True,
        "MinVolumeFactor": 0.55,
        "AllowedWeekdayMask": 28,
        "TradeStartTime": 730, "TradeEndTime": 805, "ForceFlatTime": 810,
    },
    "neck_break": {
        "Mode": "HeadAndShouldersNeckBreak",
        "PullbackTicks": 56, "DriveTicks": 28, "FailReturnTicks": 4,
        "RejectWickTicks": 3, "ReclaimBufferTicks": 4,
        "RewardRiskRatio": 1.0, "MinTargetTicks": 24,
        "MaxStopTicks": 180, "EntryOffsetTicks": 11,
    },
    "neck_break_guard": {
        "Mode": "HeadAndShouldersNeckBreak",
        "PullbackTicks": 48, "DriveTicks": 32, "FailReturnTicks": 5,
        "RejectWickTicks": 4, "ReclaimBufferTicks": 6,
        "RewardRiskRatio": 1.15, "MinTargetTicks": 28,
        "MaxStopTicks": 160, "EntryOffsetTicks": 11,
        "RequireVwapAgreement": True, "RequireEmaAgreement": True,
        "RequireEmaSlope": True, "MinVolumeFactor": 0.55,
        "MaxTradesPerDay": 1, "HardMaxTradesPerDay": 2,
        "PauseAfterConsecutiveLosses": 1, "PauseMinutesAfterLosses": 180,
    },
    "neck_retest": {
        "Mode": "HeadAndShouldersNeckRetest",
        "PullbackTicks": 56, "DriveTicks": 28, "FailReturnTicks": 4,
        "RejectWickTicks": 6, "ReclaimBufferTicks": 4,
        "RewardRiskRatio": 1.0, "MinTargetTicks": 24,
        "MaxStopTicks": 180, "EntryOffsetTicks": 12,
    },
    "neck_retest_guard": {
        "Mode": "HeadAndShouldersNeckRetest",
        "PullbackTicks": 48, "DriveTicks": 32, "FailReturnTicks": 5,
        "RejectWickTicks": 8, "ReclaimBufferTicks": 6,
        "RewardRiskRatio": 1.15, "MinTargetTicks": 28,
        "MaxStopTicks": 160, "EntryOffsetTicks": 12,
        "RequireVwapAgreement": True, "RequireEmaAgreement": True,
        "RequireEmaSlope": True, "MinVolumeFactor": 0.55,
        "MaxTradesPerDay": 1, "HardMaxTradesPerDay": 2,
        "MoveToBreakevenAtR": 0.75, "BreakevenPlusTicks": 1,
        "PauseAfterConsecutiveLosses": 1, "PauseMinutesAfterLosses": 180,
    },
    "neck_go_trail": {
        "Mode": "HeadAndShouldersNeckGo",
        "PullbackTicks": 64, "DriveTicks": 32, "FailReturnTicks": 4,
        "RejectWickTicks": 4, "ReclaimBufferTicks": 8,
        "RewardRiskRatio": 1.25, "MinTargetTicks": 32,
        "MaxStopTicks": 180, "EntryOffsetTicks": 13,
        "MoveToBreakevenAtR": 0.75, "BreakevenPlusTicks": 1,
        "UseTrailingStop": True, "TrailAfterR": 1.0, "TrailDistanceTicks": 24,
    },
}

STRENGTHS = [2, 3, 4, 5]


def hns_base_params() -> Dict[str, Any]:
    p = base.base_params()
    p.update({
        "Mode": "HeadAndShouldersClose",
        "EnableLong": False,
        "EnableShort": True,
        "RequireVwapAgreement": False,
        "RequireEmaAgreement": False,
        "RequireEmaSlope": False,
        "RequireEmaStack": False,
        "MinVolumeFactor": 0.4,
        "ReclaimBufferTicks": 4,
        "StopBufferTicks": 4,
        "MinStopTicks": 8,
        "MaxStopTicks": 120,
        "AtrStopMult": 0.0,
        "MinTargetTicks": 8,
        "EntryOffsetTicks": 10,
        "MoveToBreakevenAtR": 0.0,
        "UseTrailingStop": False,
        "UseTimeStop": True,
        "TimeStopBars": 18,
        "MinProgressR": 0.20,
        "RiskPerTradePct": 0.75,
        "UserMaxContracts": 1,
        "MaxDailyLossUsd": 80.0,
        "MaxWeeklyLossUsd": 200.0,
        "MaxTradesPerDay": 3,
        "HardMaxTradesPerDay": 5,
        "AllowedWeekdayMask": 0,
    })
    return p


def candidates() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for win_code, win in WINDOWS.items():
        for strength in STRENGTHS:
            for struct_code, struct in STRUCTURES.items():
                p = hns_base_params()
                p.update(win)
                p.update(struct)
                p["EntryTimeoutBars"] = strength
                label = f"hns_{win_code}_s{strength}_{struct_code}"
                out.append({"label": label, "params": p, "fam": "hns", "win": win_code})
    return out


def pick_survivors(rows: List[Dict[str, Any]], max_survivors: int) -> List[Dict[str, Any]]:
    eligible = [
        r for r in rows
        if int(r.get("trade_count") or 0) >= 6
        and float(r.get("adj_net") or 0.0) > 0.0
        and (math.isinf(float(r.get("adj_pf") or 0.0)) or float(r.get("adj_pf") or 0.0) >= 1.10)
    ]
    if not eligible:
        eligible = [r for r in rows if int(r.get("trade_count") or 0) >= 6]
    eligible.sort(key=base.score, reverse=True)

    picked: List[Dict[str, Any]] = []
    seen_windows = set()
    for row in eligible:
        win = str(row.get("win") or "")
        if win in seen_windows:
            continue
        picked.append(row)
        seen_windows.add(win)
        if len(picked) >= max_survivors:
            break
    for row in eligible:
        if row in picked:
            continue
        picked.append(row)
        if len(picked) >= max_survivors:
            break
    return picked[:max_survivors]


def _pf(v: Any) -> str:
    try:
        f = float(v)
    except Exception:
        return ""
    return "inf" if math.isinf(f) else f"{f:.3f}"


def write_summary(bundle: Path, final: Dict[str, Any]) -> None:
    lines = [
        "# MNQ Head & Shoulders Research Hub Ladder",
        "",
        f"Bundle: `{bundle.name}`",
        "Class: `NTAMnqResearchHub`",
        "Mode: `HeadAndShoulders`",
        f"Timeframe: {base.BARS_PERIOD_VALUE} Minute",
        "Entry: right shoulder rejection; stop beyond head; target neckline.",
        "",
    ]
    for title, key in [
        ("Smoke", "smoke_rows"),
        ("Validation", "validation_rows"),
        ("Stress", "stress_rows"),
        ("Current30D", "current_rows"),
    ]:
        rows = final.get(key) or []
        if not rows:
            continue
        lines += [
            f"## {title}",
            "",
            "| Label | Period | Trades | TPD | Net | PF | Win% | DD | SB% |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in sorted(rows, key=base.score, reverse=True):
            lines.append(
                f"| `{r.get('label','')}` | {r.get('period_label','')} | "
                f"{int(r.get('trade_count') or 0)} | "
                f"{float(r.get('trades_per_day') or 0.0):.2f} | "
                f"{float(r.get('adj_net') or 0.0):.2f} | {_pf(r.get('adj_pf'))} | "
                f"{float(r.get('win_rate') or 0.0):.1f} | "
                f"{float(r.get('max_drawdown') or 0.0):.2f} | "
                f"{float(r.get('same_bar_pct') or 0.0):.1f} |"
            )
        lines.append("")

    lines += [
        "## Decision",
        "",
        "```json",
        json.dumps(final.get("decision") or {}, indent=2, ensure_ascii=False, default=str),
        "```",
        "",
    ]
    (bundle / "head_shoulders_summary.md").write_text("\n".join(lines), encoding="utf-8")


def by_label(rows: List[Dict[str, Any]], label: str, period: str) -> Dict[str, Any]:
    return base.by_label_period(rows, label, period)


def run(smoke_only: bool, max_survivors: int) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"mnq_head_shoulders_research_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    cands = candidates()
    by_candidate = {c["label"]: c for c in cands}
    final: Dict[str, Any] = {
        "class_name": base.CLASS_NAME,
        "mode": "HeadAndShoulders/HeadAndShouldersLive",
        "instrument": base.INSTRUMENT,
        "bars_period_value": base.BARS_PERIOD_VALUE,
        "created_utc": RL.utcnow_iso(),
        "candidate_count": len(cands),
    }

    smoke_submitted = [
        base.submit_job(
            bundle=bundle, label=c["label"], stage="smoke",
            period_label=base.SMOKE[0], from_utc=base.SMOKE[1], to_utc=base.SMOKE[2],
            params=c["params"], fee=base.FEE_BASE, slip=1, fam=c["fam"], win=c["win"],
        )
        for c in cands
    ]
    smoke_rows = base.collect_rows(bundle, smoke_submitted, "smoke_rows.json")
    final["smoke_rows"] = smoke_rows

    survivors = pick_survivors(smoke_rows, max_survivors=max_survivors)
    final["smoke_survivors"] = [s["label"] for s in survivors]
    print(f"smoke survivors: {final['smoke_survivors']}", flush=True)

    if smoke_only or not survivors:
        final["decision"] = {
            "status": "smoke_only" if smoke_only else "rejected",
            "reason": "smoke_only flag" if smoke_only else "no H&S smoke survivor",
        }
        (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_summary(bundle, final)
        return

    validation_submitted: List[Dict[str, Any]] = []
    for s in survivors:
        c = by_candidate[str(s["label"])]
        for period_label, frm, to in (base.FULL, base.IS, base.OOS):
            validation_submitted.append(base.submit_job(
                bundle=bundle, label=c["label"], stage="validation",
                period_label=period_label, from_utc=frm, to_utc=to,
                params=c["params"], fee=base.FEE_BASE, slip=1, fam=c["fam"], win=c["win"],
            ))
    validation_rows = base.collect_rows(bundle, validation_submitted, "validation_rows.json")
    final["validation_rows"] = validation_rows

    full_rows = [r for r in validation_rows if r.get("period_label") == "Full"]
    full_rows.sort(key=base.score, reverse=True)
    positive_full = [r for r in full_rows if float(r.get("adj_net") or 0.0) > 0.0]
    if not positive_full:
        final["decision"] = {
            "status": "rejected",
            "reason": "no H&S survivor produced positive Full adjusted net",
            "closest": full_rows[0] if full_rows else None,
        }
        (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_summary(bundle, final)
        print("DECISION: rejected (no positive Full)", flush=True)
        return

    best = positive_full[0]
    best_label = str(best["label"])
    best_candidate = by_candidate[best_label]
    best_params = best_candidate["params"]

    stress_submitted = [
        base.submit_job(bundle=bundle, label=best_label, stage="stress", period_label="slip2",
                        from_utc=base.FULL[1], to_utc=base.FULL[2],
                        params=best_params, fee=base.FEE_BASE, slip=2,
                        fam="hns", win=best_candidate["win"]),
        base.submit_job(bundle=bundle, label=best_label, stage="stress", period_label="fee240",
                        from_utc=base.FULL[1], to_utc=base.FULL[2],
                        params=best_params, fee=base.FEE_STRESS, slip=1,
                        fam="hns", win=best_candidate["win"]),
        base.submit_job(bundle=bundle, label=best_label, stage="stress", period_label="slip2_fee240",
                        from_utc=base.FULL[1], to_utc=base.FULL[2],
                        params=best_params, fee=base.FEE_STRESS, slip=2,
                        fam="hns", win=best_candidate["win"]),
    ]
    stress_rows = base.collect_rows(bundle, stress_submitted, "stress_rows.json")
    final["stress_rows"] = stress_rows

    cur_from, cur_to = base.current_window(30)
    current_submitted = [
        base.submit_job(bundle=bundle, label=best_label, stage="current", period_label="Current30D",
                        from_utc=cur_from, to_utc=cur_to,
                        params=best_params, fee=base.FEE_BASE, slip=1,
                        fam="hns", win=best_candidate["win"]),
    ]
    current_rows = base.collect_rows(bundle, current_submitted, "current_rows.json")
    final["current_rows"] = current_rows

    full = by_label(validation_rows, best_label, "Full")
    is_ = by_label(validation_rows, best_label, "IS")
    oos = by_label(validation_rows, best_label, "OOS")
    combined = next((r for r in stress_rows if r.get("period_label") == "slip2_fee240"), {})
    current = current_rows[0] if current_rows else {}
    gate_results = base.gates(
        full, is_, oos, combined, current,
        starting_capital=RL.starting_capital_from_params(best_params),
    )
    passed = all(gate_results.values())
    final["decision"] = {
        "status": "paper_candidate" if passed else "rejected",
        "best_label": best_label,
        "locked_params": best_params,
        "gates": gate_results,
        "full": full,
        "is": is_,
        "oos": oos,
        "stress_combined": combined,
        "current30d": current,
    }
    (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    write_summary(bundle, final)
    print(f"DECISION: {final['decision']['status']} (best={best_label})", flush=True)
    print(f"gates: {gate_results}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke-only", action="store_true")
    ap.add_argument("--max-survivors", type=int, default=5)
    ap.add_argument("--bar-minutes", type=int, default=5)
    args = ap.parse_args()
    base.BARS_PERIOD_VALUE = max(1, int(args.bar_minutes))
    base.BASE_TF_SECONDS = base.BARS_PERIOD_VALUE * 60
    run(smoke_only=args.smoke_only, max_survivors=max(1, args.max_survivors))


if __name__ == "__main__":
    main()
