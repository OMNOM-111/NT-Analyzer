"""Write the MNQ Micro ORB RR150 follow-up profile card.

This profile is intentionally research_baseline, not paper_ready. The base
RR150 run has attractive income and PF, but target stress shows the edge is
too sensitive to one extra tick of slippage for current online use.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[3]
PROFILES_PATH = ROOT / "data" / "profiles" / "strategies.json"
FOLLOWUP = ROOT / "data" / "research" / "mnq_microorb_followup_20260507_0428"
TARGET_STRESS = ROOT / "data" / "research" / "mnq_microorb_targetstress_20260507_0548"
PILOT_ID = "b1_shortonly_mnq_5m_high_slip1_paper_v2"
PROFILE_ID = "mnq_micro_orb_open_rr150_1m_research_v2"


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def row(rows: Iterable[Dict[str, str]], module: str, period: str) -> Optional[Dict[str, str]]:
    for item in rows:
        if item.get("instrument") == "MNQ" and item.get("module") == module and item.get("period_label") == period:
            return item
    return None


def metric(r: Optional[Dict[str, str]]) -> Dict[str, Any]:
    if not r:
        return {}
    return {
        "trades": int(float(r["trades"])),
        "trades_per_day": float(r["trades_per_day"]),
        "active_days_pct": float(r["active_days_pct"]),
        "adj_net": float(r["adj_net"]),
        "adj_pf": float(r["adj_pf"]),
        "oos_adj_pf": float(r["oos_adj_pf"]),
        "win_rate": float(r["win_rate"]),
        "avg_trade_after_commission": float(r["avg_trade_after_commission"]),
        "max_drawdown": float(r["max_drawdown"]),
        "max_consecutive_losses": int(float(r["max_consecutive_losses"])),
        "daily_stop_hits": int(float(r["daily_stop_hits"])),
        "daily_stop_hit_pct": float(r["daily_stop_hit_pct"]),
        "same_bar_pct": float(r["same_bar_pct"]),
        "ambiguous_wins_pct": float(r["ambiguous_wins_pct"]),
        "confidence_score": int(float(r["confidence_score"])),
        "decision": r.get("decision") or "",
        "contracts": r["contracts"],
        "job_id": r["job_id"],
    }


def load_params() -> Dict[str, Any]:
    manifest = json.loads((FOLLOWUP / "followup_manifest.json").read_text(encoding="utf-8"))
    for item in manifest.get("submitted", []):
        if item.get("name") == "mnq_microorb_followup_MICRO_ORB_RR150_Full":
            return item.get("params") or {}
    raise RuntimeError("RR150 Full params not found in followup manifest")


def main() -> int:
    doc = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    pilot_before = next((p for p in doc["profiles"] if p.get("profile_id") == PILOT_ID), None)
    pilot_hash_before = hashlib.sha256(json.dumps(pilot_before, sort_keys=True).encode()).hexdigest()

    follow_rows = read_csv(FOLLOWUP / "mnq_scalp_results.csv")
    stress_rows = read_csv(TARGET_STRESS / "mnq_scalp_results.csv")

    full = metric(row(follow_rows, "MICRO_ORB_RR150", "Full"))
    is_ = metric(row(follow_rows, "MICRO_ORB_RR150", "IS"))
    oos = metric(row(follow_rows, "MICRO_ORB_RR150", "OOS"))
    fwd = metric(row(follow_rows, "MICRO_ORB_RR150", "FWD_2026_SMOKE"))
    rr175_full = metric(row(follow_rows, "MICRO_ORB_RR175", "Full"))

    fee240 = metric(row(stress_rows, "RR150_FEE240", "Full"))
    slip2 = metric(row(stress_rows, "RR150_SLIP2", "Full"))
    slip2_fee240 = metric(row(stress_rows, "RR150_SLIP2_FEE240", "Full"))
    risk050_slip2 = metric(row(stress_rows, "RR150_RISK050_SLIP2", "Full"))
    rr175_risk050_slip2 = metric(row(stress_rows, "RR175_RISK050_SLIP2", "Full"))

    if not (full and is_ and oos and fee240 and slip2 and risk050_slip2):
        raise RuntimeError("missing required RR150 metrics")

    params = load_params()
    params.update({
        "_profile_variant": "MNQ Micro ORB Open Scalp RR150",
        "_module_only": "EnableMicroOrb=true; EnableVwapReclaim=false; EnableEmaMomentum=false; EnableFailedBreakout=false",
        "_research_decision": "research_baseline_not_paper_ready",
    })

    hard_gates = {
        "trades_per_day_10_to_20": 10.0 <= full["trades_per_day"] <= 20.0,
        "adj_pf_ge_1_35": full["adj_pf"] >= 1.35,
        "oos_adj_pf_ge_1_25": oos["adj_pf"] >= 1.25,
        "win_rate_ge_52": full["win_rate"] >= 52.0,
        "avg_trade_ge_1_50": full["avg_trade_after_commission"] >= 1.50,
        "abs_max_dd_le_300": abs(full["max_drawdown"]) <= 300.0,
        "max_losing_streak_le_5": full["max_consecutive_losses"] <= 5,
        "daily_stop_hits_le_5_pct_days": full["daily_stop_hit_pct"] <= 5.0,
    }
    stress_gates = {
        "fee_2_40_full_positive": fee240["adj_net"] > 0 and fee240["adj_pf"] > 1.0,
        "slip_2_full_positive": slip2["adj_net"] > 0 and slip2["adj_pf"] > 1.0,
        "slip_2_fee_2_40_has_trades": slip2_fee240["trades"] > 0,
        "risk_0_50_slip_2_pf_ge_1_25": risk050_slip2["adj_pf"] >= 1.25,
    }

    profile: Dict[str, Any] = {
        "profile_id": PROFILE_ID,
        "name": "MNQ Micro ORB Open Scalp RR150 - research baseline",
        "strategy_class": "NTAMicroMnqScalpPilot",
        "deploy_strategy_class": "NTAMnqMicroOrbOpenScalp",
        "runtime_strategy_classes": [
            "NTAMicroMnqScalpPilot",
            "NTAMnqMicroOrbOpenScalp",
        ],
        "runtime_strategy_id": "ntamnqmicroorbopenscalp",
        "instrument": "MNQ 06-26",
        "current_contract": "MNQ 06-26",
        "timeframe": "1 Minute",
        "trade_window_pt": "06:35-08:30 + 10:30-12:00",
        "setup_mode": "MICRO_ORB_RR150",
        "status": "research_baseline",
        "status_label": "Edge-first survivor; not paper-ready because slip=2 stress fails",
        "last_job_id": full["job_id"],
        "test_period": {
            "from_utc": "2024-01-01T00:00:00Z",
            "to_utc": "2025-12-31T23:59:59Z",
        },
        "locked_parameters": params,
        "execution": {
            "calculate": "OnBarClose",
            "order_fill_resolution": "High",
            "slippage_ticks": 1,
            "round_turn_commission": 1.90,
            "session_template": "CME US Index Futures RTH",
            "starting_capital": 2000.0,
            "user_max_contracts": 1,
        },
        "metrics": {
            "trade_count": full["trades"],
            "trades_per_day": full["trades_per_day"],
            "winning_pct": full["win_rate"],
            "net_profit_after_commission": full["adj_net"],
            "profit_factor_after_commission": full["adj_pf"],
            "oos_profit_factor_after_commission": oos["adj_pf"],
            "max_drawdown": full["max_drawdown"],
            "avg_trade_after_commission": full["avg_trade_after_commission"],
            "max_consecutive_losses": full["max_consecutive_losses"],
            "daily_stop_hit_pct": full["daily_stop_hit_pct"],
            "same_bar_pct": full["same_bar_pct"],
            "ambiguous_wins_pct": full["ambiguous_wins_pct"],
            "full_2024_2025": full,
            "is_2024": is_,
            "oos_2025": oos,
            "forward_2026_smoke": fwd,
            "rr175_comparison_full": rr175_full,
            "stress_fee_2_40_full": fee240,
            "stress_slip_2_full": slip2,
            "stress_slip_2_fee_2_40_full": slip2_fee240,
            "stress_risk_0_50_slip_2_full": risk050_slip2,
            "stress_rr175_risk_0_50_slip_2_full": rr175_risk050_slip2,
        },
        "acceptance_gates": {
            "hard_aggressive_scalp": hard_gates,
            "execution_stress": stress_gates,
        },
        "decision": {
            "verdict": "research_baseline",
            "primary_reason": (
                "RR150 is the best income/PF balance in the MNQ Micro ORB family, "
                "but one extra slippage tick makes Full negative at risk 0.35. "
                "Risk 0.50 restores trade count under slip=2 but not enough PF."
            ),
            "edge_first_summary": (
                "Base RR150 Full: +$694, PF 1.45, OOS PF 1.62, win 67.7%, DD -$94. "
                "Fee $2.40 stress survives: +$318.5, PF 1.26. "
                "Slip=2 stress fails: -$30.1, PF 0.92."
            ),
            "online_blockers": [
                "Do not mark paper_ready until slip=2 or live-forward evidence improves.",
                "Same-bar rate remains very high, so High Fill validation can still overstate fills.",
                "Use the separate named wrapper only as research/demo-disabled until stress improves.",
            ],
            "next_research": [
                "Split ORB continuation and ORB retest into separate research modes.",
                "Run RR150 with wider stop/target geometry that keeps slip=2 PF above 1.25.",
                "Run 2026 forward after code-level pending-order cancellation fix.",
            ],
        },
        "confidence_score": {
            "score": 55,
            "level": "medium_research_only",
            "label": "Strong base income, weak execution robustness",
        },
        "research_bundle": str(FOLLOWUP.relative_to(ROOT)).replace("\\", "/") + "/",
        "stress_bundle": str(TARGET_STRESS.relative_to(ROOT)).replace("\\", "/") + "/",
        "evidence_job_ids": [
            full["job_id"],
            is_["job_id"],
            oos["job_id"],
            fwd.get("job_id"),
            fee240["job_id"],
            slip2["job_id"],
            risk050_slip2["job_id"],
        ],
        "demo_plan": {
            "demo_eligible": False,
            "reason_blocked": "slip=2 stress is negative; paper/live would be premature",
            "unblock_condition": "High Fill, slip>=2, commission>=1.90 rerun with Full PF>=1.25 and OOS PF>=1.25",
        },
        "notes": (
            "This card keeps the profitable MNQ Micro ORB idea alive under an edge-first "
            "decision policy, but intentionally blocks online promotion. The old 10-20 "
            "trades/day aggressive gate is too rigid for this ORB module; the real blocker "
            "is execution sensitivity, not frequency alone."
        ),
    }

    doc["profiles"] = [p for p in doc["profiles"] if p.get("profile_id") != PROFILE_ID]
    doc["profiles"].append(profile)
    generated = doc.setdefault("generated_from", {})
    if isinstance(generated, dict):
        bundles = generated.setdefault("bundles", [])
        for bundle in ("mnq_microorb_followup_20260507_0428", "mnq_microorb_targetstress_20260507_0548"):
            if bundle not in bundles:
                bundles.append(bundle)

    PROFILES_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    pilot_after = next((p for p in doc["profiles"] if p.get("profile_id") == PILOT_ID), None)
    pilot_hash_after = hashlib.sha256(json.dumps(pilot_after, sort_keys=True).encode()).hexdigest()
    assert pilot_hash_before == pilot_hash_after, "locked B1 profile changed"

    print(f"wrote profile {PROFILE_ID}")
    print(f"locked B1 hash unchanged: {pilot_hash_after[:16]}")
    print(f"profiles: {len(doc['profiles'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
