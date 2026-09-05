# 07. AI Agents and Automation

- Context Pack document: 07_AI_AGENTS_AND_AUTOMATION.md
- Last verified UTC: 2026-09-05T12:45:49Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: aa54c2940150e540d8b594dbf1d6254e172adbfd (clean beta.96 runtime; integrated browser/provider checks and exact-code CI PASS; full owner acceptance remains separate)
- Active scope: verified integrated Local, result presentation, same-input Consensus and three-model Court; full program and owner-dependent acceptance remain open
- Scope: Agent hierarchy, AI Lab, queues, workspace boundaries and model-usage rules
- Status: IN DEVELOPMENT

## Current scoped follow-up — aa54c294

Clean Local 8765 runs `aa54c2940150e540d8b594dbf1d6254e172adbfd`, beta.96,
build `dev-0.10.0-beta.96-aa54c2940150`, original owner data, Preview=false,
live orders=false. The code is committed/pushed to draft PR #282; #280/#281
remain unmerged. Operational documentation may be newer than active runtime code.

Final full **3977 passed / 44 skipped**, 954.04 s; final focused **319 PASS**,
presentation focused **610 PASS**, legacy **13/13 suites**, root/static/context/
diff and exact staged/runtime **533-file bundles PASS**.
[Exact-code CI 33965039490](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33965039490)
passed Windows, Ubuntu and static, 3/3. No main-target or release PASS is inferred.

Actual browser acceptance on this SHA: stored application Outcome and original
report links in Inspector/SF Chat; same 64-trade NT report; genuine Desktop PNG
140/800 historical bars; preserved chats (5/13 messages); three Personas and
n=3 arithmetic observations for Tolik/Ivan, NEW for Anna. Consensus proposal
cf1464ab uses two accepted same-input contributions. Fresh Court ae0e5e45
received three real valid isolated votes (DeepSeek/Gemini/Azure) and approve;
old case 86a650ab retains its one vote and invalid Gemini response. No validator
was weakened and a verdict does not execute actions.
SF Social read-only preview e4853566… has net -969.7 and PF 0.7252 explicitly
after commission; no post or permanent confirmation was created.

`LOCAL VISUAL REVIEW AVAILABLE: YES`; the full program stays IN DEVELOPMENT.
Ordinary registration/device/key, real multi-user sharing/revocation, permanent
Social publication and owner design acceptance remain separate. New Router,
Execution V2, autonomous routines and an Agent World PG adapter are not implemented.
All ten flags default OFF; exact admitted Local workspace has eight paths ON,
Router/Execution V2 OFF. Preview has separate synthetic flags, no real side effects.
The earlier 93bb1298/other-SHA test and provider history is preserved in the
[canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) and
[integrated changelog](../changelog/2026-09-05-agent-world-integrated-local.md).

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
| Agent World | `IN DEVELOPMENT` | Exactly Overview/Work/Agents plus contextual drawers; integrated domain/private-model/Court/social delta over existing SF Chat and queues, with isolated Preview; not yet the live runtime or an accepted release |
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

The current live Local `8765` is clean beta.96 at
`aa54c2940150e540d8b594dbf1d6254e172adbfd`, using the original owner data/settings
from a clean runtime worktree. Model/domain implementation below is active;
claimed-delivery/explicit-role/private-container changes are active. Sealed
rejection delivery and active-binding ratings passed in the actual browser;
retired history is preserved. Real SF Chat → model → NT report and actual
Desktop PNG (140/800 historical bars, not LIVE) passed. Native Azure binding
compatibility is active and actually verified. Remaining provider/browser/owner
acceptance, final Git/CI closeout and stages 0–13 remain open.
`fc78677dfa258fb56042866a6764e8c8a45c42e6` is the earlier adapter snapshot. The
shared deployment anchor `8f42158661e8247832c90bea8fc4d9f0071e647b` is unchanged;
Production was not checked or changed by this work.

Persona, Agent Role, Provider Account and Model retain separate identities.
Legacy provider/account keys do not become personas or permissions. Source IDs
and statuses remain explicit; unknown legacy states require review.

Commands choose the explicitly assigned application role, not a Tolik/Ivan name.
Rename preserves assignment; suspended/missing-model assignments block execution.
One exact model/source execution chain counts once in Overview without rewriting
the original task or mixing legacy performer metrics into model ratings. Final
saved SF Chat output is delivered through one claimed existing worker path.

In a controlled synthetic Preview workspace,
four deterministic handlers perform finance reconciliation, OHLC statistics,
event-order checks and SVG chart creation through persisted task/outcome states.
Three distinct fixtures produce n=3 low-confidence shadow scores per task class;
replay does not inflate samples. This does not measure external LLM quality or
change Router selection. Maximum 20 benchmark runs per user/workspace bound this
review surface; existing-key replay remains supported.

Existing workers, commands, budgets and permissions remain authoritative. The
new Local composition enables eight exact-workspace gates after existing
server-owned Development opt-in: read/UI/tasks/evaluation/memory/consensus/Court/
social. Registry defaults remain OFF. Router shadow and Execution V2 stay OFF;
Preview retains its separate four synthetic gates. This extends the earlier
clean read/UI/tasks-only adapter; the old evaluation-OFF statement is historical.

