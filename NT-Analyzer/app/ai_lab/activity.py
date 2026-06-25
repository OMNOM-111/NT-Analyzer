"""Activity log for AI Strategy Lab experiments.

Append-only JSONL per experiment at
``ai_lab/registry/activity/{experiment_id}.jsonl``. The UI polls
``tail(experiment_id, since_line=N)`` every 2s; the line-number cursor avoids
clock-skew and dedup issues.

Never echo full model chain-of-thought. Prompt previews must be the system
prompt or a one-line user instruction, capped at 200 chars. Response summaries
must be the model's final answer summary, capped at 200 chars.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from . import paths

STAGES = {
    "intake", "generate", "validate", "write", "compile", "catalog",
    "signal_sanity", "backtest", "analyze", "arbitrate", "verdict",
    "runner", "status",
}

LEVELS = {"info", "warn", "error", "success"}

_EID_RE = re.compile(r"^EXP-\d{8}-\d{4}$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_for(experiment_id: str):
    if not _EID_RE.match(experiment_id):
        raise ValueError(f"invalid experiment_id: {experiment_id}")
    paths.ACTIVITY_DIR.mkdir(parents=True, exist_ok=True)
    return paths.ACTIVITY_DIR / f"{experiment_id}.jsonl"


def _truncate(value: Any, limit: int = 200) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


def log(
    experiment_id: str,
    stage: str,
    action: str,
    *,
    level: str = "info",
    **fields: Any,
) -> int:
    """Append one entry; return the new line number (1-indexed)."""
    if stage not in STAGES:
        raise ValueError(f"invalid stage: {stage}")
    if level not in LEVELS:
        raise ValueError(f"invalid level: {level}")
    p = _path_for(experiment_id)
    safe_fields = {k: _truncate(v) for k, v in fields.items()}
    rec = {
        "ts": _now(),
        "stage": stage,
        "action": action,
        "level": level,
        **safe_fields,
    }
    # Append + count lines in one open. Avoids race between append and count
    # for the common single-writer case (the runner thread).
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(p, "rb") as fh:
        line_no = sum(1 for _ in fh)
    return line_no


def tail(
    experiment_id: str,
    since_line: int = 0,
    limit: int = 500,
) -> Dict[str, Any]:
    """Return entries with line index > since_line, capped at limit."""
    p = _path_for(experiment_id)
    if not p.exists():
        return {"entries": [], "next_line": 0, "total_lines": 0}
    entries: List[Dict[str, Any]] = []
    total = 0
    with open(p, "r", encoding="utf-8") as fh:
        for i, raw in enumerate(fh, start=1):
            total = i
            if i <= since_line:
                continue
            if len(entries) >= limit:
                continue
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                rec = {"ts": "", "stage": "runner", "action": "parse_error", "level": "warn", "raw": line[:200]}
            rec["line"] = i
            entries.append(rec)
    next_line = entries[-1]["line"] if entries else since_line
    return {"entries": entries, "next_line": next_line, "total_lines": total}


def total_lines(experiment_id: str) -> int:
    p = _path_for(experiment_id)
    if not p.exists():
        return 0
    with open(p, "rb") as fh:
        return sum(1 for _ in fh)
