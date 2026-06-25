"""Focused refinement for NTACapitulationSnapbackPilot.

This script runs after the portfolio smoke scan. It keeps the original rule:
do not choose a deploy cell until the strategy is tested across the portfolio,
then refine only the instruments that showed a positive smoke edge.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import run_capitulation_snapback_portfolio_scan as CAP  # noqa: E402


FOCUS_ROOTS = ["MGC", "MBT", "MES", "MNQ"]
FROM_FOCUS = "2025-01-01T00:00:00Z"
TO_FOCUS = "2025-12-31T23:59:59Z"

EXTRA_FIELDS = [
    "score",
    "max_adx",
    "confirm_body",
    "no_extreme_break",
    "reclaim_prev_open",
    "vwap_reclaim",
]
CSV_FIELDS = CAP.CSV_FIELDS + [f for f in EXTRA_FIELDS if f not in CAP.CSV_FIELDS]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def with_defaults(root: str, **overrides: Any) -> Dict[str, Any]:
    params = CAP.base_params(root)
    params.update({
        "MaxAdx": 100.0,
        "MinConfirmBodyFraction": 0.0,
        "RequireNoExtremeBreak": False,
        "RequireReclaimPrevOpen": False,
        "RequireVwapReclaim": False,
    })
    params.update(overrides)
    return params


def variant(root: str, name: str, **overrides: Any) -> CAP.Variant:
    return CAP.Variant(name=name, params=with_defaults(root, **overrides))


def seeded_variant(root: str, name: str, seed: Dict[str, Any], **overrides: Any) -> CAP.Variant:
    params = dict(seed)
    params.update(overrides)
    return variant(root, name, **params)


def focused_variants_for(root: str) -> List[CAP.Variant]:
    if root == "MGC":
        seed = {
            "EnableLong": False,
            "EnableShort": True,
            "TradeStartTime": 635,
            "TradeEndTime": 1000,
            "MinVolumeFactor": 1.6,
            "ShockAtrMult": 1.1,
            "ExtensionAtr": 0.8,
            "RewardRiskRatio": 1.2,
            "MinStopTicks": 10,
            "MaxStopTicks": 120,
        }
        return [
            seeded_variant(root, "mgc_short_seed", seed),
            seeded_variant(root, "mgc_short_noext", seed, RequireNoExtremeBreak=True),
            seeded_variant(root, "mgc_short_noext_confirm20", seed, RequireNoExtremeBreak=True, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mgc_short_noext_confirm35", seed, RequireNoExtremeBreak=True, MinConfirmBodyFraction=0.35),
            seeded_variant(root, "mgc_short_confirm20", seed, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mgc_short_reclaimopen", seed, RequireReclaimPrevOpen=True),
            seeded_variant(root, "mgc_short_vwapreclaim", seed, RequireVwapReclaim=True),
            seeded_variant(root, "mgc_short_adx45", seed, MaxAdx=45.0),
            seeded_variant(root, "mgc_short_adx35", seed, MaxAdx=35.0),
            seeded_variant(root, "mgc_short_0600_0930", seed, TradeStartTime=600, TradeEndTime=930),
            seeded_variant(root, "mgc_short_0635_0930", seed, TradeEndTime=930),
            seeded_variant(root, "mgc_short_0700_1030", seed, TradeStartTime=700, TradeEndTime=1030),
            seeded_variant(root, "mgc_short_loose", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6),
            seeded_variant(root, "mgc_short_strict", seed, MinVolumeFactor=2.0, ShockAtrMult=1.3, ExtensionAtr=1.0),
            seeded_variant(root, "mgc_short_rr100_hold08", seed, RewardRiskRatio=1.0, MaxHoldBars=8),
            seeded_variant(root, "mgc_short_rr150", seed, RewardRiskRatio=1.5),
            seeded_variant(root, "mgc_short_loose_noext", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, RequireNoExtremeBreak=True),
            seeded_variant(root, "mgc_short_loose_confirm20", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mgc_short_loose_noext_confirm20", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, RequireNoExtremeBreak=True, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mgc_short_loose_reclaimopen", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, RequireReclaimPrevOpen=True),
            seeded_variant(root, "mgc_short_loose_0600_0930", seed, TradeStartTime=600, TradeEndTime=930, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6),
            seeded_variant(root, "mgc_short_loose_0635_0930", seed, TradeEndTime=930, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6),
            seeded_variant(root, "mgc_short_loose_rr100_hold08", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, RewardRiskRatio=1.0, MaxHoldBars=8),
            seeded_variant(root, "mgc_short_loose_rr140", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, RewardRiskRatio=1.4),
            seeded_variant(root, "mgc_short_loose_maxtrades4", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, MaxTradesPerDay=4),
            seeded_variant(root, "mgc_short_veryloose", seed, MinVolumeFactor=1.3, ShockAtrMult=0.9, ExtensionAtr=0.5),
            seeded_variant(root, "mgc_short_loose_body45", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, MinBodyFraction=0.45),
            seeded_variant(root, "mgc_short_loose_adx45", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6, MaxAdx=45.0),
            variant(root, "mgc_both_morning_noext", EnableLong=True, EnableShort=True, TradeStartTime=635, TradeEndTime=1000, MinVolumeFactor=1.6, ShockAtrMult=1.1, ExtensionAtr=0.8, RequireNoExtremeBreak=True),
            variant(root, "mgc_both_morning_confirm20", EnableLong=True, EnableShort=True, TradeStartTime=635, TradeEndTime=1000, MinVolumeFactor=1.6, ShockAtrMult=1.1, ExtensionAtr=0.8, MinConfirmBodyFraction=0.20),
        ]

    if root == "MBT":
        seed = {
            "EnableLong": True,
            "EnableShort": True,
            "TradeStartTime": 635,
            "TradeEndTime": 1000,
            "MinVolumeFactor": 1.6,
            "ShockAtrMult": 1.1,
            "ExtensionAtr": 0.8,
            "RewardRiskRatio": 1.25,
            "MaxStopTicks": 300,
        }
        return [
            seeded_variant(root, "mbt_both_seed", seed),
            seeded_variant(root, "mbt_both_noext", seed, RequireNoExtremeBreak=True),
            seeded_variant(root, "mbt_both_noext_confirm20", seed, RequireNoExtremeBreak=True, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mbt_both_confirm20", seed, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mbt_both_adx45", seed, MaxAdx=45.0),
            seeded_variant(root, "mbt_both_adx35", seed, MaxAdx=35.0),
            seeded_variant(root, "mbt_both_reclaimopen", seed, RequireReclaimPrevOpen=True),
            seeded_variant(root, "mbt_both_vwapreclaim", seed, RequireVwapReclaim=True),
            seeded_variant(root, "mbt_both_0000_1320", seed, TradeStartTime=0, TradeEndTime=1320),
            seeded_variant(root, "mbt_both_0600_0930", seed, TradeStartTime=600, TradeEndTime=930),
            seeded_variant(root, "mbt_both_0700_1100", seed, TradeStartTime=700, TradeEndTime=1100),
            seeded_variant(root, "mbt_both_loose", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6),
            seeded_variant(root, "mbt_both_strict", seed, MinVolumeFactor=2.0, ShockAtrMult=1.3, ExtensionAtr=1.0),
            seeded_variant(root, "mbt_both_rr100_hold08", seed, RewardRiskRatio=1.0, MaxHoldBars=8),
            seeded_variant(root, "mbt_both_rr150", seed, RewardRiskRatio=1.5),
            seeded_variant(root, "mbt_short_seed", seed, EnableLong=False, EnableShort=True, RewardRiskRatio=1.2),
            seeded_variant(root, "mbt_short_noext", seed, EnableLong=False, EnableShort=True, RequireNoExtremeBreak=True, RewardRiskRatio=1.2),
            seeded_variant(root, "mbt_long_seed", seed, EnableLong=True, EnableShort=False, RewardRiskRatio=1.2),
            seeded_variant(root, "mbt_both_reclaimopen_noext", seed, RequireReclaimPrevOpen=True, RequireNoExtremeBreak=True),
            seeded_variant(root, "mbt_both_reclaimopen_confirm20", seed, RequireReclaimPrevOpen=True, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mbt_both_reclaimopen_noext_confirm20", seed, RequireReclaimPrevOpen=True, RequireNoExtremeBreak=True, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mbt_both_reclaimopen_adx45", seed, RequireReclaimPrevOpen=True, MaxAdx=45.0),
            seeded_variant(root, "mbt_both_reclaimopen_0600_0930", seed, RequireReclaimPrevOpen=True, TradeStartTime=600, TradeEndTime=930),
            seeded_variant(root, "mbt_both_reclaimopen_0700_1100", seed, RequireReclaimPrevOpen=True, TradeStartTime=700, TradeEndTime=1100),
            seeded_variant(root, "mbt_both_reclaimopen_rr100_hold08", seed, RequireReclaimPrevOpen=True, RewardRiskRatio=1.0, MaxHoldBars=8),
            seeded_variant(root, "mbt_both_reclaimopen_rr150", seed, RequireReclaimPrevOpen=True, RewardRiskRatio=1.5),
            seeded_variant(root, "mbt_both_reclaimopen_maxtrades4", seed, RequireReclaimPrevOpen=True, MaxTradesPerDay=4),
            seeded_variant(root, "mbt_both_reclaimopen_loose", seed, RequireReclaimPrevOpen=True, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6),
            seeded_variant(root, "mbt_short_reclaimopen", seed, EnableLong=False, EnableShort=True, RequireReclaimPrevOpen=True, RewardRiskRatio=1.2),
            seeded_variant(root, "mbt_long_reclaimopen", seed, EnableLong=True, EnableShort=False, RequireReclaimPrevOpen=True, RewardRiskRatio=1.2),
        ]

    if root == "MES":
        seed = {
            "EnableLong": True,
            "EnableShort": True,
            "TradeStartTime": 900,
            "TradeEndTime": 1230,
            "MinVolumeFactor": 1.8,
            "ShockAtrMult": 1.2,
            "ExtensionAtr": 0.9,
            "RewardRiskRatio": 1.25,
        }
        return [
            seeded_variant(root, "mes_midday_seed", seed),
            seeded_variant(root, "mes_midday_noext", seed, RequireNoExtremeBreak=True),
            seeded_variant(root, "mes_midday_noext_confirm20", seed, RequireNoExtremeBreak=True, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mes_midday_confirm20", seed, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mes_midday_adx45", seed, MaxAdx=45.0),
            seeded_variant(root, "mes_midday_0830_1130", seed, TradeStartTime=830, TradeEndTime=1130),
            seeded_variant(root, "mes_midday_0930_1230", seed, TradeStartTime=930),
            seeded_variant(root, "mes_midday_loose", seed, MinVolumeFactor=1.5, ShockAtrMult=1.0, ExtensionAtr=0.7),
            seeded_variant(root, "mes_midday_strict", seed, MinVolumeFactor=2.2, ShockAtrMult=1.4, ExtensionAtr=1.1),
            seeded_variant(root, "mes_short_midday", seed, EnableLong=False, EnableShort=True, RewardRiskRatio=1.2),
            seeded_variant(root, "mes_long_midday", seed, EnableLong=True, EnableShort=False, RewardRiskRatio=1.2),
            seeded_variant(root, "mes_fast_exit", seed, RewardRiskRatio=1.0, MaxHoldBars=8),
        ]

    if root == "MNQ":
        seed = {
            "EnableLong": False,
            "EnableShort": True,
            "TradeStartTime": 635,
            "TradeEndTime": 1000,
            "MinVolumeFactor": 1.6,
            "ShockAtrMult": 1.1,
            "ExtensionAtr": 0.8,
            "RewardRiskRatio": 1.2,
        }
        return [
            seeded_variant(root, "mnq_short_seed", seed),
            seeded_variant(root, "mnq_short_noext", seed, RequireNoExtremeBreak=True),
            seeded_variant(root, "mnq_short_noext_confirm20", seed, RequireNoExtremeBreak=True, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mnq_short_confirm20", seed, MinConfirmBodyFraction=0.20),
            seeded_variant(root, "mnq_short_adx45", seed, MaxAdx=45.0),
            seeded_variant(root, "mnq_short_adx35", seed, MaxAdx=35.0),
            seeded_variant(root, "mnq_short_0600_0930", seed, TradeStartTime=600, TradeEndTime=930),
            seeded_variant(root, "mnq_short_0700_1030", seed, TradeStartTime=700, TradeEndTime=1030),
            seeded_variant(root, "mnq_short_loose", seed, MinVolumeFactor=1.4, ShockAtrMult=0.95, ExtensionAtr=0.6),
            seeded_variant(root, "mnq_short_strict", seed, MinVolumeFactor=2.0, ShockAtrMult=1.3, ExtensionAtr=1.0),
            seeded_variant(root, "mnq_short_rr100_hold08", seed, RewardRiskRatio=1.0, MaxHoldBars=8),
            variant(root, "mnq_both_morning", EnableLong=True, EnableShort=True, TradeStartTime=635, TradeEndTime=1000, MinVolumeFactor=1.6, ShockAtrMult=1.1, ExtensionAtr=0.8),
        ]

    return []


def score_row(row: Dict[str, Any]) -> float:
    trades = float(row.get("trade_count") or 0.0)
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("adj_dd") or 0.0))
    if trades < 10:
        return -999999.0 + net
    return (net * max(0.25, pf)) / max(150.0, dd)


def row_from_submission(sub: Dict[str, Any]) -> Dict[str, Any]:
    row = CAP.row_from_submission(sub)
    p = sub.get("params") or {}
    row.update({
        "max_adx": p.get("MaxAdx"),
        "confirm_body": p.get("MinConfirmBodyFraction"),
        "no_extreme_break": p.get("RequireNoExtremeBreak"),
        "reclaim_prev_open": p.get("RequireReclaimPrevOpen"),
        "vwap_reclaim": p.get("RequireVwapReclaim"),
    })
    row["score"] = round(score_row(row), 6)
    return row


def rank_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(row: Dict[str, Any]) -> Tuple[float, float, float, float, float]:
        trades = float(row.get("trade_count") or 0.0)
        net = float(row.get("adj_net") or 0.0)
        pf = float(row.get("adj_pf") or 0.0)
        return (
            1.0 if trades >= 25 else 0.0,
            1.0 if net > 0.0 and pf >= 1.03 else 0.0,
            score_row(row),
            net,
            pf,
        )

    ranked = sorted(rows, key=key, reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def specs_for(roots: List[str]) -> Tuple[List[CAP.InstrumentSpec], List[Dict[str, Any]]]:
    specs: List[CAP.InstrumentSpec] = []
    skipped: List[Dict[str, Any]] = []
    for root in roots:
        try:
            front = RL.resolve_front_contract(root)
            instrument = str(front.get("instrument") or front.get("symbol") or "")
            if not instrument:
                skipped.append({"root": root, "reason": "no_front_contract"})
                continue
            specs.append(CAP.InstrumentSpec(root=root, instrument=instrument, session_template=RL.session_for(root)))
        except Exception as exc:
            skipped.append({"root": root, "reason": str(exc)})
    return specs, skipped


def submit_focus(bundle: Path, roots: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    specs, skipped = specs_for(roots)
    submissions: List[Dict[str, Any]] = []
    for spec in specs:
        for var in focused_variants_for(spec.root):
            submissions.append(CAP.submit_job(
                spec=spec,
                variant=var,
                stage="Focus2025",
                from_utc=FROM_FOCUS,
                to_utc=TO_FOCUS,
            ))
    (bundle / "skipped_instruments.json").write_text(json.dumps(skipped, indent=2), encoding="utf-8")
    (bundle / "focus_submissions.json").write_text(json.dumps(submissions, indent=2), encoding="utf-8")
    CAP.wait_for_jobs([s["job_id"] for s in submissions if s.get("job_id")])
    rows = rank_rows([row_from_submission(s) for s in submissions])
    write_csv(bundle / "focus_rows.csv", rows)
    (bundle / "focus_rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows, submissions


def top_candidates(rows: List[Dict[str, Any]], submissions: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    by_job = {s.get("job_id"): s for s in submissions}
    candidates: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        if len(candidates) >= limit:
            break
        if float(row.get("trade_count") or 0.0) < 25:
            continue
        if float(row.get("adj_net") or 0.0) <= 0.0:
            continue
        if float(row.get("adj_pf") or 0.0) < 1.03:
            continue
        key = (row.get("root"), row.get("variant"))
        if key in seen:
            continue
        sub = by_job.get(row.get("job_id"))
        if sub:
            candidates.append(sub)
            seen.add(key)
    return candidates


def submit_validation(bundle: Path, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    submissions: List[Dict[str, Any]] = []
    for cand in candidates:
        spec = CAP.InstrumentSpec(
            root=str(cand["root"]),
            instrument=str(cand["instrument"]),
            session_template=str(cand["session_template"]),
        )
        var = CAP.Variant(name=str(cand["variant"]), params=dict(cand["params"]))
        submissions.append(CAP.submit_job(spec=spec, variant=var, stage="Full2024_2025", from_utc=CAP.FROM_FULL, to_utc=CAP.TO_FULL))
        submissions.append(CAP.submit_job(spec=spec, variant=var, stage="IS2024", from_utc=CAP.FROM_IS, to_utc=CAP.TO_IS))
        submissions.append(CAP.submit_job(spec=spec, variant=var, stage="OOS2025", from_utc=CAP.FROM_OOS, to_utc=CAP.TO_OOS))
        submissions.append(CAP.submit_job(spec=spec, variant=var, stage="StressSlip2", from_utc=CAP.FROM_FULL, to_utc=CAP.TO_FULL, slippage_ticks=2))
        submissions.append(CAP.submit_job(spec=spec, variant=var, stage="StressFee2x", from_utc=CAP.FROM_FULL, to_utc=CAP.TO_FULL, fee=RL.fee_for(spec.root) * 2.0))
        current_from, current_to = CAP.current_window(spec.root)
        submissions.append(CAP.submit_job(spec=spec, variant=var, stage="CurrentFront", from_utc=current_from, to_utc=current_to))

    (bundle / "validation_submissions.json").write_text(json.dumps(submissions, indent=2), encoding="utf-8")
    CAP.wait_for_jobs([s["job_id"] for s in submissions if s.get("job_id")])
    rows = rank_rows([row_from_submission(s) for s in submissions])
    write_csv(bundle / "validation_rows.csv", rows)
    (bundle / "validation_rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def write_summary(bundle: Path, focus_rows: List[Dict[str, Any]], validation_rows: List[Dict[str, Any]]) -> None:
    lines = [
        "# Capitulation Snapback Focused Refinement",
        "",
        f"- Bundle: `{bundle}`",
        f"- Class: `{CAP.CLASS_NAME}`",
        f"- Focus period: `{FROM_FOCUS}` .. `{TO_FOCUS}`",
        f"- Roots: `{', '.join(sorted({str(r.get('root')) for r in focus_rows}))}`",
        "",
        "## Focus Top",
        "",
        "| Rank | Root | Instrument | Variant | Trades | Adj Net | PF | DD | Win % | Score |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in focus_rows[:15]:
        lines.append(
            f"| {row['rank']} | `{row['root']}` | `{row['instrument']}` | `{row['variant']}` | "
            f"{row['trade_count']} | {float(row['adj_net']):.2f} | {float(row['adj_pf']):.2f} | "
            f"{float(row['adj_dd']):.2f} | {float(row['win_pct']):.2f} | {float(row['score']):.3f} |"
        )

    if validation_rows:
        lines.extend([
            "",
            "## Validation",
            "",
            "| Rank | Stage | Root | Variant | Trades | Adj Net | PF | DD | Win % | Score |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
        ])
        for row in validation_rows:
            lines.append(
                f"| {row['rank']} | `{row['stage']}` | `{row['root']}` | `{row['variant']}` | "
                f"{row['trade_count']} | {float(row['adj_net']):.2f} | {float(row['adj_pf']):.2f} | "
                f"{float(row['adj_dd']):.2f} | {float(row['win_pct']):.2f} | {float(row['score']):.3f} |"
            )

    (bundle / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (bundle / "summary.json").write_text(json.dumps({
        "bundle": str(bundle),
        "focus_top": focus_rows[:15],
        "validation_rows": validation_rows,
    }, indent=2), encoding="utf-8")
    print("\n".join(lines), flush=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roots", nargs="*", default=FOCUS_ROOTS)
    parser.add_argument("--validate-top", type=int, default=4)
    args = parser.parse_args(argv)

    bundle = RL.PROJECT_ROOT / "data" / "research" / f"capitulation_snapback_refine_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)

    focus_rows, submissions = submit_focus(bundle, [str(r).upper() for r in args.roots])
    candidates = top_candidates(focus_rows, submissions, max(0, args.validate_top))
    validation_rows = submit_validation(bundle, candidates) if candidates else []
    write_summary(bundle, focus_rows, validation_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
