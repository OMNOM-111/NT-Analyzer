# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-28T03:06:00Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Scope: open beta.95 → beta.96 product card, beta.97–beta.99 technical iterations, paused closeout and multi-user Telegram blocker
- Status: PARTIAL
- Owner decision (2026-09-27 America/Los_Angeles): all seven Local beta.96 package tasks are explicitly approved as one frozen product package, `ownerApproval=approved` 7/7. Do not request another Local acceptance. The single remaining server-parity blocker is authenticated Agent World/AI Center plus a real non-owner shared-model invocation; see [decision and read-only probe](../changelog/2026-09-28-beta96-owner-decision-server-parity.md). A real separate Canary Professional user displayed live MBT TopstepX candles; server Preview sandbox being disabled is expected, not a chart blocker.
- Active Development candidate: PR #300 contains server-parity implementation `33e8064c`, real RLS correction `0c090d02` and additive PostgreSQL migration 0024, with source and scoped verification in the [beta.100 technical release record](../changelog/2026-09-28-beta100-server-parity-release.md). An isolated TLS PostgreSQL database with non-`BYPASSRLS` app role passed 74/74 tests, including separate-principal share/key/usage isolation; mandatory CI is running. This is unmerged/unreleased and no live server acceptance PASS is claimed. Do not turn on the new server workspace gate or modify server DB/secret state without backup and verified rollback.
- Current Production version/build/artifact when known: `0.10.0-beta.99` / `sf-0.10.0-beta.99-68ba3a95f804-20260928T021954Z` / `art_3ae473a96bb24d439fd5cb6d3a1d1096`; archive SHA256 `BD6FDEC99112154E9B0B4FBA26A2F1E257399D9B8FC15BC4500E1BD65AEBDC43`; runtime artifact SHA256 `081C9A99480C49BFBC13C29EA061E994B8310FB6A82EE431B31A38661952A2FB`

Current product line: Local beta.95 → beta.96 is the single open product card;
beta.97 is its first server release, beta.98 is its reload-loop hotfix and
beta.99 is its server entitlement-storage correction. They are exact technical
iterations inside beta.96, not separate product milestones. Do not rename or
collapse their SHA/artifact history. The
[chronology record](../changelog/2026-09-27-beta96-beta98-timeline-reconciliation.md)
contains exact identities and owner approvals.

Current release gate: **BETA.99 SCOPED PRODUCTION PASS / BETA.96 PRODUCT CARD IN PROGRESS**. Live CDP originally proved a genuine
script-initiated full-page reload, not an auth/device/redirect/polling/exception
loop. `ui.js` emitted `nt-account-change(detail:null)` on every cold offline
account read; the overview listener called `location.reload()`. Blast radius is
owner and ordinary Professional overview sessions with graded
`confirmed_live=false`. beta.92 has the same latent trigger, so rollback was not
used. beta.98 makes the null event transition-only. PR #295 merged as
`0b9233d7c8983adc0a3a6c37350a3974770cb738`; final-main CI `36346357025` PASS;
signed artifact `art_b05720a1f2d44672805b45b513f0203e` was deployed on Canary.
Identity/readiness, restart and owner offline cold-start PASS. Real separate
Professional registration then failed before cold-start: Canary subscriptions
fell through to Windows DPAPI, leaving an active non-owner user with
`initial_trial_pending=true` but no workspace, entitlement or session. Canary
acceptance for beta.98 was BLOCKED; Production was not approved. [Incident
record](../changelog/2026-09-27-beta98-production-reload-loop-hotfix.md) and
[storage blocker](../changelog/2026-09-27-canary-professional-registration-storage-blocker.md).

Operational safety: Production periodic delivery switches remain OFF; Local
Windows task `StratForge Vitek` remains enabled and Running. Interactive
Production Telegram ownership stays active, but do not complete report cutover
until the separate model/orchestrator route is accepted.

Multi-user Telegram acceptance: **EXTERNAL BLOCKED / issue #296**. One shared bot token is
already used, and browser SF Chat/agent work is scoped, durable and deduplicated.
However ordinary users do not get their own Telegram topic or mirror, and a
single shared Telegram forum cannot hide other members' topic history. Foreign
scoped inbound is rejected before model invocation, but the refusal has no
own-chat/pairing CTA and legacy unscoped topics need fail-closed migration. A
real second Google Professional user reproduced registration/linking → Open
Telegram → Start with no expected confirmation/linking step. Do not add that
user to the owner forum. The next implementation must bind
user + workspace + conversation + private chat/container + thread and verify the
sender before routing.

Historical pre-deployment checkpoint (2026-09-26): **SUPERSEDED BY THE LIVE
INCIDENT ABOVE** — the owner
accepted the current Unified Local as the release basis and deferred non-critical
design polish. Candidate beta.97 removes the two independent periodic-report
schedules, makes Vitek the single scheduler in the Deputy role and persists one
report/result/delivery key across SF Chat and Telegram. Production is the sole
default operational owner of the shared bot; Development and Canary were to stay passive
for topics, updates, mirroring and reports. The existing Local service is still
running unchanged until a verified replacement exists.

The trace found that current owner reports came from Local, while server report
settings were disabled. Local produced both deterministic summaries and a second
Chief/Orchestrator report. Production owned the webhook, but all three
environments shared the protected bot token while maintaining separate topic
registries. That made reverse routing for a Local/Canary-created topic unsafe and
did not exclude competing outbound senders. No messages, reports, keys, models or
registries were deleted. Canonical details:
[beta.97 Telegram/report candidate](../changelog/2026-09-26-beta97-telegram-report-cutover-release-candidate.md).

Those beta.97 build and promotion gates completed, but the later reload incident
required a forward-only hotfix cycle. beta.98 completed PR merge, merged-main CI,
signed artifact, Canary deployment, restart and owner cold-start, then correctly
stopped on issue #298. No data was seeded manually and beta.98 was not mutated.

