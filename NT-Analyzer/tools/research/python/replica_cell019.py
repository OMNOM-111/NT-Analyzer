"""Standalone replica of the CELL-019 entry funnel over a job's bars.json.
Counts how many bars pass each gate, to locate the blocker without recompiling.
Filters are off (diag config): MinVolumeFactor=0.01, VolExpansionFactor=0.01,
RequireVwap/Ema=False, CompressionAtrMult=10, MinBarRangeTicks=1,
MinCompressionRangeTicks=2, MaxCompressionRangeTicks=200, BreakoutBufferTicks=1.
"""
import json
import sys
from pathlib import Path

TICK = 0.25
BARS_REQ = 30
LOOKBACK = 8
ATR_PERIOD = 14
VOL_SMA = 20
MIN_COMP = 2
MAX_COMP = 200
COMP_ATR_MULT = 10.0
MIN_BAR_RANGE = 1
BREAKOUT_BUFFER = 1
MIN_STOP = 16
MAX_STOP = 40
ATR_STOP_MULT = 1.0
STOP_BUFFER = 4
RR = 1.6
MIN_TARGET = 16

job = sys.argv[1] if len(sys.argv) > 1 else "ui_20260601T032537255Z"
bars_path = Path(rf"D:\Documents\NT-Analyzer-artifacts\jobs\done\{job}\bars.json")
bars = json.loads(bars_path.read_text())
n = len(bars)
H = [b["h"] for b in bars]
L = [b["l"] for b in bars]
C = [b["c"] for b in bars]
O = [b["o"] for b in bars]
V = [b["v"] for b in bars]

# Wilder ATR
tr = [0.0] * n
for i in range(n):
    if i == 0:
        tr[i] = H[i] - L[i]
    else:
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
atr = [0.0] * n
for i in range(n):
    if i < ATR_PERIOD:
        atr[i] = sum(tr[: i + 1]) / (i + 1)
    else:
        atr[i] = (atr[i - 1] * (ATR_PERIOD - 1) + tr[i]) / ATR_PERIOD

# Volume SMA
volsma = [0.0] * n
for i in range(n):
    lo = max(0, i - VOL_SMA + 1)
    volsma[i] = sum(V[lo : i + 1]) / (i - lo + 1)

cnt = dict(eligible=0, compressed=0, range_ok=0, broke=0, vol_ok=0,
           entry_long=0, entry_short=0, stop_gate_fail=0, qty0=0, entries=0)
first_entries = []
for i in range(n):
    if i < BARS_REQ:
        continue
    cnt["eligible"] += 1
    lookback = min(max(2, LOOKBACK), i - 1)
    if lookback < 2:
        continue
    # box over bars i-1 .. i-lookback
    boxHigh = max(H[i - k] for k in range(1, lookback + 1))
    boxLow = min(L[i - k] for k in range(1, lookback + 1))
    if boxHigh <= boxLow:
        continue
    boxRangeTicks = (boxHigh - boxLow) / TICK
    atrTicks = atr[i] / TICK
    compressed = (boxRangeTicks >= MIN_COMP and boxRangeTicks <= MAX_COMP
                  and (COMP_ATR_MULT <= 0 or boxRangeTicks <= COMP_ATR_MULT * atrTicks))
    if not compressed:
        continue
    cnt["compressed"] += 1
    rangeTicks = (H[i] - L[i]) / TICK
    if rangeTicks < MIN_BAR_RANGE:
        continue
    cnt["range_ok"] += 1
    brokeUp = C[i] >= boxHigh + BREAKOUT_BUFFER * TICK
    brokeDown = C[i] <= boxLow - BREAKOUT_BUFFER * TICK
    if not (brokeUp or brokeDown):
        continue
    cnt["broke"] += 1
    volfac = V[i] / volsma[i] if volsma[i] > 0 else 0.0
    if volfac < 0.01:
        continue
    cnt["vol_ok"] += 1
    isLong = brokeUp
    # stop gate
    oppEdge = boxLow if isLong else boxHigh
    if isLong:
        geomPrice = min(L[i], oppEdge) - STOP_BUFFER * TICK
        geomTicks = (C[i] - geomPrice) / TICK
    else:
        geomPrice = max(H[i], oppEdge) + STOP_BUFFER * TICK
        geomTicks = (geomPrice - C[i]) / TICK
    import math
    rawTicks = math.ceil(max(1.0, geomTicks))
    atrStopTicks = round((atr[i] / TICK) * ATR_STOP_MULT)
    stopTicks = max(rawTicks, atrStopTicks)
    stopTicks = max(stopTicks, MIN_STOP)
    stopTicks = min(stopTicks, MAX_STOP)
    targetTicks = round(stopTicks * RR)
    if stopTicks < MIN_STOP or targetTicks < MIN_TARGET:
        cnt["stop_gate_fail"] += 1
        continue
    cnt["entries"] += 1
    if isLong:
        cnt["entry_long"] += 1
    else:
        cnt["entry_short"] += 1
    if len(first_entries) < 5:
        first_entries.append((bars[i]["t"], "L" if isLong else "S", round(C[i], 2),
                              round(boxHigh, 2), round(boxLow, 2), stopTicks, targetTicks))

print(f"bars={n}")
print(json.dumps(cnt, indent=2))
print("first entries:")
for e in first_entries:
    print(" ", e)
