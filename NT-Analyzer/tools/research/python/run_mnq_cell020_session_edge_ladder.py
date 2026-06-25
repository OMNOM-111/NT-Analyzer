"""Multi-family MNQ Research Hub ladder runner.

Drives the stable NTAMnqResearchHub engine across a MANDATORY
search ladder of several genuinely different structural families and two free
time windows (outside the active 06:35-12:45 PT cluster). It does NOT stop at
the first rejection: every family is smoke-tested, the best survivor of each is
pushed through Full/IS/OOS, and the global best is stress/current-tested against
the promotion gates. If no family passes, a ranked report is emitted.

Families (engine Mode):
  reclaim  - OrRangeReclaim : time-defined range reclaim / continuation
  failbrk  - FailedBreak    : failed breakout reversal (fade back into range)
  vwappb   - VwapPullback   : VWAP pullback continuation in an EMA-stacked trend
  reject   - RangeReject    : anchor high/low wick rejection
  emapb    - EmaPullback    : EMA-stack trend pullback continuation (no anchor)
  opendrv  - OpenDrive      : open-drive continuation after first window push
  pdbreak  - PrevDayBreak   : previous-session high/low breakout continuation
  pdreject - PrevDayReject  : previous-session high/low rejection (fade)

Windows (PT clock as configured on the chart):
  preA - pre-cash ETH : build 00:00-03:15, trade 03:20-05:55
  pmB  - afternoon ETH: build 12:00-15:00, trade 15:05-18:00
  midD - post-close   : build 11:00-13:00, trade 13:05-15:00

Usage:
    python run_mnq_cell020_session_edge_ladder.py            # full ladder
    python run_mnq_cell020_session_edge_ladder.py --smoke-only
    python run_mnq_cell020_session_edge_ladder.py --class-name NTAMnqSessionEdgeEngineC020
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402


CLASS_NAME = os.environ.get("NTA_MNQ_RESEARCH_CLASS", "NTAMnqResearchHub")
BUNDLE_PREFIX = os.environ.get("NTA_MNQ_RESEARCH_BUNDLE_PREFIX", "mnq_research_hub_session_edge")
ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures ETH"
BARS_PERIOD_VALUE = 5
BASE_TF_SECONDS = 300

FULL = ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
IS = ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
OOS = ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")
SMOKE = ("Smoke", "2025-09-01T00:00:00Z", "2025-12-31T23:59:59Z")

FEE_BASE = max(1.90, RL.fee_for(ROOT))
FEE_STRESS = 2.40

WINDOWS: Dict[str, Dict[str, int]] = {
    "preA": {"RangeStartTime": 0, "RangeEndTime": 315,
             "TradeStartTime": 320, "TradeEndTime": 555, "ForceFlatTime": 559},
    "pmB": {"RangeStartTime": 1200, "RangeEndTime": 1500,
            "TradeStartTime": 1505, "TradeEndTime": 1800, "ForceFlatTime": 1804},
    "midD": {"RangeStartTime": 1100, "RangeEndTime": 1300,
             "TradeStartTime": 1305, "TradeEndTime": 1500, "ForceFlatTime": 1504},
}

FAMILIES: Dict[str, Dict[str, Any]] = {
    "reclaim": {"Mode": "OrRangeReclaim", "reversal": False,
                "knob": "ReclaimBufferTicks", "knobs": [1, 3, 6]},
    "failbrk": {"Mode": "FailedBreak", "reversal": True,
                "knob": "FailReturnTicks", "knobs": [1, 3, 6]},
    "vwappb": {"Mode": "VwapPullback", "reversal": False,
               "knob": "PullbackTicks", "knobs": [3, 6, 10]},
    "reject": {"Mode": "RangeReject", "reversal": True,
               "knob": "RejectWickTicks", "knobs": [2, 4, 8]},
    "emapb": {"Mode": "EmaPullback", "reversal": False,
              "knob": "PullbackTicks", "knobs": [6, 10, 16]},
    "opendrv": {"Mode": "OpenDrive", "reversal": False,
                "knob": "DriveTicks", "knobs": [12, 20, 32]},
    "pdbreak": {"Mode": "PrevDayBreak", "reversal": False,
                "knob": "ReclaimBufferTicks", "knobs": [1, 3, 6]},
    "pdreject": {"Mode": "PrevDayReject", "reversal": True,
                 "knob": "RejectWickTicks", "knobs": [2, 4, 8]},
}

# Extended ladder: the first 4 families (reclaim/failbrk/vwappb/reject) were
# already exhausted and rejected in bundle mnq_cell020_session_edge_20260601_055143.
# This pass covers the 4 NEW structural families across three free windows.
LADDER: List[Tuple[str, str]] = [
    ("emapb", "pmB"),
    ("emapb", "preA"),
    ("opendrv", "pmB"),
    ("opendrv", "preA"),
    ("opendrv", "midD"),
    ("pdbreak", "pmB"),
    ("pdbreak", "midD"),
    ("pdreject", "pmB"),
    ("pdreject", "midD"),
]


def current_window(days: int = 30) -> Tuple[str, str]:
    front = RL.resolve_front_contract(ROOT)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def base_params() -> Dict[str, Any]:
    return {
        "InstrumentName": ROOT,
        "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": BASE_TF_SECONDS,
        "StartingCapital": RL.DEFAULT_STARTING_CAPITAL,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True,
        "EnableShort": True,
        "Mode": "OrRangeReclaim",
        "RangeStartTime": 0,
        "RangeEndTime": 315,
        "ReclaimBufferTicks": 3,
        "FailReturnTicks": 3,
        "RejectWickTicks": 4,
        "PullbackTicks": 6,
        "RequireEmaStack": True,
        "TradeStartTime": 320,
        "TradeEndTime": 555,
        "UseSecondTradeWindow": False,
        "SecondTradeStartTime": 100,
        "SecondTradeEndTime": 300,
        "ForceFlatTime": 559,
        "EmaFastPeriod": 9,
        "EmaMidPeriod": 21,
        "EmaSlowPeriod": 50,
        "AtrPeriod": 14,
        "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.6,
        "RequireVwapAgreement": True,
        "RequireEmaAgreement": True,
        "RequireEmaSlope": False,
        "StopBufferTicks": 4,
        "MinStopTicks": 16,
        "MaxStopTicks": 44,
        "AtrStopMult": 1.0,
        "RewardRiskRatio": 1.6,
        "MinTargetTicks": 16,
        "EntryOffsetTicks": 0,
        "EntryTimeoutBars": 3,
        "MoveToBreakevenAtR": 1.0,
        "BreakevenPlusTicks": 2,
        "UseTrailingStop": False,
        "TrailAfterR": 1.5,
        "TrailDistanceTicks": 12,
        "UseTimeStop": True,
        "TimeStopBars": 8,
        "MinProgressR": 0.30,
        "RiskPerTradePct": 0.75,
        "UserMaxContracts": 1,
        "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 80.0,
        "MaxWeeklyLossUsd": 200.0,
        "MaxTradesPerDay": 4,
        "HardMaxTradesPerDay": 6,
        "MaxConsecutiveLosses": 3,
        "PauseAfterConsecutiveLosses": 2,
        "PauseMinutesAfterLosses": 60,
        "RoundTurnCommission": FEE_BASE,
        "SlippageTicks": 1,
    }


def combo_candidates(fam_code: str, win_code: str) -> List[Dict[str, Any]]:
    fam = FAMILIES[fam_code]
    win = WINDOWS[win_code]
    out: List[Dict[str, Any]] = []
    for rr in (1.5, 2.0):
        for knob in fam["knobs"]:
            p = base_params()
            p.update(win)
            p["Mode"] = fam["Mode"]
            p["RewardRiskRatio"] = rr
            p[fam["knob"]] = knob
            if fam["reversal"]:
                # Reversal families fade the move: no trend-agreement filters,
                # a slightly looser volume floor to retain enough samples.
                p["RequireVwapAgreement"] = False
                p["RequireEmaAgreement"] = False
                p["RequireEmaSlope"] = False
                p["MinVolumeFactor"] = 0.4
            label = f"{fam_code}_{win_code}_rr{int(rr * 10):02d}_k{knob:02d}"
            out.append({"label": label, "params": p,
                        "fam": fam_code, "win": win_code})
    return out


def submit_job(
    *,
    bundle: Path,
    label: str,
    stage: str,
    period_label: str,
    from_utc: str,
    to_utc: str,
    params: Dict[str, Any],
    fee: float = FEE_BASE,
    slip: int = 1,
    fam: str = "",
    win: str = "",
) -> Dict[str, Any]:
    p = dict(params)
    p.update({
        "RoundTurnCommission": fee,
        "SlippageTicks": slip,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "InstrumentStatus": "allowed",
        "MaxContractsByCapital": 20,
    })
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=p,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=BARS_PERIOD_VALUE,
        slippage_ticks=slip,
        role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    row = {
        "stage": stage, "label": label, "fam": fam, "win": win,
        "period_label": period_label, "from_utc": from_utc, "to_utc": to_utc,
        "fee": fee, "slip": slip, "code": code, "job_id": job_id,
        "response": resp, "params": p,
    }
    print(f"submit {stage:10s} {label:24s} {period_label:12s} code={code} job={job_id or resp}", flush=True)
    (bundle / "latest_submitted.json").write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    return row


def job_state(job_id: str) -> Optional[str]:
    base = RL.jobs_root()
    for state in ("done", "failed", "cancelled", "running", "pending"):
        if (base / state / job_id).is_dir():
            return state
    if (base / "failed" / ".quarantine" / job_id).is_dir():
        return "failed"
    return None


def wait_for_jobs(rows: List[Dict[str, Any]], timeout_s: int = 21600) -> None:
    remaining = {str(r["job_id"]) for r in rows if r.get("job_id")}
    deadline = time.time() + timeout_s
    last_print = 0.0
    while remaining:
        if time.time() > deadline:
            raise TimeoutError(f"timeout waiting for jobs: {sorted(remaining)}")
        for job_id in list(remaining):
            if job_state(job_id) in {"done", "failed", "cancelled"}:
                remaining.remove(job_id)
        now = time.time()
        if now - last_print >= 30 and remaining:
            print(f"waiting: {len(remaining)} CELL-020 jobs still pending/running", flush=True)
            last_print = now
        time.sleep(3)


def trades_from(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = report.get("result") or {}
    trades = result.get("trades")
    if isinstance(trades, list):
        return trades
    d = Path(str(report.get("_dir") or ""))
    p = d / "trades.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
            return raw["trades"]
    return []


def trade_qty(trade: Dict[str, Any]) -> float:
    try:
        return max(1.0, abs(float(trade.get("quantity") or 1.0)))
    except Exception:
        return 1.0


def adjusted_pnls(trades: Iterable[Dict[str, Any]], fee: float) -> List[float]:
    out: List[float] = []
    for trade in trades:
        out.append(float(trade.get("pnl_currency") or 0.0) - fee * trade_qty(trade))
    return out


def _bar_bucket(ts: str) -> Optional[int]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    return int(dt.timestamp()) // BASE_TF_SECONDS


def same_bar_pct(trades: List[Dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    same = 0
    counted = 0
    for t in trades:
        eb = _bar_bucket(str(t.get("entry_time_utc") or ""))
        xb = _bar_bucket(str(t.get("exit_time_utc") or ""))
        if eb is None or xb is None:
            continue
        counted += 1
        if eb == xb:
            same += 1
    return round(same / counted * 100.0, 2) if counted else 0.0


def weekdays(from_utc: str, to_utc: str) -> int:
    start = date.fromisoformat(from_utc[:10])
    end = date.fromisoformat(to_utc[:10])
    if end < start:
        return 0
    total = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            total += 1
        cur += timedelta(days=1)
    return total


def max_consecutive_losses(pnls: Iterable[float]) -> int:
    best = 0
    cur = 0
    for pnl in pnls:
        if pnl < 0.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def summarize(row: Dict[str, Any], report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(row)
    out.pop("response", None)
    out.pop("params", None)
    if not report or "result" not in report:
        out.update({"status": job_state(str(row.get("job_id") or "")) or "missing", "trade_count": 0})
        return out

    trades = trades_from(report)
    fee = float(row.get("fee") or 0.0)
    pnls = adjusted_pnls(trades, fee)
    gross_profit = sum(p for p in pnls if p > 0.0)
    gross_loss = abs(sum(p for p in pnls if p < 0.0))
    adj_net = sum(pnls)
    adj_pf = gross_profit / gross_loss if gross_loss > 0.0 else (math.inf if gross_profit > 0.0 else 0.0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    active_days = Counter(
        str(t.get("entry_time_utc") or t.get("exit_time_utc") or "")[:10]
        for t in trades
        if t.get("entry_time_utc") or t.get("exit_time_utc")
    )
    active_counts = list(active_days.values())
    total_days = weekdays(str(row.get("from_utc")), str(row.get("to_utc")))
    out.update({
        "status": job_state(str(row.get("job_id"))) or "unknown",
        "trade_count": len(trades),
        "calendar_weekdays": total_days,
        "trades_per_day": round(len(trades) / total_days, 4) if total_days else 0.0,
        "active_days": len(active_counts),
        "adj_net": round(adj_net, 2),
        "adj_pf": adj_pf,
        "win_rate": round((sum(1 for p in pnls if p > 0.0) / len(pnls) * 100.0) if pnls else 0.0, 2),
        "avg_trade_after_commission": round(adj_net / len(pnls), 2) if pnls else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_consecutive_losses": max_consecutive_losses(pnls),
        "same_bar_pct": same_bar_pct(trades),
        "gross_profit_after_commission": round(gross_profit, 2),
        "gross_loss_after_commission": round(gross_loss, 2),
    })
    return out


def collect_rows(bundle: Path, rows: List[Dict[str, Any]], filename: str) -> List[Dict[str, Any]]:
    wait_for_jobs(rows)
    summaries: List[Dict[str, Any]] = []
    for row in rows:
        job_id = str(row.get("job_id") or "")
        report = RL.read_job_report(job_id) if job_id else None
        summary = summarize(row, report)
        summaries.append(summary)
        pf = summary.get("adj_pf")
        pf_s = "inf" if pf == math.inf else f"{float(pf or 0.0):.3f}"
        print(
            f"done   {row['stage']:10s} {row['label']:24s} {row['period_label']:12s} "
            f"trades={int(summary.get('trade_count') or 0):>5} "
            f"tpd={float(summary.get('trades_per_day') or 0.0):>6.2f} "
            f"net={float(summary.get('adj_net') or 0.0):>9.2f} "
            f"pf={pf_s:>7s} dd={float(summary.get('max_drawdown') or 0.0):>9.2f} "
            f"sb%={float(summary.get('same_bar_pct') or 0.0):>5.1f}",
            flush=True,
        )
        (bundle / filename).write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    return summaries


def score(row: Dict[str, Any]) -> float:
    net = float(row.get("adj_net") or 0.0)
    pf = float(row.get("adj_pf") or 0.0)
    dd = abs(float(row.get("max_drawdown") or 0.0))
    trades = int(row.get("trade_count") or 0)
    if trades <= 0:
        return -999999.0
    pf_capped = min(pf, 3.0) if not math.isinf(pf) else 3.0
    return net + pf_capped * 120.0 + min(trades, 600) * 0.5 - dd * 0.4


def pick_best_smoke(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    eligible = [
        r for r in rows
        if int(r.get("trade_count") or 0) >= 8
        and float(r.get("adj_net") or 0.0) > 0.0
        and (math.isinf(float(r.get("adj_pf") or 0.0)) or float(r.get("adj_pf") or 0.0) >= 1.10)
    ]
    if not eligible:
        eligible = [r for r in rows if int(r.get("trade_count") or 0) >= 8]
    if not eligible:
        return None
    eligible.sort(key=score, reverse=True)
    return eligible[0]


def gates(full: Dict[str, Any], is_: Dict[str, Any], oos: Dict[str, Any],
          stress_combined: Dict[str, Any], current: Dict[str, Any],
          starting_capital: Optional[float] = None) -> Dict[str, bool]:
    def f(r: Dict[str, Any], k: str) -> float:
        v = r.get(k)
        if v is None:
            return 0.0
        if v == math.inf:
            return 99.0
        return float(v)
    cap = starting_capital if starting_capital is not None else RL.DEFAULT_STARTING_CAPITAL
    return {
        "full_net_pos": f(full, "adj_net") > 0.0,
        "full_pf_135": f(full, "adj_pf") >= 1.35,
        "oos_pf_125": f(oos, "adj_pf") >= 1.25,
        "max_dd_pct_15": RL.max_drawdown_within_budget(f(full, "max_drawdown"), cap),
        "stress_combined_nonneg": f(stress_combined, "adj_net") >= 0.0,
        "current30d_nonneg": f(current, "adj_net") >= 0.0,
        "enough_trades": int(full.get("trade_count") or 0) >= 40,
        "is_net_pos": f(is_, "adj_net") > 0.0,
        "low_same_bar": f(full, "same_bar_pct") <= 50.0,
    }


def pf_str(v: Any) -> str:
    try:
        x = float(v)
    except Exception:
        return ""
    return "inf" if math.isinf(x) else f"{x:.3f}"


def write_markdown(bundle: Path, final: Dict[str, Any]) -> None:
    lines = [
        "# MNQ CELL-020 Session-Edge Ladder",
        "",
        f"Bundle: `{bundle.name}`",
        f"Class: `{CLASS_NAME}`",
        f"Session template: `{SESSION_TEMPLATE}` | Timeframe: {BARS_PERIOD_VALUE} Minute",
        "",
        "Ladder (family x window): " + ", ".join(f"{f}@{w}" for f, w in LADDER),
        "",
    ]
    for section, key in [
        ("Smoke (all families)", "smoke_rows"),
        ("Validation (Full/IS/OOS)", "validation_rows"),
        ("Stress", "stress_rows"),
        ("Current30D", "current_rows"),
    ]:
        rows = final.get(key) or []
        if not rows:
            continue
        lines += [
            f"## {section}",
            "",
            "| Label | Fam | Win | Period | Trades | TPD | Net | PF | Win% | DD | SB% |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in sorted(rows, key=score, reverse=True):
            lines.append(
                f"| `{r.get('label','')}` | {r.get('fam','')} | {r.get('win','')} | "
                f"{r.get('period_label','')} | {int(r.get('trade_count') or 0)} | "
                f"{float(r.get('trades_per_day') or 0.0):.2f} | "
                f"{float(r.get('adj_net') or 0.0):.2f} | {pf_str(r.get('adj_pf'))} | "
                f"{float(r.get('win_rate') or 0.0):.1f} | "
                f"{float(r.get('max_drawdown') or 0.0):.2f} | "
                f"{float(r.get('same_bar_pct') or 0.0):.1f} |"
            )
        lines.append("")

    ranked = final.get("family_ranking") or []
    if ranked:
        lines += [
            "## Family ranking (best smoke survivor per family/window, Full result)",
            "",
            "| Rank | Fam@Win | Label | Full Net | Full PF | Full Trades | OOS Net | OOS PF | Verdict |",
            "|---:|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for i, r in enumerate(ranked, 1):
            lines.append(
                f"| {i} | {r.get('fam','')}@{r.get('win','')} | `{r.get('label','')}` | "
                f"{float(r.get('full_net') or 0.0):.2f} | {pf_str(r.get('full_pf'))} | "
                f"{int(r.get('full_trades') or 0)} | {float(r.get('oos_net') or 0.0):.2f} | "
                f"{pf_str(r.get('oos_pf'))} | {r.get('verdict','')} |"
            )
        lines.append("")

    decision = final.get("decision") or {}
    lines += ["## Decision", "", "```json", json.dumps(decision, indent=2, ensure_ascii=False, default=str), "```", ""]
    (bundle / "cell020_session_edge_summary.md").write_text("\n".join(lines), encoding="utf-8")


def by_label_period(rows: List[Dict[str, Any]], label: str, period: str) -> Dict[str, Any]:
    for r in rows:
        if r.get("label") == label and r.get("period_label") == period:
            return r
    return {}


def run(smoke_only: bool) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"{BUNDLE_PREFIX}_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)

    final: Dict[str, Any] = {
        "class_name": CLASS_NAME,
        "instrument": INSTRUMENT,
        "session_template": SESSION_TEMPLATE,
        "bars_period_value": BARS_PERIOD_VALUE,
        "ladder": [f"{f}@{w}" for f, w in LADDER],
        "created_utc": RL.utcnow_iso(),
    }

    # ---- Stage 0: smoke every ladder combo ---------------------------------
    all_candidates: List[Dict[str, Any]] = []
    for fam_code, win_code in LADDER:
        all_candidates.extend(combo_candidates(fam_code, win_code))
    label_to_cand = {c["label"]: c for c in all_candidates}

    smoke_submitted = [
        submit_job(
            bundle=bundle, label=c["label"], stage="smoke",
            period_label=SMOKE[0], from_utc=SMOKE[1], to_utc=SMOKE[2],
            params=c["params"], fee=FEE_BASE, slip=1, fam=c["fam"], win=c["win"],
        )
        for c in all_candidates
    ]
    smoke_rows = collect_rows(bundle, smoke_submitted, "smoke_rows.json")
    final["smoke_rows"] = smoke_rows
    (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # Best smoke survivor per (family, window) combo.
    survivors: List[Dict[str, Any]] = []
    for fam_code, win_code in LADDER:
        combo_rows = [r for r in smoke_rows if r.get("fam") == fam_code and r.get("win") == win_code]
        best = pick_best_smoke(combo_rows)
        if best:
            survivors.append(best)
    final["smoke_survivors"] = [s["label"] for s in survivors]
    print(f"smoke survivors: {final['smoke_survivors']}", flush=True)
    (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    if smoke_only or not survivors:
        final["decision"] = {
            "status": "smoke_only" if smoke_only else "rejected",
            "reason": "smoke_only flag" if smoke_only else "no family produced a smoke survivor",
        }
        (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_markdown(bundle, final)
        return

    # ---- Full / IS / OOS for each family survivor --------------------------
    val_submitted: List[Dict[str, Any]] = []
    for s in survivors:
        cand = label_to_cand[s["label"]]
        for period_label, frm, to in (FULL, IS, OOS):
            val_submitted.append(submit_job(
                bundle=bundle, label=s["label"], stage="validation",
                period_label=period_label, from_utc=frm, to_utc=to,
                params=cand["params"], fee=FEE_BASE, slip=1,
                fam=cand["fam"], win=cand["win"],
            ))
    validation_rows = collect_rows(bundle, val_submitted, "validation_rows.json")
    final["validation_rows"] = validation_rows

    # Family ranking by Full score.
    ranking: List[Dict[str, Any]] = []
    for s in survivors:
        label = s["label"]
        full = by_label_period(validation_rows, label, "Full")
        oos = by_label_period(validation_rows, label, "OOS")
        ranking.append({
            "fam": s.get("fam"), "win": s.get("win"), "label": label,
            "full_net": full.get("adj_net"), "full_pf": full.get("adj_pf"),
            "full_trades": full.get("trade_count"),
            "oos_net": oos.get("adj_net"), "oos_pf": oos.get("adj_pf"),
            "verdict": "full_net>0" if float(full.get("adj_net") or 0.0) > 0.0 else "full_net<=0",
        })
    ranking.sort(key=lambda r: float(r.get("full_net") or -1e9), reverse=True)
    final["family_ranking"] = ranking

    full_pos = [r for r in ranking if float(r.get("full_net") or 0.0) > 0.0]
    best_label = str(full_pos[0]["label"]) if full_pos else None
    final["best_label"] = best_label

    if not best_label:
        final["decision"] = {
            "status": "rejected",
            "reason": "ladder exhausted: no family produced a positive Full adjusted net",
            "closest": ranking[0] if ranking else None,
        }
        (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_markdown(bundle, final)
        print("DECISION: rejected (ladder exhausted, no positive Full)", flush=True)
        return

    best_params = label_to_cand[best_label]["params"]
    best_cand = label_to_cand[best_label]

    # ---- Stress + Current30D on the global best ----------------------------
    stress_submitted = [
        submit_job(bundle=bundle, label=best_label, stage="stress", period_label="slip2",
                   from_utc=FULL[1], to_utc=FULL[2], params=best_params, fee=FEE_BASE, slip=2,
                   fam=best_cand["fam"], win=best_cand["win"]),
        submit_job(bundle=bundle, label=best_label, stage="stress", period_label="fee240",
                   from_utc=FULL[1], to_utc=FULL[2], params=best_params, fee=FEE_STRESS, slip=1,
                   fam=best_cand["fam"], win=best_cand["win"]),
        submit_job(bundle=bundle, label=best_label, stage="stress", period_label="slip2_fee240",
                   from_utc=FULL[1], to_utc=FULL[2], params=best_params, fee=FEE_STRESS, slip=2,
                   fam=best_cand["fam"], win=best_cand["win"]),
    ]
    stress_rows = collect_rows(bundle, stress_submitted, "stress_rows.json")
    final["stress_rows"] = stress_rows

    cur_from, cur_to = current_window(30)
    current_submitted = [
        submit_job(bundle=bundle, label=best_label, stage="current", period_label="Current30D",
                   from_utc=cur_from, to_utc=cur_to, params=best_params, fee=FEE_BASE, slip=1,
                   fam=best_cand["fam"], win=best_cand["win"]),
    ]
    current_rows = collect_rows(bundle, current_submitted, "current_rows.json")
    final["current_rows"] = current_rows

    full = by_label_period(validation_rows, best_label, "Full")
    is_ = by_label_period(validation_rows, best_label, "IS")
    oos = by_label_period(validation_rows, best_label, "OOS")
    combined = next((r for r in stress_rows if r.get("period_label") == "slip2_fee240"), {})
    current = current_rows[0] if current_rows else {}

    gate_results = gates(
        full, is_, oos, combined, current,
        starting_capital=RL.starting_capital_from_params(best_params),
    )
    passed = all(gate_results.values())
    final["gate_results"] = gate_results
    final["decision"] = {
        "status": "paper_candidate" if passed else "rejected",
        "best_label": best_label,
        "fam": best_cand["fam"], "win": best_cand["win"],
        "locked_params": best_params,
        "gates": gate_results,
        "full": full, "is": is_, "oos": oos,
        "stress_combined": combined, "current30d": current,
    }
    (bundle / "final.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    write_markdown(bundle, final)
    print(f"DECISION: {final['decision']['status']} (best={best_label})", flush=True)
    print(f"gates: {gate_results}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke-only", action="store_true")
    ap.add_argument(
        "--class-name",
        default="",
        help="Compiled NinjaTrader class to run. Defaults to NTAMnqResearchHub; use NTAMnqSessionEdgeEngineC020 as transition fallback.",
    )
    args = ap.parse_args()
    if args.class_name:
        global CLASS_NAME, BUNDLE_PREFIX
        CLASS_NAME = args.class_name
        if args.class_name == "NTAMnqSessionEdgeEngineC020" and BUNDLE_PREFIX == "mnq_research_hub_session_edge":
            BUNDLE_PREFIX = "mnq_cell020_session_edge"
    run(smoke_only=args.smoke_only)


if __name__ == "__main__":
    main()
