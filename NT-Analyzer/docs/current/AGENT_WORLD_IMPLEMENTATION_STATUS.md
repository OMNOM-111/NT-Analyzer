# Agent World — implementation status

Canonical program status: **IN DEVELOPMENT**. This document describes the
current unified source, not historical previews and not an accepted release.
The target architecture and owner's visual references are unchanged.

## Current release boundary (2026-09-29; supersedes historical checkpoints below)

The owner accepted the unified Local package as one product card (7/7).
Technical beta.101 is the signed immutable Canary artifact: five existing owner
connections and secrets were imported into the Linux server store under RLS;
all four active connections passed real provider tests without key re-entry, and
an ordinary DeepSeek invocation succeeded. The fifth GLM record remains retired.
Full server parity remains **PARTIAL**: new-user BYOK, authenticated
owner UI, non-owner shared invocation, revocation, restart and package smoke
are not yet accepted. Canary owner AI Center exposed a presentation defect:
an empty legacy Lab roster hid imported workspace Models from “Мои модели”.
Technical beta.102 is the narrow Development projection fix and has no server
artifact yet. Production remains beta.99, report scheduler OFF and Local
`StratForge Vitek` ON. See the [beta.101 evidence](../changelog/2026-09-28-beta101-server-secret-migration.md)
and [beta.102 change record](../changelog/2026-09-29-beta102-migrated-model-projection.md);
the older source/PR/test statements below are historical.

## 2026-09-21 isolated memory delta

Branch `codex/unified-memory-service` adds the disabled-by-default unified memory
facade described in [ADR-0013](../adr/0013-unified-agent-world-memory.md). Existing
`Memory` remains the fact contract; entity/source/relationship records, stable
source/version/fragment identities, graph-aware token retrieval, loss-accounted
legacy migration and reversible write gates are additive. Chief chat and
specialist-agent context now use the facade, but all canonical/external-context
flags remain OFF. Protected Local 8765, its data, PostgreSQL environments and
servers were not touched. This delta is `IN DEVELOPMENT`, not a release or owner
runtime acceptance.

## Exact source and protected runtime

