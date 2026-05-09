"""One-off: promote 4 non-index session templates by submitting role='smoke'."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import research_lib as RL

PROBES = [
    ("Nymex Metals RTH1",  "MGC"),
    ("Nymex Energy RTH",   "MCL"),
    ("CME FX Futures RTH", "M6A"),
    ("Cryptocurrency",     "MBT"),
]

BASE_PARAMS = {
    "SetupMode": "VwapPullback",
    "EnableLong": True, "EnableShort": True,
    "TradeStartTime": 0, "TradeEndTime": 2300, "ForceFlatTime": 2345,
    "MinAdx": 0.0, "MinVolumeFactor": 0.5, "PullbackLookback": 1,
    "MinStopTicks": 8, "MaxStopTicks": 60,
    "RewardRiskRatio": 1.5,
    "EntryOffsetTicks": 1, "EntryTimeoutBars": 2,
    "EmaFastPeriod": 50, "EmaSlowPeriod": 200,
    "AtrPeriod": 14, "AdxPeriod": 14, "VolumeSmaPeriod": 20,
    "AtrStopMult": 0.75,
    "MoveToBreakevenAtR": 0.8, "TrailAfterR": 1.2,
    "UseSecondTradeWindow": False, "UseDailyBiasFilter": False,
    "OrbDurationMinutes": 30, "OrbBreakoutBuffer": 1, "OrbFailedLookback": 3,
    "MeanRevExtensionAtr": 1.5, "MeanRevTargetVwap": True,
    "CompressionLookback": 30, "CompressionAtrPct": 0.30,
    "RollingVwapBars": 288, "Use24hSession": False,
}

if __name__ == "__main__":
    for tpl, root in PROBES:
        c = RL.resolve_front_contract(root)
        if "skip_reason" in c:
            print(f"  skip {root}: {c}"); continue
        instr = c["instrument"]
        params = {**RL.base_risk_params(root), **BASE_PARAMS}
        res = RL.submit_batch(
            name=f"sev2_promote_{root.lower()}",
            class_name="NTAMicroSessionEdgeExplorer",
            instruments=[instr], params=params,
            from_utc="2025-10-01T00:00:00Z", to_utc="2025-10-15T23:59:59Z",
            slippage_ticks=1, role="smoke", session_template=tpl,
        )
        print(f"  {tpl:25s} {root:5s} -> code={res['code']} "
              f"{str(res['response'])[:140]}")
