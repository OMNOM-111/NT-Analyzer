"""Governance source-of-truth for project rules and document sync.

This module keeps human-readable governance docs and machine-readable runtime
defaults aligned. The editable source of truth lives under data/governance/ and
the rendered Markdown lives under docs/governance/.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import runtime_env


TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".py", ".js", ".json", ".html"}
PROJECT_OWNER = "Черевко Дмитро"
INTERNAL_AMENDMENT_RE = re.compile(
    r"\n?<!--\s*STRATFORGE_INTERNAL_AMENDMENT\b.*?-->",
    flags=re.IGNORECASE | re.DOTALL,
)

# This is an API boundary, not just a navigation preference. Documents absent
# from this set remain available to owner/docs administrators but cannot be
# enumerated or fetched by an ordinary account through /api/governance/*.
PUBLIC_DOCUMENT_IDS = frozenset({
    "project-overview", "charter", "laws", "local-ai-laws", "sync-map",
    "legacy-rules", "legacy-registry", "legacy-hub-deploy", "legacy-family-plan",
    "risk-profile", "ai-lab-run-controls", "ai-lab-quality",
    "ai-lab-cloud-agents", "ai-lab-competitive-feedback",
    "ai-staff-index", "ai-staff-vitek", "ai-staff-chief", "ai-staff-dialogue",
    "ai-staff-marina", "ai-staff-tolik", "ai-staff-nikita", "ai-staff-ivan",
    "ai-staff-recovery", "north-star-2026",
    *(f"legal-{number:02d}" for number in range(9)),
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def project_root() -> Path:
    env = os.environ.get("NT_ANALYZER_ROOT")
    if env:
        path = Path(env).expanduser().resolve()
        if (path / "app").is_dir():
            return path
    return Path(__file__).resolve().parent.parent


def workspace_root() -> Path:
    return project_root().parent


def data_dir() -> Path:
    path = runtime_env.data_path("governance", project_root=project_root())
    path.mkdir(parents=True, exist_ok=True)
    return path


def docs_dir() -> Path:
    # Explicit Production runs from an immutable release.  Generated
    # governance documents are mutable runtime state and therefore must live
    # under the isolated data root just like the staging/development copy.
    # Keep the historical implicit-environment behaviour for library callers
    # that have not selected a deployment boundary yet.
    isolated_runtime = runtime_env.is_staging() or (
        runtime_env.is_production() and runtime_env.environment_explicit()
    )
    path = (
        runtime_env.data_path("governance-rendered", project_root=project_root())
        if isolated_runtime
        else project_root() / "docs" / "governance"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def laws_path() -> Path:
    return data_dir() / "laws.json"


def documents_path() -> Path:
    return data_dir() / "documents.json"


def change_log_path() -> Path:
    return data_dir() / "change_log.jsonl"


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace_root().resolve())).replace("\\", "/")
    except Exception:
        try:
            return str(path.resolve().relative_to(project_root().resolve())).replace("\\", "/")
        except Exception:
            return str(path).replace("\\", "/")


def _resolve_doc_path(rel_path: str) -> Path:
    raw = Path(rel_path)
    if raw.is_absolute():
        return raw
    return (project_root() / raw).resolve()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def _write_json(path: Path, payload: Any) -> None:
    _write_if_changed(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_text(path: Path, content: str) -> None:
    _write_if_changed(path, content.rstrip() + "\n")


def _write_if_changed(path: Path, content: str) -> None:
    # Generated governance files are rewritten on every backend start. Writing
    # only when the rendered bytes actually differ keeps a clean checkout clean
    # after a deterministic render (Phase 11 clean-checkout requirement).
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_text(encoding="utf-8") == content:
            return
    except (OSError, UnicodeDecodeError):
        pass
    path.write_text(content, encoding="utf-8")


def _preview_text(value: str, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _hash_text(value: str) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:12]


def _semantic_change_text(before: str, after: str) -> tuple[str, str]:
    """Return the first meaningful removed/added line for the compact journal."""
    before_lines = str(before or "").splitlines()
    after_lines = str(after or "").splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    removed: List[str] = []
    added: List[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"delete", "replace"}:
            removed.extend(line.strip() for line in before_lines[i1:i2] if line.strip())
        if tag in {"insert", "replace"}:
            added.extend(line.strip() for line in after_lines[j1:j2] if line.strip())
        if removed and added:
            break
    return _preview_text(removed[0] if removed else "", 120), _preview_text(added[0] if added else "", 120)


def _line_diff(before: str, after: str, *, max_rows: int = 400) -> List[Dict[str, str]]:
    """Line-level diff for the revision journal (removed=red, added=green)."""
    before_lines = str(before or "").splitlines()
    after_lines = str(after or "").splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    rows: List[Dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            segment = before_lines[i1:i2]
            if len(segment) > 6:
                for text in segment[:3]:
                    rows.append({"op": "ctx", "text": text})
                rows.append({"op": "ctx", "text": "…"})
                for text in segment[-3:]:
                    rows.append({"op": "ctx", "text": text})
            else:
                rows.extend({"op": "ctx", "text": text} for text in segment)
        elif tag == "delete":
            rows.extend({"op": "del", "text": text} for text in before_lines[i1:i2])
        elif tag == "insert":
            rows.extend({"op": "add", "text": text} for text in after_lines[j1:j2])
        elif tag == "replace":
            rows.extend({"op": "del", "text": text} for text in before_lines[i1:i2])
            rows.extend({"op": "add", "text": text} for text in after_lines[j1:j2])
        if len(rows) >= max_rows:
            rows = rows[:max_rows]
            rows.append({"op": "ctx", "text": "… (diff обрезан)"})
            break
    return rows


def _short_version_id(*parts: Any) -> str:
    seed = "|".join(str(p or "") for p in parts)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]


DEFAULT_LAWS: List[Dict[str, Any]] = [
    {
        "id": "GOV-RISK-001",
        "key": "starting_capital_usd",
        "group": "capital_risk",
        "audience": "project",
        "title": "Базовый StartingCapital на одну deploy-ячейку",
        "summary": "Новые исследования и новые профили стартуют от одного общего allocated capital.",
        "kind": "number",
        "unit": "USD",
        "value": 2000,
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "NT-Analyzer/docs/strategies/risk-profile.md",
        ],
        "dynamic_targets": [
            "app/jobqueue.py research gate",
            "app/ai_lab/backtest.py",
            "app/ai_lab/generator.py",
            "app/ai_lab/knowledge.py",
            "tools/research/python/research_lib.py",
            "ui backtest defaults",
            "ui AI Lab capital presets",
        ],
        "review_targets": [
            "existing ready/paper profiles with locked StartingCapital",
            "data/ops/registry.json and trading runtime cards",
            "historical research bundles and legacy strategy registry docs",
        ],
        "warning": "Смена capital меняет только общий дефолт. Исторические результаты и существующие locked profiles требуют ручной ревалидации.",
    },
    {
        "id": "GOV-RISK-002",
        "key": "max_drawdown_pct",
        "group": "capital_risk",
        "audience": "project",
        "title": "Promotion gate по MaxDD",
        "summary": "Абсолютный drawdown не должен превышать долю от зафиксированного StartingCapital.",
        "kind": "number",
        "unit": "%",
        "value": 15,
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "tools/research/python/research_lib.py",
        ],
        "dynamic_targets": [
            "tools/research/python/research_lib.py drawdown gate",
            "ui docs sync",
        ],
        "review_targets": [
            "legacy reports that mention fixed -$300 drawdown budget",
        ],
    },
    {
        "id": "GOV-RISK-003",
        "key": "round_turn_commission_floor_usd",
        "group": "execution_costs",
        "audience": "project",
        "title": "Минимальная честная комиссия backtest",
        "summary": "Research и AI Lab не используют значение ниже project floor за round turn на контракт.",
        "kind": "number",
        "unit": "USD",
        "value": 1.90,
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
            "NT-Analyzer/ai_lab/prompts/system_coder.txt",
        ],
        "dynamic_targets": [
            "app/jobqueue.py research gate",
            "app/ai_lab/backtest.py",
            "app/ai_lab/generator.py",
            "app/ai_lab/knowledge.py",
            "tools/research/python/research_lib.py",
        ],
        "review_targets": [
            "ops metrics that depend on per-strategy locked params",
            "legacy paper/demo profiles with older fee assumptions",
        ],
    },
    {
        "id": "GOV-RISK-004",
        "key": "slippage_ticks_floor",
        "group": "execution_costs",
        "audience": "project",
        "title": "Минимальный slippage для research",
        "summary": "Рабочие проверки не используют slippage ниже project floor.",
        "kind": "number",
        "unit": "ticks",
        "value": 1,
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
            "NT-Analyzer/ai_lab/prompts/system_coder.txt",
        ],
        "dynamic_targets": [
            "app/jobqueue.py research gate",
            "app/ai_lab/backtest.py",
            "app/ai_lab/generator.py",
            "app/ai_lab/knowledge.py",
            "tools/research/python/research_lib.py",
        ],
        "review_targets": [
            "legacy reports with slip=1/slip=2 commentary",
        ],
    },
    {
        "id": "GOV-RISK-005",
        "key": "order_fill_resolution",
        "group": "execution_costs",
        "audience": "project",
        "title": "Базовый fill mode",
        "summary": "Research-grade проверки идут только через High fill.",
        "kind": "string",
        "value": "High",
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
        ],
        "dynamic_targets": [
            "app/jobqueue.py validation",
            "tools/research/python/research_lib.py build_job_body",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-PROC-001",
        "key": "research_flow",
        "group": "process",
        "audience": "project",
        "title": "Канонический цикл разработки",
        "summary": "Новые стратегии проходят путь Research Hub -> Deploy wrapper.",
        "kind": "string",
        "value": "Research Hub -> Deploy wrapper",
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "РАЗРАБОТКА СТРАТЕГИЙ/Реестр стратегий.md",
        ],
        "dynamic_targets": [
            "governance docs only",
        ],
        "review_targets": [
            "legacy references to missing transition documents",
        ],
    },
    {
        "id": "GOV-PROC-002",
        "key": "intraday_only_default",
        "group": "process",
        "audience": "project",
        "title": "IntradayOnly по умолчанию",
        "summary": "Новые исследования и новые профили по умолчанию считаются без overnight-hold.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "NT-Analyzer/docs/strategies/risk-profile.md",
        ],
        "dynamic_targets": [
            "ui backtest risk profile defaults",
            "tools/research/python/research_lib.py",
        ],
        "review_targets": [
            "existing profiles with explicit IntradayOnly=false",
        ],
    },
    {
        "id": "GOV-PROC-003",
        "key": "paper_before_live_required",
        "group": "promotion",
        "audience": "project",
        "title": "Paper forward обязателен до live",
        "summary": "Live запрещён без paper_ready, журнала и отдельного ручного решения владельца.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "NT-Analyzer/app/ops.py",
        ],
        "dynamic_targets": [
            "governance docs",
            "ui docs sync",
        ],
        "review_targets": [
            "manual operating procedures",
        ],
    },
    {
        "id": "GOV-PROC-004",
        "key": "runtime_locked_params_must_match",
        "group": "promotion",
        "audience": "project",
        "title": "Runtime instance должен совпадать с locked params",
        "summary": "Перед paper/demo запуском runtime-параметры не должны расходиться с утвержденным профилем.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "NT-Analyzer/app/static/trading.js",
        ],
        "dynamic_targets": [
            "governance docs",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-PROC-005",
        "key": "nt_source_of_truth",
        "group": "promotion",
        "audience": "project",
        "title": "NinjaTrader — источник истины по backtest",
        "summary": "Результаты принимаются только из канонического пути NT-Analyzer bridge -> NinjaTrader.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
        ],
        "dynamic_targets": [
            "governance docs",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-001",
        "key": "ai_lab_sandbox_only",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Локальный ИИ пишет только в sandbox",
        "summary": "AI Lab не пишет production class, production CELL и не трогает рабочие стратегии напрямую.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_RUN_CONTROLS.md",
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
            "NT-Analyzer/ai_lab/prompts/system_coder.txt",
        ],
        "dynamic_targets": [
            "app/ai_lab/knowledge.py",
            "app/ai_lab/generator.py",
            "app/ai_lab/guards.py",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-002",
        "key": "ai_lab_runtime_actions_forbidden",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Локальный ИИ не запускает live/paper/demo/account actions",
        "summary": "AI Lab делает только историческое исследование и не имеет права на runtime/account операции.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_RUN_CONTROLS.md",
            "NT-Analyzer/ai_lab/prompts/system_coder.txt",
        ],
        "dynamic_targets": [
            "app/ai_lab/knowledge.py",
            "app/ai_lab/goal_parser.py",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-003",
        "key": "ai_lab_no_add_data_series",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Локальный ИИ не использует AddDataSeries",
        "summary": "Sandbox-стратегии только single instrument / single timeframe.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
            "NT-Analyzer/ai_lab/prompts/system_coder.txt",
        ],
        "dynamic_targets": [
            "app/ai_lab/knowledge.py",
            "app/ai_lab/validator.py",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-004",
        "key": "ai_lab_session_window_pt",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Локальный ИИ обязан задавать явное PT-окно входа",
        "summary": "По умолчанию sandbox shell использует фиксированное PT entry window и force-flat на конце окна.",
        "kind": "string",
        "value": "06:30-12:30 PT",
        "source_refs": [
            "NT-Analyzer/ai_lab/prompts/system_coder.txt",
        ],
        "dynamic_targets": [
            "app/ai_lab/generator.py",
            "app/ai_lab/knowledge.py",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-005",
        "key": "ai_lab_stop_target_required",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Локальный ИИ обязан задавать stop/target/daily loss/force-flat",
        "summary": "Без явной risk shell стратегия считается невалидной.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "NT-Analyzer/ai_lab/prompts/system_coder.txt",
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
        ],
        "dynamic_targets": [
            "app/ai_lab/generator.py",
            "app/ai_lab/knowledge.py",
            "app/ai_lab/validator.py",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-006",
        "key": "ai_lab_reference_grounding_required",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Локальный ИИ обязан опираться на reference library",
        "summary": "Новая стратегия не генерируется из пустого контекста; сначала reference + lessons + rejected patterns.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "NT-Analyzer/ai_lab/prompts/system_coder.txt",
            "NT-Analyzer/app/ai_lab/knowledge.py",
        ],
        "dynamic_targets": [
            "app/ai_lab/knowledge.py",
            "app/ai_lab/prompts/system_coder.txt",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-007",
        "key": "ai_lab_cloud_local_first_only",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Облачный API работает только как local-first fallback",
        "summary": "Платная модель вызывается только после зафиксированной неудачи разрешённой локальной роли; API не является основным двигателем run.",
        "kind": "boolean",
        "value": True,
        "source_refs": ["NT-Analyzer/docs/agents/AI_LAB_CLOUD_AGENTS.md"],
        "dynamic_targets": [
            "app/ai_lab/cloud_agents.py",
            "app/ai_lab/orchestrator.py",
            "app/ai_lab/generator.py",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-008",
        "key": "ai_lab_cloud_budget_caps",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Бюджет облачного API имеет жёсткие потолки",
        "summary": "Вызов блокируется до обращения к провайдеру, если reservation превышает месячный или per-run остаток.",
        "kind": "string",
        "value": "20.00 USD/month; 0.50 USD/run",
        "source_refs": ["NT-Analyzer/docs/agents/AI_LAB_CLOUD_AGENTS.md"],
        "dynamic_targets": ["app/ai_lab/cloud_agents.py", "ui AI Lab cloud-agent settings"],
        "review_targets": ["provider invoice versus local cost audit"],
    },
    {
        "id": "GOV-AI-009",
        "key": "ai_lab_cloud_output_not_verdict",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "API output не является verdict",
        "summary": "Cloud-ответ не может обойти validator, compile, backtest, arbitration, governance или ручное promotion-решение.",
        "kind": "boolean",
        "value": True,
        "source_refs": [
            "NT-Analyzer/docs/agents/AI_LAB_CLOUD_AGENTS.md",
            "NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
        ],
        "dynamic_targets": ["app/ai_lab/cloud_agents.py", "app/ai_lab/orchestrator.py"],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-010",
        "key": "ai_lab_cloud_secrets_private",
        "group": "local_ai",
        "audience": "local_ai",
        "title": "Облачные ключи и prompts не раскрываются",
        "summary": "Ключи хранятся только локально; status API возвращает флаги. Cloud usage audit хранит prompt hash и usage, но не prompt/response text.",
        "kind": "boolean",
        "value": True,
        "source_refs": ["NT-Analyzer/docs/agents/AI_LAB_CLOUD_AGENTS.md"],
        "dynamic_targets": ["app/local_secrets.py", "app/ai_lab/cloud_agents.py"],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-011", "key": "orchestrator_discussion_is_not_execution",
        "group": "local_ai", "audience": "local_ai",
        "title": "Вопрос об исследовании не является командой запуска",
        "summary": "Вопросы о выборе стратегии и обсуждение гипотез дают содержательный ответ без изменения mission state; запуск разрешён только явной командой владельца в текущем сообщении.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/chief_agent.py"], "review_targets": [],
    },
    {
        "id": "GOV-AI-012", "key": "orchestrator_lm_studio_required",
        "group": "local_ai", "audience": "local_ai",
        "title": "LM Studio обязательна до начала research",
        "summary": "До создания эксперимента Orchestrator самостоятельно запускает LM Studio и model server; fallback разрешён только после трёх зафиксированных неудач либо по явной команде владельца.",
        "kind": "string", "value": "3 bounded self-heal attempts", "source_refs": [],
        "dynamic_targets": ["app/ai_lab/chief_agent.py", "app/ai_lab/bootstrap.py"], "review_targets": [],
    },
    {
        "id": "GOV-AI-013", "key": "orchestrator_notifications_change_only",
        "group": "local_ai", "audience": "local_ai",
        "title": "Уведомления владельцу только по изменению фактов",
        "summary": "Нормальный ход работы не отправляется; один experiment и одно завершение mission дают не более одного отчёта, а полностью одинаковое Telegram-сообщение подавляется на 24 часа.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/chief_agent.py", "app/telegram_service.py"], "review_targets": [],
    },
    {
        "id": "GOV-AI-014", "key": "orchestrator_one_strategy_until_exhausted",
        "group": "local_ai", "audience": "local_ai",
        "title": "Одна стратегия до исчерпания гипотез",
        "summary": "Orchestrator меняет фильтры, входы, выходы и режимы внутри одной основы и переходит к следующей только после кандидата либо доказанного исчерпания содержательно разных вариантов.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/chief_agent.py", "app/ai_lab/runner.py"], "review_targets": [],
    },
    {
        "id": "GOV-AI-015", "key": "orchestrator_discussion_uses_strongest_model",
        "group": "local_ai", "audience": "local_ai",
        "title": "Содержательное обсуждение использует strongest reasoning lane",
        "summary": "Обсуждение, диагностика, выбор стратегии и планирование идут через critical-маршрут к самой сильной доступной модели; простые операционные команды остаются в быстром маршруте.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/chief_agent.py", "app/ai_lab/agent_router.py"], "review_targets": [],
    },
    {
        "id": "GOV-AI-016", "key": "orchestrator_dialogue_context_and_completeness",
        "group": "local_ai", "audience": "local_ai",
        "title": "Ответ менеджера обязан быть контекстным и завершённым",
        "summary": "Перед стратегическим ответом читаются project docs, reference library, lessons, user research и фактические эксперименты; короткий, обещающий или оборванный ответ автоматически заменяется полным, а команда «начинай» продолжает согласованный план этого чата.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/chief_agent.py", "app/ai_lab/knowledge.py", "app/ai_lab/universal_llm.py"], "review_targets": [],
    },
    {
        "id": "GOV-AI-017", "key": "ai_roles_compete_through_feedback",
        "group": "local_ai", "audience": "local_ai",
        "title": "ИИ-роли улучшаются через конкурентную обратную связь",
        "summary": "Роли Analyst/Coder/Judge/Reviewer сравниваются по проверяемому результату; слабый ответ не наказывается, а получает детальный feedback и временно меньший приоритет следующего вызова, пока не восстановит качество.",
        "kind": "boolean", "value": True,
        "source_refs": ["NT-Analyzer/docs/agents/AI_LAB_COMPETITIVE_FEEDBACK.md"],
        "dynamic_targets": ["governance docs", "docs/AI_LAB_COMPETITIVE_FEEDBACK.md"],
        "review_targets": ["app/ai_lab/agent_router.py role ranking", "agent usage/feedback ledger", "AI Lab UI feedback report"],
    },
    {
        "id": "GOV-AI-018", "key": "runtime_reconnect_fails_closed",
        "group": "local_ai", "audience": "local_ai",
        "title": "Переподключение NinjaTrader не подменяет торговое соединение Datafeed",
        "summary": "Автоматический reconnect разрешён только для фактически активной Realtime-стратегии на paper/demo-счёте; системные Backtest/Sim/Playback-счета, исторические экземпляры, live-счета и Datafeed исключены. Bridge не выбирает неоднозначное соединение и не отключает другие соединения автоматически.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/chief_agent.py", "app/runtime.py", "bridge/src/Runtime/RuntimeCommandProcessor.cs"],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-019", "key": "orchestrator_no_false_refusal",
        "group": "local_ai", "audience": "local_ai",
        "title": "Оркестратор не вправе отказать в выполнимой задаче",
        "summary": "До ответа «не могу» Orchestrator обязан проверить детерминированный intent и все штатные обработчики capability_map. Если действие доступно внутри приложения, оно передаётся профильному исполнителю независимо от выбранной версии модели и без требования назвать персону. Отказ допустим только вне карты возможностей либо при фактической ошибке инфраструктуры; причина и доступный следующий шаг указываются явно.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/intent_classifier.py", "app/ai_lab/capability_map.py", "app/ai_lab/chief_agent.py"],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-020", "key": "orchestrator_semantic_command_resolution",
        "group": "local_ai", "audience": "local_ai",
        "title": "Команды понимаются по смыслу, а подтверждение следует факту",
        "summary": "Перед маршрутизацией Orchestrator нормализует речь, раскладку и однозначные тикеры; уверенные команды исполняются детерминированно, неоднозначные короткие команды проверяет быстрая модель только в пределах capability allowlist. Контекст не подменяет явно введённый инструмент, а Telegram не теряет ответ и не подтверждает невыполненное действие.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": [
            "app/ai_lab/command_language.py", "app/ai_lab/intent_classifier.py",
            "app/ai_lab/capability_map.py", "app/telegram_service.py",
        ],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-021", "key": "owner_visible_execution_metadata_only",
        "group": "local_ai", "audience": "local_ai",
        "title": "Владелец видит исполнителя и ход работы, но не скрытые рассуждения",
        "summary": "Aurora и Telegram показывают фактического агента, модель/provider и проверяемый статус действия. Provider chain-of-thought не сохраняется и не выводится; вместо него используются короткие публичные стадии работы.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/chief_agent.py", "app/server.py", "app/static/aurora/assets/ui.js", "app/telegram_service.py"],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-022", "key": "capability_agent_and_completion_invariants",
        "group": "local_ai", "audience": "local_ai",
        "title": "Capability закрепляет исполнителя, а завершение подтверждает целевая система",
        "summary": "Финансовая capability всегда принадлежит Марине, lifecycle стратегии — Толику, графики — Ивану, runtime connection — Виктору. Модель не может разорвать эту связь. Поручение не становится completed по обещанию или пустому actions: требуется verified completed action либо подтверждение целевой подсистемы.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/vitek.py", "app/ai_lab/capability_map.py", "app/ai_lab/chief_agent.py"],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-023", "key": "aurora_telegram_conversation_strict_sync",
        "group": "local_ai", "audience": "local_ai",
        "title": "Один диалог Aurora соответствует одной теме Telegram",
        "summary": "Исходная реплика, уточнение, действие и итог сохраняют один conversation_id. При ошибке topic mapping сообщение остаётся в долговечной очереди и не отправляется в General; неизвестная входящая тема не подменяется default-диалогом.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/telegram_service.py", "app/ai_lab/chief_agent.py", "app/durable.py"],
        "review_targets": [],
    },
    {
        "id": "GOV-AI-024", "key": "negation_and_clarification_are_authoritative",
        "group": "local_ai", "audience": "local_ai",
        "title": "Отрицание запрещает действие, а пояснение возвращается тому же исполнителю",
        "summary": "Фразы «не запускай», «ничего не восстанавливай» и вопросы о причине не превращаются в команды. Ответ владельца на needs_input передаётся в том же диалоге и тому же профильному агенту; подтверждение не подписывается именем другого специалиста.",
        "kind": "boolean", "value": True, "source_refs": [],
        "dynamic_targets": ["app/ai_lab/intent_classifier.py", "app/ai_lab/chief_agent.py", "app/vitek.py"],
        "review_targets": [],
    },
]


DEFAULT_DOCUMENTS: Dict[str, Any] = {
    "schema_version": "1.0",
    "updated_at_utc": _now_iso(),
    "documents": [
        {
            "id": "project-overview",
            "title": "OVERVIEW",
            "label": "Главное: краткое предисловие",
            "category": "governance",
            "path": "docs/governance/OVERVIEW.md",
            "editable_kind": "none",
            "audience": "user",
        },
        {
            "id": "governance-readme",
            "title": "README",
            "label": "Индекс governance-документов",
            "category": "governance",
            "path": "docs/governance/README.md",
            "editable_kind": "none",
        },
        {
            "id": "charter",
            "title": "CHARTER",
            "label": "Устав проекта",
            "category": "governance",
            "path": "docs/governance/CHARTER.md",
            "editable_kind": "markdown",
            "audience": "user",
        },
        {
            "id": "roles",
            "title": "ROLES",
            "label": "Роли людей и ИИ",
            "category": "governance",
            "path": "docs/governance/ROLES.md",
            "editable_kind": "markdown",
        },
        {
            "id": "laws",
            "title": "LAWS",
            "label": "Законы проекта",
            "category": "governance",
            "path": "docs/governance/LAWS.md",
            "editable_kind": "laws",
            "audience": "project",
        },
        {
            "id": "local-ai-laws",
            "title": "LOCAL_AI_LAWS",
            "label": "Законы локального ИИ",
            "category": "governance",
            "path": "docs/governance/LOCAL_AI_LAWS.md",
            "editable_kind": "laws",
            "audience": "local_ai",
        },
        {
            "id": "registry-policy",
            "title": "REGISTRY_POLICY",
            "label": "Политика реестра стратегий",
            "category": "governance",
            "path": "docs/governance/REGISTRY_POLICY.md",
            "editable_kind": "markdown",
        },
        {
            "id": "sync-map",
            "title": "SYNC_MAP",
            "label": "Карта синхронизации правил",
            "category": "governance",
            "path": "docs/governance/SYNC_MAP.md",
            "editable_kind": "none",
            "audience": "user",
        },
        {
            "id": "legacy-rules",
            "title": "Legacy Rules",
            "label": "Старые общие правила",
            "category": "legacy",
            "path": "../РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md",
            "editable_kind": "none",
        },
        {
            "id": "legacy-registry",
            "title": "Legacy Registry",
            "label": "Старый реестр стратегий",
            "category": "legacy",
            "path": "../РАЗРАБОТКА СТРАТЕГИЙ/Реестр стратегий.md",
            "editable_kind": "none",
        },
        {
            "id": "legacy-hub-deploy",
            "title": "Legacy Hub Deploy",
            "label": "Переход: Research Hub -> Deploy",
            "category": "legacy",
            "path": "../РАЗРАБОТКА СТРАТЕГИЙ/Двухэтапный цикл Research Hub и Deploy.md",
            "editable_kind": "none",
        },
        {
            "id": "legacy-family-plan",
            "title": "Legacy Family Plan",
            "label": "Переход в семьи и новый цикл",
            "category": "legacy",
            "path": "../РАЗРАБОТКА СТРАТЕГИЙ/План перехода стратегий в семьи и новый цикл.md",
            "editable_kind": "none",
        },
        {
            "id": "risk-profile",
            "title": "risk-profile",
            "label": "Technical risk profile contract",
            "category": "technical",
            "path": "docs/strategies/risk-profile.md",
            "editable_kind": "none",
            "audience": "user",
        },
        {
            "id": "ai-lab-run-controls",
            "title": "AI_STRATEGY_LAB_RUN_CONTROLS",
            "label": "AI Lab run controls",
            "category": "technical",
            "path": "docs/strategies/AI_STRATEGY_LAB_RUN_CONTROLS.md",
            "editable_kind": "none",
            "audience": "user",
        },
        {
            "id": "ai-lab-quality",
            "title": "AI_STRATEGY_LAB_QUALITY",
            "label": "AI Lab quality pipeline",
            "category": "technical",
            "path": "docs/strategies/AI_STRATEGY_LAB_QUALITY.md",
            "editable_kind": "none",
            "audience": "user",
        },
        {
            "id": "ai-lab-cloud-agents",
            "title": "AI_LAB_CLOUD_AGENTS",
            "label": "AI Lab cloud agents, roles and budget",
            "category": "technical",
            "path": "docs/agents/AI_LAB_CLOUD_AGENTS.md",
            "editable_kind": "none",
            "audience": "user",
        },
        {
            "id": "ai-lab-competitive-feedback",
            "title": "AI_LAB_COMPETITIVE_FEEDBACK",
            "label": "AI Lab competitive feedback contract",
            "category": "technical",
            "path": "docs/agents/AI_LAB_COMPETITIVE_FEEDBACK.md",
            "editable_kind": "none",
            "audience": "user",
        },
        {
            "id": "ai-lab-system-coder",
            "title": "system_coder",
            "label": "Локальный AI prompt contract",
            "category": "technical",
            "path": "ai_lab/prompts/system_coder.txt",
            "editable_kind": "none",
        },
        {
            "id": "legal-00", "title": "Ключевые юридические положения",
            "label": "Проект · краткое резюме перед регистрацией",
            "category": "legal", "path": "docs/legal/00_KEY_LEGAL_POINTS.md",
            "editable_kind": "none", "audience": "user", "draft": True,
            "created_at_utc": "2026-08-10T20:49:49Z",
            "created_author": "GitHub Copilot (Claude Opus 4.8) через VS Code",
            "created_author_kind": "ai", "created_initiator": PROJECT_OWNER,
            "created_reason": "Создан проект пользовательского юридического пакета.",
        },
        {
            "id": "legal-01", "title": "Пользовательское соглашение (ToS + EULA)",
            "label": "Проект · главный договор пользователя",
            "category": "legal", "path": "docs/legal/01_TERMS_OF_SERVICE_EULA.md",
            "editable_kind": "none", "audience": "user", "draft": True,
        },
        {
            "id": "legal-02", "title": "Политика конфиденциальности",
            "label": "Проект · обработка данных",
            "category": "legal", "path": "docs/legal/02_PRIVACY_POLICY.md",
            "editable_kind": "none", "audience": "user", "draft": True,
        },
        {
            "id": "legal-03", "title": "Раскрытие торговых и авто-рисков",
            "label": "Проект · market / software / AI / automation риски",
            "category": "legal", "path": "docs/legal/03_TRADING_AUTOMATION_RISK_DISCLOSURE.md",
            "editable_kind": "none", "audience": "user", "draft": True,
        },
        {
            "id": "legal-04", "title": "Сторонние интеграции и market data",
            "label": "Проект · NinjaTrader, TopstepX, Telegram, Google",
            "category": "legal", "path": "docs/legal/04_THIRD_PARTY_INTEGRATIONS_AND_MARKET_DATA.md",
            "editable_kind": "none", "audience": "user", "draft": True,
        },
        {
            "id": "legal-05", "title": "Раскрытие ИИ и обработки данных",
            "label": "Проект · что передаётся AI-провайдерам",
            "category": "legal", "path": "docs/legal/05_AI_DISCLOSURE_AND_DATA_PROCESSING.md",
            "editable_kind": "none", "audience": "user", "draft": True,
        },
        {
            "id": "legal-06", "title": "Согласие на автоматизацию / live",
            "label": "Проект · отдельные согласия и активация",
            "category": "legal", "path": "docs/legal/06_AUTOMATION_LIVE_TRADING_ACTIVATION_CONSENT.md",
            "editable_kind": "none", "audience": "user", "draft": True,
        },
        {
            "id": "legal-07", "title": "Электронный акцепт и согласия",
            "label": "Проект · clickwrap, версии, отзыв",
            "category": "legal", "path": "docs/legal/07_CONSENT_AND_ELECTRONIC_ACCEPTANCE_POLICY.md",
            "editable_kind": "none", "audience": "user", "draft": True,
        },
        {
            "id": "legal-08", "title": "Cookies и региональные приложения",
            "label": "Проект · Cookie/Analytics + California/EU",
            "category": "legal", "path": "docs/legal/08_COOKIE_ANALYTICS_AND_REGIONAL_ADDENDA.md",
            "editable_kind": "none", "audience": "user", "draft": True,
        },
    ],
}


CHARTER_DEFAULT = """# CHARTER — О StratForge AI

