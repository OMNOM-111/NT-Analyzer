"""
write_instrument_coverage.py

Build instrument-strategy coverage checklist for the Micros universe.

Reads:
  - data/catalog/instrument_groups.json   (group -> roots)
  - data/profiles/strategies.json         (profile cards)
  - data/research/session_edge_v2_*/all_tests.json (latest bundle, optional)
  - data/catalog/instruments.json         (current contracts, optional)

Writes:
  - data/profiles/instrument_strategy_coverage.json
  - data/profiles/instrument_strategy_coverage.md

Coverage status per instrument root:
    ready        — at least one validated profile can be paper/online tested
    in_progress  — still being checked, needs correction, or should be removed
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from glob import glob

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

STATUS_RANK = {
    "ready": 5,
    "paper_ready": 5,
    "in_progress": 4,
    "paper_candidate": 4,
    "research_baseline": 3,
    "archived": 2,
    "rejected": 1,
    "missing": 0,
}

STATUS_BADGE = {
    "ready": "✅ Готова",
    "in_progress": "В процессе",
}


def _coverage_status(status: str | None) -> str:
    return "ready" if status in {"ready", "paper_ready"} else "in_progress"


def _load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _instrument_root(symbol: str) -> str:
    if not symbol:
        return ""
    # "MGC 06-26" -> "MGC"; also handle "MGC06-26"
    s = symbol.strip().split()[0]
    for i, c in enumerate(s):
        if c.isdigit():
            return s[:i]
    return s


def _current_contract_for_root(root: str, instruments_catalog) -> str | None:
    if not instruments_catalog:
        return None
    items = instruments_catalog.get("instruments") or instruments_catalog.get("items") or []
    best = None
    best_dt = None
    for it in items:
        sym = it.get("symbol") or it.get("name") or ""
        if _instrument_root(sym) != root:
            continue
        last = it.get("data_last") or it.get("last_bar_utc") or ""
        try:
            dt = datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        except Exception:
            dt = None
        if best is None or (dt and (best_dt is None or dt > best_dt)):
            best, best_dt = sym, dt
    return best


def _summarize_metrics(p: dict) -> dict:
    m = p.get("metrics") or {}
    out = {}
    for k in (
        "trade_count", "win_rate", "net_profit_after_commission",
        "profit_factor_after_commission", "max_drawdown_after_commission",
        "trades_per_month",
    ):
        if k in m:
            out[k] = m[k]
        elif k in p:
            out[k] = p[k]
    return out


def _latest_bundle_dir() -> str | None:
    pat = os.path.join(ROOT, "data", "research", "session_edge_v2_*")
    dirs = sorted(glob(pat))
    return dirs[-1] if dirs else None


def _latest_bundle_name(strategies_doc: dict) -> str | None:
    generated_from = strategies_doc.get("generated_from") or {}
    bundles = generated_from.get("bundles") or []
    if bundles:
        return bundles[-1]
    bundle_dir = _latest_bundle_dir()
    return os.path.basename(bundle_dir) if bundle_dir else None


def build_coverage():
    groups = _load_json(os.path.join(ROOT, "data", "catalog", "instrument_groups.json"), {})
    strategies_doc = _load_json(os.path.join(ROOT, "data", "profiles", "strategies.json"), {})
    profiles = strategies_doc.get("profiles") or []
    instruments_catalog = _load_json(os.path.join(ROOT, "data", "catalog", "instruments.json"), None)

    bundle_name = _latest_bundle_name(strategies_doc)

    # Group lookup
    micros = []
    root_to_groups = {}
    for grp in groups.get("groups", []):
        gname = grp.get("group_name")
        for r in grp.get("roots", []):
            root_to_groups.setdefault(r, []).append(gname)
            if gname == "Micros":
                if r not in micros:
                    micros.append(r)

    # Bucket profiles by instrument root
    by_root: dict[str, list[dict]] = {}
    for p in profiles:
        instr = p.get("instrument") or ""
        root = _instrument_root(instr)
        if not root:
            continue
        by_root.setdefault(root, []).append(p)

    # Build entries — Micros first (excluding MNQ from "needs work" view, but keep its row)
    entries = []
    for root in micros:
        group_names = root_to_groups.get(root, [])
        candidates = by_root.get(root, [])
        current_contract = _current_contract_for_root(root, instruments_catalog)

        if not candidates:
            st = _coverage_status("missing")
            entries.append({
                "root": root,
                "groups": group_names,
                "current_contract": current_contract,
                "status": st,
                "status_badge": STATUS_BADGE[st],
                "strategy_count": 0,
                "best_profile_id": None,
                "strategy_class": None,
                "setup_mode": None,
                "timeframe": None,
                "evidence_bundle": bundle_name,
                "evidence_job_ids": [],
                "metrics": {},
                "notes": "No strategy/profile registered for this instrument.",
                "next_action": "Add or rerun research; consider new SetupMode.",
                "is_locked": False,
            })
            continue

        # Pick best by status rank, then by metric net profit
        def _key(p):
            st = p.get("status") or "missing"
            return (
                STATUS_RANK.get(st, 0),
                (p.get("metrics") or {}).get("net_profit_after_commission", 0) or 0,
            )
        best = sorted(candidates, key=_key, reverse=True)[0]
        raw_status = best.get("status") or "missing"
        st = _coverage_status(raw_status)

        # Locked detection (Pilot MNQ)
        is_locked = bool(best.get("locked")) or best.get("profile_id") == "b1_shortonly_mnq_5m_high_slip1_paper_v2"

        ev_ids = best.get("evidence_job_ids") or []
        if not ev_ids and best.get("last_job_id"):
            ev_ids = [best["last_job_id"]]

        entries.append({
            "root": root,
            "groups": group_names,
            "current_contract": current_contract or best.get("current_contract") or best.get("instrument"),
            "status": st,
            "status_badge": STATUS_BADGE[st],
            "strategy_count": len(candidates),
            "best_profile_id": best.get("profile_id"),
            "strategy_class": best.get("strategy_class"),
            "setup_mode": (best.get("locked_parameters") or {}).get("SetupMode")
                          or best.get("setup_mode"),
            "timeframe": best.get("timeframe"),
            "evidence_bundle": bundle_name,
            "evidence_job_ids": ev_ids,
            "metrics": _summarize_metrics(best),
            "notes": best.get("notes") or "",
            "next_action": _next_action(raw_status, best),
            "is_locked": is_locked,
        })

    # Also include any profiles whose root isn't in Micros (informational)
    extra = []
    for root, plist in by_root.items():
        if root in micros or not root:
            continue
        best = sorted(plist, key=lambda p: STATUS_RANK.get(p.get("status") or "missing", 0), reverse=True)[0]
        raw_status = best.get("status") or "missing"
        st = _coverage_status(raw_status)
        extra.append({
            "root": root,
            "groups": root_to_groups.get(root, []),
            "current_contract": best.get("current_contract") or best.get("instrument"),
            "status": st,
            "status_badge": STATUS_BADGE[st],
            "strategy_count": len(plist),
            "best_profile_id": best.get("profile_id"),
            "strategy_class": best.get("strategy_class"),
            "setup_mode": (best.get("locked_parameters") or {}).get("SetupMode"),
            "timeframe": best.get("timeframe"),
            "evidence_bundle": bundle_name,
            "evidence_job_ids": (best.get("evidence_job_ids") or [best.get("last_job_id")] if best.get("last_job_id") else []),
            "metrics": _summarize_metrics(best),
            "notes": best.get("notes") or "",
            "next_action": _next_action(raw_status, best),
            "is_locked": False,
        })

    summary = {
        "ready": sum(1 for e in entries if e["status"] == "ready"),
        "in_progress": sum(1 for e in entries if e["status"] == "in_progress"),
        "total_micros": len(entries),
    }

    doc = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_groups": "data/catalog/instrument_groups.json",
        "source_profiles": "data/profiles/strategies.json",
        "evidence_bundle": bundle_name,
        "summary": summary,
        "micros": entries,
        "non_micros_with_profiles": extra,
        "legend": STATUS_BADGE,
    }
    return doc


def _next_action(status: str, profile: dict) -> str:
    if status in {"ready", "paper_ready"}:
        if profile.get("locked"):
            return "Locked — keep on demo / paper monitoring."
        return "Promote to paper/demo; monitor 2-week forward window."
    if status in {"in_progress", "paper_candidate"}:
        return "Run forward sample / current-contract validation; revisit after ≥20 trades."
    if status == "research_baseline":
        return "Use as baseline only; not for live."
    if status == "rejected":
        return "Try alternative SetupMode or different family bucket."
    if status == "archived":
        return "Reference only."
    return "Add strategy / register profile."


def _fmt_md(doc: dict) -> str:
    s = doc["summary"]
    lines = [
        "# Instrument Strategy Coverage — Micros",
        "",
        f"_Generated: {doc['generated_at_utc']}_",
        f"_Evidence bundle: `{doc.get('evidence_bundle') or '—'}`_",
        "",
        f"**Summary:** ✅ {s['ready']} готово · {s['in_progress']} в процессе "
        f"(of {s['total_micros']} Micros)",
        "",
        "| Root | Current | Status | # | Best profile | Class | Mode | TF | Trades | PF | Net | Next action |",
        "|---|---|---|---:|---|---|---|---|---:|---:|---:|---|",
    ]
    for e in doc["micros"]:
        m = e.get("metrics") or {}
        tc = m.get("trade_count", "—")
        pf = m.get("profit_factor_after_commission", "—")
        net = m.get("net_profit_after_commission", "—")
        lock_mark = " 🔒" if e.get("is_locked") else ""
        lines.append(
            f"| {e['root']} | {e.get('current_contract') or '—'} | {e['status_badge']}{lock_mark} | "
            f"{e['strategy_count']} | "
            f"{e.get('best_profile_id') or '—'} | "
            f"{e.get('strategy_class') or '—'} | "
            f"{e.get('setup_mode') or '—'} | "
            f"{e.get('timeframe') or '—'} | "
            f"{tc} | {pf} | {net} | {e.get('next_action','')} |"
        )
    if doc.get("non_micros_with_profiles"):
        lines += ["", "## Non-Micros profiles (informational)", ""]
        lines += ["| Root | Status | Best profile | Class |", "|---|---|---|---|"]
        for e in doc["non_micros_with_profiles"]:
            lines.append(
                f"| {e['root']} | {e['status_badge']} | "
                f"{e.get('best_profile_id') or '—'} | {e.get('strategy_class') or '—'} |"
            )
    lines += ["", "## Legend", ""]
    for k, v in doc["legend"].items():
        lines.append(f"- `{k}` — {v}")
    lines.append("")
    return "\n".join(lines)


def main():
    doc = build_coverage()
    out_dir = os.path.join(ROOT, "data", "profiles")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "instrument_strategy_coverage.json")
    md_path = os.path.join(out_dir, "instrument_strategy_coverage.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_fmt_md(doc))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    s = doc["summary"]
    print(f"summary: ready={s['ready']} in_progress={s['in_progress']} total={s['total_micros']}")


if __name__ == "__main__":
    sys.exit(main() or 0)
