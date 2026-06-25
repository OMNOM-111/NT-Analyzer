# Repository Hygiene

This repository is the product source tree, not the full local research
workspace. Keep the Git history reproducible, portable, and free of local
operator data.

## Commit

- `app/` Python backend and static UI source.
- `app/ai_lab/` AI Strategy Lab source code.
- `bridge/` NinjaTrader AddOn source and safe example config.
- `ninjatrader/strategies/` project NinjaScript source.
- `tests/`, `examples/`, `docs/`.
- `ai_lab/prompts/`, `ai_lab/schemas/`, `ai_lab/model_roles.json`.
- `ai_lab/reference_strategies/` only as reference material with license notes.
- `data/catalog/instrument_groups.json` and `data/catalog/margins.json`.

## Do Not Commit

- Backtest queues and results: `jobs/`, `data/batches/`, `data/reports/`.
- Runtime telemetry: `data/runtime/`, `data/commands/`, `data/ops/`.
- Research dumps: `data/research/`.
- Local curated/operator state: `data/profiles/`.
- AI generated runtime: `ai_lab/registry/`, `ai_lab/experiments/`,
  `ai_lab/mirrors/`, `ai_lab/quarantine/`.
- Model benchmark outputs, raw model calls, prompt logs, screenshots, PID/log
  files, caches, and build output.
- Machine-specific catalogs such as `data/catalog/strategies.json`,
  `instruments.json`, and `templates.json`.

## Before Commit

Run:

```powershell
cd NT-Analyzer
python -m tests
dotnet build bridge\NTAnalyzerBridge.csproj -c Debug
```

Then verify:

```powershell
git status --short
git diff --cached --stat
```

Before publishing, run a local-path and credential scan across the staged
payload. Treat any match as a blocker unless it is a documented false positive.
