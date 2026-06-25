"""Single sanity backtest for NTAMnqOvernightSettlementReversionC019."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMnqOvernightSettlementReversionC019"
INSTRUMENT = "MNQ 06-26"
SESSION_TEMPLATE = "CME US Index Futures ETH"


def main() -> None:
    params = {
        "InstrumentName": "MNQ",
        "ContractName": INSTRUMENT,
        "SessionTemplateName": SESSION_TEMPLATE,
        "BaseTimeframeSeconds": 900,
        "StartingCapital": 2000.0,
        "IntradayOnly": True,
        "ActiveMarginPerContract": 100.0,
        "MaxContractsByCapital": 20,
        "InstrumentStatus": "allowed",
        "MarginSourceBroker": "NinjaTrader",
        "EnableLong": True,
        "EnableShort": True,
        "TradeStartTime": 1400,
        "TradeEndTime": 2300,
        "ForceFlatTime": 2330,
        "SettlementTimePT": 1300,
        # ULTRA permissive
        "MinPointsFromSettlement": 5.0,
        "MaxPointsFromSettlement": 300.0,
        "DriftConsecutiveBars": 0,
        "RequireRejection": False,
        "RejectionFractionOfRange": 0.30,
        "AdxPeriod": 14, "RangeAdxMax": 80.0,
        "RsiPeriod": 14, "RsiShortMin": 50.0, "RsiLongMax": 50.0,
        "AtrPeriod": 14,
        "VolumeSmaPeriod": 20, "VolCeilingFactor": 5.0, "VolMinFactor": 0.10,
        "MinBarRangeTicks": 4, "MaxBarRangeTicks": 500,
        "StopBufferPoints": 1.5, "MinStopPoints": 4.0, "MaxStopPoints": 15.0,
        "AtrStopMult": 1.0,
        "TargetMode": "SettlementOrRR",
        "SettlementBufferPoints": 2.0,
        "RewardRiskRatio": 1.2, "MinTargetPoints": 3.0,
        "MoveToBreakevenAtR": 0.7, "BreakevenPlusTicks": 2,
        "UseTrailingStop": False, "TrailAfterR": 1.0, "TrailDistanceTicks": 12,
        "UseTimeStop": True, "TimeStopBars": 8, "MinProgressR": 0.3,
        "RiskPerTradePct": 0.6, "UserMaxContracts": 1, "MaxOpenPositions": 1,
        "MaxDailyLossUsd": 90.0, "MaxWeeklyLossUsd": 220.0,
        "MaxTradesPerDay": 5, "HardMaxTradesPerDay": 6,
        "MaxConsecutiveLosses": 5, "PauseAfterConsecutiveLosses": 3,
        "PauseMinutesAfterLosses": 30,
        "RoundTurnCommission": 1.90, "SlippageTicks": 1,
    }
    body = RL.build_job_body(
        class_name=CLASS_NAME,
        instrument=INSTRUMENT,
        params=params,
        from_utc="2025-01-01T00:00:00Z",
        to_utc="2025-12-31T23:59:59Z",
        bars_period_type="Minute",
        bars_period_value=15,
        slippage_ticks=1,
        role="smoke",
        session_template=SESSION_TEMPLATE,
        risk_profile=RL.build_risk_profile_for([INSTRUMENT]),
    )
    print("submitting sanity job...", flush=True)
    code, resp = RL.post("/api/jobs", body)
    print(f"submit code={code} resp={resp}", flush=True)
    if code != 201 or not isinstance(resp, dict):
        sys.exit(1)
    job_id = resp.get("job_id")
    print(f"job_id={job_id}", flush=True)

    base = RL.jobs_root()
    deadline = time.time() + 2400
    state = None
    while time.time() < deadline:
        for s in ("done", "failed", "cancelled"):
            if (base / s / job_id).is_dir():
                state = s; break
        if state: break
        time.sleep(2)
    print(f"final state: {state}", flush=True)

    report = RL.read_job_report(str(job_id))
    if not report:
        print("no report", flush=True); sys.exit(2)
    result = report.get("result") or {}
    trades = result.get("trades")
    if trades is None:
        tp = Path(str(report.get("_dir") or "")) / "trades.json"
        trades = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else []
    if isinstance(trades, dict):
        trades = trades.get("trades") or []
    print(f"trade_count: {len(trades)}", flush=True)
    if trades:
        gross = sum(float(t.get('pnl_currency') or 0.0) for t in trades)
        avg = gross / len(trades) if trades else 0
        wins = sum(1 for t in trades if (t.get('pnl_currency') or 0) > 0)
        print(f"raw_gross: {gross:.2f}  avg_per_trade: {avg:.2f}  win_rate: {wins/len(trades)*100:.1f}%", flush=True)
        print(f"first 3 trades: {json.dumps(trades[:3], default=str, ensure_ascii=False)[:600]}", flush=True)
    else:
        keys = list(report.keys()); print(f"report keys: {keys}", flush=True)
        diag = result.get("diag") or result.get("error") or result.get("status")
        print(f"diag/status: {diag}", flush=True)


if __name__ == "__main__":
    main()
