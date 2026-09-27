"""Public synthetic candles for product onboarding; no provider or owner data.

Deterministic time-indexed demo series supports the normal Desktop timeframes,
history paging and polling. It cannot be used as a live execution price source.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone


def series(instrument, timeframe, limit=1500, *, start=None, end=None, max_points=0, now=None):
    tf = str(timeframe or "5m")
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        seconds = int(tf[:-1]) * (2592000 if tf.endswith("M") else units[tf[-1].lower()])
        if seconds <= 0:
            raise ValueError()
    except (ValueError, KeyError, IndexError):
        raise ValueError("unsupported_demo_timeframe") from None
    current = now or datetime.now(timezone.utc)
    last = int(min((end or current).timestamp(), current.timestamp()) // seconds)
    count = max(1, min(int(max_points or limit or 1500), 20000))
    first = max(last - count + 1, int(start.timestamp() // seconds) if start else 0)
    seed = int(hashlib.sha256(str(instrument).upper().encode()).hexdigest()[:8], 16)
    base = 100 + seed % 20000
    def price(index):
        return round(base * (1 + .015 * math.sin(index / 47 + seed % 100)
                             + .003 * math.sin(index / 7)), 2)
    bars = []
    for index in range(first, last + 1):
        opened, closed = price(index - 1), price(index)
        spread = round(base * .0003 * (1.2 + math.sin(index / 3) ** 2), 2)
        bars.append({"t": datetime.fromtimestamp(index * seconds, timezone.utc).isoformat().replace("+00:00", "Z"),
                     "o": opened, "h": round(max(opened, closed) + spread, 2),
                     "l": round(min(opened, closed) - spread, 2), "c": closed,
                     "v": 100 + (index * 31 + seed) % 900})
    return {"instrument": str(instrument).upper(), "bars": bars, "alerts": [],
            "total": len(bars), "raw_total": len(bars), "live": False,
            "status": "demo_replay", "market_data_available": True, "price_marker_live": False,
            "requested_timeframe": tf, "matched_timeframe": tf,
            "source": {"kind": "demo_replay", "provider": "demo_replay", "runtime_state": "DEMO",
                       "sharing_scope": "public_demo", "data_plane": "history_replay"},
            "freshness": {"fresh": False, "stale": False, "offline": False},
            "note": "Учебные синтетические данные · не реальные котировки · не для исполнения сделок",
            "history": {"exhausted": False}}
