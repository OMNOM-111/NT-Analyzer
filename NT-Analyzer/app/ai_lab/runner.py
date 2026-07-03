"""Single-flight async runner for AI Strategy Lab pipelines.

Owns the daemon thread that drives ``orchestrator.run_pipeline``. Exposes
``start(args)`` which is single-flight: if a pipeline is already in a
non-terminal status, raises :class:`RunnerBusy`.

The runner also polls ``jobs/done/{job_id}/result.json`` after a backtest is
submitted, so the orchestrator's ``finalize_backtest`` is called automatically
when results land — no UI button required.

Two independent loops live here:

- **Outer loop** (`strategy_count`): each iteration creates a fresh
  experiment via ``orchestrator.start_skeleton`` — different AI-CELL ids,
  different ``class_name``, different ``.cs`` file.
- **Inner loop** (`iterations_per_strategy`): within one experiment, when
  the verdict is reject/mutate, the runner calls ``mutation.prepare_next``
  and ``orchestrator.run_pipeline_iteration`` again — same ``class_name``,
  new hypothesis/code, history versioned in ``mirrors/{cell_id}/history``.

Both loops honour cancel and the shared deadline (``max_total_runtime_minutes``).
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import activity, backtest, paths, registry
from .io_utils import write_json_atomic


def _api_snap(state: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow copy safe for JSON responses (drops threading primitives)."""
    return {k: v for k, v in state.items() if k != "cancel_event"}


class RunnerBusy(Exception):
    def __init__(self, current: Dict[str, Any]):
        super().__init__(f"runner busy: {current.get('experiment_id')}")
        self.current = _api_snap(current)


class RunBlockedLMStudio(Exception):
    """Raised by start() when the LM Studio preflight gate refuses to run.

    Carries a ``preflight`` payload (``missing_roles``, ``role_health``) so
    the HTTP layer can return a structured 409 to the UI.
    """

    def __init__(self, preflight: Dict[str, Any]):
        self.preflight = preflight
        super().__init__(
            "LM Studio preflight failed: " + ", ".join(
                str(m.get("role")) for m in preflight.get("missing_roles", [])
            )
        )


_LOCK = threading.Lock()
_CURRENT: Optional[Dict[str, Any]] = None
_THREAD: Optional[threading.Thread] = None

# Run-level state shared across outer/inner loops. Updated under _LOCK.
_RUN_STATE: Optional[Dict[str, Any]] = None

_FINALIZE_MAX_WAIT_SEC = 1800  # 30 min upper bound on waiting for result.json
_FINALIZE_POLL_SEC = 5

_STRUCTURAL_BREAKER_CODES = {
    "STAGED_DESIGN_FAILED", "PIPELINE_EXCEPTION", "SMOKE_DATA_UNVERIFIED",
    "FULL_DATA_UNVERIFIED", "FULL_DATA_INSUFFICIENT", "BLOCKED_LM_STUDIO",
}


def _failure_signature(exp: Dict[str, Any]) -> str:
    verdict = exp.get("verdict") if isinstance(exp.get("verdict"), dict) else {}
    code = str(verdict.get("rejection_code") or "").strip()
    if code:
        return code
    status = str(exp.get("status") or "").strip()
    return status if status.endswith(("_failed", "_timeout")) else ""


def _breaker_threshold(signature: str) -> int:
    if signature in _STRUCTURAL_BREAKER_CODES or signature.endswith(("_failed", "_timeout")):
        return 2
    if signature == "SMOKE_ZERO_TRADES":
        return 5
    return 0


