"""Run MGC strategy-2 research from the MNQ CELL-011 / B1 family.

This script uses `NTAMicroVwapRiskExplorer`, which preserves the MNQ B1 VWAP
entry/management logic without the backend hard-lock that is applied to
`NTAMicroVwapRiskPilot`.

Important operational note:
  - The local templates catalog still marks `Nymex Metals RTH1` as
    `supported=false`, so the backend rejects `role="research"` jobs for that
    template.
  - We therefore submit MGC jobs as `role="smoke"` even though execution
    settings remain research-grade: High fill, slippage >= 1, and explicit
    `RoundTurnCommission`.
  - This affects backend validation only, not the NinjaTrader-side metrics.

Outputs a reproducible bundle under `data/research/mgc_b1_clone_v2_<ts>/`:
  - `manifest.json`
  - `all_tests.json`
  - `all_tests.csv`
  - `stress_tests.json`
  - `summary.md`
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402


CLASS_NAME = "NTAMicroVwapRiskExplorer"
ROOT = "MGC"
SESSION_TEMPLATE = "Nymex Metals RTH1"
ROLE = "smoke"

FROM_FULL = "2024-01-01T00:00:00Z"
TO_FULL = "2025-12-31T23:59:59Z"
FROM_IS = "2024-01-01T00:00:00Z"
TO_IS = "2024-12-31T23:59:59Z"
FROM_OOS = "2025-01-01T00:00:00Z"
TO_OOS = "2025-12-31T23:59:59Z"

BUNDLE_ROOT = RL.DATA / "research"

CSV_FIELDS = [
    "stage",
    "variant",
    "job_id",
    "status",
    "instrument",
    "from_utc",
    "to_utc",
    "session_template",
    "role",
    "direction",
    "trade_start_time",
    "trade_end_time",
    "min_stop_ticks",
    "max_stop_ticks",
    "reward_risk_ratio",
    "min_adx",
    "min_volume_factor",
    "pullback_lookback",
    "entry_offset_ticks",
    "slippage_ticks",
    "round_turn_commission",
    "trade_count",
    "gross_net_profit",
    "commission_total",
    "net_profit_after_commission",
    "profit_factor_after_commission",
    "max_drawdown_after_commission",
    "winning_pct_after_commission",
]


@dataclass
class Variant:
    name: str
    params: Dict[str, Any]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value: str) -> str:
    safe = []
    for ch in value.lower():
        if ch.isalnum():
            safe.append(ch)
        else:
            safe.append("_")
    out = "".join(safe)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")[:60]


def _job_state(job_id: str) -> Optional[str]:
    jobs = RL.jobs_root()
    for sub in ("done", "failed", "cancelled", "running", "pending"):
        if (jobs / sub / job_id).is_dir():
            return sub
    return None


def _wait_for_jobs(job_ids: Iterable[str], timeout_s: int = 7200,
                   interval_s: int = 3) -> Dict[str, str]:
    remaining = set(job_ids)
    states: Dict[str, str] = {}
    deadline = time.time() + timeout_s
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            state = _job_state(job_id)
            if state in {"done", "failed", "cancelled"}:
                states[job_id] = state
                remaining.remove(job_id)
        if remaining:
            time.sleep(interval_s)
    return states


def _trade_adjusted_metrics(report: Dict[str, Any],
                            fallback_rtc: float) -> Dict[str, Any]:
    result = report.get("result") or {}
    metrics = dict(result.get("metrics") or {})
    trades = result.get("trades") or []
    if not isinstance(trades, list):
        trades = []

    if trades:
        net_trades: List[float] = []
        win = 0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for trade in trades:
            gross = float(trade.get("pnl_currency") or 0.0)
            qty = abs(int(trade.get("quantity") or 0))
            comm = trade.get("commission")
            if comm in (None, ""):
                comm = fallback_rtc * qty
            comm = float(comm or 0.0)
            net = gross - comm
            net_trades.append(net)
            if net > 0:
                win += 1
            equity += net
            peak = max(peak, equity)
            max_dd = min(max_dd, equity - peak)

        gross_profit = sum(x for x in net_trades if x > 0)
        gross_loss = sum(x for x in net_trades if x < 0)
        pf = (gross_profit / abs(gross_loss)) if gross_loss < 0 else (999.0 if gross_profit > 0 else 1.0)
        return {
            "trade_count": len(net_trades),
            "gross_net_profit": float(metrics.get("net_profit") or sum(float(t.get("pnl_currency") or 0.0) for t in trades)),
            "commission_total": round(sum(float(trade.get("commission") or (fallback_rtc * abs(int(trade.get("quantity") or 0)))) for trade in trades), 6),
            "net_profit_after_commission": round(sum(net_trades), 6),
            "profit_factor_after_commission": round(pf, 6),
            "max_drawdown_after_commission": round(max_dd, 6),
            "winning_pct_after_commission": round((100.0 * win / len(net_trades)) if net_trades else 0.0, 4),
        }

    return {
        "trade_count": int(metrics.get("trade_count") or 0),
        "gross_net_profit": float(metrics.get("net_profit") or 0.0),
        "commission_total": float(metrics.get("commission_total_adjusted") or 0.0),
        "net_profit_after_commission": float(metrics.get("net_profit_after_commission") or metrics.get("adjusted_net_profit") or metrics.get("net_profit") or 0.0),
        "profit_factor_after_commission": float(metrics.get("profit_factor_after_commission") or metrics.get("adjusted_profit_factor") or metrics.get("profit_factor") or 1.0),
        "max_drawdown_after_commission": float(metrics.get("max_drawdown_after_commission") or metrics.get("adjusted_max_drawdown") or metrics.get("max_drawdown") or 0.0),
        "winning_pct_after_commission": float(metrics.get("win_pct_after_commission") or metrics.get("winning_pct") or 0.0),
    }


def _build_row(stage: str, variant_name: str, job_id: str,
               report: Dict[str, Any]) -> Dict[str, Any]:
    job = report.get("job") or {}
    strat = job.get("strategy") or {}
    params = strat.get("parameters") or {}
    exec_ = job.get("execution") or {}
    adj = _trade_adjusted_metrics(report, float(params.get("RoundTurnCommission") or RL.fee_for(ROOT)))
    return {
        "stage": stage,
        "variant": variant_name,
        "job_id": job_id,
        "status": _job_state(job_id) or "missing",
        "instrument": job.get("instrument"),
        "from_utc": (job.get("period") or {}).get("from_utc"),
        "to_utc": (job.get("period") or {}).get("to_utc"),
        "session_template": exec_.get("session_template"),
        "role": exec_.get("role"),
        "direction": (
            "longshort" if params.get("EnableLong") and params.get("EnableShort")
            else "longonly" if params.get("EnableLong")
            else "shortonly"
        ),
        "trade_start_time": params.get("TradeStartTime"),
        "trade_end_time": params.get("TradeEndTime"),
        "min_stop_ticks": params.get("MinStopTicks"),
        "max_stop_ticks": params.get("MaxStopTicks"),
        "reward_risk_ratio": params.get("RewardRiskRatio"),
        "min_adx": params.get("MinAdx"),
        "min_volume_factor": params.get("MinVolumeFactor"),
        "pullback_lookback": params.get("PullbackLookback"),
        "entry_offset_ticks": params.get("EntryOffsetTicks"),
        "slippage_ticks": exec_.get("slippage_ticks"),
        "round_turn_commission": params.get("RoundTurnCommission"),
        **adj,
    }


def _score(row: Dict[str, Any]) -> float:
    net = float(row.get("net_profit_after_commission") or 0.0)
    pf = float(row.get("profit_factor_after_commission") or 0.0)
    dd = abs(float(row.get("max_drawdown_after_commission") or 0.0))
    trades = float(row.get("trade_count") or 0.0)
    if net <= 0 or pf < 1.0:
        return net - dd
    return (net * pf) + (trades * 4.0) - (dd * 0.35)


def _select_top_candidates(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    eligible = [
        row for row in rows
        if row.get("status") == "done"
        and float(row.get("net_profit_after_commission") or 0.0) > 0.0
        and float(row.get("profit_factor_after_commission") or 0.0) >= 1.05
        and int(row.get("trade_count") or 0) >= 8
    ]
    eligible.sort(key=_score, reverse=True)
    return eligible[:limit]


def _promotion_decision(full_row: Dict[str, Any], stress_rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    reasons: List[str] = []
    trades = int(full_row.get("trade_count") or 0)
    full_net = float(full_row.get("net_profit_after_commission") or 0.0)
    full_pf = float(full_row.get("profit_factor_after_commission") or 0.0)
    full_dd = float(full_row.get("max_drawdown_after_commission") or 0.0)
    is_row = stress_rows.get("is")
    oos_row = stress_rows.get("oos")
    slip_row = stress_rows.get("slip2")
    fee_row = stress_rows.get("fee125")
    current_row = stress_rows.get("current")

    passed = True
    if full_net <= 0:
        passed = False
        reasons.append(f"Full adjusted net <= 0 ({full_net:.2f})")
    if full_pf < 1.35:
        passed = False
        reasons.append(f"Full adjusted PF below gate ({full_pf:.2f} < 1.35)")
    if trades < 30:
        passed = False
        reasons.append(f"Trade count too low ({trades} < 30)")
    if full_dd < -300:
        passed = False
        reasons.append(f"Drawdown too deep ({full_dd:.2f})")

    if not is_row or float(is_row.get("net_profit_after_commission") or 0.0) <= 0:
        passed = False
        reasons.append("IS-2024 not positive")
    if not oos_row or float(oos_row.get("net_profit_after_commission") or 0.0) <= 0:
        passed = False
        reasons.append("OOS-2025 not positive")
    if oos_row and float(oos_row.get("profit_factor_after_commission") or 0.0) < 1.25:
        passed = False
        reasons.append("OOS-2025 PF below 1.25")
    if slip_row and float(slip_row.get("profit_factor_after_commission") or 0.0) < 1.10:
        passed = False
        reasons.append("Slip+1 stress collapses PF below 1.10")
    if fee_row and float(fee_row.get("net_profit_after_commission") or 0.0) <= 0:
        passed = False
        reasons.append("Fee x1.25 stress turns net non-positive")
    if current_row and int(current_row.get("trade_count") or 0) < 2:
        passed = False
        reasons.append("Current-contract 2026 sample has fewer than 2 trades")

    return {
        "passed": passed,
        "reasons": reasons,
    }


def _variant(base: Dict[str, Any], name: str, **overrides: Any) -> Variant:
    params = dict(base)
    params.update(overrides)
    return Variant(name=name, params=params)


def _full_variants() -> List[Variant]:
    base = RL.base_risk_params(ROOT)
    base.update({
        "EnableLong": False,
        "EnableShort": True,
        "TradeStartTime": 635,
        "TradeEndTime": 700,
        "ForceFlatTime": 1245,
        "MinAdx": 22.0,
        "MinVolumeFactor": 1.2,
        "PullbackLookback": 3,
        "AtrStopMult": 0.75,
        "MinStopTicks": 12,
        "MaxStopTicks": 12,
        "RewardRiskRatio": 3.5,
        "EntryOffsetTicks": 2,
        "EntryTimeoutBars": 2,
        "UseDailyBiasFilter": False,
    })
    return [
        _variant(base, "b1_short_0635_0700"),
        _variant(base, "short_0600_0700", TradeStartTime=600, TradeEndTime=700),
        _variant(base, "short_0600_0730", TradeStartTime=600, TradeEndTime=730),
        _variant(base, "short_0600_0800", TradeStartTime=600, TradeEndTime=800),
        _variant(base, "short_0600_1000", TradeStartTime=600, TradeEndTime=1000),
        _variant(base, "short_0630_0730", TradeStartTime=630, TradeEndTime=730),
        _variant(base, "short_0630_0800", TradeStartTime=630, TradeEndTime=800),
        _variant(base, "long_0600_0730", EnableLong=True, EnableShort=False, TradeStartTime=600, TradeEndTime=730),
        _variant(base, "long_0600_0800", EnableLong=True, EnableShort=False, TradeStartTime=600, TradeEndTime=800),
        _variant(base, "long_0600_1000", EnableLong=True, EnableShort=False, TradeStartTime=600, TradeEndTime=1000),
        _variant(base, "longshort_0600_0730", EnableLong=True, EnableShort=True, TradeStartTime=600, TradeEndTime=730),
        _variant(base, "longshort_0600_1000", EnableLong=True, EnableShort=True, TradeStartTime=600, TradeEndTime=1000),
        _variant(base, "short_stop16_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinStopTicks=16, MaxStopTicks=16),
        _variant(base, "short_stop20_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinStopTicks=20, MaxStopTicks=20),
        _variant(base, "short_stop24_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinStopTicks=24, MaxStopTicks=24),
        _variant(base, "short_rr30_0600_1000", TradeStartTime=600, TradeEndTime=1000, RewardRiskRatio=3.0),
        _variant(base, "short_rr40_0600_1000", TradeStartTime=600, TradeEndTime=1000, RewardRiskRatio=4.0),
        _variant(base, "short_adx18_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinAdx=18.0),
        _variant(base, "short_adx26_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinAdx=26.0),
        _variant(base, "short_vf10_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinVolumeFactor=1.0),
        _variant(base, "short_vf14_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinVolumeFactor=1.4),
        _variant(base, "short_pb2_0600_1000", TradeStartTime=600, TradeEndTime=1000, PullbackLookback=2),
        _variant(base, "short_pb4_0600_1000", TradeStartTime=600, TradeEndTime=1000, PullbackLookback=4),
        _variant(base, "short_eo1_0600_1000", TradeStartTime=600, TradeEndTime=1000, EntryOffsetTicks=1),
        _variant(base, "short_eo3_0600_1000", TradeStartTime=600, TradeEndTime=1000, EntryOffsetTicks=3),
        _variant(base, "short_stop24_rr30_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinStopTicks=24, MaxStopTicks=24, RewardRiskRatio=3.0),
        _variant(base, "short_stop16_rr40_0600_0730", TradeStartTime=600, TradeEndTime=730, MinStopTicks=16, MaxStopTicks=16, RewardRiskRatio=4.0),
        _variant(base, "short_adx18_vf10_0600_1000", TradeStartTime=600, TradeEndTime=1000, MinAdx=18.0, MinVolumeFactor=1.0),
        _variant(base, "short_adx26_vf14_0600_0730", TradeStartTime=600, TradeEndTime=730, MinAdx=26.0, MinVolumeFactor=1.4),
        _variant(base, "short_stop20_0600_0800", TradeStartTime=600, TradeEndTime=800, MinStopTicks=20, MaxStopTicks=20),
    ]


def _submit_job(*, job_id: str, instrument: str, params: Dict[str, Any],
                from_utc: str, to_utc: str, slippage_ticks: int,
                role: str) -> Dict[str, Any]:
    risk_profile = RL.build_risk_profile_for([instrument])
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=instrument,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=5,
        slippage_ticks=slippage_ticks,
        role=role,
        session_template=SESSION_TEMPLATE,
        risk_profile=risk_profile,
    )
    body["job_id"] = job_id
    code, resp = RL.post("/api/jobs", body)
    return {
        "code": code,
        "response": resp,
        "request": body,
        "resolved_job_id": str((resp or {}).get("job_id") or job_id),
    }


def _current_contract_window(contract_info: Dict[str, Any]) -> Dict[str, str]:
    start = str(contract_info.get("data_first") or "2026-03-22")
    end = str(contract_info.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return {
        "from_utc": f"{start}T00:00:00Z",
        "to_utc": f"{end}T23:59:59Z",
    }


def _submit_full_stage(bundle_dir: Path, instrument: str, stamp: str) -> List[Dict[str, Any]]:
    submitted: List[Dict[str, Any]] = []
    for idx, variant in enumerate(_full_variants(), start=1):
        job_id = f"mgcb1v2f_{stamp}_{idx:02d}_{_slug(variant.name)}"
        res = _submit_job(
            job_id=job_id,
            instrument=instrument,
            params=variant.params,
            from_utc=FROM_FULL,
            to_utc=TO_FULL,
            slippage_ticks=int(variant.params.get("SlippageTicks") or 1),
            role=ROLE,
        )
        submitted.append({
            "stage": "full",
            "variant": variant.name,
            "requested_job_id": job_id,
            "job_id": res["resolved_job_id"],
            "params": variant.params,
            "submit_code": res["code"],
            "submit_response": res["response"],
        })
    (bundle_dir / "manifest_full_submit.json").write_text(
        json.dumps(submitted, indent=2, ensure_ascii=False), encoding="utf-8")
    return submitted


def _submit_stress_stage(bundle_dir: Path, instrument: str, stamp: str,
                         top_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    current_window = _current_contract_window(RL.resolve_front_contract(ROOT))
    submitted: List[Dict[str, Any]] = []
    for row in top_rows:
        variant_name = str(row["variant"])
        params = next(v.params for v in _full_variants() if v.name == variant_name)
        stages = [
            ("is", FROM_IS, TO_IS, 1, dict(params)),
            ("oos", FROM_OOS, TO_OOS, 1, dict(params)),
            ("slip2", FROM_FULL, TO_FULL, 2, {**params, "SlippageTicks": 2}),
            ("fee125", FROM_FULL, TO_FULL, 1, {**params, "RoundTurnCommission": RL.fee_stress(ROOT)}),
            ("current", current_window["from_utc"], current_window["to_utc"], 1, dict(params)),
        ]
        for label, fr, to_, slip, params_stage in stages:
            job_id = f"mgcb1v2d_{stamp}_{label}_{_slug(variant_name)}"
            res = _submit_job(
                job_id=job_id,
                instrument=instrument,
                params=params_stage,
                from_utc=fr,
                to_utc=to_,
                slippage_ticks=slip,
                role=ROLE,
            )
            submitted.append({
                "stage": label,
                "variant": variant_name,
                "requested_job_id": job_id,
                "job_id": res["resolved_job_id"],
                "params": params_stage,
                "submit_code": res["code"],
                "submit_response": res["response"],
            })
    (bundle_dir / "manifest_stress_submit.json").write_text(
        json.dumps(submitted, indent=2, ensure_ascii=False), encoding="utf-8")
    return submitted


def _read_reports(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in entries:
        report = RL.read_job_report(entry["job_id"])
        if not report:
            rows.append({
                "stage": entry["stage"],
                "variant": entry["variant"],
                "job_id": entry["job_id"],
                "status": _job_state(entry["job_id"]) or "missing",
            })
            continue
        rows.append(_build_row(entry["stage"], entry["variant"], entry["job_id"], report))
    return rows


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in CSV_FIELDS})


def _summary_md(full_rows: List[Dict[str, Any]], stress_rows: List[Dict[str, Any]],
                top_rows: List[Dict[str, Any]], decisions: Dict[str, Dict[str, Any]],
                instrument: str, contract_info: Dict[str, Any]) -> str:
    lines = [
        "# MGC Strategy 2 — MNQ CELL-011 Family Research",
        "",
        f"- Instrument: `{instrument}`",
        f"- Engine family: `{CLASS_NAME}` (MNQ B1 / CELL-011 logic fork)",
        f"- Session template: `{SESSION_TEMPLATE}`",
        f"- Role used for submission: `{ROLE}`",
        "  Validation note: template is still catalog-flagged `supported=false`, so jobs must be queued as `smoke`, but fill/slippage/commission remain research-grade.",
        f"- Current-contract data window: `{contract_info.get('data_first')}` .. `{contract_info.get('data_last')}`",
        "",
        "## Full Sweep Ranking",
        "",
        "| Rank | Variant | Dir | Window | Trades | Adj Net | Adj PF | Adj DD |",
        "|---:|---|---|---|---:|---:|---:|---:|",
    ]
    ranked = sorted(full_rows, key=_score, reverse=True)
    for idx, row in enumerate(ranked[:12], start=1):
        lines.append(
            f"| {idx} | `{row.get('variant')}` | {row.get('direction')} | "
            f"{row.get('trade_start_time')}-{row.get('trade_end_time')} | "
            f"{int(row.get('trade_count') or 0)} | "
            f"{float(row.get('net_profit_after_commission') or 0.0):.2f} | "
            f"{float(row.get('profit_factor_after_commission') or 0.0):.2f} | "
            f"{float(row.get('max_drawdown_after_commission') or 0.0):.2f} |"
        )

    lines += [
        "",
        "## Stress Checks",
        "",
    ]
    if not top_rows:
        lines.append("No full-sweep candidate cleared the minimal filter for stress testing.")
    else:
        for row in top_rows:
            variant = str(row["variant"])
            lines += [
                f"### `{variant}`",
                "",
                "| Stage | Trades | Adj Net | Adj PF | Adj DD |",
                "|---|---:|---:|---:|---:|",
            ]
            rows_for_variant = [r for r in stress_rows if r.get("variant") == variant]
            stage_order = {"is": 0, "oos": 1, "slip2": 2, "fee125": 3, "current": 4}
            rows_for_variant.sort(key=lambda r: stage_order.get(str(r.get("stage")), 99))
            for srow in rows_for_variant:
                lines.append(
                    f"| {srow.get('stage')} | {int(srow.get('trade_count') or 0)} | "
                    f"{float(srow.get('net_profit_after_commission') or 0.0):.2f} | "
                    f"{float(srow.get('profit_factor_after_commission') or 0.0):.2f} | "
                    f"{float(srow.get('max_drawdown_after_commission') or 0.0):.2f} |"
                )
            decision = decisions.get(variant) or {}
            verdict = "PASS" if decision.get("passed") else "FAIL"
            lines += [
                "",
                f"- Promotion verdict: **{verdict}**",
            ]
            reasons = decision.get("reasons") or []
            if reasons:
                for reason in reasons:
                    lines.append(f"- {reason}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    contract_info = RL.resolve_front_contract(ROOT)
    if "skip_reason" in contract_info:
        print(f"cannot resolve {ROOT}: {contract_info}")
        return 2
    instrument = str(contract_info["instrument"])

    stamp = _utc_stamp()
    bundle_dir = BUNDLE_ROOT / f"mgc_b1_clone_v2_{stamp}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle_dir}")
    print(f"instrument: {instrument}")

    full_submit = _submit_full_stage(bundle_dir, instrument, stamp)
    full_job_ids = [entry["job_id"] for entry in full_submit if entry["submit_code"] == 201]
    print(f"submitted full jobs: {len(full_job_ids)}")
    _wait_for_jobs(full_job_ids)
    full_rows = _read_reports(full_submit)
    full_rows.sort(key=_score, reverse=True)
    (bundle_dir / "all_tests.json").write_text(
        json.dumps({"tests": full_rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(bundle_dir / "all_tests.csv", full_rows)

    top_rows = _select_top_candidates(full_rows, limit=5)
    print("top full candidates:")
    for row in top_rows:
        print(
            f"  {row['variant']}: trades={row.get('trade_count')} "
            f"net={row.get('net_profit_after_commission'):.2f} "
            f"pf={row.get('profit_factor_after_commission'):.2f} "
            f"dd={row.get('max_drawdown_after_commission'):.2f}"
        )

    stress_submit = _submit_stress_stage(bundle_dir, instrument, stamp, top_rows)
    stress_job_ids = [entry["job_id"] for entry in stress_submit if entry["submit_code"] == 201]
    if stress_job_ids:
        print(f"submitted stress jobs: {len(stress_job_ids)}")
        _wait_for_jobs(stress_job_ids)
    stress_rows = _read_reports(stress_submit)
    (bundle_dir / "stress_tests.json").write_text(
        json.dumps({"tests": stress_rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    stress_by_variant: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in stress_rows:
        stress_by_variant.setdefault(str(row.get("variant")), {})[str(row.get("stage"))] = row

    decisions = {
        str(row["variant"]): _promotion_decision(row, stress_by_variant.get(str(row["variant"]), {}))
        for row in top_rows
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps({
            "bundle": str(bundle_dir),
            "instrument": instrument,
            "contract_info": contract_info,
            "session_template": SESSION_TEMPLATE,
            "role": ROLE,
            "full_jobs": full_submit,
            "stress_jobs": stress_submit,
            "top_candidates": top_rows,
            "decisions": decisions,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (bundle_dir / "summary.md").write_text(
        _summary_md(full_rows, stress_rows, top_rows, decisions, instrument, contract_info),
        encoding="utf-8",
    )

    best = top_rows[0] if top_rows else None
    if best:
        dec = decisions.get(str(best["variant"])) or {}
        print(
            f"best={best['variant']} net={best['net_profit_after_commission']:.2f} "
            f"pf={best['profit_factor_after_commission']:.2f} "
            f"trades={best['trade_count']} verdict={'PASS' if dec.get('passed') else 'FAIL'}"
        )
    else:
        print("no stress candidate selected")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