Persona creation/profile updates, activation/suspension and retirement are
versioned and separate from Model/Provider Account identity. Private models use
the existing DPAPI secret store and guarded existing provider client; they do not
inherit owner connections. An explicit owner binding can reuse an existing
owner-managed connection without copying its key or raising its budget caps.
New private paid connections cannot call a provider without an approved existing
budget. No actual calls or connectivity are inferred from registration alone.

Explicit selected-model tasks and comparisons persist Task/Intent/Execution/
Contribution/Outcome/Evaluation records, actual provider receipts, observable
latency/cost and independent bounded result checks. NEW remains until three
distinct input observations; repeated identical inputs do not inflate evidence.
Connection checks and Court vote-schema checks are not general quality samples.
Evaluation is shadow-only and never changes routing or represents profitability.
An ambiguous in-flight model call is not silently retried or falsely completed.

Controlled Memory has private, task, one-day working and verified-lesson classes,
purpose-bound retrieval, provenance, TTL, explicit human promotion and append-only
revocation. A separate explicit workspace publication grants only selected
content/proof to current workspace members; source/publication revoke or expiry
removes that access. No automatic private-chat harvesting or cross-user mutation.
Strategy Projects retain immutable version snapshots and original parameters.

Consensus proposals require independently completed same-input Contributions.
Court then uses one sealed packet, three isolated model contexts, actual
contribution-bound votes, unweighted 2-of-3 quorum and retained dissent. Critical
cases require provider failure-domain diversity. Missing/failed judges, stale
rights, invalid evidence or no quorum cannot approve. Court is not the legacy
committee and its advisory approval grants no execution/trading permission.

Routine/calendar items support explicit suggestions, acceptance and dismissal;
structured verified Outcomes can suggest routines. Acceptance enqueues an
idempotent manual follow-up in the existing queue. Automation is OFF: there is
no new autonomous scheduler, recurring model spender or general Execution Engine.
Cancelling an independently queued job remains a separate existing-queue action.

SF Social publication is explicit: prepare an allowlisted verified result or
Court advisory snapshot, review its exact hash/revision, confirm permanence,
then publish through existing Community storage/idempotency. No automatic GET,
completion or judge publication. Prompts, raw answers, Memory, packet/rationale,
credentials and private source files never appear in the public card. Separate
human actor/requester evidence stays in the immutable private approval.

Explicit verified-result/PNG publication goes to the existing AI conversation
store and appears through SF Chat. Explicit Local backtest commands require a
registered class, instrument, timeframe and UTC period (maximum 31 days); no
silent strategy generator or paid model fallback. Existing NinjaTrader execution
and reports are authoritative. The existing chief monitor appends a verified
terminal result once per source revision. A Desktop command waits for actual
bars/canvas capture and an authenticated saved-image receipt; it never invokes
the headless renderer or Telegram. A selected model may prepare only the exact
explicit application specification; the existing application adapter independently
validates and dispatches it. A verified model plan is still waiting until the real
NinjaTrader result or Desktop PNG is recorded. Completion and cancelled/failed
states reconcile through the existing chief monitor and SF Chat, not another
conversation store. Unselected natural-language delegation retains the legacy
path. These adapters are not a general Router/Execution replacement.

The domain repository is SQLite-only in Development and fails closed elsewhere.
The 41 actual isolated PostgreSQL/RLS checks cover existing migrations `0001`–
`0022`, not Agent World PG storage. No new Production migration or acceptance is
implied by local contract tests or simulated provider responses.
See [ADR-0010](../adr/0010-agent-world-owner-review.md),
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md) and
[Agent World status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

## What external GPT should not over-assume

- Do not assume that a complete personal multi-user AI workforce is already fully
  commercialized just because the architecture is described.
- Do not assume cloud-provider keys are present in any environment.
- Do not assume specialist personas can place live orders.
- Do not equate an implemented dirty Local slice, a green focused suite, final
  Git/CI closeout, real-provider/browser evidence and owner acceptance.

## Canonical evidence

- [../agents/AGENTS.md](../agents/AGENTS.md)
- [../agents/AI_LAB_CLOUD_AGENTS.md](../agents/AI_LAB_CLOUD_AGENTS.md)
- [../architecture/UI_API_MAP.md](../architecture/UI_API_MAP.md)
- [beta.61 worker idle performance closeout](../changelog/2026-08-27-beta61-worker-idle-performance.md)
- `app/ai_lab/chief_agent.py`
- `app/ai_lab/domain_agents.py`
- `app/ai_lab/agent_tts.py`
- `app/vitek.py`
- `app/ai_control_center/domain_service.py`
- `app/ai_control_center/model_service.py`
- `app/ai_control_center/application_chat.py`
- `app/ai_control_center/social_publication.py`
- [Domain/service verification record](../changelog/2026-09-05-agent-world-domain-services.md)
