"""Submit target-specific stress tests for the best MNQ MICRO_ORB variants.

The broad follow-up found RR150/RR175 as the best candidates. This script tests
whether those targets survive tougher execution and whether the original 0.35%
risk budget is merely too tight for a $2000 / 1-contract MNQ account.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import mnq_scalp_pilot_lib as MS  # noqa: E402


ROOT = "MNQ"

PERIODS: List[Tuple[str, str, str]] = [
    ("Full", "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
    ("IS", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("OOS", "2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
    ("Q2_2024", "2024-04-01T00:00:00Z", "2024-06-30T23:59:59Z"),
    ("Q3_2025", "2025-07-01T00:00:00Z", "2025-09-30T23:59:59Z"),
    ("FWD_2026_SMOKE", "2026-03-12T00:00:00Z", "2026-04-24T23:59:59Z"),
]

VARIANTS: List[Tuple[str, Dict[str, Any], int]] = [
    ("RR150_SLIP2", {"RewardRiskRatio": 1.50, "SlippageTicks": 2}, 2),
    ("RR150_FEE240", {"RewardRiskRatio": 1.50, "RoundTurnCommission": 2.40}, 1),
    ("RR150_SLIP2_FEE240", {"RewardRiskRatio": 1.50, "SlippageTicks": 2, "RoundTurnCommission": 2.40}, 2),
    ("RR175_SLIP2", {"RewardRiskRatio": 1.75, "SlippageTicks": 2}, 2),
    ("RR175_FEE240", {"RewardRiskRatio": 1.75, "RoundTurnCommission": 2.40}, 1),
    ("RR175_SLIP2_FEE240", {"RewardRiskRatio": 1.75, "SlippageTicks": 2, "RoundTurnCommission": 2.40}, 2),
    ("RR150_RISK050_SLIP2", {"RewardRiskRatio": 1.50, "RiskPerTradePct": 0.50, "SlippageTicks": 2}, 2),
    ("RR175_RISK050_SLIP2", {"RewardRiskRatio": 1.75, "RiskPerTradePct": 0.50, "SlippageTicks": 2}, 2),
]


def variant_params(overrides: Dict[str, Any]) -> Dict[str, Any]:
    params = MS.scalp_params(ROOT, "MICRO_ORB")
    params.update(overrides)
    return params


def submit_one(bundle: Path, variant: str, overrides: Dict[str, Any], slippage_ticks: int,
               label: str, from_utc: str, to_utc: str) -> Dict[str, Any]:
    instruments = MS.contracts_for_period(ROOT, from_utc, to_utc)
    params = variant_params(overrides)
    res = RL.submit_batch(
        name=f"mnq_microorb_targetstress_{variant}_{label}",
        class_name=MS.CLASS_NAME,
        instruments=instruments,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=slippage_ticks,
        role="research",
        session_template=RL.session_for(ROOT),
        risk_profile=RL.build_risk_profile_for(instruments),
    )
    bid = res["response"].get("batch_id") if res["code"] == 201 else None
    print(f"[{variant:24s} {label:14s}] code={res['code']} batch={bid or res['response']}")
    return {
        "name": f"mnq_microorb_targetstress_{variant}_{label}",
        "module": variant,
        "period_label": label,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "instruments": instruments,
        "params": params,
        "code": res["code"],
        "batch_id": bid,
        "response": res["response"],
    }


def main() -> int:
    bundle = RL.DATA / "research" / f"mnq_microorb_targetstress_{RL.utcnow_compact()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"Bundle dir: {bundle}\n")
    submitted: List[Dict[str, Any]] = []
    for variant, overrides, slip in VARIANTS:
        for label, fr, to in PERIODS:
            submitted.append(submit_one(bundle, variant, overrides, slip, label, fr, to))
    manifest = bundle / "targetstress_manifest.json"
    manifest.write_text(
        json.dumps({"stage": "targetstress", "submitted": submitted}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nmanifest -> {manifest}\nbatches: {sum(1 for s in submitted if s.get('batch_id'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
