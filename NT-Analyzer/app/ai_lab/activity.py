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
    "runner", "status", "staged", "safety",
}

LEVELS = {"info", "warn", "error", "success"}

_EID_RE = re.compile(r"^EXP-\d{8}-\d{4}$")

STAGE_RU = {
    "intake": "Подготовка",
    "generate": "Генерация",
    "validate": "Проверка",
    "write": "Запись файла",
    "compile": "Компиляция",
    "catalog": "Каталог NT",
    "signal_sanity": "Проверка сигналов",
    "backtest": "Бэктест",
    "analyze": "Анализ",
    "arbitrate": "Оценка",
    "verdict": "Вердикт",
    "runner": "Запуск",
    "status": "Статус",
    "staged": "Параллельная разработка",
    "safety": "Защита запуска",
}

LEVEL_RU = {
    "info": "информация",
    "warn": "предупреждение",
    "error": "ошибка",
    "success": "успешно",
}

STATUS_RU = {
    "draft": "черновик",
    "designing": "параллельная разработка",
    "draft_ready": "проект готов",
    "generating": "генерация",
    "generated": "код сгенерирован",
    "validation_failed": "проверка не пройдена",
    "compile_requested": "компиляция запрошена",
    "awaiting_compile": "ожидание компиляции",
    "compile_failed": "ошибка компиляции",
    "compile_failed_after_fix_loop": "компиляция не исправлена",
    "awaiting_compile_timeout": "тайм-аут компиляции",
    "compiled": "скомпилировано",
    "catalog_visible": "видно в каталоге",
    "signal_sanity_failed": "проверка сигналов не пройдена",
    "backtest_submitted": "бэктест отправлен",
    "backtest_done": "бэктест завершен",
    "backtest_failed": "бэктест упал",
    "blocked_by_real_environment_issue": "заблокировано проблемой окружения",
    "blocked_lm_studio": "заблокировано LM Studio",
    "pipeline_failed": "ошибка пайплайна",
    "rejected": "отклонено",
    "mutation_candidate": "кандидат на мутацию",
    "mutation_planned": "мутация запланирована",
    "sandbox_candidate": "кандидат песочницы",
    "champion_candidate": "сильный кандидат",
    "human_review_candidate": "нужна ручная проверка",
    "portfolio_contributor": "добавлено в портфель",
    "archived": "архив",
    "cancelled": "отменено",
}

ACTION_RU = {
    "skeleton_created": "создана заготовка эксперимента",
    "memory_loaded": "загружена память исследований",
    "hypothesis_model_health_failed": "модель гипотез недоступна",
    "hypothesis_prompt": "отправлен запрос на гипотезу",
    "hypothesis_response": "получена гипотеза",
    "hypothesis_contract_rejected": "ответ гипотезы не прошел контракт",
    "hypothesis_lm_failed": "ошибка модели гипотез",
    "hypothesis_fallback": "использована запасная гипотеза",
    "class_assigned": "назначен класс стратегии",
    "coder_invoke": "запущена генерация кода",
    "coder_prompt": "отправлен запрос кодеру",
    "coder_response": "получен ответ кодера",
    "coder_done": "генерация кода завершена",
    "blocked_lm_studio": "LM Studio недоступна",
    "blocked_lm_studio_autofix": "LM Studio недоступна для автоисправления",
    "rejected_static": "статическая проверка отклонила код",
    "ok": "проверка пройдена",
    "sandbox_written": "файл записан в песочницу",
    "skipped": "шаг пропущен",
    "awaiting_nt_compile": "ожидание компиляции NinjaTrader",
    "awaiting judge model": "ожидание ответа модели-аналитика",
    "baseline_recorded": "зафиксировано состояние DLL до компиляции",
    "auto_f5_sent": "F5 автоматически отправлен в редактор NinjaScript",
    "waiting_dll": "ожидание обновления NinjaTrader.Custom.dll",
    "waiting for NT compile / dll change": "NinjaTrader компилирует: ожидается изменение DLL",
    "dll_changed": "компиляция завершена: DLL обновлена",
    "request_written": "запрос на бэктест записан",
    "checked": "проверка завершена",
    "smoke_submitted": "smoke-бэктест отправлен",
    "smoke_checked": "результат smoke-бэктеста проверен",
    "smoke_data_invalid": "smoke остановлен: исторические данные не подтверждены",
    "circuit_breaker_open": "защитный выключатель остановил запуск",
    "contract_selected": "выбран контракт с подтверждёнными минутными данными",
    "parallel_design_started": "начата параллельная разработка следующей стратегии",
    "parallel_design_ready": "параллельный проект стратегии готов",
    "parallel_design_failed": "ошибка параллельной разработки",
    "parallel_design_reused": "параллельный проект передан в исполнение",
    "mutation_planned": "мутация стратегии запланирована",
    "timeout_no_dll_change": "тайм-аут: DLL не изменилась",
    "compile_failed": "компиляция не удалась",
    "autofix_invoke": "запущено автоисправление",
    "autofix_rewrite": "файл переписан автоисправлением",
    "visible": "класс виден в каталоге",
    "evaluated": "проверка выполнена",
    "submitting": "отправка бэктеста",
    "submitted": "бэктест отправлен",
    "submit_failed": "отправка бэктеста не удалась",
    "awaiting_result": "ожидание результата",
    "result_seen": "результат найден",
    "result_timeout": "тайм-аут ожидания результата",
    "job_failed_or_cancelled": "задача упала или отменена",
    "building_pack": "сбор пакета анализа",
    "score_computed": "оценка рассчитана",
    "set": "вердикт установлен",
    "finalized": "вердикт финализирован",
    "finalize_failed": "финализация не удалась",
    "finalize_blocked": "финализация заблокирована",
    "strategy_started": "стратегия запущена",
    "strategy_finished": "стратегия завершена",
    "iteration_started": "итерация запущена",
    "iteration_finished": "итерация завершена",
    "mutation_prepare": "подготовка мутации",
    "mutation_prompt": "подготовлен запрос мутации",
    "mutation_failed": "мутация не удалась",
    "pipeline_crashed": "пайплайн аварийно завершился",
    "cancel_requested": "запрошена отмена",
    "run_cancel_requested": "запрошена отмена запуска",
    "parse_error": "ошибка чтения строки лога",
}


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


