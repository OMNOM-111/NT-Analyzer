# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-09-29T06:38:21Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Status: PARTIAL
- Scope: open `0.10.0-beta.101` product card, originating in Local beta.95 → beta.96; beta.97–beta.100 are historical technical iterations, and beta.101 Canary acceptance is in progress
- Owner decision superseding the older partial Local snapshot: the frozen beta.96 Local package is approved 7/7. No repeat acceptance of Social, Chat, registration, device trust, Agent World, sharing or charts is requested. The only remaining full-package server blocker is Agent World/AI Center plus a real non-owner shared-model invocation. A real Canary Professional user displayed TopstepX MBT 10-26 5m candles; the disabled server Preview sandbox is expected, not a chart failure. [Decision and source probe](../changelog/2026-09-28-beta96-owner-decision-server-parity.md).
- Current Canary beta.101: PR #303 merged as final main `58fbb23d1551e267dd7fe622c2414580820f3f8c`; mandatory CI [run 36526068091](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36526068091) PASS. One signed artifact `art_ed57f7076b6b46b78cc3309c55470016`, build `sf-0.10.0-beta.101-58fbb23d1551-20260929T063217Z`, archive SHA256 `E493DCE15A7B59AD1E4412046003754F29CA1A8492C5B317813374DAC565AFFE`, runtime/manifest SHA256 `99795E581E84C1CC4C2D42A233F8E337EA4ABB9267A15BF42353B1D963E87496`, signature verified. Before deploy, verified backup `backups/pre-beta101-canary-peer-20260929T063236Z` (manifest SHA256 `C90F4A17F98F25BA386B04A1DF06B6E34B98C23BAE5549D7E4F4533586D659B3`) retained DB/runtime/config/secrets and beta.100 rollback. Deployment `dep_45db3f6c48c549ad978b0f9a3e895501` is `canary_checking`; public `/live` and `/ready` PASS. Linux process selected `ServerSecrets` with protected Canary key, no DPAPI. Trusted Local in-memory snapshot transferred the existing five owner models via pinned SSH stdin and server re-encryption (migration `caea5f06-d5e6-5625-ab08-db5e6c944fcc`); full owner/non-owner provider/share/restart acceptance remains PENDING. No Production promotion, scheduler change or Local Vitek cutover. [Release record](../changelog/2026-09-28-beta101-server-secret-migration.md).
- Current Production version/build/artifact when known: `0.10.0-beta.99` / `sf-0.10.0-beta.99-68ba3a95f804-20260928T021954Z` / `art_3ae473a96bb24d439fd5cb6d3a1d1096`; archive SHA256 `BD6FDEC99112154E9B0B4FBA26A2F1E257399D9B8FC15BC4500E1BD65AEBDC43`; runtime artifact SHA256 `081C9A99480C49BFBC13C29EA061E994B8310FB6A82EE431B31A38661952A2FB`; signature verified, production trust.
- Production incident 2026-09-27: authenticated owner and Professional overview sessions can enter a real full-page reload loop when the runtime-account response is graded `confirmed_live=false`. CDP proved a script-initiated reload from `nt-account-change`, with no redirect, auth/device loop, service worker or runtime exception. beta.92 contains the same latent defect and was not used as a misleading rollback. The minimal beta.98 correction emits the event only for a real live-to-offline selected-account transition. [Incident and release record](../changelog/2026-09-27-beta98-production-reload-loop-hotfix.md).
- Historical beta.100 Canary PARTIAL checkpoint (superseded by beta.101): `0.10.0-beta.100`, source `7b66bcb6abd486891870b0419afd93f8828dbb85`, build `sf-0.10.0-beta.100-7b66bcb6abd4-20260928T210349Z`, signed artifact `art_de49135714cf48b6aace2a977fad334f`, archive SHA256 `2CCB46F376C4A6445295D7221BB753B959F08FBE1970065996AF7460C6CB4DB1`, runtime/manifest SHA256 `5FFE722FD86DE9892E7C150287C63CC3C8D3388DADD61AF3BA756C0A446812FF`. `/live` and `/ready` identity PASS; migration 0024 applied; `canary-current` beta.100, `canary-previous` beta.99. Verified pre-change DB/runtime/config/secret backup `backups/pre-beta100-canary-peer-20260928T210636Z` has manifest SHA256 `7B8EB4C484A7BF6CD580B310460D52E752DE386C7450207697F3BEF82E7EEEDF`. Server workspace opt-in is ON only for the confirmed owner and separate Google workspace, with a Canary-only protected encryption key. The owner-approved one-day Pro grant for that user is active and the AI Center opens after reload. Its Models tab shows no shared models: accepted Local owner bindings still require Windows DPAPI, while the beta.100 server vault requires owner-scoped `aw_provider.<UUID>` ciphertext and no safe migration/binding path exists in this artifact. No provider credential was copied. Full package acceptance remains PARTIAL; real shared-model invocation and wider parity smoke have not passed. Preview sandbox remains deliberately disabled; prior real non-owner live-chart evidence stands pending beta.100 retest.
- beta.100 server-parity code merged via PR #300 and narrow release identity PR #301 to final `main` SHA `7b66bcb6abd486891870b0419afd93f8828dbb85`. It uses authenticated PostgreSQL/RLS Agent World domains and a new FORCE-RLS encrypted server BYOK/shared-model store. All five PR checks, isolated TLS PostgreSQL/RLS tests (74/74 with non-`BYPASSRLS` app role and separate principals) and mandatory final-main CI [run 36471503031](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36471503031) PASS after a transient Windows loopback-test abort on first attempt. The [beta.100 technical release record](../changelog/2026-09-28-beta100-server-parity-release.md) has exact release gates. Production remains beta.99; no Production scheduler or Local `StratForge Vitek` cutover is included.
- Current Production runtime: the owner approved the exact beta.99 artifact and approval `apr_07a3758b5207418bb70e2096971b2873` was consumed by deployment `dep_48d36d71b00e480eac201c3f3a71e0f1`. `/live`, `/ready`, owner login/API and separate non-owner Professional session/workspace/entitlement and cold-start PASS. Production pre-deploy backup is `backups/pre-beta99-production-peer-20260928T024620Z`; beta.97 is the immediate previous release and beta.92 remains preserved in the older rollback history. This scoped runtime PASS does not close the beta.96 product card; final product closeout is paused.
- Current Development/CI: PR #299 merged to final `main` SHA `68ba3a95f804800195bb6e8dff556dd843b8eb6e`; mandatory final-main CI run `36365092457` PASS. beta.99 routes subscription read/reference/write/status/audit through the authoritative server-storage predicate for Canary and Production while preserving Development DPAPI fail-closed behavior. PR #297 had no unique changes and was closed as superseded.
- Operational report cutover remains paused: Production owns the interactive shared Telegram route, but all periodic delivery switches are OFF; Local `StratForge Vitek` remains enabled and Running. The pre-change settings backup is `backups/pre-beta99-scheduler-pause-20260928T030245Z`. No second-user Telegram action was performed.
- Product-card status contract: beta.95 → beta.96 is the single open product card and remains `● In progress`. beta.97–beta.99 are its exact technical iterations, not separate milestones. `✓ Done` requires Development, Local test, explicit owner acceptance, Canary and verified Production; `◉ Ready for owner review` is allowed only when the current technical stage is complete and the requested owner check plus next action are explicit; `○ Planned` means work has not started. Every card preserves separate Development / Local test / Owner / Canary / Production stages. [Parity and status record](../changelog/2026-09-27-beta96-product-card-parity-and-status-contract.md).
- Multi-user Telegram acceptance is not implemented: ordinary scoped users have browser SF Chat but no accepted personal Telegram binding/topic mirror. A real second Google Professional user reproduced registration/linking → Open Telegram → Start with no confirmation/linking step. No unsafe second user was added to the owner forum; issue #296 remains separate from beta.99.
- Local source verified SHA: 56945ac68e94cb7ffa031ef2312dec5a9ad80a54 (canonical live mirror; 6080 passed / 134 skipped across 293 files after complete affected-module reruns; full Preview/owner walkthrough plus final chart-lifetime follow-up; browser-tool interruption/recovery documented in the canonical receipt)
- Historical beta.97 integration checkpoint: `f455043f`, PR #294. Full Local regression: 6087 passed / 134 skipped / 0 failed in 1:07:38; 650-file pre-release bundle and context validation PASS. It later merged as `4f6bb0b3` and completed Canary and Production promotion.
- Local verification UTC: 2026-09-24T04:08:00Z; on 2026-09-26 the owner explicitly accepted the current Local version as the release basis, with non-critical design details deferred
- Historical UI correction: [SF Chat dialog receipt](../changelog/2026-09-05-sf-chat-app-dialogs.md); existing backend/data/flags unchanged, no release
- Historical protected Local program snapshot: [integrated review record](../changelog/2026-09-05-agent-world-program-review.md) — clean 2b6d0112 was active; genuine report/PNG observations, real fact handoff and deduplicated manual SF Chat delivery verified; 4235/44 skipped full suite, 542-file bundles and CI 33984524477 3/3 PASS. New unified-source evidence is separate below; full-program/owner acceptance remains open.
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Unified Local branch: `integration/stratforge-unified-local` (PR #280), product-card version `0.10.0-beta.96`; that exact Development build was not promoted under the beta.96 artifact identity, while its source lineage continued through technical iterations beta.97–beta.99
- Local 8765 verified implementation: clean `56945ac68e94cb7ffa031ef2312dec5a9ad80a54`, build `dev-0.10.0-beta.96-56945ac68e94`; final documentation-only closeout does not rebuild Local. Original owner access settings unchanged, Preview=false.
- Active Shared Models work branch: `codex/shared-model-local-completion`, continuing draft PR #291 (`feat/shared-model-access`). It preserves the existing WIP ancestry; [current Local acceptance](../changelog/2026-09-24-local-preview-social-followup.md) supersedes earlier Local runtime identities below. Historical Agent World review remains in [AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md](../current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md).
- Historical live endpoint recheck 2026-09-26: Canary and Production then reported beta.92. It is superseded by the beta.97–beta.99 technical release history recorded above; beta.92 remains a preserved older rollback slot.
- Telegram trace 2026-09-26: the owner reports were produced by Local. The Local Telegram notifier and Chief scheduler both had periodic paths; server Telegram report settings were disabled. Canary and Production had the same protected bot token fingerprint, while topic mappings lived in separate data roots, so only Production could reverse-route replies received by its webhook. The release candidate removes both independent schedules, makes Vitek the single report controller, persists stable report keys and SF Chat history, and makes Production the sole operational Telegram owner by default. Current Local remains running unchanged until the Production replacement is accepted.
- Release candidate details: [beta.97 Telegram/report cutover](../changelog/2026-09-26-beta97-telegram-report-cutover-release-candidate.md).

Current follow-up: **BETA** — [Local TopStep mirror and Preview corrections](../changelog/2026-09-24-local-preview-social-followup.md). The latest owner-approved contract is personal NinjaTrader first, otherwise common live TopStep mirror for active chart-capable trial/subscription users, including disposable Preview. No DEMO fallback. Legacy source flags do not gate end-user mirror admission. Social/avatar, sharing labels, shared-model revoke and one-click owner-session return passed the fresh Preview/owner walkthrough on clean 003e00d1. Charts follow the active disposable process rather than the paid-model 30-minute limit; final regression is 6080 PASS / 134 skipped across 293 files. Final runtime 56945ac6 retains active Preview charts beyond the AI-call time budget. The last browser-control interruption and canonical disposable cleanup are documented in the receipt; no owner session was replaced. Local only; no Server/Canary/Production changes.

Current scoped Local status: **BETA** — [Preview parity/account lifecycle](../changelog/2026-09-23-preview-parity-account-lifecycle.md), continuing `ca8e6639`. Historical trial chart baseline, shared-model labelling, current Deputy/avatar speech, public Social projection and confirmed Local account erasure passed manual acceptance and regression. Preview uses normal registration/trial with disposable private stores; public posts/shared models remain common. Exit/Reset erases private data while minimal deletion receipts and anonymous usage survive. Production relational erasure is unavailable. The earlier DEMO/source restriction is historical and superseded by the current owner-approved live-mirror contract above; deployed servers remain unchanged.

Local chart incident (2026-09-23): the pinned Local supervisor claimed the Production public origin and isolated its chart gateway. The scoped correction uses the actual loopback listener; targeted tests PASS; correction preserved in the 0a9bcf09 baseline and subsequent Local UX checkpoint, owner Desktop TopstepX charts verified. Production supplied real MET candles during an authorized read. [Incident and exact scope](../changelog/2026-09-23-local-chart-gateway.md).

- Development delta 2026-09-21: isolated branch `codex/unified-memory-service`
  introduces one disabled-by-default `MemoryService` for Chief/chat/specialist
  context, additive entity/source/relationship records on the existing generic
  SQLite/PostgreSQL ledger, stable source/version/fragment IDs, ranked token
  context, conflict/TTL handling, and loss-accounted JSONL migration. Existing
  `Memory` is unchanged. Protected Local, runtime data and servers were not
  touched; no PostgreSQL runtime or release acceptance is claimed. Canonical
  external-model context and all write cutover flags remain OFF. See
  [ADR-0013](../adr/0013-unified-agent-world-memory.md).

- Current Agent World candidate: `2debb2d62ab1af9cba4da2e8d9bbaee9832316d2` on the final-acceptance
  branch; AW-FINAL-1 CLOSED by independent verification (2026-09-14). After `ai_automation`
  withdrawal the accepted graph stays completed/accepted (same review hash, Evaluation and SF Chat
  completion) while new commission, approval, reconcile, schedule and the next occurrence are refused.
  Exact-SHA gates: CI `34863855186` Static PASS, Ubuntu 5802/0/128 skipped, Windows attempt 3 5799 passed / 0 failed / 131 skipped, 1:54:34 (attempts 1-2 cancelled at the 120-minute job limit under shared-host load with 0 failures; not counted);
  PostgreSQL 129/0/0 + runtime PASS; browser guide 15/15 on isolated :8818 (dirty=false).
  Implementation 94% (unchanged), readiness 80% (Delegation E2E P->Y). Owner-dependent items stay open.
  [Correction receipt](../changelog/2026-09-14-agent-world-historical-acceptance.md).
  Protected Local and release environments are unchanged; no new features are in scope.

- Historical saved Agent World candidate: `81e92c1ad363ffb86e18499f78017ed6973b3626`,
  CI **34719653016** static PASS, Ubuntu **5781 passed / 2 failed / 128 skipped**
  in 1662.25 s; Windows remains running. A follow-up fixes only Persona process
  UI fixture multicast event/leave callbacks (**9 focused PASS, 2.41 s**), not
  runtime code. Exact-candidate Preview browser routes covered synthetic
  Telegram/Google/Email OTP/QR, unchecked consent, permanent/session and new-
  browser device OTP; Exit returned to QA8815 test owner, not protected Local.
  This is synthetic QA evidence, not real owner/external-provider certification.
  Full final verification remains open; **95% / 70% stay provisional**.

- Earlier saved Agent World candidate: `a091ce6794da75064a9012dfe97d50bfc140e978`,
  `codex/agent-world-final-acceptance`, draft PR #287. Exact disposable PostgreSQL:
  **129 PASS / 0 skips** (88 Agent World/External/Persona + 29 legacy + 12 workers),
  legacy runner **13/13**, static/context/diff and **610-file bundle PASS**.
  CI **34714150028 Linux: 5776 passed / 4 failed / 128 skipped** in 1480.45 s;
  Windows remains running. Follow-up fixes to three stale fixtures have 17
  scoped + 1 aggregate PASS, not a full CI PASS. Final regression/browser acceptance remains
  open. Historical 51924538 fixture failure is retained, not overwritten.
  Published **95% / 70% are provisional**, pending 36-row reconciliation under
  unchanged weights; Master records the existing 25 vs 25.5 numerator discrepancy.
  Current route: [OWNER_ACCEPTANCE_GUIDE.md](../current/OWNER_ACCEPTANCE_GUIDE.md).
  [Exact candidate record](../changelog/2026-09-12-agent-world-final-integration.md)
  is Development evidence only; Local 8765 and deployed environments are unchanged.
  Pre-final QA8815 observed synthetic Court, Only-me Social publication and
  Memory revoke. Its a091ce67 backend plus changed static files is not immutable
  final browser evidence. Test email/device setup awaits owner approval;
  impersonation does not bypass the automation device guard.

- Current Agent World integration: `codex/agent-world-final-acceptance` combines
  `9365695a` and `4d8ee514` at `334f086f`, preserving both histories. P1-5 native
  API/worker/typed Evaluation was verified on its source branch at `c16b511d`
  (CI 34678502093). Final unified regression/CI/browser acceptance is in progress,
  not inherited from those historical passes. PostgreSQL ordinary-user native
  acceptance now has real isolated-server tests, separate from prior shape tests.
  The [master status](../current/AGENT_WORLD_MASTER_STATUS.md) is the sole
  operational source. Local 8765, version and deployed environments are unchanged.
  Previous unified checkpoint: `51924538`, draft PR #287. Follow-up work adds six
  context-bound Memory scopes and named Development-only diagnostic publication;
  these do not relax real provider diversity, remote budgets or private access.
  At d7b48060: real PostgreSQL 129 passed / 0 skipped; CI 34703741359 Linux
  5745 passed / 1 failed / 128 skipped (old security fixture omitted semantic
  confirmation). Final regression is not PASS. Follow-up fixes preserve explicit
  chat continuation, accepted schedule-source binding and in-app QA confirmation.
  Windows CI reached the unchanged 120-minute timeout; no full PASS is claimed.
  Browser-discovered follow-up joins external tasks to shared task/review/chat
  presentation and pins schedule approval to its shown plan hash. Final exact-SHA
  regression and browser acceptance remain pending; no second evaluator is added.
  At 51924538, 118 non-external PG cases passed. External 10/1 exposed an isolated
  spawned-chat fixture path gap; the corrected fixture passed all 11. Receipts are
  distinct; the exact a091ce67 PG rerun above now supersedes that requirement. QA8815 preserves its
  data with a cold backup; 8765 is untouched.

- Parallel P1-5 (2026-09-10 historical checkpoint): **IN DEVELOPMENT**, isolated external-agent protocol
  and service ports; not mounted or deployed. Native Evaluation/registry integration
  requires integrator handoff. No global readiness change. See the parallel section
  of [master status](../current/AGENT_WORLD_MASTER_STATUS.md) and
  [checkpoint evidence](../changelog/2026-09-10-external-agent-onboarding.md).

Historical Shared Models continuation (2026-09-22): **BETA (Local)** on
`feat/shared-model-access`, recovered code `548c995a`, checkpoint `f43a50de`.
Registration/Preview personal-workspace provisioning and restricted QA profiles
are implemented. Live shared-model Preview passed for Chat and Agent World;
ordinary Preview profiles retain real permissions; the denied-AI profile, reset
to a fresh identity/workspace and disposable cleanup passed real Local HTTP QA.
Full Linux regression: 6035 passed / 131 skipped; Windows full coverage after
runner-related retries: 6032 passed / 134 skipped. Local owner launch endpoint
acceptance and cleanup passed; self-hosted CI jobs remain queued in draft PR #291.
[Canonical continuation record](../changelog/2026-09-22-shared-models-local-continuation.md).
No Canary/Production change is included in this work.

## Historical integration evidence — 2026-09-09

The preserved executable source of that historical checkpoint was
**`e45b64b0121014c5d796553ae8b512d98a5782ae`** on draft PR #285, with
329 focused, root static/context and 593-file pre-release bundle PASS. Clean
immutable full: **5416 PASS / 119 SKIP / 0 FAIL / 0 ERROR**, 5834.82 s;
legacy **13/13 PASS**. Fresh disposable PostgreSQL separately passed
**69 Agent World**, **41 legacy PG**, **7 Persona identity**, and actual
authenticated API → existing worker → SQL → replay → restart/RLS. These are
not inherited 376 results. Full-run skips remain **68 AW PG + 7 Persona PG +
41 legacy PG + 3 platform**; fresh DB receipts supplement, not relabel, them.
Exact source/cluster/runtime hashes: [e45 verification](../changelog/2026-09-09-agent-world-e45-verification.md).
PR rollup was empty when inspected, not CI PASS.

8804 runs an immutable e45 copy with retained synthetic data and its checked
41-file cold backup. Browser reopened and activated **Ариадна QA**, preserving
aliases/main/style/Марина face, then created a separate synthetic connection
through the wizard and completed its local-executor diagnostic: **0 external
calls**, no real key, no DeepSeek/BYOK or model-quality acceptance. The next
selected-Persona Chat request failed `execution_v2_approved_scope_changed`;
completed Work and stale “1 в работе” header also disagreed. Error history stays.

Subsequent Persona/V2 approved-identity reconstruction and read-only live-refresh
corrections are **IN DEVELOPMENT**. The e45 full/PG PASS does not certify this
later delta. Positive exact-code browser repeat, remaining integrated routes,
audible speech, new-code gates and owner acceptance remain open. Next: short
tests and a separate checkpoint, cold backup, only isolated 8804 restart on
immutable new source, then continue the full route; do not rerun completed e45
checks as though they were missing. Protected Local8765/owner keys remain
unchanged. Real registration, separate ordinary-user key, a specific permanent
real Social publication and visual design acceptance are distinct owner actions.
The program stays **IN DEVELOPMENT**, not a deployment or accepted release.

The following checkpoints are earlier preserved evidence:

`376b400dc3c8ab3a008f1e45800d401dd02c4b6f` had root static/context and a
588-file artifact PASS; immutable full **5262 PASS / 1 FAIL / 112 SKIP**,
legacy 13/13 PASS. Its stale cancel-command unit fixture was corrected later,
not relabelled PASS on 376. Its 69 AW + 41 legacy PG and API/worker/restart/RLS
results remain in the [376 receipt](../changelog/2026-09-08-agent-world-postgres-376-acceptance.md).
The subsequent [Persona checkpoint](../changelog/2026-09-08-agent-world-persona-chat-checkpoint.md)
is e45 above, with its own separately completed seven Persona PG cases.

Shared checkpoint `a03ec82b686a9f6f05c056fe5a500ecbdb3babac` is pushed (65 files,
584-file artifact gate PASS), not owner acceptance. Its detached full regression
is separate from subsequent fixes. Disposable tests confirmed a bounded
authenticated Connector-to-job binding gap; exact dispatch/scope/path validation
and source-bound synthetic corrections are described in the
[boundary record](../changelog/2026-09-08-agent-world-trusted-report-boundary.md).
Neither the protected owner data nor its historical real report was changed.

Exact-a03 detached full regression finished at 5124 PASS / 12 FAIL / 112 SKIP,
legacy runner 13/13 PASS; 68 Agent World PG, 41 legacy PG and 3 platform skips
are not PostgreSQL evidence. Later Chat-review and Router-Persona changes are
recorded separately: ledger review cannot be replaced by message stars/timers,
and the speaking Persona is not the selected executor identity. Their focused
receipts do not replace the next integrated full/browser pass. See the single
program matrix and scoped changelogs below.

Core checkpoint `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406` is preserved on
draft PR #285. The subsequent shared API/worker/Chat/UI delta connects bounded
Coordinator reviews, Persona, Process Intelligence and explicit Preview data.
Router choices and queued test-executor origin are now pinned. System and
task counts report the actual mechanism/result state, not old implementation
assumptions. Status remains **IN DEVELOPMENT** pending exact-code integrated
browser/full/runtime gates. See the
[shared checkpoint](../changelog/2026-09-08-agent-world-shared-integration-checkpoint.md)
and the single [program matrix](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).
Fresh PostgreSQL evidence is separately 69 Agent World PASS, 41 legacy PASS,
and API/worker/restart/RLS acceptance bound to its recorded application hash;
it is not final full-regression evidence. `localhost:8804` is isolated QA with
fresh synthetic data, not a replacement for protected Local 8765. Details and
remaining checks: [takeover record](../changelog/2026-09-08-agent-world-integration-takeover.md).

Agent World source is now `codex/agent-world-unified-acceptance`, from combined
`f0bafe8ea46653827bc836afcb2197964390cf08` plus preserved late Claude documents.
See the [intake manifest](../changelog/2026-09-08-agent-world-integration-takeover.md).
Mechanisms/review are already integrated. The non-trading root/worker/Chat
route has focused evidence; ordinary SERVICE delivery and Router hardening
have separate scoped repeats. Latest full
4537/110 result is historical code `92436698`, not the new source. Part E's
PostgreSQL runtime evidence and fixture-claim withdrawal are retained separately.
Local 8765 still serves `2b6d0112`, without an activation. The inherited metadata
and snapshot describe earlier Local/deployment evidence, not today's integration
HEAD. No new release/Production verification, provider call or budget is authorized.

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

## Earlier scoped checkpoint verification

Historical ef4006eb: **3914 passed / 44 skipped**, 759.73 s, 218 focused PASS,
legacy 13/13, Python/23-JS/root/context and staged/runtime 533-file bundles PASS.
Exact-SHA [CI 33956017912](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33956017912)
passed all three jobs; absent main-target checks are not counted as green.
Narrow Azure owner-binding follow-up: **3925 passed / 44 skipped**, 759.35 s,
plus 187 focused PASS; its exact-bundle/commit/activation subsequently passed on bd239e76.
The 44 skips remain explicit; 41 have separate actual isolated PG evidence.
Three real DeepSeek/Gemini comparisons passed: n=3, OBSERVED, low confidence,
no routing effect. Project versioning, private Memory promotion, manual routine,
calendar forms and System flags were exercised in Local. Full Court/shared
Memory/Social/own-key and owner design acceptance remain open. Actual Desktop PNG,
saved rejection recovery, active-model rating and local calendar display passed
on ef4006eb; actual historical bars are not labelled LIVE.

## Evidence modes

- Repository evidence: legacy isolation PR #254 and Telegram URL-flow PR #255
  merged with mandatory CI GREEN on `main`.
- Earlier isolated PR #270/#278 implementation and test snapshots are
  [historical context](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md);
  they are integrated into the accepted Unified Local base.
- Unified Local evidence: auth/onboarding, Device Confirmation, SF Social,
  SF Chat and isolated Owner Preview coexist in `0.10.0-beta.96`. Contextual
  Preview registration verification is `173 passed` focused and `2680 passed,
  44 skipped` full, plus a manual browser walkthrough of Telegram, Google,
  e-mail/OTP, QR, permanent/session-only trust and Owner Local restore.
- Accepted Preview closeout is `4ae766ea0c3258a8bb049644ac2afbba6cb89330`,
  clean and synchronized, PR #280 CI five checks successful. The 44 skipped
  tests are unverified scenarios; this evidence belongs to the baseline.
- Agent World integrated code now includes scoped Personas/models, verified
  model-to-NinjaTrader/Desktop work, independent evaluations, Consensus/Court,
  controlled Memory, projects, manual routine/calendar follow-ups and explicit
  SF Social publication inside the same three-tab AI Center. Existing SF Chat,
  worker, permissions and paid-budget authorities remain in use. This delta is
  implemented but still `IN DEVELOPMENT`, not a finished owner acceptance.
  [Canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) and
  [ADR-0012](../adr/0012-agent-world-integrated-local.md) identify exact scope.
- Protected 2b6d0112 Local snapshot: all ten flags default OFF. Its exact
  Development workspace opt-in through
  `STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES` enables eight reviewed paths:
  read/UI/tasks/evaluation/memory/consensus/Court/social. Router shadow and
  Execution V2 remain OFF. Controlled Preview has its separate four fixture
  flags and rejects real model/domain side effects; browser input enables none.
  This describes the protected Local snapshot, not the later isolated e45
  workspace's explicit Router/V2/delegation/scheduler test opt-ins. No protective
  flags on owner Local are changed by those isolated tests.
- The old owner process served dirty beta.93 / `7062f749` because its scheduled
  task still targeted the old checkout. After explicit owner approval, isolated
  copy checks, coherent/cold backups and exact process retirement, Local 8765
  initially ran clean `486db834`, then the recorded model/domain/dialog checkpoints;
  now `2b6d0112` beta.96
  against the same original owner data root. The original verified backtest
  and its original chat messages survived restart without duplication. The new
  explicit Anna handoff brings the backtest thread to eight messages. The narrow
  Azure owner binding is active and verified; no second worker may share
  the owner data root.
- Live ca505d83 SF Chat → DeepSeek → NinjaTrader → original report passed:
  model task `62182839-1c4c-563d-8186-bcef081ec599`, 64 historical trades,
  net -969.70, PF 0.725188. Independent source verification is not profitability.
  DeepSeek connection test passed; Z.AI endpoint was unavailable. Ordinary-user
  signup awaits owner Terms confirmation and separate OpenRouter key, not copied credentials.
- Claimed delivery, roles, private containers, sealed-failure recovery and
  rating/calendar fixes are active at ef4006eb with exact-SHA CI. Older results
  remain historical. The noncanonical Gemini plan stayed rejected, without
  Desktop dispatch; its saved failure reached the original chat once without
  another provider call. A new command produced a genuine Desktop PNG, 140/800
  historical bars, in the same chat. Earlier failures remain failures.
  Separate actual isolated
  PostgreSQL 17.10 regression passed `41 passed, 0 skipped` against existing
  migrations 1–22, TLS and non-superuser/NOBYPASSRLS roles. This does not provide
  an Agent World PostgreSQL adapter for that historical code: its domain store
  was Development SQLite only. Current e45 adapter/migration 0023 and fresh
  69/41/7 plus runtime/RLS evidence are separately recorded above. See the
  [integrated verification ledger](../changelog/2026-09-05-agent-world-integrated-local.md).

- Operational evidence: Release Center closeout, server symlinks and read-only
  Production audit/acceptance evidence in the current handoff.
- Canonical live release snapshot:
  [2026-08-31-beta85-forward-only-promotion.md](../changelog/2026-08-31-beta85-forward-only-promotion.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Agent World | `IN DEVELOPMENT` | Accepted Local implementation `56945ac6` includes Shared Models BETA, verified disposable-user flows and preserved team/history behavior. On 2026-09-26 the owner accepted the current Local product as the release basis while deferring non-critical design details | This does not convert unfinished Agent World mechanisms to AVAILABLE; server acceptance and remaining explicit blockers stay separate |
| Auth / owner identity | `BETA` in Unified Local | `0.10.0-beta.96` has one three-step registration contract for Telegram, Google and e-mail, a stable StratForge handle shared by profile/SF Social/SF Chat, final clickwrap consent and the existing shared environment-routed provider architecture. Owner Preview uses the same state transitions with sandbox-only synthetic credentials | Not present in the last recorded deployed beta.92 artifact; live real-provider acceptance and immutable Canary/Production promotion remain separate gates |
| Device confirmation / trusted access | `BETA` in Unified Local | Every new unknown human browser/app access starts as a two-minute pending session. The first freshly authenticated device can choose permanent trust or current-session-only without a redundant second OTP; later unknown clients still use confirmed Telegram or verified e-mail. Machine → Client → Session grouping remains proof-based | Integrated and browser-verified in Local beta.96, but not present in last recorded deployed beta.92; real-provider acceptance and release promotion remain separate gates |
| Legacy UI / Telegram Mini App | `DEPRECATED` | Merged main serves Aurora only; legacy UI, Mini App, remote-access and tunnel routes fail with HTTP 410. Classic assets are available only in a separate localhost read-only Legacy Viewer. Telegram `/start` uses a normal URL button | Last recorded Canary/Production release is beta.92; historical snapshots remain until owner review |
| User entry and trial access | `BETA` in Unified Local | Anonymous product access is removed. Every verified account receives the same full product with a default five-hour active-use starting grant; idle time is not charged. Profile/security remain available after exhaustion | Not present in last recorded deployed beta.92; product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | A versioned release/change record is visible with title, summary, PRs, SHA, build/artifact, stage, checks, duration and environment identity. Production approval/promotion fails closed without title, summary, source SHA and verification PASS | beta.92 is the last recorded acceptance; any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Accepted Local `56945ac6`: 6080 passed / 134 skipped across 293 files after complete affected-module reruns; a separate 2026-09-25 prepublication slice added 430 focused PASS and a 646-file pre-release bundle 4/4 PASS | Skips stay explicit; final release-candidate full regression, PostgreSQL and final-SHA CI are still required |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was not changed by this Telegram/report correction | immutable Canary/Production acceptance remains pending |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | Last recorded Production Connector on VMNINJA is `0.4.5-dev.1` (2026-09-02 health accepted); SERVER BACKTEST, cancel state machine, device catalog, account snapshot and Connector LIVE/GRACE/OFFLINE presentation are accepted | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material; current installed version has not been re-verified |
| Production worker queue | `AVAILABLE` | Eleven worker slots remain 4/4/2/1; empty workers use adaptive jittered backoff and one 30-second stale sweeper. Later auth hot-spot work reduced `/api/auth/status` latency but did not claim CPU improvement outside noise | DB tx/s still lacks a safe first-class diagnostics path |
| SF Social / SF Chat | `BETA` in Unified Local | The former Community tab is SF Social; existing profile/privacy/feed/moderation and human/AI SF Chat stores stay authoritative. Agent World adds explicit verified snapshots to the existing Community store and model/application evidence to the same chat; real backtest delivery survived restart | Agent World Social publication remains pending; rejected-plan recovery and actual PNG chat delivery passed; broader Strategy/Chart/Live adapters remain separate. Existing relational PG tests passed, not an Agent World PG release. beta.96 is not promoted to Canary/Production |
| Documents | `BETA` | Hidden Markdown amendment blocks are removed and AI provenance is infrastructure-only or absent | Last recorded server deployment is beta.92; current live identity requires a fresh endpoint check |
| Legal | `AVAILABLE` | One official onboarding agreement `2026-08-30-v2` is the sole versioned clickwrap; related official policies are readable informational documents; owner configuration is absent from both document API namespaces | Live Trading remains unavailable pending separate release and legal requirements |

## Last recorded operational identity (not re-verified in this task)

| Environment | Version | Git SHA | Build ID | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- | --- |
| Canary | `0.10.0-beta.92` | `9d800770d08e0072ec453c2611e98726e295b2e4` | `sf-0.10.0-beta.92-9d800770d08e-20260902T035324Z` | `07A3961277E3879357EE92A8471911FAFA4B57E1B3BF2D046E1BCA41D27A9169` | accepted 2026-09-02; not re-verified live |
| Production | `0.10.0-beta.92` | same | same | same | `production_live` 2026-09-02; not re-verified live |

The later Release Center audit identifies one accepted beta.92 artifact in both environments:
`art_57db4318cb8745d399d98bccf48de396`, archive SHA256
`FAD094C243B8EDE0B365BE9874466FA9C53C414CB0C9588D4EF4DC0CE62FF315`,
manifest SHA256 as in the table. Canary passed at `2026-09-02T03:54:35Z` and
Production became live at `2026-09-02T03:57:03Z`. See the
[Connector closeout](../changelog/2026-09-02-connector-0.4.5-catalog-snapshot-identity.md)
and [timeline audit](../changelog/2026-09-24-timeline-source-audit.md).

## Deprecated current-state claims

- beta.29-beta.87 release identities are history, not the latest recorded deployment.
- The target Production installation is no longer offline or blocked by
  `sf_connector_installations_workspace_id_fkey`.
- Earlier draft legal labels are obsolete; the current package is official product documentation.
- Local chart admission follows the owner-approved common TopStep mirror contract; provider-contract verification is not claimed.

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
