# 07. AI Agents and Automation

- Context Pack document: 07_AI_AGENTS_AND_AUTOMATION.md
- Last verified UTC: 2026-09-05T01:43:39Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: fc78677dfa258fb56042866a6764e8c8a45c42e6
- Scope: Agent hierarchy, AI Lab, queues, workspace boundaries and model-usage rules
- Status: IN DEVELOPMENT

## Agent hierarchy

```text
Owner
  -> Viktor / Vitek (default interlocutor)
     -> Manager
        -> Deputy
        -> Secretary
        -> Specialists: Marina, Tolik, Nikita, Ivan
```

`StratForge Orchestrator` is the technical routing gateway, not a separate boss
above Vitek.

## Current surfaces

| Surface | Status | Current fact |
| --- | --- | --- |
| Agent World | `IN DEVELOPMENT` | Three-section center; separate synthetic Preview benchmarks and explicit Local-owner real NinjaTrader/Desktop adapters into existing SF Chat; global defaults OFF, real E2E acceptance pending |
| Vitek / default assistant | `DONE` | default owner-facing operator, incidents, tasks, plans and summaries |
| Management tiers | `DONE` | manager / deputy / secretary tiers exist with different execution posture |
| Specialist personas | `DONE` | Marina, Tolik, Nikita and Ivan are stable named personas with scoped domains |
| Agent TTS profiles | `PARTIAL` | per-agent voices and preview/speak endpoints exist; provider availability remains credential-dependent |
| AI Strategy Lab loop | `PARTIAL` | strategy ideation, code generation, compile, backtest and arbitration loop exist |
| Cloud AI fallbacks | `PARTIAL` | optional, budget-gated and credential-dependent; not the default trust anchor |
| Personal NinjaTrader Agent Team | `IN DEVELOPMENT` | desired workspace-isolated personal agent team exists as architecture direction more than completed product surface |
| Shared owner-training coordinator | `PARTIAL` | owner-training workspace and orchestrator are current; broader resource/lease behavior continues to harden |

## Job / lease / queue model

- Local-first job history still exists in repository-visible runtime paths.
- Server-side queueing and leases exist in `app/production_workers.py` and the
  production schema.
- Production worker concurrency is fixed at four interactive-AI, four chart,
  two telemetry and one maintenance slot.
- An empty slot backs off through 500 ms, 1 s and approximately 2 s with
  jitter; real work resets pickup polling to 250 ms. Storage outage retries
  wait at least 1 s.
- One stoppable `WorkerService` coordinator sweeps stale leases every 30 s;
  individual workers do not sweep on every empty claim.
- Shared NinjaTrader contention is intended to be expressed as a lease problem,
  not solved by silent parallel access.

## Workspace isolation rules

- Conversations are scoped by `user_id + workspace_id + conversation_id`.
- A workspace should not inherit another workspace's runtime state.
- Paid/cloud agents do not gain runtime, paper or live-trading authority just
  because a provider key exists.

## Model-usage principles

1. The visible persona is stable even if the underlying LLM provider changes.
2. Fallback to paid/cloud models is explicit, budgeted and auditable.
3. AI output does not bypass product permissions or release gates.
4. Plans and dialogue are not equivalent to execution approval.

## Agent World current contract

Persona, Agent Role, Provider Account and Model retain separate identities.
Legacy provider/account keys do not become personas or permissions. Source IDs
and statuses remain explicit; unknown legacy states require review.

In a controlled synthetic Preview workspace,
four deterministic handlers perform finance reconciliation, OHLC statistics,
event-order checks and SVG chart creation through persisted task/outcome states.
Three distinct fixtures produce n=3 low-confidence shadow scores per task class;
replay does not inflate samples. This does not measure external LLM quality or
change Router selection. Maximum 20 benchmark runs per user/workspace bound this
review surface; existing-key replay remains supported.

Existing workers, commands, budgets and permissions remain authoritative.
No Court, general Execution Engine, automatic memory, routine/calendar scheduler
or social publisher is activated. Four flags may be ON for admitted Preview.
The real Local-owner opt-in activates read/UI/tasks only; evaluation remains OFF
and real agents stay NEW, without invented model-quality or profitability scores.

Explicit verified-result/PNG publication goes to the existing AI conversation
store and appears through SF Chat. Explicit Local backtest commands require a
registered class, instrument, timeframe and UTC period (maximum 31 days); no
silent strategy generator or paid model fallback. Existing NinjaTrader execution
and reports are authoritative. The existing chief monitor appends a verified
terminal result once per source revision. A Desktop command waits for actual
bars/canvas capture and an authenticated saved-image receipt; it never invokes
the headless renderer or Telegram. Other natural-language delegation uses the
legacy path. These adapters are not a general Router/Execution replacement.
See [ADR-0010](../adr/0010-agent-world-owner-review.md),
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md) and
[Agent World status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

## What external GPT should not over-assume

- Do not assume that a complete personal multi-user AI workforce is already fully
  commercialized just because the architecture is described.
- Do not assume cloud-provider keys are present in any environment.
- Do not assume specialist personas can place live orders.

## Canonical evidence

- [../agents/AGENTS.md](../agents/AGENTS.md)
- [../agents/AI_LAB_CLOUD_AGENTS.md](../agents/AI_LAB_CLOUD_AGENTS.md)
- [../architecture/UI_API_MAP.md](../architecture/UI_API_MAP.md)
- [beta.61 worker idle performance closeout](../changelog/2026-08-27-beta61-worker-idle-performance.md)
- `app/ai_lab/chief_agent.py`
- `app/ai_lab/domain_agents.py`
- `app/ai_lab/agent_tts.py`
- `app/vitek.py`
