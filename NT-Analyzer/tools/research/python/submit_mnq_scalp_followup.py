"""Submit focused follow-up research for the MNQ MICRO_ORB scalp candidate.

This is not the broad 4-instrument sweep. It stress-tests and tunes the only
positive candidate from mnq_scalp_pilot_20260507_0023:

  NTAMicroMnqScalpPilot / MNQ / MICRO_ORB

The manifest remains compatible with collect_mnq_scalp_pilot.py because each
variant is encoded as a distinct "module" label.
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

FOLLOWUP_PERIODS: List[Tuple[str, str, str]] = MS.PERIODS + [
    ("FWD_2026_SMOKE", "2026-03-12T00:00:00Z", "2026-04-24T23:59:59Z"),
]

VARIANTS: List[Tuple[str, Dict[str, Any], int]] = [
    ("MICRO_ORB_BASE", {}, 1),
    ("MICRO_ORB_SLIP2", {"SlippageTicks": 2}, 2),
    ("MICRO_ORB_FEE240", {"RoundTurnCommission": 2.40}, 1),
    ("MICRO_ORB_SLIP2_FEE240", {"SlippageTicks": 2, "RoundTurnCommission": 2.40}, 2),
    ("MICRO_ORB_RR100", {"RewardRiskRatio": 1.00}, 1),
    ("MICRO_ORB_RR150", {"RewardRiskRatio": 1.50}, 1),
    ("MICRO_ORB_RR175", {"RewardRiskRatio": 1.75}, 1),
    ("MICRO_ORB_OR5", {"OrbDurationMinutes": 5}, 1),
    ("MICRO_ORB_OR10", {"OrbDurationMinutes": 10}, 1),
    ("MICRO_ORB_BUFFER0", {"OrbBreakoutBuffer": 0}, 1),
    ("MICRO_ORB_BUFFER2", {"OrbBreakoutBuffer": 2}, 1),
    ("MICRO_ORB_RETEST8", {"OrbRetestBars": 8}, 1),
    ("MICRO_ORB_TS4", {"TimeStopBars": 4}, 1),
]


def variant_params(overrides: Dict[str, Any]) -> Dict[str, Any]:
    params = MS.scalp_params(ROOT, "MICRO_ORB")
    params.update(overrides)
    return params


def submit_one(bundle: Path, variant: str, overrides: Dict[str, Any], slippage_ticks: int,
               period_label: str, from_utc: str, to_utc: str) -> Dict[str, Any]:
    instruments = MS.contracts_for_period(ROOT, from_utc, to_utc)
    if not instruments:
        return {
            "name": f"mnq_microorb_followup_{variant}_{period_label}",
            "module": variant,
            "period_label": period_label,
            "from_utc": from_utc,
            "to_utc": to_utc,
            "instruments": [],
            "params": variant_params(overrides),
            "code": 0,
            "batch_id": None,
            "response": {"skip_reason": "no overlapping minute-data contract"},
        }

    params = variant_params(overrides)
    res = RL.submit_batch(
        name=f"mnq_microorb_followup_{variant}_{period_label}",
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
    print(f"[{variant:24s} {period_label:14s}] code={res['code']} batch={bid or res['response']}")
    return {
        "name": f"mnq_microorb_followup_{variant}_{period_label}",
        "module": variant,
        "period_label": period_label,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "instruments": instruments,
        "params": params,
        "code": res["code"],
        "batch_id": bid,
        "response": res["response"],
    }


def main(argv: List[str]) -> int:
    bundle = RL.DATA / "research" / f"mnq_microorb_followup_{RL.utcnow_compact()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"Bundle dir: {bundle}\n")

    submitted: List[Dict[str, Any]] = []
    for variant, overrides, slip in VARIANTS:
        for label, fr, to in FOLLOWUP_PERIODS:
            submitted.append(submit_one(bundle, variant, overrides, slip, label, fr, to))

    manifest = bundle / "followup_manifest.json"
    manifest.write_text(
        json.dumps({"stage": "followup", "submitted": submitted}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nmanifest -> {manifest}\nbatches: {sum(1 for s in submitted if s.get('batch_id'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
