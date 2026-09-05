# Agent World — integrated owner review continuation

- Release title: Agent World — verified results, explicit handoff and manual review
- Change summary: retain completed SF Chat in-app dialogs; finish the integrated
  owner-review path with separate application-result observations, explicit
  fact handoff between Personas, manual routine/calendar discussions and HTTP
  Memory isolation evidence. No replacement of working execution authorities.
- Canonical status: `IN DEVELOPMENT`; Local review is not whole-program acceptance.
- Branch/PR: `codex/agent-world-owner-preview`, draft
  [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282), above unmerged #281/#280.
- Source baseline: `f80d67f730bcd4734893ee7f83643f580138be9a`; active code before
  this delta `95912cbff8152905966e6bb7bfc2a45d3db15f80`.
- Version: `0.10.0-beta.96` unchanged. No merge, deploy, signing, SQL migration,
  owner-key copying, budget increase or trading order.

## User-visible changes

The accepted three-tab page remains Overview / Work / Agents, with contextual
drawers and existing SF Chat. Genuine report/PNG outcomes stay visible before
later model-check outcomes. Real backtest and chart receipt observations appear
separately in agent profiles: distinct verified inputs, exact provenance, NEW
below three observations, no pooled profitability or general-quality score.
Failed and pending attempts remain in history; they are not verified receipts.

An owner may explicitly transfer an existing verified application's allowlisted
facts to a different active Persona/model. It creates a typed dependent Task in
the same SF Chat, sharing correlation with its parent. Only faithful fact
transfer is independently evaluated (`extract_facts`), not strategy correctness
or visual chart analysis. Before any provider transmission, the source revision,
artifact hashes, original/child messages, target, account/device membership and
existing budget are rechecked. Recursive or implicit delegation is not added.

Accepted routines/calendar events now have an explicit **Open manual review in
SF Chat** action. The existing worker delivers one neutral system message with
source/revision/date and an immutable receipt. Repeated requests do not duplicate
it. Queued does not mean delivered; the page shows the saved conversation only
after delivery. This is immediate human-requested discussion, **not execution at
the event's due time**. Automatic scheduling and model spending remain OFF.

Own-model connection has an inline guide to a separate OpenRouter inference key,
the real password field, and `openrouter/free`. Owner credentials are never
copied. A compatible external agent means a supported HTTPS chat-completions
endpoint, not arbitrary MCP/desktop access. Free-router selection/availability
is provider-controlled; no particular underlying model is invented.

Readonly-session, entitlement and exhausted-budget projections now hide
unavailable actions in lists, details and Overview without hiding prior evidence.
The existing POST authority was already fail-closed; this aligns the UI with it.
All Aurora pages receive the same updated shared-script cache key; the completed
in-app dialog behavior/theme and native-prompt boundary remain unchanged.

## Verification and evidence classification

- Presentation/UI: 206 PASS; current presentation/dialog/Aurora regression:
  135 PASS. Pure rendering tests do not assert live provider behavior.
- Final integrated gateway/model/follow-up/presentation subset: 267 PASS,
  zero skipped, 278.92 s.
- Memory: 26 actual loopback HTTP/SQLite tests with synthetic ordinary sessions;
  190 combined PASS. Covers grants, private artifacts, member/foreign scope,
  source supersession/revoke/TTL, device/session/membership revocation and CSRF.
  This is not a live multi-human browser acceptance claim.
- Frozen full regression: **4235 PASS, 44 skipped, zero failures**, 1129.40 s.
  Skips: 41 PostgreSQL cases without the isolated acceptance DB and three
  Windows-inapplicable shell/POSIX cases. Skipped is not verified; the previous
  real PostgreSQL run is historical evidence only. An interrupted pre-freeze
  run is not PASS.
- Exact staged bundle: **542 files, PASS** for static scan inside bundle,
  required runtime reads, Python compilation and shipped JavaScript syntax.
  Two repository-only current-document links were found by the first bundle
  run and corrected to explicit accepted exclusions, then the bundle passed.
- Repository-root CSP/secrets/Markdown scan, context validator and diff check:
  PASS. No source outside the named Agent World/Chat presentation scope changed.

Scoped evidence: [application evaluations](2026-09-05-agent-world-application-evaluation-projection.md),
[typed handoff](2026-09-05-agent-world-typed-result-handoff.md),
[manual discussion](2026-09-05-agent-world-manual-followup-chat.md),
[Memory HTTP](2026-09-05-agent-world-memory-http-e2e.md),
[gateway contracts](2026-09-05-agent-world-program-gateway-contracts.md).

The real historical NT result remains task `62182839-1c4c-563d-8186-bcef081ec599`:
64 trades, net after commission -969.70, PF after commission 0.7252. The genuine
Desktop PNG remains task `c691534b-0670-5313-af39-491b46564248`, 140 rendered of
800 historical bars, not a fresh live quote. These are prior actual executions
being retained and reverified, not newly executed jobs or fixture statistics.

## Remaining program and approval boundaries

Separate ordinary-user registration/device/key acceptance and an independently
configured external-agent endpoint remain unverified. An expired email challenge
was observed in the ordinary-user registration draft; no completed ordinary
account or successful user-key test is claimed. These block only those scenarios.

SF Social exact snapshot `e4853566df3b4091b276f21503c64956b02a4502087e47a8af6362db6507eaee`
was reviewed again; permanent posting still awaits explicit owner confirmation
of the private visibility and caption. No source files/private Memory are public.

General autonomous delegation/Router shadow cutover, a replacement Execution
Engine/Deviation Control, autonomous due-time routines, and an Agent World
PostgreSQL adapter are not implemented by this slice. Existing safe adapters
remain authorities. Backtesting-page redesign is outside this program slice.
Owner design acceptance, final Git/CI closeout and stage closure are separate.

## Release impact and rollback

The future artifact would include the scoped Python adapters, Aurora JS/cache
references, tests and canonical documents. Runtime data, JSONL history, secrets,
operator scripts, logs/screenshots and backups under `.artifacts/` are excluded.
All ten flags default OFF; eight exact Development-workspace flags stay ON,
Router/Execution V2 stay OFF, and no Canary/Production flag is changed.

The prior clean Local code `95912cbff8152905966e6bb7bfc2a45d3db15f80` is the
code rollback point; preserve later owner writes before any data rollback.
No automatic state rollback is authorized. The verified Local activation helper
retains the original owner data root and refuses active work or an unknown PID.

## Operational closeout

Code verification result: **PASS**. Frozen full regression and exact staged
bundle passed. Exact clean Local activation, new live handoff/manual discussion
and Git/CI identity will be appended after verification; they are not inferred
from fixture checks. Full-program owner acceptance remains **PENDING**.
The repository-only `docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md`
is the single current handoff; this shipped record supplies scoped historical
evidence. Owner/developer current documents are excluded from the runtime bundle.
