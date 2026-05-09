"""Submit NTAMicroMnqScalpPilot research batches.

Usage:
  python submit_mnq_scalp_pilot.py stage0
  python submit_mnq_scalp_pilot.py full

stage0 submits a short 2026 current-contract smoke for ALL + each module.
full submits MNQ/MES/MYM/M2K across Full/IS/OOS/8 quarters for ALL + modules.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402
import mnq_scalp_pilot_lib as MS  # noqa: E402


def submit_one(bundle: Path, name: str, instruments: List[str],
               module: str, period_label: str, from_utc: str, to_utc: str) -> Dict[str, Any]:
    root = instruments[0].split()[0]
    params = MS.scalp_params(root, module)
    res = RL.submit_batch(
        name=name,
        class_name=MS.CLASS_NAME,
        instruments=instruments,
        params=params,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=1,
        slippage_ticks=1,
        role="research",
        session_template=RL.session_for(root),
        risk_profile=RL.build_risk_profile_for(instruments),
    )
    bid = res["response"].get("batch_id") if res["code"] == 201 else None
    print(f"[{name:56s}] code={res['code']} batch={bid or res['response']}")
    return {
        "name": name,
        "module": module,
        "period_label": period_label,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "instruments": instruments,
        "params": params,
        "code": res["code"],
        "batch_id": bid,
        "response": res["response"],
    }


def write_manifest(bundle: Path, stage: str, submitted: List[Dict[str, Any]]) -> None:
    p = bundle / f"{stage}_manifest.json"
    p.write_text(json.dumps({"stage": stage, "submitted": submitted},
                            indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nmanifest -> {p}\nbatches: {len(submitted)}")


def stage0(bundle: Path) -> None:
    instruments = MS.contracts_for_roots(["MNQ"])
    label, fr, to = MS.SMOKE_PERIOD
    submitted = []
    for module in MS.MODULES:
        submitted.append(submit_one(
            bundle, f"mnq_scalp_stage0_{module}", instruments,
            module, label, fr, to,
        ))
    write_manifest(bundle, "stage0", submitted)


def full(bundle: Path) -> None:
    submitted = []
    for root in MS.ROOTS:
        for module in MS.MODULES:
            for label, fr, to in MS.PERIODS:
                instruments = MS.contracts_for_period(root, fr, to)
                if not instruments:
                    print(f"skip {root} {module} {label}: no overlapping minute-data contract")
                    continue
                submitted.append(submit_one(
                    bundle,
                    f"mnq_scalp_{root}_{module}_{label}",
                    instruments, module, label, fr, to,
                ))
    write_manifest(bundle, "full", submitted)


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("stage0", "full"):
        print(__doc__)
        return 2
    bundle = RL.DATA / "research" / f"mnq_scalp_pilot_{RL.utcnow_compact()}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"Bundle dir: {bundle}\n")
    if argv[1] == "stage0":
        stage0(bundle)
    else:
        full(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
