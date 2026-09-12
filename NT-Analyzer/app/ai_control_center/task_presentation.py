"""One read-only lifecycle projection; execution is not human acceptance.

Raw ledger states remain immutable compatibility facts. Overview, Work, Persona
and SF Chat consume the same display state and disjoint counters from here.
"""
from __future__ import annotations


TASK_CLASSES = {
    "connection_exact": "Проверка подключения",
    "json_arithmetic": "Диагностика: арифметика JSON",
    "assistant_response": "Ответ помощника · ручная проверка",
    "extract_facts": "Передача фактов",
    "backtest_spec": "Подготовка и выполнение бэктеста",
    "chart_spec": "Снимок графика",
    "court_vote": "Независимое заключение Court",
    "verified_fact_transfer": "Общий результат · проверка передачи фактов",
}
STATES = {
    "queued": "В очереди", "running": "Выполняется",
    "waiting_result": "Ожидается результат", "awaiting_review": "Ожидает вашей проверки",
    "completed": "Проверка завершена", "failed": "Ошибка",
    "blocked": "Приостановлено: нужно решение", "cancelled": "Отменено",
    "rejected": "Результат отклонён", "planned": "Запланировано",
    "result_received": "Результат получен · приёмка не зафиксирована",
    "verified_automatically": "Автоматическая проверка завершена",
}
ACTIVE = frozenset({"queued", "running", "waiting_result"})
ATTENTION = frozenset({"awaiting_review", "failed", "blocked", "rejected"})


def project(task: dict, *, evaluation=None, human_review=None) -> dict:
    """No successful provider call silently becomes an accepted professional task."""
    raw = str(task.get("status") or "unknown")
    aggregate = task.get("source_kind") == "bounded_delegation_result"
    review = human_review or {"status": "not_required"}
    failed_check = isinstance(evaluation, dict) and evaluation.get("passed") is False
    # A verified plan is a provider response, not the requested report/PNG.
    application_required = bool(task.get("application_request")) or task.get("task_class") in {"backtest_spec", "chart_spec"}
    # Rows from the existing NinjaTrader and Desktop adapters are not model
    # tasks: they carry no provider receipt or evaluation, and their own
    # executor already verified them. Judging them by the model-result fields
    # would leave a finished report or snapshot reported as still waiting.
    model_task = (task.get("source_kind") == "real_model_response"
                  or "provider_result_received" in task or bool(task.get("evaluation_id"))
                  or bool(task.get("application_request")))
    # An adapter row counts as carrying a result only when its own executor
    # recorded evidence: source checksums for a NinjaTrader report, a verified
    # snapshot for a Desktop capture. Being an adapter row is not itself a
    # result, so a finished job whose evidence is missing or failed
    # verification never completes on the strength of its type.
    adapter_evidence = not model_task and int(task.get("evidence_count") or 0) > 0
    provider_result = (task.get("provider_result_received") is True
                       if "provider_result_received" in task
                       else bool(task.get("evaluation_id")) or adapter_evidence)
    application = task.get("application_result")
    application_result = (isinstance(application, dict) and application.get("verified") is True
                          and bool(application.get("artifact_ids")) and bool(task.get("application_evaluation_id")))
    result = task.get("aggregate_result_received") is True if aggregate else application_result if application_required else provider_result
    if aggregate:
        provider_result = False
    execution = task.get("execution_v2") or {}
    execution_status = execution.get("status")
    execution_blocked = execution_status in {"review", "deviated", "failed", "cancelled"}
    if task.get("error_code") or raw in {"failed", "error"} or failed_check:
        display = "blocked" if raw == "blocked" and not failed_check else "failed"
    elif raw == "cancelled":
        display = "cancelled"
    elif raw == "blocked":
        display = "blocked"
    elif execution_blocked:
        display = "blocked"
    elif aggregate and raw == "review":
        display = {"accepted": "completed", "rejected": "rejected", "stale": "blocked"}.get(
            review.get("status"), "blocked" if review.get("status") == "blocked" and review.get("blocked_reason") != "delegation_required_reviews_pending" else "awaiting_review")
    elif raw in {"succeeded", "completed"}:
        if application_required and not application_result or execution_status and execution_status != "succeeded":
            display = "waiting_result"
        elif not model_task and not adapter_evidence:
            # Execution finished, but the adapter could not confirm its own
            # evidence. That is a result a human has to look at, not a
            # completed one and not one still running.
            display = "awaiting_review"
        else:
            automatic = (result and adapter_evidence) or (
                task.get("task_class") in {"connection_exact", "court_vote"}
                and result and isinstance(evaluation, dict) and evaluation.get("passed") is True)
            display = {"pending": "awaiting_review", "accepted": "completed", "rejected": "rejected"}.get(
                review.get("status"), "verified_automatically" if automatic else "result_received" if result else "waiting_result")
    elif raw in {"queued", "ready"}:
        display = "queued"
    elif raw in {"running", "working", "active"}:
        display = "running"
    elif raw in {"waiting", "pending"}:
        display = "waiting_result"
    elif raw in {"review", "review_required", "approval_required", "awaiting_owner"}:
        display = "awaiting_review"
    else:
        display = "planned"
    technical = task.get("task_class") or task.get("source_kind") or ""
    label = TASK_CLASSES.get(technical, "Задание")
    person = (task.get("lead") or {}).get("display_name") or ""
    return {**task, "ledger_status": raw, "display_status": display,
            "status_label": STATES[display], "display_status_label": STATES[display], "task_class_label": label,
            "display_title": (person + " · " if person else "") + label if technical in TASK_CLASSES else task.get("title", "Задание"),
            "provider_result_received": provider_result, "application_result_required": application_required,
            "application_result_received": application_result, "result_received": result,
            "verification_status": "failed" if failed_check else "passed" if application_result or not application_required and isinstance(evaluation, dict) and evaluation.get("passed") is True else "pending",
            "verification_scope": "transport_only" if technical == "assistant_response" else "task_contract",
            "human_review": review, "is_active": display in ACTIVE,
            "needs_attention": display in ATTENTION,
            "result_label": "Результат получен" if result else "Результат ещё не получен"}


def counters(tasks: list[dict]) -> dict:
    """Each task has one lifecycle bucket; attention is an explicitly named union."""
    states = [task.get("display_status", task.get("status")) for task in tasks]
    failed = states.count("failed")
    reviewed = states.count("completed")
    return {"tasks_total": len(tasks), "active_tasks": sum(s in ACTIVE for s in states),
            "running": states.count("running"), "queued": states.count("queued"),
            "waiting_result": states.count("waiting_result"),
            "awaiting_review": states.count("awaiting_review"),
            "completed": reviewed, "completed_tasks": reviewed,
            "results_received": sum(task.get("result_received") is True for task in tasks),
            "provider_results_received": sum(task.get("provider_result_received") is True for task in tasks),
            "application_results_received": sum(task.get("application_result_received") is True for task in tasks),
            "failed": failed, "failed_tasks": failed, "blocked": states.count("blocked"),
            "verified_automatically": states.count("verified_automatically"),
            "acceptance_not_recorded": states.count("result_received"),
            "rejected": states.count("rejected"), "cancelled": states.count("cancelled"),
            "attention": sum(s in ATTENTION for s in states)}