- Active branch: `codex/agent-world-unified-acceptance`, draft
  [PR #285](https://github.com/OMNOM-111/NT-Analyzer/pull/285), base
  `codex/agent-world-owner-preview`. No other PR base changed.
- Latest saved and pushed executable checkpoint:
  `e45b64b0121014c5d796553ae8b512d98a5782ae`. Its clean immutable full run is
  **5416 PASS / 119 SKIP / 0 FAIL / 0 ERROR**, 5834.82 s; legacy **13/13 PASS**.
  Fresh disposable PostgreSQL receipts separately show **69 Agent World PASS**,
  **41 legacy PG PASS**, **7 Persona identity PASS**, and actual authenticated
  API → worker → SQL → replay → restart/RLS **PASS**. Exact hashes and the
  119-skip breakdown are in the
  [e45 verification receipt](../changelog/2026-09-09-agent-world-e45-verification.md).
  Its PR check rollup was empty when inspected, **not CI PASS**.
- Subsequent uncommitted delta is **IN DEVELOPMENT**: the browser reproduced
  `execution_v2_approved_scope_changed` for a correctly selected Persona;
  approved-request reconstruction is being corrected to retain that identity,
  without relaxing the tamper guard. Read-only task/header/inspector refresh and
  narrow table wrapping are also being corrected. Read-only refresh now preserves
  late forms/search/selection and loaded pages; SF Chat errors have bounded details
  and closed drawers are inert. See the
  [continuity delta](../changelog/2026-09-10-agent-world-state-continuity.md).
  The e45 full/PG results do
  **not** certify this later code; exact-code regression and browser repeat remain.
- The following earlier checkpoints are retained as historical source evidence,
  not as the current runtime or the new delta's verification:
- Combined intake: `f0bafe8ea46653827bc836afcb2197964390cf08`.
  Intake checkpoint: `1409553a46d0dffa7ef329b28029d93f68b405d7`.
  Preserved core checkpoint: `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`.
- Shared integration checkpoint: `a03ec82b686a9f6f05c056fe5a500ecbdb3babac`
  (65 files, clean, pushed). Root static/context and 584-file bundle PASS.
  Detached full regression: **5124 passed / 12 failed / 112 skipped**, 3187.56 s;
  legacy runner **13/13 PASS**. These results apply to that checkpoint, not WIP.
  Later report-binding/Persona continuity corrections are separate changes.
- Next preserved checkpoint: `376b400dc3c8ab3a008f1e45800d401dd02c4b6f`,
  49 files, pushed, clean; root static/context and 588-file bundle PASS.
  Immutable full: **5262 passed / 1 failed / 112 skipped**, 3816.60 s;
  legacy **13/13 PASS**, 61.96 s. The stale cancel-observability fixture was
  corrected afterwards without weakening Connector binding. Subsequent Persona
  selection / response-only work is described in the
  [next checkpoint record](../changelog/2026-09-08-agent-world-persona-chat-checkpoint.md).
  That later saved checkpoint is e45 above; its full/PG results do not change
  the historical failure count on 376. Integrated browser acceptance remains open.
- Protected owner Local: **http://127.0.0.1:8765/ui/ai-command-center.html**,
  code `2b6d0112bef88c5bfb73970de64ec5518443e56b`,
  build `dev-0.10.0-beta.96-2b6d0112bef8`. Not switched or restarted.
- Version remains `0.10.0-beta.96`. No merge, release, Canary/Production,
  working-database migration, trading, owner-key copying or paid calls.
- Isolated full Aurora QA uses **http://localhost:8804/** with its own
  synthetic owner, cookies, data, queue and exact-workspace test executor.
  It now runs the clean detached `e45b64b0` copy; before its isolated restart,
  41 synthetic data files were cold-backed-up and SHA256-compared. Final new-code
  evidence requires the subsequent Persona/V2 and live-refresh correction. This is not a
  protected owner Local backup or switch.

Source provenance, original worktree hashes and residual ownership:
[intake record](../changelog/2026-09-08-agent-world-integration-takeover.md).
The full earlier status is preserved (only relocated relative links adjusted) as a
[dated historical snapshot](../archive/AGENT_WORLD_STATUS_13573_2026-09-08.md).
Earlier Parts C/D/E of the [review handoff](AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md)
are historical evidence, not competing current implementation statuses.

## Program matrix — distinct acceptance axes

All rows remain `IN DEVELOPMENT` until the integrated gates below close.
“Implemented” does not imply enabled, external-provider verified or visually accepted.

| Capability | Code / API / UI | Current evidence | Remaining gate or limitation |
|---|---|---|---|
| Manual Preview/Auth/Device | Contextual proofs and first-device contract preserved; e-mail expiry recovery added | Scoped auth/Preview tests; explicit Google, QR, first-device permanent and unknown-client session/OTP observed before final shared code | Exact-code positive Telegram/e-mail, reset/exit and full manual route rerun; genuine owner consent remains owner action |
| Agent World Preview dataset | Separate synthetic operator; existing DomainService CRUD; explicit idempotent seed of 6 records; same-page controls | 153 scoped PASS; final 30-case Preview suite PASS, no external calls | Default Preview has no provider/worker/Router/Court/publication or routine execution. Separate shared-model QA profiles now support bounded live Local calls; see [Shared Models](../agents/SHARED_MODELS.md) for current status and acceptance |
| Persona | Existing UUID, name/style/role/avatar/voice retained; aliases, main assistant and separate SF Chat selector; exact revision before enqueue/transmit | e45 full and separate 7 Persona PG PASS. Browser reopened Ариадна QA after restart, retained aliases/main/style/Марина face, explicitly activated revision 2 | Selected-Persona Chat failed the V2 scope check in e45; correction's positive browser repeat pending. Audible device verification remains; speaking clip is not phoneme lip-sync |
| Model / Provider Account / external endpoint | Separate persona/connection/model, own-key wizard, receipt and disconnect; read-only chat_completions_v1 capabilities; bounded one-off assistant text with transport-only check, no semantic score | e45 full/PG; browser created SYNTHETIC · Ариадна QA via wizard and completed the named local test-executor diagnostic with a non-secret placeholder, zero external calls | Not a real DeepSeek or ordinary-user BYOK acceptance. Separate user key and supported endpoint remain owner-dependent; no remote tools/tasks, MCP, A2A or general external-agent protocol |
| Task lifecycle / SF Chat | One display-state projection; source/children/aggregate; review as separate immutable event; delivery recovery not provider replay | e45 full PASS; actual browser found completed Work diagnostic with stale header “1 в работе” and selected-Persona V2 refusal; history retained | Live-refresh/V2 delta and full executing/result/pending review/accepted/error/retry browser route still require verification; do not mark earlier error accepted |
| New non-trading Coordinator | Intent → original numeric-summary task → explicit immutable-plan grant → up to 3 levels of verified fact transfer → aggregate review | API plus actual worker/Chat: 1 PASS; Coordinator 40 PASS, delegation/handoff 61 PASS; graph collision 2 PASS; shared security/Coordinator 165 PASS including ordinary SERVICE delivery after browser expiry | Limited numeric-summary/fact-transfer operations, not a general planner; final full/runtime browser still pending |
| Application-result handoff | Trusted application evidence required; existing historical owner run retained | Scope/CAS/provenance tests; unmarked fixture claims withdrawn | New genuine NinjaTrader result unavailable without permitted engine/data path; never relabel synthetic reports as NinjaTrader |
| Router V2 | Existing shadow selection, explicit source-bound preview/apply, pinned choice before normal queue; same-page inspector | 50 scoped PASS, no skips; 1 routed-to-verified-data PASS; shared UI contract bundle 339 PASS | Exact-code full/runtime and browser; synthetic observations not real ranking/calibration evidence |
| Execution / Deviation | Existing queue, immutable approved identities, limits, grant/device, receipt/deviation checks; routing/test-origin pins | e45 full/PG runtime PASS for their recorded cases; subsequent actual selected-Persona request exposed approved-scope reconstruction mismatch | Corrected Persona identity and tamper guard require new exact-code/browser acceptance; no high-risk trading acceptance |
| Autonomous scheduler | Existing scanner, bounded occurrences, grant/capability/budget/device rechecks; no open chat required | Earlier isolated API/worker synthetic run preserved; UI source-task selection corrected | Exact-code runtime/browser stop/restart/expiry route; creating a routine never authorizes its execution |
| Consensus / Court | Existing immutable packet, separate contributions/votes, decision history, no trade execution by judge | Existing focused tests and prior synthetic evidence retained | Final integration regression/browser; no claim of independently calibrated real model judges |
| Controlled Memory | Private/shared scoped records, explicit promotion/revocation; existing sources and revisions | Two-user synthetic HTTP sharing/revocation in Preview suite | Final two-user visual route; Preview SQLite is not PG/RLS evidence |
| Projects / experiments / Process Intelligence | Versioned project records, comparison jobs, verified-source suggestions and cooldown; API and same-page UI wired | PI core 28 PASS; shared API tests exercise source-CAS/propose/accept | Final UI/E2E; real comparisons only with separately permitted connections/budget |
| SF Social | Existing permanent snapshot prepare → explicit publish, separate store and scope | Existing snapshot/isolation tests | Final isolated route and owner's confirmation of a specific permanent real publication |
| PostgreSQL / RLS | Adapter and migration 0023 integrated; no implicit migration/fallback; Persona uniqueness uses existing transaction | Fresh exact-e45: 69 Agent World PASS, 41 legacy PG PASS, 7 Persona PG PASS; separate actual API/worker/restart/RLS PASS with TLS/NOBYPASSRLS and ten FORCE RLS tables | e45 storage/runtime gate verified, not a deployed storage migration. Subsequent code and full program still require their own acceptance; generic skips remain explicit |
| Full Aurora / visual composition | Three main tabs with inspectors; no replacement shell or broad relayout | e45 browser Persona/wizard observations; at 1136×904 the Work stage column wrapped excessively and header count lagged | Narrow refresh/wrapping correction's exact-code overflow/focus/accessibility/browser pass; owner has NOT accepted design correspondence |
| Git / release | Original worktrees preserved; exact-path staging; e45 checkpoint pushed to task PR | e45 clean immutable full, 329 focused, root/static/context and 593-file pre-release bundle PASS; PR check rollup empty | Later delta needs its own saved SHA and gates; fresh CI and owner acceptance remain. IMPLEMENTATION COMPLETE / STAGE CLOSED are not claimed; merge/deploy NOT authorized |

## Evidence rules and withdrawn claims

- Historical full **4537 passed / 110 skipped** is for `92436698`, not this
  code. Focused suites overlap and must not be added into a fake full total.
- **69 Agent World PostgreSQL**, **41 legacy PostgreSQL**, **7 Persona
  PostgreSQL**, and the separate API/worker/restart/RLS scenario are different
  exact-e45 receipts in the
  [new verification record](../changelog/2026-09-09-agent-world-e45-verification.md).
  Its full run's **119 SKIP** are 68 Agent World PG, 7 Persona PG, 41 legacy PG
  and 3 platform cases; the fresh DB runs supplement, not rewrite, those skips.
  The [earlier unified PG receipt](../changelog/2026-09-08-agent-world-postgres-unified-acceptance.md)
  and [376 receipt](../changelog/2026-09-08-agent-world-postgres-376-acceptance.md)
  remain historical. Neither an adapter PASS nor a generic skip certifies a new runtime.
- The two manually prepared reports falsely labelled NinjaTrader are rejected
  after their test marker correction. Their old successful browser claims are
  withdrawn. The genuine historical owner 64-trade run/PNG remains a separate
  receipt, not a fresh test of this build.
- Named `local_test_executor` responses, test connections, evaluations and
  downstream envelopes stay synthetic. They do not establish a real provider
  connection or professional model quality. Flags OFF deny queued test-origin
  work instead of changing its executor.
- A verified result, delivery to Chat, a human review, a Court decision and
  permission for later execution are separate events.
- A later disposable test confirmed a distinct authenticated Connector-to-job
  binding defect, not an anonymous/model upload. The current correction binds
  stored commands to exact server dispatch and canonical safe paths, preserves
  history on collisions and appends exact source-bound origin corrections.
  Expanded boundary/live/Preview/application regression: 206 PASS, 135.48 s;
  boundary/Connector/live-backtest including cancel: 208 PASS, 27.49 s. See the
  [boundary record](../changelog/2026-09-08-agent-world-trusted-report-boundary.md).
- The a03 full run's 112 skips are **68 Agent World PostgreSQL**, **41 legacy
  PostgreSQL**, and **3 platform-dependent** cases. Its 12 failures are one
  stale application-origin expectation, seven Preview-contract expectations
  and four incomplete Persona read-model test doubles. Corrections preserve
  validation/isolation/history assertions; the later e45 full result above is
  separate evidence, not a relabelling of these failures.
- [Chat review boundary](../changelog/2026-09-08-agent-world-chat-review-boundary.md):
  a timer, legacy message stars or fulfillment marks cannot accept/rate an
  Agent World Task. Prior marks remain historical. Boundary + Chief: 132 PASS.
- [Router Persona preservation](../changelog/2026-09-08-agent-world-router-persona-preservation.md):
  source Persona/Role are pinned independently of the selected executor;
  preview/apply/transmit recheck current revisions. 201 scoped PASS, 21 Persona
  role/history PASS; this is transport-double evidence, not a real model call.

## Ownership, checkpoint and next operation

Root owns integration, current documents, main Aurora page/API wiring and Git.
Bounded trusted-history/security work and Router source-pin work are coordinated
in this one worktree; contributors do not stage/commit or touch Local 8765.
Their change records document exact scopes and tests. Remaining files are only
named code/tests/docs; ignored test databases, launchers, screenshots, logs,
cookies and artifacts are outside Git. Existing user data is never reset.

Next operation: finish focused checks for the reproduced Persona/V2 mismatch
and read-only refresh, preserve that separate checkpoint after mandatory
diff/context/artifact gates, then cold-back up the current synthetic data and
restart **only** isolated 8804 on an immutable copy. Repeat the same Persona Chat
request and executing/result/pending-review/decision/error/safe-retry route,
including counters, profile and preserved error history. Continue the remaining
Preview, Memory, Coordinator/Router/Court, projects, scheduler and Social-prepare
routes alongside exact new-code regression. Completed e45 full/PG receipts need
not be rerun as e45; later executable changes require their own evidence.
Do not stop at one UI fix or treat an absent user key as a program-wide blocker.

Use the [owner route guide](AGENT_WORLD_OWNER_ACCEPTANCE_GUIDE.md) to record
individual observed steps. It is a checklist, not a second implementation status.
The [e45 verification receipt](../changelog/2026-09-09-agent-world-e45-verification.md)
records exact source/cluster/runtime hashes and the separately completed seven
Persona PG cases; browser, audible speech and human acceptance are different axes.

Before any future Local activation, prepare a data backup and an explicit
rollback to the protected 2b6d0112 runtime and request the one exact activation
approval. No Local activation is included in the current mandate.

OWNER ACCEPTANCE READY: NO — integrated exact-code gates and functional
limitations above remain; this is not only a missing owner key.
VISUAL DESIGN ACCEPTED: NO.
LOCAL 8765 UPDATED: NO.
MERGE / DEPLOY: NOT PERFORMED.
