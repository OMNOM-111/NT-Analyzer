"""Audit and repair attempt for failed MNQ CELL-015 / CELL-016 paper-forward.

The goal is to separate three questions:
  1. Did the original profiles fail only after the validation cutoff?
  2. Does realistic live-like slippage erase the apparent edge?
  3. Are there conservative copy variants worth keeping as research candidates?

Outputs are written under data/research/mnq_c015_c016_failure_audit_<stamp>/.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402


ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z", 1, 1.90)
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z", 1, 1.90)
CURRENT_PRE = ("CurrentPrePaper", "2026-04-13T00:00:00Z", "2026-05-13T23:59:59Z", 1, 1.90)
FORWARD = ("ForwardPaperWindow", "2026-05-14T00:00:00Z", "2026-05-25T23:59:59Z", 1, 1.90)
FORWARD_SLIP3 = ("ForwardSlip3", "2026-05-14T00:00:00Z", "2026-05-25T23:59:59Z", 3, 1.90)
FORWARD_SLIP5 = ("ForwardSlip5", "2026-05-14T00:00:00Z", "2026-05-25T23:59:59Z", 5, 2.40)
FULL_SLIP3 = ("FullSlip3", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z", 3, 1.90)
FULL_SLIP5 = ("FullSlip5Fee240", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z", 5, 2.40)

CSV_FIELDS = [
    "variant_id",
    "source_cell",
    "copy_cell",
    "class_name",
    "stage",
    "job_id",
    "status",
    "trade_count",
    "active_days_pct",
    "adj_net",
    "adj_pf",
    "adj_dd",
    "win_pct",
    "avg_trade",
    "max_consecutive_losses",
    "slippage_ticks",
    "round_turn_commission",
]


@dataclass(frozen=True)
class Variant:
    variant_id: str
    source_cell: str
    copy_cell: str
    class_name: str
    display_name: str
    params: Dict[str, Any]
    note: str


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def load_profile_params(cell_id: str) -> Dict[str, Any]:
    data = json.loads((RL.PROJECT_ROOT / "data" / "profiles" / "strategies.json").read_text(encoding="utf-8"))
    for profile in data.get("profiles", []):
        if profile.get("cell_id") == cell_id:
            return dict(profile.get("locked_parameters") or {})
    raise RuntimeError(f"profile not found for {cell_id}")


def c015_copy_params(base: Dict[str, Any], *, strict: bool, end_time: int, stop_min: int, stop_max: int,
                     rr: float, volume: float, entry_offset: int) -> Dict[str, Any]:
    p = dict(base)
    p.update({
        "TradeStartTime": 635,
        "TradeEndTime": end_time,
        "ForceFlatTime": 1300,
        "OpenPressureMinScore": 2 if strict else 1,
        "SweepLookbackBars": 4 if strict else 3,
        "MomentumLookbackBars": 2 if strict else 1,
        "MinBarRangeTicks": 3 if strict else 2,
        "MinBodyRangePct": 0.05 if strict else 0.0,
        "MinCloseLocationPct": 0.25 if strict else 0.20,
        "MinVolumeFactor": volume,
        "StopBufferTicks": 2 if strict else 1,
        "MinStopTicks": stop_min,
        "MaxStopTicks": stop_max,
        "RewardRiskRatio": rr,
        "EntryOffsetTicks": entry_offset,
        "EntryTimeoutBars": 1,
        "DailyLossLimit": 25.0,
        "WeeklyLossLimit": 75.0,
        "MaxTradesPerDay": 6,
        "HardMaxTradesPerDay": 8,
        "MaxConsecutiveLosses": 2,
        "PauseAfterConsecutiveLosses": 1,
        "PauseMinutesAfterLosses": 30,
        "SlippageTicks": 3,
    })
    return p


def c016_copy_params(base: Dict[str, Any], *, module: str, end_time: int, stop_min: int,
                     stop_max: int, rr: float, volume: float) -> Dict[str, Any]:
    p = dict(base)
    p.update({
        "TradeStartTime": 635,
        "TradeEndTime": end_time,
        "ForceFlatTime": 1300,
        "UseSetupModeFilter": False,
        "EnableLong": False,
        "EnableShort": True,
        "EnableVwapReclaim": module in {"all", "vwap", "vwap_fail"},
        "EnableEmaMomentum": module in {"all", "ema", "ema_fail"},
        "EnableMicroOrb": module in {"all", "orb", "orb_fail"},
        "EnableFailedBreakout": module in {"all", "fail", "vwap_fail", "ema_fail", "orb_fail"},
        "MinStopTicks": stop_min,
        "MaxStopTicks": stop_max,
        "RewardRiskRatio": rr,
        "MinVolumeFactor": volume,
        "EntryOffsetTicks": 1,
        "EntryTimeoutBars": 1,
        "MaxDailyLossUsd": 25.0,
        "MaxWeeklyLossUsd": 75.0,
        "MaxTradesPerDay": 6,
        "HardMaxTradesPerDay": 8,
        "MaxConsecutiveLosses": 2,
        "PauseAfterConsecutiveLosses": 1,
        "PauseMinutesAfterLosses": 30,
        "SlippageTicks": 3,
    })
    return p


def build_variants() -> List[Variant]:
    c015 = load_profile_params("CELL-015")
    c016 = load_profile_params("CELL-016")
    out = [
        Variant(
            "c015_original_deployed",
            "CELL-015",
            "CELL-015",
            "NTAMnqLiquiditySweepReversalC015",
            "Scalping Open Pressure Stop MNQ 1m v1 c015",
            c015,
            "Original rejected deployed profile.",
        ),
        Variant(
            "c016_original_deployed",
            "CELL-016",
            "CELL-016",
            "NTAMnqOpenDriveShortScalpC016",
            "Scalping Open Drive Short MNQ 1m v1 c016",
            c016,
            "Original rejected deployed wrapper profile.",
        ),
        Variant(
            "c015_copy_c019_strict_score2_offset",
            "CELL-015",
            "CELL-019",
            "NTAMnqLiquiditySweepReversalC015",
            "Copy of C015 FIXED Open Pressure MNQ 1m v1 c019",
            c015_copy_params(c015, strict=True, end_time=830, stop_min=6, stop_max=14, rr=3.0, volume=0.8, entry_offset=1),
            "C015 repair: stricter score/body/volume, wider stop box, one-tick stop-entry confirmation, hard daily throttle.",
        ),
        Variant(
            "c015_copy_c019_strict_0700",
            "CELL-015",
            "CELL-019",
            "NTAMnqLiquiditySweepReversalC015",
            "Copy of C015 FIXED Open Pressure Early MNQ 1m v1 c019",
            c015_copy_params(c015, strict=True, end_time=700, stop_min=6, stop_max=14, rr=3.0, volume=0.8, entry_offset=1),
            "C015 repair: same stricter filters but only first 25 minutes after 06:35.",
        ),
        Variant(
            "c016_copy_c020_fail_only",
            "CELL-016",
            "CELL-020",
            "NTAMicroMnqScalpPilot",
            "Copy of C016 FIXED Failed Breakout MNQ 1m v1 c020",
            c016_copy_params(c016, module="fail", end_time=700, stop_min=6, stop_max=14, rr=2.0, volume=1.0),
            "C016 repair: removes all-module stacking, keeps only failed-breakout short branch with stricter liquidity and throttles.",
        ),
        Variant(
            "c016_copy_c020_orb_fail",
            "CELL-016",
            "CELL-020",
            "NTAMicroMnqScalpPilot",
            "Copy of C016 FIXED ORB/Fail MNQ 1m v1 c020",
            c016_copy_params(c016, module="orb_fail", end_time=700, stop_min=6, stop_max=14, rr=2.0, volume=1.0),
            "C016 repair: narrows to ORB + failed-breakout short modules, early-only, wider stops, hard daily throttle.",
        ),
    ]
    return out


def submit_job(variant: Variant, stage: str, from_utc: str, to_utc: str, slip: int, fee: float) -> Dict[str, Any]:
    params = dict(variant.params)
    params.update({
        "RoundTurnCommission": fee,
        "SlippageTicks": slip,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "InstrumentStatus": "allowed",
        "MaxContractsByCapital": 20,
    })
    body = RL.build_job_body(
        class_name=variant.class_name,
        instrument=INSTRUMENT,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=slip,
        role="research",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = str(resp.get("job_id") or "") if code == 201 and isinstance(resp, dict) else ""
    print(f"submit {variant.variant_id:34s} {stage:20s} slip={slip} fee={fee:.2f} code={code} job={job_id}", flush=True)
    return {
        "variant_id": variant.variant_id,
        "source_cell": variant.source_cell,
        "copy_cell": variant.copy_cell,
        "class_name": variant.class_name,
        "display_name": variant.display_name,
        "note": variant.note,
        "stage": stage,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "slippage_ticks": slip,
        "round_turn_commission": fee,
        "code": code,
        "response": resp,
        "job_id": job_id,
        "params": params,
    }


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
            print(f"waiting: {len(remaining)} audit jobs still pending/running", flush=True)
            last_print = now
        if remaining:
            time.sleep(interval_s)


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
    start = datetime.fromisoformat(from_utc[:10]).date()
    end = datetime.fromisoformat(to_utc[:10]).date()
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days += 1
        cur = cur.fromordinal(cur.toordinal() + 1)
    return max(1, days)


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
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = sum(p for p in pnls if p < 0)
    net = sum(pnls)
    pf = gross_profit / abs(gross_loss) if gross_loss < 0 else (999.0 if gross_profit > 0 else 0.0)
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
    day_count = weekdays(from_utc, to_utc)
    return {
        "trade_count": len(pnls),
        "active_days": len(active_days),
        "active_days_pct": round(len(active_days) / day_count * 100.0, 4),
        "adj_net": round(net, 6),
        "adj_pf": round(pf, 6),
        "adj_dd": round(dd, 6),
        "win_pct": round(wins / len(pnls) * 100.0, 4) if pnls else 0.0,
        "avg_trade": round(net / len(pnls), 6) if pnls else 0.0,
        "max_consecutive_losses": max_losses,
    }


def row_from_submission(sub: Dict[str, Any]) -> Dict[str, Any]:
    row = {k: sub.get(k) for k in (
        "variant_id", "source_cell", "copy_cell", "class_name", "display_name",
        "note", "stage", "job_id", "from_utc", "to_utc", "slippage_ticks",
        "round_turn_commission",
    )}
    row["status"] = job_state(str(sub.get("job_id") or "")) or "missing"
    report = RL.read_job_report(str(sub.get("job_id") or ""))
    if not report or "result" not in report:
        row.update({
            "trade_count": 0,
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


def verdict(rows: Dict[str, Dict[str, Any]], source_cell: str, copy_cell: str) -> Dict[str, Any]:
    full = rows.get("Full", {})
    current = rows.get("CurrentPrePaper", {})
    forward = rows.get("ForwardPaperWindow", {})
    f3 = rows.get("ForwardSlip3", {})
    f5 = rows.get("ForwardSlip5", {})
    fs3 = rows.get("FullSlip3", {})
    failed: List[str] = []
    if copy_cell == source_cell:
        failed.append("original_rejected_profile_forensic_only")
    if float(full.get("adj_net") or 0.0) <= 0.0:
        failed.append("full_net_positive")
    if float(full.get("adj_pf") or 0.0) < 1.35:
        failed.append("full_pf_ge_1_35")
    if float(current.get("adj_net") or 0.0) <= 0.0:
        failed.append("current_pre_paper_positive")
    if float(forward.get("adj_net") or 0.0) <= 0.0:
        failed.append("forward_paper_window_positive")
    if float(f3.get("adj_net") or 0.0) <= 0.0:
        failed.append("forward_slip3_positive")
    if float(f5.get("adj_net") or 0.0) <= 0.0:
        failed.append("forward_slip5_fee240_positive")
    if float(fs3.get("adj_net") or 0.0) <= 0.0:
        failed.append("full_slip3_positive")
    max_dd = 350.0 if source_cell == "CELL-016" else 450.0
    if abs(float(full.get("adj_dd") or 0.0)) > max_dd:
        failed.append(f"full_dd_le_{int(max_dd)}")
    return {
        "ready_pass": not failed,
        "decision": "paper_retest_candidate" if not failed else "research_only",
        "failed_gates": failed,
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    bundle = RL.PROJECT_ROOT / "data" / "research" / f"mnq_c015_c016_failure_audit_{utc_stamp()}"
    bundle.mkdir(parents=True, exist_ok=True)
    variants = build_variants()
    plans = [FULL, OOS, CURRENT_PRE, FORWARD, FORWARD_SLIP3, FORWARD_SLIP5, FULL_SLIP3, FULL_SLIP5]

    print(f"bundle: {bundle}", flush=True)
    print(f"variants: {len(variants)} jobs={len(variants) * len(plans)}", flush=True)
    submissions: List[Dict[str, Any]] = []
    for variant in variants:
        for stage, from_utc, to_utc, slip, fee in plans:
            submissions.append(submit_job(variant, stage, from_utc, to_utc, slip, fee))
    (bundle / "submissions.json").write_text(json.dumps(submissions, indent=2), encoding="utf-8")
    wait_for_jobs([s.get("job_id") for s in submissions if s.get("job_id")])

    rows = [row_from_submission(s) for s in submissions]
    write_csv(bundle / "rows.csv", rows)
    (bundle / "rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    decisions: List[Dict[str, Any]] = []
    params_by_variant = {v.variant_id: v.params for v in variants}
    for variant in variants:
        stage_rows = {r["stage"]: r for r in rows if r["variant_id"] == variant.variant_id}
        d = {
            "variant_id": variant.variant_id,
            "source_cell": variant.source_cell,
            "copy_cell": variant.copy_cell,
            "class_name": variant.class_name,
            "display_name": variant.display_name,
            "note": variant.note,
            "locked_parameters": params_by_variant[variant.variant_id],
            "rows": stage_rows,
        }
        d.update(verdict(stage_rows, variant.source_cell, variant.copy_cell))
        decisions.append(d)
    decisions.sort(key=lambda d: (
        1 if d["ready_pass"] else 0,
        float((d["rows"].get("ForwardPaperWindow") or {}).get("adj_net") or -999999),
        float((d["rows"].get("FullSlip3") or {}).get("adj_net") or -999999),
    ), reverse=True)
    (bundle / "decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    summary = {
        "bundle": str(bundle),
        "ready": [d["variant_id"] for d in decisions if d["ready_pass"]],
        "best": decisions[0] if decisions else None,
        "decisions": [
            {
                "variant_id": d["variant_id"],
                "decision": d["decision"],
                "failed_gates": d["failed_gates"],
                "forward_net": (d["rows"].get("ForwardPaperWindow") or {}).get("adj_net"),
                "forward_pf": (d["rows"].get("ForwardPaperWindow") or {}).get("adj_pf"),
                "full_net": (d["rows"].get("Full") or {}).get("adj_net"),
                "full_pf": (d["rows"].get("Full") or {}).get("adj_pf"),
                "full_slip3_net": (d["rows"].get("FullSlip3") or {}).get("adj_net"),
            }
            for d in decisions
        ],
    }
    (bundle / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["decisions"], indent=2), flush=True)
    return 0 if summary["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
