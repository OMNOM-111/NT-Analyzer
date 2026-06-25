"""Research runner for the MNQ full-session scalp CELL-014 candidate.

The runner intentionally uses the already-compiled NTAMicroMnqScalpPilot engine
for honest NinjaTrader backtests before a deploy wrapper is promoted. It compares
three families requested for full-session work:

  - current morning ORB retest logic with an expanded window;
  - separate mid-day reversion modules;
  - late-session continuation / no-trade candidates.

Outputs are written under data/research/mnq_full_session_c014_<timestamp>/.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import mnq_scalp_pilot_lib as MS  # noqa: E402


CLASS_NAME = "NTAMicroMnqScalpPilot"
CURRENT_CONTRACT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures RTH"

PERIODS: List[Tuple[str, str, str]] = [
    ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
    ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
]

SMOKE = ("Smoke2026", "2026-03-12T00:00:00Z", "2026-05-11T23:59:59Z")

TIMEFRAMES: List[Tuple[str, str, int]] = [
    ("15s", "Second", 15),
    ("30s", "Second", 30),
    ("45s", "Second", 45),
    ("1m", "Minute", 1),
    ("5m", "Minute", 5),
]

SCREEN12_ROOTS = [
    "MGC", "MNQ", "M2K", "M6A", "M6B", "M6E",
    "M6J", "MBT", "MCL", "MES", "MET", "MYM",
]


def mnq_base_params() -> Dict[str, Any]:
    p = MS.scalp_params("MNQ", "ALL")
    p.update({
        "StartingCapital": 2000.0,
        "ActiveMarginPerContract": 100.0,
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "RiskPerTradePct": 0.35,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 60.0,
        "MaxWeeklyLossUsd": 150.0,
        "MaxDailyLossPct": 3.0,
        "MaxDailyProfitPct": 0.0,
        "MaxTradesPerDay": 20,
        "HardMaxTradesPerDay": 25,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 15,
        "RoundTurnCommission": 1.90,
        "SlippageTicks": 1,
        "TradeStartTime": 635,
        "TradeEndTime": 1245,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 1030,
        "SecondTradeEndTime": 1200,
        "ForceFlatTime": 1300,
        "NewsBlackoutTimes": "",
        "NewsBlackoutWindowMin": 5,
        "OrbStartTime": 630,
    })
    return p


def one_module(
    *,
    setup_mode: str,
    enable_long: bool,
    enable_short: bool,
    trade_start: int,
    trade_end: int,
    force_flat: int = 1300,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    p = mnq_base_params()
    p.update({
        "UseSetupModeFilter": True,
        "SetupMode": setup_mode,
        "EnableVwapReclaim": setup_mode == "VwapPullbackScalp",
        "EnableEmaMomentum": setup_mode == "EmaImpulseScalp",
        "EnableMicroOrb": setup_mode in ("OrbContinuationScalp", "OrbRetestScalp"),
        "EnableFailedBreakout": setup_mode == "FailedOrbReversalScalp",
        "EnableLong": enable_long,
        "EnableShort": enable_short,
        "TradeStartTime": trade_start,
        "TradeEndTime": trade_end,
        "UseSecondTradeWindow": False,
        "ForceFlatTime": force_flat,
    })
    if overrides:
        p.update(overrides)
    return p


def all_modules_full_session() -> Dict[str, Any]:
    p = mnq_base_params()
    p.update({
        "UseSetupModeFilter": False,
        "EnableVwapReclaim": True,
        "EnableEmaMomentum": True,
        "EnableMicroOrb": True,
        "EnableFailedBreakout": True,
        "EnableLong": True,
        "EnableShort": True,
        "TradeStartTime": 635,
        "TradeEndTime": 1245,
        "UseSecondTradeWindow": False,
        "ForceFlatTime": 1300,
        "AtrStopMult": 0.30,
        "MinStopTicks": 6,
        "MaxStopTicks": 14,
        "RewardRiskRatio": 1.35,
        "EntryOffsetTicks": 0,
        "MinVolumeFactor": 0.8,
    })
    return p


def candidates() -> List[Dict[str, Any]]:
    return [
        {
            "label": "c013_orbretest_extended_short",
            "hypothesis": "Current CELL-013 ORB retest logic with full active-session window.",
            "params": one_module(
                setup_mode="OrbRetestScalp",
                enable_long=False,
                enable_short=True,
                trade_start=635,
                trade_end=1245,
                overrides={
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 6,
                    "MaxStopTicks": 12,
                    "RewardRiskRatio": 1.50,
                    "EntryOffsetTicks": 0,
                    "OrbDurationMinutes": 3,
                    "OrbBreakoutBuffer": 1,
                    "OrbRetestBars": 5,
                    "MinVolumeFactor": 0.8,
                },
            ),
        },
        {
            "label": "full_all_modules_longshort",
            "hypothesis": "Single full-session mixed module baseline.",
            "params": all_modules_full_session(),
        },
        {
            "label": "orbretest_extended_short_rr160",
            "hypothesis": "Full-session ORB retest short-only with slightly wider RR for cost stress.",
            "params": one_module(
                setup_mode="OrbRetestScalp",
                enable_long=False,
                enable_short=True,
                trade_start=635,
                trade_end=1245,
                overrides={
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 6,
                    "MaxStopTicks": 12,
                    "RewardRiskRatio": 1.60,
                    "EntryOffsetTicks": 0,
                    "OrbDurationMinutes": 3,
                    "OrbBreakoutBuffer": 1,
                    "OrbRetestBars": 5,
                    "MinVolumeFactor": 0.8,
                },
            ),
        },
        {
            "label": "orbretest_extended_short_rr175",
            "hypothesis": "Full-session ORB retest short-only with RR=1.75.",
            "params": one_module(
                setup_mode="OrbRetestScalp",
                enable_long=False,
                enable_short=True,
                trade_start=635,
                trade_end=1245,
                overrides={
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 6,
                    "MaxStopTicks": 12,
                    "RewardRiskRatio": 1.75,
                    "EntryOffsetTicks": 0,
                    "OrbDurationMinutes": 3,
                    "OrbBreakoutBuffer": 1,
                    "OrbRetestBars": 5,
                    "MinVolumeFactor": 0.8,
                },
            ),
        },
        {
            "label": "orbretest_extended_short_stop8_14_rr160",
            "hypothesis": "Full-session ORB retest short-only with wider 8-14 tick risk box.",
            "params": one_module(
                setup_mode="OrbRetestScalp",
                enable_long=False,
                enable_short=True,
                trade_start=635,
                trade_end=1245,
                overrides={
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 8,
                    "MaxStopTicks": 14,
                    "RewardRiskRatio": 1.60,
                    "EntryOffsetTicks": 0,
                    "OrbDurationMinutes": 3,
                    "OrbBreakoutBuffer": 1,
                    "OrbRetestBars": 5,
                    "MinVolumeFactor": 0.8,
                },
            ),
        },
        {
            "label": "orbretest_0635_1200_short_rr150",
            "hypothesis": "Expanded ORB retest short-only ending at 12:00 PT to isolate the last 45 minutes.",
            "params": one_module(
                setup_mode="OrbRetestScalp",
                enable_long=False,
                enable_short=True,
                trade_start=635,
                trade_end=1200,
                force_flat=1245,
                overrides={
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 6,
                    "MaxStopTicks": 12,
                    "RewardRiskRatio": 1.50,
                    "EntryOffsetTicks": 0,
                    "OrbDurationMinutes": 3,
                    "OrbBreakoutBuffer": 1,
                    "OrbRetestBars": 5,
                    "MinVolumeFactor": 0.8,
                },
            ),
        },
        {
            "label": "orbretest_two_window_short_rr150_control",
            "hypothesis": "Current two-window ORB retest control against the approved morning profile.",
            "params": one_module(
                setup_mode="OrbRetestScalp",
                enable_long=False,
                enable_short=True,
                trade_start=635,
                trade_end=830,
                force_flat=1245,
                overrides={
                    "UseSecondTradeWindow": True,
                    "SecondTradeStartTime": 1030,
                    "SecondTradeEndTime": 1200,
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 6,
                    "MaxStopTicks": 12,
                    "RewardRiskRatio": 1.50,
                    "EntryOffsetTicks": 0,
                    "OrbDurationMinutes": 3,
                    "OrbBreakoutBuffer": 1,
                    "OrbRetestBars": 5,
                    "MinVolumeFactor": 0.8,
                },
            ),
        },
        {
            "label": "midday_failed_reversal_longshort",
            "hypothesis": "Afternoon/mid-day local failed-break reversion module.",
            "params": one_module(
                setup_mode="FailedOrbReversalScalp",
                enable_long=True,
                enable_short=True,
                trade_start=900,
                trade_end=1245,
                overrides={
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 6,
                    "MaxStopTicks": 14,
                    "RewardRiskRatio": 1.20,
                    "EntryOffsetTicks": 0,
                    "OrbFailedLookback": 4,
                    "MinVolumeFactor": 0.7,
                    "UseTimeStop": True,
                    "TimeStopBars": 4,
                    "MinProgressR": 0.20,
                },
            ),
        },
        {
            "label": "midday_vwap_reclaim_longshort",
            "hypothesis": "Mid-day VWAP reclaim / mean-reversion proxy.",
            "params": one_module(
                setup_mode="VwapPullbackScalp",
                enable_long=True,
                enable_short=True,
                trade_start=900,
                trade_end=1245,
                overrides={
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 6,
                    "MaxStopTicks": 14,
                    "RewardRiskRatio": 1.25,
                    "EntryOffsetTicks": 0,
                    "MinAdx": 0.0,
                    "MinVolumeFactor": 0.7,
                    "PullbackLookback": 4,
                },
            ),
        },
        {
            "label": "late_ema_continuation_longshort",
            "hypothesis": "Late-session continuation module; candidate may become no-trade if weak.",
            "params": one_module(
                setup_mode="EmaImpulseScalp",
                enable_long=True,
                enable_short=True,
                trade_start=1030,
                trade_end=1245,
                overrides={
                    "AtrStopMult": 0.30,
                    "MinStopTicks": 6,
                    "MaxStopTicks": 14,
                    "RewardRiskRatio": 1.35,
                    "EntryOffsetTicks": 0,
                    "MinAdx": 0.0,
                    "MinVolumeFactor": 0.7,
                    "RequireSlowTrend": True,
                    "PullbackLookback": 4,
                    "EmaImpulseLookback": 3,
                },
            ),
        },
    ]


def wait_job(job_id: str, timeout_s: int = 1200) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        report = RL.read_job_report(job_id)
        if report and "result" in report:
            return report
        if report and ("error" in report or "failed" in str(report.get("_dir", ""))):
            return report
        time.sleep(2)
    return {"job_id": job_id, "timeout": True}


def metric(report: Dict[str, Any], key: str, default: float = 0.0) -> float:
    result = report.get("result") or {}
    metrics = result.get("metrics") or {}
    value = result.get(key, metrics.get(key, default))
    if isinstance(value, str) and value.lower() == "inf":
        return math.inf
    try:
        return float(value)
    except Exception:
        return default


def trades_from(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return trades
    d = Path(str(report.get("_dir") or ""))
    p = d / "trades.json"
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return raw
            if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
                return raw["trades"]
        except Exception:
            return []
    return []


def summarize(row: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    trades = trades_from(report)
    gross_profit = 0.0
    gross_loss = 0.0
    adj_net = 0.0
    fee = float(row.get("fee") or 0.0)
    for trade in trades:
        qty = int(trade.get("quantity") or 1)
        pnl = float(trade.get("pnl_currency") or 0.0) - fee * max(1, qty)
        adj_net += pnl
        if pnl >= 0.0:
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)
    if trades:
        adj_pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
        trade_count = len(trades)
    else:
        adj_net = metric(report, "net_profit_after_commission", metric(report, "net_profit", 0.0))
        adj_pf = metric(report, "profit_factor_after_commission", metric(report, "profit_factor", 0.0))
        trade_count = int(metric(report, "trade_count", 0.0))

    out = dict(row)
    out.update({
        "status_dir": report.get("_dir", ""),
        "trade_count": trade_count,
        "adj_net": round(adj_net, 2),
        "adj_pf": adj_pf,
        "max_drawdown": metric(report, "max_drawdown_after_commission", metric(report, "max_drawdown", 0.0)),
        "timeout": bool(report.get("timeout")),
        "error": report.get("error") or report.get("result_error"),
    })
    return out


def aggregate(rows: Iterable[Dict[str, Any]], keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(row.get(k) for k in keys), []).append(row)

    out: List[Dict[str, Any]] = []
    for key_values, group in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        gross_profit = 0.0
        gross_loss = 0.0
        adj_net = 0.0
        trade_count = 0
        max_dd = 0.0
        for row in group:
            adj_net += float(row.get("adj_net") or 0.0)
            trade_count += int(row.get("trade_count") or 0)
            max_dd = min(max_dd, float(row.get("max_drawdown") or 0.0))
            report = RL.read_job_report(str(row.get("job_id") or ""))
            if report:
                for trade in trades_from(report):
                    qty = int(trade.get("quantity") or 1)
                    pnl = float(trade.get("pnl_currency") or 0.0) - float(row.get("fee") or 0.0) * max(1, qty)
                    if pnl >= 0.0:
                        gross_profit += pnl
                    else:
                        gross_loss += abs(pnl)
        pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
        rec = {k: v for k, v in zip(keys, key_values)}
        rec.update({
            "trade_count": trade_count,
            "adj_net": round(adj_net, 2),
            "adj_pf": pf,
            "max_drawdown": round(max_dd, 2),
            "job_ids": [r.get("job_id") for r in group if r.get("job_id")],
            "instruments": sorted({str(r.get("instrument")) for r in group if r.get("instrument")}),
        })
        out.append(rec)
    return out


def submit_row(
    *,
    bundle: Path,
    label: str,
    stage: str,
    period_label: str,
    instrument: str,
    from_utc: str,
    to_utc: str,
    params: Dict[str, Any],
    bars_type: str,
    bars_value: int,
    fee: float = 1.90,
    slip: int = 1,
    root: str = "MNQ",
) -> Dict[str, Any]:
    p = dict(params)
    p.update({
        "RoundTurnCommission": fee,
        "SlippageTicks": slip,
        "ActiveMarginPerContract": RL.margin_for(root),
        "InstrumentStatus": "allowed",
        "MaxContractsByCapital": 20,
    })
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=instrument,
        params=p,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type=bars_type,
        bars_period_value=bars_value,
        slippage_ticks=slip,
        role="smoke" if stage in {"smoke", "screen12"} else "research",
        session_template=RL.session_for(root),
        risk_profile=RL.build_risk_profile_for([instrument]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if code == 201 else None
    row = {
        "stage": stage,
        "label": label,
        "period_label": period_label,
        "instrument": instrument,
        "root": root,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "timeframe": f"{bars_value} {bars_type}",
        "bars_period_type": bars_type,
        "bars_period_value": bars_value,
        "fee": fee,
        "slip": slip,
        "code": code,
        "job_id": job_id,
        "response": resp,
    }
    print(f"submit {stage:10s} {label:36s} {period_label:12s} {instrument:10s} {bars_value:>2} {bars_type:<6s} code={code} job={job_id or resp}")
    (bundle / "latest_submitted.json").write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    return row


def run_rows(bundle: Path, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        job_id = row.get("job_id")
        if not job_id:
            out.append(row)
            continue
        report = wait_job(str(job_id))
        summary = summarize(row, report)
        out.append(summary)
        pf = summary.get("adj_pf")
        pf_s = "inf" if pf == math.inf else f"{float(pf or 0.0):.3f}"
        print(
            f"done   {row['stage']:10s} {row['label']:36s} {row['period_label']:12s} "
            f"{row['instrument']:10s} trades={summary['trade_count']:>4} "
            f"net={summary['adj_net']:>8.2f} pf={pf_s:>7s} dd={summary['max_drawdown']:>8.2f}"
        )
        (bundle / "latest_summary_rows.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def submit_smoke(bundle: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    label, fr, to = SMOKE
    for cand in candidates():
        rows.append(submit_row(
            bundle=bundle,
            label=cand["label"],
            stage="smoke",
            period_label=label,
            instrument=CURRENT_CONTRACT,
            from_utc=fr,
            to_utc=to,
            params=cand["params"],
            bars_type="Minute",
            bars_value=1,
        ))
    return run_rows(bundle, rows)


def submit_timeframe_scan(bundle: Path, candidate_labels: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    label, fr, to = SMOKE
    selected = [
        c for c in candidates()
        if not candidate_labels or c["label"] in candidate_labels
    ]
    for cand in selected:
        for tf_label, bars_type, bars_value in TIMEFRAMES:
            rows.append(submit_row(
                bundle=bundle,
                label=f"{cand['label']}__{tf_label}",
                stage="tf_scan",
                period_label=label,
                instrument=CURRENT_CONTRACT,
                from_utc=fr,
                to_utc=to,
                params=cand["params"],
                bars_type=bars_type,
                bars_value=bars_value,
            ))
    return run_rows(bundle, rows)


def submit_validation(bundle: Path, labels: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    selected = [c for c in candidates() if not labels or c["label"] in labels]
    for cand in selected:
        for period_label, fr, to in PERIODS:
            rows.append(submit_row(
                bundle=bundle,
                label=cand["label"],
                stage="validation",
                period_label=period_label,
                instrument=CURRENT_CONTRACT,
                from_utc=fr,
                to_utc=to,
                params=cand["params"],
                bars_type="Minute",
                bars_value=1,
            ))
    return run_rows(bundle, rows)


def submit_stress(bundle: Path, labels: List[str]) -> List[Dict[str, Any]]:
    stress_defs = [
        ("StressSlip2", 1.90, 2),
        ("StressFee240", 2.40, 1),
        ("StressSlip2Fee240", 2.40, 2),
    ]
    rows: List[Dict[str, Any]] = []
    by_label = {c["label"]: c for c in candidates()}
    for label in labels:
        cand = by_label[label]
        for period_label, fee, slip in stress_defs:
            rows.append(submit_row(
                bundle=bundle,
                label=label,
                stage="stress",
                period_label=period_label,
                instrument=CURRENT_CONTRACT,
                from_utc=PERIODS[0][1],
                to_utc=PERIODS[0][2],
                params=cand["params"],
                bars_type="Minute",
                bars_value=1,
                fee=fee,
                slip=slip,
            ))
    return run_rows(bundle, rows)


def root_window(root: str) -> Tuple[int, int, int]:
    if root in {"MNQ", "MES", "MYM", "M2K"}:
        return 635, 1245, 1300
    if root in {"MGC"}:
        return 600, 1245, 1300
    if root in {"MBT", "MET"}:
        return 0, 2200, 2245
    return 600, 1245, 1300


def params_for_root(root: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(candidate["params"])
    start, end, flat = root_window(root)
    p.update({
        "TradeStartTime": start,
        "TradeEndTime": end,
        "ForceFlatTime": flat,
        "ActiveMarginPerContract": RL.margin_for(root),
        "RoundTurnCommission": RL.fee_for(root),
        "SlippageTicks": 1,
    })
    return p


def front_contract(root: str) -> Optional[str]:
    front = RL.resolve_front_contract(root)
    if front.get("skip_reason"):
        return None
    return str(front.get("instrument") or "")


def submit_screen12(bundle: Path, label: str) -> List[Dict[str, Any]]:
    by_label = {c["label"]: c for c in candidates()}
    cand = by_label[label]
    rows: List[Dict[str, Any]] = []
    for root in SCREEN12_ROOTS:
        instrument = front_contract(root)
        if not instrument:
            rows.append({
                "stage": "screen12",
                "label": label,
                "period_label": "Full",
                "root": root,
                "instrument": "",
                "code": 0,
                "response": {"skip_reason": "no overlapping minute-data contract"},
            })
            continue
        rows.append(submit_row(
            bundle=bundle,
            label=label,
            stage="screen12",
            period_label="Full",
            instrument=instrument,
            root=root,
            from_utc=PERIODS[0][1],
            to_utc=PERIODS[0][2],
            params=params_for_root(root, cand),
            bars_type="Minute",
            bars_value=1,
            fee=RL.fee_for(root),
            slip=1,
        ))
    return run_rows(bundle, [r for r in rows if r.get("job_id")]) + [r for r in rows if not r.get("job_id")]


def pass_core_gates(validation: List[Dict[str, Any]], label: str) -> bool:
    by_period = {r["period_label"]: r for r in validation if r.get("label") == label}
    full = by_period.get("Full")
    is_ = by_period.get("IS")
    oos = by_period.get("OOS")
    if not full or not is_ or not oos:
        return False
    return (
        full.get("adj_net", 0.0) > 0.0
        and full.get("adj_pf", 0.0) >= 1.35
        and int(full.get("trade_count") or 0) >= 30
        and RL.max_drawdown_within_budget(full.get("max_drawdown", 0.0))
        and is_.get("adj_net", 0.0) > 0.0
        and oos.get("adj_net", 0.0) > 0.0
        and oos.get("adj_pf", 0.0) >= 1.25
    )


def write_markdown(bundle: Path, final: Dict[str, Any]) -> None:
    def fmt_pf(v: Any) -> str:
        try:
            x = float(v)
        except Exception:
            return ""
        return "inf" if math.isinf(x) else f"{x:.3f}"

    lines = [
        "# MNQ Full Session CELL-014 Research",
        "",
        f"Bundle: `{bundle}`",
        "",
        "## Candidates",
        "",
        "| Label | Hypothesis |",
        "|---|---|",
    ]
    for c in candidates():
        lines.append(f"| `{c['label']}` | {c['hypothesis']} |")

    for section, rows in [
        ("Smoke", final.get("smoke_agg") or []),
        ("Timeframe Scan", final.get("tf_scan_agg") or []),
        ("Validation", final.get("validation_agg") or []),
        ("Stress", final.get("stress_agg") or []),
        ("Screen12", final.get("screen12_agg") or []),
    ]:
        if not rows:
            continue
        lines += ["", f"## {section}", "", "| Label | Period | Root | Timeframe | Trades | Adj net | Adj PF | Max DD |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            lines.append(
                f"| `{r.get('label','')}` | {r.get('period_label','')} | {r.get('root','MNQ')} | "
                f"{r.get('timeframe','1 Minute')} | {r.get('trade_count',0)} | "
                f"{float(r.get('adj_net') or 0.0):.2f} | {fmt_pf(r.get('adj_pf'))} | "
                f"{float(r.get('max_drawdown') or 0.0):.2f} |"
            )

    if final.get("gate_decisions"):
        lines += ["", "## Gate Decisions", "", "| Label | Core gates | Stress positive | Decision |", "|---|---:|---:|---|"]
        for d in final["gate_decisions"]:
            lines.append(
                f"| `{d['label']}` | {d['core_gates']} | {d.get('stress_positive', False)} | {d['decision']} |"
            )

    (bundle / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["smoke", "tf-scan", "validation", "stress", "screen12", "all"], default="all")
    ap.add_argument("--label", action="append", help="Candidate label to run; can be repeated.")
    ap.add_argument("--screen-label", default="c013_orbretest_extended_short")
    args = ap.parse_args(argv[1:])

    bundle = RL.DATA / "research" / f"mnq_full_session_c014_{RL.utcnow_compact()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}")

    final: Dict[str, Any] = {
        "bundle": str(bundle),
        "class_name": CLASS_NAME,
        "current_contract": CURRENT_CONTRACT,
        "acceptance_gates": {
            "full_2024_2025": "adj_net > 0, adj_pf >= 1.35, trades >= 30, max_dd <= 15% StartingCapital",
            "is_2024": "adj_net > 0",
            "oos_2025": "adj_net > 0, adj_pf >= 1.25",
            "stress": "slip=2 positive, fee=2.40 positive, combined desired positive",
        },
    }

    if args.stage in ("smoke", "all"):
        final["smoke_rows"] = submit_smoke(bundle)
        final["smoke_agg"] = aggregate(final["smoke_rows"], ("label", "period_label", "root", "timeframe"))

    if args.stage in ("tf-scan", "all"):
        labels = args.label or ["c013_orbretest_extended_short", "midday_failed_reversal_longshort"]
        final["tf_scan_rows"] = submit_timeframe_scan(bundle, labels)
        final["tf_scan_agg"] = aggregate(final["tf_scan_rows"], ("label", "period_label", "root", "timeframe"))

    if args.stage in ("validation", "all"):
        final["validation_rows"] = submit_validation(bundle, args.label)
        final["validation_agg"] = aggregate(final["validation_rows"], ("label", "period_label", "root", "timeframe"))
        passed = [
            c["label"] for c in candidates()
            if (not args.label or c["label"] in args.label)
            and pass_core_gates(final["validation_agg"], c["label"])
        ]
        final["core_gate_passed_labels"] = passed
    else:
        passed = args.label or []

    if args.stage in ("stress", "all"):
        stress_labels = args.label or passed
        final["stress_rows"] = submit_stress(bundle, stress_labels) if stress_labels else []
        final["stress_agg"] = aggregate(final["stress_rows"], ("label", "period_label", "root", "timeframe"))

    if args.stage in ("screen12", "all"):
        screen_label = args.label[0] if args.label else (passed[0] if passed else args.screen_label)
        final["screen12_label"] = screen_label
        final["screen12_rows"] = submit_screen12(bundle, screen_label)
        final["screen12_agg"] = aggregate(
            [r for r in final["screen12_rows"] if r.get("job_id")],
            ("label", "period_label", "root", "timeframe"),
        )
        final["screen12_skips"] = [r for r in final["screen12_rows"] if not r.get("job_id")]

    gate_decisions = []
    validation_agg = final.get("validation_agg") or []
    stress_agg = final.get("stress_agg") or []
    for c in candidates():
        label = c["label"]
        if args.label and label not in args.label:
            continue
        core = pass_core_gates(validation_agg, label)
        stress_rows = [r for r in stress_agg if r.get("label") == label]
        stress_positive = bool(stress_rows) and all(float(r.get("adj_net") or 0.0) > 0.0 for r in stress_rows)
        if core and stress_positive:
            decision = "paper_candidate; eligible for wrapper/profile promotion"
        elif core:
            decision = "research_candidate; core gates passed, stress failed or pending"
        else:
            decision = "rejected_or_research_only; core gates failed or pending"
        gate_decisions.append({
            "label": label,
            "core_gates": core,
            "stress_positive": stress_positive,
            "decision": decision,
        })
    final["gate_decisions"] = gate_decisions

    (bundle / "summary.json").write_text(json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(bundle, final)
    print(f"summary -> {bundle / 'summary.json'}")
    print(f"markdown -> {bundle / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
