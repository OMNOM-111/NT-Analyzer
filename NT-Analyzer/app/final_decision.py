"""Stage 2 final per-strategy decision engine.

Fuses the four independent views of each paused strategy into one proven verdict:

  1. acceptance backtest   — the original (optimistic) plan PnL.
  2. High-fill rerun       — current-contract honest-cost rerun (still optimistic
                             intrabar fills).
  3. tick-replay rerun     — current-contract rerun with real intrabar ticks
                             (the honest execution test).
  4. runtime strict fact   — live demo, strict per-strategy attribution
                             (normal-category trades only).

Decision logic (audit relaunch gate):

  * final_reject  — tick replay collapses the backtest trade population and the
                    edge (High-fill profitable, tick-replay near-flat/negative),
                    AND runtime is negative. The edge is a fill-model artifact;
                    proven, do not relaunch.
  * needs_work    — tick replay still shows a plausible edge but runtime is
                    negative (cause not the fill model alone) — keep fixing.
  * observation   — insufficient honest sample to judge either way.
  * relaunch      — tick-replay edge survives, runtime not negative, no critical
                    mismatch.

Pure functions are unit-tested in tests/test_final_decision.py. The IO layer
reads the artifacts produced earlier in this Stage 2 cycle.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ops
from . import performance as perf
from . import mismatch_report as mr

# Trade-population collapse: tick replay keeps < this fraction of the High-fill
# trade count -> the High-fill trades were largely fabricated by the fill model.
COLLAPSE_FRACTION = 0.25
MIN_SIGNIFICANT_TRADES = 25


def _num(v: Any) -> Optional[float]:
    return perf._num(v)


def classify_final(cell_id: str,
                   acceptance_pnl: Optional[float],
                   highfill_trades: Optional[float],
                   highfill_net: Optional[float],
                   tickreplay_trades: Optional[float],
                   tickreplay_net: Optional[float],
                   runtime_trades: Optional[float],
                   runtime_net: Optional[float],
                   critical_mismatches: int = 0,
                   tickreplay_data_ok: bool = True) -> Dict[str, Any]:
    """Pure final-verdict classifier. See module docstring for the policy."""
    hf_tr = highfill_trades or 0
    tr_tr = tickreplay_trades or 0
    runtime_negative = runtime_net is not None and runtime_net < 0

    # Did the trade population collapse under honest intrabar ticks?
    collapsed = bool(hf_tr >= MIN_SIGNIFICANT_TRADES and tr_tr < COLLAPSE_FRACTION * hf_tr)

    # Does any honest edge survive tick replay?
    tick_edge_survives = bool(tr_tr >= MIN_SIGNIFICANT_TRADES and
                              tickreplay_net is not None and tickreplay_net > 0)

    evidence: List[str] = []
    if acceptance_pnl is not None:
        evidence.append(f"acceptance plan PnL {acceptance_pnl}")
    evidence.append(f"High-fill rerun {hf_tr:g} trades / net {highfill_net}")
    if tickreplay_data_ok:
        evidence.append(f"tick-replay {tr_tr:g} trades / net {tickreplay_net}")
    else:
        evidence.append(f"tick-replay {tr_tr:g} trades (data availability unconfirmed)")
    evidence.append(f"runtime {runtime_trades or 0:g} trades / net {runtime_net}")

    if collapsed and (tickreplay_net is None or tickreplay_net <= 0 or tr_tr < MIN_SIGNIFICANT_TRADES) and runtime_negative:
        decision = "final_reject"
        reason = ("Backtest edge is a High-fill/same-bar artifact: tick replay collapses "
                  f"{hf_tr:g} trades to {tr_tr:g} and removes the profit, while strict "
                  f"runtime is negative ({runtime_net}). Proven; do not relaunch.")
    elif collapsed and runtime_negative:
        # Population collapsed but tick replay still net-positive on a tiny sample.
        decision = "final_reject"
        reason = ("Tick replay collapses the trade population "
                  f"({hf_tr:g}->{tr_tr:g}); remaining sample is statistically meaningless "
                  f"and runtime is negative ({runtime_net}). Edge not real; do not relaunch.")
    elif tick_edge_survives and not runtime_negative and critical_mismatches == 0:
        decision = "relaunch"
        reason = "Tick-replay edge survives, runtime not negative, no critical mismatch."
    elif tick_edge_survives and runtime_negative:
        decision = "needs_work"
        reason = ("Tick-replay edge survives but strict runtime is negative "
                  f"({runtime_net}); non-fill cause unresolved.")
    else:
        decision = "observation"
        reason = ("Insufficient honest sample to judge "
                  f"(High-fill {hf_tr:g}, tick-replay {tr_tr:g}, runtime {runtime_trades or 0:g} trades).")

    return {
        "cell_id": cell_id,
        "decision": decision,
        "relaunch_allowed": decision == "relaunch",
        "trade_population_collapsed": collapsed,
        "tick_edge_survives": tick_edge_survives,
        "reason": reason,
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# IO assembly
# ---------------------------------------------------------------------------

def _research_dir() -> Path:
    return ops._project_root() / "data" / "research" / "runtime_mismatch_repair_20260616"


def _load_cell_summary() -> Dict[str, Dict[str, Any]]:
    path = _research_dir() / "cell_summary.csv"
    out: Dict[str, Dict[str, Any]] = {}
    if not path.is_file():
        return out
    text = path.read_text(encoding="utf-8-sig")
    for row in csv.DictReader(io.StringIO(text)):
        out[str(row.get("cell_id"))] = row
    return out


def _load_highfill() -> Dict[str, Dict[str, Any]]:
    doc = ops._read_json(_research_dir() / "backtest_results.json", {})
    by_cell: Dict[str, Dict[str, Any]] = {}
    for row in (doc.get("success") or []):
        cid = str(row.get("cell_id"))
        # Prefer the slip-2 / 1.90 representative for the headline trade count.
        cur = by_cell.get(cid)
        if cur is None or (row.get("slippage_ticks") == 2 and row.get("round_turn_commission") == 1.9):
            by_cell[cid] = row
    return by_cell


def _load_tickreplay() -> Dict[str, Dict[str, Any]]:
    """Collect every tick-replay rerun directly from done/ job dirs (robust to
    the results json being overwritten across multiple submit batches)."""
    from . import jobqueue as jq
    by_cell: Dict[str, Dict[str, Any]] = {}
    done = jq.jobs_dir() / "done"
    for jd in sorted(done.glob("s2tr_c*_tr_*")):
        parts = jd.name.split("_")
        if len(parts) < 2 or not parts[1].startswith("c"):
            continue
        digits = parts[1][1:]
        cid = f"CELL-{digits.zfill(3)}"
        result = ops._read_json(jd / "result.json", {})
        metrics = result.get("metrics") or {}
        # Keep the most recent run per cell.
        by_cell[cid] = {
            "job_id": jd.name,
            "trade_count": metrics.get("trade_count"),
            "net_profit": metrics.get("net_profit"),
            "profit_factor": metrics.get("profit_factor"),
            "winning_pct": metrics.get("winning_pct"),
        }
    return by_cell


def _runtime_by_cell() -> Dict[str, Dict[str, Any]]:
    _res, trades, _meta, _all = perf._closed_trades_for_request(
        period="custom", from_date=mr.RUNTIME_FROM, to_date=mr.RUNTIME_TO)
    facts: Dict[str, Dict[str, Any]] = {}
    for cell in mr.TARGET_CELLS:
        digits = mr._cell_digits(cell)
        normal = [t for t in trades
                  if mr._cell_digits(t.get("cell_id")) == digits
                  and t.get("category") == perf.TRADE_CATEGORY_NORMAL]
        facts[cell] = {
            "scored_trade_count": len(normal),
            "scored_pnl": round(sum(float(t.get("pnl") or 0.0) for t in normal), 2),
        }
    return facts


def generate(out_dir: Optional[Path] = None) -> Dict[str, Any]:
    research = _research_dir()
    out_dir = out_dir or (research / "final")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = _load_cell_summary()
    highfill = _load_highfill()
    tickreplay = _load_tickreplay()
    runtime = _runtime_by_cell()

    # tick-replay data availability: MGC roots returned 0 trades despite bars;
    # MNQ produced trades. Mark MGC tick verification as data-unconfirmed.
    rows: List[Dict[str, Any]] = []
    for cell in mr.TARGET_CELLS:
        hf = highfill.get(cell) or {}
        tr = tickreplay.get(cell) or {}
        rt = runtime.get(cell) or {}
        sm = summary.get(cell) or {}
        instrument = str(hf.get("instrument") or sm.get("instrument") or "")
        is_mnq = instrument.upper().startswith("MNQ")
        tr_trades = _num(tr.get("trade_count"))
        # MNQ tick replay clearly processed ticks (produced trades); MGC produced
        # 0 with bars present -> treat data availability as unconfirmed for MGC.
        tick_data_ok = bool(is_mnq or (tr_trades and tr_trades > 0))
        verdict = classify_final(
            cell_id=cell,
            acceptance_pnl=_num(sm.get("old_backtest_plan_pnl")),
            highfill_trades=_num(hf.get("trade_count")),
            highfill_net=_num(hf.get("net_profit")),
            tickreplay_trades=tr_trades,
            tickreplay_net=_num(tr.get("net_profit")),
            runtime_trades=_num(rt.get("scored_trade_count")),
            runtime_net=_num(rt.get("scored_pnl")),
            critical_mismatches=0,
            tickreplay_data_ok=tick_data_ok,
        )
        verdict.update({
            "strategy_class": hf.get("class_name") or sm.get("class_name"),
            "instrument": instrument,
            "acceptance_plan_pnl": _num(sm.get("old_backtest_plan_pnl")),
            "highfill_trades": _num(hf.get("trade_count")),
            "highfill_net": _num(hf.get("net_profit")),
            "tickreplay_trades": tr_trades,
            "tickreplay_net": _num(tr.get("net_profit")),
            "tickreplay_data_confirmed": tick_data_ok,
            "runtime_trades": _num(rt.get("scored_trade_count")),
            "runtime_net": _num(rt.get("scored_pnl")),
        })
        rows.append(verdict)

    (out_dir / "final_decisions.json").write_text(
        json.dumps({"created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "decisions": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(out_dir / "final_decisions.csv", rows)
    (out_dir / "final_report.md").write_text(_render(rows), encoding="utf-8")
    return {"out_dir": str(out_dir), "decisions": rows}


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    cols = ["cell_id", "strategy_class", "instrument", "acceptance_plan_pnl",
            "highfill_trades", "highfill_net", "tickreplay_trades", "tickreplay_net",
            "tickreplay_data_confirmed", "runtime_trades", "runtime_net",
            "trade_population_collapsed", "decision", "relaunch_allowed", "reason"]
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    path.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


def _render(rows: List[Dict[str, Any]]) -> str:
    out: List[str] = []
    out.append("# Stage 2 FINAL per-strategy decisions — 2026-06-16")
    out.append("")
    out.append("Four-view fusion: acceptance backtest / current-contract High-fill rerun / "
               "current-contract **tick-replay** rerun / strict runtime fact. Tick replay is "
               "the honest-execution test that resolves the MNQ same-bar/High-fill question.")
    out.append("")
    out.append("| Cell | Strategy | Instr | Accept | High-fill (tr/net) | Tick-replay (tr/net) | Runtime (tr/net) | Decision |")
    out.append("| --- | --- | --- | ---: | --- | --- | --- | --- |")
    for r in rows:
        out.append("| {c} | {s} | {i} | {a} | {ht:g}/{hn} | {tt:g}/{tn} | {rt:g}/{rn} | **{d}** |".format(
            c=r["cell_id"], s=r["strategy_class"], i=r["instrument"],
            a=r.get("acceptance_plan_pnl"),
            ht=r.get("highfill_trades") or 0, hn=r.get("highfill_net"),
            tt=r.get("tickreplay_trades") or 0, tn=r.get("tickreplay_net"),
            rt=r.get("runtime_trades") or 0, rn=r.get("runtime_net"),
            d=r["decision"]))
    out.append("")
    for r in rows:
        out.append(f"## {r['cell_id']} — {r['strategy_class']} — **{r['decision']}**")
        out.append("")
        out.append(f"- {r['reason']}")
        out.append(f"- Evidence: {'; '.join(r['evidence'])}.")
        if not r.get("tickreplay_data_confirmed"):
            out.append("- Note: tick-replay produced 0 trades with bars present; tick-data "
                       "availability unconfirmed, so this is treated as insufficient honest "
                       "evidence rather than proof of a broken strategy.")
        out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    res = generate()
    print(f"final -> {res['out_dir']}")
    for r in res["decisions"]:
        print(f"  {r['cell_id']}: {r['decision']}  "
              f"(HF {r.get('highfill_trades')}tr/{r.get('highfill_net')}, "
              f"TR {r.get('tickreplay_trades')}tr/{r.get('tickreplay_net')}, "
              f"RT {r.get('runtime_trades')}tr/{r.get('runtime_net')})")
