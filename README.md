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
- Vitek is the owner-facing control layer: application and Telegram messages
  enter through one StratForge Orchestrator gateway, while the manager and
  specialist agents work independently behind it.

## Repository Layout

```text
NT-Analyzer/
  app/                       Python backend, API, and static UI server
  app/static/                Backtesting, strategies, trading, performance, AI UI
  app/ai_lab/                AI Strategy Lab orchestration code
  app/secure_store.py        Windows DPAPI storage for local integration secrets
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

For unattended local operation, install the event-driven Vitek watchdog once:

```powershell
cd NT-Analyzer
.\00_INSTALL_VITEK_BACKGROUND.cmd
```

The watchdog does not open a browser. See
`NT-Analyzer/docs/VITEK.md` and
`NT-Analyzer/docs/PRODUCTION_READINESS_2026-07-13.md`.

External model connections are configured locally at
`http://127.0.0.1:8765/ui/ai-agents.html`. API keys are encrypted with Windows
DPAPI, never stored in source, and never returned by the HTTP API. See
`NT-Analyzer/docs/AI_LAB_CLOUD_AGENTS.md` for providers, budgets and grant tracking.

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
- `data/integrations/ai_agents.registry.json` and
  `data/integrations/ai_agent_keys.dpapi`;
- local NinjaTrader catalogs generated from a user's machine.

See `NT-Analyzer/docs/repository-hygiene.md` for the full policy.

## License

Proprietary. See `LICENSE`.
