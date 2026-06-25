"""Permissive per-family smoke for NTAMnqSessionEdgeEngineC020.

Fires each entry family once on a short recent window with wide-open windows
and minimal filters, to confirm the freshly compiled assembly actually executes
every Mode before launching the full ladder. Trade counts > 0 per family means
the dispatcher and anchor logic are live.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMnqSessionEdgeEngineC020"
ROOT = "MNQ"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures ETH"

FROM = "2025-11-01T00:00:00Z"
TO = "2025-12-31T23:59:59Z"

MODES = ["OrRangeReclaim", "FailedBreak", "VwapPullback", "RangeReject"]


def permissive_params(mode: str) -> Dict[str, Any]:
    return {
        "InstrumentName": ROOT,
        "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": 300,
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": RL.margin_for(ROOT),
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "EnableLong": True,
        "EnableShort": True,
        "Mode": mode,
        # Build anchor across the whole overnight, trade the entire RTH-ish day.
        "RangeStartTime": 0,
        "RangeEndTime": 359,
        "TradeStartTime": 400,
        "TradeEndTime": 1230,
        "UseSecondTradeWindow": False,
        "ForceFlatTime": 1259,
        "EmaFastPeriod": 9, "EmaMidPeriod": 21, "EmaSlowPeriod": 50,
        "AtrPeriod": 14, "VolumeSmaPeriod": 20,
        "MinVolumeFactor": 0.01,
        "RequireVwapAgreement": False,
        "RequireEmaAgreement": False,
        "RequireEmaSlope": False,
        "RequireEmaStack": False,
        "ReclaimBufferTicks": 1,
        "FailReturnTicks": 1,
        "RejectWickTicks": 8,
        "PullbackTicks": 16,
        "StopBufferTicks": 4, "MinStopTicks": 12, "MaxStopTicks": 60,
        "AtrStopMult": 1.0, "RewardRiskRatio": 1.5, "MinTargetTicks": 12,
        "EntryOffsetTicks": 0, "EntryTimeoutBars": 3,
        "MoveToBreakevenAtR": 1.0, "BreakevenPlusTicks": 2,
        "UseTrailingStop": False, "TrailAfterR": 1.5, "TrailDistanceTicks": 12,
        "UseTimeStop": True, "TimeStopBars": 8, "MinProgressR": 0.30,
        "RiskPerTradePct": 0.75, "UserMaxContracts": 1, "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 100000.0, "MaxWeeklyLossUsd": 100000.0,
        "MaxTradesPerDay": 50, "HardMaxTradesPerDay": 50,
        "MaxConsecutiveLosses": 50, "PauseAfterConsecutiveLosses": 50,
        "PauseMinutesAfterLosses": 0,
        "RoundTurnCommission": 1.90, "SlippageTicks": 1,
    }


def main() -> None:
    rows: List[Dict[str, Any]] = []
    for mode in MODES:
        body = RL.build_job_body(
            class_name=CLASS_NAME, instrument=INSTRUMENT,
            params=permissive_params(mode), from_utc=FROM, to_utc=TO,
            bars_period_type="Minute", bars_period_value=5, slippage_ticks=1,
            role="smoke", session_template=SESSION_TEMPLATE,
            risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
        )
        code, resp = RL.post("/api/jobs", body)
        job_id = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
        print(f"submit {mode:16s} code={code} job={job_id or resp}", flush=True)
        rows.append({"mode": mode, "job_id": job_id})

    base = RL.jobs_root()

    def state(jid: str) -> str:
        for s in ("done", "failed", "cancelled", "running", "pending"):
            if (base / s / jid).is_dir():
                return s
        if (base / "failed" / ".quarantine" / jid).is_dir():
            return "failed"
        return "missing"

    remaining = {r["job_id"] for r in rows if r["job_id"]}
    deadline = time.time() + 1800
    while remaining and time.time() < deadline:
        for jid in list(remaining):
            if state(jid) in {"done", "failed", "cancelled"}:
                remaining.remove(jid)
        if remaining:
            time.sleep(3)

    for r in rows:
        jid = r["job_id"]
        if not jid:
            print(f"{r['mode']:16s} NO JOB", flush=True)
            continue
        st = state(jid)
        report = RL.read_job_report(jid)
        trades = []
        if report and isinstance(report.get("result"), dict):
            trades = report["result"].get("trades") or []
        if not trades:
            d = Path(str((report or {}).get("_dir") or ""))
            tp = d / "trades.json"
            if tp.exists():
                raw = json.loads(tp.read_text(encoding="utf-8"))
                trades = raw if isinstance(raw, list) else raw.get("trades", [])
        err = ""
        if st == "failed":
            d = base / "failed" / jid
            ep = d / "error.json"
            if ep.exists():
                err = ep.read_text(encoding="utf-8")[:300]
        print(f"{r['mode']:16s} state={st:8s} trades={len(trades)} {err}", flush=True)


if __name__ == "__main__":
    main()
