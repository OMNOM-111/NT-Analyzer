"""Presentation helpers layered on the single task lifecycle projection.

`task_presentation.project()` is the one place a task's lifecycle state is
computed. This module never recomputes it: everything here is derived from that
module's `display_status`, or covers things it does not address at all — the
human stage label, honest progress, the reason and next action behind a
warning, and the Persona face allow-list.

Two independent state computations is precisely the defect this program has
been unpicking, so the grouping below is a presentation view over
`task_presentation.STATES`, not a second opinion about what a task is doing.
"""
from __future__ import annotations

import re
from types import MappingProxyType

from .task_presentation import STATES

# Coarse groups used by counters and panel headings. Each display state belongs
# to exactly one group, and every state in task_presentation.STATES is placed —
# asserted in tests, so a new state cannot appear without being classified.
PHASE_EXECUTING = "executing"
PHASE_AWAITING_REVIEW = "awaiting_review"
PHASE_AWAITING_DECISION = "awaiting_decision"
PHASE_RESULT_UNCONFIRMED = "result_unconfirmed"
PHASE_DONE = "done"
PHASE_FAILED = "failed"
PHASE_CANCELLED = "cancelled"

_PHASE_BY_DISPLAY = MappingProxyType({
    "queued": PHASE_EXECUTING, "running": PHASE_EXECUTING,
    "waiting_result": PHASE_EXECUTING, "planned": PHASE_EXECUTING,
    "awaiting_review": PHASE_AWAITING_REVIEW,
    "blocked": PHASE_AWAITING_DECISION,
    # A received result whose acceptance is not recorded is neither finished
    # nor blocked on anybody: it is evidence the owner has not signed off on.
    "result_received": PHASE_RESULT_UNCONFIRMED,
    "completed": PHASE_DONE, "verified_automatically": PHASE_DONE,
    "failed": PHASE_FAILED, "rejected": PHASE_FAILED,
    "cancelled": PHASE_CANCELLED,
})

PHASE_LABELS = MappingProxyType({
    PHASE_EXECUTING: "Выполняется",
    PHASE_AWAITING_REVIEW: "Ожидает проверки",
    PHASE_AWAITING_DECISION: "Ожидает решения",
    PHASE_RESULT_UNCONFIRMED: "Результат не принят",
    PHASE_DONE: "Завершено",
    PHASE_FAILED: "Ошибка",
    PHASE_CANCELLED: "Отменено",
})

OPEN_PHASES = frozenset({PHASE_AWAITING_REVIEW, PHASE_AWAITING_DECISION})
ATTENTION_PHASES = frozenset({PHASE_AWAITING_REVIEW, PHASE_AWAITING_DECISION, PHASE_FAILED})
DONE_DISPLAY = frozenset({"completed", "verified_automatically"})