def _status_label(status: Any) -> str:
    raw = str(status or "")
    return STATUS_RU.get(raw, raw)


def _action_label(action: str, fields: Dict[str, Any]) -> str:
    if " -> " in action:
        left, right = action.split(" -> ", 1)
        return f"{_status_label(left)} → {_status_label(right)}"
    return ACTION_RU.get(action, action)


def _reason_label(reason: Any) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return raw
    exact = {
        "entering intake": "переход к подготовке эксперимента",
        "dry_run only": "сухой запуск без полной цепочки",
        "skip_compile=true, waiting on manual F5": "компиляция пропущена: ожидается ручной F5",
        "class visible in NT catalog": "класс найден в каталоге NinjaTrader",
        "compile chain did not succeed": "цепочка компиляции не завершилась успешно",
        "autofix loop exhausted": "лимит автоисправлений исчерпан",
        "coder returned no contract-valid C#": "кодер не вернул C# по контракту",
        "autofix produced invalid source": "автоисправление вернуло некорректный исходный код",
        "user requested extension": "пользователь запросил продление",
        "user cancelled": "пользователь отменил запуск",
        "no result.json within 30 min": "result.json не появился за 30 минут",
        "ok": "все нормально",
        "overtrading_risk": "риск слишком частых сделок",
        "zero_theoretical_signals": "нет теоретических сигналов",
        "below_min_theoretical_signals": "меньше минимального числа теоретических сигналов",
        "compile_failed": "ошибка компиляции",
    }
    if raw in exact:
        return exact[raw]
    match = re.fullmatch(r"compile attempt (\d+)", raw)
    if match:
        return f"попытка компиляции {match.group(1)}"
    match = re.fullmatch(r"job (.+) submitted", raw)
    if match:
        return f"задача {match.group(1)} отправлена"
    match = re.fullmatch(r"job (.+)", raw)
    if match:
        return f"задача {match.group(1)}"
    if raw.startswith("verdict ") and "mutating same cell" in raw:
        verdict = raw[len("verdict "):].split(" ", 1)[0]
        return f"вердикт {verdict}: пробуем мутацию той же ячейки"
    if raw.startswith("signal sanity failed: "):
        return "проверка сигналов не пройдена: " + raw.split(": ", 1)[1]
    if raw.startswith("signal sanity blocked by environment: "):
        return "проверка сигналов заблокирована окружением: " + raw.split(": ", 1)[1]
    if raw.startswith("submit error: "):
        return "ошибка отправки: " + raw.split(": ", 1)[1]
    if raw.startswith("smoke submit error: "):
        return "ошибка smoke-submit: " + raw.split(": ", 1)[1]
    if raw.startswith("unhandled pipeline error: "):
        return "необработанная ошибка пайплайна: " + raw.split(": ", 1)[1]
    return raw


def _localized_fields(stage: str, action: str, level: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    localized: Dict[str, Any] = {
        "stage_ru": STAGE_RU.get(stage, stage),
        "action_ru": _action_label(action, fields),
        "level_ru": LEVEL_RU.get(level, level),
    }
    if fields.get("from_status") is not None:
        localized["from_status_ru"] = _status_label(fields.get("from_status"))
    if fields.get("to_status") is not None:
        localized["to_status_ru"] = _status_label(fields.get("to_status"))
    if fields.get("final_status") is not None:
        localized["final_status_ru"] = _status_label(fields.get("final_status"))
    if fields.get("status") is not None:
        localized["status_ru"] = _status_label(fields.get("status"))
    if fields.get("reason") is not None:
        localized["reason_ru"] = _reason_label(fields.get("reason"))
    return localized


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
    localized = {
        k: _truncate(v) for k, v in _localized_fields(stage, action, level, safe_fields).items()
        if k not in safe_fields
    }
    rec = {
        "ts": _now(),
        "stage": stage,
        "action": action,
        "level": level,
        **localized,
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
