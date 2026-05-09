"""Submit Session-Edge v2 jobs for NTAMicroSessionEdgeExplorer.

Usage:
  python submit_session_edge_v2.py stage0      # smoke: 1 job per (family, mode)
  python submit_session_edge_v2.py stageA      # broad scan: family x mode x direction
  python submit_session_edge_v2.py stageB-mgc  # MGC current-contract validation
  python submit_session_edge_v2.py stageD <bundle_dir>  # IS/OOS/stress for survivors

stageD reads `accepted_profiles.json` + `paper_candidates.json` from the bundle
directory passed as the second arg and runs IS/OOS/slip+1/fee*1.25 per candidate.

All bundles write a manifest under data/research/session_edge_v2_<ts>/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL          # noqa: E402
import session_edge_v2_lib as SE   # noqa: E402

CLASS_NAME = "NTAMicroSessionEdgeExplorer"

FROM_FULL = "2024-01-01T00:00:00Z"
TO_FULL   = "2025-12-31T23:59:59Z"
FROM_IS   = "2024-01-01T00:00:00Z"
TO_IS     = "2024-12-31T23:59:59Z"
FROM_OOS  = "2025-01-01T00:00:00Z"
TO_OOS    = "2025-12-31T23:59:59Z"

# Smoke window — 1 month, fast.
FROM_SMOKE = "2025-10-01T00:00:00Z"
TO_SMOKE   = "2025-10-31T23:59:59Z"


# --------------------------------------------------------------------------
def _resolve_family_contracts(roots: List[str]) -> List[str]:
    out = []
    for r in roots:
        c = RL.resolve_front_contract(r)
        if "skip_reason" not in c:
            out.append(c["instrument"])
    return out


def _submit(name: str, instruments: List[str], params: Dict[str, Any],
            from_utc: str, to_utc: str, slippage_ticks: int = 1,
            session_template: str = None, role: str = "smoke") -> Dict[str, Any]:
    # role='smoke' bypasses the supported=True gate for non-Index templates;
    # bridge only auto-supports "CME US Index Futures RTH" and resets the rest
    # on every catalog refresh. role does not affect metrics, only validation.
    res = RL.submit_batch(
        name=name, class_name=CLASS_NAME,
        instruments=instruments, params=params,
        from_utc=from_utc, to_utc=to_utc,
        bars_period_type="Minute", bars_period_value=5,
        slippage_ticks=slippage_ticks, role=role,
        session_template=session_template,
    )
    ok = res["code"] == 201
    bid = res["response"].get("batch_id") if ok else None
    print(f"  [{name:60s}] code={res['code']} batch={bid or res['response']}")
    return {"name": name, "instruments": instruments,
            "session_template": session_template,
            "params": params, "code": res["code"],
            "batch_id": bid, "response": res["response"]}


# --------------------------------------------------------------------------
def stage0_smoke(out_dir: Path) -> Dict[str, Any]:
    """One batch per (family, mode). 1-month window. Just confirms compile +
    catalog registration + each SetupMode initializes."""
    submitted, skipped = [], []
    for label, roots, t0, t1, tflat, modes in SE.FAMILIES:
        contracts = _resolve_family_contracts(roots)
        if not contracts:
            skipped.append({"family": label, "reason": "no contracts"})
            continue
        worst_root = max(roots, key=RL.margin_for)
        for mode in modes:
            params = SE.setup_mode_defaults(mode, worst_root)
            params.update(RL.base_risk_params(worst_root))
            params["SetupMode"] = mode  # restore after base_risk_params overwrite
            params.update({
                "EnableLong": True, "EnableShort": True,
                "TradeStartTime": t0, "TradeEndTime": t1, "ForceFlatTime": tflat,
            })
            r = _submit(
                name=f"sev2_smoke_{label}_{mode}",
                instruments=contracts, params=params,
                from_utc=FROM_SMOKE, to_utc=TO_SMOKE,
                session_template=SE.family_session(roots[0]),
            )
            r.update({"family": label, "mode": mode})
            submitted.append(r)
    p = out_dir / "stage0_smoke_manifest.json"
    p.write_text(json.dumps({"submitted": submitted, "skipped": skipped},
                            indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nstage0 manifest -> {p}\nbatches: {len(submitted)} skipped: {len(skipped)}")
    return {"manifest": str(p), "submitted": submitted, "skipped": skipped}


# --------------------------------------------------------------------------
def stageA_broad(out_dir: Path) -> Dict[str, Any]:
    """Broad scan: family x mode x direction over Full window."""
    submitted, skipped = [], []
    for label, roots, t0, t1, tflat, modes in SE.FAMILIES:
        contracts = _resolve_family_contracts(roots)
        if not contracts:
            skipped.append({"family": label, "reason": "no contracts"})
            continue
        worst_root = max(roots, key=RL.margin_for)
        for mode in modes:
            for dlabel, dparams in SE.DIRECTIONS:
                # Crypto only meaningful long+short and shortonly+longonly,
                # but all 3 are cheap. Same for others.
                params = SE.setup_mode_defaults(mode, worst_root)
                params.update(RL.base_risk_params(worst_root))
                params["SetupMode"] = mode
                params.update(dparams)
                params.update({
                    "TradeStartTime": t0, "TradeEndTime": t1, "ForceFlatTime": tflat,
                })
                r = _submit(
                    name=f"sev2_stageA_{label}_{mode}_{dlabel}",
                    instruments=contracts, params=params,
                    from_utc=FROM_FULL, to_utc=TO_FULL,
                    session_template=SE.family_session(roots[0]),
                )
                r.update({"family": label, "mode": mode, "direction": dlabel})
                submitted.append(r)
    p = out_dir / "stageA_manifest.json"
    p.write_text(json.dumps({"submitted": submitted, "skipped": skipped},
                            indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nstageA manifest -> {p}\nbatches: {len(submitted)} skipped: {len(skipped)}")
    return {"manifest": str(p), "submitted": submitted}


# --------------------------------------------------------------------------
def stageB_mgc_current(out_dir: Path) -> Dict[str, Any]:
    """MGC current contract (06-26 or whatever data_last says) — short-only,
    every applicable SetupMode, full window."""
    c = RL.resolve_front_contract("MGC")
    if "skip_reason" in c:
        print(f"MGC unresolvable: {c}")
        return {"submitted": [], "skipped": [c]}
    contract = c["instrument"]
    print(f"Using MGC current contract: {contract} (data_last={c.get('data_last')})")

    modes = [SE.MODE_VWAP_PB, SE.MODE_VWAP_MEAN_REV, SE.MODE_COMPRESSION]
    submitted = []
    for mode in modes:
        for dlabel, dparams in SE.DIRECTIONS:
            params = SE.setup_mode_defaults(mode, "MGC")
            params.update(RL.base_risk_params("MGC"))
            params["SetupMode"] = mode
            params.update(dparams)
            params.update({"TradeStartTime": 600, "TradeEndTime": 1000,
                           "ForceFlatTime": 1245})
            r = _submit(
                name=f"sev2_stageB_mgc_current_{mode}_{dlabel}",
                instruments=[contract], params=params,
                from_utc=FROM_FULL, to_utc=TO_FULL,
                session_template=SE.family_session("MGC"),
            )
            r.update({"family": "metals", "mode": mode, "direction": dlabel,
                      "current_contract_validation": True})
            submitted.append(r)
    p = out_dir / "stageB_mgc_manifest.json"
    p.write_text(json.dumps({"submitted": submitted, "current_contract": contract,
                             "data_last": c.get("data_last")},
                            indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nstageB-mgc manifest -> {p}\nbatches: {len(submitted)}")
    return {"manifest": str(p), "submitted": submitted}


# --------------------------------------------------------------------------
def stageD_iso_oos_stress(bundle_dir: Path) -> Dict[str, Any]:
    """Read accepted+candidate profiles JSON from bundle, run IS+OOS+slip+fee
    stress for each. The bundle JSON shape is set by collect_session_edge_v2.py.
    """
    accepted_p = bundle_dir / "accepted_profiles.json"
    candidate_p = bundle_dir / "paper_candidates.json"
    profiles = []
    if accepted_p.exists():
        profiles += json.loads(accepted_p.read_text(encoding="utf-8")).get("profiles", [])
    if candidate_p.exists():
        profiles += json.loads(candidate_p.read_text(encoding="utf-8")).get("profiles", [])
    if not profiles:
        print("No accepted/candidate profiles to stress-test.")
        return {"submitted": []}

    submitted = []
    for prof in profiles:
        instr = prof["instrument"]
        params = dict(prof["parameters"])
        sess = prof.get("session_template") or SE.family_session(instr.split()[0])
        for label, fr, to_ in (("IS", FROM_IS, TO_IS), ("OOS", FROM_OOS, TO_OOS)):
            r = _submit(
                name=f"sev2_stageD_{prof['profile_id']}_{label}",
                instruments=[instr], params=params,
                from_utc=fr, to_utc=to_, session_template=sess,
            )
            r.update({"profile_id": prof["profile_id"], "stress": label})
            submitted.append(r)
        # Slip+1 stress over Full
        p2 = dict(params)
        r = _submit(
            name=f"sev2_stageD_{prof['profile_id']}_slip2",
            instruments=[instr], params=p2,
            from_utc=FROM_FULL, to_utc=TO_FULL,
            session_template=sess, slippage_ticks=2,
        )
        r.update({"profile_id": prof["profile_id"], "stress": "slip2"})
        submitted.append(r)
        # Fee*1.25 stress over Full
        p3 = dict(params)
        p3["RoundTurnCommission"] = max(RL.RTC_FLOOR + 0.50,
                                         float(p3.get("RoundTurnCommission", RL.RTC_FLOOR)) * 1.25)
        r = _submit(
            name=f"sev2_stageD_{prof['profile_id']}_fee125",
            instruments=[instr], params=p3,
            from_utc=FROM_FULL, to_utc=TO_FULL, session_template=sess,
        )
        r.update({"profile_id": prof["profile_id"], "stress": "fee125"})
        submitted.append(r)

    p = bundle_dir / "stageD_manifest.json"
    p.write_text(json.dumps({"submitted": submitted},
                            indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nstageD manifest -> {p}\nbatches: {len(submitted)}")
    return {"manifest": str(p), "submitted": submitted}


# --------------------------------------------------------------------------
def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    stage = argv[1]
    bundle_root = RL.DATA / "research"
    bundle_root.mkdir(exist_ok=True)
    if stage == "stageD":
        if len(argv) < 3:
            print("stageD requires bundle dir as 2nd arg")
            return 2
        bdir = Path(argv[2])
        stageD_iso_oos_stress(bdir)
        return 0

    bdir = bundle_root / f"session_edge_v2_{RL.utcnow_compact()}"
    bdir.mkdir(exist_ok=True)
    print(f"Bundle dir: {bdir}\n")
    if stage == "stage0":
        stage0_smoke(bdir)
    elif stage == "stageA":
        stageA_broad(bdir)
    elif stage == "stageB-mgc":
        stageB_mgc_current(bdir)
    else:
        print(f"unknown stage: {stage}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
