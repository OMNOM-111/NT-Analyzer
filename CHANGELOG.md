# Changelog

## 2026-07-13

- Added Vitek as the owner-facing right hand above the internal manager and
  specialist agents, with concise human dialogue and one-response routing from
  both Aurora and Telegram.
- Replaced periodic full polling with durable event-driven wakeups, explicit
  rest/resume, plans, incidents, tasks, strategy time-window coverage and
  parallel agent activity.
- Restored StratForge Orchestrator UI compatibility, protected chat history from
  transient auth/API failures and added explicit Telegram login recovery.
- Scoped Orchestrator conversations by user and workspace and migrated the
  owner's legacy chats idempotently without exposing them to other users.
- Added Vitek background watchdog startup, safe no-browser operating rules,
  end-to-end decision tests and production-readiness documentation.

## 2026-07-02

- Added StratForge Orchestrator as the owner-facing manager with isolated app/
  Telegram conversations, named finance/strategy/news specialists, secure model
  routing, cost accounting and a governed North Star.
- Reworked autonomous strategy development to finish one strategy before the
  next: evidence-driven mutations, stagnation/time limits, result-only reports
  and commission-aware metrics.
- Made stop commands deterministic and race-safe across the mission and runner;
  queued restarts are cleared and stale workers cannot reactivate stopped work.
- Removed model/action/cycle boilerplate from owner messages and added stable
  incident deduplication for Telegram/system notifications.
- Fixed LM Studio lazy operation by retaining the API server between runs while
  unloading models from VRAM; explicit no-local missions now bypass local probes.
- Expanded Aurora operations, news, performance and strategy views; added
  historical-data integrity checks in the NinjaTrader bridge and full regression
  coverage for the staged AI pipeline.
- Removed private CEO photos and ignored machine-specific Telegram topic maps,
  runtime artifacts and benchmark outputs.

## 2026-06-30

- Added a dedicated AI Agents / API Keys page with provider/model/role CRUD,
  connection testing, enable/disable controls and a configurable pricing table.
- Added Windows DPAPI key storage separated from gitignored agent metadata;
  plaintext keys are excluded from API responses, logs, errors and prompt history.
- Added a universal chat/embedding client for OpenAI-compatible, Microsoft
  Foundry/Azure OpenAI, Gemini and custom endpoints with token/cost accounting.
- Added daily/monthly/single-call budget gates, automatic disable, usage audit,
  provider/model totals and student grant/credit tracking with manual portal
  snapshots plus OpenRouter credit synchronization.
- Simplified model onboarding to provider/account/model/key, moved routing fields
  behind advanced settings, and removed duplicate cloud-agent management from AI Lab.
- Fixed zero-budget semantics (monitor-only), full Azure Responses/legacy embedding
  endpoint handling, Gemini chat-vs-embedding inference and GPT-5 reasoning tests.
- Added account/quota classification and shared-credit grouping for multiple Azure
  deployments plus rotation pool/priority metadata for multiple free-tier keys.

## 2026-06-29

- Added local-first DeepSeek/Gemini fallback management to AI Lab with secure
  local API-key storage, role-to-model routing, provider checks, price catalog,
  usage audit, and hard `$20/month` plus `$0.50/run` budget gates.
- Wired paid fallback only for invalid hypothesis contracts and repeated local
  compile-fix failures; cloud output cannot bypass deterministic validation,
  arbitration, governance, or manual promotion.
- Added AI Lab configuration UI, official price-source links, regression tests,
  and governance/operator documentation.

## 2026-06-26

- Fixed position sizing in three strategy engines so a trade is skipped when
  one contract exceeds the configured per-trade risk budget after costs.
- Added concrete-class entry signals and legacy signal attribution for C007,
  C127, and the geodesic research pilot.
- Corrected AI Strategy Lab risk guidance and added static gates against
  anonymous entry signals and forced minimum-one-contract sizing.
- Added regression coverage for the June 25 C007/C127 attribution incident and
  repository-wide NinjaTrader strategy safety checks.

## 2026-06-25

- Added product-level repository documentation and proprietary license.
- Added CI workflow for Python suite and conditional local bridge build.
- Documented Git hygiene boundaries for runtime, research, and AI Lab data.
- Prepared AI Strategy Lab source, UI, schema, prompt, and reference assets for
  controlled product commits while keeping generated model/runtime artifacts
  local.
