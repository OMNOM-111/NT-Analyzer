"""
Phase 2 backtest runner — NTAMicroVwapRiskPilot v0.1
=====================================================
Sends 3 jobs (capital 1000/2000/3000) with EXPLICIT Risk Profile parameters
so the strategy trades even if the backend mapper is not yet active.

Usage:
    python tools\run_backtest_vwap_v1.py

Requirements:
    - NT-Analyzer backend running on http://127.0.0.1:8765
    - NinjaTrader 8 running with NT-Analyzer bridge loaded
    - NTAMicroVwapRiskPilot strategy compiled in NinjaTrader
"""

import urllib.request
import json
import os
import sys
import time

BASE_URL = "http://127.0.0.1:8765"
JOBS_DIR = os.path.join(os.path.dirname(__file__), "..", "jobs")

# MES intraday margin (CME Micro E-mini S&P 500): ~$40 intraday per contract
MES_MARGIN = 40.0


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


def submit_job(capital: float) -> str:
    """Submit a backtest with explicit Risk Profile parameters."""
    max_contracts = max(1, int(capital // MES_MARGIN))
    max_contracts = min(max_contracts, 10)  # safety cap

    payload = {
        "class_name": "NTAMicroVwapRiskPilot",
        "instrument": "MES 06-26",
        "bars_period_type": "Minute",
        "bars_period_value": 5,
        "from_utc": "2024-01-01T00:00:00Z",
        "to_utc": "2025-12-31T00:00:00Z",
        "calculate": "OnBarClose",
        "is_tick_replay": False,
        "risk_profile": {
            "starting_capital": capital,
            "intraday_only": True,
        },
        "parameters": {
            # === Risk Profile (explicit — bypasses mapper) ===
            "StartingCapital": float(capital),
            "IntradayOnly": True,
            "ActiveMarginPerContract": MES_MARGIN,
            "MaxContractsByCapital": max_contracts,
            "InstrumentStatus": "allowed",
            "MarginSourceBroker": "CME",
            # === Risk ===
            "RiskPerTradePct": 1.0,
            "MaxDailyLossPct": 2.0,
            "MaxDailyProfitPct": 4.0,
            "MaxTradesPerDay": 6,
            "MaxConsecutiveLosses": 3,
            "UserMaxContracts": max_contracts,
            "RoundTurnCommission": 1.90,
            "SlippageTicks": 1,
            # === Strategy tuning (relaxed for first run) ===
            "MinAdx": 15.0,
            "MinVolumeFactor": 0.7,
            "PullbackLookback": 5,
            "AtrStopMult": 0.8,
            "MinStopTicks": 4,
            "MaxStopTicks": 20,
            "RewardRiskRatio": 1.5,
            "AvoidFirstMinutesAfterOpen": 3,
            "NoEntryMinutesBeforeClose": 20,
            "ForceFlatMinutesBeforeClose": 10,
        },
    }

    resp = post_json(f"{BASE_URL}/api/jobs", payload)
    job_id = resp.get("job_id")
    if not job_id:
        raise RuntimeError(f"No job_id in response: {resp}")
    return job_id


def wait_for_result(job_id: str, timeout_s: int = 600) -> dict | None:
    """Poll until job is done or failed. Returns result dict or None."""
    deadline = time.time() + timeout_s
    dots = 0
    while time.time() < deadline:
        # Check filesystem first (faster)
        for folder in ("done", "failed"):
            path = os.path.join(JOBS_DIR, folder, job_id, "result.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    return json.load(f), folder
        # Also check API
        try:
            info = get_json(f"{BASE_URL}/api/jobs/{job_id}")
            status = info.get("status", "?")
            if status in ("done", "failed"):
                # Try filesystem once more
                for folder in ("done", "failed"):
                    path = os.path.join(JOBS_DIR, folder, job_id, "result.json")
                    if os.path.exists(path):
                        with open(path, encoding="utf-8", errors="replace") as f:
                            return json.load(f), folder
        except Exception:
            pass

        dots += 1
        if dots % 10 == 0:
            print(f"  [{job_id}] still running ({dots * 5}s)...")
        time.sleep(5)

    return None, "timeout"


def print_result(job_id: str, capital: float, result: dict, folder: str) -> None:
    print(f"\n{'='*60}")
    print(f"Job: {job_id}  capital=${capital:.0f}  [{folder}]")
    print(f"{'='*60}")

    perf = result.get("performance", {})
    if not perf:
        # Try alternative structures
        perf = result.get("summary", result.get("result", {}))

    if perf:
        keys = [
            ("total_trades", "Trades total"),
            ("trade_count", "Trades total"),
            ("winning_trades", "Winning trades"),
            ("winning_pct", "Win rate %"),
            ("profit_factor", "Profit factor"),
            ("net_profit", "Net profit $"),
            ("gross_profit", "Gross profit $"),
            ("gross_loss", "Gross loss $"),
            ("max_drawdown", "Max drawdown $"),
            ("avg_trade", "Avg trade $"),
            ("avg_win", "Avg win $"),
            ("avg_loss", "Avg loss $"),
            ("sharpe_ratio", "Sharpe ratio"),
        ]
        for k, label in keys:
            if k in perf:
                v = perf[k]
                if isinstance(v, float):
                    print(f"  {label:<20}: {v:.2f}")
                else:
                    print(f"  {label:<20}: {v}")
    else:
        print("  [no performance block found]")
        # Print raw result structure
        print("  Keys:", list(result.keys()))
        # Print context.strategy.final_parameters to diagnose
        ctx = result.get("context", {})
        strat = ctx.get("strategy", {})
        fp = strat.get("final_parameters", {})
        if fp:
            print("\n  Final parameters received by strategy:")
            for k, v in fp.items():
                print(f"    {k}: {v}")


def main():
    print("=== NTAMicroVwapRiskPilot Phase 2 Backtest ===")
    print(f"Backend: {BASE_URL}")
    print(f"Period: 2024-01-01 .. 2025-12-31  |  MES 06-26  |  5m bars")
    print()

    # Check backend is up
    try:
        health = get_json(f"{BASE_URL}/api/health")
        if not health.get("ok"):
            print("ERROR: backend health check failed:", health)
            sys.exit(1)
        print(f"✓ Backend OK  |  NinjaTrader running: {health.get('ninjatrader_running')}")
    except Exception as e:
        print(f"ERROR: cannot reach backend at {BASE_URL}: {e}")
        sys.exit(1)

    job_ids = {}
    for capital in [1000, 2000, 3000]:
        try:
            jid = submit_job(capital)
            job_ids[capital] = jid
            print(f"✓ Submitted capital={capital}  job_id={jid}")
        except Exception as e:
            print(f"✗ Failed capital={capital}: {e}")

    if not job_ids:
        print("No jobs submitted.")
        sys.exit(1)

    print(f"\nWaiting for {len(job_ids)} jobs (max 10 min each)...")

    results = {}
    for capital, jid in job_ids.items():
        print(f"\nWaiting for capital={capital} [{jid}]...")
        result, folder = wait_for_result(jid, timeout_s=600)
        if result:
            results[capital] = (result, folder)
            print_result(jid, capital, result, folder)
        else:
            print(f"  TIMEOUT — job {jid} did not complete in time")

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for capital in sorted(results):
        result, folder = results[capital]
        perf = result.get("performance", {})
        trades = perf.get("total_trades") or perf.get("trade_count", "?")
        wr = perf.get("winning_pct", "?")
        pf = perf.get("profit_factor", "?")
        np_ = perf.get("net_profit", "?")
        print(f"  capital={capital:5.0f}  trades={trades!s:>5}  WR={wr!s:>6}%  PF={pf!s:>5}  NetP={np_!s:>8}")

    # Print final parameters check
    if results:
        first_result, _ = next(iter(results.values()))
        fp = first_result.get("context", {}).get("strategy", {}).get("final_parameters", {})
        if fp:
            print("\nMapper check (should be non-zero):")
            print(f"  StartingCapital       = {fp.get('StartingCapital', '?')}")
            print(f"  InstrumentStatus      = {fp.get('InstrumentStatus', '?')}")
            print(f"  ActiveMarginPerContr. = {fp.get('ActiveMarginPerContract', '?')}")
            print(f"  MaxContractsByCapital = {fp.get('MaxContractsByCapital', '?')}")


if __name__ == "__main__":
    main()