Дата актуализации: 2026-08-10

## Цель

StratForge AI — торгово-аналитическая платформа для анализа рынков и стратегий: realtime-графики и market data из нескольких источников, NinjaTrader через StratForge Connector, AI-агенты, бэктестинг, управление стратегиями и учебная торговля. Aurora — веб-интерфейс; `NT-Analyzer` — техническое имя репозитория.

## Границы продукта

- Источник истины по историческим результатам: `NinjaTrader -> StratForge Connector`.
- Проект работает в режиме `local-first`: код, документы, research-артефакты и AI Lab живут локально в репозитории.
- AI Lab — отдельная sandbox-ветвь для исследовательской генерации; production-код и paper/live процессы не пишутся туда автоматически.

## Базовые принципы

- Сначала правила, потом код и запуск.
- Один закон = один канонический источник в `data/governance/laws.json`.
- Человек утверждает цель, капитал, допуски к paper/live и изменения governance.
- Любое изменение, которое влияет на risk/budget/process, должно быть видно и в документах, и в runtime-источниках по возможности автоматически.
- Если автоматическая синхронизация опасна для уже одобренных профилей, система должна не молча переписать данные, а явно показать `manual review required`.

## Что считать готовым

- Governance-документы собраны в `docs/governance/`.
- Главные законы доступны в UI на `/ui/docs.html`.
- Изменение закона меняет source-of-truth JSON и пересобирает человекочитаемые Markdown-файлы.
- Будущие research/AI Lab/default UI-сценарии берут значения из governance, а не из россыпи захардкоженных чисел.
"""


ROLES_DEFAULT = """# ROLES

