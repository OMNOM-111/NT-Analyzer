"""AI Lab error / rejection / compile-fail / demo-mismatch / infra-fail logging.

Every record is a single JSONL line. Repeated patterns are surfaced via
``pattern_counts()`` so other modules can apply prevention rules
(validator blocks, mutator caps, scoring penalties).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import paths
from .io_utils import append_jsonl, iter_jsonl, read_json, write_json_atomic

VALID_PHASES = {
    "intake", "memory", "generate", "validate", "compile",
    "restart", "catalog", "backtest", "analyze", "arbitrate",
}
VALID_SEVERITIES = {"info", "warn", "error", "blocker"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(message: str) -> str:
    """Collapse volatile bits (paths, line numbers, hex addresses, GUIDs)."""
    s = message or ""
    s = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<PATH>", s)
    s = re.sub(r"/[^\s\"']+", "<PATH>", s)
    s = re.sub(r"\b0x[0-9a-fA-F]+\b", "<HEX>", s)
    s = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "<GUID>", s)
    s = re.sub(r"\bline \d+\b", "line <N>", s, flags=re.I)
    s = re.sub(r"\(\d+,\d+\)", "(<N>,<N>)", s)
    s = re.sub(r"\b\d+\b", "<N>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:400]


def log_error(
    experiment_id: str,
    phase: str,
    error_type: str,
    raw_message: str,
    severity: str = "error",
    class_name: Optional[str] = None,
    target_root: Optional[str] = None,
    fix_attempt: Optional[str] = None,
    resolved: bool = False,
    lesson_summary: Optional[str] = None,
) -> Dict[str, Any]:
    paths.ensure_dirs()
    if phase not in VALID_PHASES:
        raise ValueError(f"Invalid phase: {phase}")
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"Invalid severity: {severity}")
    rec = {
        "timestamp_utc": _now(),
        "experiment_id": experiment_id,
        "class_name": class_name,
        "target_root": target_root,
        "phase": phase,
        "error_type": error_type,
        "raw_message": (raw_message or "")[:4000],
        "normalized_pattern": _normalize(raw_message),
        "severity": severity,
        "fix_attempt": fix_attempt,
        "resolved": resolved,
        "lesson_summary": lesson_summary,
    }
    append_jsonl(paths.ERROR_LOG_PATH, rec)
    _update_pattern_counts(rec)
    return rec


def log_compile_fail(experiment_id: str, class_name: str, error_text: str, attempt: int) -> Dict[str, Any]:
    rec = {
        "timestamp_utc": _now(),
        "experiment_id": experiment_id,
        "class_name": class_name,
        "attempt": attempt,
        "raw": (error_text or "")[:8000],
        "normalized_pattern": _normalize(error_text),
    }
    append_jsonl(paths.COMPILE_FAIL_PATH, rec)
    return rec


def log_infra_fail(experiment_id: str, phase: str, message: str) -> Dict[str, Any]:
    rec = {
        "timestamp_utc": _now(),
        "experiment_id": experiment_id,
        "phase": phase,
        "message": (message or "")[:4000],
        "normalized_pattern": _normalize(message),
    }
    append_jsonl(paths.INFRA_FAIL_PATH, rec)
    return rec


def log_rejection(experiment_id: str, rejection_code: str, reasons: List[str], structural: bool) -> Dict[str, Any]:
    rec = {
        "timestamp_utc": _now(),
        "experiment_id": experiment_id,
        "rejection_code": rejection_code,
        "reasons": reasons,
        "structural": structural,
    }
    append_jsonl(paths.REJECTED_HYPOTHESES_PATH, rec)
    return rec


def log_demo_mismatch(
    experiment_id: str,
    strategy_family: str,
    instrument: str,
    timeframe: str,
    backtest_signature: Dict[str, Any],
    demo_failure_signature: Dict[str, Any],
    suspected_reasons: List[str],
    confirmed_reasons: Optional[List[str]] = None,
    postmortem_ref: Optional[str] = None,
) -> Dict[str, Any]:
    rec = {
        "timestamp_utc": _now(),
        "experiment_id": experiment_id,
        "strategy_family": strategy_family,
        "instrument": instrument,
        "timeframe": timeframe,
        "backtest_signature": backtest_signature,
        "demo_failure_signature": demo_failure_signature,
        "suspected_reasons": suspected_reasons,
        "confirmed_reasons": confirmed_reasons or [],
        "postmortem_ref": postmortem_ref,
    }
    append_jsonl(paths.DEMO_MISMATCH_PATH, rec)
    return rec


def _update_pattern_counts(rec: Dict[str, Any]) -> None:
    data = read_json(paths.ERROR_PATTERNS_PATH, default={"schema_version": "0.1", "patterns": []}) or {}
    patterns = data.get("patterns", [])
    key = (rec["phase"], rec["error_type"], rec["normalized_pattern"])
    found = None
    for p in patterns:
        if (p.get("phase"), p.get("error_type"), p.get("normalized_pattern")) == key:
            found = p
            break
    if found:
        found["count"] = int(found.get("count", 0)) + 1
        found["last_seen_utc"] = rec["timestamp_utc"]
        examples = found.setdefault("example_experiments", [])
        if rec["experiment_id"] not in examples:
            examples.append(rec["experiment_id"])
            if len(examples) > 10:
                examples.pop(0)
    else:
        patterns.append({
            "phase": rec["phase"],
            "error_type": rec["error_type"],
            "normalized_pattern": rec["normalized_pattern"],
            "count": 1,
            "first_seen_utc": rec["timestamp_utc"],
            "last_seen_utc": rec["timestamp_utc"],
            "example_experiments": [rec["experiment_id"]],
        })
    data["patterns"] = patterns
    write_json_atomic(paths.ERROR_PATTERNS_PATH, data)


def pattern_counts() -> List[Dict[str, Any]]:
    data = read_json(paths.ERROR_PATTERNS_PATH, default={"patterns": []}) or {}
    return data.get("patterns", [])


def top_repeated_patterns(threshold: int = 2) -> List[Dict[str, Any]]:
    return [p for p in pattern_counts() if p.get("count", 0) >= threshold]


def recent_errors(limit: int = 50) -> List[Dict[str, Any]]:
    from .io_utils import tail_jsonl
    return tail_jsonl(paths.ERROR_LOG_PATH, n=limit)


def count_by_phase() -> Dict[str, int]:
    c: Counter = Counter()
    for rec in iter_jsonl(paths.ERROR_LOG_PATH):
        c[rec.get("phase", "unknown")] += 1
    return dict(c)
