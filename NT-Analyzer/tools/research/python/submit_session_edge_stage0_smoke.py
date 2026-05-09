"""Stage 0 smoke: one batch per product family (different TradingHours
template) using NTAMicroVwapRiskExplorer with an extremely loose entry
window so we just verify bars + template plumbing — NOT trading edge.

Each batch carries one instrument so we can read each bridge diagnostics
log per template independently. Outputs the submitted batch_ids to stdout
and to data/research/_stage0_smoke_<TS>.json for the manifest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMicroVwapRiskExplorer"

# (family_label, root, smoke_window_start_HHMM, end_HHMM, force_flat_HHMM)
FAMILIES = [
    ("index_micros", "MES",  835, 1400, 1355),
    ("metals",       "MGC",  830, 1400, 1355),
    ("energy",       "MCL",  900, 1400, 1355),
    ("fx",           "M6E",  300, 1400, 1355),
    ("crypto",       "MBT",    0, 2300, 2255),
]

# Tiny date window to keep smoke fast.
FROM_UTC = "2025-09-01T00:00:00Z"
TO_UTC   = "2025-09-15T00:00:00Z"


def main() -> int:
    submitted = []
    for label, root, t0, t1, tflat in FAMILIES:
        c = RL.resolve_front_contract(root)
        if "skip_reason" in c:
            submitted.append({"family": label, "root": root,
                              "skipped": c["skip_reason"]})
            print(f"[SKIP] {label}/{root}: {c['skip_reason']}")
            continue
        params = {
            "EnableLong": False,
            "EnableShort": True,
            "TradeStartTime": t0,
            "TradeEndTime": t1,
            "ForceFlatTime": tflat,
            "MinAdx": 12,
            "MinVolumeFactor": 0.5,
            "PullbackLookback": 5,
            "MinStopTicks": 8,
            "MaxStopTicks": 24,
            "RewardRiskRatio": 2.0,
            "EntryOffsetTicks": 1,
            "EntryTimeoutBars": 2,
            "RoundTurnCommission": RL.fee_for(root),
        }
        # Smoke role, so non-supported templates are still allowed by backend.
        result = RL.submit_batch(
            name=f"stage0_smoke_{label}_{root}",
            class_name=CLASS_NAME,
            instruments=[c["instrument"]],
            params=params,
            from_utc=FROM_UTC, to_utc=TO_UTC,
            bars_period_type="Minute", bars_period_value=5,
            slippage_ticks=1, role="smoke",
            session_template=RL.session_for(root),
        )
        submitted.append({"family": label, "root": root,
                          "instrument": c["instrument"],
                          "session_template": RL.session_for(root),
                          "code": result["code"],
                          "response": result["response"]})
        print(f"[{label}/{root}] code={result['code']} "
              f"resp={json.dumps(result['response'])[:160]}")

    out_dir = RL.DATA / "research"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"_stage0_smoke_{RL.utcnow_compact()}.json"
    out_path.write_text(json.dumps(submitted, indent=2), encoding="utf-8")
    print(f"\nmanifest: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
