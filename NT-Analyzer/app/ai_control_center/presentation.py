"""Shared presentation vocabulary for Agent World.

Machine identifiers stay authoritative and unchanged; this module only adds the
human labels and the coarse phase used by counters. Execution, waiting for a
review, waiting for an owner decision and finishing are four different things,
so a single "active" number can never stand for all of them.
"""
from __future__ import annotations

from types import MappingProxyType

# Persona/model/task machine statuses keep their meaning. Phases group them for
# counters so that a card and its metric can never disagree about one task.
PHASE_EXECUTING = "executing"
PHASE_AWAITING_REVIEW = "awaiting_review"
PHASE_AWAITING_DECISION = "awaiting_decision"
PHASE_DONE = "done"
PHASE_FAILED = "failed"
PHASE_CANCELLED = "cancelled"

_PHASE_BY_STATUS = MappingProxyType({
    "planned": PHASE_EXECUTING, "ready": PHASE_EXECUTING, "queued": PHASE_EXECUTING,
    "running": PHASE_EXECUTING, "working": PHASE_EXECUTING, "waiting": PHASE_EXECUTING,
    "review": PHASE_AWAITING_REVIEW, "review_required": PHASE_AWAITING_REVIEW,
    "blocked": PHASE_AWAITING_DECISION, "approval_required": PHASE_AWAITING_DECISION,
    "awaiting_owner": PHASE_AWAITING_DECISION,
    "succeeded": PHASE_DONE, "completed": PHASE_DONE, "verified": PHASE_DONE,
    "failed": PHASE_FAILED, "rejected": PHASE_FAILED, "error": PHASE_FAILED,
    "cancelled": PHASE_CANCELLED,
})

PHASE_LABELS = MappingProxyType({
    PHASE_EXECUTING: "Выполняется",
    PHASE_AWAITING_REVIEW: "Ожидает проверки",
    PHASE_AWAITING_DECISION: "Ожидает решения",
    PHASE_DONE: "Завершено",
    PHASE_FAILED: "Ошибка",
    PHASE_CANCELLED: "Отменено",
})

# Phases that need a human before the task can move again. They are not
# execution and they are not finished work.
OPEN_PHASES = frozenset({PHASE_AWAITING_REVIEW, PHASE_AWAITING_DECISION})
ATTENTION_PHASES = frozenset({PHASE_AWAITING_REVIEW, PHASE_AWAITING_DECISION, PHASE_FAILED})

RUBRIC_LABELS = MappingProxyType({
    "connection_exact": "Проверка соединения",
    "json_arithmetic": "Арифметика · JSON",
    "extract_facts": "Извлечение фактов",
    "court_vote": "Голос Court",
    "backtest_spec": "План бэктеста",
    "chart_spec": "План графика",
    "application_execution": "Соответствие результата приложения",
})

STAGE_LABELS = MappingProxyType({
    "awaiting_provider": "Ожидает ответа модели",
    "provider_receipt": "Ответ модели получен",
    "awaiting_application": "Ожидает результата приложения",
    "application_verified": "Результат приложения проверен",
    "application_failed": "Приложение вернуло ошибку",
    "application_cancel_requested": "Запрошена отмена в приложении",
    "work": "Выполнение",
    "evaluation": "Проверка результата",
    "planning": "Планирование",
    "review": "Проверка",
})

# Why an item needs attention, in the owner's terms, plus what actually unblocks
# it. An unexplained warning is not an actionable one.
ATTENTION_REASONS = MappingProxyType({
    PHASE_AWAITING_REVIEW: (
        "Модель ответила, но независимая проверка не подтвердила формат результата.",
        "Откройте задачу и решите: принять, повторить или оставить в истории.",
    ),
    PHASE_AWAITING_DECISION: (
        "Задача остановлена до вашего решения.",
        "Откройте задачу и подтвердите или отклоните следующий шаг.",
    ),
    PHASE_FAILED: (
        "Попытка завершилась ошибкой и сохранена в истории как неуспешная.",
        "Откройте задачу, чтобы увидеть код ошибки и при необходимости повторить.",
    ),
})


def task_phase(status) -> str:
    """Coarse phase for a task status. Unknown statuses never become 'done'."""
    return _PHASE_BY_STATUS.get(str(status or "").lower(), PHASE_AWAITING_DECISION)


def phase_label(phase) -> str:
    return PHASE_LABELS.get(str(phase or ""), "Состояние не определено")


def rubric_label(rubric_key) -> str:
    key = str(rubric_key or "")
    return RUBRIC_LABELS.get(key, key or "Класс задачи не указан")


def stage_label(stage) -> str:
    key = str(stage or "")
    return STAGE_LABELS.get(key, key or "Этап не указан")


def progress_pct(status) -> int | None:
    """Honest progress.

    Only a finished task is 100 %. A failed, cancelled or awaiting-review task
    has no meaningful completion percentage, so it reports none instead of a
    full bar that contradicts its own status badge.
    """
    phase = task_phase(status)
    if phase == PHASE_DONE:
        return 100
    if phase == PHASE_EXECUTING:
        return 0
    return None


def attention_reason(phase) -> tuple[str, str]:
    return ATTENTION_REASONS.get(str(phase or ""), (
        "Требуется внимание владельца.", "Откройте задачу, чтобы увидеть подробности."))


def counters(statuses) -> dict:
    """Separate counters. The caller must not add these together as 'tasks'."""
    phases = [task_phase(status) for status in statuses]
    return {
        "executing": phases.count(PHASE_EXECUTING),
        "awaiting_review": phases.count(PHASE_AWAITING_REVIEW),
        "awaiting_decision": phases.count(PHASE_AWAITING_DECISION),
        "done": phases.count(PHASE_DONE),
        "failed": phases.count(PHASE_FAILED),
        "cancelled": phases.count(PHASE_CANCELLED),
    }