beta.99 implements only the required storage boundary correction:
subscription document read/reference/write, status and audit delegate to the
existing authoritative server predicate used by account/workspace storage.
Development DPAPI remains unchanged and fail-closed. Source checkpoint
`c68b19f9fa0c3161b31f42cb994db49f2f00faa3` merged through PR #299 as final
`main` SHA `68ba3a95f804800195bb6e8dff556dd843b8eb6e`; mandatory final-main CI
run `36365092457` PASS. The signed immutable artifact
`art_3ae473a96bb24d439fd5cb6d3a1d1096` (archive
`BD6FDEC99112154E9B0B4FBA26A2F1E257399D9B8FC15BC4500E1BD65AEBDC43`,
runtime/manifest
`081C9A99480C49BFBC13C29EA061E994B8310FB6A82EE431B31A38661952A2FB`)
is accepted on Canary and promoted unchanged to Production. A real separate Google Professional identity is non-owner,
has its own personal workspace, active entitlement and session; cache-disabled
cold start and post-service-restart checks each showed one expected navigation,
zero runtime exceptions and no reload loop. Candidate
`rc_dd6b884b2bfe4f7dace6c76bb6cbf12c` is `production_live`.
[beta.99 record](../changelog/2026-09-27-beta99-canary-entitlement-storage-routing.md).

Production promotion used approval `apr_07a3758b5207418bb70e2096971b2873`
and deployment `dep_48d36d71b00e480eac201c3f3a71e0f1`. Identity,
signature, `/live`, `/ready`, owner login/API, and cache-disabled owner and
existing non-owner Professional cold starts PASS with one expected navigation,
zero runtime exceptions and no reload loop. Current queues are clear and the
existing owner topic mapping persists. Production periodic delivery is paused;
Local `StratForge Vitek` stays ON. Ordinary-user Telegram issue #296 remains
separate. Full-package parity is still PARTIAL: final-source ancestry and 327
targeted tests PASS, but live Canary reports Agent World disabled and no real
non-owner shared-model invocation. Do not enter `Ready for owner review` or
`Done` until this server path passes full Canary and Production. Do not delete the Canary
test account without action-time confirmation. Canonical evidence:
[beta.96 product-card parity and status contract](../changelog/2026-09-27-beta96-product-card-parity-and-status-contract.md).

Checkpoint `f455043f`, draft PR #294: full Local regression **6087 passed / 134
skipped / 0 failed** in 1:07:38. The exact 650-file pre-release bundle, context
validator, timeline JavaScript syntax and diff checks PASS. Static, bridge and
Ubuntu PR checks PASS; Windows and full `python-tests` remain pending at this
checkpoint. Merge and environment release gates are unchanged.

