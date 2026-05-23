"""Print time-window audit decisions from strategies.json profiles."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROFILES = ROOT / "data" / "profiles" / "strategies.json"
RUN_ID = "twaudit_20260518T095551"
ADOPTED = {"CELL-012", "CELL-013"}
REJECT = {
    "CELL-001", "CELL-002", "CELL-003", "CELL-004",
    "CELL-011", "CELL-014", "CELL-015", "CELL-016",
}


def main() -> int:
    doc = json.loads(PROFILES.read_text(encoding="utf-8-sig"))
    rows = []
    for p in doc.get("profiles") or []:
        if not isinstance(p, dict):
            continue
        cell = str(p.get("cell_id") or "").upper()
        if cell not in ADOPTED | REJECT:
            continue
        if p.get("status") not in ("ready", "paper_ready"):
            continue
        notes = str(p.get("notes") or "")
        decision = "ADOPT" if cell in ADOPTED else "REJECT_EXPANSION"
        if decision == "REJECT_EXPANSION" and RUN_ID not in notes:
            decision += " (note missing in profile)"
        locked = p.get("locked_parameters") or {}
        rows.append({
            "cell": cell,
            "profile_id": p.get("profile_id"),
            "decision": decision,
            "trade_window_pt": p.get("trade_window_pt"),
            "TradeStartTime": locked.get("TradeStartTime"),
            "TradeEndTime": locked.get("TradeEndTime"),
            "UseSecondTradeWindow": locked.get("UseSecondTradeWindow"),
            "ForceFlatTime": locked.get("ForceFlatTime"),
        })
    rows.sort(key=lambda r: r["cell"])
    for r in rows:
        print(
            f"{r['cell']:8} {r['decision']:18} "
            f"window={r.get('trade_window_pt') or '-'} "
            f"params={r['TradeStartTime']}-{r['TradeEndTime']} "
            f"2nd={r['UseSecondTradeWindow']} flat={r['ForceFlatTime']} "
            f"id={r['profile_id']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
