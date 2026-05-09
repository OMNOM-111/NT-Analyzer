"""Append SessionEdge v2 profile cards to data/profiles/strategies.json.

Builds three new cards (paper_ready / paper_candidate / paper_candidate)
plus rejected summaries. Verifies pilot profile is preserved hash-stable.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "research" / "python"))
import research_lib as RL  # noqa: E402

BUNDLE = ROOT / "data" / "research" / "session_edge_v2_20260505_2208"
PROFILES_PATH = ROOT / "data" / "profiles" / "strategies.json"

PILOT_ID = "b1_shortonly_mnq_5m_high_slip1_paper_v2"


def card_for(name, instrument, mode, direction, status, status_label,
             metrics_full, metrics_is, metrics_oos, metrics_slip, metrics_fee,
             evidence_jobs, params, decision, notes, contract,
             confidence_score, data_quality):
    def _flat_metrics(block):
        if not block:
            return {}
        return {
            "trade_count": block.get("trade_count"),
            "winning_pct": block.get("winning_pct"),
            "net_profit_after_commission": block.get("adj_net"),
            "profit_factor_after_commission": block.get("adj_pf"),
            "max_drawdown": block.get("max_drawdown"),
            "round_turn_commission": block.get("round_turn_commission"),
        }

    def _confidence(value):
        if isinstance(value, dict):
            return value
        score = int(round(float(value) * 100)) if isinstance(value, (int, float)) and value <= 1 else int(value)
        if score >= 70:
            level = "high"
        elif score >= 50:
            level = "medium"
        elif score > 0:
            level = "low"
        else:
            level = "rejected"
        return {"score": score, "level": level}

    def _decision(value):
        if isinstance(value, dict):
            return value
        return {
            "verdict": str(value),
            "reason": notes,
        }

    metrics = _flat_metrics(metrics_full)
    metrics.update({
        "full_2024_2025": metrics_full,
        "is_2024": metrics_is,
        "oos_2025": metrics_oos,
        "stress_slip_plus1": metrics_slip,
        "stress_fee_x1_25": metrics_fee,
    })

    return {
        "profile_id": f"sev2_{instrument.split()[0].lower()}_{mode.lower()}_{direction}_paper_v1",
        "name": name,
        "strategy_class": "NTAMicroSessionEdgeExplorer",
        "instrument": instrument,
        "current_contract": contract,
        "timeframe": "5 Minute",
        "status": status,
        "status_label": status_label,
        "last_job_id": evidence_jobs[0] if evidence_jobs else None,
        "test_period": {"from_utc": "2024-01-01T00:00:00Z",
                        "to_utc": "2025-12-31T00:00:00Z"},
        "locked_parameters": params,
        "execution": {
            "session_template": params.get("_session_template"),
            "round_turn_commission": params.get("RoundTurnCommission", 1.9),
            "slippage_ticks": params.get("SlippageTicks", 1),
            "commission_assumption_note":
                "RoundTurnCommission is a NinjaTrader project-side fee model "
                "(not an external prop-firm schedule). Instrument universe comes from the local data/catalog/instrument_groups.json 'Micros' group."
        },
        "metrics": metrics,
        "confidence_score": _confidence(confidence_score),
        "decision": _decision(decision),
        "notes": notes,
        "data_quality": data_quality,
        "contract_roll_policy": "Front-month CME continuous; re-validate at each contract roll.",
        "demo_plan": {
            "demo_eligible": status == "paper_ready",
            "min_paper_days": 10,
            "instruments": [instrument],
            "halt_if_dd_exceeds_usd": 250.0,
        },
        "evidence_job_ids": evidence_jobs,
        "research_bundle": "data/research/session_edge_v2_20260505_2208/",
    }


def main():
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    existing_ids = {p.get("profile_id") for p in data.get("profiles", [])}

    pilot_before = next((p for p in data["profiles"]
                         if p.get("profile_id") == PILOT_ID), None)
    pilot_hash_before = hashlib.sha256(
        json.dumps(pilot_before, sort_keys=True).encode()).hexdigest()

    tests = json.loads((BUNDLE / "all_tests.json").read_text(encoding="utf-8"))["tests"]

    def find(needle_substr, name_filter=None):
        out = []
        for t in tests:
            n = (t.get("name") or "").lower()
            if needle_substr in n and (name_filter is None or name_filter(n)):
                out.append(t)
        return out

    def metrics_of(t):
        return {
            "trade_count": t["trade_count"],
            "winning_pct": t["winning_pct"],
            "adj_net": t["adj_net"],
            "adj_pf": t["adj_pf"],
            "max_drawdown": t["max_drawdown"],
            "round_turn_commission": t["round_turn_commission"],
        }

    # MGC short
    mgc_full = find("stagea_metals_vwappullback_shortonly")[0]
    mgc_b = find("stageb_mgc_current_vwappullback_shortonly")[0]
    mgc_d_is = find("stagea_metals_vwappullback_shortonly")  # placeholder; below replace
    mgc_is = next(t for t in tests if "stageD" in (t.get("manifest") or "")
                  and "mgc" in (t.get("name") or "").lower()
                  and "vwappullback" in (t.get("name") or "").lower()
                  and "shortonly" in (t.get("name") or "").lower()
                  and "_is" in (t.get("name") or "").lower())
    mgc_oos = next(t for t in tests if "stageD" in (t.get("manifest") or "")
                   and "mgc" in (t.get("name") or "").lower()
                   and "vwappullback" in (t.get("name") or "").lower()
                   and "shortonly" in (t.get("name") or "").lower()
                   and "_oos" in (t.get("name") or "").lower())
    mgc_slip = next(t for t in tests if "stageD" in (t.get("manifest") or "")
                    and "mgc" in (t.get("name") or "").lower()
                    and "vwappullback" in (t.get("name") or "").lower()
                    and "shortonly" in (t.get("name") or "").lower()
                    and "slip2" in (t.get("name") or "").lower())
    mgc_fee = next(t for t in tests if "stageD" in (t.get("manifest") or "")
                   and "mgc" in (t.get("name") or "").lower()
                   and "vwappullback" in (t.get("name") or "").lower()
                   and "shortonly" in (t.get("name") or "").lower()
                   and "fee125" in (t.get("name") or "").lower())

    mgc_params = {**mgc_full["parameters"],
                  "_session_template": mgc_full["session_template"]}
    mgc_card = card_for(
        name="VWAP Pullback MGC 5m v1",
        instrument=mgc_b["instrument"],
        mode="VwapPullback", direction="shortonly",
        status="paper_ready",
        status_label="Готов к paper",
        metrics_full=metrics_of(mgc_full),
        metrics_is=metrics_of(mgc_is),
        metrics_oos=metrics_of(mgc_oos),
        metrics_slip=metrics_of(mgc_slip),
        metrics_fee=metrics_of(mgc_fee),
        evidence_jobs=[mgc_full["job_id"], mgc_b["job_id"], mgc_is["job_id"],
                       mgc_oos["job_id"], mgc_slip["job_id"], mgc_fee["job_id"]],
        params=mgc_params,
        decision="paper_ready",
        notes=("Edge consistent on current contract MGC 06-26 (Stage B = "
               "57 trades, +$992, PF 1.82). Survives slip+1 (PF 1.42) and "
               "fee×1.25 (PF 1.68). IS/OOS each ~30 trades, both positive."),
        contract=mgc_b["instrument"],
        confidence_score=0.78,
        data_quality="good",
    )

    # MNG short — explicitly select MNG instrument from stageA energy_VwapPullback_shortonly
    mng_full = next(t for t in tests
                    if "stagea_energy_vwappullback_shortonly" in (t.get("name") or "").lower()
                    and "mng" in (t.get("instrument") or "").lower())
    mng_is = next(t for t in tests if "stageD" in (t.get("manifest") or "")
                  and "mng" in (t.get("name") or "").lower()
                  and "vwappullback" in (t.get("name") or "").lower()
                  and "shortonly" in (t.get("name") or "").lower()
                  and "_is" in (t.get("name") or "").lower())
    mng_oos = next(t for t in tests if "stageD" in (t.get("manifest") or "")
                   and "mng" in (t.get("name") or "").lower()
                   and "vwappullback" in (t.get("name") or "").lower()
                   and "shortonly" in (t.get("name") or "").lower()
                   and "_oos" in (t.get("name") or "").lower())
    mng_slip = next(t for t in tests if "stageD" in (t.get("manifest") or "")
                    and "mng" in (t.get("name") or "").lower()
                    and "vwappullback" in (t.get("name") or "").lower()
                    and "shortonly" in (t.get("name") or "").lower()
                    and "slip2" in (t.get("name") or "").lower())
    mng_fee = next(t for t in tests if "stageD" in (t.get("manifest") or "")
                   and "mng" in (t.get("name") or "").lower()
                   and "vwappullback" in (t.get("name") or "").lower()
                   and "shortonly" in (t.get("name") or "").lower()
                   and "fee125" in (t.get("name") or "").lower())
    mng_params = {**mng_full["parameters"],
                  "_session_template": mng_full["session_template"]}
    mng_card = card_for(
        name="SessionEdge v2 MNG ShortOnly VwapPullback (paper_candidate)",
        instrument=mng_full["instrument"],
        mode="VwapPullback", direction="shortonly",
        status="paper_candidate",
        status_label="Кандидат — slip×PF на пороге",
        metrics_full=metrics_of(mng_full),
        metrics_is=metrics_of(mng_is),
        metrics_oos=metrics_of(mng_oos),
        metrics_slip=metrics_of(mng_slip),
        metrics_fee=metrics_of(mng_fee),
        evidence_jobs=[mng_full["job_id"], mng_is["job_id"], mng_oos["job_id"],
                       mng_slip["job_id"], mng_fee["job_id"]],
        params=mng_params,
        decision="paper_candidate",
        notes=("Edge present (Full 42 trades, +$162, PF 1.23, current contract). "
               "Slippage stress reduces PF to 1.12; fee stress 1.20. "
               "Needs forward proof before promotion to paper_ready."),
        contract=mng_full["instrument"],
        confidence_score=0.55,
        data_quality="acceptable",
    )

    # MBT crypto smoke (1mo only)
    mbt = next((t for t in tests if (t.get("manifest") == "stage0_smoke_manifest.json")
                and "mbt" in (t.get("instrument") or "").lower()
                and "rollingvwapcrypto" in (t.get("name") or "").lower()), None)
    cards_new = [mgc_card, mng_card]
    if mbt:
        mbt_card = card_for(
            name="SessionEdge v2 MBT RollingVwapCrypto (smoke-only)",
            instrument=mbt["instrument"],
            mode="RollingVwapCrypto", direction="longshort",
            status="paper_candidate",
            status_label="Только smoke (Q4 2025) — нужен полный прогон",
            metrics_full=metrics_of(mbt),
            metrics_is=None, metrics_oos=None,
            metrics_slip=None, metrics_fee=None,
            evidence_jobs=[mbt["job_id"]],
            params={**mbt["parameters"], "_session_template": mbt["session_template"]},
            decision="paper_candidate",
            notes=("Only 1-month smoke window: 59 trades, +$217, PF 1.26. "
                   "Crypto is the only family where RollingVwapCrypto produced "
                   "meaningful trades. Re-run on full 2024-2025 in next bundle."),
            contract=mbt["instrument"],
            confidence_score=0.35,
            data_quality="smoke_only",
        )
        cards_new.append(mbt_card)

    # Rejected summary card per family
    rejected_summary = {
        "profile_id": "sev2_rejected_summary_v1",
        "name": "SessionEdge v2 — rejected modes/families summary",
        "strategy_class": "NTAMicroSessionEdgeExplorer",
        "status": "rejected",
        "status_label": "Отклонено",
        "research_bundle": "data/research/session_edge_v2_20260505_2208/",
        "rejected_breakdown": {
            "index_micros (MES, MYM, M2K)":
                "All SetupModes (VwapPullback, OrbContinuation, FailedOrbReversal, "
                "CompressionBreakout) yielded PF<1.0 across 2024-2025. "
                "Best single None-direction smoke: MYM Compression PF 1.07 / 10 trades — "
                "не дотягивает до minimum.",
            "fx (M6A, M6B, M6E)":
                "VwapPullback и VwapMeanReversion дали высокий trade count, но PF 0.3–0.85; "
                "current edge не прослеживается. Нужен другой setup (London/NY overlap, "
                "ADX-режим) — отдельная гипотеза для следующего bundle.",
            "metals MHG (если был)":
                "VwapPullback longonly 32 trades, PF 1.006 — кандидат с очень слабым edge.",
            "energy MCL":
                "VwapPullback и Compression: small smoke positives but full-window negative.",
        },
        "notes": ("MNQ исключён из нового исследования (locked Pilot). "
                  "local micro group — только список инструментов; commission/margin = "
                  "NinjaTrader project assumption."),
    }
    cards_new.append(rejected_summary)

    # Append (replace if id collision)
    new_profiles = []
    new_ids = {c["profile_id"] for c in cards_new}
    for p in data["profiles"]:
        if p.get("profile_id") in new_ids:
            continue
        new_profiles.append(p)
    new_profiles.extend(cards_new)
    data["profiles"] = new_profiles
    gf = data.get("generated_from")
    if isinstance(gf, dict):
        gf.setdefault("bundles", []).append("session_edge_v2_20260505_2208")
    else:
        data["generated_from"] = (gf or "") + " + session_edge_v2_20260505_2208"

    PROFILES_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Verify Pilot integrity
    pilot_after = next((p for p in data["profiles"]
                        if p.get("profile_id") == PILOT_ID), None)
    pilot_hash_after = hashlib.sha256(
        json.dumps(pilot_after, sort_keys=True).encode()).hexdigest()
    assert pilot_hash_before == pilot_hash_after, "PILOT PROFILE MUTATED!"
    print(f"Pilot profile hash unchanged: {pilot_hash_after}")
    print(f"Added {len(cards_new)} cards: " +
          ", ".join(c["profile_id"] for c in cards_new))
    print(f"Total profiles now: {len(data['profiles'])}")


if __name__ == "__main__":
    main()
