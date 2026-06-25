"""Operationally close the Stage 2 runtime/backtest mismatch cells.

The diagnostic/final-decision stage proves that the current strategies are not
eligible for relaunch. This script moves them out of the working portfolio
surface while preserving audit evidence and source history.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RESEARCH_DIR = ROOT / "data" / "research" / "runtime_mismatch_repair_20260616"
FINAL_SUMMARY = RESEARCH_DIR / "final" / "summary.json"
CLOSURE_DIR = RESEARCH_DIR / "closure"
CLOSURE_DATE = "2026-06-17"
CLOSURE_ID = "runtime_mismatch_closure_2026-06-17"

TARGET_CELLS = {
    "CELL-001",
    "CELL-002",
    "CELL-003",
    "CELL-004",
    "CELL-005",
    "CELL-011",
    "CELL-015",
    "CELL-016",
    "CELL-017",
    "CELL-018",
}

CLASS_ALIASES = {
    "CELL-001": {"VWAPPullbackMGC5mV1"},
    "CELL-002": {"B1ShortOnlyMGC5mV2"},
    "CELL-003": {"B1Stop24MGC5mC003"},
    "CELL-004": {"B1Stop20MGC5mC004"},
    "CELL-005": {"B1Volume14MGC5mC005"},
    "CELL-011": {"NTAMicroVwapRiskPilot"},
    "CELL-015": {"NTAMnqLiquiditySweepReversalC015"},
    "CELL-016": {"NTAMnqOpenDriveShortScalpC016"},
    "CELL-017": {"NTAMnqPostActiveScalpC017", "NTAMnqLateVwapLongScalpC017"},
    "CELL-018": {"NTAMnqDailyOpenScalpC018"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def decisions_by_cell() -> Dict[str, Dict[str, Any]]:
    doc = read_json(FINAL_SUMMARY, {})
    out: Dict[str, Dict[str, Any]] = {}
    for row in doc.get("decisions") or []:
        if isinstance(row, dict) and row.get("cell_id") in TARGET_CELLS:
            out[str(row["cell_id"])] = row
    return out


def profile_cell(profile: Dict[str, Any]) -> str:
    return str(profile.get("cell_id") or profile.get("archived_cell_id") or "").strip()


def profile_classes(profile: Dict[str, Any]) -> set[str]:
    out = set()
    for key in ("strategy_class", "deploy_strategy_class"):
        value = str(profile.get(key) or "").strip()
        if value:
            out.add(value)
    for value in profile.get("runtime_strategy_classes") or []:
        text = str(value or "").strip()
        if text:
            out.add(text)
    return out


def target_cell_for_profile(profile: Dict[str, Any]) -> Optional[str]:
    cell = profile_cell(profile)
    if cell in TARGET_CELLS:
        return cell
    classes = profile_classes(profile)
    for target_cell, aliases in CLASS_ALIASES.items():
        if classes.intersection(aliases):
            return target_cell
    return None


def stable_strategy_id(profile: Dict[str, Any]) -> str:
    for key in ("stable_id", "runtime_strategy_id", "profile_id"):
        value = str(profile.get(key) or "").strip()
        if value:
            return value
    return ""


def closure_reason(cell: str, decision: Dict[str, Any]) -> str:
    if decision.get("decision") == "final_reject":
        return (
            "Archived/purged from working portfolio: current-contract tick replay "
            "proved the High-fill backtest edge was a same-bar artifact."
        )
    if cell == "CELL-011":
        return (
            "Archived/purged from working portfolio: only one strict runtime trade "
            "and no honest current-contract edge sample; no relaunch evidence."
        )
    return (
        "Archived/purged from working portfolio: current-contract High-fill sample "
        "has only three trades and tick-replay produced zero trades; no durable edge "
        "or relaunch evidence."
    )


def closure_record(cell: str, decision: Dict[str, Any], previous_status: str) -> Dict[str, Any]:
    return {
        "closure_id": CLOSURE_ID,
        "closed_at_utc": utc_now(),
        "final_action": "archived_purged",
        "cell_status": "empty",
        "purge_completed": True,
        "repair_attempted": False,
        "relaunch_ready": False,
        "original_cell_id": cell,
        "previous_status": previous_status,
        "diagnostic_decision": decision.get("decision") or "observation",
        "reason": closure_reason(cell, decision),
        "evidence": {
            "highfill_trades": decision.get("highfill_trades"),
            "highfill_net": decision.get("highfill_net"),
            "tickreplay_trades": decision.get("tickreplay_trades"),
            "tickreplay_net": decision.get("tickreplay_net"),
            "tickreplay_data_confirmed": decision.get("tickreplay_data_confirmed"),
            "runtime_trades": decision.get("runtime_trades"),
            "runtime_net": decision.get("runtime_net"),
        },
        "artifact_bundle": "data/research/runtime_mismatch_repair_20260616",
    }


def close_profiles(decisions: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    path = ROOT / "data" / "profiles" / "strategies.json"
    doc = read_json(path, {"schema_version": "1.1", "profiles": []})
    rows: List[Dict[str, Any]] = []
    for profile in doc.get("profiles") or []:
        if not isinstance(profile, dict):
            continue
        cell = target_cell_for_profile(profile)
        if not cell:
            continue
        decision = decisions.get(cell, {"cell_id": cell, "decision": "observation"})
        previous_status = str(profile.get("status") or "")
        rec = closure_record(cell, decision, previous_status)
        profile["archived_cell_id"] = cell
        profile["cell_id"] = ""
        profile["slot"] = None
        profile["status"] = "archived"
        profile["status_label"] = "Архив"
        profile["matrix_hidden"] = True
        profile["archive_reason"] = rec["reason"]
        profile["purge_completed_at_utc"] = rec["closed_at_utc"]
        profile["operational_closure"] = rec
        profile["updated_at_utc"] = rec["closed_at_utc"]
        demo = profile.get("demo_trial")
        if isinstance(demo, dict):
            demo["state"] = "closed"
            demo["closed_at_utc"] = rec["closed_at_utc"]
            demo["close_reason"] = rec["reason"]
        rows.append({
            "cell_id": cell,
            "profile_id": profile.get("profile_id") or profile.get("id") or "",
            "strategy_id": stable_strategy_id(profile),
            "strategy_class": profile.get("deploy_strategy_class") or profile.get("strategy_class") or "",
            "previous_status": previous_status,
            "final_action": "archived_purged",
            "cell_status": "empty",
            "reason": rec["reason"],
        })
    doc["updated_at_utc"] = utc_now()
    doc["stage2_operational_closure"] = {
        "closure_id": CLOSURE_ID,
        "closed_at_utc": utc_now(),
        "target_cells": sorted(TARGET_CELLS),
        "final_action": "archived_purged",
        "artifact_bundle": "data/research/runtime_mismatch_repair_20260616",
    }
    write_json(path, doc)
    return rows


def registry_cell(row: Dict[str, Any]) -> str:
    return str(row.get("cell_id") or row.get("archived_cell_id") or "").strip()


def registry_classes(row: Dict[str, Any]) -> set[str]:
    out = set()
    for key in ("class_name", "deploy_strategy_class"):
        value = str(row.get(key) or "").strip()
        if value:
            out.add(value)
    return out


def target_cell_for_registry(row: Dict[str, Any]) -> Optional[str]:
    cell = registry_cell(row)
    if cell in TARGET_CELLS:
        return cell
    classes = registry_classes(row)
    sid = str(row.get("strategy_id") or "").strip().lower()
    for target_cell, aliases in CLASS_ALIASES.items():
        if classes.intersection(aliases):
            return target_cell
    strategy_ids = {
        "CELL-001": {"vwap_pullback_mgc_5m_v1"},
        "CELL-002": {"mgc_b1_short_5m_v2"},
        "CELL-003": {"mgc_b1_stop24_5m_c003"},
        "CELL-004": {"mgc_b1_stop20_5m_c004"},
        "CELL-005": {"mgc_b1_volume14_5m_c005"},
        "CELL-011": {"vwap_short_mnq_5m_v1"},
        "CELL-015": {"open_pressure_stop_scalp_mnq_1m_v1"},
        "CELL-016": {"open_drive_short_scalp_mnq_1m_v1"},
        "CELL-017": {"late_vwap_long_scalp_mnq_1m_v1", "postactive_allmodules_mnq_1m_c017_v1"},
        "CELL-018": {"daily_open_allmodules_mnq_1m_v1"},
    }
    for target_cell, ids in strategy_ids.items():
        if sid in ids:
            return target_cell
    return None


def close_registry(decisions: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    path = ROOT / "data" / "ops" / "registry.json"
    doc = read_json(path, {"schema_version": "1.0", "strategies": []})
    rows: List[Dict[str, Any]] = []
    for row in doc.get("strategies") or []:
        if not isinstance(row, dict):
            continue
        cell = target_cell_for_registry(row)
        if not cell:
            continue
        decision = decisions.get(cell, {"cell_id": cell, "decision": "observation"})
        previous_status = str(row.get("status") or "")
        rec = closure_record(cell, decision, previous_status)
        row["archived_cell_id"] = cell
        row["cell_id"] = ""
        row["status"] = "archived"
        row["account_mode"] = "live_locked"
        row["archive_reason"] = rec["reason"]
        row["operational_closure"] = rec
        row["updated_at_utc"] = rec["closed_at_utc"]
        rows.append({
            "cell_id": cell,
            "strategy_id": row.get("strategy_id") or "",
            "strategy_class": row.get("class_name") or "",
            "previous_status": previous_status,
            "final_action": "archived_purged",
            "cell_status": "empty",
            "reason": rec["reason"],
        })
    doc["updated_at_utc"] = utc_now()
    doc["stage2_operational_closure"] = {
        "closure_id": CLOSURE_ID,
        "closed_at_utc": utc_now(),
        "target_cells": sorted(TARGET_CELLS),
        "final_action": "archived_purged",
    }
    write_json(path, doc)
    return rows


def close_states(registry_rows: Iterable[Dict[str, Any]]) -> None:
    path = ROOT / "data" / "ops" / "state.json"
    doc = read_json(path, {})
    if not isinstance(doc, dict):
        return
    ids = {str(row.get("strategy_id") or "") for row in registry_rows if row.get("strategy_id")}
    for sid in ids:
        state = doc.get(sid)
        if not isinstance(state, dict):
            continue
        state["current_state"] = "archived"
        state["manual_enabled"] = False
        state["intent_pending"] = False
        state["last_state_change_utc"] = utc_now()
        state["archive_reason"] = f"{CLOSURE_ID}: archived_purged"
    write_json(path, doc)


def close_scc() -> Dict[str, Any]:
    path = ROOT / "data" / "ops" / "scc_classes.json"
    doc = read_json(path, {"active": [], "rejected": []})
    active = {str(x) for x in doc.get("active") or [] if str(x)}
    rejected = {str(x) for x in doc.get("rejected") or [] if str(x)}
    target_classes = set().union(*CLASS_ALIASES.values())
    active -= target_classes
    rejected |= target_classes
    doc["active"] = sorted(active)
    doc["rejected"] = sorted(rejected)
    doc["notes"] = (
        "Stage2 operational closure 2026-06-17: C001-C005/C011/C015-C018 "
        "archived_purged; rejected classes are excluded from SCC/catalog. "
        "Historical source remains for audit only."
    )
    doc["stage2_operational_closure"] = {
        "closure_id": CLOSURE_ID,
        "target_cells": sorted(TARGET_CELLS),
        "rejected_classes_added": sorted(target_classes),
    }
    write_json(path, doc)
    return doc


def close_raw_catalog() -> Dict[str, Any]:
    path = ROOT / "data" / "catalog" / "strategies.json"
    doc = read_json(path, {})
    if not isinstance(doc, dict):
        return {"removed": 0}
    strategies = doc.get("strategies")
    if not isinstance(strategies, list):
        return {"removed": 0}
    target_classes = set().union(*CLASS_ALIASES.values())
    before = len(strategies)
    doc["strategies"] = [
        row for row in strategies
        if not (isinstance(row, dict) and str(row.get("class_name") or "").strip() in target_classes)
    ]
    removed = before - len(doc["strategies"])
    doc["count"] = len(doc["strategies"])
    doc["stage2_operational_closure"] = {
        "closure_id": CLOSURE_ID,
        "removed_classes": sorted(target_classes),
        "note": "Raw bridge catalog snapshot filtered; app /api/catalog also excludes rejected classes.",
    }
    write_json(path, doc)
    return {"removed": removed}


def close_families() -> None:
    path = ROOT / "data" / "profiles" / "strategy_families.json"
    doc = read_json(path, {})
    if not isinstance(doc, dict):
        return
    profile_ids = {
        "b1_shortonly_mnq_5m_high_slip1_paper_v2",
        "sev2_mgc_vwappullback_shortonly_paper_v1",
        "mgc_b1_shortonly_5m_paper_v2",
        "mgc_b1_stop24_5m_paper_c003",
        "mgc_b1_stop20_5m_paper_c004",
        "mgc_b1_volume14_5m_paper_c005",
        "mnq_open_pressure_stop_scalp_1m_c015_v1",
        "mnq_open_drive_short_scalp_1m_c016_candidate_v1",
        "mnq_late_vwap_long_scalp_1m_c017_candidate_v1",
        "mnq_postactive_allmodules_1m_c017_ready_v1",
        "mnq_daily_open_allmodules_2h_1m_c018_ready_v1",
    }
    target_classes = set().union(*CLASS_ALIASES.values())
    for mapping_name, keys in (("class_map", target_classes), ("profile_map", profile_ids)):
        mapping = doc.get(mapping_name)
        if not isinstance(mapping, dict):
            continue
        for key in list(mapping.keys()):
            if key not in keys:
                continue
            value = mapping.get(key)
            if not isinstance(value, dict):
                continue
            value["family_status"] = "archived_purged"
            value["family_role"] = "archived_strategy"
            value["new_research_allowed"] = False
            value["operational_closure"] = {
                "closure_id": CLOSURE_ID,
                "final_action": "archived_purged",
                "cell_status": "empty",
            }
    doc["updated_at_utc"] = utc_now()
    write_json(path, doc)


def write_notes(profile_rows: Iterable[Dict[str, Any]]) -> None:
    from app import ops  # Imported late so JSON edits above stay standalone.

    seen = set()
    for row in profile_rows:
        sid = str(row.get("strategy_id") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        note = (
            f"[Operational closure {CLOSURE_DATE}] final_action=archived_purged; "
            f"original_cell={row['cell_id']}; cell_status=empty. {row['reason']} "
            "No demo/runtime relaunch is allowed from this profile; historical source "
            "and reports remain only as audit evidence."
        )
        ops.append_note(sid, note, by="stage2_closure")


def write_closure_artifacts(profile_rows: List[Dict[str, Any]], registry_rows: List[Dict[str, Any]],
                            decisions: Dict[str, Dict[str, Any]]) -> None:
    CLOSURE_DIR.mkdir(parents=True, exist_ok=True)
    by_cell: Dict[str, Dict[str, Any]] = {}
    for cell in sorted(TARGET_CELLS):
        d = decisions.get(cell, {"cell_id": cell, "decision": "observation"})
        profiles = [r for r in profile_rows if r["cell_id"] == cell]
        registries = [r for r in registry_rows if r["cell_id"] == cell]
        reason = closure_reason(cell, d)
        by_cell[cell] = {
            "cell_id": cell,
            "final_action": "archived_purged",
            "cell_status": "empty",
            "purge_completed": True,
            "repair_attempted": False,
            "relaunch_ready": False,
            "diagnostic_decision": d.get("decision") or "observation",
            "reason": reason,
            "profiles_closed": profiles,
            "registry_rows_closed": registries,
            "evidence": {
                "highfill_trades": d.get("highfill_trades"),
                "highfill_net": d.get("highfill_net"),
                "tickreplay_trades": d.get("tickreplay_trades"),
                "tickreplay_net": d.get("tickreplay_net"),
                "tickreplay_data_confirmed": d.get("tickreplay_data_confirmed"),
                "runtime_trades": d.get("runtime_trades"),
                "runtime_net": d.get("runtime_net"),
            },
        }

    summary = {
        "schema_version": "1.0",
        "closure_id": CLOSURE_ID,
        "created_at_utc": utc_now(),
        "source_final_summary": str(FINAL_SUMMARY.relative_to(ROOT)).replace("\\", "/"),
        "final_action_counts": {"archived_purged": len(TARGET_CELLS)},
        "relaunch_ready_cells": [],
        "empty_cells": sorted(TARGET_CELLS),
        "cells": [by_cell[cell] for cell in sorted(by_cell)],
    }
    write_json(CLOSURE_DIR / "summary.json", summary)

    csv_path = CLOSURE_DIR / "closure_matrix.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = [
            "cell_id", "final_action", "cell_status", "purge_completed",
            "repair_attempted", "relaunch_ready", "diagnostic_decision",
            "highfill_trades", "highfill_net", "tickreplay_trades",
            "tickreplay_net", "runtime_trades", "runtime_net", "reason",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for cell in sorted(by_cell):
            row = by_cell[cell]
            ev = row["evidence"]
            writer.writerow({
                "cell_id": cell,
                "final_action": row["final_action"],
                "cell_status": row["cell_status"],
                "purge_completed": row["purge_completed"],
                "repair_attempted": row["repair_attempted"],
                "relaunch_ready": row["relaunch_ready"],
                "diagnostic_decision": row["diagnostic_decision"],
                "highfill_trades": ev.get("highfill_trades"),
                "highfill_net": ev.get("highfill_net"),
                "tickreplay_trades": ev.get("tickreplay_trades"),
                "tickreplay_net": ev.get("tickreplay_net"),
                "runtime_trades": ev.get("runtime_trades"),
                "runtime_net": ev.get("runtime_net"),
                "reason": row["reason"],
            })

    lines = [
        f"# Runtime mismatch closure - {CLOSURE_DATE}",
        "",
        "Final operational action: all ten problem cells are archived/purged from the working portfolio surface.",
        "No strategy is approved for relaunch.",
        "",
        "| Cell | Final action | Cell now | Diagnostic decision | Evidence | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for cell in sorted(by_cell):
        row = by_cell[cell]
        ev = row["evidence"]
        def pair(label: str, trades_key: str, net_key: str) -> str:
            trades = ev.get(trades_key)
            net = ev.get(net_key)
            if trades is None and net is None:
                return f"{label} n/a"
            return f"{label} {trades}tr/{net}"
        evidence = (
            f"{pair('HF', 'highfill_trades', 'highfill_net')}; "
            f"{pair('TR', 'tickreplay_trades', 'tickreplay_net')}; "
            f"{pair('runtime', 'runtime_trades', 'runtime_net')}"
        )
        lines.append(
            f"| {cell} | archived_purged | empty | {row['diagnostic_decision']} | "
            f"{evidence} | {row['reason']} |"
        )
    lines.extend([
        "",
        "Closure checks:",
        "",
        "- `data/profiles/strategies.json`: target profiles archived, hidden from matrix, original cell stored as `archived_cell_id`.",
        "- `data/ops/registry.json`: target registry rows archived/live_locked and original cell stored as `archived_cell_id`.",
        "- `data/ops/scc_classes.json`: target deploy classes moved to rejected, so SCC cannot expose them as active.",
        "- `/api/catalog`: rejected classes are filtered from the selectable strategy catalog.",
        "- Strategy notes received an `Operational closure 2026-06-17` entry.",
        "",
        "Historical source and reports are retained for audit only; a future strategy must occupy these cells through a new profile and a new validation cycle.",
        "",
    ])
    (CLOSURE_DIR / "runtime_mismatch_closure_2026-06-17.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def update_research_registry_md() -> None:
    path = ROOT.parent / "РАЗРАБОТКА СТРАТЕГИЙ" / "Реестр стратегий.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    marker = f"## Operational closure {CLOSURE_DATE}"
    if marker in text:
        return
    block = f"""
{marker}

