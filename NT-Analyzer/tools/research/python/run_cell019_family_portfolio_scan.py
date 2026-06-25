"""Generic portfolio scan for ready-made CELL-019 runners.

This orchestrator reuses family-specific candidate selection, scoring and gates,
but applies them across the non-MNQ portfolio with a single cross-instrument
pipeline:
  Smoke -> Full / IS / OOS -> stress -> Current30D

Promotion rule: only roots with at least one positive smoke variant go to the
expensive stages.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import research_lib as RL  # noqa: E402


EXCLUDED_ROOTS = {"MNQ"}
EXCLUDED_SESSIONS = {"Cryptocurrency"}

FAMILY_CONFIG: Dict[str, Dict[str, str]] = {
    "precash_compression_breakout": {
        "module": "run_mnq_cell019_precash_compression_breakout",
        "session_mode": "eth",
        "bundle_prefix": "cell019_precash_compression_breakout_portfolio_scan",
    },
    "overnight_settlement_breakout": {
        "module": "run_mnq_cell019_overnight_settlement_breakout",
        "session_mode": "eth",
        "bundle_prefix": "cell019_overnight_settlement_breakout_portfolio_scan",
    },
    "overnight_settlement_reversion": {
        "module": "run_mnq_cell019_overnight_settlement_reversion",
        "session_mode": "eth",
        "bundle_prefix": "cell019_overnight_settlement_reversion_portfolio_scan",
    },
    "vwap_pullback": {
        "module": "run_mnq_cell019_vwap_pullback_portfolio_adapter",
        "session_mode": "rth",
        "bundle_prefix": "cell019_vwap_pullback_portfolio_scan",
    },
}

ETH_SESSION_TEMPLATE_BY_ROOT: Dict[str, str] = {
    "MES": "CME US Index Futures ETH",
    "MNQ": "CME US Index Futures ETH",
    "MYM": "CME US Index Futures ETH",
    "M2K": "CME US Index Futures ETH",
    "MGC": "Nymex Metals - Energy ETH",
    "MHG": "Nymex Metals - Energy ETH",
    "SIL": "Nymex Metals - Energy ETH",
    "MCL": "Nymex Metals - Energy ETH",
    "MNG": "Nymex Metals - Energy ETH",
    "M6A": "CME FX Futures ETH",
    "M6B": "CME FX Futures ETH",
    "M6E": "CME FX Futures ETH",
}


def load_family(name: str) -> Tuple[Dict[str, str], Any]:
    config = FAMILY_CONFIG[name]
    module = importlib.import_module(config["module"])
    return config, module


def bars_period_value(base: Any) -> int:
    if hasattr(base, "BARS_PERIOD_VALUE"):
        return int(getattr(base, "BARS_PERIOD_VALUE"))
    if hasattr(base, "BARS"):
        return int(getattr(base, "BARS"))
    raise AttributeError(f"{base.__name__} has no BARS_PERIOD_VALUE/BARS constant")


def current_window_for(root: str, days: int = 30) -> Tuple[str, str]:
    front = RL.resolve_front_contract(root)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def session_template_for(root: str, session_mode: str) -> Optional[str]:
    if session_mode == "eth":
        return ETH_SESSION_TEMPLATE_BY_ROOT.get(root)
    if session_mode == "rth":
        return RL.session_for(root)
    raise ValueError(f"Unsupported session mode: {session_mode}")


def discover_roots(explicit: Optional[List[str]], include_mnq: bool, session_mode: str) -> List[Dict[str, Any]]:
    roots = explicit or sorted(RL.ACTIVE_MARGIN)
    found: List[Dict[str, Any]] = []
    for root in roots:
        root = root.strip().upper()
        if not root:
            continue
        if not include_mnq and root in EXCLUDED_ROOTS:
            continue
        if RL.margin_for(root) > 2000.0:
            continue
        session_template = session_template_for(root, session_mode)
        if not session_template or session_template in EXCLUDED_SESSIONS:
            continue
        front = RL.resolve_front_contract(root)
        if front.get("skip_reason") or front.get("stale"):
            continue
        found.append({
            "root": root,
            "instrument": front["instrument"],
            "session_template": session_template,
            "margin": RL.margin_for(root),
            "fee": RL.fee_for(root),
            "front": front,
        })
    return found


def ensure_strategy_visible(base: Any) -> Dict[str, Any]:
    refresh_code, refresh = RL.post("/api/catalog/refresh", {})
    strategies_code, strategies = RL.get("/api/strategies")
    names = set(strategies.get("strategies") or [])
    return {
        "refresh_code": refresh_code,
        "refresh_ok": bool(refresh.get("ok")),
        "strategies_code": strategies_code,
        "strategies_count": int(refresh.get("strategies_count") or 0),
        "has_class": getattr(base, "CLASS_NAME") in names,
    }


def instrument_params(root_ctx: Dict[str, Any], base_params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(base_params)
    params.update({
        "InstrumentName": root_ctx["root"],
        "ContractName": root_ctx["instrument"],
        "SessionTemplateName": root_ctx["session_template"],
        "ActiveMarginPerContract": root_ctx["margin"],
        "RoundTurnCommission": root_ctx["fee"],
    })
    return params


def submit_job(
    *,
    base: Any,
    root_ctx: Dict[str, Any],
    bundle: Path,
    label: str,
    stage: str,
    period_label: str,
    from_utc: str,
    to_utc: str,
    params: Dict[str, Any],
    fee: float,
    slip: int,
) -> Dict[str, Any]:
    p = dict(params)
    p.update({
        "RoundTurnCommission": fee,
        "SlippageTicks": slip,
        "ActiveMarginPerContract": root_ctx["margin"],
        "InstrumentStatus": "allowed",
        "MaxContractsByCapital": 20,
    })
    contract = root_ctx["instrument"]
    body = RL.build_job_body(
        class_name=base.CLASS_NAME,
        instrument=contract,
        params=p,
        from_utc=from_utc,
        to_utc=to_utc,
        bars_period_type="Minute",
        bars_period_value=bars_period_value(base),
        slippage_ticks=slip,
        role="smoke",
        session_template=p.get("SessionTemplateName", root_ctx["session_template"]),
        risk_profile=RL.build_risk_profile_for([contract]),
    )
    code, resp = RL.post("/api/jobs", body)
    job_id = resp.get("job_id") if code == 201 and isinstance(resp, dict) else None
    row = {
        "stage": stage,
        "label": label,
        "instrument": contract,
        "root": root_ctx["root"],
        "front_contract": contract,
        "session_template": root_ctx["session_template"],
        "period_label": period_label,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "fee": fee,
        "slip": slip,
        "code": code,
        "job_id": job_id,
        "response": resp,
        "params": p,
    }
    print(
        f"submit {stage:10s} {label:36s} {contract:12s} {period_label:14s} code={code} job={job_id or resp}",
        flush=True,
    )
    (bundle / "latest_submitted.json").write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    return row


def by_label_period(rows: List[Dict[str, Any]], label: str, period: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("label") == label and row.get("period_label") == period:
            return row
    return {}


def best_smoke_row(base: Any, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    return sorted(rows, key=base.score, reverse=True)[0]


def stress_fee_for(base: Any, root_ctx: Dict[str, Any]) -> float:
    family_stress = float(getattr(base, "FEE_STRESS", RL.fee_stress(root_ctx["root"])))
    return max(root_ctx["fee"], family_stress)


def run_for_root(bundle: Path, root_ctx: Dict[str, Any], base: Any, smoke_top: int, smoke_only: bool) -> Dict[str, Any]:
    root_bundle = bundle / root_ctx["root"]
    root_bundle.mkdir(parents=True, exist_ok=True)

    result: Dict[str, Any] = {
        "root": root_ctx["root"],
        "instrument": root_ctx["instrument"],
        "session_template": root_ctx["session_template"],
        "margin": root_ctx["margin"],
        "fee": root_ctx["fee"],
    }

    candidates = base.candidates()
    smoke_submitted = [
        submit_job(
            base=base,
            root_ctx=root_ctx,
            bundle=root_bundle,
            label=candidate["label"],
            stage="smoke",
            period_label=base.SMOKE[0],
            from_utc=base.SMOKE[1],
            to_utc=base.SMOKE[2],
            params=instrument_params(root_ctx, candidate["params"]),
            fee=root_ctx["fee"],
            slip=1,
        )
        for candidate in candidates
    ]
    smoke_rows = base.collect_rows(root_bundle, smoke_submitted, "smoke_rows.json")
    smoke_survivors = base.pick_smoke(smoke_rows, smoke_top)
    has_positive_smoke = any(float(row.get("adj_net") or 0.0) > 0.0 for row in smoke_rows)
    result["smoke_rows"] = smoke_rows
    result["smoke_survivors"] = smoke_survivors
    print(f"root {root_ctx['root']} smoke survivors: {smoke_survivors}", flush=True)

    if smoke_only or not smoke_survivors or not has_positive_smoke:
        result["decision"] = {
            "status": "smoke_only" if smoke_only else "rejected",
            "reason": (
                "smoke_only flag"
                if smoke_only else
                "no positive smoke variant; stop before Full/IS/OOS"
                if not has_positive_smoke else
                "no smoke survivor passed minimal filters"
            ),
        }
        return result

    label_to_params = {
        candidate["label"]: instrument_params(root_ctx, candidate["params"])
        for candidate in candidates
    }

    validation_submitted: List[Dict[str, Any]] = []
    for label in smoke_survivors:
        params = label_to_params[label]
        for period_label, frm, to in (base.FULL, base.IS, base.OOS):
            validation_submitted.append(
                submit_job(
                    base=base,
                    root_ctx=root_ctx,
                    bundle=root_bundle,
                    label=label,
                    stage="validation",
                    period_label=period_label,
                    from_utc=frm,
                    to_utc=to,
                    params=params,
                    fee=root_ctx["fee"],
                    slip=1,
                )
            )
    validation_rows = base.collect_rows(root_bundle, validation_submitted, "validation_rows.json")
    result["validation_rows"] = validation_rows

    full_candidates = [by_label_period(validation_rows, label, "Full") for label in smoke_survivors]
    full_candidates = [row for row in full_candidates if row and float(row.get("adj_net") or 0.0) > 0.0]
    full_candidates.sort(key=base.score, reverse=True)
    best_label = str(full_candidates[0]["label"]) if full_candidates else None
    result["best_label"] = best_label

    if not best_label:
        result["decision"] = {
            "status": "rejected",
            "reason": "no survivor produced a positive Full adjusted net",
        }
        return result

    best_params = label_to_params[best_label]
    stress_fee = stress_fee_for(base, root_ctx)
    stress_submitted = [
        submit_job(
            base=base,
            root_ctx=root_ctx,
            bundle=root_bundle,
            label=best_label,
            stage="stress",
            period_label="slip2",
            from_utc=base.FULL[1],
            to_utc=base.FULL[2],
            params=best_params,
            fee=root_ctx["fee"],
            slip=2,
        ),
        submit_job(
            base=base,
            root_ctx=root_ctx,
            bundle=root_bundle,
            label=best_label,
            stage="stress",
            period_label="fee240",
            from_utc=base.FULL[1],
            to_utc=base.FULL[2],
            params=best_params,
            fee=stress_fee,
            slip=1,
        ),
        submit_job(
            base=base,
            root_ctx=root_ctx,
            bundle=root_bundle,
            label=best_label,
            stage="stress",
            period_label="slip2_fee240",
            from_utc=base.FULL[1],
            to_utc=base.FULL[2],
            params=best_params,
            fee=stress_fee,
            slip=2,
        ),
    ]
    stress_rows = base.collect_rows(root_bundle, stress_submitted, "stress_rows.json")
    result["stress_rows"] = stress_rows

    cur_from, cur_to = current_window_for(root_ctx["root"], 30)
    current_submitted = [
        submit_job(
            base=base,
            root_ctx=root_ctx,
            bundle=root_bundle,
            label=best_label,
            stage="current",
            period_label="Current30D",
            from_utc=cur_from,
            to_utc=cur_to,
            params=best_params,
            fee=root_ctx["fee"],
            slip=1,
        )
    ]
    current_rows = base.collect_rows(root_bundle, current_submitted, "current_rows.json")
    result["current_rows"] = current_rows

    full = by_label_period(validation_rows, best_label, "Full")
    is_ = by_label_period(validation_rows, best_label, "IS")
    oos = by_label_period(validation_rows, best_label, "OOS")
    combined = next((row for row in stress_rows if row.get("period_label") == "slip2_fee240"), {})
    current = current_rows[0] if current_rows else {}
    gate_results = base.gates(full, is_, oos, combined, current)
    result["gate_results"] = gate_results
    result["decision"] = {
        "status": "paper_candidate" if all(gate_results.values()) else "rejected",
        "best_label": best_label,
        "locked_params": best_params,
        "gates": gate_results,
        "full": full,
        "is": is_,
        "oos": oos,
        "stress_combined": combined,
        "current30d": current,
    }
    return result


def write_outputs(bundle: Path, scan: Dict[str, Any], family: str, base: Any) -> None:
    (bundle / "scan_summary.json").write_text(
        json.dumps(scan, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    lines = [
        f"# CELL-019 Portfolio Scan: {family}",
        "",
        f"Bundle: `{bundle.name}`",
        f"Class: `{base.CLASS_NAME}`",
        "",
        "| Root | Contract | Best smoke | Smoke net | Smoke PF | Full net | Full PF | OOS PF | SameBar | Status | Reason |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]

    def pf(value: Any) -> str:
        try:
            x = float(value)
        except Exception:
            return ""
        return "inf" if math.isinf(x) else f"{x:.3f}"

    for item in scan.get("roots", []):
        smoke = best_smoke_row(base, item.get("smoke_rows") or [])
        decision = item.get("decision") or {}
        full = decision.get("full") or {}
        oos = decision.get("oos") or {}
        same_bar = float(full.get("same_bar_pct") or 0.0)
        lines.append(
            f"| {item.get('root', '')} | {item.get('instrument', '')} | `{smoke.get('label') or ''}` | "
            f"{float(smoke.get('adj_net') or 0.0):.2f} | {pf(smoke.get('adj_pf'))} | "
            f"{float(full.get('adj_net') or 0.0):.2f} | {pf(full.get('adj_pf'))} | {pf(oos.get('adj_pf'))} | "
            f"{same_bar:.1f} | {decision.get('status', '')} | {decision.get('reason', '')} |"
        )
    lines.append("")
    (bundle / "scan_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True, choices=sorted(FAMILY_CONFIG))
    ap.add_argument("--roots", help="Comma-separated roots to scan (default: all eligible non-MNQ roots)")
    ap.add_argument("--include-mnq", action="store_true")
    ap.add_argument("--smoke-top", type=int, default=1)
    ap.add_argument("--smoke-only", action="store_true")
    args = ap.parse_args()

    config, base = load_family(args.family)
    explicit = [part.strip() for part in args.roots.split(",")] if args.roots else None
    roots = discover_roots(explicit, include_mnq=args.include_mnq, session_mode=config["session_mode"])
    if not roots:
        raise SystemExit(f"No eligible roots found for family {args.family}")

    visibility = ensure_strategy_visible(base)
    if not visibility["refresh_ok"] or not visibility["has_class"]:
        raise SystemExit(f"Strategy not visible after catalog refresh: {visibility}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"{config['bundle_prefix']}_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"family: {args.family}", flush=True)
    print(f"bundle: {bundle}", flush=True)
    print(f"roots: {[r['root'] for r in roots]}", flush=True)

    scan: Dict[str, Any] = {
        "family": args.family,
        "class_name": base.CLASS_NAME,
        "created_utc": RL.utcnow_iso(),
        "session_mode": config["session_mode"],
        "visibility": visibility,
        "roots": [],
    }

    for root_ctx in roots:
        print(
            f"\n=== root {root_ctx['root']} contract={root_ctx['instrument']} session={root_ctx['session_template']} margin={root_ctx['margin']} fee={root_ctx['fee']} ===",
            flush=True,
        )
        root_result = run_for_root(bundle, root_ctx, base, smoke_top=args.smoke_top, smoke_only=args.smoke_only)
        scan["roots"].append(root_result)
        write_outputs(bundle, scan, args.family, base)


if __name__ == "__main__":
    main()