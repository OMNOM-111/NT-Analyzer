"""Anti-duplicate fingerprint registry.

Purpose: prevent two identical strategy clones from being written back-to-back
inside one run, or across recent runs on the same root. We do **not** ban
re-exploring a family — only literal clones (same hypothesis + same entry
keywords + same parameter topology + same indicator set + same source SHA in
the worst case).

Storage: ``ai_lab/registry/strategy_fingerprints.jsonl``. One record per write
attempt (skeleton-written, mutation-written, fallback-template-written).

Decision rule for ``check_anti_duplicate``:
    A new candidate fingerprint is a duplicate if **any** of:
    1. The same fingerprint already appears in the last ``lookback_n`` records
       for the same root.
    2. The fingerprint matches the most recent record overall (immediate repeat).
    3. The hypothesis Jaccard similarity vs any of the last 5 records on the
       same root is > 0.85.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import paths
from .io_utils import append_jsonl


# Indicator vocabulary used to extract a stable indicator-set from C# source.
_INDICATOR_TOKENS = (
    "EMA", "SMA", "WMA", "DEMA", "TEMA", "HMA", "VWMA",
    "RSI", "ADX", "ATR", "VWAP", "MACD", "MIN", "MAX",
    "Bollinger", "BollingerBands", "Stochastics", "KeltnerChannel",
    "DonchianChannel", "PSAR", "CCI", "ROC", "MFI",
)

_ENTRY_KEYWORDS = (
    "EnterLong", "EnterShort", "EnterLongLimit", "EnterShortLimit",
    "EnterLongStopMarket", "EnterShortStopMarket",
    "ExitLong", "ExitShort",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fingerprints_path() -> Path:
    return paths.REGISTRY_DIR / "strategy_fingerprints.jsonl"


def _hypothesis_tokens(text: str) -> Set[str]:
    return {t for t in re.findall(r"[A-Za-z]{4,}", (text or "").lower())}


def _normalize_hypothesis(text: str) -> str:
    return " ".join(sorted(_hypothesis_tokens(text)))


def _extract_indicators(source: str) -> List[str]:
    found: Set[str] = set()
    for tok in _INDICATOR_TOKENS:
        if re.search(rf"\b{tok}\s*\(", source or ""):
            found.add(tok)
    return sorted(found)


def _extract_entry_keywords(source: str) -> List[str]:
    found: Set[str] = set()
    for tok in _ENTRY_KEYWORDS:
        if tok in (source or ""):
            found.add(tok)
    return sorted(found)


def _parameter_topology(parameters: Dict[str, Any]) -> List[str]:
    """Return parameter NAMES (not values) — value drift should NOT bump fp."""
    return sorted(str(k) for k in (parameters or {}).keys())


def fingerprint(
    *,
    family: str,
    hypothesis: str,
    indicators: List[str],
    entry_keywords: List[str],
    param_topology: List[str],
) -> str:
    payload = {
        "family": (family or "").strip(),
        "hypothesis_norm": _normalize_hypothesis(hypothesis),
        "indicators": sorted(indicators),
        "entry_keywords": sorted(entry_keywords),
        "param_topology": sorted(param_topology),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint_for_source(
    *,
    family: str,
    hypothesis: str,
    source: str,
    parameters: Dict[str, Any],
) -> str:
    return fingerprint(
        family=family,
        hypothesis=hypothesis,
        indicators=_extract_indicators(source),
        entry_keywords=_extract_entry_keywords(source),
        param_topology=_parameter_topology(parameters),
    )


def record_fingerprint(
    fp: str,
    *,
    experiment_id: str,
    root: str,
    family: str,
    iteration: int = 1,
    source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    paths.ensure_dirs()
    rec = {
        "ts_utc": _now(),
        "fingerprint": fp,
        "experiment_id": experiment_id,
        "root": root,
        "family": family,
        "iteration": iteration,
        "source_sha256": source_sha256,
    }
    append_jsonl(fingerprints_path(), rec)
    return rec


def _iter_recent(limit: int) -> Iterable[Dict[str, Any]]:
    p = fingerprints_path()
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    out: List[Dict[str, Any]] = []
    for raw in lines[-max(1, limit * 4):]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out[-limit:]


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def check_anti_duplicate(
    fp: str,
    root: str,
    *,
    lookback_n: int = 30,
    hypothesis: Optional[str] = None,
    similarity_threshold: float = 0.85,
) -> Dict[str, Any]:
    """Return ``{ok, conflict?}``.

    ``ok=False`` means the caller (mutation.py / orchestrator) must request a
    different hypothesis instead of writing this one.
    """
    recent = list(_iter_recent(lookback_n))
    # Same fingerprint in the last N records on the same root → duplicate.
    for r in recent:
        if r.get("fingerprint") == fp and r.get("root") == root:
            return {"ok": False, "conflict": {"reason": "same_fingerprint_same_root",
                                              "experiment_id": r.get("experiment_id"),
                                              "iteration": r.get("iteration")}}
    # Immediate repeat (last record, any root) is always a duplicate.
    if recent and recent[-1].get("fingerprint") == fp:
        return {"ok": False, "conflict": {"reason": "immediate_repeat",
                                          "experiment_id": recent[-1].get("experiment_id")}}
    if hypothesis:
        new_tokens = _hypothesis_tokens(hypothesis)
        for r in recent[-5:]:
            old_tokens = _hypothesis_tokens(r.get("hypothesis_norm") or "")
            sim = _jaccard(new_tokens, old_tokens)
            if sim > similarity_threshold and r.get("root") == root:
                return {"ok": False, "conflict": {
                    "reason": "hypothesis_too_similar",
                    "similarity": round(sim, 3),
                    "experiment_id": r.get("experiment_id"),
                }}
    return {"ok": True}


def recent_records(limit: int = 50) -> List[Dict[str, Any]]:
    return list(_iter_recent(limit))
