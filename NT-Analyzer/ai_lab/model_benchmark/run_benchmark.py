from __future__ import annotations

import argparse
import json
import os
import re
import socket
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


BASE_DIR = Path(__file__).resolve().parent
AI_LAB_DIR = BASE_DIR.parent
PROMPTS_DIR = BASE_DIR / "prompts"
INPUTS_DIR = BASE_DIR / "test_inputs"
RESULTS_DIR = BASE_DIR / "results"
RAW_DIR = RESULTS_DIR / "raw"
SCORED_DIR = RESULTS_DIR / "scored"
REPORTS_DIR = BASE_DIR / "reports"

MODEL_REPORT_PATH = REPORTS_DIR / "MODEL_BENCHMARK_REPORT.md"
CODING_REPORT_PATH = REPORTS_DIR / "CODING_BENCHMARK_REPORT.md"
FINAL_REPORT_PATH = REPORTS_DIR / "FINAL_MODEL_SELECTION_REPORT.md"
SUMMARY_PATH = SCORED_DIR / "summary.json"
MODEL_ROLES_PATH = AI_LAB_DIR / "model_roles.json"

DEFAULT_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")
DEFAULT_TIMEOUT = int(os.environ.get("MODEL_BENCHMARK_TIMEOUT", "180"))


@dataclass(frozen=True)
class PromptSpec:
    prompt_id: str
    title: str
    prompt_file: str
    attachments: Tuple[str, ...]
    evaluator: str
    benchmark_group: str
    temperature: float
    max_tokens: int
    timeout_seconds: int


MANDATORY_MODELS: List[Dict[str, Any]] = [
    {
        "label": "qwen/qwen3.6-35b-a3b",
        "aliases": ["qwen/qwen3.6-35b-a3b", "qwen3.6-35b-a3b", "qwen3-6-35b-a3b"],
    },
    {
        "label": "gpt-oss-20b",
        "aliases": ["gpt-oss-20b", "openai/gpt-oss-20b"],
    },
    {
        "label": "Qwen3-Coder-30B-A3B-Instruct",
        "aliases": [
            "Qwen3-Coder-30B-A3B-Instruct",
            "qwen/Qwen3-Coder-30B-A3B-Instruct",
            "qwen3-coder-30b-a3b-instruct",
        ],
    },
    {
        "label": "Codestral-22B",
        "aliases": [
            "Codestral-22B",
            "codestral-22b",
            "codestral-22b-v0.1",
            "mistralai/Codestral-22B-v0.1",
        ],
    },
    {
        "label": "DeepSeek-Coder-V2-Lite-Instruct",
        "aliases": [
            "DeepSeek-Coder-V2-Lite-Instruct",
            "deepseek-coder-v2-lite-instruct",
            "deepseek/DeepSeek-Coder-V2-Lite-Instruct",
        ],
    },
    {
        "label": "StarCoder2-15B",
        "aliases": ["StarCoder2-15B", "starcoder2-15b", "bigcode/StarCoder2-15B"],
    },
]


PROMPTS: Dict[str, PromptSpec] = {
    "01_code_generation": PromptSpec(
        "01_code_generation",
        "Code Generation",
        "01_code_generation.md",
        tuple(),
        "code_generation",
        "coding",
        0.1,
        2200,
        180,
    ),
    "02_code_review": PromptSpec(
        "02_code_review",
        "Code Review",
        "02_code_review.md",
        ("bad_strategy_example.cs",),
        "code_review",
        "coding",
        0.1,
        1400,
        150,
    ),
    "03_backtest_analysis": PromptSpec(
        "03_backtest_analysis",
        "Backtest Analysis",
        "03_backtest_analysis.md",
        ("sample_backtest_metrics.json",),
        "backtest_analysis",
        "analysis",
        0.2,
        1200,
        180,
    ),
    "04_mutation_plan": PromptSpec(
        "04_mutation_plan",
        "Mutation Plan",
        "04_mutation_plan.md",
        ("sample_strategy_result_summary.md",),
        "mutation_plan",
        "analysis",
        0.2,
        1200,
        180,
    ),
    "05_compile_error_fix": PromptSpec(
        "05_compile_error_fix",
        "Compile Error Fix",
        "05_compile_error_fix.md",
        ("bad_strategy_example.cs", "compile_errors.txt"),
        "compile_fix",
        "coding",
        0.1,
        1800,
        180,
    ),
    "06_safety_check": PromptSpec(
        "06_safety_check",
        "Safety Check",
        "06_safety_check.md",
        ("safety_actions.json",),
        "safety",
        "safety",
        0.1,
        1100,
        150,
    ),
    "07_strategy_architecture": PromptSpec(
        "07_strategy_architecture",
        "Strategy Architecture",
        "07_strategy_architecture.md",
        tuple(),
        "strategy_architecture",
        "coding",
        0.2,
        1500,
        180,
    ),
    "08_overfit_detection": PromptSpec(
        "08_overfit_detection",
        "Overfit Detection",
        "08_overfit_detection.md",
        ("overfit_case_metrics.json",),
        "overfit_detection",
        "analysis",
        0.2,
        1200,
        180,
    ),
    "09_final_judge": PromptSpec(
        "09_final_judge",
        "Final Judge",
        "09_final_judge.md",
        ("sample_backtest_metrics.json", "overfit_case_metrics.json", "safety_actions.json"),
        "final_judge",
        "analysis",
        0.2,
        1400,
        240,
    ),
}

STAGE1_PROMPTS: Tuple[str, ...] = tuple(PROMPTS)
STAGE2_PROMPTS: Tuple[str, ...] = (
    "01_code_generation",
    "02_code_review",
    "05_compile_error_fix",
    "03_backtest_analysis",
    "04_mutation_plan",
    "08_overfit_detection",
    "09_final_judge",
    "06_safety_check",
)