RUBRIC_LABELS = MappingProxyType({
    "connection_exact": "Проверка соединения",
    "json_arithmetic": "Арифметика · JSON",
    "assistant_response": "Ответ помощника · ручная проверка",
    "extract_facts": "Извлечение фактов",
    "court_vote": "Голос Court",
    "backtest_spec": "План бэктеста",
    "chart_spec": "План графика",
    "application_execution": "Соответствие результата приложения",
    # Emitted by the existing NinjaTrader and Desktop adapters.
    "ninjatrader_historical_backtest": "Исторический бэктест NinjaTrader",
    "desktop_chart_snapshot": "Снимок графика Рабочего стола",
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

# Why an item needs attention, plus what actually unblocks it. Waiting for a
# check is not waiting for a decision, so the two never share wording.
ATTENTION_REASONS = MappingProxyType({
    PHASE_AWAITING_REVIEW: (
        "Модель ответила, но независимая проверка не подтвердила формат результата.",
        "Откройте задачу, чтобы увидеть ответ и результат проверки. Подтверждение требуется не везде.",
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

# A request refused before it reached the queue. The stored code is exact; these
# are the sentences a person can act on. Families cover the codes that share one
# cause, so a new code inside a family is explained rather than shown raw.
REFUSAL_REASONS = MappingProxyType({
    "execution_v2_approved_scope_changed":
        "Запрос не принят: состав согласованного задания изменился между подготовкой и отправкой.",
    "execution_v2_deadline_expired":
        "Запрос не принят: срок согласованного задания истёк до отправки.",
    "persona_selection_changed":
        "Запрос не принят: выбранная Persona изменилась между подготовкой и отправкой.",
    "model_connection_inactive":
        "Запрос не принят: выбранное подключение больше не активно.",
    "model_test_executor_disabled":
        "Запрос не принят: named-обработчик недоступен в этом рабочем пространстве.",
})
REFUSAL_FAMILIES = (
    ("execution_v2_", "Запрос не принят: проверка прав на исполнение не пропустила его."),
    ("agent_world_", "Запрос не принят: сессия или рабочее пространство изменились."),
    ("model_", "Запрос не принят: подключение или его настройки не позволили выполнить его."),
    ("handoff_", "Запрос не принят: источник передачи фактов не прошёл проверку."),
)
REFUSAL_ACTION = ("Задание не выполнялось и не стоит в очереди. Исходное сообщение сохранено; "
                  "отправьте новый запрос, когда причина устранена.")


def task_phase(display_status) -> str:
    """Group one already-computed display state. Never re-derives from status."""
    return _PHASE_BY_DISPLAY.get(str(display_status or "").lower(), PHASE_AWAITING_DECISION)


def phase_label(phase) -> str:
    return PHASE_LABELS.get(str(phase or ""), "Состояние не определено")


def _machine_key(value) -> bool:
    """A lowercase ASCII identifier, as opposed to text written for a reader.

    The NinjaTrader and Desktop adapters already send a written stage; replacing
    that with a placeholder would be a step backwards.
    """
    return bool(re.fullmatch(r"[a-z][a-z0-9_]*", str(value or "")))


def rubric_label(rubric_key) -> str:
    key = str(rubric_key or "")
    return RUBRIC_LABELS.get(key, key or "Класс задачи не указан")


def stage_label(stage) -> str:
    key = str(stage or "")
    if key in STAGE_LABELS:
        return STAGE_LABELS[key]
    if not key:
        return "Этап не указан"
    return "Этап: технические детали" if _machine_key(key) else key


def progress_pct(display_status) -> int | None:
    """Honest progress: a number only where one was actually measured.

    Nothing on this path measures partial completion, so only a finished task
    reports 100. Everything else reports none and the card shows its state
    instead — which says more than a fabricated percentage and cannot
    contradict the badge beside it.
    """
    return 100 if str(display_status or "").lower() in DONE_DISPLAY else None


def attention_reason(phase) -> tuple[str, str]:
    return ATTENTION_REASONS.get(str(phase or ""), (
        "Требуется внимание владельца.", "Откройте задачу, чтобы увидеть подробности."))


def refusal_reason(error_code) -> tuple[str, str] | None:
    """The sentence and next action behind a pre-queue refusal, or None.

    A code this module does not recognise still produces a sentence rather than
    silence: not knowing the exact cause is not a reason to tell somebody
    nothing happened.
    """
    code = str(error_code or "")
    if not code:
        return None
    if code in REFUSAL_REASONS:
        return REFUSAL_REASONS[code], REFUSAL_ACTION
    for prefix, sentence in REFUSAL_FAMILIES:
        if code.startswith(prefix):
            return sentence, REFUSAL_ACTION
    return "Запрос не принят сервером до постановки в очередь.", REFUSAL_ACTION


def counters(display_statuses) -> dict:
    """Separate counters over the single projection's states."""
    phases = [task_phase(value) for value in display_statuses]
    return {
        "executing": phases.count(PHASE_EXECUTING),
        "awaiting_review": phases.count(PHASE_AWAITING_REVIEW),
        "awaiting_decision": phases.count(PHASE_AWAITING_DECISION),
        "result_unconfirmed": phases.count(PHASE_RESULT_UNCONFIRMED),
        "done": phases.count(PHASE_DONE),
        "failed": phases.count(PHASE_FAILED),
        "cancelled": phases.count(PHASE_CANCELLED),
    }


# Persona faces. Only keys with a shipped asset directory under
# app/static/aurora/assets/agents/ are offered; an unknown key falls back to the
# name initial rather than borrowing another agent's face. A Persona name is
# free text, so a face is always an explicit choice, never inferred from it.
AVATAR_KEYS = ("vitek", "manager", "marina", "tolik", "nikita", "ivan")
AVATAR_LABELS = MappingProxyType({
    "vitek": "Виктор", "manager": "Управляющий", "marina": "Марина",
    "tolik": "Толик", "nikita": "Никита", "ivan": "Иван",
})


def avatar_key(value) -> str:
    """Empty string for anything not on the list; never raises on user text."""
    key = str(value or "").strip().lower()
    return key if key in AVATAR_KEYS else ""
