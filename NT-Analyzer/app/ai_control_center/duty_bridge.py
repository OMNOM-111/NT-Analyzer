"""The duty controller's owner-facing work, carried by the Заместитель.

The engine that watches the platform is the one that always watched it: it
finds problems, asks before it acts and keeps the team's working hours. What
changed on 20.09.2026 is the path to the owner. Its questions, its pause and
its "check now" arrive here, in the AI Center, as the deputy's own items, and
are answered here - so the old screens carry no function of their own and can
stand aside as history.

Nothing is reimplemented: every answer goes back through the same functions
the old screens called, so a decision means exactly what it always meant.
"""
from __future__ import annotations

from .states import ContractError

# Which incident is still open, and which task still waits for the owner, is
# the engine's own definition; it is read from there, never restated here.
# What the owner can answer, in their own words. The values are the engine's.
DECISIONS = (("create_task", "Поручить команде"), ("acknowledge", "Принял к сведению"),
             ("resolve", "Уже решено"), ("ignore", "Не нужно"))
SEVERITY = {"critical": "crit", "error": "crit", "warning": "warn", "task": "info", "info": "info"}
MAX_QUESTIONS = 40


def _owner(authorized):
    scope = authorized.get("chat_scope") or {}
    if not (scope.get("is_owner") and scope.get("uses_owner_runtime") and scope.get("membership_role") == "owner"):
        raise ContractError("owner_runtime_only")


def _vitek():
    from .. import vitek
    return vitek


def _question(incident):
    return {
        "kind": "incident",
        "id": str(incident.get("incident_id") or ""),
        "title": str(incident.get("title") or "Вопрос без названия"),
        "detail": str(incident.get("details") or ""),
        "recommendation": str(incident.get("recommendation") or ""),
        "category": str(incident.get("category") or ""),
        "level": SEVERITY.get(str(incident.get("severity") or ""), "info"),
        "at_utc": str(incident.get("last_seen_at_utc") or incident.get("first_seen_at_utc") or ""),
        "occurrences": incident.get("occurrences"),
        "decisions": [{"value": value, "label": label} for value, label in DECISIONS],
    }


def _task_question(task):
    return {
        "kind": "task",
        "id": str(task.get("task_id") or ""),
        "title": str(task.get("owner_title") or task.get("title") or "Поручение без названия"),
        "detail": str(task.get("question") or task.get("owner_summary") or task.get("result") or ""),
        "level": "warn",
        "at_utc": str(task.get("updated_at_utc") or task.get("created_at_utc") or ""),
        "status": str(task.get("status") or ""),
    }


def state(authorized):
    """What the deputy has for the owner: questions, the team's state, pauses."""
    _owner(authorized)
    vitek = _vitek()
    status = vitek.status()
    incidents = [row for row in (status.get("incidents") or [])
                 if str(row.get("status") or "") in vitek.OPEN_INCIDENT_STATUSES and bool(row.get("owner_decision_required"))]
    tasks = [row for row in (status.get("tasks") or [])
             if str(row.get("status") or "") in vitek.WAITING_TASK_STATUSES]
    questions = [_question(row) for row in incidents] + [_task_question(row) for row in tasks]
    rest = status.get("rest") if isinstance(status.get("rest"), dict) else {}
    return {
        "available": bool(status.get("ok", True)),
        "mode": str(status.get("mode") or ""),
        "message": str(status.get("message") or ""),
        "worker_alive": bool(status.get("worker_alive")),
        "resting": {"active": bool(rest.get("active")), "until_utc": str(rest.get("until_utc") or ""),
                    "reason": str(rest.get("reason") or "")},
        "questions": questions[:MAX_QUESTIONS],
        "question_count": len(questions),
        "working": [{"agent_id": row.get("agent_id"), "name": row.get("name"), "working": bool(row.get("working")),
                     "state": row.get("state"), "work": row.get("work"), "model": row.get("model")}
                    for row in (status.get("agent_activity") or [])],
        "last_check_utc": str(status.get("last_scan_at_utc") or ""),
        "task_counts": status.get("task_counts") or {},
    }


def decide(authorized, incident_id, decision, note="", user_id="owner"):
    """The owner's answer to one question, applied by the engine that asked."""
    _owner(authorized)
    if authorized.get("read_only"):
        raise ContractError("duty_read_only")
    if str(decision) not in {value for value, _ in DECISIONS}:
        raise ContractError("duty_decision_invalid")
    if not isinstance(note, str) or len(note) > 500:
        raise ContractError("duty_note_invalid")
    try:
        return {"incident": _vitek().decide_incident(str(incident_id), str(decision), note=note,
                                                     authorized_by=str(user_id or "owner"))}
    except Exception as exc:  # noqa: BLE001 - the engine's own refusal, stated as is
        raise ContractError("duty_refused:" + str(exc)[:120])


def answer(authorized, task_id, text):
    _owner(authorized)
    if authorized.get("read_only"):
        raise ContractError("duty_read_only")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ContractError("duty_answer_invalid")
    try:
        return {"task": _vitek().answer_task(str(task_id), text.strip())}
    except Exception as exc:  # noqa: BLE001
        raise ContractError("duty_refused:" + str(exc)[:120])


def pause(authorized, minutes=0, reason=""):
    """The owner stops the team for a while; the engine keeps the reason."""
    _owner(authorized)
    if authorized.get("read_only"):
        raise ContractError("duty_read_only")
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or not 0 <= minutes <= 24 * 60:
        raise ContractError("duty_pause_invalid")
    return {"rest": _vitek().set_rest(duration_minutes=int(minutes), reason=str(reason or "Решение владельца")[:200])}


def resume(authorized):
    _owner(authorized)
    if authorized.get("read_only"):
        raise ContractError("duty_read_only")
    return {"rest": _vitek().resume()}


def check(authorized):
    """«Проверить сейчас»: the same pass the engine runs by itself."""
    _owner(authorized)
    if authorized.get("read_only"):
        raise ContractError("duty_read_only")
    return {"check": _vitek().scan(notify=False)}
