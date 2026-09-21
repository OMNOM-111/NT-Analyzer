"""Evidence-shaped memory retrieval metrics; no claims without observations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

from .states import ContractError


def observation(*, task_id: str, context_package: Mapping[str, object], succeeded: bool | None,
                observed_at: datetime | None = None, irrelevant_score: float = .10,
                stale_after_days: int = 180) -> dict:
    if not isinstance(task_id, str) or not task_id or not isinstance(context_package, Mapping):
        raise ContractError("memory_metric_input_invalid")
    if succeeded is not None and type(succeeded) is not bool:
        raise ContractError("memory_metric_input_invalid")
    if not isinstance(irrelevant_score, (int, float)) or not 0 <= irrelevant_score <= 1:
        raise ContractError("memory_metric_input_invalid")
    if type(stale_after_days) is not int or not 1 <= stale_after_days <= 3650:
        raise ContractError("memory_metric_input_invalid")
    stamp = observed_at or datetime.now(timezone.utc)
    if stamp.utcoffset() != timedelta(0):
        raise ContractError("utc_required")
    entries = context_package.get("entries") or []
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ContractError("memory_metric_input_invalid")
    cutoff = stamp - timedelta(days=stale_after_days)
    stale, irrelevant = 0, 0
    for row in entries:
        irrelevant += float(row.get("score") or 0) < irrelevant_score
        try:
            updated = datetime.fromisoformat(str(row.get("updated_at_utc") or "").replace("Z", "+00:00"))
        except ValueError:
            updated = datetime.min.replace(tzinfo=timezone.utc)
        stale += updated < cutoff
    count = len(entries)
    return {"schema_version": "memory-retrieval-observation-v1", "task_id": task_id,
        "observed_at": stamp.isoformat().replace("+00:00", "Z"), "memory_used": count > 0,
        "context_tokens": int(context_package.get("estimated_tokens") or 0),
        "selected_count": count, "candidate_count": int(context_package.get("candidate_count") or 0),
        "irrelevant_count": irrelevant, "irrelevant_rate": irrelevant / count if count else None,
        "stale_count": stale, "stale_rate": stale / count if count else None,
        "conflict_count": int(context_package.get("conflict_count") or 0), "succeeded": succeeded}


def summarize(observations: Iterable[Mapping[str, object]]) -> dict:
    rows = list(observations)
    if any(not isinstance(row, Mapping)
           or row.get("schema_version") != "memory-retrieval-observation-v1" for row in rows):
        raise ContractError("memory_metric_observation_invalid")

    def cohort(memory_used):
        values = [row for row in rows if row.get("memory_used") is memory_used]
        outcomes = [row["succeeded"] for row in values if type(row.get("succeeded")) is bool]
        return {"tasks": len(values), "measured_outcomes": len(outcomes),
            "success_rate": sum(outcomes) / len(outcomes) if outcomes else None}

    selected = sum(int(row.get("selected_count") or 0) for row in rows)
    return {"schema_version": "memory-evaluation-summary-v1", "observations": len(rows),
        "context_tokens": sum(int(row.get("context_tokens") or 0) for row in rows),
        "selected_facts": selected,
        "irrelevant_rate": (sum(int(row.get("irrelevant_count") or 0) for row in rows) / selected
                            if selected else None),
        "stale_rate": (sum(int(row.get("stale_count") or 0) for row in rows) / selected
                       if selected else None),
        "conflicts": sum(int(row.get("conflict_count") or 0) for row in rows),
        "with_memory": cohort(True), "without_memory": cohort(False)}
