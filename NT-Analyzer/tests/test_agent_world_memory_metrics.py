from datetime import datetime, timezone

from app.ai_control_center.memory_metrics import observation, summarize


NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def test_metrics_measure_tokens_relevance_staleness_conflicts_and_ab_cohorts():
    packet = {"estimated_tokens": 120, "candidate_count": 5, "conflict_count": 1, "entries": [
        {"score": .8, "updated_at_utc": "2026-09-20T00:00:00Z"},
        {"score": .05, "updated_at_utc": "2025-01-01T00:00:00Z"},
    ]}
    with_memory = observation(task_id="T1", context_package=packet, succeeded=True, observed_at=NOW)
    without = observation(task_id="T2", context_package={"entries": []}, succeeded=False, observed_at=NOW)
    summary = summarize([with_memory, without])
    assert with_memory["context_tokens"] == 120
    assert with_memory["irrelevant_rate"] == with_memory["stale_rate"] == .5
    assert summary["conflicts"] == 1
    assert summary["with_memory"]["success_rate"] == 1
    assert summary["without_memory"]["success_rate"] == 0
