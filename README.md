# StratForge AI

StratForge AI exists so that any trader — regardless of experience or coding
skills — can turn a trading idea into a fully automatic strategy, validated on
real historical data, and stop sitting at the monitor. *A trader is good;
auto-trading is even better.* A team of AI agents writes the strategy code, tests
it through the NinjaTrader Strategy Analyzer on real history, and improves it
until it meets the target criteria — then hands it back ready for demo testing.

It brings together realtime charts and multi-provider market data, NinjaTrader 8
integration through the StratForge Connector, an AI Agent Team, backtesting, and
strategy lifecycle management in one local-first application: the Aurora web UI
on top of a Python backend. Simulation/Live reflects the connected NinjaTrader
account; paper/demo controls are available, while live commands remain
release-gated pending a separate owner and regulatory decision.

> `NT-Analyzer` is the repository and technical identifier (the project's
> original name). The product it builds and runs is StratForge AI.

Owner/developer handoff: open [product history](timeline.html) for the visual
Local / Canary / Production snapshot and the current delivery batch. Changes
to it follow [timeline maintenance](NT-Analyzer/docs/TIMELINE_MAINTENANCE.md).

The product is intentionally local-first:

- NinjaTrader remains the source of truth for compilation, execution, fills,
  trades, metrics, and runtime strategy state.
- TopstepX is the primary independent, read-only chart source for history and
  realtime when the user explicitly enables it with their own credentials. A
  fresh NinjaTrader Connector runtime and then another authorized credentialed
  provider form the fallback path; delayed/history data is never labeled live.
- NinjaTrader remains the only execution path and the source of truth for fills,
  trades, metrics, and runtime strategy state. Futures roots resolve to the
  current contract automatically; no synthetic candles are created and an
  external chart feed never authorizes an order.
- StratForge AI owns the job queues, the Aurora UI, result storage, comparison,
  runtime telemetry views, market-data failover, and AI-assisted research
  workflows.
- AI-generated strategy code is sandboxed and gated before any promotion to a
  portfolio or paper workflow.
- The application runs in isolated Development, Canary, and Production
  environments, promoted through the Release Center as one immutable artifact.
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
`NT-Analyzer/docs/archive/PRODUCTION_READINESS_2026-07-13.md`.

External model connections are configured locally at
`http://127.0.0.1:8765/ui/ai-agents.html`. API keys are encrypted with Windows
DPAPI, never stored in source, and never returned by the HTTP API. See
`NT-Analyzer/docs/agents/AI_LAB_CLOUD_AGENTS.md` for providers, budgets and grant tracking.

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
