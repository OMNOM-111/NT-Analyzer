"""Small real-prompt benchmark for assigning local LM Studio roles."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, Iterable, List, Optional

from . import lm_studio, paths
from .generator import (
    _build_static_validation_autofix_prompt,
    _extract_csharp,
    repair_common_nt8_source,
)
from .io_utils import write_json_atomic
from .validator import validate_source


JUDGE_PROMPT = """Return ONLY JSON:
{"reference_id":"REF-008","family":"vwap_pullback","market_regime":"...",
"entry_trigger":"...","why_not_generic":"...","hypothesis":"..."}
Design a non-generic MNQ intraday idea for 06:30-12:30 PT, 1-3 trades/day.
Do not use generic breakout, Donchian, Bollinger mean reversion, or EMA crossover."""

CODER_PROMPT = """Return one complete C# file in a csharp fence.
Class NTAAiSandboxBenchmark : Strategy in NinjaTrader.NinjaScript.Strategies.
Use one primary series, OnBarClose, no OnExecutionUpdate/AddDataSeries.
Use SessionStartTimePT=63000, SessionEndTimePT=123000 and ToTime(Time[0]).
Snapshot CumProfit at Bars.IsFirstBarOfSession; MaxDailyLoss uses session delta.
Configure SetStopLoss and SetProfitTarget before entry. MaxTradesPerDay=2.
Entry: one simple liquidity-sweep reversal. Force flat after SessionEndTimePT."""


def _run_task(
    model: str,
    *,
    task: str,
    prompt: str,
    max_tokens: int,
    timeout: int,
) -> Dict[str, Any]:
    started = time.time()
    try:
        response = lm_studio.chat(
            role="coder",
            model_override=model,
            messages=[
                {"role": "system", "content": "Be concise and obey the output contract exactly."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
            timeout=timeout,
            retries=0,
            purpose=f"model_benchmark_{task}",
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "task": task, "ok": False, "elapsed_sec": round(time.time() - started, 3),
            "error": str(exc),
        }
    content = str(response.get("content") or "")
    row: Dict[str, Any] = {
        "task": task,
        "ok": False,
        "elapsed_sec": round(time.time() - started, 3),
        "model": response.get("model") or model,
        "content_preview": content[:500],
        "usage": response.get("usage") or {},
    }
    if task == "judge":
        parsed = lm_studio.extract_json_block(content)
        required = {
            "reference_id", "family", "market_regime", "entry_trigger",
            "why_not_generic", "hypothesis",
        }
        row["parsed"] = parsed
        row["ok"] = isinstance(parsed, dict) and required.issubset(parsed)
        row["quality_score"] = 100 if row["ok"] else 0
    else:
        source = _extract_csharp(content) or ""
        source, repairs = repair_common_nt8_source(source)
        report = validate_source(
            source, expected_class_name="NTAAiSandboxBenchmark"
        )
        attempts: List[Dict[str, Any]] = [{
            "attempt": 1,
            "validation": report.to_dict(),
            "deterministic_repairs": repairs,
        }]
        # Match the production generator: one draft plus two focused static
        # autofix passes. Benchmarking only the raw first draft incorrectly
        # rejects models that are reliable inside the actual pipeline.
        for attempt_no in range(2, 4):
            if report.ok or not source:
                break
            try:
                repair_response = lm_studio.chat(
                    role="coder",
                    model_override=model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Repair the complete NinjaTrader 8 strategy. "
                                "Return only one complete csharp file."
                            ),
                        },
                        {
                            "role": "user",
                            "content": _build_static_validation_autofix_prompt(
                                class_name="NTAAiSandboxBenchmark",
                                violations=report.violations,
                                prior_source=source,
                            ),
                        },
                    ],
                    temperature=0.1,
                    max_tokens=2200,
                    timeout=timeout,
                    retries=0,
                    purpose=f"model_benchmark_{task}_repair_{attempt_no}",
                )
            except Exception as exc:  # noqa: BLE001
                attempts.append({
                    "attempt": attempt_no,
                    "validation": report.to_dict(),
                    "error": str(exc),
                })
                break
            repaired_source = _extract_csharp(
                str(repair_response.get("content") or "")
            )
            if not repaired_source:
                attempts.append({
                    "attempt": attempt_no,
                    "validation": report.to_dict(),
                    "error": "autofix returned no C#",
                })
                continue
            source, repairs = repair_common_nt8_source(repaired_source)
            report = validate_source(
                source, expected_class_name="NTAAiSandboxBenchmark"
            )
            attempts.append({
                "attempt": attempt_no,
                "validation": report.to_dict(),
                "deterministic_repairs": repairs,
            })
        row["elapsed_sec"] = round(time.time() - started, 3)
        row["attempts"] = attempts
        row["validation"] = report.to_dict()
        row["final_source"] = source
        row["ok"] = report.ok
        row["quality_score"] = (
            max(0, 100 - 5 * (len(attempts) - 1))
            if report.ok
            else max(0, 70 - 10 * len(report.violations))
        )
    return row


def benchmark(
    models: Optional[Iterable[str]] = None,
    *,
    judge_timeout: int = 240,
    coder_timeout: int = 360,
) -> Dict[str, Any]:
    candidates = list(dict.fromkeys(models or lm_studio.list_models(timeout=15)))
    candidates = [
        model for model in candidates
        if "embed" not in model.lower() and model.strip()
    ]
    rows: List[Dict[str, Any]] = []
    for model in candidates:
        judge = _run_task(
            model, task="judge", prompt=JUDGE_PROMPT,
            max_tokens=220, timeout=judge_timeout,
        )
        coder = _run_task(
            model, task="coder", prompt=CODER_PROMPT,
            max_tokens=1500, timeout=coder_timeout,
        )
        rows.append({"model": model, "judge": judge, "coder": coder})

    def best(role: str) -> Optional[str]:
        valid = [row for row in rows if row[role].get("ok")]
        valid.sort(key=lambda row: (
            -float(row[role].get("quality_score") or 0),
            float(row[role].get("elapsed_sec") or 1e9),
        ))
        return valid[0]["model"] if valid else None

    elapsed_judge = [
        float(row["judge"].get("elapsed_sec") or 0)
        for row in rows if row["judge"].get("ok")
    ]
    elapsed_coder = [
        float(row["coder"].get("elapsed_sec") or 0)
        for row in rows if row["coder"].get("ok")
    ]
    report = {
        "schema_version": "1.0",
        "base_url": lm_studio.base_url(),
        "models": rows,
        "recommendation": {
            "idea_generator": best("judge"),
            "code_writer": best("coder"),
            "best_effort_code_writer": (
                max(
                    rows,
                    key=lambda row: float(row["coder"].get("quality_score") or 0),
                    default={},
                ).get("model")
            ),
            "code_pipeline_ready": any(row["coder"].get("ok") for row in rows),
            "judge_timeout_sec": max(180, int(max(elapsed_judge or [120]) * 1.6)),
            "coder_timeout_sec": max(300, int(max(elapsed_coder or [180]) * 1.6)),
            "context_length": 8192,
            "parallel": 1,
            "retries": 0,
        },
    }
    paths.ensure_dirs()
    write_json_atomic(paths.MODEL_BENCHMARK_PATH, report)
    return report


def main() -> int:
    report = benchmark()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