Scoped Local work completed: **BETA** — [Preview parity/account lifecycle](../changelog/2026-09-23-preview-parity-account-lifecycle.md). Historical DEMO acceptance is superseded by the current live-mirror contract below. Ordinary registration permissions; public surfaces shared, private data isolated. Fresh Preview/owner browser walkthrough, deletion/reset/exit receipts and full regression PASS. Test containers removed; owner access snapshot unchanged. Owner review and remote CI remain separate. No server/Canary/Production work authorized.
- Local source verified SHA: 56945ac68e94cb7ffa031ef2312dec5a9ad80a54 (canonical live mirror; 6080 passed / 134 skipped across 293 files after complete affected-module reruns; full Preview/owner walkthrough plus final chart-lifetime follow-up; browser-tool interruption/recovery documented in the canonical receipt)
- Local verification UTC: 2026-09-24T04:08:00Z; pack-wide deployment anchor above remains historical, not a claim of new Production verification
- Historical UI correction: [SF Chat dialog receipt](../changelog/2026-09-05-sf-chat-app-dialogs.md); existing backend/data/flags unchanged, no release
- Historical protected Local program snapshot: [integrated review record](../changelog/2026-09-05-agent-world-program-review.md) — clean 2b6d0112 was active; genuine report/PNG observations, real fact handoff and deduplicated manual SF Chat delivery verified; 4235/44 skipped full suite, 542-file bundles and CI 33984524477 3/3 PASS. New unified-source evidence is separate below; full-program/owner acceptance remains open.
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Protected Local branch snapshot: `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282) above foundation PR #281 and integration PR #280; the active final branch is identified below, while #285 is an accepted integration input
- Historical Local origin: `0.10.0-beta.96`, source `56945ac6` on Local 8765. It was not itself promoted; beta.97 was the later server release of the evolving package and beta.98 is the subsequent hotfix.
- Integration state: scoped model/domain/Chat/NT/Desktop, real fact handoff, manual discussion, separate application observations, Consensus and Court verified; owner-dependent and full-program work remain
- Historical 2026-09-24 snapshot: Production was then beta.92. The current technical runtime is beta.99 on Canary and Production as recorded at the top; the earlier snapshot is retained only as history. See [timeline audit](../changelog/2026-09-24-timeline-source-audit.md).
- The root [`timeline.html`](../../../timeline.html) is the owner-facing handoff. Read it, the [mandatory workflow](../TIMELINE_MAINTENANCE.md) and this current handoff before development, merge or release. Update the same open product card until verified Production closeout; a merely live technical artifact does not create a new product milestone. After the card legitimately reaches `Done`, new functionality starts the next version/card. A version must have source/commit plus Development/CI evidence before artifact/Canary/Production. All current/future cards use `Done / In progress / Ready for owner review / Planned` and retain separate Development / Local test / Owner / Canary / Production stages.
- 2026-09-25 prepublication Local QA: 430 focused tests PASS; live owner MES/MNQ 12-26 and disposable Preview MBT 09-26 charts painted TopstepX/WS; checked Social/Chat/Agent World screens opened without console errors; 646-file bundle 4/4 PASS. With owner authorization, Preview registration, terms and first-device trust completed; a fresh Preview user received an SF Chat AI reply via an owner-shared model. A separate real Development user sent a private message to the owner; the owner saw it and sent a reply; the disposable user and conversation were self-deleted. The receiving side of that reply was not separately checked. A stale Preview bridge expires after 1800 seconds and breaks Social/Chat reads until a fresh launch. Permanent Social comment was blocked by automated action review, so no public write is claimed. Agent World still has the partial items in its master status, and the UI's chart task example says `MNQ 09-26` while the active chart is `MNQ 12-26`. The timeline shows a separate ✓ for checked internals and retains the overall ! and owner-approval gate. [Exact QA record](../changelog/2026-09-25-prepublication-local-qa.md).
- Scope: Agent World integrated Local implementation and pending full owner acceptance; Production deployment facts are inherited evidence
- Status: IN DEVELOPMENT

Current follow-up: **BETA** — [Local TopStep mirror and Preview corrections](../changelog/2026-09-24-local-preview-social-followup.md). The latest owner-approved contract is personal NinjaTrader first, otherwise common live TopStep mirror for active chart-capable trial/subscription users, including disposable Preview. No DEMO fallback. Legacy source flags do not gate end-user mirror admission. Social/avatar, sharing labels, shared-model revoke and one-click owner-session return passed the fresh Preview/owner walkthrough on clean 003e00d1. Charts follow the active disposable process rather than the paid-model 30-minute limit; final regression is 6080 PASS / 134 skipped across 293 files. Final runtime 56945ac6 retains active Preview charts beyond the AI-call time budget. The last browser-control interruption and canonical disposable cleanup are documented in the receipt; no owner session was replaced. Local only; no Server/Canary/Production changes.

Local chart recovery (2026-09-23), branch `codex/fix-local-chart-gateway`: the supervisor origin correction is preserved in the 0a9bcf09 baseline and subsequent Local UX checkpoint; owner Desktop TopstepX charts were verified. The separate chart PR keeps its own closeout. Preserve TopstepX/SignalR and entitlement gates. Saved MBT 08-26 and the empty MNQ probe remain separate contract/provider observations. [Canonical incident](../changelog/2026-09-23-local-chart-gateway.md).

- Isolated memory handoff (2026-09-21): `codex/unified-memory-service` adds the
  common read facade, context builder, stable identifiers, typed graph records,
  reconciliation and reversible write routing described in
  [ADR-0013](../adr/0013-unified-agent-world-memory.md). All new flags are OFF;
  JSONL remains the live writer and later becomes read-only only after an exact
  PASS reconciliation. Do not restart Local 8765, migrate owner data, enable
  external-memory egress, or touch Canary/Production without separate owner
  authorization. Next activation steps are measured shadow read, reviewed
  migration report, dual write, then archive-only canonical write.

- Current state: AW-FINAL-1 CLOSED on code `2debb2d6`, task branch
  `codex/agent-world-final-acceptance`, PR #287; later branch commits are documentation only.
  Verified on the exact SHA: CI `34863855186` (Static PASS, Ubuntu 5802/0/128, Windows attempt 3 5799 passed / 0 failed / 131 skipped, 1:54:34 (attempts 1-2 cancelled at the 120-minute job limit under shared-host load with 0 failures; not counted)),
  PostgreSQL 129/0/0 + runtime, browser guide 15/15 and AW-FINAL-1 lifecycle 20/20 on isolated :8818.
  Failed checkpoint `e1d5d24d` stays history and is not reused. Next work is owner-dependent only
  (BYOK key, audible voice, provider diversity, remote-agent budget, SF Social publication, visual P3).
  See [correction receipt](../changelog/2026-09-14-agent-world-historical-acceptance.md).
  Local 8765 and old candidate data remain untouched. No merge/deploy/new features.

- Historical saved source: `81e92c1ad363ffb86e18499f78017ed6973b3626`, task branch
  `codex/agent-world-final-acceptance`, draft PR #287. CI **34719653016**:
  static PASS, Ubuntu **5781 passed / 2 failed / 128 skipped**, 1662.25 s;
  Windows still running. Follow-up Persona process UI fixture multicast
  event/leave callback correction has **9 focused PASS in 2.41 s**, with no
  runtime-code change. Preserve the failed CI receipt; final gates remain open.
  Exact-81e92c1a synthetic Preview browser verification covered Telegram/Google/
  Email OTP/QR, initially unchecked consent, permanent/session and new-browser
  OTP; Exit restored QA8815 test owner only. Do not infer real provider/owner
  registration or protected Local-data acceptance. **95% / 70% stay provisional**.

- Earlier saved source: `a091ce6794da75064a9012dfe97d50bfc140e978`, task branch
  `codex/agent-world-final-acceptance`, draft PR #287. Exact-code disposable
  PostgreSQL **129 PASS / 0 skips** (88 Agent World/External/Persona, 29 legacy,
  12 workers); legacy runner **13/13**; static/context/diff and **610-file bundle
  PASS**. CI **34714150028 Linux: 5776 passed / 4 failed / 128 skipped**,
  1480.45 s; Windows remains running. Three stale fixture corrections have
  17 scoped + 1 aggregate PASS, not full-regression acceptance. Do not start a competing heavy full
  regression while its Windows job uses this PC. Next: complete final browser
  routes and CI, then reconcile the unchanged 36-row programme matrix.
  Published **95% / 70% stay provisional**; Master explicitly records the
  existing E2E arithmetic discrepancy, not a new scoring method or increase.
  Use [OWNER_ACCEPTANCE_GUIDE.md](../current/OWNER_ACCEPTANCE_GUIDE.md), not its
  deprecated historical Agent World guide. Exact receipt:
  [final integration record](../changelog/2026-09-12-agent-world-final-integration.md).
  No owner-key use, Local switch, merge, release or deployment is authorized.
  QA8815 browser observations (synthetic Court, Only-me Social, Memory revoke)
  remain pre-final: backend a091ce67 plus pending static changes. Preserve
  device-guard denial for impersonation; a separate test email/device flow
  awaits explicit owner permission. Final clean browser repeat is still needed.

- Current single-integrator task: `codex/agent-world-final-acceptance`, integration
  commit `334f086f`, inputs `9365695a` and `4d8ee514`. Shared-file handoff is complete;
  the old P1-5 ownership blocker no longer applies. Native P1-5 source CI is
  34678502093 at `c16b511d`; final unified checks are still pending. Work now covers
  public semantic clarification, immutable Intent replacement, synthetic process/
  scheduler provenance, real ordinary-user PostgreSQL tests and isolated browser
  acceptance. See [master status](../current/AGENT_WORLD_MASTER_STATUS.md).
  No owner credential, Local switch, main merge or deploy is authorized.
  Previous unified checkpoint is `51924538`, draft PR #287. Its follow-up closes
  explicit Memory context-scope enforcement and honest synthetic Social
  publication, including known-artifact and fresh-authority negative checks.
  d7b48060 PostgreSQL: 129 passed, no skips. CI 34703741359 Linux failed one
  older security scenario that omitted the new semantic confirmation; 5745
  passed / 128 skipped. That scenario now explicitly confirms the plan without
  weakening session-expiry assertions. Temporary QA8815 is not final acceptance.
  Chat-first, accepted schedule-source binding, Court JSON candidate metadata
  and in-app QA dialog/layout corrections require a new unified-SHA full run.
  Windows CI ended at the unchanged 120-minute limit, not a PASS. Current fixes
  add native external-task shared reads, manual-review counters and saved-receipt
  SF Chat delivery; schedule approval rejects a changed preview hash. Correlated
  synthetic programme rerun is 9 PASS in 319.50 seconds. The former next step was
  to restart temporary QA8815 after committing and repeat browser/unified gates;
  protected 8765 and final acceptance 8814 remain untouched/unstarted.
  QA8815 was restarted on clean 51924538 with preserved data and cold backup.
  PostgreSQL 118 PASS plus initial external 10/1 are retained separately from the
  corrected external fixture 11 PASS. Follow-up fixes shared external status/history
  presentation without changing old evidence. The exact-SHA PG rerun is now
  complete at a091ce67 above; CI and final isolated acceptance remain pending.
  Earlier failed/corrected receipts remain separate; no release or owner-key use.

- Historical integrator answer read at `61ff7a38` (2026-09-11): reviewed checkpoint `97095b00`,
  shared ownership unchanged; await typed Evaluation/native kind integration SHA.
  Subsequent isolated protocol/role-ownership hardening: 70 focused tests passed.
  Next bound-cancel checkpoint: 75 passed; terminal-state preservation checked.
  Subsequent cleanup: repeat revoke retries local secret deletion safely; dispatch
  rechecks after claim/secret access. Native atomic ordering remains unwired.
  Native cleanup after revoke and API/worker composition still require integration.

- Historical parallel P1-5 checkpoint only (not current next steps): branch `codex/agent-world-external-agent-onboarding`, base
  `9ae183f65149c9cc7253490810667fc75cbf9cf6`. Separate A2A 0.3 bounded connection,
  not Persona/Model/MCP. Shared integration files remain with the integrator.
  Next: agree native kind/codec and external Evaluation subject, then wire existing
  storage/queue/API. No complete app E2E claim. See
  [master parallel handoff](../current/AGENT_WORLD_MASTER_STATUS.md) and
  [P1-5 change record](../changelog/2026-09-10-external-agent-onboarding.md).
- Historical saved/pushed executable source (superseded by the integration above):
  **`e45b64b0121014c5d796553ae8b512d98a5782ae`**, task branch
  `codex/agent-world-unified-acceptance`, draft PR #285. Clean immutable full
  **5416 PASS / 119 SKIP / 0 FAIL / 0 ERROR**, 5834.82 s; legacy **13/13 PASS**.
  At preservation, 329 focused, root static/context and 593-file bundle PASS.
  Fresh separate PostgreSQL receipts: **69 AW PASS**, **41 legacy PASS**,
  **7 Persona identity PASS**, actual API/worker/SQL/replay/restart/RLS **PASS**
  with TLS/NOBYPASSRLS on a new disposable cluster. The generic full skips
  remain 68 AW PG + 7 Persona PG + 41 legacy PG + 3 platform cases.
  [Exact e45 hashes and receipts](../changelog/2026-09-09-agent-world-e45-verification.md).
  The inspected PR check rollup was empty, not CI PASS.
- New delta after e45: Persona selection is retained in Execution V2 approved
  identity reconstruction after a browser-reproduced
  `execution_v2_approved_scope_changed`. Read-only live refresh and narrow table
  wrapping are being corrected after completed Work/stale header observations.
  Late interaction/page/focus preservation, bounded Chat error details and inert
  closed drawers are in the [continuity delta](../changelog/2026-09-10-agent-world-state-continuity.md).
  **IN DEVELOPMENT**; e45 full/PG does not cover this later code. Positive
  exact-code browser repeat and the complete review/error/retry route remain.
- Isolated 8804 currently serves immutable e45 with preserved synthetic data
  and a checked 41-file cold backup. Browser retained Ариадна QA's aliases,
  main/style/Марина face after restart, activated revision 2 and completed a
  separate wizard connection diagnostic with an obvious non-secret placeholder.
  Named synthetic executor, zero external calls: not a real DeepSeek connection,
  user BYOK acceptance or professional model quality. Its following selected-
  Persona SF Chat request failed the V2 guard; preserve that error and message.
- Next operation: finish focused correction checks, save a separate checkpoint
  after mandatory short gates, cold-back up current synthetic data and restart
  **only** isolated 8804 on immutable new source. Complete the
  [owner browser route](../current/AGENT_WORLD_OWNER_ACCEPTANCE_GUIDE.md), then
  remaining non-overlapping integrated gates; completed e45 tests are not missing
  work. Owner key/real consent/specific permanent publication/design remain
  distinct holds. Protected 8765 is not switched, restarted or migrated.
- Historical checkpoint: `376b400dc3c8ab3a008f1e45800d401dd02c4b6f`,
  588-file bundle/static/context PASS. Immutable full: 5262 PASS / 1 FAIL /
  112 SKIP; legacy 13/13 PASS. Later bounded Persona chat/transport changes and
  the stale cancel-command fixture correction are separate from that snapshot.
  [Next checkpoint](../changelog/2026-09-08-agent-world-persona-chat-checkpoint.md)
  adds main/alias/UUID selection and receipt-only assistant responses, no
  professional score or model/tool authority. Its later full/PG are e45 above;
  the old failed 376 result is not relabelled.
  [Exact 376 PG evidence](../changelog/2026-09-08-agent-world-postgres-376-acceptance.md):
  69 AW + 41 legacy PASS, separate TLS/NOBYPASSRLS API/worker/restart PASS;
  seven later Persona PG cases are separate e45 evidence. Isolated 8804 used
  clean376 before e45; protected8765 unchanged.
- Historical shared checkpoint: `a03ec82b686a9f6f05c056fe5a500ecbdb3babac`, pushed to PR #285,
  clean at preservation; mandatory static/context/artifact checks passed.
  Subsequent scoped work covers canonical Connector result binding, rejected
  origin correction, Persona voice in saved SF Chat messages and preservation
  of the speaking Persona across Router executor changes. See the
  [boundary record](../changelog/2026-09-08-agent-world-trusted-report-boundary.md).
  Detached exact-a03 full: 5124 PASS / 12 FAIL / 112 SKIP; legacy 13/13 PASS.
  Skips separate 68 Agent World PostgreSQL, 41 legacy PostgreSQL and 3 platform
  cases. Later fixes preserve scoped provenance/isolation assertions; final
  integrated full/browser remains pending. The
  [Chat review boundary](../changelog/2026-09-08-agent-world-chat-review-boundary.md)
  prevents timer/message stars from accepting a Task; the
  [Router identity contract](../changelog/2026-09-08-agent-world-router-persona-preservation.md)
  preserves speaking Persona separately from executor. No flag/Local/Production
  activation occurred.
- Historical preserved core: `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`, draft
  PR #285 on `codex/agent-world-unified-acceptance`. The subsequent shared
  API/worker/Chat/UI delta and remaining gates are in the
  [shared checkpoint](../changelog/2026-09-08-agent-world-shared-integration-checkpoint.md)
  and single [program matrix](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).
  New isolated PostgreSQL evidence is 69 Agent World
  plus 41 legacy PASS and separately hash-bound API/worker/restart/RLS acceptance,
  not a new full-regression PASS. See the
  [takeover record](../changelog/2026-09-08-agent-world-integration-takeover.md).
  Local 8765 and original worktrees are unchanged; localhost:8804 is isolated QA.
- Historical independent review snapshot (already included in the unified source): `claude/agent-world-review-and-hardening`,
  local and unpushed, base `45ab4361`, HEAD `c865db2248a12f6927d077dc31efe8b05c02426e`.
  Findings, deliberate non-changes and the exact next operation are in
  [AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md](../current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md)
  with its [change record](../changelog/2026-09-06-agent-world-status-presentation-review.md).
  It reworks status counters, Persona occupancy, warning actionability, score
  provenance, System readiness axes, evidence placement and Inspector focus; it
  changes no flag, migration, route or authority. Pushed as draft
  [PR #283](https://github.com/OMNOM-111/NT-Analyzer/pull/283) (base
  `codex/agent-world-owner-preview`, review only — #282's base untouched);
  exact-SHA CI 3/3 PASS on `84115efc`, later commits not yet certified.
- Historical intake receipt: separate uncommitted work existed in the `agent-world-mechanisms`
  worktree (base `45ab4361`): PostgreSQL/RLS repository with migration 0023,
  Router V2, Execution V2 + Deviation Control, delegation, scheduler and a task
  lifecycle projection. It was reviewed read-only from a stable hash-verified
  snapshot and left untouched: 113 passed / 68 skipped in isolation, the 68
  being the PostgreSQL suite, unrunnable here for want of a server. Its
  `task_presentation.py` supersedes this branch's phase logic; the merge order
  and the port list are in the handoff. Codex has since checkpointed that work
  as `f9b94445`/`db85773f`; 31 of the 33 reviewed files are byte-identical to
  `db85773f` and the two that differ are changelogs, so the review binds to
  that commit.

Historical Shared Models continuation (2026-09-22): continue `feat/shared-model-access` from
recovered `548c995a` and checkpoint `f43a50de`; do not restart implementation.
Disposable Preview profiles now use registration trial/personal-workspace
provisioning without blanket permission grants. The old observer QA account's
temporary `ai_lab` override was restored to its recorded baseline. Live shared
model invocation in Preview passed (Chat + Agent World, usage/revoke/cleanup).
Real HTTP QA also confirmed denied AI access, a fresh identity/workspace after
reset, retained restrictions and container deletion; focused suite: 182 passed.
Local scope is BETA: owner launch endpoint E2E passed, access settings before/after
matched; full Linux 6035/131 skipped and Windows coverage 6032/134 skipped passed
with runner-related retries documented. Draft PR #291 contains the continuation;
self-hosted CI is queued, so merge/release acceptance remains open.
[Canonical continuation record](../changelog/2026-09-22-shared-models-local-continuation.md).

## Resume point — 2026-09-09

Continue in `codex/agent-world-unified-acceptance` from saved e45 and its owned
Persona/V2/live-refresh WIP, not from the old mechanisms or review branch.
The combined source `f0bafe8ea46653827bc836afcb2197964390cf08` is an earlier
intake checkpoint, not a request to reconstruct integration.
The [intake manifest](../changelog/2026-09-08-agent-world-integration-takeover.md)
accounts for both executors, the stable five-file documentation delta, excluded
runtime state and the already ported 73 flag cases. Root owns shared integration
files. Original worktrees, PR bases and Local 8765 are unchanged.
Next: freeze/save the separate correction after short mandatory gates, preserve
current synthetic data with a checked cold backup, restart only isolated 8804,
then exact-code full-Aurora/browser/regression acceptance. The e45 full/PG and
runtime receipts are complete for e45; later source needs its own evidence.
The new numeric-summary/delegation root already has normal-queue/Chat evidence;
do not implement it again. Close current remaining gates from the matrix.
Keep real/synthetic evidence separate and Part E's withdrawn claims visible.
The dated snapshot is historical; its old missing-mechanism/UI-freeze
instructions do not override the owner's new sole-integrator mandate.

## Historical mechanisms WIP checkpoint — 2026-09-06

Saved WIP source: `f9b9444524aa497781fe3de7254d1bfb0e3b062c` (37 files;
clean worktree after commit). Short static/secret/context/diff and 556-file
bundle gates PASS; exact-checkpoint full pytest NOT RUN. All further backend
work is a separate commit; frozen UI remains exactly as in this checkpoint.

Separate branch `codex/agent-world-mechanisms` preserves additive PostgreSQL
repository/RLS migration 0023, Router V2, Execution/Deviation, finite delegation,
schedule, automation authority and unfinished status/UI work from `45ab4361`.
Canonical status: **IN DEVELOPMENT**, with integration gaps; not active on
protected Local 8765 (`2b6d0112`, beta.96). No new flags or migrations applied.
New disposable AW PostgreSQL evidence: 69 PASS/0 skipped; existing PG suites:
41 PASS/0 skipped separately. Without DSNs, the new suite has 68 skips, not PASS.
Latest UI subset has 3 FAIL/88 PASS; exact-checkpoint full regression not run.
Do not inherit prior Local/CI PASS. Details, known defects, ownership and resume
operation: [mechanisms WIP record](../changelog/2026-09-06-agent-world-mechanisms-wip.md).

Independent PR #283 remains separate; no UI/presentation consolidation until
review reconciliation, and no edits to its branch/tests. Preserve existing
WIP UI only; continue non-overlapping backend in later commits. No merge/deploy
or paid external calls. Owner visual acceptance, registration, separate key and
exact permanent Social publication remain pending.

## Completed SF Chat dialog correction — historical 95912cbf verification

The task branch replaces native conversation confirmations and rename/folder
prompts with styled asynchronous in-app dialogs, plus notification-inbox clear.
Cancellation, keyboard focus, stale context and duplicate actions are guarded;
existing backend, permissions, stores and Auth/device/Preview remain unchanged.
This does not migrate unrelated release/trading/security administration dialogs.
At the completed 95912cbf checkpoint, styled dialogs, Escape/cancel, preserved history,
safe navigation and inbox focus passed in the actual browser. Full regression:
4032 PASS / 44 skipped, supplemented by final 62 dialog checks (seven auth-context
cases added after collection); 352 focused regression, root/static/context and
534-file staged/runtime bundles PASS. Exact-code CI 33970324754 is 3/3 PASS:
Windows 4039/44, Linux 4042/41 and static, including all final auth-context cases.
Skipped DB/platform cases are not new live PASS; this is no program/release closeout.
Canonical status/evidence: [dialog change record](../changelog/2026-09-05-sf-chat-app-dialogs.md)
and [program status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

## Previous verified model/domain checkpoint — aa54c294

At that previous checkpoint, clean Local 8765 ran `aa54c2940150e540d8b594dbf1d6254e172adbfd`, beta.96,
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

## Historical protected-Local implementation checkpoint — 2026-09-05

This preserved section describes the accepted 2b6d0112-era Local scope, not the
new unified source's missing mechanisms or its next operation. Use the active
resume point and canonical program matrix above for current work.

[AGENT_WORLD_IMPLEMENTATION_STATUS.md](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
is the canonical current program handoff. It records base/current checkpoint,
file ownership, flag state, tests and skips, rollback and the next safe step.
The task worktree is isolated from the clean active runtime and does not modify
PR #280. Code aa54c294 is committed/pushed with exact-code CI PASS and a separate
operational documentation closeout. The integrated page is ready for visual review,
not only two isolated demonstrations. `LOCAL VISUAL REVIEW AVAILABLE: YES`;
full `OWNER ACCEPTANCE READY: NO`, because the ordinary-user own-key,
real multi-user sharing/revocation and permanent Social scenarios are still open.
Stages 0–13 and final program/release closure are not claimed.

[ADR-0012](../adr/0012-agent-world-integrated-local.md) now defines the integrated
scope: Personas, private user-owned model connections and guarded owner bindings,
actual model/application tasks and evaluations, comparisons, Consensus/Court,
controlled Memory, projects, manual routine/calendar follow-ups, System and
explicit SF Social publication. Three primary tabs remain Overview/Work/Agents;
these tools and Task Inspector are drawers on the same page. Existing SF Chat,
worker/jobqueue, permissions, secret store and paid-budget ledger remain the
authorities. No general Router or Execution V2 replacement, autonomous scheduler,
trading authority, budget increase or numbered SQL migration is introduced.

All ten flags default OFF. The exact server-side Development workspace allowlist
`STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES`, with fresh account/device/membership
admission, enables eight reviewed paths: read/UI/tasks/evaluation/memory/
consensus/Court/social. Router shadow and Execution V2 remain OFF. Preview
continues with its separate four synthetic flags and cannot invoke real models,
domain workflows or external publication. Reads after trial/budget expiry may
retain the user's existing evidence; they do not grant new work or model calls.

Real SF Chat work requires an actual stored user message and selected model.
An independently checked Tolik/Ivan plan starts only the existing NinjaTrader
or Desktop mechanism. A valid plan stays waiting until the original source
produces a verified report or authentic PNG receipt. Separate immutable
application outcomes and evaluations drive status and SF Chat recovery. Distinct
real observations, not self-ratings or synthetic fixtures, populate reputation;
n < 3 stays NEW. Court uses three isolated judges and an immutable 2-of-3
advisory verdict, never execution. Memory sharing has an explicit live TTL/
source-revision grant; Social publishing requires the exact prepared hash and
explicit permanent confirmation. Routines/calendar acceptance creates manual
follow-ups through the existing queue; automation stays OFF.

The original Local at 8765 served dirty beta.93 / `7062f749` because its scheduled
task still pointed at that checkout. This is historical, not the current runtime.
After owner authorization, copy/cold backups, SQLite integrity and isolated-copy
startup checks, only the matched Local process/task chain was replaced. Clean
detached `agent-world-local-runtime` at `2b6d0112bef88c5bfb73970de64ec5518443e56b`
now serves beta.96, build `dev-0.10.0-beta.96-2b6d0112bef8`, with the original
owner data, account, workspace, history and NT heartbeat. No active job was lost.
Delivery, roles, private containers, sealed-rejection recovery, active-model
ratings, local calendar and new-version timestamps are active. Azure compatibility
accepts only canonical api-version on resolved Azure owner bindings;
private transport, secrets, native adapter and existing budgets do not change.
The current explicit Anna handoff retains the original report and adds one
child result to the same chat (eight total messages). Two manual follow-up
discussions each have one neutral system message; no autonomous scheduler runs.

The manual NinjaTrader proof `ui_20260905T003301149Z` has 1,273 actual bars and
64 trades, but is not Agent World-originated and remains excluded from statistics.
Fresh SF Chat/model-created backtest `62182839-1c4c-563d-8186-bcef081ec599`
passed on ca505d83: 64 trades, net -969.70, PF 0.725188, original report and hashes.
Three real DeepSeek/Gemini comparisons passed, n=3/OBSERVED/low confidence. The
verified backtest and five messages survived restart without duplication. Real
project versioning, private Memory promotion, manual routine/calendar acceptance
and System flags were exercised. Fresh three-model Court and read-only Social
preview now pass; shared Memory/permanent Social remain pending.
A Gemini Desktop plan was rejected for a noncanonical JSON wrapper, without
dispatch. Its saved failure reached the original chat once on ef4006eb without another
provider call. After an initial no-bars timeout, a new explicit command completed
task c691534b: real Desktop PNG, 140/800 historical bars, rendered in the same chat.
Both earlier failures stay failures; OFFLINE provenance remains explicit.
No second worker may share the owner data root. The ordinary
development profile resets data root to the code checkout; the verified Local
wrapper reapplies the original data root after profile load. Original task XML,
backups and manifests remain outside Git. Code rollback and data rollback are
separate; preserve new owner writes before restoring a cold snapshot.

Historical 34deb827 passed 3906/44. Historical ef4006eb passed **3914 tests,
44 skipped**, 759.73 s, **218 focused**, legacy/static/context/staged and runtime
533-file bundles, plus exact-SHA CI 3/3. The narrow Azure follow-up passed
**3925 tests, 44 skipped**, 759.35 s, plus **187 focused**; exact-bundle,
activation and actual Azure checks subsequently passed. Saved completion uses one claimed existing
worker, not another provider call. Actual isolated PostgreSQL 17.10 separately
passed **41 tests, zero skips**, 122.71 s, on existing migrations 1–22 with TLS
and non-superuser/NOBYPASSRLS roles. The remaining two shell and one POSIX
permissions tests are unavailable on Windows. There is no Agent World PG adapter:
its domain repository remains Development SQLite only, fail-closed elsewhere.
Exact-code CI and the documented aa54c294 provider/browser scenarios pass;
owner-dependent scenarios and full program acceptance remain open. See the
[integrated change record](../changelog/2026-09-05-agent-world-integrated-local.md).

The earlier code `fc78677df` full **3369 passed, 44 skipped**, legacy **13/13**,
**517-file** bundle checks and synthetic browser results are preserved in the
[pre-model checkpoint archive](../archive/AGENT_WORLD_PRE_MODEL_CHECKPOINT_486DB834.md).
[ADR-0010](../adr/0010-agent-world-owner-review.md) and
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md) remain historical scope and
safety records; their switch-pending/three-flag limitations do not describe this
new integrated implementation. Earlier PASS does not certify the current delta.

## Accepted Unified Local — beta.96

- Auth/registration, Device Confirmation, SF Social, SF Chat and Owner Preview
  coexist in one build. Human identity and StratForge handle are shared.
- Starting access is five hours of active use. Pending device confirmation is
  two minutes, with permanent or current-session-only trust. The first device
  can consume fresh single-use login proof; subsequent unknown clients use OTP.
- Contextual Preview buttons replace credentials on the actual provider screen.
  Terms, final registration and trust choices remain manual. Preview has
  separate data/cookies and blocked external effects. Exit restores full owner
  Local; no private owner values belong in this context pack.
- Inherited evidence: Preview implementation `42a99a85f164f69c6ddd0edf46859ef005e787e2`,
  closeout `4ae766ea0c3258a8bb049644ac2afbba6cb89330`; focused `173 passed`,
  full `2680 passed, 44 skipped`, static/context/bundle PASS, manual provider,
  QR/device/exit walkthrough PASS, PR #280 CI `5/5` success.
- Skipped scenarios are unverified. New Agent World checks are reported
  separately in the canonical status/change record.
- SF Social owns profiles, feed, privacy, moderation and approved result posts.
  SF Chat owns human conversations; the AI conversation authority is projected
  through the same shell. Strategy/Chart/Live publishing adapters remain
  `IN DEVELOPMENT`. The navigation-stage SF Social label is now applied;
  compatible `community*` APIs remain.

## Dependency, review and CI

The owner-review PR targets the foundation branch so its diff contains only
this slice. PR #281 and PR #280 follow their own owner-approved merge process.
After that, retarget/rebase the stack as appropriate and rerun applicable
checks; do not infer that baseline CI certifies later commits.

The existing Next Architecture CI supports manual dispatch on the task branch.
The separate `ci` workflow runs only for main-targeting PRs. Record dispatched
checks and merge-required checks separately; never describe absent checks as
green. No workflow or branch-protection changes are part of this slice.

[Branch run 33937601902](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33937601902)
historically passed **3/3** on `b05ee124caf652c77689fd749cd9eadc8265d564` (documentation after
code `fc78677df`): Linux **3372 passed/41 skipped**, Windows **3369 passed/44 skipped**,
static PASS. Later 34deb827 run 33951941036 passed three jobs. Historical ef4006eb
[run 33956017912](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33956017912)
also passed all three jobs. Azure CI 33958551325 and Court CI 33960694698 passed 3/3. PR #282 stays
draft for owner review; program stages remain open.

Protected-Local exact-code [run 33984524477](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33984524477)
passed 3/3 at `2b6d0112bef88c5bfb73970de64ec5518443e56b`: Windows 4235/44,
Ubuntu 4238/41 and static. Local full 4235/44 and staged/runtime 542-file bundles
PASS. Clean Local activation, real Anna fact handoff and two deduplicated manual
discussion receipts passed. Code rollback is 95912cbf with later owner writes
preserved; no data rollback, merge or deploy is authorized. Operational docs
may advance branch HEAD without another runtime switch. Full-program closure
and owner design acceptance are not inferred from this code closeout.

## Historical deployment identity

The pack-wide `Verified against Git SHA` remains its shared deployment anchor;
`Local source verified SHA` and the canonical status identify the separate
Local implementation and accepted base. The validator's legacy `Current Git SHA` field below refers only
to that deployment anchor, not to the Agent World branch.

| Deployment metadata | Recorded value |
| --- | --- |
| Current Git SHA | `8f42158661e8247832c90bea8fc4d9f0071e647b` (pack-wide deployment anchor) |
| Local accepted base SHA | `4ae766ea0c3258a8bb049644ac2afbba6cb89330` |

This task did not access Canary/Production. The last recorded operational
snapshot remains beta.87:
`8f42158661e8247832c90bea8fc4d9f0071e647b`,
build `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`,
artifact `art_9ce9dbcb9a7a4fee9df6a54d40f29806`.
Canary acceptance and same-artifact Production promotion are recorded in
[the canonical beta.87 closeout](../changelog/2026-08-31-beta85-forward-only-promotion.md).
These inherited facts are not a live re-verification or a release of beta.96.

The former isolated PR #270/#278 descriptions, earlier test counts, operational
metrics, and `c9b2883` Preview snapshot are preserved in
[pre-foundation historical context](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md).
They no longer define the current Local baseline.

## Remaining boundaries

- The unified source implements explicit SQLite/PostgreSQL Agent World storage
  and migration 0023, with no silent fallback or migration of owner data.
  Fresh e45 has **69 AW PG**, **41 legacy PG**, **7 Persona PG** PASS and
  separately actual authenticated API/worker/SQL/replay/restart/RLS PASS. The
  legacy 41 are storage 12, workers 12, relational SF Chat 9 and Stage 8 8;
  they are not AW adapter tests. The generic run's 116 database skips remain
  visible, supplemented by those fresh receipts. Earlier migrations 1–22/41-only
  PASS and the protected Local's SQLite mode are historical/different scope.
  This is not a Production migration or acceptance of subsequent WIP.
- DeepSeek and Gemini connections and three actual comparisons passed; fresh
  model/chat/NT report passed on ca505d83 and survived 34deb827 restart. Z.AI
  unavailability and initial chart failures are not PASS. New actual PNG, saved
  failure recovery and corrected ratings/calendar passed on ef4006eb; Azure passed
  on bd239e76. Court format/result presentation, shared Memory/Social and own-key acceptance remain.
- Agent World is `IN DEVELOPMENT`: domain mechanisms are implemented, but the
  full local owner acceptance, Git/CI closeout and stages 0–13 are not closed.
- Ordinary test signup `aw_model_review_0905` reached final Terms on localhost;
  owner confirmation and separate OpenRouter key (`openrouter/free`) are pending.
  The new personal-container CTA grants no NT/key/budget/flag permissions;
  actual private-provider acceptance is `PENDING OWNER KEY`, not a reason to stop
  other acceptance work or copy owner keys into a test account.
- Bounded Router V2, Execution/Deviation, multi-level fact delegation and finite
  autonomous scheduling are implemented in unified source and need remaining
  integrated browser/new-code gates, not redevelopment. The selected-Persona V2
  correction is separate current WIP. Protected Local remains on its older OFF
  settings; isolated-workspace opt-ins do not authorize production/trading or a
  general planner. Actual observed evaluations do not change Router weights.
- Shared owner-feed distribution remains `EXTERNAL BLOCKED` without authority.
- Public Connector installer remains `EXTERNAL BLOCKED` on authorized signing.
- Preserve market data, Charts, Connector, trading, Auth, devices and SF stores.
- Version assignment, merge, signed artifact, Canary and Production are separate
  owner-controlled stages. Local/CI completion never implies release approval.

## Earlier scoped checkpoint verification

Historical ef4006eb: full 3914/44 (759.73 s), 218 focused, legacy 13/13,
Python/23-JS/root/context/staged and runtime 533-file bundles PASS; exact-SHA
CI 33956017912 all three jobs PASS. Azure follow-up: 3925/44 (759.35 s),
187 focused PASS. The 44 skips stay explicit; 41 have separate isolated PG proof.
Three real comparisons, NT/chat/restart, actual Desktop PNG, failure recovery,
ratings/calendar, Azure and initial domain actions passed. Full Court, shared
Memory/Social, own-key and final owner acceptance remain open.

## Next safe step

Review the updated draft PR #291, continued from the isolated
`codex/shared-model-local-completion` checkout. Local code `0a9bcf09` has
6044 passed / 134 skipped / 0 failures, bundle/context gates PASS and actual
owner/new-user browser acceptance. Remote CI and owner review remain separate. Actual Local activation,
disposable registration and short real shared-model requests were explicitly
authorized and completed. The original owner access projection is unchanged;
DeepSeek sharing is restored off and disposable Preview roots were removed.

This scoped Local acceptance does not close the whole Agent World program or
its separate owner visual/provider/voice/remote-agent acceptance. Unified-memory
migration and write-cutover flags remain off. Do not merge, release, activate
Canary/Production, alter live trading or migrate owner data under this scope.

## Canonical evidence

- [Foundation change record](../changelog/2026-09-04-agent-world-foundation.md)
- [Preview closeout](../changelog/2026-09-04-beta96-visual-audit-and-first-device.md)
- [Current status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
- [Exact e45 full and fresh PostgreSQL/runtime receipts](../changelog/2026-09-09-agent-world-e45-verification.md)
- [Integrated Local ADR](../adr/0012-agent-world-integrated-local.md)
- [Integrated change and verification record](../changelog/2026-09-05-agent-world-integrated-local.md)
- [Environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and automation](07_AI_AGENTS_AND_AUTOMATION.md)
- [Market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)

Local new-user follow-up: runtime `0a9bcf09` preserves d9c53860 and checkpoints
fdd40f90, 20ddf9dc, a06db104, 687b7b0d and fc737e96. Manual registration, shared
test/task/Chat, separate owner usage, revoke, isolated Memory, disposable cleanup
and trial page navigation passed. Owner Chat pages 181 saved messages without
large-history rendering timeouts; collapse/reopen and console checks passed on
the actual Local origin. Final native Windows regression passed: 6044 passed / 134 skipped / 0 failures; bundle/context/root-secret checks PASS.
Market-data/trading permissions are unchanged. TopStep strategy tab is IN DEVELOPMENT. Canonical evidence: [new-user Local completion](../changelog/2026-09-23-new-user-local-completion.md).

Local UX follow-up (2026-09-23): model checks now show progress/result inside
an open card, with collapsible diagnostics and no duplicate connection button.
New-user Preview conversations use a scoped Deputy response without creating
Task/review records; explicit text work retains the task lifecycle and usage.
[Change and verification record](../changelog/2026-09-23-model-card-deputy-chat-ux.md).
Manual acceptance, 368 final-code related tests, successful disposable cleanup
and full Windows coverage (6057 passed / 134 skipped; no unresolved failures)
are recorded there. The first sweep found 24 test-port dependency failures;
both affected whole files passed on rerun (66 tests), without runtime changes.
No Canary/Production activation is authorized.
