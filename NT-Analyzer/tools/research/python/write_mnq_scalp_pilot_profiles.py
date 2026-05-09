"""Append NTAMicroMnqScalpPilot profile cards to data/profiles/strategies.json.

Builds:
  - mnqscalp_microorb_mnq_1m_research_v1   (MICRO_ORB on MNQ — only positive Full row)
  - mnqscalp_rejected_summary_v1           (other modules / instruments — REJECT evidence)

Uses honest single-canonical-contract aggregation (latest expiry per period)
from bundle data/research/mnq_scalp_pilot_20260507_0023/. Verifies locked B1
pilot profile is preserved hash-stable.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent.parent.parent
PROFILES_PATH = ROOT / "data" / "profiles" / "strategies.json"
BUNDLE = ROOT / "data" / "research" / "mnq_scalp_pilot_20260507_0023"
HONEST_CSV = BUNDLE / "mnq_scalp_results_HONEST.csv"

PILOT_ID = "b1_shortonly_mnq_5m_high_slip1_paper_v2"
CURRENT_FRONT_MNQ = "MNQ 06-26"   # active front-month as of 2026-05-06


def load_honest_rows() -> List[Dict[str, Any]]:
    with HONEST_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_row(rows: List[Dict[str, Any]], instrument: str, module: str,
             period_label: str) -> Optional[Dict[str, Any]]:
    for r in rows:
        if (r["instrument"] == instrument and r["module"] == module
                and r["period_label"] == period_label):
            return r
    return None


def row_to_metrics(r: Dict[str, Any]) -> Dict[str, Any]:
    if not r:
        return {}
    return {
        "trade_count": int(r["trades"]),
        "trades_per_day": float(r["trades_per_day"]),
        "winning_pct": float(r["win_rate"]),
        "net_profit_after_commission": float(r["adj_net"]),
        "profit_factor_after_commission": float(r["adj_pf"]),
        "max_drawdown": float(r["max_drawdown"]),
        "avg_trade_after_commission": float(r["avg_trade_after_commission"]),
        "max_consecutive_losses": int(r["max_consecutive_losses"]),
        "daily_stop_hit_pct": float(r["daily_stop_hit_pct"]),
        "same_bar_pct": float(r["same_bar_pct"]),
        "round_turn_commission": float(r["round_turn_commission"]),
        "canonical_contract": r["canonical_contract"],
        "from_utc": r["from_utc"],
        "to_utc": r["to_utc"],
        "evidence_job_id": r["job_id"],
    }


def quarter_metrics(rows: List[Dict[str, Any]], instrument: str, module: str) -> Dict[str, Any]:
    out = {}
    for r in rows:
        if (r["instrument"] == instrument and r["module"] == module
                and r["period_label"].startswith("Q")):
            out[r["period_label"]] = {
                "trades": int(r["trades"]),
                "adj_net": float(r["adj_net"]),
                "adj_pf": float(r["adj_pf"]),
                "win": float(r["win_rate"]),
                "mdd": float(r["max_drawdown"]),
            }
    positive = sum(1 for q in out.values() if q["adj_net"] > 0)
    out["_positive_quarters"] = f"{positive}/{len(out)}"
    return out


def load_locked_params(bundle: Path) -> Dict[str, Any]:
    """Pull canonical strategy params from the manifest's MICRO_ORB Full submission."""
    manifest = json.loads((bundle / "full_manifest.json").read_text(encoding="utf-8"))
    for s in manifest.get("submitted") or []:
        if s.get("name") == "mnq_scalp_MNQ_MICRO_ORB_Full":
            return s.get("params") or {}
    return {}


