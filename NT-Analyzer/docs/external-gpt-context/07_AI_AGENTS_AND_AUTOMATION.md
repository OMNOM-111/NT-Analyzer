# 07. AI Agents and Automation

- Context Pack document: 07_AI_AGENTS_AND_AUTOMATION.md
- Last verified UTC: 2026-08-13T02:25:57Z
- Verified against Git SHA: cad53f682e413db86bc3a77e57f8942baf4d4bc3
- Scope: Agent hierarchy, AI Lab, queues, workspace boundaries and model-usage rules
- Status: DONE

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

## What external GPT should not over-assume

- Do not assume that a complete personal multi-user AI workforce is already fully
  commercialized just because the architecture is described.
- Do not assume cloud-provider keys are present in any environment.
- Do not assume specialist personas can place live orders.

## Canonical evidence

- [../agents/AGENTS.md](../agents/AGENTS.md)
- [../agents/AI_LAB_CLOUD_AGENTS.md](../agents/AI_LAB_CLOUD_AGENTS.md)
- [../architecture/UI_API_MAP.md](../architecture/UI_API_MAP.md)
- `app/ai_lab/chief_agent.py`
- `app/ai_lab/domain_agents.py`
- `app/ai_lab/agent_tts.py`
- `app/vitek.py`