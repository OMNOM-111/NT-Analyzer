"""Centralised timeout configuration for all LLM calls.

Policy: quality_over_speed — every operation gets enough time for a good
answer. Exceeding the hard ceiling means the model clearly cannot finish;
the router switches to the next candidate (cooldown 300 s), it does not retry
the same agent.

Values are loaded once from ``ai_lab/llm_timeouts.json``.  Any entry can be
overridden at runtime with an environment variable:
    AI_LAB_TIMEOUT_<OPERATION_UPPER>=<seconds>

Examples:
    AI_LAB_TIMEOUT_CODE_GENERATION=720
    AI_LAB_TIMEOUT_LOCAL_CODER=1200
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "ai_lab" / "llm_timeouts.json"

_cfg: Dict[str, Any] = {}


def _load() -> None:
    global _cfg
    try:
        _cfg = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _cfg = {}


_load()


def resolve_timeout(operation: str, *, model_id: str = "") -> int:
    """Return timeout in seconds for *operation*.

    Resolution order:
    1. Env var ``AI_LAB_TIMEOUT_<OPERATION_UPPER>`` (runtime override)
    2. ``model_overrides`` in the JSON for the given *model_id*
    3. ``operations[operation].timeout_sec`` in the JSON
    4. Hard fallback: 180 s
    """
    env_val = os.environ.get(f"AI_LAB_TIMEOUT_{operation.upper()}")
    if env_val:
        try:
            return max(1, int(env_val))
        except ValueError:
            pass
    if model_id:
        overrides = (_cfg.get("model_overrides") or {}).get(model_id) or {}
        if operation in overrides:
            try:
                return max(1, int(overrides[operation]))
            except (TypeError, ValueError):
                pass
    entry = (_cfg.get("operations") or {}).get(operation) or {}
    val = entry.get("timeout_sec")
    if val is not None:
        try:
            return max(1, int(val))
        except (TypeError, ValueError):
            pass
    return 180


# ---------------------------------------------------------------------------
# Named constants — import these at call sites instead of magic numbers.
# ---------------------------------------------------------------------------

#: Short connectivity probe; model must answer immediately.
CONNECTION_TEST: int = resolve_timeout("connection_test")

#: Health-check via a 1–2 sentence completion.
MODEL_PROBE: int = resolve_timeout("model_probe")

#: /v1/models list request.
LIST_MODELS: int = resolve_timeout("list_models")

#: Embedding vectors (no quality requirement on generation time).
EMBEDDING: int = resolve_timeout("embedding")

#: Short analytical reply: news, events, Telegram, accountant.
LIGHT_CHAT: int = resolve_timeout("light_chat")

#: Hypothesis / backtest analysis / overfit detection (thinking tokens).
ANALYSIS: int = resolve_timeout("analysis")

#: Code review, risk manager, final judge, committee.
REVIEW: int = resolve_timeout("review")

#: Full NinjaScript C# generation (coder / compile_error_fixer roles, cloud).
CODE_GENERATION: int = resolve_timeout("code_generation")

#: Compile-error autofix with full file context.
CODE_AUTOFIX: int = resolve_timeout("code_autofix")

#: Orchestrator JSON plan (DeepSeek thinking + up to 6 000 output tokens).
ORCHESTRATOR_PLAN: int = resolve_timeout("orchestrator_plan")

#: Strategic / manager dialogue including repair pass (8 192-token envelope).
CHIEF_DIALOGUE: int = resolve_timeout("chief_dialogue")

#: Weekly / monthly / quarterly report generation.
PERIODIC_REPORT: int = resolve_timeout("periodic_report")

#: Local LM Studio judge role (idea generator).
LOCAL_JUDGE: int = resolve_timeout("local_judge")

#: Local LM Studio coder role (NinjaScript generation).
LOCAL_CODER: int = resolve_timeout("local_coder")

#: Local LM Studio default chat (all other roles).
LOCAL_CHAT: int = resolve_timeout("local_chat_default")


def reload() -> None:
    """Reload configuration from disk and refresh module-level constants.

    Intended for tests and hot-reload scenarios only.
    """
    global CONNECTION_TEST, MODEL_PROBE, LIST_MODELS, EMBEDDING
    global LIGHT_CHAT, ANALYSIS, REVIEW
    global CODE_GENERATION, CODE_AUTOFIX
    global ORCHESTRATOR_PLAN, CHIEF_DIALOGUE, PERIODIC_REPORT
    global LOCAL_JUDGE, LOCAL_CODER, LOCAL_CHAT

    _load()

    CONNECTION_TEST   = resolve_timeout("connection_test")
    MODEL_PROBE       = resolve_timeout("model_probe")
    LIST_MODELS       = resolve_timeout("list_models")
    EMBEDDING         = resolve_timeout("embedding")
    LIGHT_CHAT        = resolve_timeout("light_chat")
    ANALYSIS          = resolve_timeout("analysis")
    REVIEW            = resolve_timeout("review")
    CODE_GENERATION   = resolve_timeout("code_generation")
    CODE_AUTOFIX      = resolve_timeout("code_autofix")
    ORCHESTRATOR_PLAN = resolve_timeout("orchestrator_plan")
    CHIEF_DIALOGUE    = resolve_timeout("chief_dialogue")
    PERIODIC_REPORT   = resolve_timeout("periodic_report")
    LOCAL_JUDGE       = resolve_timeout("local_judge")
    LOCAL_CODER       = resolve_timeout("local_coder")
    LOCAL_CHAT        = resolve_timeout("local_chat_default")


def policy() -> Dict[str, Any]:
    """Return the full loaded configuration (read-only copy for diagnostics)."""
    import copy
    return copy.deepcopy(_cfg)
