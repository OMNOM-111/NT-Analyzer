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

import run_benchmark as base


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
AI_LAB_DIR = BASE_DIR.parent
PROMPTS_DIR = BASE_DIR / "prompts"
INPUTS_DIR = BASE_DIR / "test_inputs"
RESULTS_DIR = BASE_DIR / "results"
RAW_LARGE_DIR = RESULTS_DIR / "raw_large"
SCORED_LARGE_DIR = RESULTS_DIR / "scored_large"
REPORTS_DIR = BASE_DIR / "reports"
COMPILE_SANDBOX_DIR = BASE_DIR / "AI_SANDBOX_COMPILE_TEST"

LONG_REPORT = REPORTS_DIR / "LONG_TIMEOUT_MODEL_BENCHMARK_REPORT.md"
COMPILE_REPORT = REPORTS_DIR / "COMPILE_BENCHMARK_REPORT.md"
BACKTEST_REPORT = REPORTS_DIR / "BACKTEST_BENCHMARK_REPORT.md"
FINAL_REPORT = REPORTS_DIR / "FINAL_LARGE_MODEL_SELECTION_REPORT.md"
LARGE_SUMMARY = SCORED_LARGE_DIR / "large_summary.json"
MODEL_ROLES_PATH = AI_LAB_DIR / "model_roles.json"

DEFAULT_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")


@dataclass(frozen=True)
class PromptSpec:
    prompt_id: str
    title: str
    prompt_file: str
    attachments: Tuple[str, ...]
    evaluator: str
    temperature: float
    max_tokens: int


MANDATORY_TARGETS = [
    {
        "label": "openai/gpt-oss-20b",
        "aliases": ["openai/gpt-oss-20b", "gpt-oss-20b"],
    },
    {
        "label": "Qwen3-Coder-30B-A3B-Instruct",
        "aliases": ["Qwen3-Coder-30B-A3B-Instruct", "qwen3-coder-30b-a3b-instruct"],
    },
    {
        "label": "qwen/qwen3.6-35b-a3b",
        "aliases": ["qwen/qwen3.6-35b-a3b", "qwen3.6-35b-a3b"],
    },
    {
        "label": "Codestral-22B",
        "aliases": ["Codestral-22B", "codestral-22b", "codestral-22b-v0.1"],
    },
    {
        "label": "DeepSeek-Coder-V2-Lite-Instruct",
        "aliases": ["DeepSeek-Coder-V2-Lite-Instruct", "deepseek-coder-v2-lite-instruct"],
    },
]

MODEL_PRIORITY = (
    "openaigptoss20b",
    "qwen3coder30ba3binstruct",
    "codestral22b",
    "qwenqwen3635ba3b",
    "deepseekcoderv2liteinstruct",
)
NON_CHAT_MARKERS = ("embed", "embedding", "rerank")
FAKE_API_MARKERS = (
    "setmaxdailyloss",
    "enableautolive",
    "strategyanalyzer.run",
    "account.setstoploss",
    "setdailylosslimit",
)

LONG_PROMPTS: Tuple[PromptSpec, ...] = (
    PromptSpec("10_idea_generation", "Idea Generation", "10_idea_generation.md", tuple(), "idea_generation", 0.3, 1800),
    PromptSpec("11_strategy_specification", "Strategy Specification", "11_strategy_specification.md", ("idea_seed.md",), "strategy_specification", 0.2, 1600),
    PromptSpec("12_overfit_detection", "Large Overfit Detection", "12_overfit_detection.md", ("large_overfit_cases.json",), "large_overfit_detection", 0.2, 1300),
    PromptSpec("13_final_strategy_committee", "Final Strategy Committee", "13_final_strategy_committee.md", ("strategy_committee_outputs.json",), "strategy_committee", 0.2, 1400),
)

CODE_PROMPTS: Tuple[PromptSpec, ...] = (
    PromptSpec("01_code_generation", "Code Generation", "01_code_generation.md", tuple(), "code_generation", 0.1, 2200),
    PromptSpec("02_code_review", "Code Review", "02_code_review.md", ("bad_strategy_example.cs",), "code_review", 0.1, 1400),
    PromptSpec("05_compile_error_fix", "Compile Error Fix", "05_compile_error_fix.md", ("bad_strategy_example.cs", "compile_errors.txt"), "compile_fix", 0.1, 1800),
    PromptSpec("11_strategy_specification", "Strategy Specification", "11_strategy_specification.md", ("idea_seed.md",), "strategy_specification", 0.2, 1600),
)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dirs() -> None:
    for path in [RAW_LARGE_DIR, SCORED_LARGE_DIR, REPORTS_DIR, COMPILE_SANDBOX_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def safe_name(name: str) -> str:
    return base.safe_name(name)


def normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in NON_CHAT_MARKERS)


