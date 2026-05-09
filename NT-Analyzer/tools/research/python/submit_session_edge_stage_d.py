"""Stage D — IS/OOS/stress for Stage A survivors.

Candidates from Stage A v3 (batch ts ~185338-185339):
  - MGC 04-26  metals shortonly  (57 trades, +$1100, PF 1.95)
  - MNG 05-26  energy shortonly  (41 trades, +$138,  PF 1.20)
  - MYM 06-26  index   shortonly (130 trades, +$194, PF 1.08)
  - MHG 05-26  metals shortonly  (32 trades, +$32,   PF 1.05)
  - M2K 06-26  index   shortonly (175 trades, +$102, PF 1.04)

Per candidate we run:
  IS  (2024)  baseline
  OOS (2025)  baseline
  Stress: slip=2 over Full
  Stress: fee*1.25 over Full
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import research_lib as RL  # noqa: E402

CLASS_NAME = "NTAMicroVwapRiskExplorer"

# (label, root, contract, family-time-window)
CANDIDATES = [
    ("mgc_short", "MGC", "MGC 04-26", "metals"),
    ("mng_short", "MNG", "MNG 05-26", "energy"),
    ("mym_short", "MYM", "MYM 06-26", "index"),
    ("mhg_short", "MHG", "MHG 05-26", "metals"),
    ("m2k_short", "M2K", "M2K 06-26", "index"),
]

WINDOW_BY_FAMILY = {
    "index":  (635, 1000, 1245),
    "metals": (600, 1000, 1245),
    "energy": (600, 1000, 1245),
}


def base_params(root: str, family: str) -> dict:
    t0, t1, tflat = WINDOW_BY_FAMILY[family]
    return {
        **RL.base_risk_params(root),
        "EnableLong": False, "EnableShort": True,
        "TradeStartTime": t0, "TradeEndTime": t1, "ForceFlatTime": tflat,
        "MinAdx": 22.0, "MinVolumeFactor": 1.2, "PullbackLookback": 3,
        "MinStopTicks": 12, "MaxStopTicks": 12,
        "RewardRiskRatio": 3.5,
        "EntryOffsetTicks": 2, "EntryTimeoutBars": 2,
    }


def main() -> int:
    submitted = []
    for label, root, contract, family in CANDIDATES:
        st = RL.session_for(root)
        rp = RL.build_risk_profile_for([contract])
        # IS 2024
        for variant, fro, to, override_params, override_slip in [
            ("is2024",  "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z", {}, 1),
            ("oos2025", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z", {}, 1),
            ("slip2",   "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z", {"SlippageTicks": 2}, 2),
            ("fee125",  "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z",
                {"RoundTurnCommission": RL.fee_stress(root)}, 1),
        ]:
            params = {**base_params(root, family), **override_params}
            res = RL.submit_batch(
                name=f"sedge_stageD_{label}_{variant}",
                class_name=CLASS_NAME,
                instruments=[contract],
                params=params,
                from_utc=fro, to_utc=to,
                bars_period_type="Minute", bars_period_value=5,
                slippage_ticks=override_slip, role="research",
                session_template=st, risk_profile=rp,
            )
            ok = res["code"] == 201
            print(f"[{label}/{variant:8s}] code={res['code']} batch="
                  f"{res['response'].get('batch_id') if ok else res['response']}")
            submitted.append({
                "label": label, "variant": variant,
                "instrument": contract, "session_template": st,
                "from_utc": fro, "to_utc": to,
                "params": params, "slippage_ticks": override_slip,
                "code": res["code"], "response": res["response"],
            })
    out_path = RL.DATA / "research" / f"_stageD_{RL.utcnow_compact()}.json"
    out_path.write_text(json.dumps(submitted, indent=2), encoding="utf-8")
    print(f"\nmanifest: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