Дата актуализации: 2026-06-27

## Владелец проекта

- Утверждает цель проекта, законы, capital/risk, допуск к paper/live и любые спорные архитектурные изменения.
- Принимает решение, когда существующий approved profile нужно ревалидировать после смены закона.

## Cursor (Auto)

- Задача: навигация по репозиторию, анализ, подсказки, небольшие локальные правки.
- Не должен самовольно менять архитектуру, locked-стратегии и governance без явной задачи.

## Codex / GPT

- Задача: совместная разработка приложения, backend, UI, research tooling и governance-системы вместе с владельцем.
- Может делать крупные изменения, если они прозрачны, документированы и согласуются с законами проекта.

## Claude (VS)

- Альтернативный канал разработки и ревью.
- Роль по правам равна Codex/GPT: код, архитектура, стратегия, документация по явной задаче владельца.

## Gemini

- Основная зона: дизайн, UI/UX, визуальная структура, presentation-level решения.
- Также может выполнять и другие задачи по прямому поручению владельца.

## LM Studio / Local AI

- Используется для автономной генерации стратегий только в AI Lab sandbox.
- Работает строго по `LOCAL_AI_LAWS.md`, `system_coder.txt`, `knowledge.py` и lessons/reference library.
- Не имеет права запускать paper/live/demo, трогать production-strategies или выходить за sandbox.

