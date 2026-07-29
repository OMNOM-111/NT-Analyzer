"""Canonical paths for AI Strategy Lab.

Single source of truth so that no module hard-codes paths inline.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import runtime_env


def _project_root() -> Path:
    # app/ai_lab/paths.py -> app/ai_lab -> app -> NT-Analyzer
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT = _project_root()

AI_LAB_DIR = PROJECT_ROOT / "ai_lab"
MUTABLE_AI_LAB_DIR = (
    runtime_env.data_path("ai_lab", project_root=PROJECT_ROOT)
    if runtime_env.uses_isolated_data_root() else AI_LAB_DIR
)
REGISTRY_DIR = MUTABLE_AI_LAB_DIR / "registry"
EXPERIMENTS_DIR = REGISTRY_DIR / "experiments"
POSTMORTEMS_DIR = REGISTRY_DIR / "strategy_postmortems"
KNOWLEDGE_CARDS_DIR = REGISTRY_DIR / "knowledge_cards"
RUNS_DIR = REGISTRY_DIR / "runs"
PROMPTS_LOG_DIR = REGISTRY_DIR / "prompts_log"
ACTIVITY_DIR = REGISTRY_DIR / "activity"
REFERENCE_STRATEGIES_DIR = AI_LAB_DIR / "reference_strategies"

USER_RESEARCH_DIR = MUTABLE_AI_LAB_DIR / "user_research"
PROMPTS_DIR = AI_LAB_DIR / "prompts"
SCHEMAS_DIR = AI_LAB_DIR / "schemas"
MIRRORS_DIR = MUTABLE_AI_LAB_DIR / "mirrors"
SOURCE_SNAPSHOTS_DIR = MIRRORS_DIR / "source_snapshots"
QUARANTINE_DIR = MUTABLE_AI_LAB_DIR / "quarantine" / "compile_failed"
MODEL_BENCHMARK_PATH = REGISTRY_DIR / "model_benchmark_latest.json"

INDEX_PATH = REGISTRY_DIR / "index.json"
ERROR_LOG_PATH = REGISTRY_DIR / "error_log.jsonl"
ERROR_PATTERNS_PATH = REGISTRY_DIR / "error_patterns.json"
LESSON_LOG_PATH = REGISTRY_DIR / "lesson_log.jsonl"
REJECTED_HYPOTHESES_PATH = REGISTRY_DIR / "rejected_hypotheses.jsonl"
DEMO_MISMATCH_PATH = REGISTRY_DIR / "demo_mismatch_registry.jsonl"
COMPILE_FAIL_PATH = REGISTRY_DIR / "compile_fail_registry.jsonl"
INFRA_FAIL_PATH = REGISTRY_DIR / "infra_fail_registry.jsonl"


def nt_user_home() -> Path:
    override = os.environ.get("NT_USER_HOME")
    if override:
        return Path(override)
    return Path.home()


def nt_custom_dir() -> Path:
    if runtime_env.uses_isolated_data_root():
        return runtime_env.data_path(
            "ninjatrader", "Custom", project_root=PROJECT_ROOT,
        )
    return nt_user_home() / "Documents" / "NinjaTrader 8" / "bin" / "Custom"


def ai_sandbox_strategies_dir() -> Path:
    """Canonical compile source for AI sandbox strategies.

    Note: spec uses literal "NT-Analyzer_AI Labstrategies" (no space before 'strategies').
    """
    override = os.environ.get("AI_LAB_SANDBOX_DIR")
    if override:
        return Path(override)
    return nt_custom_dir() / "Strategies" / "NT-Analyzer_AI Labstrategies"


def ensure_dirs() -> None:
    for p in (
        AI_LAB_DIR, REGISTRY_DIR, EXPERIMENTS_DIR, POSTMORTEMS_DIR,
        KNOWLEDGE_CARDS_DIR, RUNS_DIR, PROMPTS_LOG_DIR, ACTIVITY_DIR,
        USER_RESEARCH_DIR, USER_RESEARCH_DIR / "incoming",
        USER_RESEARCH_DIR / "curated", USER_RESEARCH_DIR / "postmortems",
        PROMPTS_DIR, SCHEMAS_DIR, MIRRORS_DIR, SOURCE_SNAPSHOTS_DIR,
        REFERENCE_STRATEGIES_DIR, QUARANTINE_DIR,
    ):
        p.mkdir(parents=True, exist_ok=True)
    for jl in (
        ERROR_LOG_PATH, LESSON_LOG_PATH, REJECTED_HYPOTHESES_PATH,
        DEMO_MISMATCH_PATH, COMPILE_FAIL_PATH, INFRA_FAIL_PATH,
    ):
        if not jl.exists():
            jl.touch()
