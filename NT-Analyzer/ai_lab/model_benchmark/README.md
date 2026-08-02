# Local Model Benchmark for NT-Analyzer / AI Strategy Lab

This benchmark evaluates local LM Studio models for NT-Analyzer and NinjaTrader 8 strategy-development tasks without compiling, executing, deploying, or modifying trading code.

Safety scope:

- read-only prompts, responses, scoring, and reports;
- no NinjaTrader bridge changes;
- no NinjaScript compile or execution;
- no live trading;
- no paper/demo auto-start;
- no production strategy creation or mutation.

Default API endpoint:

- `http://localhost:1234/v1`

The runner uses:

- `GET /v1/models`
- `POST /v1/chat/completions`

Mandatory target models:

- Runtime inventory is discovered from `/v1/models`; removed models remain only in dated benchmark artifacts.
- `gpt-oss-20b`
- `Qwen3-Coder-30B-A3B-Instruct`
- `Codestral-22B`
- `DeepSeek-Coder-V2-Lite-Instruct`
- `StarCoder2-15B`

Any additional visible chat/reasoning/coding models from `/v1/models` are included automatically. Embedding/rerank models are recorded as `skipped_non_chat` and are not sent to chat completions.

## Benchmark Stages

Stage 1 general benchmark runs every available chat model through:

- `01_code_generation`
- `02_code_review`
- `03_backtest_analysis`
- `04_mutation_plan`
- `05_compile_error_fix`
- `06_safety_check`
- `07_strategy_architecture`
- `08_overfit_detection`
- `09_final_judge`

Stage 2 targeted benchmark repeats the critical prompts for candidate models selected from Stage 1:

- Coding: `01_code_generation`, `02_code_review`, `05_compile_error_fix`
- Analysis: `03_backtest_analysis`, `04_mutation_plan`, `08_overfit_detection`, `09_final_judge`
- Safety: `06_safety_check`

Models are tested sequentially. The runner does not parallelize model calls.

## Usage

From `NT-Analyzer`:

```powershell
& ".\.venv\Scripts\python.exe" "ai_lab\model_benchmark\run_benchmark.py" --timeout 180
```

Optional arguments:

- `--base-url http://localhost:1234/v1`
- `--timeout 180`
- `--skip-stage2`

## Output Layout

- `prompts/` - benchmark prompts
- `test_inputs/` - fixed benchmark inputs
- `results/raw/stage1/<model>/<prompt_id>.md` - raw model answer with metadata frontmatter
- `results/raw/stage2/<model>/<prompt_id>.md` - targeted raw model answer
- `results/raw/**/<prompt_id>.json` - metadata plus raw API payload
- `results/scored/<model>.json` - per-model aggregate scores
- `results/scored/summary.json` - whole benchmark summary
- `reports/MODEL_BENCHMARK_REPORT.md` - full model report
- `reports/CODING_BENCHMARK_REPORT.md` - coding-specific report
- `reports/FINAL_MODEL_SELECTION_REPORT.md` - final role assignment and cleanup plan
- `../model_roles.json` - generated only after all roles receive a selected tested model

If LM Studio is offline or a mandatory model is missing, the benchmark still writes reports and marks the model as `not_available` / `RETEST_REQUIRED`.