`runtime_mismatch_closure_2026-06-17`: C001-C005, C011, C015-C018 removed from the working portfolio surface.

- C015-C018: archived_purged after tick-replay proved the 1m High-fill/same-bar edge was not real.
- C001-C005: archived_purged because current-contract evidence has only 0-3 honest trades and no relaunch-grade edge.
- C011: archived_purged because one runtime trade is not a relaunch-grade evidence base.
- Cells are empty for new strategy development; historical source/reports remain audit-only.

"""
    insert_before = "\n## Покрытие инструментов"
    if insert_before in text:
        text = text.replace(insert_before, "\n" + block + insert_before, 1)
    else:
        text = text.rstrip() + "\n\n" + block
    path.write_text(text, encoding="utf-8")


def main() -> None:
    decisions = decisions_by_cell()
    profile_rows = close_profiles(decisions)
    registry_rows = close_registry(decisions)
    close_states(registry_rows)
    close_scc()
    close_raw_catalog()
    close_families()
    write_notes(profile_rows)
    write_closure_artifacts(profile_rows, registry_rows, decisions)
    update_research_registry_md()
    print(f"closed_profiles={len(profile_rows)}")
    print(f"closed_registry_rows={len(registry_rows)}")
    print(f"closure_dir={CLOSURE_DIR}")


if __name__ == "__main__":
    main()
