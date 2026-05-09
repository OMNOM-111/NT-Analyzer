"""Repair broken `$` substitutions in vwap_explorer_20260505_1750/rejected_profiles.json
caused by PowerShell here-string variable expansion eating the dollar sign.

We reconstruct the intended sentences from the numeric metrics already stored in
the same record, so no human re-interpretation is needed.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

P = Path(__file__).resolve().parents[3] / "data" / "research" / \
    "vwap_explorer_20260505_1750" / "rejected_profiles.json"

doc = json.loads(P.read_text(encoding="utf-8"))

for entry in doc.get("rejected", []):
    m = entry.get("metrics", {})
    new_reasons = []
    for r in entry.get("reasons", []):
        # Pattern: "(-, AdjPF X.YZ)" -> "($IS_NET, AdjPF X.YZ)"
        is_net = m.get("IS2024_AdjNet")
        if "(-, AdjPF" in r and is_net is not None:
            r = r.replace("(-, AdjPF", f"(IS AdjNet ${is_net}, AdjPF")
        # Pattern: "AdjNet -" at end of clause -> "AdjNet $X"
        slip_net = m.get("Stress_slip2_AdjNet")
        if slip_net is not None:
            r = re.sub(r"AdjNet -(?=[\.,;\s]|$)", f"AdjNet ${slip_net}", r)
        # Pattern: "IS-2024 catastrophic: - in N trades"
        if "catastrophic: -" in r and is_net is not None:
            r = r.replace("catastrophic: -", f"catastrophic: AdjNet ${is_net}")
        # Pattern: "Max drawdown - ="
        max_dd = m.get("Full_AdjDD")
        if "Max drawdown - =" in r and max_dd is not None:
            r = r.replace("Max drawdown - =", f"Max drawdown ${abs(max_dd)} =")
        new_reasons.append(r)
    entry["reasons"] = new_reasons

P.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"repaired {len(doc.get('rejected', []))} entries -> {P}")