## Правило фиксации изменений

Для изменений governance, стратегии или runtime-процесса должна быть понятна цепочка:

- кто инициировал изменение;
- кто исполнил;
- каким инструментом;
- какой закон или документ был затронут.
"""


REGISTRY_POLICY_DEFAULT = """# REGISTRY_POLICY

Дата актуализации: 2026-06-27

## Зачем нужен реестр

Реестр не заменяет законы. Его задача — отражать текущее состояние стратегий, семей и evidence после уже принятых решений.

## Что хранится в реестре

- `root family`, `strategy family`, `class_name`, `display_name`, статус.
- Locked params, которые реально утверждены для профиля.
- Последний валидный evidence bundle и краткий вывод.
- Следующее действие: `research`, `paper`, `review`, `archive`, `reject`.

## Что нельзя делать

- Нельзя переписывать исторический evidence задним числом после смены laws.
- Нельзя автоматически считать старые `ready/paper_ready` профили совместимыми с новым global capital/risk law без ревалидации.
- Нельзя хранить в реестре новые правила проекта, если их канонический дом — `LAWS.md`.

## Правило обновления

1. Сначала меняется law или профильный источник истины.
2. Потом обновляется реестр стратегии.
3. Если law затронул capital/risk/process, в реестре должна появиться пометка о необходимости ревалидации или о том, что профиль уже пересчитан.
"""


def _default_laws_doc() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "updated_at_utc": _now_iso(),
        "laws": copy.deepcopy(DEFAULT_LAWS),
    }


def _normalize_law_value(law: Dict[str, Any], value: Any) -> Any:
    kind = str(law.get("kind") or "").lower()
    if kind == "number":
        if isinstance(value, bool):
            raise ValueError("boolean is not a valid numeric value")
        number = float(value)
        if abs(number - round(number)) < 1e-9:
            return int(round(number))
        return round(number, 4)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ValueError("boolean value expected")
    return str(value).strip()


def _group_title(group: str) -> str:
    return {
        "capital_risk": "Капитал и риск",
        "execution_costs": "Комиссии, slippage и fill",
        "process": "Процесс разработки",
        "promotion": "Promotion и runtime-контроль",
        "local_ai": "Локальный ИИ и cloud fallback в AI Lab sandbox",
    }.get(group, group)


def _law_value_text(law: Dict[str, Any]) -> str:
    value = law.get("value")
    unit = str(law.get("unit") or "")
    kind = str(law.get("kind") or "").lower()
    if kind == "boolean":
        return "Да" if bool(value) else "Нет"
    if kind == "number" and unit:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return f"{value} {unit}".strip()
        if unit == "USD":
            return f"{number:.2f} USD"
        if unit == "%":
            return f"{number:.0f}%"
        if abs(number - round(number)) < 1e-9:
            return f"{int(round(number))} {unit}".strip()
        return f"{number:.2f} {unit}".strip()
    return str(value)


def _law_value_text_for(law: Dict[str, Any], value: Any) -> str:
    probe = copy.deepcopy(law)
    probe["value"] = value
    return _law_value_text(probe)


def _law_document_ids(law: Dict[str, Any]) -> List[str]:
    audience = str(law.get("audience") or "project")
    ids = ["project-overview", "sync-map"]
    ids.append("local-ai-laws" if audience == "local_ai" else "laws")
    return ids


def _normalize_documents_registry(data: Dict[str, Any]) -> Dict[str, Any]:
    docs = data.get("documents")
    if not isinstance(docs, list):
        docs = []
    existing = {
        str(row.get("id") or ""): copy.deepcopy(row)
        for row in docs
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in DEFAULT_DOCUMENTS["documents"]:
        key = str(row.get("id") or "")
        if not key:
            continue
        merged = copy.deepcopy(row)
        if key in existing:
            merged.update(existing[key])
        if key.startswith("legal-"):
            merged.setdefault("created_at_utc", "2026-08-10T20:49:49Z")
            merged.setdefault("created_author", "GitHub Copilot (Claude Opus 4.8) через VS Code")
            merged.setdefault("created_author_kind", "ai")
            merged.setdefault("created_initiator", PROJECT_OWNER)
            merged.setdefault("created_reason", "Создан проект пользовательского юридического пакета.")
        normalized.append(merged)
        seen.add(key)
    for row in docs:
        if not isinstance(row, dict):
            continue
        key = str(row.get("id") or "")
        if not key or key in seen:
            continue
        normalized.append(copy.deepcopy(row))
    data = copy.deepcopy(data)
    data["documents"] = normalized
    return data


def _normalize_history_entry(raw: Dict[str, Any], fallback_no: int) -> Dict[str, Any]:
    changes: List[Dict[str, Any]] = []
    raw_changes = raw.get("changes")
    if isinstance(raw_changes, list):
        for item in raw_changes:
            if not isinstance(item, dict):
                continue
            diff_rows = item.get("diff")
            changes.append({
                "field": str(item.get("field") or ""),
                "label": str(item.get("label") or item.get("field") or "Изменение"),
                "before": item.get("before"),
                "after": item.get("after"),
                "before_text": str(item.get("before_text") or ""),
                "after_text": str(item.get("after_text") or ""),
                "before_hash": str(item.get("before_hash") or ""),
                "after_hash": str(item.get("after_hash") or ""),
                "diff": [
                    {"op": str(row.get("op") or "ctx"), "text": str(row.get("text") or "")}
                    for row in diff_rows if isinstance(row, dict)
                ] if isinstance(diff_rows, list) else [],
            })
    if not changes:
        reason = str(raw.get("reason") or "").strip()
        if reason:
            changes.append({
                "field": "note",
                "label": "Изменение",
                "before": None,
                "after": None,
                "before_text": "",
                "after_text": reason,
                "before_hash": "",
                "after_hash": "",
                "diff": [],
            })
    document_ids = [
        str(item).strip()
        for item in (raw.get("document_ids") or [])
        if str(item).strip()
    ] if isinstance(raw.get("document_ids"), list) else []
    actor = str(raw.get("actor") or "system")
    author = str(raw.get("author") or actor)
    return {
        "amendment_no": int(raw.get("amendment_no") or fallback_no),
        "ts_utc": str(raw.get("ts_utc") or _now_iso()),
        "actor": actor,
        "author": author,
        "author_id": str(raw.get("author_id") or ""),
        "author_kind": str(raw.get("author_kind") or "human"),
        "initiator": str(raw.get("initiator") or "").strip(),
        "version_id": str(raw.get("version_id") or ""),
        "reason": str(raw.get("reason") or "").strip(),
        "entity_type": str(raw.get("entity_type") or "note"),
        "entity_id": str(raw.get("entity_id") or ""),
        "entity_title": str(raw.get("entity_title") or raw.get("entity_id") or raw.get("path") or "Изменение"),
        "document_ids": document_ids,
        "path": str(raw.get("path") or ""),
        "changes": changes,
    }


def _read_change_log_entries() -> List[Dict[str, Any]]:
    ensure_governance_files(render=False)
    path = change_log_path()
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    entries: List[Dict[str, Any]] = []
    next_fallback = 1
    for line in lines:
        raw_line = str(line or "").strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        entry = _normalize_history_entry(payload, next_fallback)
        entries.append(entry)
        next_fallback = max(next_fallback + 1, int(entry.get("amendment_no") or 0) + 1)
    entries.sort(key=lambda row: (int(row.get("amendment_no") or 0), str(row.get("ts_utc") or "")))
    return entries


def _next_amendment_no() -> int:
    entries = _read_change_log_entries()
    if not entries:
        return 1
    return max(int(row.get("amendment_no") or 0) for row in entries) + 1


def _append_change_log_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = copy.deepcopy(entry)
    payload["amendment_no"] = int(payload.get("amendment_no") or _next_amendment_no())
    payload["ts_utc"] = str(payload.get("ts_utc") or _now_iso())
    payload["actor"] = str(payload.get("actor") or "system")
    payload["author"] = str(payload.get("author") or payload["actor"])
    if not payload.get("version_id"):
        payload["version_id"] = _short_version_id(
            payload.get("entity_id"), payload["amendment_no"], payload["ts_utc"],
        )
    with change_log_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return _normalize_history_entry(payload, int(payload["amendment_no"]))


def read_change_log(limit: int = 100, *, entity_id: Optional[str] = None, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
    entries = _read_change_log_entries()
    if entity_id:
        entries = [row for row in entries if str(row.get("entity_id") or "") == entity_id]
    if document_id:
        entries = [
            row for row in entries
            if document_id in (row.get("document_ids") or []) or str(row.get("entity_id") or "") == document_id
        ]
    entries.sort(key=lambda row: (int(row.get("amendment_no") or 0), str(row.get("ts_utc") or "")), reverse=True)
    if limit > 0:
        return entries[:limit]
    return entries


def _history_line(entry: Dict[str, Any]) -> str:
    change_parts: List[str] = []
    for item in (entry.get("changes") or [])[:2]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("field") or "Изменение")
        before_text = str(item.get("before_text") or "")
        after_text = str(item.get("after_text") or "")
        if before_text or after_text:
            change_parts.append(f"{label}: `{before_text or '—'}` -> `{after_text or '—'}`")
    detail = "; ".join(change_parts) or str(entry.get("reason") or "Без деталей")
    return (
        f"- Поправка {entry.get('amendment_no')} · {entry.get('ts_utc')} · "
        f"`{entry.get('actor')}` · {entry.get('entity_title')}: {detail}"
    )


def _internal_amendment_comment() -> str:
    """Hidden provenance for generated Markdown; UI history remains the display."""
    latest = read_change_log(limit=1)
    if not latest:
        return ""
    entry = latest[0]
    text = " | ".join((
        str(entry.get("ts_utc") or ""),
        str(entry.get("actor") or "system"),
        str(entry.get("reason") or "generated governance render"),
    )).replace("--", "—")
    return f"<!-- STRATFORGE_INTERNAL_AMENDMENT\n{text}\n-->"


def _governance_updated_at() -> str:
    """Deterministic "last updated" stamp for generated governance documents.

    Generated docs are re-rendered on every backend start and on import. Using
    the wall-clock render date would dirty a clean checkout on the next calendar
    day; instead we use the latest recorded governance mutation time (the laws
    document plus the amendment journal), so a mere restart / re-render never
    changes the rendered bytes (Phase 11 deterministic-render requirement).
    """
    doc = _read_json(laws_path(), _default_laws_doc())
    if not isinstance(doc, dict):
        doc = _default_laws_doc()
    times = [str(doc.get("updated_at_utc") or "")]
    times.extend(str(row.get("ts_utc") or "") for row in read_change_log(limit=5))
    return max((value for value in times if value), default="не указана")


def _render_laws_markdown(audience: str) -> str:
    doc = _read_json(laws_path(), _default_laws_doc())
    if not isinstance(doc, dict):
        doc = _default_laws_doc()
    selected = [
        law for law in doc.get("laws", [])
        if isinstance(law, dict) and str(law.get("audience") or "") == audience
    ]
    title = "LAWS" if audience == "project" else "LOCAL_AI_LAWS"
    subtitle = (
        "Короткий свод действующих проектных законов для пользователей и системы StratForge AI."
        if audience == "project"
        else "Короткий свод законов для локального ИИ и узкого облачного fallback в AI Lab sandbox."
    )
    parts: List[str] = [f"# {title}", "", f"Дата актуализации: {_governance_updated_at()}", "", subtitle]
    current_group = None
    for law in selected:
        group = str(law.get("group") or "")
        if group != current_group:
            parts.extend(["", f"## {_group_title(group)}", ""])
            current_group = group
        parts.extend(
            [
                f"### {law.get('id')} — {law.get('title')}",
                "",
                f"- Значение: `{_law_value_text(law)}`",
                f"- Суть: {law.get('summary')}",
            ]
        )
        warning = str(law.get("warning") or "").strip()
        if warning:
            parts.append(f"- Важно: {warning}")
        refs = [str(x) for x in (law.get("source_refs") or []) if str(x).strip()]
        if refs:
            parts.append(f"- Источники: {', '.join(f'`{x}`' for x in refs)}")
        targets = [str(x) for x in (law.get("dynamic_targets") or []) if str(x).strip()]
        if targets:
            parts.append(f"- Автосинхронизация: {', '.join(targets)}")
        review = [str(x) for x in (law.get("review_targets") or []) if str(x).strip()]
        if review:
            parts.append(f"- Ручная проверка: {', '.join(review)}")
        parts.append("")
    internal = _internal_amendment_comment()
    if internal:
        parts.extend(["", internal])
    return "\n".join(parts).strip() + "\n"


def _render_sync_map_markdown() -> str:
    doc = _read_json(laws_path(), _default_laws_doc())
    if not isinstance(doc, dict):
        doc = _default_laws_doc()
    parts = [
        "# SYNC_MAP",
        "",
        f"Дата актуализации: {_governance_updated_at()}",
        "",
        "Этот файл показывает, что именно меняется автоматически после редактирования закона, а что остаётся на ручную проверку.",
        "",
    ]
    for law in doc.get("laws", []):
        if not isinstance(law, dict):
            continue
        parts.extend(
            [
                f"## {law.get('id')} — {law.get('title')}",
                "",
                f"- Текущее значение: `{_law_value_text(law)}`",
                f"- Автоматически обновляется: {', '.join(law.get('dynamic_targets') or ['—'])}",
                f"- Нужно проверить вручную: {', '.join(law.get('review_targets') or ['—'])}",
                "",
            ]
        )
    internal = _internal_amendment_comment()
    if internal:
        parts.extend(["", internal])
    return "\n".join(parts).strip() + "\n"


def _render_readme_markdown() -> str:
    body = """# Governance Docs

