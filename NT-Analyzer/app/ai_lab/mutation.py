"""In-cell mutation: derive a new hypothesis/code from the prior iteration.

The runner's *inner loop* calls :func:`prepare_next` after a reject/mutate
verdict. The result is a new strategy version inside the **same** AI-CELL —
same ``class_name``, same ``experiment_id``, but a new hypothesis, new ``.cs``
content, and a new sha256.

Versioning policy (decided 2026-06-17):
    one ``class_name`` per AI-CELL. We keep ``current.cs`` as the only file
    NinjaTrader compiles; previous iterations are copied to
    ``ai_lab/mirrors/{ai_cell_id}/history/v{N}.cs`` for audit and prompt diffs.

Mutation prompt requirements:
    * include the previous hypothesis, family, indicator set, PF, trade count,
      rejection_code, signal_sanity diff;
    * explicitly forbid trivial parameter tweaks ("change hypothesis and
      filter, not just BreakoutLookback/SL/TP");
    * if uniqueness gate marks the candidate as a duplicate, retry up to 3
      times with stronger anti-duplicate instructions.

The mutation module never writes to the production strategies path; all writes
go through :func:`generator.write_to_sandbox`, which already enforces the
sandbox guard.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import activity, paths, registry


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def history_dir(ai_cell_id: str) -> Path:
    d = paths.MIRRORS_DIR / ai_cell_id / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_current_version(exp: Dict[str, Any], iteration_idx: int) -> Optional[Path]:
    """Copy the current sandbox .cs into mirrors/{cell_id}/history/v{N}.cs."""
    ai_cell_id = exp.get("ai_cell_id") or ""
    if not ai_cell_id:
        return None
    src_path_str = (exp.get("strategy_source") or {}).get("sandbox_path") or \
                   (exp.get("strategy_source") or {}).get("mirror_path")
    if not src_path_str:
        return None
    src = Path(src_path_str)
    if not src.exists():
        return None
    target = history_dir(ai_cell_id) / f"v{iteration_idx}.cs"
    try:
        shutil.copy2(src, target)
    except OSError:
        return None
    return target


def build_mutation_prompt(
    exp: Dict[str, Any],
    *,
    prev_iteration_idx: int,
) -> str:
    """Compose a mutation user prompt with prior-iteration diff."""
    family = exp.get("family") or "?"
    hypothesis = exp.get("hypothesis") or ""
    analysis = exp.get("analysis") or {}
    sanity = exp.get("signal_sanity") or {}
    verdict = exp.get("verdict") or {}
    arb = exp.get("arbitration") or {}
    history = exp.get("iteration_history") or []
    prev_versions = "\n".join(
        f"- v{h.get('iteration')}: status={h.get('status')}, "
        f"verdict={h.get('verdict')}, code={h.get('rejection_code')}, "
        f"pf={h.get('pf_after_commission')}, trades={h.get('trades_total')}"
        for h in history[-6:]
    )
    parts = [
        "MUTATION TASK (in-cell iteration).",
        f"AI Cell: {exp.get('ai_cell_id')} (class {exp.get('class_name')})",
        f"Target root: {exp.get('target_root')}",
        f"Previous iteration index: {prev_iteration_idx}",
        f"Previous family: {family}",
        f"Previous hypothesis: {hypothesis[:600]}",
        "",
        "Previous iteration outcome:",
        f"- status: {exp.get('status')}",
        f"- verdict: {verdict.get('outcome')} ({verdict.get('rejection_code')})",
        f"- arbitration score: {arb.get('score')}",
        f"- trades_total: {analysis.get('trades_total')}",
        f"- pf_after_commission: {analysis.get('pf_after_commission')}",
        f"- monthly_growth_pct: {analysis.get('monthly_growth_pct')}",
        f"- signal_sanity: {sanity.get('reason')} (theoretical={sanity.get('theoretical_signals')})",
        "",
        "Iteration history:",
        prev_versions or "- (none)",
        "",
        "Hard mutation rules:",
        "- Change hypothesis and entry filter, not only BreakoutLookback/SL/TP/MaxTradesPerDay.",
        "- Keep the same class_name and namespace (this is an in-cell iteration).",
        "- Must improve on the specific rejection_code above; explain in a Russian comment header what changed.",
        "- Respect every hard constraint and acceptance gate from the knowledge context.",
        "- If the previous iteration produced 0 trades, change setup conditions (timeframe, lookback regime, filter), not only thresholds.",
        "- If PF after commission < 1.0, propose either a new filter or a different time-of-day window — do not just tighten stops.",
        "- Keep C# identifiers, NinjaTrader API names, property names, and error codes in English.",
        "- Write all human-readable explanation comments in Russian.",
        "",
        "Return ONE corrected NT8 C# strategy in a ```csharp fence.",
    ]
    return "\n".join(parts)


def _read_current_source(exp: Dict[str, Any]) -> str:
    src_path = (exp.get("strategy_source") or {}).get("sandbox_path") or \
               (exp.get("strategy_source") or {}).get("mirror_path")
    if not src_path:
        return ""
    try:
        return Path(src_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def prepare_next(experiment_id: str, prev_iteration_idx: int) -> Dict[str, Any]:
    """Generate the next in-cell iteration and rewrite the sandbox .cs.

    Returns a dict with ``ok`` and either ``new_sha256`` / ``mirror_history_path``
    on success or ``error`` on failure. The runner consumes this and re-runs
    ``orchestrator.run_pipeline`` on the same experiment_id afterwards.
    """
    exp = registry.read_experiment(experiment_id)
    if exp is None:
        return {"ok": False, "error": f"experiment not found: {experiment_id}"}

    next_iter = int(prev_iteration_idx) + 1
    class_name = exp.get("class_name") or ""
    ai_cell_id = exp.get("ai_cell_id") or ""
    if not class_name or not ai_cell_id:
        return {"ok": False, "error": "experiment missing class_name/ai_cell_id"}

    # 1) Archive the previous version into mirrors history.
    mirror_path = archive_current_version(exp, prev_iteration_idx)

    # 2) Build a mutation context for the next normal judge/coder pass.
    # The runner will call orchestrator.run_pipeline again.  Do not generate
    # source here as well, otherwise that source is immediately overwritten by
    # the next judge/coder pass and two expensive model calls are wasted.
    prior_source = _read_current_source(exp)
    user_prompt = build_mutation_prompt(exp, prev_iteration_idx=prev_iteration_idx)
    activity.log(
        experiment_id, "generate", "mutation_prompt",
        level="info", iteration=next_iter,
        prompt_preview="Prepare the next iteration: change hypothesis and filter, not only risk parameters.",
        prompt_preview_ru="Подготовить следующую итерацию: изменить гипотезу и фильтр, а не только параметры риска.",
    )

    # 3) Reset orchestrator-driving fields for the next pipeline call.
    exp = registry.read_experiment(experiment_id) or exp
    exp["mirror_history_dir"] = str(history_dir(ai_cell_id))
    exp["current_iteration"] = next_iter
    exp["pending_mutation_context"] = (
        user_prompt
        + "\n\n// --- previous source (rewrite this strategy) ---\n"
        + prior_source[:8000]
    )
    history = list(exp.get("iteration_history") or [])
    history.append({
        "iteration": next_iter,
        "sha256": None,
        "verdict": None,
        "rejection_code": None,
        "status": "mutation_planned",
        "mirror_history_path": str(mirror_path) if mirror_path else None,
        "created_utc": _now(),
        "mutation_of_iteration": prev_iteration_idx,
    })
    exp["iteration_history"] = history
    # Re-arm the pipeline so the next orchestrator run validates+compiles
    # the new source. We bring the status back to "generated"; the
    # orchestrator's compile chain will continue from there.
    exp["status"] = "generated"
    exp["compile"] = exp.get("compile") or {}
    exp["compile"]["attempts"] = 0
    exp["compile"]["last_status"] = None
    exp["backtests"] = []
    exp["analysis"] = {}
    exp["arbitration"] = {}
    exp["signal_sanity"] = {}
    exp["execution_sanity"] = {}
    exp.pop("compile_result", None)
    exp["verdict"] = {}
    try:
        registry.write_experiment(exp)
    except Exception as we:  # noqa: BLE001
        return {"ok": False, "error": f"write_experiment failed: {we}"}

    activity.log(
        experiment_id, "generate", "mutation_planned",
        level="success", iteration=next_iter,
        mirror_history_path=str(mirror_path) if mirror_path else None,
    )
    return {
        "ok": True,
        "iteration": next_iter,
        "pending_context": True,
        "mirror_history_path": str(mirror_path) if mirror_path else None,
    }
