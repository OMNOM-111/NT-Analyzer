"""Rank MNQ MICRO_ORB follow-up variants with soft edge-first gates."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import research_lib as RL  # noqa: E402

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List


def f(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) if row.get(key) is not None else default)
    except (TypeError, ValueError):
        return default


def score(row: Dict[str, Any]) -> float:
    adj = f(row, "adj_net")
    pf = f(row, "adj_pf")
    oos = f(row, "oos_adj_pf")
    win = f(row, "win_rate")
    avg = f(row, "avg_trade_after_commission")
    dd = abs(f(row, "max_drawdown"))
    tpd = f(row, "trades_per_day")
    losses = f(row, "max_consecutive_losses")
    same = f(row, "same_bar_pct")

    s = 0.0
    s += max(-35, min(45, adj / 12.0))
    s += max(-30, min(30, (pf - 1.0) * 55.0))
    s += max(-25, min(25, (oos - 1.0) * 45.0))
    s += max(-18, min(18, (win - 50.0) * 0.9))
    s += max(-18, min(18, avg * 8.0))
    s += max(-20, min(15, (300.0 - dd) / 18.0))
    if 10.0 <= tpd <= 20.0:
        s += 12
    elif tpd >= 3.0:
        s += 5
    elif tpd >= 0.75:
        s -= 2
    else:
        s -= 10
    if losses > 5:
        s -= min(18, (losses - 5) * 6)
    if same > 90:
        s -= 12
    elif same > 70:
        s -= 8
    elif same > 50:
        s -= 4
    return round(s, 2)


def soft_decision(row: Dict[str, Any], quarters: List[Dict[str, Any]]) -> str:
    if int(row.get("trades") or 0) <= 0:
        return "REJECT_NO_TRADES"
    positive_quarters = sum(1 for q in quarters if f(q, "adj_net") > 0)
    if f(row, "adj_net") <= 0 or f(row, "adj_pf") < 1.0:
        return "REJECT_NEGATIVE_FULL"
    if f(row, "oos_adj_pf") < 1.0:
        return "REJECT_NEGATIVE_OOS"
    edge = (
        f(row, "adj_net") > 250
        and f(row, "adj_pf") >= 1.25
        and f(row, "oos_adj_pf") >= 1.25
        and f(row, "win_rate") >= 60
        and RL.max_drawdown_within_budget(f(row, "max_drawdown"))
        and positive_quarters >= 5
    )
    robust = (
        edge
        and f(row, "avg_trade_after_commission") >= 1.0
        and f(row, "max_consecutive_losses") <= 5
    )
    if robust:
        return "PAPER_CANDIDATE_SPARSE"
    if edge:
        return "RESEARCH_EDGE_SPARSE"
    return "RESEARCH_ONLY"


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: python rank_mnq_scalp_followup.py <bundle>")
        return 2
    bundle = Path(argv[1])
    data = json.loads((bundle / "mnq_scalp_results.json").read_text(encoding="utf-8"))
    rows = data["rows"]
    full = [r for r in rows if r.get("period_label") == "Full"]
    quarters_by_module: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if str(r.get("period_label") or "").startswith("Q"):
            quarters_by_module[str(r.get("module") or "")].append(r)

    ranked: List[Dict[str, Any]] = []
    for r in full:
        mod = str(r.get("module") or "")
        quarters = quarters_by_module.get(mod, [])
        q_pos = sum(1 for q in quarters if f(q, "adj_net") > 0)
        item = dict(r)
        item["edge_score"] = score(r)
        item["soft_decision"] = soft_decision(r, quarters)
        item["positive_quarters"] = f"{q_pos}/{len(quarters)}"
        ranked.append(item)
    ranked.sort(key=lambda r: (r["soft_decision"].startswith("REJECT"), -f(r, "edge_score")))

    out_json = bundle / "followup_ranking.json"
    out_json.write_text(json.dumps({"ranked_full": ranked}, indent=2, ensure_ascii=False), encoding="utf-8")

    cols = [
        "rank", "variant", "decision", "score", "trades", "tpd", "adj_net", "adj_pf",
        "oos_pf", "win", "avg", "dd", "losses", "same_bar", "positive_quarters",
    ]
    lines = [
        "# MNQ MICRO_ORB Follow-up Ranking",
        "",
        "| " + " | ".join(cols) + " |",
        "|" + "|".join(["---"] * len(cols)) + "|",
    ]
    for i, r in enumerate(ranked, 1):
        lines.append(
            "| "
            + " | ".join([
                str(i),
                str(r.get("module") or ""),
                str(r.get("soft_decision") or ""),
                str(r.get("edge_score")),
                str(r.get("trades")),
                str(r.get("trades_per_day")),
                str(r.get("adj_net")),
                str(r.get("adj_pf")),
                str(r.get("oos_adj_pf")),
                str(r.get("win_rate")),
                str(r.get("avg_trade_after_commission")),
                str(r.get("max_drawdown")),
                str(r.get("max_consecutive_losses")),
                str(r.get("same_bar_pct")),
                str(r.get("positive_quarters")),
            ])
            + " |"
        )
    out_md = bundle / "followup_ranking.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