def _notify_circuit_breaker(experiment_id: str, signature: str, count: int) -> None:
    try:
        from .. import telegram_service
        telegram_service.send_chief_report(
            "Работа остановлена защитой",
            [
                "Дмитрий Сергеевич, остановил новые запуски: повторяется одна системная ошибка.",
                "Проверяю причину; новые стратегии и платные запросы пока не запускаю.",
            ],
            urgent=True,
            model_name="deterministic safety circuit breaker",
        )
    except Exception:
        pass
    activity.log(
        experiment_id, "safety", "circuit_breaker_open", level="error",
        signature=signature, repeated=count,
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current() -> Optional[Dict[str, Any]]:
    """Return running pipeline info, or None if idle.

    The returned dict is a shallow copy so callers can safely serialize it.
    """
    with _LOCK:
        if _CURRENT is None:
            return None
        snap = _api_snap(_CURRENT)
        exp = registry.read_experiment(_CURRENT["experiment_id"])
        if exp:
            if registry.is_terminal(exp.get("status", "draft")):
                return None
            snap.update({
                "ai_cell_id": exp.get("ai_cell_id"),
                "class_name": exp.get("class_name"),
                "target_root": exp.get("target_root"),
                "status": exp.get("status"),
            })
        return snap


def cancel_event_for(experiment_id: str) -> Optional[threading.Event]:
    with _LOCK:
        if _CURRENT is None:
            return None
        if _CURRENT.get("experiment_id") != experiment_id:
            return None
        return _CURRENT.get("cancel_event")


def is_cancelled(experiment_id: Optional[str] = None) -> bool:
    with _LOCK:
        if _CURRENT is None:
            return False
        if experiment_id is not None and _CURRENT.get("experiment_id") != experiment_id:
            return False
        ev = _CURRENT.get("cancel_event")
        return bool(ev and ev.is_set())


def request_cancel(experiment_id: str) -> Dict[str, Any]:
    with _LOCK:
        if _CURRENT is None or _CURRENT.get("experiment_id") != experiment_id:
            return {"ok": False, "cancelled": False, "reason": "not current"}
        ev = _CURRENT.get("cancel_event")
        if ev is None:
            return {"ok": False, "cancelled": False, "reason": "no cancel event"}
        already = ev.is_set()
        ev.set()
    if not already:
        try:
            activity.log(experiment_id, "runner", "cancel_requested", level="warn")
        except Exception:
            pass
    return {"ok": True, "cancelled": True, "experiment_id": experiment_id, "already": already}


def _is_busy_locked() -> bool:
    if _CURRENT is None:
        return False
    exp = registry.read_experiment(_CURRENT["experiment_id"])
    if exp is None:
        return False
    return not registry.is_terminal(exp.get("status", "draft"))


def start(args: Dict[str, Any]) -> Dict[str, Any]:
    """Single-flight entry. Returns ``{experiment_id, status, queued, run_id}``.

    Raises :class:`RunnerBusy` if another pipeline is still running.
    Raises :class:`RunBlockedLMStudio` if the LM Studio preflight gate fails
    and the caller did not opt in to ``allow_template_fallback`` (or set
    ``use_llm=False``). In that case **no** experiment is created.
    """
    global _CURRENT, _THREAD, _RUN_STATE

    from . import orchestrator  # lazy import to avoid cycle at import time
    from . import bootstrap, lm_studio  # lazy import; preflight only used at run start

    # Normalize the new outer/inner schema. ``strategy_count`` (outer) and
    # ``iterations_per_strategy`` (inner) are the canonical names; the
    # legacy ``max_cells_per_run`` / ``max_mutations_per_cell`` are still
    # accepted for backward compat by the HTTP layer, which translates them.
    strategy_count = max(1, min(10, int(args.get("strategy_count")
                                        or args.get("max_cells_per_run") or 1)))
    iterations_unlimited = bool(args.get("iterations_unlimited", False))
    raw_iters = args.get("iterations_per_strategy")
    if raw_iters in (None, "", 0):
        # Legacy mapping: max_mutations_per_cell is "extra" iterations
        # beyond the first attempt, so total iterations = mutations + 1.
        legacy = args.get("max_mutations_per_cell")
        if legacy not in (None, ""):
            iterations_per_strategy = max(1, min(20, int(legacy) + 1))
        else:
            iterations_per_strategy = 1
    else:
        iterations_per_strategy = max(1, min(20, int(raw_iters)))
    if iterations_unlimited:
        iterations_per_strategy = None  # type: ignore[assignment]
    raw_runtime = args.get("max_total_runtime_minutes")
    if raw_runtime in (None, "", 0):
        runtime_minutes: Optional[int] = None
    else:
        runtime_minutes = max(1, min(1440, int(raw_runtime)))
    use_llm = bool(args.get("use_llm", True))
    allow_template_fallback = bool(args.get("allow_template_fallback", False))
    stop_on_first_candidate = bool(args.get("stop_on_first_candidate", False))

    args = dict(args)
    args["strategy_count"] = strategy_count
    args["iterations_per_strategy"] = iterations_per_strategy
    args["iterations_unlimited"] = iterations_unlimited
    args["max_total_runtime_minutes"] = runtime_minutes
    args["allow_template_fallback"] = allow_template_fallback
    args["stop_on_first_candidate"] = stop_on_first_candidate
    # Keep legacy field populated so orchestrator.start_skeleton still serializes it.
    args["max_cells_per_run"] = strategy_count

    # Reject a concurrent start before any LM Studio traffic.  The preflight
    # can take minutes on local models; running it for a request that cannot
    # start both delays the 409 response and competes with the active model
    # generation.  Keep the second check below as the race-safe gate after
    # preflight.
    with _LOCK:
        if _is_busy_locked():
            assert _CURRENT is not None
            raise RunnerBusy(_CURRENT)

    bootstrap_result: Dict[str, Any] = {"skipped": True}
    if (
        use_llm
        and not allow_template_fallback
        and not bool(args.get("dry_run", False))
        and bootstrap.auto_bootstrap_enabled()
    ):
        bootstrap_result = bootstrap.start(load_models=False, wait_readiness=False)

    # LM Studio hard gate — first thing, BEFORE start_skeleton, so a failed
    # preflight leaves zero experiments behind.
    preflight: Dict[str, Any] = {"ok": True, "skipped": True}
    if use_llm and not allow_template_fallback and not bool(args.get("dry_run", False)):
        if lm_studio.lazy_mode_enabled():
            try:
                h = lm_studio.lm_status(allow_probe=False)
                missing = h.get("missing_run_roles") or []
                preflight = {
                    "ok": bool(h.get("available")) and not missing,
                    "missing_roles": missing,
                    "checked_via": "models_list_lazy_no_chat",
                    "base_url": h.get("base_url"),
                    "checked_at_utc": _now(),
                    "lazy_mode": True,
                }
            except Exception as e:  # noqa: BLE001
                preflight = {"ok": False, "missing_roles": [
                    {"role": "judge", "reason": "lazy_preflight_exception", "error": str(e)},
                ], "error": str(e), "lazy_mode": True}
        else:
            try:
                preflight = lm_studio.preflight_all_required_roles(
                    list(lm_studio.RUN_REQUIRED_ROLES), purpose="runner_preflight",
                )
            except Exception as e:  # noqa: BLE001
                preflight = {"ok": False, "missing_roles": [
                    {"role": "judge", "reason": "preflight_exception", "error": str(e)},
                ], "error": str(e)}
        if not preflight.get("ok"):
            _write_run_log("preflight_blocked", preflight=preflight, bootstrap=bootstrap_result)
            raise RunBlockedLMStudio(preflight)

    with _LOCK:
        if _is_busy_locked():
            assert _CURRENT is not None
            raise RunnerBusy(dict(_CURRENT))

        run_id = "RUN-" + uuid.uuid4().hex[:12]
        deadline = (
            time.time() + runtime_minutes * 60 if runtime_minutes is not None else None
        )

        skeleton = orchestrator.start_skeleton(args)
        experiment_id = skeleton["experiment_id"]
        cancel_event = threading.Event()
        _CURRENT = {
            "experiment_id": experiment_id,
            "ai_cell_id": skeleton.get("ai_cell_id"),
            "class_name": skeleton.get("class_name"),
            "target_root": skeleton.get("target_root"),
            "status": skeleton.get("status"),
            "started_at_utc": _now(),
            "cancel_event": cancel_event,
            "run_id": run_id,
        }
        _RUN_STATE = {
            "run_id": run_id,
            "started_utc": _now(),
            "strategy_count": strategy_count,
            "iterations_per_strategy": iterations_per_strategy,
            "iterations_unlimited": iterations_unlimited,
            "max_total_runtime_minutes": runtime_minutes,
            "deadline_epoch": deadline,
            "strategy_idx": 1,
            "iteration_idx": 1,
            "current_experiment_id": experiment_id,
            "experiments": [experiment_id],
            "candidate_count": 0,
            "cancelled": False,
            "stop_on_first_candidate": stop_on_first_candidate,
            "use_llm": use_llm,
            "allow_template_fallback": allow_template_fallback,
            "preflight": preflight,
            "bootstrap": bootstrap_result,
            "llm_efficiency": {
                "lazy_mode": lm_studio.lazy_mode_enabled(),
                "reuse_loaded_model": lm_studio.reuse_loaded_model_enabled(),
                "unload_after_each_request": lm_studio.unload_after_request_enabled(),
                "run_end_unload": bootstrap.auto_unload_enabled(),
                "prompt_cache_marker": lm_studio.prompt_cache_marker(),
            },
            "cancel_event": cancel_event,
        }
        _persist_run_state_locked()

        def _worker():
            _run_pipeline_worker(experiment_id, args, run_id)

        _THREAD = threading.Thread(
            target=_worker, name=f"ai-lab-runner-{run_id}", daemon=True
        )
        _THREAD.start()

    return {
        "experiment_id": experiment_id,
        "status": skeleton.get("status"),
        "ai_cell_id": skeleton.get("ai_cell_id"),
        "class_name": skeleton.get("class_name"),
        "queued": True,
        "run_id": run_id,
        "strategy_count": strategy_count,
        "iterations_per_strategy": iterations_per_strategy,
        "iterations_unlimited": iterations_unlimited,
        "max_total_runtime_minutes": runtime_minutes,
    }


def _prepare_next_during_backtest(
    source_experiment_id: str,
    args: Dict[str, Any],
    holder: Dict[str, Any],
    run_id: str,
) -> None:
    """Use otherwise idle model time while NinjaTrader owns the backtest lane."""
    from . import orchestrator

    _update_run_state(staged_pipeline={
        "state": "waiting_for_backtest", "source_experiment_id": source_experiment_id,
    })
    deadline = time.time() + 900
    while time.time() < deadline and not _is_run_cancelled():
        source = registry.read_experiment(source_experiment_id) or {}
        status = str(source.get("status") or "")
        if status == "backtesting" or registry.is_terminal(status):
            break
        time.sleep(2)
    if _is_run_cancelled():
        holder["cancelled"] = True
        return
    source = registry.read_experiment(source_experiment_id) or {}
    next_args = dict(args)
    source_family = str(source.get("family") or "")
    source_hypothesis = str(source.get("hypothesis") or "")[:500]
    base_goal = str(next_args.get("user_goal") or next_args.get("goal") or "")
    next_args["user_goal"] = (
        base_goal
        + "\nStaged pipeline: prepare a structurally distinct next strategy while the prior one "
        + f"is backtesting. Avoid copying family={source_family}; prior hypothesis={source_hypothesis}"
    )[:3000]
    next_args["staged_source_experiment_id"] = source_experiment_id
    next_args["avoid_families"] = [source_family] if source_family else []
    _update_run_state(staged_pipeline={
        "state": "designing", "source_experiment_id": source_experiment_id,
    })
    prepared = orchestrator.prepare_strategy_draft(next_args)
    if holder.get("abandoned"):
        prepared["status"] = "archived"
        prepared["archive_reason"] = "staged planner exceeded handoff deadline"
        registry.write_experiment(prepared)
        return
    holder["experiment"] = prepared
    _update_run_state(staged_pipeline={
        "state": "ready" if prepared.get("status") == "draft_ready" else "failed",
        "source_experiment_id": source_experiment_id,
        "developing_experiment_id": prepared.get("experiment_id"),
        "status": prepared.get("status"),
        "family": prepared.get("family"),
        "model": ((prepared.get("staged_pipeline") or {}).get("model")),
    })


def _attach_staged_feedback(next_experiment: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    committee = source.get("agent_committee") or {}
    optimizer = ((committee.get("reports") or {}).get("optimizer") or {})
    next_experiment["staged_feedback"] = {
        "source_experiment_id": source.get("experiment_id"),
        "source_status": source.get("status"),
        "source_family": source.get("family"),
        "source_verdict": source.get("verdict") or {},
        "source_metrics": {
            key: (source.get("analysis") or {}).get(key)
            for key in ("trades_total", "net_after_commission", "pf_after_commission", "dd_after_commission")
        },
        "optimizer_advice": str(optimizer.get("content") or "")[:2500],
        "shared_at_utc": _now(),
    }
    registry.write_experiment(next_experiment)
    return next_experiment


def _run_pipeline_worker(experiment_id: str, args: Dict[str, Any], run_id: str) -> None:
    from . import orchestrator
    from . import mutation as ai_mutation
    global _CURRENT, _THREAD, _RUN_STATE

    current_experiment_id = experiment_id
    strategy_count = int(args.get("strategy_count") or 1)
    iterations_per_strategy = args.get("iterations_per_strategy")
    iterations_unlimited = bool(args.get("iterations_unlimited", False))
    deadline = None
    runtime_min = args.get("max_total_runtime_minutes")
    if runtime_min not in (None, ""):
        deadline = time.time() + int(runtime_min) * 60
    stop_on_first_candidate = bool(args.get("stop_on_first_candidate", False))
    candidate_count = 0
    failure_counts: Dict[str, int] = {}
    breaker_open = False

    try:
        for strategy_idx in range(1, strategy_count + 1):
            if _is_run_cancelled():
                break
            if deadline is not None and time.time() >= deadline:
                _write_run_log("deadline_reached_outer", run_id=run_id,
                               strategy_idx=strategy_idx)
                break

            _update_run_state(strategy_idx=strategy_idx, iteration_idx=1,
                              current_experiment_id=current_experiment_id)
            staged_holder: Dict[str, Any] = {}
            staged_thread: Optional[threading.Thread] = None
            if strategy_idx < strategy_count:
                staged_args = dict(args)
                staged_args.update({
                    "parent_experiment_id": current_experiment_id,
                    "research_mode": "research_until_candidate_or_budget_exhausted",
                    "research_run_id": run_id,
                    "research_attempt_index": strategy_idx + 1,
                    "max_cells_per_run": strategy_count,
                })
                staged_thread = threading.Thread(
                    target=_prepare_next_during_backtest,
                    args=(current_experiment_id, staged_args, staged_holder, run_id),
                    name=f"ai-lab-staged-{run_id}-{strategy_idx + 1}", daemon=True,
                )
                staged_thread.start()
            activity.log(
                current_experiment_id, "runner", "strategy_started", level="info",
                run_id=run_id, strategy_idx=strategy_idx,
                strategy_total=strategy_count,
            )

            # --- inner iteration loop ---
            iter_idx = 1
            while True:
                if _is_run_cancelled():
                    break
                if deadline is not None and time.time() >= deadline:
                    _write_run_log("deadline_reached_inner", run_id=run_id,
                                   strategy_idx=strategy_idx, iteration_idx=iter_idx)
                    break
                _update_run_state(iteration_idx=iter_idx)
                inner_total: Any = "∞" if iterations_unlimited else iterations_per_strategy
                activity.log(
                    current_experiment_id, "runner", "iteration_started", level="info",
                    run_id=run_id, strategy_idx=strategy_idx,
                    iteration_idx=iter_idx, iteration_total=str(inner_total),
                )

                iter_args = dict(args)
                iter_args["research_run_id"] = run_id
                iter_args["research_attempt_index"] = strategy_idx
                iter_args["max_cells_per_run"] = strategy_count
                iter_args["iteration_idx"] = iter_idx

                _execute_one_cell(current_experiment_id, iter_args)
                exp = registry.read_experiment(current_experiment_id) or {}
                _record_iteration_in_experiment(exp, iter_idx)
                if _is_candidate(exp):
                    candidate_count += 1
                    _update_run_state(candidate_count=candidate_count)

                activity.log(
                    current_experiment_id, "runner", "iteration_finished",
                    level="success", final_status=exp.get("status"),
                    iteration_idx=iter_idx,
                    candidate_count=candidate_count,
                )

                signature = _failure_signature(exp)
                if signature:
                    failure_counts[signature] = failure_counts.get(signature, 0) + 1
                    threshold = _breaker_threshold(signature)
                    if threshold and failure_counts[signature] >= threshold:
                        breaker_open = True
                        _update_run_state(
                            circuit_breaker={
                                "open": True, "signature": signature,
                                "count": failure_counts[signature],
                                "opened_at_utc": _now(),
                            }
                        )
                        _notify_circuit_breaker(
                            current_experiment_id, signature, failure_counts[signature],
                        )
                        break

                # Should we mutate and try another iteration in the same cell?
                with _LOCK:
                    if _RUN_STATE is not None and _RUN_STATE.get("run_id") == run_id:
                        iterations_per_strategy = _RUN_STATE.get("iterations_per_strategy")
                        stop_on_first_candidate = bool(_RUN_STATE.get("stop_on_first_candidate"))
                if not _inner_should_continue(
                    exp, iter_idx,
                    iterations_per_strategy=iterations_per_strategy,
                    iterations_unlimited=iterations_unlimited,
                    deadline=deadline,
                ):
                    break

                next_iter = iter_idx + 1
                activity.log(
                    current_experiment_id, "runner", "mutation_prepare",
                    level="warn",
                    iteration_idx=next_iter,
                    reason=f"verdict {exp.get('verdict', {}).get('outcome')} → mutating same cell",
                )
                try:
                    mutation_result = ai_mutation.prepare_next(
                        current_experiment_id, iter_idx
                    )
                except Exception as me:  # noqa: BLE001
                    activity.log(current_experiment_id, "runner", "mutation_failed",
                                 level="error", error=str(me)[:300])
                    break
                if not mutation_result.get("ok"):
                    activity.log(
                        current_experiment_id,
                        "runner",
                        "mutation_failed",
                        level="error",
                        error=str(mutation_result.get("error") or "unknown mutation failure")[:300],
                        iteration_idx=next_iter,
                    )
                    break
                iter_idx = next_iter

            # End of inner loop — decide if we keep going with a new strategy.
            exp = registry.read_experiment(current_experiment_id) or {}
            activity.log(
                current_experiment_id, "runner", "strategy_finished",
                level="success", final_status=exp.get("status"),
                run_id=run_id, strategy_idx=strategy_idx,
                candidate_count=candidate_count,
            )
            if breaker_open:
                if staged_thread is not None and staged_thread.is_alive():
                    staged_holder["abandoned"] = True
                break
            if stop_on_first_candidate and candidate_count >= 1:
                break
            if strategy_idx >= strategy_count:
                break
            if _is_run_cancelled():
                break
            if deadline is not None and time.time() >= deadline:
                break

            source_experiment = registry.read_experiment(current_experiment_id) or {}
            if staged_thread is not None:
                wait_limit = 240.0
                if deadline is not None:
                    wait_limit = max(1.0, min(wait_limit, deadline - time.time()))
                staged_thread.join(timeout=wait_limit)
            next_skeleton = staged_holder.get("experiment")
            if not isinstance(next_skeleton, dict) or next_skeleton.get("status") != "draft_ready":
                if staged_thread is not None and staged_thread.is_alive():
                    staged_holder["abandoned"] = True
                next_args = dict(args)
                next_args.update({
                    "parent_experiment_id": current_experiment_id,
                    "research_mode": "research_until_candidate_or_budget_exhausted",
                    "research_run_id": run_id,
                    "research_attempt_index": strategy_idx + 1,
                    "max_cells_per_run": strategy_count,
                })
                next_skeleton = orchestrator.start_skeleton(next_args)
            next_skeleton = _attach_staged_feedback(next_skeleton, source_experiment)
            current_experiment_id = next_skeleton["experiment_id"]
            with _LOCK:
                if _CURRENT is not None:
                    ev = _CURRENT.get("cancel_event")
                    _CURRENT.update({
                        "experiment_id": current_experiment_id,
                        "ai_cell_id": next_skeleton.get("ai_cell_id"),
                        "class_name": next_skeleton.get("class_name"),
                        "target_root": next_skeleton.get("target_root"),
                        "status": next_skeleton.get("status"),
                        "cancel_event": ev,
                    })
                if _RUN_STATE is not None:
                    _RUN_STATE["current_experiment_id"] = current_experiment_id
                    _RUN_STATE["experiments"].append(current_experiment_id)
                    _RUN_STATE["staged_pipeline"] = {
                        "state": "promoted_to_execution",
                        "developing_experiment_id": current_experiment_id,
                        "status": next_skeleton.get("status"),
                    }
                    _persist_run_state_locked()
    except Exception as e:  # noqa: BLE001
        activity.log(current_experiment_id, "runner", "pipeline_crashed", level="error",
                     error=str(e), trace=traceback.format_exc()[:1000])
        try:
            exp = registry.read_experiment(current_experiment_id) or {}
            if exp.get("status") and not registry.is_terminal(str(exp.get("status"))):
                registry.transition_status(
                    current_experiment_id,
                    "pipeline_failed",
                    reason=f"unhandled pipeline error: {e}",
                    extra={
                        "verdict": {
                            "outcome": "reject",
                            "reasons": [f"pipeline error: {e}"],
                            "rejection_code": "PIPELINE_EXCEPTION",
                            "structural": True,
                        }
                    },
                )
        except Exception:
            pass
    finally:
        try:
            from . import bootstrap
            if bootstrap.auto_unload_enabled():
                unload = bootstrap.unload_models()
                _write_run_log("lm_studio_unloaded", unload=unload)
        except Exception as exc:  # noqa: BLE001
            _write_run_log("lm_studio_unload_failed", error=str(exc)[:500])
        try:
            with _LOCK:
                ev = _CURRENT.get("cancel_event") if _CURRENT else None
                was_cancelled = bool(ev and ev.is_set())
            if was_cancelled:
                exp = registry.read_experiment(current_experiment_id) or {}
                status = exp.get("status", "")
                if status and not registry.is_terminal(status):
                    try:
                        registry.transition_status(
                            current_experiment_id, "cancelled", reason="user cancelled"
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        with _LOCK:
            if _RUN_STATE is not None:
                _RUN_STATE["finished_utc"] = _now()
                _RUN_STATE["cancelled"] = bool(_RUN_STATE.get("cancelled"))
                _persist_run_state_locked()
            _CURRENT = None
            _THREAD = None
            _RUN_STATE = None


def _inner_should_continue(
    exp: Dict[str, Any],
    iter_idx: int,
    *,
    iterations_per_strategy: Optional[int],
    iterations_unlimited: bool,
    deadline: Optional[float],
) -> bool:
    """Decide whether to run another iteration within the SAME experiment.

    True iff the verdict warrants mutation AND we have iteration/runtime budget.
    """
    if not iterations_unlimited and iterations_per_strategy is not None and iter_idx >= int(iterations_per_strategy):
        return False
    if deadline is not None and time.time() >= deadline:
        return False
    status = str(exp.get("status") or "")
    if status in {"cancelled", "blocked_lm_studio", "blocked_by_real_environment_issue"}:
        return False
    # Candidate-class statuses → we are done with this cell.
    if status in registry.PORTFOLIO_ELIGIBLE_STATUSES:
        return False
    # compile_failed_after_fix_loop / validation_failed are structural; a new
    # hypothesis won't fix the same broken NT8 pattern in the same cell.
    # Check this BEFORE the verdict so a "reject" verdict on a structural
    # failure doesn't trick us into another doomed mutation.
    if status in {"compile_failed", "compile_failed_after_fix_loop",
                  "validation_failed", "awaiting_compile_timeout"}:
        return False
    verdict = (exp.get("verdict") or {}).get("outcome")
    # Mutate when verdict indicates mid-quality or explicit reject.
    if verdict in {"mutate", "reject"}:
        if _strategy_is_stagnating(exp):
            return False
        return True
    if status in {"rejected", "mutation_candidate"}:
        if _strategy_is_stagnating(exp):
            return False
        return True
    return False


def _strategy_is_stagnating(exp: Dict[str, Any]) -> bool:
    """Detect an evidence-backed plateau across the latest three variants."""
    history = [
        row for row in (exp.get("iteration_history") or [])
        if isinstance(row, dict) and row.get("status") != "mutation_planned"
    ]
    if len(history) < 3:
        return False
    recent = history[-3:]
    codes = {str(row.get("rejection_code") or "") for row in recent}
    families = {str(row.get("family") or "") for row in recent}
    hypotheses = [
        re.sub(r"\s+", " ", str(row.get("hypothesis") or "").strip().lower())
        for row in recent
    ]
    if hypotheses[0] and len(set(hypotheses)) == 1:
        return True
    if len(codes) != 1 or "" in codes or len(families) != 1:
        return False
    pfs = [row.get("pf_after_commission") for row in recent]
    if any(value is None for value in pfs):
        return False
    try:
        numeric = [float(value) for value in pfs]
    except (TypeError, ValueError):
        return False
    return max(numeric[1:]) <= numeric[0] + 0.03


def _record_iteration_in_experiment(exp: Dict[str, Any], iter_idx: int) -> None:
    eid = exp.get("experiment_id")
    if not eid:
        return
    history = list(exp.get("iteration_history") or [])
    analysis = exp.get("analysis") if isinstance(exp.get("analysis"), dict) else {}
    backtests = [row for row in (exp.get("backtests") or []) if isinstance(row, dict)]
    latest_test = backtests[-1] if backtests else {}
    final_row = {
        "iteration": iter_idx,
        "sha256": (exp.get("strategy_source") or {}).get("sha256"),
        "verdict": (exp.get("verdict") or {}).get("outcome"),
        "rejection_code": (exp.get("verdict") or {}).get("rejection_code"),
        "status": exp.get("status"),
        "pf_after_commission": analysis.get("pf_after_commission", latest_test.get("pf_after_commission")),
        "trades_total": analysis.get("trades_total", latest_test.get("trades")),
        "net_after_commission": analysis.get("net_after_commission", latest_test.get("net_after_commission")),
        "family": exp.get("family"),
        "hypothesis": str(exp.get("hypothesis") or "")[:500],
        "score": (exp.get("arbitration") or {}).get("score"),
        "recorded_utc": _now(),
    }
    existing_idx = next(
        (
            idx for idx, row in enumerate(history)
            if int(row.get("iteration") or 0) == iter_idx
        ),
        None,
    )
    if existing_idx is None:
        history.append(final_row)
    else:
        # ``mutation.prepare_next`` creates a provisional "generated" row
        # before the pipeline runs. Preserve its audit fields while replacing
        # provisional status/verdict/metrics with the completed iteration.
        history[existing_idx] = {**history[existing_idx], **final_row}
    exp["iteration_history"] = history
    exp["current_iteration"] = iter_idx
    try:
        registry.write_experiment(exp)
    except Exception:
        pass


def _execute_one_cell(experiment_id: str, args: Dict[str, Any]) -> None:
    from . import orchestrator

    orchestrator.run_pipeline(experiment_id, args)
    exp = registry.read_experiment(experiment_id) or {}
    status = exp.get("status", "")
    if status == "backtesting":
        bts = exp.get("backtests") or []
        if bts:
            job_id = bts[-1].get("job_id")
            if job_id:
                _await_and_finalize(experiment_id, job_id)


def _is_candidate(exp: Dict[str, Any]) -> bool:
    status = exp.get("status")
    verdict = exp.get("verdict") or {}
    if status in registry.PORTFOLIO_ELIGIBLE_STATUSES and not registry.promotion_blockers(exp):
        return True
    return verdict.get("outcome") in {"candidate", "keep"} and not registry.promotion_blockers(exp)


def _should_continue_loop(
    exp: Dict[str, Any],
    args: Dict[str, Any],
    *,
    research_mode: str,
    attempt_index: int,
    max_cells: int,
    candidate_count: int,
    deadline: float,
) -> bool:
    """Legacy outer-loop continuation check (kept for tests/back-compat).

    The live worker now uses ``_inner_should_continue`` + outer ``for``-loop;
    this function is preserved so existing tests
    (``t_runner_research_loop_continues_after_rejected``) keep passing.
    """
    if research_mode != "research_until_candidate_or_budget_exhausted":
        return False
    if time.time() >= deadline:
        return False
    if attempt_index >= max_cells:
        return False
    target_candidate_count = int(args.get("target_candidate_count") or 1)
    stop_on_first_candidate = bool(args.get("stop_on_first_candidate", True))
    if candidate_count >= target_candidate_count:
        return False
    if stop_on_first_candidate and candidate_count >= 1:
        return False
    status = str(exp.get("status") or "")
    if not registry.is_terminal(status):
        return False
    return status not in registry.PORTFOLIO_ELIGIBLE_STATUSES


# ---------------------- run-level state helpers ----------------------

def _runs_dir():
    d = paths.RUNS_DIR / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _persist_run_state_locked() -> None:
    """Write a sanitized snapshot of _RUN_STATE to disk. Caller must hold _LOCK."""
    if _RUN_STATE is None:
        return
    snap = _api_snap(_RUN_STATE)
    try:
        write_json_atomic(_runs_dir() / f"{_RUN_STATE['run_id']}.json", snap)
    except Exception:
        pass


def _write_run_log(action: str, **fields: Any) -> None:
    """Write to ``ai_lab/registry/runs/runs/{run_id}.log`` for run-level events.

    Used for events that happen BEFORE an experiment exists (e.g. preflight
    block) — those can't go in experiment activity log.
    """
    run_id = fields.pop("run_id", None) or ("RUN-" + uuid.uuid4().hex[:8])
    rec = {"ts_utc": _now(), "action": action, "run_id": run_id, **fields}
    try:
        log_path = _runs_dir() / f"{run_id}.log"
        with log_path.open("a", encoding="utf-8") as fh:
            import json as _json
            fh.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _update_run_state(**fields: Any) -> None:
    with _LOCK:
        if _RUN_STATE is None:
            return
        _RUN_STATE.update(fields)
        _persist_run_state_locked()


def _is_run_cancelled() -> bool:
    with _LOCK:
        if _RUN_STATE is None:
            return False
        if _RUN_STATE.get("cancelled"):
            return True
        ev = _RUN_STATE.get("cancel_event")
        return bool(ev and ev.is_set())


def run_status() -> Optional[Dict[str, Any]]:
    """Return current run progress (outer/inner indices, deadline, etc.).

    Returns None if no run is active.
    """
    with _LOCK:
        if _RUN_STATE is None:
            return None
        snap = _api_snap(_RUN_STATE)
        # Live mirror of current experiment status.
        cur_eid = snap.get("current_experiment_id")
        if cur_eid:
            exp = registry.read_experiment(cur_eid) or {}
            snap["current_experiment_status"] = exp.get("status")
            snap["current_experiment_iteration_history"] = exp.get("iteration_history") or []
        if snap.get("deadline_epoch"):
            snap["seconds_remaining"] = max(0, int(snap["deadline_epoch"] - time.time()))
        else:
            snap["seconds_remaining"] = None
        return snap


def request_run_cancel(run_id: Optional[str] = None) -> Dict[str, Any]:
    """Cancel the whole run: stops outer loop, cancels current inner iteration."""
    with _LOCK:
        if _RUN_STATE is None:
            return {"ok": False, "reason": "no_active_run"}
        if run_id and _RUN_STATE.get("run_id") != run_id:
            return {"ok": False, "reason": "not_current", "current_run_id": _RUN_STATE.get("run_id")}
        _RUN_STATE["cancelled"] = True
        ev = _RUN_STATE.get("cancel_event")
        if ev is not None:
            ev.set()
        cur_eid = _RUN_STATE.get("current_experiment_id")
        cur_run_id = _RUN_STATE.get("run_id")
        _persist_run_state_locked()
    if cur_eid:
        try:
            activity.log(cur_eid, "runner", "run_cancel_requested", level="warn",
                         run_id=cur_run_id)
        except Exception:
            pass
    return {"ok": True, "run_id": cur_run_id, "experiment_id": cur_eid}


def update_run_policy(*, iterations_per_strategy: Optional[int] = None,
                      stop_on_first_candidate: Optional[bool] = None) -> Dict[str, Any]:
    """Adjust safe loop limits for the currently running strategy."""
    with _LOCK:
        if _RUN_STATE is None:
            return {"ok": False, "reason": "no_active_run"}
        if iterations_per_strategy is not None:
            _RUN_STATE["iterations_per_strategy"] = max(1, min(20, int(iterations_per_strategy)))
        if stop_on_first_candidate is not None:
            _RUN_STATE["stop_on_first_candidate"] = bool(stop_on_first_candidate)
        _persist_run_state_locked()
        return {"ok": True, **_api_snap(_RUN_STATE)}


def _await_and_finalize(experiment_id: str, job_id: str) -> None:
    """Poll jobs/done/{job_id}/result.json then call finalize_backtest."""
    from . import orchestrator

    activity.log(experiment_id, "backtest", "awaiting_result", level="info", job_id=job_id)
    deadline = time.time() + _FINALIZE_MAX_WAIT_SEC
    while time.time() < deadline:
        job_dir = backtest.find_job_dir(job_id)
        if job_dir and (job_dir.parent.name == "done") and (job_dir / "result.json").exists():
            activity.log(experiment_id, "backtest", "result_seen", level="success",
                         job_id=job_id, job_dir=str(job_dir))
            try:
                out = orchestrator.finalize_backtest(experiment_id, job_id)
                activity.log(experiment_id, "verdict", "finalized", level="success",
                             status=out.get("status"), score=out.get("score"))
            except Exception as e:  # noqa: BLE001
                activity.log(experiment_id, "verdict", "finalize_failed",
                             level="error", error=str(e))
            return
        if job_dir and job_dir.parent.name in ("failed", "cancelled"):
            activity.log(experiment_id, "backtest", "job_failed_or_cancelled",
                         level="error", job_id=job_id, dir=job_dir.parent.name)
            registry.transition_status(experiment_id, "backtest_failed",
                                       reason=f"job {job_dir.parent.name}")
            return
        time.sleep(_FINALIZE_POLL_SEC)
    activity.log(experiment_id, "backtest", "result_timeout", level="error",
                 job_id=job_id, waited_sec=_FINALIZE_MAX_WAIT_SEC)
    try:
        registry.transition_status(experiment_id, "backtest_failed",
                                   reason="no result.json within 30 min")
    except Exception:
        pass


def reset_for_tests() -> None:
    """Test-only: clear runner state so a fresh tempdir starts clean."""
    global _CURRENT, _THREAD, _RUN_STATE
    with _LOCK:
        _CURRENT = None
        _THREAD = None
        _RUN_STATE = None