Эта папка — канонический слой governance для проекта.

- `OVERVIEW.md` — краткое главное предисловие и актуальная сводка.
- `CHARTER.md` — цель, границы и основные принципы.
- `ROLES.md` — роли владельца и всех ИИ-каналов.
- `LAWS.md` — общие законы проекта.
- `LOCAL_AI_LAWS.md` — отдельные законы локального ИИ и cloud fallback / AI Lab.
- `../agents/AI_LAB_COMPETITIVE_FEEDBACK.md` — контракт конкурентной обратной связи для AI-ролей.
- `REGISTRY_POLICY.md` — правила ведения реестра стратегий.
- `SYNC_MAP.md` — что синхронизируется автоматически, а что нужно проверять вручную.

Редактируемый machine source of truth:

- `data/governance/laws.json`
- `data/governance/documents.json`
- `data/governance/change_log.jsonl` — последовательный журнал поправок с датой, временем, автором и before/after.
"""
    internal = _internal_amendment_comment()
    return body.rstrip() + (f"\n\n{internal}" if internal else "") + "\n"


def _render_overview_markdown() -> str:
    laws_doc = load_laws()
    by_key = {
        str(row.get("key") or ""): row
        for row in laws_doc.get("laws", [])
        if isinstance(row, dict)
    }

    def law_value(key: str, fallback: Any) -> Any:
        row = by_key.get(key)
        return row.get("value") if isinstance(row, dict) and "value" in row else fallback

    history = read_change_log(limit=5)
    capital = float(law_value("starting_capital_usd", 2000))
    max_dd_pct = float(law_value("max_drawdown_pct", 15))
    commission = float(law_value("round_turn_commission_floor_usd", 1.90))
    slippage = int(law_value("slippage_ticks_floor", 1))
    fill_mode = str(law_value("order_fill_resolution", "High"))
    intraday = "Да" if bool(law_value("intraday_only_default", True)) else "Нет"
    research_flow = str(law_value("research_flow", "Research Hub -> Deploy wrapper"))
    paper_gate = "Да" if bool(law_value("paper_before_live_required", True)) else "Нет"
    runtime_lock = "Да" if bool(law_value("runtime_locked_params_must_match", True)) else "Нет"
    ai_window = str(law_value("ai_lab_session_window_pt", "06:30-12:30 PT"))
    ai_sandbox = "Да" if bool(law_value("ai_lab_sandbox_only", True)) else "Нет"
    cloud_budget = str(law_value("ai_lab_cloud_budget_caps", "20.00 USD/month; 0.50 USD/run"))
    # Generated docs are refreshed on every backend start. Their contents must
    # not become dirty merely because the process restarted; use the latest
    # actual governance mutation time instead of wall-clock render time.
    mutation_times = [str(laws_doc.get("updated_at_utc") or "")]
    mutation_times.extend(str(row.get("ts_utc") or "") for row in history)
    updated_at = max((value for value in mutation_times if value), default="не указана")

    parts = [
        "# OVERVIEW",
        "",
        f"Дата актуализации: {updated_at}",
        "",
        "## О StratForge AI",
        "",
        "StratForge AI — торгово-аналитическая платформа для анализа рынков и стратегий: realtime-графики и market data из нескольких источников, NinjaTrader через StratForge Connector, AI-агенты, бэктестинг, управление стратегиями и учебная торговля. Полная цель, назначение и текущие возможности — в `CHARTER`.",
        "",
        "Этот документ (`OVERVIEW`) — сжатая рабочая сводка правил и параметров для разработчиков стратегий. Актуальная версия всегда определяется текущими законами и журналом поправок.",
        "",
        "## Рабочие параметры стратегий (для разработчиков)",
        "",
        f"- StartingCapital по умолчанию: `{capital:.2f} USD`",
        f"- Max drawdown gate: `{max_dd_pct:.0f}%` от зафиксированного capital",
        f"- Минимальная комиссия: `{commission:.2f} USD` round turn",
        f"- Минимальный slippage: `{slippage} ticks`",
        f"- Fill mode: `{fill_mode}`",
        f"- IntradayOnly по умолчанию: `{intraday}`",
        f"- Канонический цикл: `{research_flow}`",
        f"- Paper before live: `{paper_gate}`",
        f"- Runtime должен совпадать с locked params: `{runtime_lock}`",
        f"- AI Lab sandbox only: `{ai_sandbox}`",
        f"- AI Lab cloud API: `local-first fallback; {cloud_budget}`",
        f"- Базовое PT-окно AI Lab: `{ai_window}`",
        "",
        "## На что смотреть в первую очередь",
        "",
        "- Бюджет стратегии: capital, MaxDD, комиссия и slippage.",
        "- Любой live-допуск возможен только после paper и ручного решения владельца.",
        "- Любое изменение закона должно быть видно и в документах, и в журнале поправок.",
        "- Исторические approved/paper профили после смены capital или risk нужно ревалидировать отдельно.",
        "",
        "## Где править и где проверять",
        "",
        "- Удобнее всего работать через `/ui/docs.html`: там читать, редактировать и смотреть журнал.",
        "- Законы менять в `LAWS` или `LOCAL_AI_LAWS`.",
        "- После изменения смотреть `SYNC_MAP`, блок `Где проверять после изменения` и журнал поправок.",
        "- Подробный журнал редакций и технические сведения доступны владельцу/разработчику справа во вкладке «Документы» через «Подробнее».",
    ]
    internal = _internal_amendment_comment()
    if internal:
        parts.extend(["", internal])
    return "\n".join(parts).strip() + "\n"


def _render_generated_docs() -> None:
    _write_text(docs_dir() / "README.md", _render_readme_markdown())
    _write_text(docs_dir() / "OVERVIEW.md", _render_overview_markdown())
    _write_text(docs_dir() / "LAWS.md", _render_laws_markdown("project"))
    _write_text(docs_dir() / "LOCAL_AI_LAWS.md", _render_laws_markdown("local_ai"))
    _write_text(docs_dir() / "SYNC_MAP.md", _render_sync_map_markdown())


def ensure_governance_files(*, render: bool = True) -> None:
    docs_dir()
    data_dir()
    if not laws_path().is_file():
        _write_json(laws_path(), _default_laws_doc())
    if not documents_path().is_file():
        _write_json(documents_path(), DEFAULT_DOCUMENTS)
    if not change_log_path().is_file():
        change_log_path().write_text("", encoding="utf-8")
    registry_doc = _read_json(documents_path(), DEFAULT_DOCUMENTS)
    if not isinstance(registry_doc, dict):
        registry_doc = copy.deepcopy(DEFAULT_DOCUMENTS)
    normalized_registry = _normalize_documents_registry(registry_doc)
    if normalized_registry != registry_doc:
        normalized_registry["updated_at_utc"] = _now_iso()
        _write_json(documents_path(), normalized_registry)

    charter_path = docs_dir() / "CHARTER.md"
    roles_path = docs_dir() / "ROLES.md"
    policy_path = docs_dir() / "REGISTRY_POLICY.md"
    if not charter_path.is_file():
        _write_text(charter_path, CHARTER_DEFAULT)
    if not roles_path.is_file():
        _write_text(roles_path, ROLES_DEFAULT)
    if not policy_path.is_file():
        _write_text(policy_path, REGISTRY_POLICY_DEFAULT)

    if render:
        _render_generated_docs()


def load_laws() -> Dict[str, Any]:
    ensure_governance_files(render=False)
    data = _read_json(laws_path(), _default_laws_doc())
    if not isinstance(data, dict):
        data = _default_laws_doc()
    laws = data.get("laws")
    if not isinstance(laws, list):
        data["laws"] = copy.deepcopy(DEFAULT_LAWS)
    return data


def load_documents_registry() -> Dict[str, Any]:
    ensure_governance_files(render=False)
    data = _read_json(documents_path(), DEFAULT_DOCUMENTS)
    if not isinstance(data, dict):
        data = copy.deepcopy(DEFAULT_DOCUMENTS)
    normalized = _normalize_documents_registry(data)
    if normalized != data:
        normalized["updated_at_utc"] = _now_iso()
        _write_json(documents_path(), normalized)
        return normalized
    return normalized


def _save_laws(doc: Dict[str, Any]) -> None:
    saved = copy.deepcopy(doc)
    saved["updated_at_utc"] = _now_iso()
    _write_json(laws_path(), saved)


def _law_change_rows(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    if before.get("value") != after.get("value"):
        changes.append({
            "field": "value",
            "label": "Значение",
            "before": before.get("value"),
            "after": after.get("value"),
            "before_text": _law_value_text_for(before, before.get("value")),
            "after_text": _law_value_text_for(after, after.get("value")),
            "before_hash": "",
            "after_hash": "",
        })
    if str(before.get("summary") or "") != str(after.get("summary") or ""):
        changes.append({
            "field": "summary",
            "label": "Краткая суть",
            "before": before.get("summary"),
            "after": after.get("summary"),
            "before_text": str(before.get("summary") or ""),
            "after_text": str(after.get("summary") or ""),
            "before_hash": "",
            "after_hash": "",
        })
    if str(before.get("warning") or "") != str(after.get("warning") or ""):
        changes.append({
            "field": "warning",
            "label": "Предупреждение",
            "before": before.get("warning"),
            "after": after.get("warning"),
            "before_text": str(before.get("warning") or ""),
            "after_text": str(after.get("warning") or ""),
            "before_hash": "",
            "after_hash": "",
        })
    return changes


def _document_change_row(before: str, after: str) -> List[Dict[str, Any]]:
    before_text, after_text = _semantic_change_text(before, after)
    return [{
        "field": "content",
        "label": "Содержимое",
        "before": None,
        "after": None,
        "before_text": before_text,
        "after_text": after_text,
        "before_hash": _hash_text(before),
        "after_hash": _hash_text(after),
        "diff": _line_diff(before, after),
    }]


def list_documents() -> List[Dict[str, Any]]:
    registry = load_documents_registry()
    result: List[Dict[str, Any]] = []
    for row in registry.get("documents", []):
        if not isinstance(row, dict):
            continue
        item = copy.deepcopy(row)
        item["owner"] = str(registry.get("owner") or PROJECT_OWNER)
        path = _resolve_doc_path(str(row.get("path") or ""))
        item["abs_path"] = str(path)
        item["rel_path"] = _rel(path)
        item["exists"] = path.is_file()
        result.append(item)
    return result


def document_is_public(item: Dict[str, Any]) -> bool:
    return str(item.get("audience") or "").lower() == "user" or str(item.get("id") or "") in PUBLIC_DOCUMENT_IDS


def public_document(item: Dict[str, Any]) -> Dict[str, Any]:
    """Remove owner/dev paths and internal amendment comments from a document."""
    allowed = {
        "id", "title", "label", "category", "editable_kind", "audience",
        "draft", "exists", "content", "laws",
    }
    out = {key: copy.deepcopy(value) for key, value in item.items() if key in allowed}
    if "content" in out:
        out["content"] = INTERNAL_AMENDMENT_RE.sub("", str(out.get("content") or "")).rstrip() + "\n"
    return out


def _document_by_id(doc_id: str) -> Optional[Dict[str, Any]]:
    for item in list_documents():
        if item.get("id") == doc_id:
            return item
    return None


def _law_items_for_audience(audience: str) -> List[Dict[str, Any]]:
    laws_doc = load_laws()
    items = []
    for row in laws_doc.get("laws", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("audience") or "") != audience:
            continue
        items.append(copy.deepcopy(row))
    return items


def read_document(doc_id: str) -> Optional[Dict[str, Any]]:
    item = _document_by_id(doc_id)
    if not item:
        return None
    editable = str(item.get("editable_kind") or "none")
    if editable == "laws":
        audience = str(item.get("audience") or "project")
        content = _render_laws_markdown(audience)
        return {
            **item,
            "content": content,
            "laws": _law_items_for_audience(audience),
        }
    path = Path(item["abs_path"])
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        content = ""
    return {
        **item,
        "content": content,
    }


def update_law(
    law_id: str,
    payload: Dict[str, Any],
    *,
    actor: str = "ui",
    author: str = "",
    author_id: str = "",
    author_kind: str = "human",
    initiator: str = "",
) -> Dict[str, Any]:
    laws_doc = load_laws()
    for law in laws_doc.get("laws", []):
        if not isinstance(law, dict) or law.get("id") != law_id:
            continue
        before = copy.deepcopy(law)
        if "value" in payload:
            law["value"] = _normalize_law_value(law, payload.get("value"))
        if "summary" in payload and str(payload.get("summary") or "").strip():
            law["summary"] = str(payload.get("summary")).strip()
        if "warning" in payload:
            law["warning"] = str(payload.get("warning") or "").strip()
        changes = _law_change_rows(before, law)
        if not changes:
            return {
                "ok": True,
                "changed": False,
                "law": copy.deepcopy(law),
                "warning": law.get("warning") or "",
                "review_targets": copy.deepcopy(law.get("review_targets") or []),
                "history_entry": None,
            }
        law["updated_at_utc"] = _now_iso()
        _save_laws(laws_doc)
        history_entry = _append_change_log_entry({
            "actor": actor or "ui",
            "author": str(author or actor or "ui"),
            "author_id": str(author_id or "").strip(),
            "author_kind": str(author_kind or "human").strip() or "human",
            "initiator": str(initiator or "").strip(),
            "reason": str(payload.get("reason") or "").strip() or f"update law {law_id}",
            "entity_type": "law",
            "entity_id": law_id,
            "entity_title": f"{law.get('id')} — {law.get('title')}",
            "document_ids": _law_document_ids(law),
            "path": _rel(laws_path()),
            "changes": changes,
        })
        _render_generated_docs()
        return {
            "ok": True,
            "changed": True,
            "law": copy.deepcopy(law),
            "warning": law.get("warning") or "",
            "review_targets": copy.deepcopy(law.get("review_targets") or []),
            "history_entry": history_entry,
        }
    raise KeyError(f"law not found: {law_id}")


def update_markdown_document(
    doc_id: str,
    content: str,
    *,
    actor: str = "ui",
    reason: str = "",
    author: str = "",
    author_id: str = "",
    author_kind: str = "human",
    initiator: str = "",
) -> Dict[str, Any]:
    item = _document_by_id(doc_id)
    if not item:
        raise KeyError(f"document not found: {doc_id}")
    if str(item.get("editable_kind") or "") != "markdown":
        raise ValueError(f"document is not markdown-editable: {doc_id}")
    path = Path(item["abs_path"])
    try:
        before = path.read_text(encoding="utf-8-sig")
    except OSError:
        before = ""
    if before == content:
        return {"ok": True, "changed": False, "document": read_document(doc_id), "history_entry": None}
    _write_text(path, content)
    author_display = str(author or actor or "ui").strip()
    history_entry = _append_change_log_entry({
        "actor": str(actor or author_display or "ui"),
        "author": author_display,
        "author_id": str(author_id or "").strip(),
        "author_kind": str(author_kind or "human").strip() or "human",
        "initiator": str(initiator or "").strip(),
        "reason": str(reason or "").strip() or f"update document {doc_id}",
        "entity_type": "document",
        "entity_id": doc_id,
        "entity_title": str(item.get("label") or item.get("title") or doc_id),
        "document_ids": [doc_id],
        "path": _rel(path),
        "changes": _document_change_row(before, content),
    })
    _render_generated_docs()
    return {"ok": True, "changed": True, "document": read_document(doc_id), "history_entry": history_entry}


def document_revisions(doc_id: str) -> Dict[str, Any]:
    """Per-document, immutable revision journal.

    Revision №1 is the synthetic "документ создан" baseline; every real edit in
    the append-only change log becomes the next revision in chronological order.
    """
    item = _document_by_id(doc_id)
    title = str((item or {}).get("label") or (item or {}).get("title") or doc_id)
    owner = str(PROJECT_OWNER)
    entries = read_change_log(0, document_id=doc_id)
    entries = sorted(
        entries,
        key=lambda row: (int(row.get("amendment_no") or 0), str(row.get("ts_utc") or "")),
    )
    created_author = str((item or {}).get("created_author") or "StratForge AI · импорт документа")
    revisions: List[Dict[str, Any]] = [{
        "revision_no": 1,
        "version_id": "created",
        "ts_utc": str((item or {}).get("created_at_utc") or ""),
        "kind": "created",
        "title": "документ создан",
        "author": created_author,
        "author_id": str((item or {}).get("created_author_id") or ""),
        "author_kind": str((item or {}).get("created_author_kind") or "system"),
        "initiator": str((item or {}).get("created_initiator") or ""),
        "reason": str((item or {}).get("created_reason") or "Существующий документ импортирован в журнал редакций; исходный автор не был зафиксирован."),
        "path": str((item or {}).get("rel_path") or (item or {}).get("path") or ""),
        "changes": [],
    }]
    for index, entry in enumerate(entries, start=2):
        revisions.append({
            "revision_no": index,
            "version_id": str(entry.get("version_id") or ""),
            "ts_utc": str(entry.get("ts_utc") or ""),
            "kind": "edited",
            "title": str(entry.get("reason") or "правка"),
            "author": str(entry.get("author") or entry.get("actor") or ""),
            "author_id": str(entry.get("author_id") or ""),
            "author_kind": str(entry.get("author_kind") or "human"),
            "initiator": str(entry.get("initiator") or ""),
            "reason": str(entry.get("reason") or ""),
            "path": str(entry.get("path") or ""),
            "amendment_no": int(entry.get("amendment_no") or 0),
            "changes": entry.get("changes") or [],
        })
    return {"document_id": doc_id, "title": title, "owner": owner, "revisions": revisions}


def runtime_defaults() -> Dict[str, Any]:
    laws_doc = load_laws()
    by_key = {
        str(row.get("key") or ""): row
        for row in laws_doc.get("laws", [])
        if isinstance(row, dict)
    }

    def law_value(key: str, fallback: Any) -> Any:
        row = by_key.get(key)
        return row.get("value") if isinstance(row, dict) and "value" in row else fallback

    return {
        "starting_capital": float(law_value("starting_capital_usd", 2000)),
        "max_drawdown_pct": float(law_value("max_drawdown_pct", 15)) / 100.0,
        "round_turn_commission": float(law_value("round_turn_commission_floor_usd", 1.90)),
        "slippage_ticks": int(law_value("slippage_ticks_floor", 1)),
        "order_fill_resolution": str(law_value("order_fill_resolution", "High")),
        "intraday_only": bool(law_value("intraday_only_default", True)),
        "ai_lab_session_window_pt": str(law_value("ai_lab_session_window_pt", "06:30-12:30 PT")),
    }


def goals_path() -> Path:
    return data_dir() / "goals.json"


def read_goals() -> Dict[str, Any]:
    """Machine-readable project goals (North Star). Empty dict if not configured."""
    path = goals_path()
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def north_star_progress() -> Dict[str, Any]:
    """North Star goal + live progress from runtime realized PnL after commission.

    ``progress`` is realized (closed) after-commission PnL accumulated since the
    goal ``baseline_date``. It intentionally excludes backtest and unrealized
    PnL — those never count toward the goal.
    """
    goals = read_goals()
    north = goals.get("north_star") if isinstance(goals, dict) else None
    if not isinstance(north, dict) or not north:
        return {"configured": False}

    target = float(north.get("target_usd") or 0.0)
    baseline_date = str(north.get("baseline_date") or "").strip()
    baseline_realized = float(north.get("baseline_realized_usd") or 0.0)
    deadline = str(north.get("deadline") or "").strip()

    realized: Optional[float] = None
    realized_error = ""
    if baseline_date:
        try:
            from . import performance as _perf  # lazy import to avoid cycles
            today = datetime.now(timezone.utc).date().isoformat()
            resp = _perf.build_performance_response(
                period="custom", from_date=baseline_date, to_date=today,
            )
            realized = float((resp.get("summary") or {}).get("pnl") or 0.0)
        except Exception as exc:  # pragma: no cover - defensive
            realized_error = str(exc)[:200]

    progress = None if realized is None else round(realized - baseline_realized, 2)
    remaining = None if progress is None else round(target - progress, 2)
    pct = None if (progress is None or target <= 0) else round(progress / target * 100.0, 2)

    days_left: Optional[int] = None
    if deadline:
        try:
            end = datetime.fromisoformat(deadline).date()
            days_left = max(0, (end - datetime.now(timezone.utc).date()).days)
        except ValueError:
            days_left = None
    pace_required = None
    if remaining is not None and days_left and days_left > 0:
        pace_required = round(max(0.0, remaining) / days_left, 2)

    return {
        "configured": True,
        "id": north.get("id"),
        "title": north.get("title"),
        "statement": north.get("statement"),
        "target_usd": target,
        "deadline": deadline,
        "baseline_date": baseline_date,
        "baseline_realized_usd": baseline_realized,
        "progress_usd": progress,
        "remaining_usd": remaining,
        "progress_pct": pct,
        "days_left": days_left,
        "pace_required_usd_per_day": pace_required,
        "measurement": north.get("measurement"),
        "milestones": north.get("milestones") or [],
        "constraints": north.get("constraints") or [],
        "doc": north.get("doc"),
        "realized_source_error": realized_error,
    }


def _scan_candidate_refs(patterns: Iterable[str]) -> List[Dict[str, Any]]:
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns if p]
    if not compiled:
        return []
    roots = [
        project_root() / "app",
        project_root() / "tools",
        project_root() / "docs",
        workspace_root() / "РАЗРАБОТКА СТРАТЕГИЙ",
    ]
    findings: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                rel = path.resolve().relative_to(project_root().resolve())
                if rel.parts[:2] in {("docs", "governance"), ("data", "governance")}:
                    continue
            except Exception:
                pass
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            hits = sum(len(rx.findall(text)) for rx in compiled)
            if hits <= 0:
                continue
            findings.append({
                "path": _rel(path),
                "hits": hits,
            })
    findings.sort(key=lambda row: (-int(row.get("hits", 0)), str(row.get("path") or "")))
    return findings[:80]


def consistency_report() -> Dict[str, Any]:
    laws_doc = load_laws()
    scan_map = {
        "starting_capital_usd": [
            r"StartingCapital[^\n]{0,80}[0-9]",
            r"starting_capital[^\n]{0,80}[0-9]",
        ],
        "round_turn_commission_floor_usd": [
            r"RoundTurnCommission[^\n]{0,80}[0-9]",
            r"round_turn_commission[^\n]{0,80}[0-9]",
        ],
        "slippage_ticks_floor": [
            r"SlippageTicks[^\n]{0,80}[0-9]",
            r"slippage_ticks[^\n]{0,80}[0-9]",
        ],
    }
    items: List[Dict[str, Any]] = []
    for law in laws_doc.get("laws", []):
        if not isinstance(law, dict):
            continue
        items.append({
            "law_id": law.get("id"),
            "key": law.get("key"),
            "title": law.get("title"),
            "value": law.get("value"),
            "dynamic_targets": copy.deepcopy(law.get("dynamic_targets") or []),
            "review_targets": copy.deepcopy(law.get("review_targets") or []),
            "candidate_hardcoded_refs": _scan_candidate_refs(scan_map.get(str(law.get("key") or ""), [])),
        })
    return {
        "generated_at_utc": _now_iso(),
        "runtime_defaults": runtime_defaults(),
        "items": items,
    }


# Library and test imports do not select a deployment boundary and must never
# rewrite tracked Markdown in the source checkout as a side effect. Real
# Development/Canary/Production startup is explicit and renders into its
# isolated governance-rendered data root.
ensure_governance_files(render=runtime_env.environment_explicit())
