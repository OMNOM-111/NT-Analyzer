# Agent World — implementation status

Canonical program status: **IN DEVELOPMENT**. This document describes the
current unified source, not historical previews and not an accepted release.
The target architecture and owner's visual references are unchanged.

## Exact source and protected runtime

- Active branch: `codex/agent-world-unified-acceptance`, draft
  [PR #285](https://github.com/OMNOM-111/NT-Analyzer/pull/285), base
  `codex/agent-world-owner-preview`. No other PR base changed.
- Combined intake: `f0bafe8ea46653827bc836afcb2197964390cf08`.
  Intake checkpoint: `1409553a46d0dffa7ef329b28029d93f68b405d7`.
  Preserved core checkpoint: `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`.
- Shared integration checkpoint: `a03ec82b686a9f6f05c056fe5a500ecbdb3babac`
  (65 files, clean, pushed). Root static/context and 584-file bundle PASS.
  Detached full regression: **5124 passed / 12 failed / 112 skipped**, 3187.56 s;
  legacy runner **13/13 PASS**. These results apply to that checkpoint, not WIP.
  Later report-binding/Persona continuity corrections are separate changes;
  final exact-code regression/browser is pending.
- Next preserved checkpoint: `376b400dc3c8ab3a008f1e45800d401dd02c4b6f`,
  49 files, pushed, clean; root static/context and 588-file bundle PASS.
  Immutable full: **5262 passed / 1 failed / 112 skipped**, 3816.60 s;
  legacy **13/13 PASS**, 61.96 s. The stale cancel-observability fixture was
  corrected afterwards without weakening Connector binding. Subsequent Persona
  selection / response-only work is described in the
  [next checkpoint record](../changelog/2026-09-08-agent-world-persona-chat-checkpoint.md).
  Its own immutable full and fresh PG/browser evidence are still pending.
- Protected owner Local: **http://127.0.0.1:8765/ui/ai-command-center.html**,
  code `2b6d0112bef88c5bfb73970de64ec5518443e56b`,
  build `dev-0.10.0-beta.96-2b6d0112bef8`. Not switched or restarted.
- Version remains `0.10.0-beta.96`. No merge, release, Canary/Production,
  working-database migration, trading, owner-key copying or paid calls.
- Isolated full Aurora QA uses **http://localhost:8804/** with its own
  synthetic owner, cookies, data, queue and exact-workspace test executor.
  It now runs the clean detached `376b400d` copy; before its isolated restart,
  41 synthetic data files were cold-backed-up and SHA256-compared. Final new-code
  evidence still requires the subsequent Persona checkpoint. This is not a
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
| Agent World Preview dataset | Separate synthetic operator; existing DomainService CRUD; explicit idempotent seed of 6 records; same-page controls | 153 scoped PASS; final 30-case Preview suite PASS, no external calls | Final browser; Preview deliberately has no provider/worker/Router/Court/publication or routine execution |
| Persona | Existing UUID, name/style/role/avatar/voice retained; aliases, main assistant and separate SF Chat selector; exact revision before enqueue/transmit | Persona identity/chat 53 PASS; selected-response/worker 58 PASS; shipped UI/result/dialog 121 PASS | New immutable full/browser and 7 new real PG cases pending; audible device verification; speaking clip is not phoneme lip-sync |
| Model / Provider Account / external endpoint | Separate persona/connection/model, own-key wizard, receipt and disconnect; read-only chat_completions_v1 capabilities; bounded one-off assistant text with transport-only check, no semantic score | Provenance/worker and 58 response/Persona checks; test-origin pin prevents external fallback after flag OFF | Separate ordinary-user key and real supported endpoint remain owner-dependent; no remote tools/tasks, MCP, A2A or general external-agent protocol |
| Task lifecycle / SF Chat | One display-state projection; source/children/aggregate; review as separate immutable event; delivery recovery not provider replay | Shared API 12 PASS; unified UI/shared/security 234 PASS; Coordinator worker E2E PASS | Final exact-code combined tests and browser executing/result/pending review/accepted/error/retry route |
| New non-trading Coordinator | Intent → original numeric-summary task → explicit immutable-plan grant → up to 3 levels of verified fact transfer → aggregate review | API plus actual worker/Chat: 1 PASS; Coordinator 40 PASS, delegation/handoff 61 PASS; graph collision 2 PASS; shared security/Coordinator 165 PASS including ordinary SERVICE delivery after browser expiry | Limited numeric-summary/fact-transfer operations, not a general planner; final full/runtime browser still pending |
| Application-result handoff | Trusted application evidence required; existing historical owner run retained | Scope/CAS/provenance tests; unmarked fixture claims withdrawn | New genuine NinjaTrader result unavailable without permitted engine/data path; never relabel synthetic reports as NinjaTrader |
| Router V2 | Existing shadow selection, explicit source-bound preview/apply, pinned choice before normal queue; same-page inspector | 50 scoped PASS, no skips; 1 routed-to-verified-data PASS; shared UI contract bundle 339 PASS | Exact-code full/runtime and browser; synthetic observations not real ranking/calibration evidence |
| Execution / Deviation | Existing queue, immutable approved identities, limits, grant/device, receipt/deviation checks; routing/test-origin pins | Focused execution/deviation tests | Final shared negative/regression; no high-risk trading acceptance |
| Autonomous scheduler | Existing scanner, bounded occurrences, grant/capability/budget/device rechecks; no open chat required | Earlier isolated API/worker synthetic run preserved; UI source-task selection corrected | Exact-code runtime/browser stop/restart/expiry route; creating a routine never authorizes its execution |
| Consensus / Court | Existing immutable packet, separate contributions/votes, decision history, no trade execution by judge | Existing focused tests and prior synthetic evidence retained | Final integration regression/browser; no claim of independently calibrated real model judges |
| Controlled Memory | Private/shared scoped records, explicit promotion/revocation; existing sources and revisions | Two-user synthetic HTTP sharing/revocation in Preview suite | Final two-user visual route; Preview SQLite is not PG/RLS evidence |
| Projects / experiments / Process Intelligence | Versioned project records, comparison jobs, verified-source suggestions and cooldown; API and same-page UI wired | PI core 28 PASS; shared API tests exercise source-CAS/propose/accept | Final UI/E2E; real comparisons only with separately permitted connections/budget |
| SF Social | Existing permanent snapshot prepare → explicit publish, separate store and scope | Existing snapshot/isolation tests | Final isolated route and owner's confirmation of a specific permanent real publication |
| PostgreSQL / RLS | Adapter and migration 0023 integrated; no implicit migration/fallback; Persona uniqueness uses existing transaction | Fresh exact-376: 69 Agent World PASS, 41 legacy PG PASS, separately API/worker/restart/RLS PASS with TLS/NOBYPASSRLS | New Persona transaction changes require fresh final-code suites plus 7 additional cases and runtime; neither earlier PASS nor generic skips certify them |
| Full Aurora / visual composition | Three main tabs with inspectors; no replacement shell or broad relayout | UI contract and syntax checks; full Aurora earlier browser observations | Exact-code overflow/focus/accessibility/browser pass; owner has NOT accepted design correspondence |
| Git / release | Original worktrees preserved; exact-path staging; checkpoint in task PR | Core checkpoint 13573, short artifact/context/static PASS | Final clean SHA, full regression, fresh CI and owner acceptance; merge/deploy NOT authorized |

## Evidence rules and withdrawn claims

- Historical full **4537 passed / 110 skipped** is for `92436698`, not this
  code. Focused suites overlap and must not be added into a fake full total.
- **69 Agent World PostgreSQL**, **41 legacy PostgreSQL**, and the separate
  API/worker/restart/RLS scenario are different receipts. Exact cluster,
  app-role/TLS and WIP hash are in the
  [PG receipt](../changelog/2026-09-08-agent-world-postgres-unified-acceptance.md).
  Neither adapter PASS nor the generic-suite skips certify a new runtime.
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
  validation/isolation/history assertions; final full rerun remains required.
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

Next operation: freeze shared source, preserve the checkpoint after short
mandatory diff/context/artifact gates, then restart only the isolated 8804
instance on that exact code. Run manual Preview and full Aurora routes while
the final focused/full/static and disposable PostgreSQL tests run on immutable
test data. Fix reproducible failures in later commits. Do not stop at one UI fix.

Use the [owner route guide](AGENT_WORLD_OWNER_ACCEPTANCE_GUIDE.md) to record
individual observed steps. It is a checklist, not a second implementation status.
The separate [fresh 376 PostgreSQL receipt](../changelog/2026-09-08-agent-world-postgres-376-acceptance.md)
records its exact source/cluster/runtime hashes; seven later Persona cases are
not silently included in those counts.

Before any future Local activation, prepare a data backup and an explicit
rollback to the protected 2b6d0112 runtime and request the one exact activation
approval. No Local activation is included in the current mandate.

OWNER ACCEPTANCE READY: NO — integrated exact-code gates and functional
limitations above remain; this is not only a missing owner key.
VISUAL DESIGN ACCEPTED: NO.
LOCAL 8765 UPDATED: NO.
MERGE / DEPLOY: NOT PERFORMED.