def model_priority(model_id: Optional[str]) -> Tuple[int, str]:
    if not model_id:
        return (10_000, "")
    normalized = normalize_name(model_id)
    for index, alias in enumerate(MODEL_PRIORITY):
        if alias in normalized or normalized in alias:
            return (index, model_id)
    return (1000, model_id)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fence_for(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "json"
    if path.suffix.lower() == ".cs":
        return "csharp"
    if path.suffix.lower() == ".md":
        return "markdown"
    return "text"


def append_attachments(prompt_text: str, attachments: Tuple[str, ...]) -> str:
    chunks = [prompt_text.strip()]
    for attachment in attachments:
        p = INPUTS_DIR / attachment
        chunks.append(f"Attached file: {attachment}\n\n```{fence_for(p)}\n{read_text(p).rstrip()}\n```")
    return "\n\n".join(chunks).strip() + "\n"


def http_get_json(url: str, timeout: int) -> Dict[str, Any]:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def http_post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def list_models(base_url: str) -> Tuple[List[str], Optional[str]]:
    try:
        payload = http_get_json(f"{base_url}/models", 30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    return [item.get("id") for item in payload.get("data", []) if item.get("id")], None


def match_model(target: Dict[str, Any], detected_models: Sequence[str]) -> Optional[str]:
    scored: List[Tuple[int, int, str]] = []
    for detected in detected_models:
        nd = normalize_name(detected)
        for alias in target["aliases"]:
            na = normalize_name(alias)
            if nd == na:
                scored.append((0, len(detected), detected))
            elif nd in na or na in nd:
                scored.append((1, abs(len(nd) - len(na)), detected))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return scored[0][2]


def build_model_entries(detected_models: Sequence[str], models_error: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    matched: set[str] = set()
    for target in MANDATORY_TARGETS:
        actual = match_model(target, detected_models)
        if actual:
            matched.add(actual)
        entries.append(
            {
                "requested_model": target["label"],
                "actual_model": actual,
                "source": "mandatory",
                "status": "pending" if actual else "not_available",
                "error": None if actual else (models_error or "Model not found via /v1/models"),
            }
        )
    for detected in detected_models:
        if detected in matched:
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
    entries.sort(key=lambda item: model_priority(item.get("actual_model")))
    skipped = [
        {
            "requested_model": detected,
            "actual_model": detected,
            "source": "detected_non_chat",
            "status": "skipped_non_chat",
            "error": "Non-chat model skipped for chat benchmark.",
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
    return re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()


def contains_any(text: str, items: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(item.lower() in lowered for item in items)


def contains_all(text: str, items: Iterable[str]) -> bool:
    lowered = text.lower()
    return all(item.lower() in lowered for item in items)


def count_list_items(text: str) -> int:
    return len(re.findall(r"(?m)^\s*(?:\d+\.|[-*])\s+", strip_thinking(text)))


def make_score(checks: List[Tuple[str, bool]], notes: Optional[List[str]] = None) -> Dict[str, Any]:
    ok = sum(1 for _, passed in checks if passed)
    score = 5.0 * ok / len(checks) if checks else 0.0
    missing = [label for label, passed in checks if not passed]
    merged = list(notes or [])
    if missing:
        merged.append("Missing or weak: " + "; ".join(missing[:5]))
    return {
        "score": round(score, 2),
        "checks": [{"label": label, "ok": passed} for label, passed in checks],
        "notes": merged,
    }


def evaluate_idea_generation(text: str) -> Dict[str, Any]:
    visible = strip_thinking(text)
    lowered = visible.lower()
    checks = [
        ("generates 5 ideas", len(re.findall(r"(?im)^\s*(?:#{1,4}\s*)?(?:idea\s*)?\d+[\).:-]", visible)) >= 5 or visible.lower().count("name") >= 5),
        ("uses simple 1-3 indicators", contains_any(lowered, ["1-3", "1 to 3", "no more than 3", "ema", "atr", "vwap"])),
        ("clear entry rules", "entry" in lowered),
        ("clear exit rules", "exit" in lowered),
        ("stop loss", "stop" in lowered),
        ("take profit or time stop", contains_any(lowered, ["take profit", "profit target", "time stop"])),
        ("max trades per day", contains_any(lowered, ["max trades", "maximum trades"])),
        ("force flat time", contains_any(lowered, ["force flat", "force-flat"])),
        ("no overnight", "overnight" in lowered and contains_any(lowered, ["no overnight", "avoid overnight", "intraday only"])),
        ("hypothesis", "hypothesis" in lowered),
        ("why work and fail", contains_any(lowered, ["why it might work", "might work"]) and contains_any(lowered, ["why it might fail", "might fail"])),
        ("avoids overfit", contains_any(lowered, ["overfit", "curve-fit", "avoid parameter"])),
        ("no live/paper auto-start", not contains_any(lowered, ["go live", "live trading", "paper/demo auto-start", "auto-start paper"])),
    ]
    return make_score(checks, [f"Detected list items: {count_list_items(visible)}"])


def evaluate_strategy_specification(text: str) -> Dict[str, Any]:
    visible = strip_thinking(text)
    lowered = visible.lower()
    checks = [
        ("instrument universe", "instrument universe" in lowered),
        ("timeframe", "timeframe" in lowered),
        ("PT session window", contains_any(lowered, ["pt", "pacific"])),
        ("indicators", "indicator" in lowered),
        ("entry rules", "entry" in lowered),
        ("exit rules", "exit" in lowered),
        ("risk rules", contains_any(lowered, ["risk rules", "risk"])),
        ("parameters", "parameter" in lowered),
        ("acceptance gates", contains_any(lowered, ["acceptance gate", "acceptance criteria", "accept if"])),
        ("rejection gates", contains_any(lowered, ["rejection gate", "rejection criteria", "reject if"])),
        ("what to test first", contains_any(lowered, ["test first", "first test"])),
        ("stop loss", "stop" in lowered),
        ("take profit or time stop", contains_any(lowered, ["take profit", "profit target", "time stop"])),
        ("max trades/day", contains_any(lowered, ["max trades", "maximum trades"])),
        ("High fill/slippage/commission", contains_any(lowered, ["high fill", "conservative fill"]) and contains_any(lowered, ["slippage >= 1", "slippage 1"]) and contains_any(lowered, ["1.90", "roundturncommission"])),
        ("no live/paper/deploy", not contains_any(lowered, ["go live", "live trading", "auto-start paper", "production deployment"])),
    ]
    return make_score(checks)


def evaluate_large_overfit_detection(text: str) -> Dict[str, Any]:
    visible = strip_thinking(text)
    lowered = visible.lower()
    checks = [
        ("selects D as robust candidate", "d" in lowered and contains_any(lowered, ["robust candidate", "candidate", "best"])),
        ("rejects high profit low trades A", "a" in lowered and contains_any(lowered, ["low trade", "18", "reject"])),
        ("rejects OOS-negative B", "b" in lowered and contains_any(lowered, ["oos", "negative", "reject"])),
        ("rejects same-bar C", "c" in lowered and contains_any(lowered, ["same-bar", "same bar", "ambiguity", "reject"])),
        ("rejects one lucky month E", "e" in lowered and contains_any(lowered, ["lucky month", "one month", "reject"])),
        ("uses adjusted/cost reasoning", contains_any(lowered, ["adjusted", "commission", "slippage"])),
        ("prefers IS/OOS balance", contains_any(lowered, ["is/oos", "out-of-sample", "balance", "robust"])),
        ("requires next validation", contains_any(lowered, ["next validation", "walk-forward", "retest", "oos"])),
        ("no live/paper", not contains_any(lowered, ["go live", "live trading", "paper/demo auto-start"])),
    ]
    return make_score(checks)


def evaluate_strategy_committee(text: str) -> Dict[str, Any]:
    visible = strip_thinking(text)
    lowered = visible.lower()
    checks = [
        ("LAB-B selected as candidate", "lab-b" in lowered and "candidate" in lowered),
        ("LAB-A rejected or retest-only", "lab-a" in lowered and contains_any(lowered, ["reject", "mutate", "retest"])),
        ("LAB-C rejected for same-bar", "lab-c" in lowered and contains_any(lowered, ["same-bar", "same bar", "ambiguity", "reject"])),
        ("LAB-D blocks unsafe live promotion", "lab-d" in lowered and contains_any(lowered, ["live", "blocked", "veto", "reject"])),
        ("never promotes to production", not contains_any(lowered, ["promote to production", "production promotion", "go live"])),
        ("mentions safety veto", contains_any(lowered, ["safety veto", "veto", "blocked"])),
        ("requires conservative settings", contains_any(lowered, ["high fill", "slippage", "1.90", "roundturncommission"])),
        ("uses allowed decision vocabulary", contains_any(lowered, ["reject", "mutate", "candidate", "promote"])),
    ]
    return make_score(checks)


EVALUATORS: Dict[str, Callable[[str], Dict[str, Any]]] = {
    "idea_generation": evaluate_idea_generation,
    "strategy_specification": evaluate_strategy_specification,
    "large_overfit_detection": evaluate_large_overfit_detection,
    "strategy_committee": evaluate_strategy_committee,
    "code_generation": base.evaluate_code_generation,
    "code_review": base.evaluate_code_review,
    "compile_fix": base.evaluate_compile_fix,
}


def chat_completion(base_url: str, model_id: str, prompt_text: str, *, temperature: float, max_tokens: int, timeout: int) -> Dict[str, Any]:
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are participating in a strict local benchmark for NT-Analyzer / AI Strategy Lab. "
                    "Only historical backtest research is allowed. No live trading, no paper/demo auto-start, "
                    "no production or locked strategy changes. Be concise, structured, and avoid chain-of-thought. "
                    "Do not invent NinjaTrader APIs."
                ),
            },
            {"role": "user", "content": prompt_text},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    return http_post_json(f"{base_url}/chat/completions", payload, timeout)


def write_raw(stage: str, requested_model: str, prompt: PromptSpec, metadata: Dict[str, Any], body: str, raw_response: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    bucket = RAW_LARGE_DIR / stage / safe_name(requested_model)
    bucket.mkdir(parents=True, exist_ok=True)
    md_path = bucket / f"{prompt.prompt_id}.md"
    json_path = bucket / f"{prompt.prompt_id}.json"
    md_path.write_text("---\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n---\n\n" + body.rstrip() + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {"metadata": metadata, "response_preview": body[:4000], "raw_response": raw_response},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(md_path.relative_to(BASE_DIR)), str(json_path.relative_to(BASE_DIR))


def run_prompt(
    *,
    base_url: str,
    stage: str,
    requested_model: str,
    actual_model: str,
    prompt: PromptSpec,
    timeout: int,
    retry_timeout: Optional[int] = None,
) -> Dict[str, Any]:
    prompt_text = append_attachments(read_text(PROMPTS_DIR / prompt.prompt_file), prompt.attachments)
    attempts: List[Dict[str, Any]] = []
    timeouts = [timeout]
    if retry_timeout:
        timeouts.append(retry_timeout)
    last_error = ""
    for attempt_index, attempt_timeout in enumerate(timeouts, start=1):
        started = now_utc()
        started_clock = time.perf_counter()
        metadata = {
            "stage": stage,
            "requested_model": requested_model,
            "model": actual_model,
            "prompt_id": prompt.prompt_id,
            "prompt_title": prompt.title,
            "evaluator": prompt.evaluator,
            "attempt": attempt_index,
            "temperature": prompt.temperature,
            "max_tokens": prompt.max_tokens,
            "timeout_seconds": attempt_timeout,
            "started_at": started,
        }
        try:
            raw = chat_completion(
                base_url,
                actual_model,
                prompt_text,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                timeout=attempt_timeout,
            )
            output = extract_content(raw)
            duration = round(time.perf_counter() - started_clock, 3)
            metadata.update(
                {
                    "finished_at": now_utc(),
                    "duration_seconds": duration,
                    "output_chars": len(output),
                    "error": None,
                }
            )
            score = EVALUATORS[prompt.evaluator](output)
            md_rel, json_rel = write_raw(stage, requested_model, prompt, metadata, output, raw)
            return {
                "stage": stage,
                "prompt_id": prompt.prompt_id,
                "title": prompt.title,
                "evaluator": prompt.evaluator,
                "status": "ok",
                "attempts": attempts + [{"attempt": attempt_index, "status": "ok", "duration_seconds": duration}],
                "metadata": metadata,
                "score": score,
                "raw_markdown": md_rel,
                "raw_json": json_rel,
            }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout, json.JSONDecodeError, KeyError, TypeError) as exc:
            duration = round(time.perf_counter() - started_clock, 3)
            last_error = f"{type(exc).__name__}: {exc}"
            metadata.update(
                {
                    "finished_at": now_utc(),
                    "duration_seconds": duration,
                    "output_chars": 0,
                    "error": last_error,
                }
            )
            status = "timeout" if "timed out" in last_error.lower() or "timeout" in last_error.lower() else "error"
            attempts.append({"attempt": attempt_index, "status": status, "duration_seconds": duration, "error": last_error})
            write_raw(stage, requested_model, prompt, metadata, last_error, None)
            if status != "timeout":
                break
    return {
        "stage": stage,
        "prompt_id": prompt.prompt_id,
        "title": prompt.title,
        "evaluator": prompt.evaluator,
        "status": "timeout" if "timeout" in last_error.lower() or "timed out" in last_error.lower() else "error",
        "attempts": attempts,
        "metadata": metadata,
        "error": last_error,
        "raw_markdown": str((RAW_LARGE_DIR / stage / safe_name(requested_model) / f"{prompt.prompt_id}.md").relative_to(BASE_DIR)),
        "raw_json": str((RAW_LARGE_DIR / stage / safe_name(requested_model) / f"{prompt.prompt_id}.json").relative_to(BASE_DIR)),
    }


def score_map(results: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    grouped: Dict[str, List[float]] = {}
    for result in results:
        if result.get("status") == "ok":
            grouped.setdefault(result["evaluator"], []).append(result["score"]["score"])
    return {name: round(statistics.mean(values), 2) for name, values in grouped.items()}


def duration_stats(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    durations = [result["metadata"]["duration_seconds"] for result in results if result.get("status") == "ok"]
    chars = [result["metadata"].get("output_chars", 0) for result in results if result.get("status") == "ok"]
    return {
        "median_duration_seconds": round(statistics.median(durations), 3) if durations else None,
        "average_duration_seconds": round(statistics.mean(durations), 3) if durations else None,
        "average_response_chars": round(statistics.mean(chars), 1) if chars else None,
    }


def aggregate_model(model_result: Dict[str, Any]) -> Dict[str, Any]:
    results = model_result.get("prompt_results", [])
    ok = [result for result in results if result.get("status") == "ok"]
    timeouts = sum(1 for result in results if result.get("status") == "timeout")
    scores = score_map(results)
    quality = round(statistics.mean(scores.values()), 2) if scores else 0.0
    stats = duration_stats(results)
    aggregate = {
        "requested_model": model_result["requested_model"],
        "actual_model": model_result.get("actual_model"),
        "source": model_result.get("source"),
        "status": model_result["status"],
        "error": model_result.get("error"),
        "categories": scores,
        "overall_quality_score": quality,
        "attempts": len(results),
        "success_count": len(ok),
        "success_rate": round(len(ok) / len(results), 3) if results else 0.0,
        "timeout_count": timeouts,
        **stats,
    }
    if model_result.get("sandbox_code"):
        aggregate["sandbox_code"] = model_result.get("sandbox_code", [])
        aggregate["sandbox_code_count"] = len(model_result.get("sandbox_code", []))
    return aggregate


def role_quality(aggregate: Dict[str, Any], name: str) -> float:
    return float(aggregate.get("categories", {}).get(name) or 0.0)


def load_previous_summary() -> Dict[str, Any]:
    p = BASE_DIR / "results" / "scored" / "summary.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def previous_aggregate_by_actual(previous: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in previous.get("aggregates", []):
        if item.get("actual_model"):
            out[item["actual_model"]] = item
        out[item.get("requested_model", "")] = item
    return out


def pick_best(aggregates: Sequence[Dict[str, Any]], score_fn: Callable[[Dict[str, Any]], float], minimum: float = 0.0) -> Optional[Dict[str, Any]]:
    candidates = [item for item in aggregates if item.get("status") == "tested" and score_fn(item) >= minimum]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            score_fn(item),
            item.get("overall_quality_score", 0.0),
            item.get("success_rate", 0.0),
            -(item.get("median_duration_seconds") or 9999.0),
        ),
    )


def select_code_models(long_aggregates: Sequence[Dict[str, Any]]) -> List[str]:
    selected: List[str] = []
    required_current_leaders = ["openai/gpt-oss-20b", "Qwen3-Coder-30B-A3B-Instruct"]
    for model in required_current_leaders:
        if model not in selected:
            selected.append(model)
    for item in long_aggregates:
        if item.get("status") != "tested":
            continue
        actual_or_requested = item.get("actual_model") or item["requested_model"]
        passed = item.get("success_count", 0) >= 3 and item.get("success_rate", 0.0) >= 0.75
        if passed and actual_or_requested not in selected and item["requested_model"] not in selected:
            selected.append(item["requested_model"])
    return selected


def first_code_block(text: str) -> str:
    return base.first_code_block(text)


def static_validate_code(code: str, expected_class_name: str = "") -> Dict[str, Any]:
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from app.ai_lab.validator import validate_source

        return validate_source(code, expected_class_name=expected_class_name).to_dict()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "violations": [f"validator failed: {exc}"], "warnings": [], "class_name": expected_class_name}


def save_sandbox_code(requested_model: str, prompt_id: str, text: str) -> Optional[Dict[str, Any]]:
    code = first_code_block(text)
    if not code or "class " not in code:
        return None
    filename = f"AI_SANDBOX_{safe_name(requested_model)}_{safe_name(prompt_id)}.cs"
    path = COMPILE_SANDBOX_DIR / filename
    path.write_text(code.rstrip() + "\n", encoding="utf-8")
    validation = static_validate_code(code)
    return {"path": str(path), "chars": len(code), "validation": validation}


def run_long_text_benchmark(
    base_url: str,
    model_entries: Sequence[Dict[str, Any]],
    long_timeout: int,
    retry_timeout: int,
    max_failed_prompts: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    results: List[Dict[str, Any]] = []
    aggregates: List[Dict[str, Any]] = []
    for entry in model_entries:
        requested = entry["requested_model"]
        actual = entry.get("actual_model")
        if not actual:
            print(f"[long] {requested}: NOT AVAILABLE", flush=True)
            model_result = {**entry, "status": "not_available", "prompt_results": []}
            results.append(model_result)
            aggregates.append(aggregate_model(model_result))
            continue
        print(f"[long] testing {requested} -> {actual}", flush=True)
        model_result = {**entry, "status": "tested", "prompt_results": []}
        failed_prompts = 0
        for prompt in LONG_PROMPTS:
            result = run_prompt(
                base_url=base_url,
                stage="long_text",
                requested_model=requested,
                actual_model=actual,
                prompt=prompt,
                timeout=long_timeout,
                retry_timeout=retry_timeout,
            )
            model_result["prompt_results"].append(result)
            if result["status"] == "ok":
                failed_prompts = 0
                print(f"  - {prompt.prompt_id}: score={result['score']['score']:.2f} duration={result['metadata']['duration_seconds']:.2f}s attempts={len(result['attempts'])}", flush=True)
            else:
                failed_prompts += 1
                print(f"  - {prompt.prompt_id}: {result['status']} {result.get('error')} attempts={len(result.get('attempts', []))}", flush=True)
                if failed_prompts >= max_failed_prompts:
                    print(f"  - stopping {requested}: {failed_prompts} consecutive failed long prompts", flush=True)
                    break
        results.append(model_result)
        aggregates.append(aggregate_model(model_result))
    return results, aggregates


def run_code_benchmark(
    base_url: str,
    model_entries: Sequence[Dict[str, Any]],
    code_model_labels: Sequence[str],
    timeout: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    by_label: Dict[str, Dict[str, Any]] = {}
    for entry in model_entries:
        by_label[entry["requested_model"]] = entry
        if entry.get("actual_model"):
            by_label[entry["actual_model"]] = entry
    results: List[Dict[str, Any]] = []
    aggregates: List[Dict[str, Any]] = []
    for label in code_model_labels:
        entry = by_label.get(label)
        if not entry or not entry.get("actual_model"):
            continue
        requested = entry["requested_model"]
        actual = entry["actual_model"]
        print(f"[code] testing {requested} -> {actual}", flush=True)
        model_result = {**entry, "status": "tested", "prompt_results": [], "sandbox_code": []}
        for prompt in CODE_PROMPTS:
            result = run_prompt(
                base_url=base_url,
                stage="realistic_code",
                requested_model=requested,
                actual_model=actual,
                prompt=prompt,
                timeout=timeout,
                retry_timeout=None,
            )
            if result["status"] == "ok":
                raw_md = BASE_DIR / result["raw_markdown"]
                body = raw_md.read_text(encoding="utf-8").split("---\n\n", 1)[-1]
                saved = save_sandbox_code(requested, prompt.prompt_id, body)
                if saved:
                    result["sandbox_code"] = saved
                    model_result["sandbox_code"].append(saved)
                print(f"  - {prompt.prompt_id}: score={result['score']['score']:.2f} duration={result['metadata']['duration_seconds']:.2f}s", flush=True)
            else:
                print(f"  - {prompt.prompt_id}: {result['status']} {result.get('error')}", flush=True)
            model_result["prompt_results"].append(result)
        results.append(model_result)
        aggregates.append(aggregate_model(model_result))
    return results, aggregates


def category_score(item: Dict[str, Any], name: str) -> float:
    return float(item.get("categories", {}).get(name) or 0.0)


def find_aggregate(aggregates: Sequence[Dict[str, Any]], model: Optional[str]) -> Optional[Dict[str, Any]]:
    if not model:
        return None
    for item in aggregates:
        if item.get("actual_model") == model or item.get("requested_model") == model:
            return item
    return None


def build_assignments(
    long_aggregates: Sequence[Dict[str, Any]],
    code_aggregates: Sequence[Dict[str, Any]],
    previous_summary: Dict[str, Any],
) -> Dict[str, Optional[str]]:
    previous_assignments = previous_summary.get("assignments", {})
    previous_by_actual = previous_aggregate_by_actual(previous_summary)

    idea = pick_best(long_aggregates, lambda item: category_score(item, "idea_generation"), 2.5)
    spec = pick_best(long_aggregates, lambda item: category_score(item, "strategy_specification"), 2.5)
    overfit = pick_best(long_aggregates, lambda item: category_score(item, "large_overfit_detection"), 2.5)
    committee = pick_best(long_aggregates, lambda item: category_score(item, "strategy_committee"), 2.5)
    researcher = pick_best(
        long_aggregates,
        lambda item: (
            category_score(item, "idea_generation")
            + category_score(item, "strategy_specification")
            + category_score(item, "large_overfit_detection")
            + category_score(item, "strategy_committee")
        )
        / 4.0,
        2.5,
    )

    code_writer = pick_best(code_aggregates, lambda item: category_score(item, "code_generation"), 2.5)
    code_reviewer = pick_best(code_aggregates, lambda item: category_score(item, "code_review"), 2.5)
    fixer = pick_best(code_aggregates, lambda item: category_score(item, "compile_fix"), 2.5)

    def prev_pick(role: str) -> Optional[str]:
        return previous_assignments.get(role)

    def actual(item: Optional[Dict[str, Any]]) -> Optional[str]:
        return item.get("actual_model") if item else None

    backtest_model = prev_pick("backtest_analyst")
    mutation_model = prev_pick("mutation_planner")
    safety_model = prev_pick("safety_judge")
    final_model = actual(committee) or prev_pick("final_judge")

    # Prefer a previous proven analyst if it remains visible and current long score did not test backtest prompts.
    if backtest_model and backtest_model not in previous_by_actual:
        backtest_model = actual(researcher)
    if mutation_model and mutation_model not in previous_by_actual:
        mutation_model = actual(researcher)
    if safety_model and safety_model not in previous_by_actual:
        safety_model = actual(committee)

    fast = pick_best(
        long_aggregates,
        lambda item: ((item.get("overall_quality_score") or 0.0) * 0.65)
        + (5.0 / max(1.0, (item.get("median_duration_seconds") or 9999.0) / 20.0) * 0.35),
        1.0,
    )
    if prev_pick("fast_assistant"):
        # Keep previous fast leader if still visible and no new model clearly beats it.
        prev_fast = find_aggregate(long_aggregates, prev_pick("fast_assistant"))
        if prev_fast and fast:
            if (prev_fast.get("overall_quality_score") or 0.0) >= (fast.get("overall_quality_score") or 0.0) - 0.5:
                fast = prev_fast

    return {
        "idea_generator": actual(idea),
        "strategy_researcher": actual(researcher),
        "strategy_spec_writer": actual(spec),
        "code_writer": actual(code_writer) or prev_pick("code_writer"),
        "code_reviewer": actual(code_reviewer) or prev_pick("code_reviewer"),
        "compile_error_fixer": actual(fixer) or prev_pick("compile_error_fixer"),
        "backtest_analyst": backtest_model,
        "mutation_planner": mutation_model,
        "overfit_detector": actual(overfit),
        "safety_judge": safety_model,
        "final_judge": final_model,
        "fast_assistant": actual(fast),
        "embedding_model": "text-embedding-nomic-embed-text-v1.5",
    }


def build_dispositions(
    all_aggregates: Sequence[Dict[str, Any]],
    skipped_models: Sequence[Dict[str, Any]],
    assignments: Dict[str, Optional[str]],
) -> Dict[str, Dict[str, str]]:
    assigned = {v for v in assignments.values() if v}
    dispositions: Dict[str, Dict[str, str]] = {}
    for item in all_aggregates:
        requested = item["requested_model"]
        actual = item.get("actual_model")
        if item.get("status") == "not_available":
            dispositions[requested] = {"disposition": "retest_required", "reason": "Model was not visible via /v1/models."}
        elif actual in assigned or requested in assigned:
            dispositions[requested] = {"disposition": "keep", "reason": "Assigned to at least one final AI Strategy Lab role."}
        elif item.get("timeout_count", 0) > 0 and item.get("success_count", 0) == 0:
            dispositions[requested] = {
                "disposition": "retest_required_long_timeout",
                "reason": "Long-timeout benchmark still produced timeout-only evidence; do not delete automatically.",
            }
        elif item.get("overall_quality_score", 0.0) >= 3.0:
            dispositions[requested] = {"disposition": "optional_manual_use", "reason": "Useful secondary/manual consultant, but not best for a final role."}
        elif item.get("success_count", 0) == 0:
            dispositions[requested] = {"disposition": "retest_required_long_timeout", "reason": "No successful chat evidence after long-timeout attempts."}
        else:
            dispositions[requested] = {"disposition": "delete_candidate", "reason": "Long-timeout benchmark completed but model was not useful for any role."}

    for skipped in skipped_models:
        dispositions[skipped["requested_model"]] = {
            "disposition": "keep",
            "reason": "Non-chat model skipped; keep if used for embeddings/RAG/project search.",
        }
    return dispositions


def md_table(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |"
    divider = "| " + " | ".join(["---"] * len(rows[0])) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join([header, divider] + body)


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def disposition_lines(dispositions: Dict[str, Dict[str, str]], name: str) -> str:
    lines = [f"- `{model}` - {info['reason']}" for model, info in dispositions.items() if info["disposition"] == name]
    return "\n".join(lines) if lines else "- none"


def aggregate_rows(aggregates: Sequence[Dict[str, Any]], dispositions: Dict[str, Dict[str, str]]) -> List[List[str]]:
    rows = [["Model", "Status", "Idea", "Spec", "Overfit", "Committee", "Overall", "Median sec", "Timeouts", "Disposition"]]
    for item in aggregates:
        rows.append(
            [
                item["requested_model"],
                item.get("status", "unknown"),
                fmt(category_score(item, "idea_generation")),
                fmt(category_score(item, "strategy_specification")),
                fmt(category_score(item, "large_overfit_detection")),
                fmt(category_score(item, "strategy_committee")),
                fmt(item.get("overall_quality_score")),
                fmt(item.get("median_duration_seconds")),
                fmt(item.get("timeout_count")),
                dispositions.get(item["requested_model"], {}).get("disposition", "n/a"),
            ]
        )
    return rows


def code_rows(aggregates: Sequence[Dict[str, Any]], dispositions: Dict[str, Dict[str, str]]) -> List[List[str]]:
    rows = [["Model", "Code Gen", "Review", "Fix", "Spec", "Overall", "Median sec", "Static sandbox files", "Disposition"]]
    for item in aggregates:
        rows.append(
            [
                item["requested_model"],
                fmt(category_score(item, "code_generation")),
                fmt(category_score(item, "code_review")),
                fmt(category_score(item, "compile_fix")),
                fmt(category_score(item, "strategy_specification")),
                fmt(item.get("overall_quality_score")),
                fmt(item.get("median_duration_seconds")),
                str(item.get("sandbox_code_count") or sum(1 for r in item.get("sandbox_code", []) if r)),
                dispositions.get(item["requested_model"], {}).get("disposition", "n/a"),
            ]
        )
    return rows


def write_reports(
    *,
    started_at: str,
    finished_at: str,
    base_url: str,
    detected_models: Sequence[str],
    long_results: Sequence[Dict[str, Any]],
    long_aggregates: Sequence[Dict[str, Any]],
    code_results: Sequence[Dict[str, Any]],
    code_aggregates: Sequence[Dict[str, Any]],
    skipped_models: Sequence[Dict[str, Any]],
    assignments: Dict[str, Optional[str]],
    dispositions: Dict[str, Dict[str, str]],
    code_model_labels: Sequence[str],
) -> None:
    detected = "\n".join(f"- `{m}`" for m in detected_models) if detected_models else "- none"
    assignment_rows = [["Role", "Selected model"]] + [[role, f"`{model}`" if model else "NO SAFE PICK"] for role, model in assignments.items()]
    long_report = "# LONG_TIMEOUT_MODEL_BENCHMARK_REPORT\n\n"
    long_report += f"Benchmark window: `{started_at}` -> `{finished_at}`\n\n"
    long_report += f"Base URL: `{base_url}`\n\n"
    long_report += "Scope: text-only long-timeout benchmark. No compile, no backtest, no live/paper/demo, no production changes.\n\n"
    long_report += "## Detected models\n\n" + detected + "\n\n"
    long_report += "## Long-timeout score table\n\n" + md_table(aggregate_rows(long_aggregates, dispositions)) + "\n\n"
    long_report += "## Raw output locations\n\n"
    raw_lines: List[str] = []
    for model in long_results:
        for result in model.get("prompt_results", []):
            raw_lines.append(f"- `{model['requested_model']}` / `{result['prompt_id']}` -> [`{result.get('raw_markdown')}`](../{result.get('raw_markdown')})")
    long_report += ("\n".join(raw_lines) if raw_lines else "- none") + "\n"
    LONG_REPORT.write_text(long_report, encoding="utf-8")

    compile_report = "# COMPILE_BENCHMARK_REPORT\n\n"
    compile_report += "Status: `compile_not_executed`\n\n"
    compile_report += "Reason: no explicit manual confirmation was given to trigger NinjaTrader/NinjaScript Editor compile, and the available compile pipeline can send F5 / refresh catalog against the real local NinjaTrader environment. This benchmark therefore saved sandbox code and ran static validation only.\n\n"
    compile_report += f"Sandbox folder: `{COMPILE_SANDBOX_DIR}`\n\n"
    compile_report += "## Code benchmark models\n\n" + ("\n".join(f"- `{m}`" for m in code_model_labels) if code_model_labels else "- none") + "\n\n"
    compile_report += "## Static code score table\n\n" + md_table(code_rows(code_aggregates, dispositions)) + "\n\n"
    compile_report += "## Static validation details\n\n"
    validation_lines: List[str] = []
    for model in code_results:
        for saved in model.get("sandbox_code", []):
            validation = saved.get("validation", {})
            validation_lines.append(
                f"- `{model['requested_model']}` -> `{saved['path']}`: ok=`{validation.get('ok')}`, "
                f"violations=`{'; '.join(validation.get('violations', [])) or 'none'}`, "
                f"warnings=`{'; '.join(validation.get('warnings', [])) or 'none'}`"
            )
    compile_report += ("\n".join(validation_lines) if validation_lines else "- none") + "\n\n"
    compile_report += "## Manual compile checklist\n\n"
    compile_report += "\n".join(
        [
            "1. Confirm which sandbox `.cs` files should be copied to the canonical NinjaTrader AI sandbox path.",
            "2. Verify class names start with `NTAAiSandbox` and remain inside AI_SANDBOX / AI-CELL.",
            "3. Confirm no locked, accepted, paper-ready, or production strategy file will be changed.",
            "4. Open NinjaScript Editor manually and compile.",
            "5. Save compile errors to `ai_lab/model_benchmark/results/compile_manual/`.",
            "6. Run model autofix only against the sandbox copy if compile errors are present.",
        ]
    )
    compile_report += "\n"
    COMPILE_REPORT.write_text(compile_report, encoding="utf-8")

    backtest_report = "# BACKTEST_BENCHMARK_REPORT\n\n"
    backtest_report += "Status: `backtest_not_executed`\n\n"
    backtest_report += "Reason: no strategy was confirmed as successfully compiled inside AI_SANDBOX during this benchmark. Historical backtests are allowed only after compile success and safety gates.\n\n"
    backtest_report += "## Required execution settings for a future run\n\n"
    backtest_report += "\n".join(
        [
            "- `order_fill_resolution = High`",
            "- `slippage_ticks >= 1`",
            "- `RoundTurnCommission >= 1.90`",
            "- adjusted metrics after commission",
            "- no Standard fill acceptance",
            "- no slippage 0 acceptance",
            "- historical-only NT-Analyzer pipeline",
        ]
    )
    backtest_report += "\n\n## Future mini test set\n\n- short smoke period\n- Full / IS / OOS\n- MNQ/MES or MNQ/MGC after manual confirmation\n"
    BACKTEST_REPORT.write_text(backtest_report, encoding="utf-8")

    final_report = "# FINAL_LARGE_MODEL_SELECTION_REPORT\n\n"
    final_report += f"Generated at: `{finished_at}`\n\n"
    final_report += "## Final role assignment\n\n" + md_table(assignment_rows) + "\n\n"
    final_report += "## Long-timeout table\n\n" + md_table(aggregate_rows(long_aggregates, dispositions)) + "\n\n"
    final_report += "## Compile-realism table\n\n" + md_table(code_rows(code_aggregates, dispositions)) + "\n\n"
    final_report += "## Models to keep\n\n" + disposition_lines(dispositions, "keep") + "\n\n"
    final_report += "## Models to keep optional/manual use\n\n" + disposition_lines(dispositions, "optional_manual_use") + "\n\n"
    final_report += "## Models requiring retest\n\n" + disposition_lines(dispositions, "retest_required") + "\n\n"
    final_report += "## Models requiring long-timeout retest\n\n" + disposition_lines(dispositions, "retest_required_long_timeout") + "\n\n"
    final_report += "## Models to delete\n\n" + disposition_lines(dispositions, "delete_candidate") + "\n\n"
    final_report += "No cleanup was executed. Deletion requires separate confirmation after showing model IDs/paths and reasons.\n\n"
    final_report += "## Speed / quality / hallucination limitations\n\n"
    slow = [item for item in long_aggregates if item.get("median_duration_seconds") and item["median_duration_seconds"] > 180]
    final_report += "Speed-constrained models:\n" + ("\n".join(f"- `{item['requested_model']}` median `{item['median_duration_seconds']}` sec" for item in slow) if slow else "- none") + "\n\n"
    final_report += "Quality-constrained models:\n"
    weak = [item for item in long_aggregates if item.get("status") == "tested" and item.get("success_count", 0) > 0 and item.get("overall_quality_score", 0.0) < 3.0]
    final_report += ("\n".join(f"- `{item['requested_model']}` overall `{item['overall_quality_score']}`" for item in weak) if weak else "- none") + "\n\n"
    final_report += "Hallucination/fake API risks:\n"
    fake_risks: List[str] = []
    for model in code_results:
        for result in model.get("prompt_results", []):
            if result.get("status") == "ok":
                notes = "; ".join(result.get("score", {}).get("notes", []))
                if "fake" in notes.lower() or "api" in notes.lower():
                    fake_risks.append(f"- `{model['requested_model']}` / `{result['prompt_id']}`: {notes}")
    final_report += ("\n".join(fake_risks) if fake_risks else "- none detected by static heuristics") + "\n\n"
    final_report += "## Fully evaluated gaps\n\n"
    not_full: List[str] = []
    for item in long_aggregates:
        if item.get("status") != "tested" or item.get("success_count", 0) < len(LONG_PROMPTS):
            not_full.append(f"- `{item['requested_model']}` - long-text prompts incomplete or timeout-only.")
    for item in code_aggregates:
        if item.get("success_count", 0) < len(CODE_PROMPTS):
            not_full.append(f"- `{item['requested_model']}` - realistic code prompts incomplete.")
    final_report += "Models not fully evaluated:\n"
    final_report += ("\n".join(not_full) if not_full else "- none at text/static-code level") + "\n\n"
    final_report += "- Real NinjaTrader compile was not executed.\n- Historical backtest was not executed because compile was not executed.\n- VRAM/RAM were not visible through the OpenAI-compatible endpoint.\n- Static scoring is still heuristic and should be validated with manual compile/backtest when explicitly approved.\n"
    FINAL_REPORT.write_text(final_report, encoding="utf-8")


def write_summary(
    *,
    started_at: str,
    finished_at: str,
    base_url: str,
    detected_models: Sequence[str],
    model_entries: Sequence[Dict[str, Any]],
    skipped_models: Sequence[Dict[str, Any]],
    long_results: Sequence[Dict[str, Any]],
    long_aggregates: Sequence[Dict[str, Any]],
    code_results: Sequence[Dict[str, Any]],
    code_aggregates: Sequence[Dict[str, Any]],
    code_model_labels: Sequence[str],
    assignments: Dict[str, Optional[str]],
    dispositions: Dict[str, Dict[str, str]],
) -> None:
    payload = {
        "started_at": started_at,
        "finished_at": finished_at,
        "base_url": base_url,
        "detected_models": list(detected_models),
        "model_entries": list(model_entries),
        "skipped_models": list(skipped_models),
        "long_prompts": [prompt.prompt_id for prompt in LONG_PROMPTS],
        "code_prompts": [prompt.prompt_id for prompt in CODE_PROMPTS],
        "code_model_labels": list(code_model_labels),
        "long_aggregates": list(long_aggregates),
        "code_aggregates": list(code_aggregates),
        "assignments": assignments,
        "dispositions": dispositions,
    }
    LARGE_SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (SCORED_LARGE_DIR / "long_results.json").write_text(json.dumps(long_results, ensure_ascii=False, indent=2), encoding="utf-8")
    (SCORED_LARGE_DIR / "code_results.json").write_text(json.dumps(code_results, ensure_ascii=False, indent=2), encoding="utf-8")
    MODEL_ROLES_PATH.write_text(json.dumps(assignments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    ensure_dirs()
    started_at = now_utc()
    print(f"[large] base_url={args.base_url}", flush=True)
    detected_models, models_error = list_models(args.base_url)
    if models_error:
        print(f"[large] /models error: {models_error}", flush=True)
    else:
        print(f"[large] detected models: {len(detected_models)}", flush=True)
    model_entries, skipped_models = build_model_entries(detected_models, models_error)

    long_results, long_aggregates = run_long_text_benchmark(
        args.base_url,
        model_entries,
        args.long_timeout,
        args.retry_timeout,
        args.max_failed_prompts,
    )

    code_model_labels = select_code_models(long_aggregates)
    print(f"[code] selected models: {', '.join(code_model_labels) if code_model_labels else 'none'}", flush=True)
    code_results, code_aggregates = run_code_benchmark(args.base_url, model_entries, code_model_labels, args.code_timeout)

    previous_summary = load_previous_summary()
    assignments = build_assignments(long_aggregates, code_aggregates, previous_summary)
    all_disposition_aggregates = list(long_aggregates)
    dispositions = build_dispositions(all_disposition_aggregates, skipped_models, assignments)
    finished_at = now_utc()

    write_summary(
        started_at=started_at,
        finished_at=finished_at,
        base_url=args.base_url,
        detected_models=detected_models,
        model_entries=model_entries,
        skipped_models=skipped_models,
        long_results=long_results,
        long_aggregates=long_aggregates,
        code_results=code_results,
        code_aggregates=code_aggregates,
        code_model_labels=code_model_labels,
        assignments=assignments,
        dispositions=dispositions,
    )
    write_reports(
        started_at=started_at,
        finished_at=finished_at,
        base_url=args.base_url,
        detected_models=detected_models,
        long_results=long_results,
        long_aggregates=long_aggregates,
        code_results=code_results,
        code_aggregates=code_aggregates,
        skipped_models=skipped_models,
        assignments=assignments,
        dispositions=dispositions,
        code_model_labels=code_model_labels,
    )
    print(f"[large] report: {LONG_REPORT}", flush=True)
    print(f"[large] compile report: {COMPILE_REPORT}", flush=True)
    print(f"[large] backtest report: {BACKTEST_REPORT}", flush=True)
    print(f"[large] final report: {FINAL_REPORT}", flush=True)
    print(f"[large] model roles: {MODEL_ROLES_PATH}", flush=True)
    return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run final large local LLM benchmark for NT-Analyzer AI Strategy Lab.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible LM Studio base URL")
    parser.add_argument("--long-timeout", type=int, default=300, help="First long text timeout seconds")
    parser.add_argument("--retry-timeout", type=int, default=600, help="Retry timeout seconds after timeout")
    parser.add_argument("--code-timeout", type=int, default=300, help="Realistic code benchmark timeout seconds")
    parser.add_argument("--max-failed-prompts", type=int, default=2, help="Stop a model after this many failed long prompts")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
