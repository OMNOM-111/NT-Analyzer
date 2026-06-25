"""Lesson registry. Lessons distill repeated errors/rejections/user research into
actionable rules that bias future hypothesis selection, mutation, and scoring."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import paths
from .io_utils import append_jsonl, iter_jsonl

VALID_SOURCES = {"error_pattern", "rejection", "user_research", "postmortem", "demo_mismatch"}
VALID_SCOPES = {"global", "instrument", "family", "experiment", "user_research"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lesson_id(summary: str) -> str:
    h = hashlib.sha1(summary.encode("utf-8")).hexdigest()[:10]
    return f"LSN-{h}"


def record_lesson(
    summary: str,
    source: str,
    scope: str = "global",
    scope_key: Optional[str] = None,
    evidence_refs: Optional[List[str]] = None,
    rule: Optional[str] = None,
    weight: float = 1.0,
) -> Dict[str, Any]:
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid lesson source: {source}")
    if scope not in VALID_SCOPES:
        raise ValueError(f"Invalid lesson scope: {scope}")
    rec = {
        "timestamp_utc": _now(),
        "lesson_id": _lesson_id(summary),
        "summary": summary,
        "scope": scope,
        "scope_key": scope_key,
        "source": source,
        "evidence_refs": evidence_refs or [],
        "rule": rule,
        "weight": weight,
    }
    append_jsonl(paths.LESSON_LOG_PATH, rec)
    return rec


def lessons_for(scope: Optional[str] = None, scope_key: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rec in iter_jsonl(paths.LESSON_LOG_PATH):
        if scope and rec.get("scope") != scope:
            continue
        if scope_key and rec.get("scope_key") != scope_key:
            continue
        out.append(rec)
    return out


def all_lessons(limit: int = 200) -> List[Dict[str, Any]]:
    from .io_utils import tail_jsonl
    return tail_jsonl(paths.LESSON_LOG_PATH, n=limit)
