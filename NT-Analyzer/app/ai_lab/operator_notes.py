"""Live operator notes for in-flight AI experiments.

The operator can POST extra instructions while an experiment is running.
Notes are appended to ``ai_lab/registry/operator_notes/{experiment_id}.jsonl``
and consumed by the orchestrator at every checkpoint (judge / coder /
autofix / compile retry / backtest submit / arbitration).

A note arriving mid-LM call is NOT lost: it stays pending until the next
checkpoint reads it. Notes never abort the in-flight HTTP request.

Global memory promotion: notes with ``priority="high"`` or text containing one
of the keywords below are also appended to
``ai_lab/registry/global_operator_notes.jsonl``. ``knowledge.build_context``
reads the last 20 global notes so a rule typed once is visible to every later
strategy on every later run.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import activity, paths


_VALID_PRIORITIES = {"low", "normal", "high"}

# Hits on these substrings (case-insensitive) auto-promote a note to global
# memory. Keep the list short and high-precision; users can always pass
# ``priority="high"`` or ``scope_global=True`` to force promotion.
_GLOBAL_PROMOTION_KEYWORDS = (
    "ошибк",       # ошибка/ошибки
    "не повтор",   # не повторяй
    "запрет",      # запрет/запрещено
    "никогда",
    "always",
    "never",
    "avoid",
    "fix:",
    "rule:",
    "правило",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _notes_dir() -> Path:
    d = paths.REGISTRY_DIR / "operator_notes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path_for(experiment_id: str) -> Path:
    return _notes_dir() / f"{experiment_id}.jsonl"


def _load(experiment_id: str) -> List[Dict[str, Any]]:
    p = _path_for(experiment_id)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return out


def _save_all(experiment_id: str, entries: List[Dict[str, Any]]) -> None:
    p = _path_for(experiment_id)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    tmp.replace(p)


def add(experiment_id: str, text: str, priority: str = "normal",
        scope_global: bool = False) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("operator note text cannot be empty")
    if priority not in _VALID_PRIORITIES:
        priority = "normal"
    entry = {
        "ts_utc": _now(),
        "text": text[:4000],
        "priority": priority,
        "applied_at_stage": None,
        "applied_at_ts_utc": None,
    }
    p = _path_for(experiment_id)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    entry["index"] = sum(1 for _ in p.open("r", encoding="utf-8")) - 1

    # Promote to global memory when caller asked, priority=high, or text
    # matches the curated keyword list.
    text_lower = text.lower()
    auto_promote = any(k in text_lower for k in _GLOBAL_PROMOTION_KEYWORDS)
    if scope_global or priority == "high" or auto_promote:
        try:
            promote_to_global(
                text=text, priority=priority,
                source_experiment_id=experiment_id,
                trigger="explicit" if scope_global else (
                    "priority_high" if priority == "high" else "keyword"
                ),
            )
            entry["promoted_to_global"] = True
        except Exception:
            entry["promoted_to_global"] = False
    return entry


def global_notes_path() -> Path:
    return paths.REGISTRY_DIR / "global_operator_notes.jsonl"


def promote_to_global(
    *, text: str, priority: str = "normal",
    source_experiment_id: Optional[str] = None,
    trigger: str = "explicit",
) -> Dict[str, Any]:
    """Append a global operator note. Safe to call from add() or manual API."""
    paths.ensure_dirs()
    p = global_notes_path()
    rec = {
        "ts_utc": _now(),
        "text": (text or "").strip()[:4000],
        "priority": priority if priority in _VALID_PRIORITIES else "normal",
        "source_experiment_id": source_experiment_id,
        "trigger": trigger,
    }
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_global_notes(limit: int = 20) -> List[Dict[str, Any]]:
    p = global_notes_path()
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return out[-limit:]


def list_all(experiment_id: str) -> List[Dict[str, Any]]:
    return _load(experiment_id)


def pending(experiment_id: str) -> List[Dict[str, Any]]:
    return [e for e in _load(experiment_id) if not e.get("applied_at_stage")]


def mark_applied(experiment_id: str, indexes: List[int], stage: str) -> None:
    entries = _load(experiment_id)
    if not entries:
        return
    # `indexes` references positions in the *pending* list at the time the
    # caller pulled it. Map those to absolute indexes so we don't touch
    # already-applied entries.
    pending_abs = [i for i, e in enumerate(entries) if not e.get("applied_at_stage")]
    ts = _now()
    for rel in indexes:
        if 0 <= rel < len(pending_abs):
            entries[pending_abs[rel]]["applied_at_stage"] = stage
            entries[pending_abs[rel]]["applied_at_ts_utc"] = ts
    _save_all(experiment_id, entries)


def render_for_prompt(experiment_id: str, max_chars: int = 1200) -> str:
    return render_entries(pending(experiment_id), max_chars=max_chars)


def render_entries(notes: List[Dict[str, Any]], max_chars: int = 1200) -> str:
    """Render an explicit note batch, including notes just marked applied."""
    if not notes:
        return ""
    lines = ["## OPERATOR NOTES (newest last)"]
    for n in notes:
        prio = n.get("priority") or "normal"
        ts = n.get("ts_utc") or ""
        lines.append(f"- [{prio}] {ts} {n.get('text','')}")
    text = "\n".join(lines)
    # Truncate from the start (oldest) when too long, but keep the header.
    if len(text) <= max_chars:
        return text
    head = lines[0]
    body = lines[1:]
    while body and len("\n".join([head] + body)) > max_chars:
        body.pop(0)
    return "\n".join([head] + body)


def apply_checkpoint(experiment_id: str, stage: str) -> List[Dict[str, Any]]:
    """Pull pending notes and mark them applied; log to activity."""
    pend = pending(experiment_id)
    if not pend:
        return []
    try:
        activity.log(
            experiment_id,
            "runner",
            "operator_note_applied",
            level="info",
            count=len(pend),
            applied_stage=stage,
            preview=str([p["text"][:80] for p in pend])[:200],
        )
    except Exception:
        pass
    mark_applied(experiment_id, list(range(len(pend))), stage)
    return pend