def main() -> int:
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))

    pilot_before = next((p for p in data["profiles"]
                         if p.get("profile_id") == PILOT_ID), None)
    pilot_hash_before = hashlib.sha256(
        json.dumps(pilot_before, sort_keys=True).encode()).hexdigest()

    rows = load_honest_rows()
    full = find_row(rows, "MNQ", "MICRO_ORB", "Full")
    is_ = find_row(rows, "MNQ", "MICRO_ORB", "IS")
    oos = find_row(rows, "MNQ", "MICRO_ORB", "OOS")
    if not (full and is_ and oos):
        print("ERROR: missing canonical MNQ MICRO_ORB rows in honest CSV", file=sys.stderr)
        return 1

    locked_params = load_locked_params(BUNDLE)
    quarters = quarter_metrics(rows, "MNQ", "MICRO_ORB")

    # Acceptance gate audit
    full_m = row_to_metrics(full)
    oos_m = row_to_metrics(oos)
    is_m = row_to_metrics(is_)
    gates = {
        "trades_per_day_10_to_20": 10.0 <= full_m["trades_per_day"] <= 20.0,
        "adj_pf_ge_1_35": full_m["profit_factor_after_commission"] >= 1.35,
        "oos_adj_pf_ge_1_25": oos_m["profit_factor_after_commission"] >= 1.25,
        "win_pct_ge_52": full_m["winning_pct"] >= 52.0,
        "avg_trade_ge_1_50": full_m["avg_trade_after_commission"] >= 1.50,
        "abs_max_dd_le_300": abs(full_m["max_drawdown"]) <= 300.0,
        "max_consec_losses_le_5": full_m["max_consecutive_losses"] <= 5,
        "daily_stop_pct_le_5": full_m["daily_stop_hit_pct"] <= 5.0,
    }
    passed = sum(1 for v in gates.values() if v)
    confidence_pct = int(round(passed / len(gates) * 100))   # = 5/8 = 63

    notes = (
        "MNQ × MICRO_ORB — единственный положительный Full в bundle "
        "mnq_scalp_pilot_20260507_0023 (canonical-contract aggregation, "
        "MNQ 03-26 — latest expiry в окне). "
        "Full: 600 trades, +$443, PF 1.37, win 74%, MDD -$103. "
        "OOS 2025: 296 trades, +$316, PF 1.63, win 78%. "
        f"Quarterly: {quarters['_positive_quarters']} positive (Q2_2024 -$41, "
        "Q3_2025 -$27 — мягкие просадки). "
        f"Gates passed: {passed}/8. "
        "FAIL: trades_per_day=1.15 (gate 10-20), avg/trade=$0.74 (gate ≥$1.50), "
        "max_consec_losses=6 (gate ≤5). "
        "Edge подтверждён, но MICRO_ORB по своей природе sparse — не high-freq скальпер. "
        "Стратегия логически привязана к индексным RTH-фьючерсам (06:30 PT opening); "
        "на MES — 0 trades (MinStopTicks×$1.25 > RiskPerTradePct×StartingCapital), "
        "на MYM/M2K — отрицательный Full. Best instrument = MNQ. "
        "Other modules (VWAP_RECLAIM/EMA_MOMENTUM/FAILED_BREAKOUT) на Full — отрицательные."
    )

    research_card: Dict[str, Any] = {
        "profile_id": "mnqscalp_microorb_mnq_1m_research_v1",
        "name": "MNQ Micro Scalp — MICRO_ORB only (research baseline)",
        "strategy_class": "NTAMicroMnqScalpPilot",
        "instrument": "MNQ",
        "current_contract": CURRENT_FRONT_MNQ,
        "timeframe": "1 Minute",
        "trade_window_pt": "06:35-08:30 + 10:30-12:00 PT (MaxTradesPerDay=20)",
        "status": "research_baseline",
        "status_label": "Положительный edge, sparse — не дотягивает до paper по trades/day",
        "last_job_id": full_m["evidence_job_id"],
        "test_period": {
            "from_utc": full_m["from_utc"],
            "to_utc": full_m["to_utc"],
        },
        "locked_parameters": {
            **locked_params,
            "_module_only": "MICRO_ORB (EnableVwapReclaim=false, EnableEmaMomentum=false, "
                            "EnableMicroOrb=true, EnableFailedBreakout=false)",
        },
        "execution": {
            "calculate": "OnBarClose",
            "order_fill_resolution": "High",
            "slippage_ticks": 1,
            "round_turn_commission": 1.90,
            "session_template": "CME US Index Futures RTH",
            "starting_capital": 2000.0,
            "commission_assumption_note":
                "RoundTurnCommission $1.90 — NinjaTrader project-side fee model "
                "(не внешний prop schedule). Slip=1 tick, fill=High — same convention "
                "as locked B1 paper_ready.",
        },
        "metrics": {
            "trade_count": full_m["trade_count"],
            "winning_pct": full_m["winning_pct"],
            "net_profit_after_commission": full_m["net_profit_after_commission"],
            "profit_factor_after_commission": full_m["profit_factor_after_commission"],
            "max_drawdown": full_m["max_drawdown"],
            "avg_trade_after_commission": full_m["avg_trade_after_commission"],
            "trades_per_day": full_m["trades_per_day"],
            "max_consecutive_losses": full_m["max_consecutive_losses"],
            "daily_stop_hit_pct": full_m["daily_stop_hit_pct"],
            "same_bar_pct": full_m["same_bar_pct"],
            "round_turn_commission": full_m["round_turn_commission"],
            "full_2024_2025": full_m,
            "is_2024": is_m,
            "oos_2025": oos_m,
            "quarterly_2024_2025": quarters,
            "stress_slip_plus1": None,
            "stress_fee_x1_25": None,
        },
        "acceptance_gates": {
            "passed_count": f"{passed}/{len(gates)}",
            "results": gates,
        },
        "confidence_score": {
            "score": confidence_pct,
            "level": "medium" if confidence_pct >= 50 else ("low" if confidence_pct > 0 else "rejected"),
            "label": "Edge подтверждён, sparse сигнал — не паперный скальпер по дефиниции",
        },
        "decision": {
            "verdict": "research_baseline",
            "reason": "Positive valid edge on canonical contract, but trades/day & avg/trade "
                      "below paper-ready scalper gates. Promote to paper_candidate only after "
                      "neighbor-param sweep (OrbDurationMinutes 5/10, RR 1.1/1.5) raises trade "
                      "frequency or after stress-test pack (slip=2, fee×1.25) confirms robustness.",
            "weaknesses": [
                "trades_per_day=1.15 (gate 10-20) — sparse, не классический intraday scalper",
                "avg_trade_after_commission=$0.74 (gate ≥$1.50) — низкая edge per trade",
                "max_consecutive_losses=6 (gate ≤5) — на грани",
                "same_bar_pct ≈ 96-98% — High fill resolution artefact, как и B1",
                "stress_slip_plus1 / stress_fee_x1_25 — не запущены",
                "MNQ × ALL Full — аномалия (стратегия зависает в Jan 2024, продолжает только в OOS); требует диагностики риск-менеджмента",
            ],
            "next_test": [
                "Stress: SlippageTicks=2 на тех же 220 сабмишнах",
                "Stress: RoundTurnCommission=2.375 ($1.90 × 1.25)",
                "Neighbor params sweep: OrbDurationMinutes ∈ {5,10}, RewardRiskRatio ∈ {1.10,1.50}",
                "Rerun MNQ × ALL Full с диагностикой (почему стопает после Jan 2024)",
                "Forward verification на MNQ 06-26 (2026 YTD, ~2 месяца)",
            ],
        },
        "notes": notes,
        "data_quality": "good — canonical-contract aggregation, sverka raw result.json пройдена",
        "contract_roll_policy": "Front-month CME continuous; canonical research contract = MNQ 03-26 "
                                "(window 2024-2025); current production = MNQ 06-26.",
        "demo_plan": {
            "demo_eligible": False,
            "min_paper_days": 0,
            "instruments": ["MNQ"],
            "halt_if_dd_exceeds_usd": 200.0,
            "promotion_blocker": "Below paper-ready gates on trades_per_day & avg_trade_after_commission",
        },
        "evidence_job_ids": [
            full_m["evidence_job_id"], is_m["evidence_job_id"], oos_m["evidence_job_id"],
        ],
        "research_bundle": "data/research/mnq_scalp_pilot_20260507_0023/",
    }

    # Rejected summary card — per-module evidence
    rejected_breakdown = {}
    for module in ["VWAP_RECLAIM", "EMA_MOMENTUM", "FAILED_BREAKOUT", "ALL"]:
        r = find_row(rows, "MNQ", module, "Full")
        if r:
            rejected_breakdown[f"MNQ × {module} (Full)"] = (
                f"trades={r['trades']}, adj_net=${r['adj_net']}, PF={r['adj_pf']}, "
                f"MDD=${r['max_drawdown']} — отрицательный Full"
                + (" (АНОМАЛИЯ: стопает после Jan 2024)" if module == "ALL" else "")
            )
    rejected_breakdown["MES × all modules"] = (
        "0 trades по всем модулям. Root cause: MinStopTicks=8 × tick_value=$1.25 = $10 "
        "> RiskPerTradePct=0.35% × StartingCapital=$2000 = $7. Position sizing отвергает "
        "каждое entry. Чтобы включить MES — нужен MES-aware MinStopTicks или другая sizing."
    )
    rejected_breakdown["MYM × all modules"] = (
        "Все модули отрицательные на Full. Best (MICRO_ORB): -$173 / 94 trades / PF 0.43."
    )
    rejected_breakdown["M2K × all modules"] = (
        "Все модули отрицательные на Full. Best (ALL): -$174 / 204 trades / PF 0.67."
    )

    rejected_card: Dict[str, Any] = {
        "profile_id": "mnqscalp_rejected_summary_v1",
        "name": "NTAMicroMnqScalpPilot — rejected modules/instruments summary",
        "strategy_class": "NTAMicroMnqScalpPilot",
        "status": "rejected",
        "status_label": "Отклонено (4 модуля × 3 инструмента)",
        "research_bundle": "data/research/mnq_scalp_pilot_20260507_0023/",
        "rejected_breakdown": rejected_breakdown,
        "notes": (
            "Bundle 20260507_0023: 220 сабмишнов (4 инструмента × 5 модулей × 11 периодов). "
            "После канонического агрегирования (latest expiry per period) только MNQ × MICRO_ORB "
            "Full положительный. Все остальные комбинации либо отрицательны, либо имеют 0 trades. "
            "ChatGPT исходно интерпретировал inflated CSV (overlapping контракты), что давало "
            "ложно-положительные OOS для MNQ × ALL/EMA/FAILED. Real OOS PF: 1.29/1.10/1.19 — "
            "выше 1.0 но Full все равно отрицательный."
        ),
        "data_quality": "good — diagnosed and isolated against aggregator bug",
    }

    cards_new: List[Dict[str, Any]] = [research_card, rejected_card]
    new_ids = {c["profile_id"] for c in cards_new}
    new_profiles = [p for p in data["profiles"] if p.get("profile_id") not in new_ids]
    new_profiles.extend(cards_new)
    data["profiles"] = new_profiles

    gf = data.get("generated_from")
    if isinstance(gf, dict):
        gf.setdefault("bundles", []).append("mnq_scalp_pilot_20260507_0023")

    PROFILES_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    pilot_after = next((p for p in data["profiles"]
                        if p.get("profile_id") == PILOT_ID), None)
    pilot_hash_after = hashlib.sha256(
        json.dumps(pilot_after, sort_keys=True).encode()).hexdigest()
    assert pilot_hash_before == pilot_hash_after, "PILOT PROFILE MUTATED!"
    print(f"Pilot B1 hash unchanged: {pilot_hash_after[:16]}…")
    print(f"Added {len(cards_new)} cards: " + ", ".join(c["profile_id"] for c in cards_new))
    print(f"Total profiles now: {len(data['profiles'])}")
    print(f"Confidence on research card: {confidence_pct} (gates {passed}/{len(gates)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
