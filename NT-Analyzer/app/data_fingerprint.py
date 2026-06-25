"""Real historical_data_fingerprint, computed from the bars a backtest used.

The NinjaTrader bridge now computes this natively (sha256 of the primary bar
series) and folds it into run_hash. For runs produced by an older loaded AddOn
(which emitted ``placeholder``), this module recomputes the identical-in-spirit
fingerprint from the job's ``bars.json`` artifact — the exact OHLCV series the
backtest consumed — so no judged run is left with a placeholder fingerprint.

sha256 over bars.json is reproducible and proves which data drove the run: if
NinjaTrader re-downloads/repairs history, the bars (and thus the fingerprint)
change even when the run_hash inputs do not.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional


def sha256_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def fingerprint_from_bars_file(bars_path: Path) -> Optional[Dict[str, Any]]:
    """Compute a real data fingerprint from a bars.json artifact.

    Returns None when the artifact is missing or empty so callers can keep the
    placeholder honestly instead of inventing a hash.
    """
    try:
        raw = bars_path.read_bytes()
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        bars = json.loads(raw)
        bar_count = len(bars) if isinstance(bars, list) else None
    except ValueError:
        bar_count = None
    return {
        "method": "sha256_of_bars_json_artifact",
        "value": sha256_of_bytes(raw),
        "bar_count": bar_count,
        "files": [bars_path.name],
        "source": "post_hoc_from_artifact",
    }


def fingerprint_for_job(job_dir: Path) -> Dict[str, Any]:
    """Real fingerprint for a job dir, or an explicit placeholder marker."""
    fp = fingerprint_from_bars_file(job_dir / "bars.json")
    if fp is not None:
        return fp
    return {"method": "placeholder", "value": "sha256:placeholder",
            "bar_count": None, "files": [], "source": "no_bars_artifact"}


def backfill_job(job_dir: Path) -> Dict[str, Any]:
    """Write a data_fingerprint.json sidecar next to a job's artifacts.

    Does not rewrite result.json (which is the immutable bridge output); the
    sidecar records the real fingerprint and whether the run_hash already
    included it.
    """
    fp = fingerprint_for_job(job_dir)
    result = {}
    rp = job_dir / "result.json"
    if rp.is_file():
        try:
            result = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {}
    ctx = (result.get("context") or {})
    embedded = (ctx.get("historical_data_fingerprint") or {})
    embedded_real = str(embedded.get("method") or "") not in ("", "placeholder")
    sidecar = {
        "job_id": result.get("job_id") or job_dir.name,
        "run_hash": result.get("run_hash"),
        "historical_data_fingerprint": fp,
        "run_hash_includes_fingerprint": embedded_real,
        "note": ("run_hash already includes a real fingerprint" if embedded_real
                 else "run_hash predates real fingerprint; sidecar value proves the data used"),
    }
    (job_dir / "data_fingerprint.json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar
