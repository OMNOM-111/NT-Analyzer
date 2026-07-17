"""Baseline latency instrumentation for the pre-event-stream market-data path.

Records stage timestamps without changing control flow. Used for Phase 0
reports and later comparisons after the IPC / WebSocket cutover.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional

from . import runtime_env

_LOCK = threading.RLock()
_ENABLED = os.environ.get("NTA_MARKET_DATA_BASELINE", "1").strip() not in {"0", "false", "False"}
_MAX_SAMPLES = 4096
_STAGES: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))
_EVENTS: Deque[Dict[str, Any]] = deque(maxlen=_MAX_SAMPLES)
_COUNTERS: Dict[str, int] = defaultdict(int)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _runtime_dir() -> Path:
    from . import runtime
    override = getattr(runtime._RUNTIME_CONTEXT, "runtime_dir", "")
    path = (
        Path(override) if override
        else runtime_env.data_path("runtime", project_root=_root())
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def baseline_path() -> Path:
    return _runtime_dir() / "market_data_baseline.json"


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def mark(stage: str, duration_ms: Optional[float] = None, **meta: Any) -> None:
    """Record a stage sample.

    If ``duration_ms`` is omitted, only an occurrence counter is incremented.
    """
    if not _ENABLED:
        return
    with _LOCK:
        _COUNTERS[str(stage)] += 1
        if duration_ms is not None and math.isfinite(float(duration_ms)):
            _STAGES[str(stage)].append(float(duration_ms))
        if meta:
            row = {
                "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "stage": str(stage),
                "duration_ms": duration_ms,
            }
            row.update(meta)
            _EVENTS.append(row)


class StageTimer:
    """Context manager for stage duration sampling."""

    __slots__ = ("_stage", "_meta", "_t0")

    def __init__(self, stage: str, **meta: Any) -> None:
        self._stage = stage
        self._meta = meta
        self._t0 = 0.0

    def __enter__(self) -> "StageTimer":
        self._t0 = now_ms()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        mark(self._stage, now_ms() - self._t0, **self._meta)


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return round(ordered[low], 3)
    weight = rank - low
    return round(ordered[low] * (1.0 - weight) + ordered[high] * weight, 3)


def stage_stats(stage: str) -> Dict[str, Any]:
    with _LOCK:
        samples = list(_STAGES.get(stage, ()))
        count = int(_COUNTERS.get(stage, 0))
    if not samples:
        return {"stage": stage, "count": count, "samples": 0}
    return {
        "stage": stage,
        "count": count,
        "samples": len(samples),
        "p50_ms": _percentile(samples, 50),
        "p95_ms": _percentile(samples, 95),
        "p99_ms": _percentile(samples, 99),
        "mean_ms": round(statistics.fmean(samples), 3),
        "max_ms": round(max(samples), 3),
        "min_ms": round(min(samples), 3),
    }


def snapshot() -> Dict[str, Any]:
    with _LOCK:
        stages = sorted(_STAGES.keys())
        counters = dict(_COUNTERS)
        recent = list(_EVENTS)[-50:]
    return {
        "version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "enabled": _ENABLED,
        "counters": counters,
        "stages": [stage_stats(name) for name in stages],
        "recent_events": recent,
        "known_bottlenecks_code_audit": [
            "desktop.js LIVE_POLL_MS=350 full /bars/batch re-fetch",
            "BEFORE Phase2: Bridge CaptureMarketData mutated last bar + RequestSnapshotWrite on Last ticks",
            "AFTER Phase2: MD callback only enqueues; file snapshot remains on timer/BarsUpdate path",
            "Bridge WriteSnapshot serializes all series to market_bars.json (atomic file I/O fallback)",
            "backend re-reads/parses market_bars.json (mitigated by signature cache)",
            "no WebSocket incremental UI path yet; CanonicalBarEngine not yet wired to Desktop",
        ],
    }


def persist() -> Path:
    path = baseline_path()
    path.write_text(json.dumps(snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def reset() -> None:
    with _LOCK:
        _STAGES.clear()
        _EVENTS.clear()
        _COUNTERS.clear()


def summarize_markdown(stats: Optional[Dict[str, Any]] = None) -> str:
    doc = stats or snapshot()
    lines = [
        "# Market-data baseline summary",
        "",
        f"Generated: `{doc.get('generated_at_utc')}`",
        "",
        "| Stage | Samples | p50 (ms) | p95 (ms) | p99 (ms) | mean | max |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in doc.get("stages") or []:
        lines.append(
            "| {stage} | {samples} | {p50} | {p95} | {p99} | {mean} | {maxv} |".format(
                stage=row.get("stage"),
                samples=row.get("samples", 0),
                p50=row.get("p50_ms", "—"),
                p95=row.get("p95_ms", "—"),
                p99=row.get("p99_ms", "—"),
                mean=row.get("mean_ms", "—"),
                maxv=row.get("max_ms", "—"),
            )
        )
    lines.append("")
    lines.append("## Code-audit bottlenecks")
    lines.append("")
    for item in doc.get("known_bottlenecks_code_audit") or []:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def measure_file_snapshot_io(path: Optional[Path] = None, iterations: int = 20) -> Dict[str, Any]:
    """Synthetic measurement of atomic JSON snapshot read/write cost."""
    from . import market_data

    target = path or market_data._snapshot_path()
    payload = {
        "version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "series": [
            {
                "key": f"MNQ|5m|{i}",
                "instrument": "MNQ 09-26",
                "timeframe": "5m",
                "status": "live",
                "error": "",
                "bars": [
                    {"t": f"2026-07-16T12:00:{j:02d}Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}
                    for j in range(60)
                ],
            }
            for i in range(8)
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False)
    write_ms: List[float] = []
    read_ms: List[float] = []
    target.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(max(1, iterations)):
        t0 = now_ms()
        tmp = target.with_suffix(target.suffix + ".baseline.tmp")
        tmp.write_text(raw, encoding="utf-8")
        os.replace(tmp, target)
        write_ms.append(now_ms() - t0)
        t1 = now_ms()
        _ = json.loads(target.read_text(encoding="utf-8-sig"))
        read_ms.append(now_ms() - t1)
    for stage, samples in (("baseline.file_write_ms", write_ms), ("baseline.file_read_ms", read_ms)):
        for value in samples:
            mark(stage, value)
    return {
        "path": str(target),
        "bytes": len(raw.encode("utf-8")),
        "iterations": iterations,
        "write": {
            "p50_ms": _percentile(write_ms, 50),
            "p95_ms": _percentile(write_ms, 95),
            "p99_ms": _percentile(write_ms, 99),
        },
        "read": {
            "p50_ms": _percentile(read_ms, 50),
            "p95_ms": _percentile(read_ms, 95),
            "p99_ms": _percentile(read_ms, 99),
        },
    }


def audit_code_path_findings() -> Dict[str, Any]:
    """Static findings from the pre-change architecture (no live NT required)."""
    return {
        "data_flow": [
            "desktop.js UI.poll LIVE_POLL_MS=350",
            "POST /api/ops/runtime/bars/batch",
            "server._market_bars_payload",
            "market_data.register_request → market_data_requests.json",
            "RuntimeMarketDataExporter SyncRequests/Capture*/WriteSnapshot",
            "market_bars.json atomic snapshot",
            "market_data_failover.apply_failover (Databento HTTP / Yahoo)",
            "chart-engine.js full series paint",
        ],
        "callback_path_issues": [
            "CaptureMarketData runs under MarketData.Update and mutates last bar OHLC",
            "CaptureMarketData calls RequestSnapshotWrite (may schedule file I/O)",
            "No bounded event queue; no IPC stream; bars built inside Bridge",
        ],
        "transport": "file JSON snapshots only",
        "ui_statuses": "desktop live/wait/err only (no LIVE/DEGRADED/STALE/RECOVERING)",
        "external_live": "Databento key absent in this environment → Yahoo delayed chart fallback only",
    }
