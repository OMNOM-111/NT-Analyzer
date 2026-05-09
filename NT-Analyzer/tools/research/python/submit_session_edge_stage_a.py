"""Stage A — broad scan across all product families using the locked Pilot
B1 ShortOnly parameter family as the reference setup, but routed through the
correct TradingHours template per product family. One batch per family
(family → one session template).

Goal: honest baseline measurement of whether the existing VwapPullback core
has any signal on non-MNQ markets, NOW that each market gets its proper
session calendar. NOT a parameter sweep — that comes after we see signal.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMicroVwapRiskExplorer"
FROM_UTC = "2024-01-01T00:00:00Z"
TO_UTC   = "2025-12-31T23:59:59Z"

# (family_label, [roots], TradeStart_HHMM, TradeEnd_HHMM, ForceFlat_HHMM)
# Times are HHMM in the strategy's local clock (Pacific Time, matching the
# locked Pilot profile convention 06:35 PT = NY open + 5min).
FAMILIES = [
    ("index_micros", ["MES", "MYM", "M2K"], 635, 1000, 1245),
    ("metals",       ["MGC", "MHG", "SIL"], 600, 1000, 1245),
    ("energy",       ["MCL", "MNG"],         600, 1000, 1245),
    ("fx",           ["M6A", "M6B", "M6E"],  100, 1000, 1245),
    ("crypto",       ["MBT", "MET"],            0, 2200, 2245),
]

# Three direction passes per family.
DIRECTIONS = [
    ("shortonly", {"EnableLong": False, "EnableShort": True}),
    ("longonly",  {"EnableLong": True,  "EnableShort": False}),
    ("longshort", {"EnableLong": True,  "EnableShort": True}),
]


def main() -> int:
    submitted = []
    skipped = []
    for label, roots, t0, t1, tflat in FAMILIES:
        contracts: list[str] = []
        for r in roots:
            c = RL.resolve_front_contract(r)
            if "skip_reason" in c:
                skipped.append({"family": label, "root": r,
                                "reason": c["skip_reason"]})
                continue
            contracts.append(c["instrument"])
        if not contracts:
            print(f"[SKIP-FAMILY] {label}: no resolvable contracts")
            continue
        # Use the most conservative (highest) margin and fee in the family
        # so the same parameters apply to all batch children.
        worst_root = max(roots, key=RL.margin_for)
        for dlabel, dparams in DIRECTIONS:
            params = {
                **RL.base_risk_params(worst_root),
                **dparams,
                "TradeStartTime": t0,
                "TradeEndTime": t1,
                "ForceFlatTime": tflat,
                # VWAP-pullback entry filters (Pilot B1 family).
                "MinAdx": 22.0,
                "MinVolumeFactor": 1.2,
                "PullbackLookback": 3,
                "MinStopTicks": 12,
                "MaxStopTicks": 12,
                "RewardRiskRatio": 3.5,
                "EntryOffsetTicks": 2,
                "EntryTimeoutBars": 2,
            }
            res = RL.submit_batch(
                name=f"sedge_stageA_{label}_{dlabel}",
                class_name=CLASS_NAME,
                instruments=contracts,
                params=params,
                from_utc=FROM_UTC, to_utc=TO_UTC,
                bars_period_type="Minute", bars_period_value=5,
                slippage_ticks=1, role="research",
                session_template=RL.session_for(roots[0]),
            )
            submitted.append({
                "family": label, "direction": dlabel,
                "instruments": contracts,
                "session_template": RL.session_for(roots[0]),
                "fee_used": params["RoundTurnCommission"],
                "code": res["code"],
                "response": res["response"],
            })
            ok = res["code"] == 201
            print(f"[{label}/{dlabel:9s}] code={res['code']} "
                  f"batch={res['response'].get('batch_id') if ok else res['response']}")

    out_dir = RL.DATA / "research"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"_stageA_{RL.utcnow_compact()}.json"
    out_path.write_text(json.dumps({"submitted": submitted, "skipped": skipped},
                                   indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\nmanifest: {out_path}")
    print(f"submitted batches: {len(submitted)}")
    print(f"skipped instruments: {len(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
