"""Search MNQ CELL-019 overnight / early-morning candidates.

The Strategies day planner currently leaves MNQ 15:00-06:35 PT empty.  This
runner targets the non-overlapping overnight part of that gap and forces all
profiles flat before the existing MGC 06:00 PT and MNQ 06:35 PT portfolios
begin trading.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import run_mnq_cell019_evening_session as EVENING  # noqa: E402


EVENING.DISPLAY_NAME = "Scalping Overnight MNQ 1m v1 c019"


def build_variants(limit: Optional[int] = None) -> List[EVENING.Variant]:
    windows = [
        (300, 555, 559, 300),
        (400, 555, 559, 400),
        (330, 555, 559, 330),
        (200, 500, 505, 200),
        (100, 400, 405, 100),
        (30, 300, 305, 30),
    ]
    specs: Dict[str, Dict[str, Any]] = {
        "all": {
            "directions": ["both", "short", "long"],
            "rrs": [3.0, 4.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.5, 0.7],
        },
        "vwap": {
            "directions": ["both", "long", "short"],
            "rrs": [2.0, 2.5, 3.0],
            "stops": [(4, 10), (6, 14)],
            "volumes": [0.5, 0.7],
        },
        "ema": {
            "directions": ["both", "long", "short"],
            "rrs": [2.0, 3.0, 4.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.7],
        },
        "orb_retest": {
            "directions": ["both", "short", "long"],
            "rrs": [1.75, 2.5],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.7],
        },
        "fail": {
            "directions": ["both", "short", "long"],
            "rrs": [1.25, 1.5, 2.0],
            "stops": [(4, 10), (6, 12)],
            "volumes": [0.0, 0.7],
        },
    }
    variants: List[EVENING.Variant] = []
    for start, end, flat, orb_start in windows:
        window_label = f"{start:04d}_{end:04d}"
        for module, spec in specs.items():
            for direction in spec["directions"]:
                for rr in spec["rrs"]:
                    for min_stop, max_stop in spec["stops"]:
                        for vol in spec["volumes"]:
                            params = EVENING.base_params()
                            params.update(EVENING.module_params(module, direction))
                            params.update({
                                "TradeStartTime": start,
                                "TradeEndTime": end,
                                "ForceFlatTime": flat,
                                "OrbStartTime": orb_start,
                                "RewardRiskRatio": rr,
                                "MinStopTicks": min_stop,
                                "MaxStopTicks": max_stop,
                                "MinVolumeFactor": vol,
                                "PullbackLookback": 4 if module in {"vwap", "ema"} else 3,
                            })
                            if module == "fail":
                                params["OrbFailedLookback"] = 4
                                params["TimeStopBars"] = 4
                                params["MinProgressR"] = 0.20
                            rr_label = str(rr).replace(".", "")
                            vol_label = str(vol).replace(".", "")
                            name = (
                                f"{module}_{direction}_{window_label}_"
                                f"s{min_stop}_{max_stop}_rr{rr_label}_v{vol_label}"
                            )
                            variants.append(EVENING.Variant(
                                name=name,
                                params=params,
                                window=f"{start:04d}-{end:04d}",
                                module=module,
                                direction=direction,
                                rr=rr,
                                min_stop=min_stop,
                                max_stop=max_stop,
                                min_volume=vol,
                                setup_mode=str(params.get("SetupMode") or "AllModules"),
                                orb_start=orb_start,
                            ))
                            if limit and len(variants) >= limit:
                                return variants
    return variants


EVENING.build_variants = build_variants


if __name__ == "__main__":
    raise SystemExit(EVENING.main())
