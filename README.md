# NT-Analyzer

NT-Analyzer is a local NinjaTrader 8 strategy analysis platform with a Python
backend, static web UI, NinjaTrader bridge AddOn, portfolio/runtime dashboards,
and an AI Strategy Lab for controlled strategy research.

The product is intentionally local-first:

- NinjaTrader remains the source of truth for compilation, execution, fills,
  trades, metrics, and runtime strategy state.
- NT-Analyzer owns job queues, UI, result storage, comparison, runtime
  telemetry views, and AI-assisted research workflows.
- AI-generated strategy code is sandboxed and gated before any promotion to a
  portfolio or paper workflow.

## Repository Layout

```text
NT-Analyzer/
  app/                       Python backend, API, and static UI server
  app/static/                Backtesting, strategies, trading, performance, AI UI
  app/ai_lab/                AI Strategy Lab orchestration code
  bridge/                    NinjaTrader 8 AddOn (.NET Framework 4.8)
  ninjatrader/strategies/    Project NinjaScript strategy sources
  ai_lab/prompts/            Curated AI system prompts
  ai_lab/schemas/            AI Lab JSON schemas
  ai_lab/reference_strategies/ Reference-only research library
  docs/                      Product contracts and operator docs
  examples/                  Safe example JSON payloads
  tests/                     Custom Python test runner suite
  tools/                     Install and research helper scripts
```

Local runtime data is excluded from Git: jobs, reports, batches, NinjaTrader
runtime telemetry, AI experiment runs, model-call logs, screenshots, caches,
build output, and personal research notes.

## Quick Start

Requirements:

- Windows
- Python 3.11+
- NinjaTrader 8
- .NET SDK with .NET Framework 4.8 targeting support
- Optional: LM Studio on `http://127.0.0.1:1234/v1` for AI Strategy Lab

```powershell
cd NT-Analyzer
python -m pip install -r requirements.txt
python -m tests
dotnet build bridge\NTAnalyzerBridge.csproj -c Debug
```

Run locally:

```powershell
cd NT-Analyzer
.\00_START_NT_ANALYZER.cmd
```

Then open:

```text
http://127.0.0.1:8765/ui/
```

## Product Boundary

Commit:

- backend, UI, bridge, strategy source, tests, schemas, docs, examples;
- safe static catalogs such as `instrument_groups.json` and `margins.json`;
- curated prompts and reference-only AI Strategy Lab documentation.

Do not commit:

- `jobs/`, `data/runtime/`, `data/reports/`, `data/research/`,
  `data/profiles/`, `data/ops/`;
- `ai_lab/registry/`, `ai_lab/experiments/`, model benchmark results,
  prompt logs, screenshots, local model calls;
- local NinjaTrader catalogs generated from a user's machine.

See `NT-Analyzer/docs/repository-hygiene.md` for the full policy.

## License

Proprietary. See `LICENSE`.