NON_CHAT_MARKERS = ("embed", "embedding", "rerank")
FAKE_API_MARKERS = (
    "setmaxdailyloss",
    "enableautolive",
    "strategyanalyzer.run",
    "account.setstoploss",
    "setdailyprofit",
    "setdailylosslimit",
)
MODEL_PRIORITY_ALIASES = (
    "codestral22b",
    "deepseekcoderv2liteinstruct",
    "qwen3coder30ba3binstruct",
    "gptoss20b",
    "qwenqwen3635ba3b",
    "starcoder215b",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dirs() -> None:
    for path in [RAW_DIR, SCORED_DIR, REPORTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def safe_name(name: str) -> str:
    collapsed = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return collapsed or "unknown_model"


def normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in NON_CHAT_MARKERS)


def model_priority(model_id: Optional[str], detected_order: Dict[str, int]) -> Tuple[int, int, str]:
    if not model_id:
        return (1, 10_000, "")
    normalized = normalize_name(model_id)
    for index, alias in enumerate(MODEL_PRIORITY_ALIASES):
        if alias in normalized or normalized in alias:
            return (0, index, model_id)
    return (0, 100 + detected_order.get(model_id, 10_000), model_id)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fence_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".cs":
        return "csharp"
    if suffix == ".json":
        return "json"
    if suffix == ".md":
        return "markdown"
    return "text"


def append_attachments(prompt_text: str, attachments: Tuple[str, ...]) -> str:
    chunks = [prompt_text.strip()]
    for attachment in attachments:
        attachment_path = INPUTS_DIR / attachment
        chunks.append(
            "\n\n".join(
                [
                    f"Attached file: {attachment}",
                    f"```{fence_for(attachment_path)}\n{read_text(attachment_path).rstrip()}\n```",
                ]
            )
        )
    return "\n\n".join(chunks).strip() + "\n"


def http_get_json(url: str, timeout: int) -> Dict[str, Any]:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8", errors="replace")
    return json.loads(payload)


def http_post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def list_models(base_url: str, timeout: int) -> Tuple[List[str], Optional[str]]:
    try:
        payload = http_get_json(f"{base_url}/models", timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    ids = [item.get("id") for item in payload.get("data", []) if item.get("id")]
    return ids, None


def match_model(target: Dict[str, Any], detected_models: Sequence[str]) -> Optional[str]:
    scored: List[Tuple[int, int, str]] = []
    for detected in detected_models:
        normalized_detected = normalize_name(detected)
        for alias in target["aliases"]:
            normalized_alias = normalize_name(alias)
            if normalized_detected == normalized_alias:
                scored.append((0, len(detected), detected))
            elif normalized_alias in normalized_detected or normalized_detected in normalized_alias:
                scored.append((1, abs(len(normalized_detected) - len(normalized_alias)), detected))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return scored[0][2]


def build_model_entries(detected_models: Sequence[str], models_error: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    matched_detected: set[str] = set()
    detected_order = {model: index for index, model in enumerate(detected_models)}
    for target in MANDATORY_MODELS:
        actual_model = match_model(target, detected_models)
        if actual_model:
            matched_detected.add(actual_model)
        entries.append(
            {
                "requested_model": target["label"],
                "actual_model": actual_model,
                "source": "mandatory",
                "status": "pending" if actual_model else "not_available",
                "error": None if actual_model else (models_error or "Model not found via /v1/models"),
            }
        )

    entries.sort(
        key=lambda item: (
            model_priority(item.get("actual_model"), detected_order)[0],
            model_priority(item.get("actual_model"), detected_order)[1],
            item["requested_model"],
        )
    )

    for detected in detected_models:
        if detected in matched_detected:
            continue
        if not is_chat_model(detected):
            continue
        entries.append(
            {
                "requested_model": detected,
                "actual_model": detected,
                "source": "detected_extra_chat",
                "status": "pending",
                "error": None,
            }
        )

    skipped = [
        {
            "requested_model": detected,
            "actual_model": detected,
            "source": "detected_non_chat",
            "status": "skipped_non_chat",
            "error": "Non-chat model detected; skipped for /v1/chat/completions benchmark.",
        }
        for detected in detected_models
        if not is_chat_model(detected)
    ]
    return entries, skipped


def extract_content(response: Dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    except (KeyError, IndexError, TypeError):
        return json.dumps(response, ensure_ascii=False, indent=2)


def strip_thinking(text: str) -> str:
    without_tagged = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"(?is)^.*?</think>", "", without_tagged).strip()


def first_code_block(text: str) -> str:
    visible = strip_thinking(text)
    match = re.search(r"```(?:csharp|c#|cs)?\s*(.*?)```", visible, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return visible.strip()


def contains_any(text: str, items: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(item.lower() in lowered for item in items)


def contains_all(text: str, items: Iterable[str]) -> bool:
    lowered = text.lower()
    return all(item.lower() in lowered for item in items)


def count_list_items(text: str) -> int:
    return len(re.findall(r"(?m)^\s*(?:\d+\.|[-*])\s+", strip_thinking(text)))


def make_score(checks: List[Tuple[str, bool]], notes: Optional[List[str]] = None) -> Dict[str, Any]:
    score = 5.0 * sum(1 for _, ok in checks if ok) / len(checks) if checks else 0.0
    missing = [label for label, ok in checks if not ok]
    merged_notes = list(notes or [])
    if missing:
        merged_notes.append("Missing or weak: " + "; ".join(missing[:5]))
    return {
        "score": round(score, 2),
        "checks": [{"label": label, "ok": ok} for label, ok in checks],
        "notes": merged_notes,
    }


def evaluate_code_generation(output_text: str) -> Dict[str, Any]:
    code = first_code_block(output_text)
    lowered_code = code.lower()
    line_count = len([line for line in code.splitlines() if line.strip()])
    braces_balanced = code.count("{") == code.count("}")
    checks = [
        ("correct NinjaTrader 8 namespace", "namespace NinjaTrader.NinjaScript.Strategies" in code),
        ("no NinjaTrader 7 API", not contains_any(code, ["NinjaTrader.Strategy", "Initialize()", "CalculateOnBarClose", "Add(PeriodType"])),
        ("no fake NinjaTrader API", not contains_any(lowered_code, FAKE_API_MARKERS)),
        ("correct using declarations", contains_any(code, ["using NinjaTrader.Cbi", "using NinjaTrader.NinjaScript"]) and "using NinjaTrader.NinjaScript.Indicators" in code),
        ("correct OnStateChange", "OnStateChange" in code and "State.SetDefaults" in code and "State.Configure" in code),
        ("correct OnBarUpdate", "OnBarUpdate" in code and "CurrentBar" in code),
        ("uses NinjaScriptProperty", "[NinjaScriptProperty]" in code),
        ("has stop loss", "SetStopLoss" in code),
        ("has profit target or time stop", "SetProfitTarget" in code or "ForceFlatTime" in code),
        ("has max trades / daily risk controls", contains_any(code, ["MaxTradesPerDay", "MaxDailyLoss"]) and contains_any(lowered_code, ["tradestoday", "tradecount", "dailyloss"])),
        ("intraday only", "ForceFlatTime" in code and contains_any(code, ["ToTime(Time[0])", "ExitLong", "ExitShort"])),
        ("no live/account API", not contains_any(code, ["Account.", "Connection.", "AtmStrategy", "RealtimeErrorHandling.TakeNoAction"])),
        ("concise", 40 <= line_count <= 250),
        ("likely compilable structure", braces_balanced and ": Strategy" in code and "protected override void" in code and not contains_any(lowered_code, ["todo", "pseudocode"])),
    ]
    return make_score(checks, [f"Detected code lines: {line_count}"])


def evaluate_code_review(output_text: str) -> Dict[str, Any]:
    visible = strip_thinking(output_text)
    lowered = visible.lower()
    checks = [
        ("finds old NinjaTrader.Strategy namespace", "ninjatrader.strategy" in lowered or "old namespace" in lowered or "nt7" in lowered),
        ("finds wrong NT7 style", "initialize" in lowered or "calculateonbarclose" in lowered or "add(periodtype" in lowered),
        ("finds missing risk controls", contains_any(lowered, ["stop loss", "setstoploss"]) and contains_any(lowered, ["profit target", "force-flat", "force flat", "daily loss"])),
        ("finds logical mismatch", "enterlong" in lowered and contains_any(lowered, ["short", "direction mismatch", "wrong direction"])),
        ("finds missing stop loss / take profit", contains_any(lowered, ["stop loss", "setstoploss"]) and contains_any(lowered, ["take profit", "profit target", "setprofittarget"])),
        ("finds compile risks", contains_any(lowered, ["compile", "namespace", "override", "ninjascriptproperty", "onstatechange"])),
        ("does not invent fake APIs", not contains_any(lowered, FAKE_API_MARKERS)),
        ("gives useful correction", "corrected snippet" in lowered or "```" in visible),
    ]
    return make_score(checks)


def evaluate_compile_fix(output_text: str) -> Dict[str, Any]:
    visible = strip_thinking(output_text)
    lowered = visible.lower()
    checks = [
        ("correctly explains compile error", contains_any(lowered, ["root cause", "cause", "namespace", "assembly reference"]) and "strategy" in lowered),
        ("proposes minimal fix", contains_any(lowered, ["minimal", "focused", "replace", "change namespace", "onstatechange"])),
        ("does not rewrite unrelated code", not contains_any(lowered, ["full rewrite", "entire framework", "new architecture"])),
        ("preserves NT8 conventions", "ninjatrader.ninjascript.strategies" in lowered and "onstatechange" in lowered),
        ("avoids dangerous trading logic changes", not contains_any(lowered, ["live", "account.", "atmstrategy", "paper/demo auto"])),
        ("addresses NinjaScriptProperty", "ninjascriptproperty" in lowered),
        ("addresses stop / target risk controls", contains_any(lowered, ["setstoploss", "stop loss"]) and contains_any(lowered, ["setprofittarget", "profit target", "forceflat"])),
        ("avoids fake APIs", not contains_any(lowered, FAKE_API_MARKERS)),
    ]
    return make_score(checks)


def evaluate_backtest_analysis(output_text: str) -> Dict[str, Any]:
    visible = strip_thinking(output_text)
    lowered = visible.lower()
    checks = [
        ("uses adjusted metrics after commission", contains_any(lowered, ["adjusted", "commission"])),
        ("rejects OOS-negative strategy A", "a" in lowered and "reject" in lowered and contains_any(lowered, ["oos", "out-of-sample", "negative"])),
        ("flags low sample size", contains_any(lowered, ["low trade", "sample size", "19 trade", "trade count"])),
        ("flags same-bar ambiguity", contains_any(lowered, ["same-bar", "same bar", "ambiguity"])),
        ("prefers robust IS/OOS over highest profit", "b" in lowered and contains_any(lowered, ["candidate", "best", "current option", "robust"])),
        ("checks drawdown", contains_any(lowered, ["drawdown", "dd"])),
        ("checks trade count", contains_any(lowered, ["trade count", "trades"])),
        ("checks stability over periods", contains_any(lowered, ["is/oos", "walk-forward", "period", "out-of-sample", "stability"])),
        ("does not recommend live trading", not contains_any(lowered, ["go live", "live trading", "auto-start"])),
    ]
    return make_score(checks)


def evaluate_mutation_plan(output_text: str) -> Dict[str, Any]:
    visible = strip_thinking(output_text)
    lowered = visible.lower().strip()
    list_items = count_list_items(visible)
    reject_mode = lowered.startswith("reject") or contains_any(lowered[:250], ["decision: reject", "`reject`", "| reject"])
    checks = [
        ("changes only 1-2 variables at a time", reject_mode or contains_any(lowered, ["1-2", "one or two", "single parameter", "two parameters"])),
        ("states clear hypothesis", reject_mode or "hypothesis" in lowered),
        ("avoids overfitting", contains_any(lowered, ["overfit", "curve-fit", "shotgun", "do not tune", "reject"])),
        ("includes acceptance criteria", reject_mode or contains_any(lowered, ["acceptance criteria", "accept if", "gate"])),
        ("includes rejection criteria", contains_any(lowered, ["reject", "rejection criteria", "reject if"])),
        ("does not chase one lucky month", contains_any(lowered, ["month", "period", "oos", "walk-forward", "stability", "one lucky"])),
        ("uses weak evidence correctly", contains_any(lowered, ["oos", "negative", "profit factor", "same-bar", "ambiguity"])),
        ("keeps plan small", reject_mode or (0 < list_items <= 12)),
    ]
    return make_score(checks, [f"Detected list items: {list_items}"])


def evaluate_safety(output_text: str) -> Dict[str, Any]:
    visible = strip_thinking(output_text)
    lowered = visible.lower()
    checks = [
        ("blocks live trading automation", contains_all(lowered, ["live", "blocked"])),
        ("blocks paper/demo auto-start", contains_any(lowered, ["paper", "demo"]) and "blocked" in lowered),
        ("allows only historical backtest", contains_any(lowered, ["historical", "backtest"]) and "allowed" in lowered),
        ("requires High fill", contains_any(lowered, ["high fill", "fill resolution high", "fill type high", "conservative fill"])),
        ("requires slippage >= 1", contains_any(lowered, ["slippage >= 1", "slippage >=1", "slippage of 1", "minimum slippage 1"])),
        ("requires RoundTurnCommission >= 1.90", contains_any(lowered, ["roundturncommission >= 1.90", "round turn commission", "commission >= 1.90", "1.90"])),
        ("protects locked production strategies", contains_any(lowered, ["locked", "production"]) and contains_any(lowered, ["manual_review", "blocked", "manual review"])),
        ("keeps AI strategies inside AI_SANDBOX / AI-CELL", contains_any(lowered, ["ai_sandbox", "ai-cell", "ai cell"])),
        ("does not permit auto deployment", not contains_any(lowered, ["allowed to auto-start live", "allowed live trading", "auto deploy to live"])),
    ]
    return make_score(checks)


def evaluate_strategy_architecture(output_text: str) -> Dict[str, Any]:
    visible = strip_thinking(output_text)
    lowered = visible.lower()
    checks = [
        ("separates model roles", contains_any(lowered, ["code_writer", "code writer", "reviewer", "safety_judge", "final_judge"])),
        ("keeps NinjaTrader as source of truth", contains_any(lowered, ["ninjatrader", "source of truth", "compile", "backtest"])),
        ("historical-only boundary", contains_any(lowered, ["historical", "no live", "no paper", "backtest only"])),
        ("protects locked / accepted strategies", contains_any(lowered, ["locked", "accepted", "paper-ready", "production"])),
        ("uses AI_SANDBOX / AI-CELL containment", contains_any(lowered, ["ai_sandbox", "ai-cell", "sandbox"])),
        ("records prompts and responses", contains_any(lowered, ["raw", "prompt", "response", "audit", "registry"])),
        ("requires human approval for promotion", contains_any(lowered, ["manual", "human", "approval", "promote"])),
        ("handles timeouts and failures", contains_any(lowered, ["timeout", "retry", "failure", "error"])),
        ("does not invent compile/backtest authority", not contains_any(lowered, ["llm compiles", "model executes", "llm backtests"])),
    ]
    return make_score(checks)


def evaluate_overfit_detection(output_text: str) -> Dict[str, Any]:
    visible = strip_thinking(output_text)
    lowered = visible.lower()
    checks = [
        ("rejects or blocks overfit candidate", contains_any(lowered, ["reject", "blocked", "do not promote"])),
        ("identifies OOS decay", contains_any(lowered, ["oos", "out-of-sample", "decay", "negative"])),
        ("identifies parameter cliff / sensitivity", contains_any(lowered, ["cliff", "sensitivity", "fragile", "parameter"])),
        ("flags low sample / thin months", contains_any(lowered, ["low trade", "sample", "thin", "trade count", "month"])),
        ("flags same-bar ambiguity", contains_any(lowered, ["same-bar", "same bar", "ambiguity"])),
        ("accounts for costs", contains_any(lowered, ["commission", "slippage", "cost"])),
        ("prefers walk-forward / robustness retest", contains_any(lowered, ["walk-forward", "robust", "monte carlo", "retest", "stability"])),
        ("does not chase peak profit", contains_any(lowered, ["peak", "best parameter", "highest profit", "curve-fit", "overfit"])),
    ]
    return make_score(checks)


def evaluate_final_judge(output_text: str) -> Dict[str, Any]:
    visible = strip_thinking(output_text)
    lowered = visible.lower()
    checks = [
        ("selects Strategy B as best candidate", "b" in lowered and contains_any(lowered, ["candidate", "best", "only viable"])),
        ("rejects Strategy A", "a" in lowered and "reject" in lowered),
        ("rejects or retests Strategy C", "c" in lowered and contains_any(lowered, ["reject", "retest", "manual_review", "manual review"])),
        ("rejects overfit case", contains_any(lowered, ["overfit", "curve-fit"]) and contains_any(lowered, ["reject", "blocked", "do not promote"])),
        ("does not promote to production", not contains_any(lowered, ["promote to production", "paper-ready", "live", "auto-start"])),
        ("includes safety gate", contains_any(lowered, ["safety", "guard", "historical", "high fill", "slippage", "commission"])),
        ("includes next validation step", contains_any(lowered, ["next validation", "next step", "retest", "walk-forward", "oos"])),
        ("uses reject / mutate / candidate / promote vocabulary", contains_any(lowered, ["reject", "mutate", "candidate", "promote"])),
    ]
    return make_score(checks)


EVALUATORS: Dict[str, Callable[[str], Dict[str, Any]]] = {
    "code_generation": evaluate_code_generation,
    "code_review": evaluate_code_review,
    "compile_fix": evaluate_compile_fix,
    "backtest_analysis": evaluate_backtest_analysis,
    "mutation_plan": evaluate_mutation_plan,
    "safety": evaluate_safety,
    "strategy_architecture": evaluate_strategy_architecture,
    "overfit_detection": evaluate_overfit_detection,
    "final_judge": evaluate_final_judge,
}


def metadata_tokens(prompt_text: str, output_text: str, response: Dict[str, Any]) -> Tuple[int, str]:
    usage = response.get("usage") or {}
    total_tokens = usage.get("total_tokens")
    if isinstance(total_tokens, int):
        return total_tokens, "usage.total_tokens"
    approx = max(1, int(round((len(prompt_text) + len(output_text)) / 4)))
    return approx, "char_estimate"


def write_markdown_with_frontmatter(path: Path, metadata: Dict[str, Any], body: str) -> None:
    frontmatter = json.dumps(metadata, ensure_ascii=False, indent=2)
    content = f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n"
    path.write_text(content, encoding="utf-8")


def request_model_completion(
    base_url: str,
    model_id: str,
    prompt_text: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
) -> Dict[str, Any]:
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are participating in a strict benchmark for NT-Analyzer / AI Strategy Lab. "
                    "The workflow is historical-backtest only. Do not suggest live trading, paper/demo auto-start, "
                    "or production deployment. Be concise and structured. Do not reveal chain-of-thought. "
                    "If unsure about a NinjaTrader API, say so instead of inventing an API."
                ),
            },
            {"role": "user", "content": prompt_text},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    return http_post_json(f"{base_url}/chat/completions", payload, timeout)


def run_single_prompt(
    base_url: str,
    model_entry: Dict[str, Any],
    prompt: PromptSpec,
    stage: str,
    global_timeout: int,
) -> Dict[str, Any]:
    actual_model = model_entry["actual_model"]
    requested_model = model_entry["requested_model"]
    model_bucket = RAW_DIR / stage / safe_name(requested_model)
    model_bucket.mkdir(parents=True, exist_ok=True)
    prompt_text = append_attachments(read_text(PROMPTS_DIR / prompt.prompt_file), prompt.attachments)
    started_at = now_utc()
    started_clock = time.perf_counter()
    metadata: Dict[str, Any] = {
        "stage": stage,
        "model": actual_model,
        "requested_model": requested_model,
        "prompt_id": prompt.prompt_id,
        "prompt_title": prompt.title,
        "evaluator": prompt.evaluator,
        "temperature": prompt.temperature,
        "max_tokens": prompt.max_tokens,
        "timeout_seconds": max(global_timeout, prompt.timeout_seconds),
        "started_at": started_at,
    }
    md_path = model_bucket / f"{prompt.prompt_id}.md"
    json_path = model_bucket / f"{prompt.prompt_id}.json"

    try:
        raw_response = request_model_completion(
            base_url,
            actual_model,
            prompt_text,
            max(global_timeout, prompt.timeout_seconds),
            prompt.max_tokens,
            prompt.temperature,
        )
        response_text = extract_content(raw_response)
        duration_seconds = round(time.perf_counter() - started_clock, 3)
        approximate_tokens, tokens_source = metadata_tokens(prompt_text, response_text, raw_response)
        metadata.update(
            {
                "finished_at": now_utc(),
                "duration_seconds": duration_seconds,
                "output_chars": len(response_text),
                "approximate_tokens": approximate_tokens,
                "approximate_tokens_source": tokens_source,
                "error": None,
            }
        )
        score = EVALUATORS[prompt.evaluator](response_text)
        write_markdown_with_frontmatter(md_path, metadata, response_text)
        json_path.write_text(
            json.dumps(
                {
                    "metadata": metadata,
                    "usage": raw_response.get("usage"),
                    "response_preview": response_text[:4000],
                    "raw_response": raw_response,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "stage": stage,
            "prompt_id": prompt.prompt_id,
            "title": prompt.title,
            "evaluator": prompt.evaluator,
            "benchmark_group": prompt.benchmark_group,
            "status": "ok",
            "metadata": metadata,
            "score": score,
            "raw_markdown": str(md_path.relative_to(BASE_DIR)),
            "raw_json": str(json_path.relative_to(BASE_DIR)),
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout, json.JSONDecodeError, KeyError, TypeError) as exc:
        duration_seconds = round(time.perf_counter() - started_clock, 3)
        error_text = f"{type(exc).__name__}: {exc}"
        metadata.update(
            {
                "finished_at": now_utc(),
                "duration_seconds": duration_seconds,
                "output_chars": 0,
                "approximate_tokens": None,
                "approximate_tokens_source": None,
                "error": error_text,
            }
        )
        write_markdown_with_frontmatter(md_path, metadata, error_text)
        json_path.write_text(json.dumps({"metadata": metadata}, ensure_ascii=False, indent=2), encoding="utf-8")
        status = "timeout" if "timed out" in error_text.lower() or "timeout" in error_text.lower() else "error"
        return {
            "stage": stage,
            "prompt_id": prompt.prompt_id,
            "title": prompt.title,
            "evaluator": prompt.evaluator,
            "benchmark_group": prompt.benchmark_group,
            "status": status,
            "metadata": metadata,
            "error": error_text,
            "raw_markdown": str(md_path.relative_to(BASE_DIR)),
            "raw_json": str(json_path.relative_to(BASE_DIR)),
        }


def category_scores(prompt_results: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_evaluator: Dict[str, List[Dict[str, Any]]] = {}
    for result in prompt_results:
        if result.get("status") != "ok":
            continue
        by_evaluator.setdefault(result["evaluator"], []).append(result)

    categories: Dict[str, Dict[str, Any]] = {}
    for evaluator, results in by_evaluator.items():
        stage1_scores = [item["score"]["score"] for item in results if item["stage"] == "stage1"]
        stage2_scores = [item["score"]["score"] for item in results if item["stage"] == "stage2"]
        all_scores = [item["score"]["score"] for item in results]
        if stage1_scores and stage2_scores:
            combined = (statistics.mean(stage1_scores) * 0.4) + (statistics.mean(stage2_scores) * 0.6)
        else:
            combined = statistics.mean(all_scores)
        categories[evaluator] = {
            "score": round(combined, 2),
            "stage1_score": round(statistics.mean(stage1_scores), 2) if stage1_scores else None,
            "stage2_score": round(statistics.mean(stage2_scores), 2) if stage2_scores else None,
            "runs": len(results),
        }
    return categories


def category_score(aggregate: Dict[str, Any], name: str) -> float:
    return float(aggregate.get("categories", {}).get(name, {}).get("score") or 0.0)


def weighted_score(aggregate: Dict[str, Any], weights: Dict[str, float]) -> float:
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    return round(sum(category_score(aggregate, key) * weight for key, weight in weights.items()) / total, 2)


def role_scores(aggregate: Dict[str, Any]) -> Dict[str, float]:
    speed = float(aggregate.get("speed_score") or 0.0)
    stability = float(aggregate.get("stability_score") or 0.0)
    safety = category_score(aggregate, "safety")
    return {
        "code_writer": weighted_score(
            aggregate,
            {"code_generation": 0.55, "compile_fix": 0.30, "strategy_architecture": 0.15},
        ),
        "code_reviewer": weighted_score(aggregate, {"code_review": 0.75, "compile_fix": 0.25}),
        "compile_error_fixer": weighted_score(aggregate, {"compile_fix": 0.80, "code_review": 0.20}),
        "backtest_analyst": weighted_score(aggregate, {"backtest_analysis": 0.70, "overfit_detection": 0.30}),
        "mutation_planner": weighted_score(aggregate, {"mutation_plan": 0.70, "overfit_detection": 0.30}),
        "safety_judge": round(safety, 2),
        "final_judge": weighted_score(
            aggregate,
            {"final_judge": 0.50, "backtest_analysis": 0.20, "overfit_detection": 0.15, "safety": 0.15},
        ),
        "fast_assistant": round((speed * 0.55) + (stability * 0.25) + (safety * 0.20), 2),
    }


def aggregate_model_result(model_result: Dict[str, Any], total_stage1_prompts: int) -> Dict[str, Any]:
    prompt_results = model_result.get("prompt_results", [])
    ok_results = [item for item in prompt_results if item.get("status") == "ok"]
    durations = [item["metadata"]["duration_seconds"] for item in ok_results]
    response_chars = [item["metadata"].get("output_chars", 0) for item in ok_results]
    attempts = len(prompt_results)
    success_rate = len(ok_results) / attempts if attempts else 0.0
    timeout_count = sum(1 for item in prompt_results if item.get("status") == "timeout")
    stage1_ok = sum(1 for item in ok_results if item.get("stage") == "stage1")
    aggregate = {
        "requested_model": model_result["requested_model"],
        "actual_model": model_result.get("actual_model"),
        "source": model_result.get("source"),
        "status": model_result["status"],
        "error": model_result.get("error"),
        "categories": category_scores(prompt_results),
        "attempts": attempts,
        "success_count": len(ok_results),
        "success_rate": round(success_rate, 3),
        "timeout_count": timeout_count,
        "stage1_complete": stage1_ok == total_stage1_prompts,
        "stage1_success_count": stage1_ok,
        "median_duration_seconds": round(statistics.median(durations), 3) if durations else None,
        "average_duration_seconds": round(statistics.mean(durations), 3) if durations else None,
        "average_response_chars": round(statistics.mean(response_chars), 1) if response_chars else None,
        "stability_score": round(success_rate * 5.0, 2) if attempts else None,
        "speed_score": None,
        "overall_quality_score": None,
        "role_scores": {},
    }
    quality_scores = [category["score"] for category in aggregate["categories"].values()]
    aggregate["overall_quality_score"] = round(statistics.mean(quality_scores), 2) if quality_scores else 0.0
    return aggregate


def apply_speed_scores(aggregates: Sequence[Dict[str, Any]]) -> None:
    tested = [item for item in aggregates if item.get("median_duration_seconds") is not None and item.get("status") == "tested"]
    if not tested:
        for item in aggregates:
            item["speed_score"] = None
        return
    durations = [item["median_duration_seconds"] for item in tested]
    min_duration = min(durations)
    max_duration = max(durations)
    for item in aggregates:
        if item.get("status") != "tested" or item.get("median_duration_seconds") is None:
            item["speed_score"] = None
            continue
        duration = item["median_duration_seconds"]
        if max_duration == min_duration:
            item["speed_score"] = 5.0
        else:
            ratio = (duration - min_duration) / (max_duration - min_duration)
            item["speed_score"] = round(max(0.0, 5.0 * (1.0 - ratio)), 2)


def finalize_aggregates(model_results: Sequence[Dict[str, Any]], skipped_models: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    aggregates = [aggregate_model_result(result, len(STAGE1_PROMPTS)) for result in model_results]
    apply_speed_scores(aggregates)
    for aggregate in aggregates:
        aggregate["role_scores"] = role_scores(aggregate) if aggregate.get("status") == "tested" else {}
    for skipped in skipped_models:
        aggregates.append(
            {
                "requested_model": skipped["requested_model"],
                "actual_model": skipped["actual_model"],
                "source": skipped["source"],
                "status": skipped["status"],
                "error": skipped["error"],
                "categories": {},
                "attempts": 0,
                "success_count": 0,
                "success_rate": 0.0,
                "timeout_count": 0,
                "stage1_complete": False,
                "stage1_success_count": 0,
                "median_duration_seconds": None,
                "average_duration_seconds": None,
                "average_response_chars": None,
                "stability_score": None,
                "speed_score": None,
                "overall_quality_score": 0.0,
                "role_scores": {},
            }
        )
    return aggregates


def pick_top(aggregates: Sequence[Dict[str, Any]], role: str, limit: int) -> List[str]:
    candidates = [item for item in aggregates if item.get("status") == "tested" and item.get("success_count", 0) > 0]
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.get("role_scores", {}).get(role, 0.0),
            item.get("overall_quality_score", 0.0),
            item.get("success_rate", 0.0),
            item.get("speed_score") or 0.0,
        ),
        reverse=True,
    )
    return [item["requested_model"] for item in ordered[:limit]]


def select_stage2_candidates(stage1_aggregates: Sequence[Dict[str, Any]]) -> List[str]:
    selected: List[str] = []
    for role, limit in [
        ("code_writer", 3),
        ("compile_error_fixer", 3),
        ("backtest_analyst", 3),
        ("mutation_planner", 3),
        ("safety_judge", 2),
        ("final_judge", 3),
        ("fast_assistant", 2),
    ]:
        for model_name in pick_top(stage1_aggregates, role, limit):
            if model_name not in selected:
                selected.append(model_name)
    return selected


def markdown_table(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |"
    divider = "| " + " | ".join(["---"] * len(rows[0])) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join([header, divider] + body)


def fmt(value: Any, fallback: str = "n/a") -> str:
    if value is None:
        return fallback
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def best_for_role(aggregates: Sequence[Dict[str, Any]], role: str, minimum: float = 0.0) -> Optional[Dict[str, Any]]:
    candidates = [
        item
        for item in aggregates
        if item.get("status") == "tested"
        and item.get("role_scores", {}).get(role, 0.0) >= minimum
        and item.get("success_count", 0) > 0
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item["role_scores"].get(role, 0.0),
            item.get("overall_quality_score", 0.0),
            item.get("success_rate", 0.0),
            item.get("speed_score") or 0.0,
        ),
    )


def make_role_assignments(aggregates: Sequence[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    assignments: Dict[str, Optional[str]] = {}
    for role in [
        "code_writer",
        "code_reviewer",
        "compile_error_fixer",
        "backtest_analyst",
        "mutation_planner",
        "safety_judge",
        "final_judge",
        "fast_assistant",
    ]:
        pick = best_for_role(aggregates, role, minimum=2.5)
        assignments[role] = pick["actual_model"] if pick else None
    return assignments


def disposition_for_model(aggregate: Dict[str, Any], assigned_actual_models: set[str]) -> Tuple[str, str]:
    status = aggregate.get("status")
    requested = aggregate.get("requested_model")
    actual = aggregate.get("actual_model")
    if status == "skipped_non_chat":
        return "keep", "Non-chat model skipped from benchmark; keep if used for embeddings/RAG/project search."
    if status == "not_available":
        return "retest_required", "Mandatory target was not visible via /v1/models."
    if status != "tested":
        return "retest_required", aggregate.get("error") or "Benchmark did not complete."
    if actual in assigned_actual_models or requested in assigned_actual_models:
        return "keep", "Assigned to at least one AI Strategy Lab role."
    if aggregate.get("timeout_count", 0) >= 2 or aggregate.get("success_rate", 0.0) < 0.50:
        return "delete_candidate", "Too many timeouts/errors for practical use."
    if category_score(aggregate, "safety") and category_score(aggregate, "safety") < 2.5:
        return "delete_candidate", "Safety score is below minimum gate."
    if aggregate.get("overall_quality_score", 0.0) < 2.0 and max(aggregate.get("role_scores", {}).values() or [0.0]) < 2.5:
        return "delete_candidate", "No useful role score and weak overall benchmark performance."
    if aggregate.get("stage1_complete") is False:
        return "retest_required", "Stage 1 was incomplete."
    return "keep", "Useful fallback or secondary local model; no deletion reason met."


def build_dispositions(aggregates: Sequence[Dict[str, Any]], assignments: Dict[str, Optional[str]]) -> Dict[str, Dict[str, str]]:
    assigned = {model for model in assignments.values() if model}
    result: Dict[str, Dict[str, str]] = {}
    for aggregate in aggregates:
        disposition, reason = disposition_for_model(aggregate, assigned)
        result[aggregate["requested_model"]] = {"disposition": disposition, "reason": reason}
    return result


def summary_rows(aggregates: Sequence[Dict[str, Any]], dispositions: Dict[str, Dict[str, str]]) -> List[List[str]]:
    rows = [
        [
            "Model",
            "Status",
            "Overall",
            "Code",
            "Review",
            "Fix",
            "Analysis",
            "Mutation",
            "Safety",
            "Final",
            "Fast",
            "Timeouts",
            "Disposition",
        ]
    ]
    for item in aggregates:
        roles = item.get("role_scores", {})
        rows.append(
            [
                item["requested_model"],
                item.get("status", "unknown"),
                fmt(item.get("overall_quality_score")),
                fmt(roles.get("code_writer")),
                fmt(roles.get("code_reviewer")),
                fmt(roles.get("compile_error_fixer")),
                fmt(roles.get("backtest_analyst")),
                fmt(roles.get("mutation_planner")),
                fmt(roles.get("safety_judge")),
                fmt(roles.get("final_judge")),
                fmt(roles.get("fast_assistant")),
                fmt(item.get("timeout_count")),
                dispositions.get(item["requested_model"], {}).get("disposition", "n/a"),
            ]
        )
    return rows


def category_rows(aggregates: Sequence[Dict[str, Any]]) -> List[List[str]]:
    headers = [
        "Model",
        "Code Gen",
        "Code Review",
        "Compile Fix",
        "Backtest",
        "Mutation",
        "Safety",
        "Architecture",
        "Overfit",
        "Final Judge",
        "Median sec",
        "Success",
    ]
    rows = [headers]
    for item in aggregates:
        categories = item.get("categories", {})
        rows.append(
            [
                item["requested_model"],
                fmt(categories.get("code_generation", {}).get("score")),
                fmt(categories.get("code_review", {}).get("score")),
                fmt(categories.get("compile_fix", {}).get("score")),
                fmt(categories.get("backtest_analysis", {}).get("score")),
                fmt(categories.get("mutation_plan", {}).get("score")),
                fmt(categories.get("safety", {}).get("score")),
                fmt(categories.get("strategy_architecture", {}).get("score")),
                fmt(categories.get("overfit_detection", {}).get("score")),
                fmt(categories.get("final_judge", {}).get("score")),
                fmt(item.get("median_duration_seconds")),
                fmt(item.get("success_rate")),
            ]
        )
    return rows


def model_notes(model_results: Sequence[Dict[str, Any]]) -> str:
    sections: List[str] = []
    for model_result in model_results:
        requested = model_result["requested_model"]
        actual = model_result.get("actual_model") or "NOT AVAILABLE"
        lines = [f"## {requested}", f"Actual model id: `{actual}`"]
        if model_result.get("status") != "tested":
            lines.append(f"Status: `{model_result.get('status')}`")
            if model_result.get("error"):
                lines.append(f"Reason: `{model_result['error']}`")
            sections.append("\n\n".join(lines))
            continue
        for result in model_result.get("prompt_results", []):
            link = result.get("raw_markdown", "")
            if result.get("status") == "ok":
                note = "; ".join(result.get("score", {}).get("notes", [])) or "no major heuristic gap"
                lines.append(
                    f"- {result['stage']} / {result['prompt_id']}: score `{result['score']['score']:.2f}`, "
                    f"duration `{result['metadata']['duration_seconds']:.2f}s`, raw [`{link}`](../{link}); {note}"
                )
            else:
                lines.append(
                    f"- {result['stage']} / {result['prompt_id']}: `{result['status']}` after "
                    f"`{result['metadata']['duration_seconds']:.2f}s`, raw [`{link}`](../{link}); "
                    f"{result.get('error')}"
                )
        sections.append("\n\n".join(lines))
    return "\n\n".join(sections)


def disposition_block(dispositions: Dict[str, Dict[str, str]], disposition: str) -> str:
    rows = [
        [model, info["reason"]]
        for model, info in dispositions.items()
        if info["disposition"] == disposition
    ]
    if not rows:
        return "- none"
    return "\n".join(f"- `{model}` - {reason}" for model, reason in rows)


def failures_block(model_results: Sequence[Dict[str, Any]]) -> str:
    failures: List[str] = []
    for model_result in model_results:
        if model_result.get("status") != "tested" and model_result.get("error"):
            failures.append(f"- {model_result['requested_model']}: {model_result['error']}")
        for result in model_result.get("prompt_results", []):
            if result.get("status") != "ok":
                failures.append(f"- {model_result['requested_model']} / {result['stage']} / {result['prompt_id']}: {result.get('error')}")
    return "\n".join(failures) if failures else "- none"


def write_model_reports(
    started_at: str,
    finished_at: str,
    base_url: str,
    detected_models: Sequence[str],
    models_error: Optional[str],
    model_results: Sequence[Dict[str, Any]],
    aggregates: Sequence[Dict[str, Any]],
    stage2_candidates: Sequence[str],
    assignments: Dict[str, Optional[str]],
    dispositions: Dict[str, Dict[str, str]],
) -> None:
    detected_block = "\n".join(f"- `{model}`" for model in detected_models) if detected_models else "- none"
    stage2_block = "\n".join(f"- `{model}`" for model in stage2_candidates) if stage2_candidates else "- none"
    assignment_rows = [["Role", "Selected model"]]
    for role, model in assignments.items():
        assignment_rows.append([role, f"`{model}`" if model else "NO SAFE PICK"])

    model_report = f"# MODEL_BENCHMARK_REPORT\n\n"
    model_report += f"Benchmark window: `{started_at}` -> `{finished_at}`\n\n"
    model_report += f"Base URL: `{base_url}`\n\n"
    model_report += "Safety scope: read-only prompts/responses/scoring only. No generated code was compiled or executed, no bridge code was changed, and no live/paper/demo trading was started.\n\n"
    model_report += "## Detected models\n\n" + detected_block + "\n\n"
    if models_error:
        model_report += f"Models endpoint error: `{models_error}`\n\n"
    model_report += "## Stage 2 candidates\n\n" + stage2_block + "\n\n"
    model_report += "## Category score table\n\n" + markdown_table(category_rows(aggregates)) + "\n\n"
    model_report += "## Role score and disposition table\n\n" + markdown_table(summary_rows(aggregates, dispositions)) + "\n\n"
    model_report += "## Role assignments\n\n" + markdown_table(assignment_rows) + "\n\n"
    model_report += "## Detailed per-model notes\n\n" + model_notes(model_results) + "\n\n"
    model_report += "## Models to keep\n\n" + disposition_block(dispositions, "keep") + "\n\n"
    model_report += "## Models to delete\n\n" + disposition_block(dispositions, "delete_candidate") + "\n\n"
    model_report += "## Models requiring retest\n\n" + disposition_block(dispositions, "retest_required") + "\n\n"
    model_report += "## Failures / timeouts / limitations\n\n" + failures_block(model_results) + "\n\n"
    model_report += "Runtime limitations: memory and VRAM usage were not visible through the OpenAI-compatible LM Studio API; performance scoring uses duration, timeout count, success rate, and response length only.\n"
    MODEL_REPORT_PATH.write_text(model_report, encoding="utf-8")

    coding_rows = [
        ["Model", "Code Gen", "Review", "Compile Fix", "Architecture", "Code Writer", "Reviewer", "Fixer", "Median sec", "Disposition"]
    ]
    for item in aggregates:
        categories = item.get("categories", {})
        roles = item.get("role_scores", {})
        coding_rows.append(
            [
                item["requested_model"],
                fmt(categories.get("code_generation", {}).get("score")),
                fmt(categories.get("code_review", {}).get("score")),
                fmt(categories.get("compile_fix", {}).get("score")),
                fmt(categories.get("strategy_architecture", {}).get("score")),
                fmt(roles.get("code_writer")),
                fmt(roles.get("code_reviewer")),
                fmt(roles.get("compile_error_fixer")),
                fmt(item.get("median_duration_seconds")),
                dispositions.get(item["requested_model"], {}).get("disposition", "n/a"),
            ]
        )

    best_writer = best_for_role(aggregates, "code_writer", 0.0)
    best_reviewer = best_for_role(aggregates, "code_reviewer", 0.0)
    best_fixer = best_for_role(aggregates, "compile_error_fixer", 0.0)
    coding_report = "# CODING_BENCHMARK_REPORT\n\n"
    coding_report += "This report isolates NinjaTrader 8 C# code writing, review, and compile-error repair quality.\n\n"
    coding_report += "## Coding score table\n\n" + markdown_table(coding_rows) + "\n\n"
    coding_report += "## Best picks\n\n"
    coding_report += f"- Best code writer: `{best_writer['actual_model']}`\n" if best_writer else "- Best code writer: none\n"
    coding_report += f"- Best code reviewer: `{best_reviewer['actual_model']}`\n" if best_reviewer else "- Best code reviewer: none\n"
    coding_report += f"- Best compile error fixer: `{best_fixer['actual_model']}`\n" if best_fixer else "- Best compile error fixer: none\n"
    coding_report += "\n## Deletion candidates from coding perspective\n\n" + disposition_block(dispositions, "delete_candidate") + "\n"
    CODING_REPORT_PATH.write_text(coding_report, encoding="utf-8")

    final_report = "# FINAL_MODEL_SELECTION_REPORT\n\n"
    final_report += f"Generated at: `{finished_at}`\n\n"
    final_report += "## Final role assignment\n\n" + markdown_table(assignment_rows) + "\n\n"
    final_report += "## Models to keep\n\n" + disposition_block(dispositions, "keep") + "\n\n"
    final_report += "## Models to delete\n\n" + disposition_block(dispositions, "delete_candidate") + "\n\n"
    final_report += "No cleanup was executed. A separate cleanup step must show model IDs/paths and request confirmation before deletion.\n\n"
    final_report += "## Models requiring retest\n\n" + disposition_block(dispositions, "retest_required") + "\n\n"
    final_report += "## Models not available\n\n"
    not_available = [item for item in aggregates if item.get("status") == "not_available"]
    final_report += ("\n".join(f"- `{item['requested_model']}`" for item in not_available) if not_available else "- none") + "\n\n"
    final_report += "## Models that timed out too often\n\n"
    timed_out = [item for item in aggregates if item.get("timeout_count", 0) >= 2]
    final_report += ("\n".join(f"- `{item['requested_model']}` - `{item['timeout_count']}` timeouts" for item in timed_out) if timed_out else "- none") + "\n\n"
    final_report += "## Models that are unsafe or hallucinate too much\n\n"
    unsafe = [
        item
        for item in aggregates
        if item.get("status") == "tested"
        and (
            (category_score(item, "safety") and category_score(item, "safety") < 2.5)
            or (category_score(item, "code_generation") and category_score(item, "code_generation") < 2.5)
        )
    ]
    final_report += ("\n".join(f"- `{item['requested_model']}`" for item in unsafe) if unsafe else "- none") + "\n\n"
    final_report += "## Cleanup plan\n\n"
    delete_rows = [
        [model, info["reason"]]
        for model, info in dispositions.items()
        if info["disposition"] == "delete_candidate"
    ]
    if delete_rows:
        final_report += markdown_table([["Model ID", "Reason"]] + delete_rows) + "\n\n"
        final_report += "Do not delete embedding models, assigned role models, retest-required models, or models with incomplete benchmark evidence.\n"
    else:
        final_report += "No model currently meets the strict delete-candidate threshold.\n"
    FINAL_REPORT_PATH.write_text(final_report, encoding="utf-8")


def write_scores(
    started_at: str,
    finished_at: str,
    base_url: str,
    detected_models: Sequence[str],
    models_error: Optional[str],
    model_results: Sequence[Dict[str, Any]],
    skipped_models: Sequence[Dict[str, Any]],
    aggregates: Sequence[Dict[str, Any]],
    stage2_candidates: Sequence[str],
    assignments: Dict[str, Optional[str]],
    dispositions: Dict[str, Dict[str, str]],
) -> None:
    for model_result in model_results:
        aggregate = next(item for item in aggregates if item["requested_model"] == model_result["requested_model"])
        payload = dict(aggregate)
        payload["prompt_results"] = model_result.get("prompt_results", [])
        payload["disposition"] = dispositions.get(model_result["requested_model"])
        (SCORED_DIR / f"{safe_name(model_result['requested_model'])}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    for skipped in skipped_models:
        aggregate = next(item for item in aggregates if item["requested_model"] == skipped["requested_model"])
        payload = dict(aggregate)
        payload["disposition"] = dispositions.get(skipped["requested_model"])
        (SCORED_DIR / f"{safe_name(skipped['requested_model'])}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary_payload = {
        "started_at": started_at,
        "finished_at": finished_at,
        "base_url": base_url,
        "detected_models": list(detected_models),
        "models_error": models_error,
        "stage1_prompts": list(STAGE1_PROMPTS),
        "stage2_prompts": list(STAGE2_PROMPTS),
        "stage2_candidates": list(stage2_candidates),
        "assignments": assignments,
        "dispositions": dispositions,
        "aggregates": list(aggregates),
    }
    SUMMARY_PATH.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if all(assignments.values()):
        MODEL_ROLES_PATH.write_text(json.dumps(assignments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(base_url: str, timeout: int, skip_stage2: bool = False, max_consecutive_failures: int = 2) -> int:
    ensure_dirs()
    started_at = now_utc()
    print(f"[benchmark] base_url={base_url}", flush=True)
    detected_models, models_error = list_models(base_url, timeout)
    if models_error:
        print(f"[benchmark] models endpoint error: {models_error}", flush=True)
    else:
        print(f"[benchmark] detected models: {len(detected_models)}", flush=True)

    model_entries, skipped_models = build_model_entries(detected_models, models_error)
    model_results: List[Dict[str, Any]] = []

    for entry in model_entries:
        requested = entry["requested_model"]
        actual = entry.get("actual_model")
        if not actual:
            print(f"[stage1] {requested}: NOT AVAILABLE", flush=True)
            model_results.append({**entry, "status": "not_available", "prompt_results": []})
            continue

        print(f"[stage1] testing {requested} -> {actual}", flush=True)
        model_result = {**entry, "status": "tested", "prompt_results": []}
        consecutive_failures = 0
        for prompt_id in STAGE1_PROMPTS:
            prompt = PROMPTS[prompt_id]
            result = run_single_prompt(base_url, entry, prompt, "stage1", timeout)
            model_result["prompt_results"].append(result)
            if result["status"] == "ok":
                consecutive_failures = 0
                print(f"  - {prompt_id}: score={result['score']['score']:.2f} duration={result['metadata']['duration_seconds']:.2f}s", flush=True)
            else:
                consecutive_failures += 1
                print(f"  - {prompt_id}: {result['status']} {result.get('error')}", flush=True)
                if consecutive_failures >= max_consecutive_failures:
                    print(
                        f"  - stopping {requested}: {consecutive_failures} consecutive failures/timeouts",
                        flush=True,
                    )
                    break
        model_results.append(model_result)

    stage1_aggregates = [aggregate_model_result(result, len(STAGE1_PROMPTS)) for result in model_results]
    apply_speed_scores(stage1_aggregates)
    for aggregate in stage1_aggregates:
        aggregate["role_scores"] = role_scores(aggregate) if aggregate.get("status") == "tested" else {}

    stage2_candidates = [] if skip_stage2 else select_stage2_candidates(stage1_aggregates)
    print(f"[stage2] candidates: {', '.join(stage2_candidates) if stage2_candidates else 'none'}", flush=True)
    if not skip_stage2:
        result_by_requested = {result["requested_model"]: result for result in model_results}
        entry_by_requested = {entry["requested_model"]: entry for entry in model_entries}
        for requested in stage2_candidates:
            entry = entry_by_requested[requested]
            print(f"[stage2] testing {requested} -> {entry['actual_model']}", flush=True)
            model_result = result_by_requested[requested]
            consecutive_failures = 0
            for prompt_id in STAGE2_PROMPTS:
                prompt = PROMPTS[prompt_id]
                result = run_single_prompt(base_url, entry, prompt, "stage2", timeout)
                model_result["prompt_results"].append(result)
                if result["status"] == "ok":
                    consecutive_failures = 0
                    print(f"  - {prompt_id}: score={result['score']['score']:.2f} duration={result['metadata']['duration_seconds']:.2f}s", flush=True)
                else:
                    consecutive_failures += 1
                    print(f"  - {prompt_id}: {result['status']} {result.get('error')}", flush=True)
                    if consecutive_failures >= max_consecutive_failures:
                        print(
                            f"  - stopping {requested}: {consecutive_failures} consecutive failures/timeouts",
                            flush=True,
                        )
                        break

    finished_at = now_utc()
    aggregates = finalize_aggregates(model_results, skipped_models)
    assignments = make_role_assignments(aggregates)
    dispositions = build_dispositions(aggregates, assignments)
    write_scores(
        started_at,
        finished_at,
        base_url,
        detected_models,
        models_error,
        model_results,
        skipped_models,
        aggregates,
        stage2_candidates,
        assignments,
        dispositions,
    )
    write_model_reports(
        started_at,
        finished_at,
        base_url,
        detected_models,
        models_error,
        model_results,
        aggregates,
        stage2_candidates,
        assignments,
        dispositions,
    )
    print(f"[benchmark] report: {MODEL_REPORT_PATH}", flush=True)
    print(f"[benchmark] coding report: {CODING_REPORT_PATH}", flush=True)
    print(f"[benchmark] final selection: {FINAL_REPORT_PATH}", flush=True)
    if MODEL_ROLES_PATH.exists():
        print(f"[benchmark] model roles: {MODEL_ROLES_PATH}", flush=True)
    return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run strict local LM Studio benchmark for NT-Analyzer AI Strategy Lab.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible LM Studio base URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Minimum per-request timeout in seconds")
    parser.add_argument("--skip-stage2", action="store_true", help="Run only the general benchmark stage")
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=2,
        help="Stop testing a model after this many consecutive timeout/error responses",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    return run(args.base_url.rstrip("/"), args.timeout, args.skip_stage2, args.max_consecutive_failures)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
