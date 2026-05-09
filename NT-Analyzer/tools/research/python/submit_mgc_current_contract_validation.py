"""Re-validate the MGC short-only profile on the *current* front contract
(MGC 06-26 as of 2026-05-05), not the rolled-off MGC 04-26 used in the
prior bundle.

Submits three jobs back-to-back via /api/jobs:
  1. baseline (slip=1, fee=project)
  2. slip stress (slip=2)
  3. fee stress (fee × 1.25)

Date range = whatever data is available on the resolved current contract.
With ~6 weeks of bars, this is a current-contract *sanity check*, not a
full IS/OOS validation.

Writes a manifest at:
  data/research/mgc_current_contract_validation_<TS>/manifest.json
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # type: ignore

CLASS = "NTAMicroVwapRiskExplorer"
ROOT = "MGC"
TPL = "Nymex Metals RTH1"

# Locked params from vwap_explorer_mgc_5m_shortonly_session_edge_v1.
LOCKED = {
    "StartingCapital": 2000.0, "IntradayOnly": True,
    "ActiveMarginPerContract": 200.0, "MaxContractsByCapital": 10,
    "InstrumentStatus": "allowed", "MarginSourceBroker": "NinjaTrader",
    "EnableLong": False, "EnableShort": True,
    "EmaFastPeriod": 50, "EmaSlowPeriod": 200,
    "AtrPeriod": 14, "AdxPeriod": 14, "MinAdx": 22.0,
    "VolumeSmaPeriod": 20, "MinVolumeFactor": 1.2,
    "PullbackLookback": 3,
    "AtrStopMult": 0.75, "MinStopTicks": 12, "MaxStopTicks": 12,
    "RewardRiskRatio": 3.5, "MoveToBreakevenAtR": 0.8, "TrailAfterR": 1.2,
    "EntryTimeoutBars": 2, "EntryOffsetTicks": 2,
    "TradeStartTime": 600, "TradeEndTime": 1000,
    "UseSecondTradeWindow": False, "ForceFlatTime": 1245,
    "MaxDailyLossPct": 2.0, "MaxDailyProfitPct": 4.0,
    "MaxTradesPerDay": 4, "MaxConsecutiveLosses": 3, "UserMaxContracts": 5,
    "RoundTurnCommission": 1.9, "SlippageTicks": 1, "UseDailyBiasFilter": False,
}


def main() -> int:
    front = RL.resolve_front_contract(ROOT)
    if "skip_reason" in front:
        print("CANNOT VALIDATE:", front); return 2
    instr = front["instrument"]
    df, dl = front["data_first"], front["data_last"]
    print(f"Current contract for {ROOT}: {instr}  data {df}..{dl}  stale={front.get('stale')}")

    # Use the contract's full available window — pad by +/-1 day for safety.
    from_utc = f"{df}T00:00:00Z"
    to_utc = f"{dl}T23:59:59Z"

    risk = RL.build_risk_profile_for([instr])

    runs = [
        ("baseline_slip1_fee1.90", dict(LOCKED), 1),
        ("slip2",                  {**LOCKED, "SlippageTicks": 2}, 2),
        ("fee125",                 {**LOCKED, "RoundTurnCommission": round(1.9*1.25, 2)}, 1),
    ]

    submitted = []
    for tag, p, slip in runs:
        body = RL.build_job_body(
            class_name=CLASS, instrument=instr, params=p,
            from_utc=from_utc, to_utc=to_utc,
            slippage_ticks=slip, role="research",
            session_template=TPL, risk_profile=risk,
        )
        body["tags"] = ["mgc_current_contract_validation", tag]
        code, resp = RL.post("/api/jobs", body)
        jid = resp.get("job_id") or resp.get("id")
        print(f"  {tag}: HTTP {code}  job_id={jid}")
        submitted.append({"tag": tag, "job_id": jid, "http": code, "resp": resp})

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = RL.DATA / "research" / f"mgc_current_contract_validation_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": "current-contract sanity check for MGC short-only profile",
        "strategy_class": CLASS,
        "instrument_resolved": front,
        "session_template": TPL,
        "from_utc": from_utc, "to_utc": to_utc,
        "locked_parameters": LOCKED,
        "submitted_jobs": submitted,
        "fee_basis": "PROJECT BACKTEST ASSUMPTION (NinjaTrader-side cost model). Not an external prop-firm or broker fee schedule.",
        "instrument_universe_source": "data/catalog/instrument_groups.json group_name='Micros' (no separate local micro group playlist exists in this project; the local 'Micros' group is the instrument list)",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nmanifest -> {out_dir/'manifest.json'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
