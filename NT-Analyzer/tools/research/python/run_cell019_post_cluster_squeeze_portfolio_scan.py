"""Cross-instrument portfolio scan for CELL-019 post-cluster squeeze.

Reuses the validated MNQ runner logic from
run_mnq_cell019_post_cluster_squeeze.py, but swaps the instrument/session
envelope across every catalog-backed root that still fits the $2k intraday
profile.

Flow per instrument:
  1. Refresh strategy catalog once for the whole scan.
  2. Run the existing 2025 smoke sweep.
  3. Promote only the top smoke survivor(s) into Full / IS / OOS / stress /
     Current30D.
  4. Mark paper-candidate only if the original gate set passes unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import research_lib as RL  # noqa: E402
import run_mnq_cell019_post_cluster_squeeze as BASE  # noqa: E402


EXCLUDED_ROOTS = {"MNQ"}
EXCLUDED_SESSIONS = {"Cryptocurrency"}


def current_window_for(root: str, days: int = 30) -> tuple[str, str]:
    front = RL.resolve_front_contract(root)
    end_raw = str(front.get("data_last") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    end_day = datetime.fromisoformat(end_raw[:10]).date()
    start_day = end_day - timedelta(days=days)
    return f"{start_day.isoformat()}T00:00:00Z", f"{end_day.isoformat()}T23:59:59Z"


def discover_roots(explicit: Optional[List[str]], include_mnq: bool) -> List[Dict[str, Any]]:
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
        session = RL.session_for(root)
        if session in EXCLUDED_SESSIONS:
            continue
        front = RL.resolve_front_contract(root)
        if front.get("skip_reason") or front.get("stale"):
            continue
        found.append({
            "root": root,
            "instrument": front["instrument"],
            "session_template": session,
            "margin": RL.margin_for(root),
            "fee": RL.fee_for(root),
            "front": front,
        })
    return found


def ensure_strategy_visible() -> Dict[str, Any]:
    refresh_code, refresh = RL.post("/api/catalog/refresh", {})
    strategies_code, strategies = RL.get("/api/strategies")
    names = set(strategies.get("strategies") or [])
    return {
        "refresh_code": refresh_code,
        "refresh_ok": bool(refresh.get("ok")),
        "strategies_code": strategies_code,
        "strategies_count": int(refresh.get("strategies_count") or 0),
        "has_class": BASE.CLASS_NAME in names,
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


def annotate(rows: List[Dict[str, Any]], root_ctx: Dict[str, Any]) -> None:
    for row in rows:
        row["root"] = root_ctx["root"]
        row["front_contract"] = root_ctx["instrument"]
        row["session_template"] = root_ctx["session_template"]


def by_label_period(rows: List[Dict[str, Any]], label: str, period: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("label") == label and row.get("period_label") == period:
            return row
    return {}


def run_for_root(bundle: Path, root_ctx: Dict[str, Any], smoke_top: int, smoke_only: bool) -> Dict[str, Any]:
    root_bundle = bundle / root_ctx["root"]
    root_bundle.mkdir(parents=True, exist_ok=True)

    result: Dict[str, Any] = {
        "root": root_ctx["root"],
        "instrument": root_ctx["instrument"],
        "session_template": root_ctx["session_template"],
        "margin": root_ctx["margin"],
        "fee": root_ctx["fee"],
    }

    smoke_submitted: List[Dict[str, Any]] = []
    for candidate in BASE.candidates():
        row = BASE.submit_job(
            bundle=root_bundle,
            label=candidate["label"],
            stage="smoke",
            period_label=BASE.SMOKE[0],
            from_utc=BASE.SMOKE[1],
            to_utc=BASE.SMOKE[2],
            params=instrument_params(root_ctx, candidate["params"]),
            fee=root_ctx["fee"],
            slip=1,
            instrument=root_ctx["instrument"],
        )
        smoke_submitted.append(row)
    annotate(smoke_submitted, root_ctx)

    smoke_rows = BASE.collect_rows(root_bundle, smoke_submitted, "smoke_rows.json")
    survivors = BASE.pick_smoke(smoke_rows, smoke_top)
    has_positive_smoke = any(float(row.get("adj_net") or 0.0) > 0.0 for row in smoke_rows)
    result["smoke_rows"] = smoke_rows
    result["smoke_survivors"] = survivors
    print(f"root {root_ctx['root']} smoke survivors: {survivors}", flush=True)

    if smoke_only or not survivors or not has_positive_smoke:
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
        for candidate in BASE.candidates()
    }

    validation_submitted: List[Dict[str, Any]] = []
    for label in survivors:
        params = label_to_params[label]
        for period_label, frm, to in (BASE.FULL, BASE.IS, BASE.OOS):
            row = BASE.submit_job(
                bundle=root_bundle,
                label=label,
                stage="validation",
                period_label=period_label,
                from_utc=frm,
                to_utc=to,
                params=params,
                fee=root_ctx["fee"],
                slip=1,
                instrument=root_ctx["instrument"],
            )
            validation_submitted.append(row)
    annotate(validation_submitted, root_ctx)

    validation_rows = BASE.collect_rows(root_bundle, validation_submitted, "validation_rows.json")
    result["validation_rows"] = validation_rows

    full_candidates = [by_label_period(validation_rows, label, "Full") for label in survivors]
    full_candidates = [row for row in full_candidates if row and float(row.get("adj_net") or 0.0) > 0.0]
    full_candidates.sort(key=BASE.score, reverse=True)
    best_label = str(full_candidates[0]["label"]) if full_candidates else None
    result["best_label"] = best_label

    if not best_label:
        result["decision"] = {
            "status": "rejected",
            "reason": "no survivor produced a positive Full adjusted net",
        }
        return result

    best_params = label_to_params[best_label]

    stress_submitted = [
        BASE.submit_job(
            bundle=root_bundle,
            label=best_label,
            stage="stress",
            period_label="slip2",
            from_utc=BASE.FULL[1],
            to_utc=BASE.FULL[2],
            params=best_params,
            fee=root_ctx["fee"],
            slip=2,
            instrument=root_ctx["instrument"],
        ),
        BASE.submit_job(
            bundle=root_bundle,
            label=best_label,
            stage="stress",
            period_label="fee240",
            from_utc=BASE.FULL[1],
            to_utc=BASE.FULL[2],
            params=best_params,
            fee=max(root_ctx["fee"], BASE.FEE_STRESS),
            slip=1,
            instrument=root_ctx["instrument"],
        ),
        BASE.submit_job(
            bundle=root_bundle,
            label=best_label,
            stage="stress",
            period_label="slip2_fee240",
            from_utc=BASE.FULL[1],
            to_utc=BASE.FULL[2],
            params=best_params,
            fee=max(root_ctx["fee"], BASE.FEE_STRESS),
            slip=2,
            instrument=root_ctx["instrument"],
        ),
    ]
    annotate(stress_submitted, root_ctx)
    stress_rows = BASE.collect_rows(root_bundle, stress_submitted, "stress_rows.json")
    result["stress_rows"] = stress_rows

    cur_from, cur_to = current_window_for(root_ctx["root"], 30)
    current_submitted = [
        BASE.submit_job(
            bundle=root_bundle,
            label=best_label,
            stage="current",
            period_label="Current30D",
            from_utc=cur_from,
            to_utc=cur_to,
            params=best_params,
            fee=root_ctx["fee"],
            slip=1,
            instrument=root_ctx["instrument"],
        )
    ]
    annotate(current_submitted, root_ctx)
    current_rows = BASE.collect_rows(root_bundle, current_submitted, "current_rows.json")
    result["current_rows"] = current_rows

    full = by_label_period(validation_rows, best_label, "Full")
    is_ = by_label_period(validation_rows, best_label, "IS")
    oos = by_label_period(validation_rows, best_label, "OOS")
    combined = next((row for row in stress_rows if row.get("period_label") == "slip2_fee240"), {})
    current = current_rows[0] if current_rows else {}
    gate_results = BASE.gates(full, is_, oos, combined, current)
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


def write_outputs(bundle: Path, scan: Dict[str, Any]) -> None:
    (bundle / "scan_summary.json").write_text(
        json.dumps(scan, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    lines = [
        "# CELL-019 Cross-Instrument Post-Cluster Squeeze Scan",
        "",
        f"Bundle: `{bundle.name}`",
        "",
        "| Root | Contract | Smoke survivors | Best label | Full net | Full PF | Full DD | OOS PF | SameBar | Status |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in scan.get("roots", []):
        decision = item.get("decision") or {}
        full = decision.get("full") or {}
        oos = decision.get("oos") or {}
        same_bar = float(full.get("same_bar_pct") or 0.0)
        full_pf = full.get("adj_pf")
        oos_pf = oos.get("adj_pf")
        def pf(value: Any) -> str:
            try:
                x = float(value)
            except Exception:
                return ""
            return "inf" if math.isinf(x) else f"{x:.3f}"
        lines.append(
            f"| {item.get('root','')} | {item.get('instrument','')} | {len(item.get('smoke_survivors') or [])} | "
            f"`{item.get('best_label') or ''}` | {float(full.get('adj_net') or 0.0):.2f} | {pf(full_pf)} | "
            f"{float(full.get('max_drawdown') or 0.0):.2f} | {pf(oos_pf)} | {same_bar:.1f} | {decision.get('status','')} |"
        )
    lines.append("")
    (bundle / "scan_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", help="Comma-separated roots to scan (default: all eligible non-MNQ roots)")
    ap.add_argument("--include-mnq", action="store_true")
    ap.add_argument("--smoke-top", type=int, default=1)
    ap.add_argument("--smoke-only", action="store_true")
    args = ap.parse_args()

    explicit = [part.strip() for part in args.roots.split(",")] if args.roots else None
    roots = discover_roots(explicit, include_mnq=args.include_mnq)
    if not roots:
        raise SystemExit("No eligible roots found for post-cluster squeeze scan")

    visibility = ensure_strategy_visible()
    if not visibility["refresh_ok"] or not visibility["has_class"]:
        raise SystemExit(f"Strategy not visible after catalog refresh: {visibility}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle = RL.DATA / "research" / f"cell019_post_cluster_squeeze_portfolio_scan_{ts}"
    bundle.mkdir(parents=True, exist_ok=True)
    print(f"bundle: {bundle}", flush=True)
    print(f"roots: {[r['root'] for r in roots]}", flush=True)

    scan: Dict[str, Any] = {
        "class_name": BASE.CLASS_NAME,
        "created_utc": RL.utcnow_iso(),
        "visibility": visibility,
        "roots": [],
    }

    for root_ctx in roots:
        print(
            f"\n=== root {root_ctx['root']} contract={root_ctx['instrument']} session={root_ctx['session_template']} margin={root_ctx['margin']} fee={root_ctx['fee']} ===",
            flush=True,
        )
        root_result = run_for_root(bundle, root_ctx, smoke_top=args.smoke_top, smoke_only=args.smoke_only)
        scan["roots"].append(root_result)
        write_outputs(bundle, scan)


if __name__ == "__main__":
    main()