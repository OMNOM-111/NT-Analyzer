# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-10-02T19:13:00Z
- Verified against Git SHA: e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885
- Current Canary source SHA: e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885; beta.106 accepted, current health recovered
- Scope: closed beta.95 → beta.106 product card plus In progress Local recovery / beta.107 erasure task
- Status: IN DEVELOPMENT
- Current Production version/build/artifact when known: `0.10.0-beta.106` / `sf-0.10.0-beta.106-e7ecd2133c65-20261001T150927Z` / `art_7aebf504ae354ce7981c58359a1ff546`; health/readiness and delivery receipt acceptance PASS; product package 7/7 Production accepted

## Current task — Local Runtime & Documentation Canonicalization

Development checkpoint (2026-10-02T19:13Z): PR #314 is open on committed
`codex/beta107-relational-account-erasure` SHA
`7979e32b1175d4730cd20e71a5c954206645027a`, with VERSION beta.107,
migration 0025 and the PostgreSQL/RLS server erasure adapter. Fresh disposable
TLS PostgreSQL applied 0001–0025 from scratch; 170/170 affected regression
tests passed with a `NOBYPASSRLS` application role. Tests cover freeze/rollback/
retry, owner/service/shared refusal, private Social/Chat/Agent World/credential
removal, usage/audit retention, exact file and legacy AI-chat scope cleanup,
foreign data preservation and a freed Google subject. Pre-release bundle,
Context Pack and documentation validators passed. PR required CI, final-main
CI, artifact, server backup/migration/QA and actual reboot remain pending.
The server incident's exact retained handler route is still unknown.
Do not infer beta.107 Canary/Production acceptance from this Development work.
The next step is PR CI; no server promotion is authorized by a local test.
The historical beta.106 7/7 Done card remains unchanged.

Latest checkpoint (2026-10-02T17:47Z): the 503 `api_admission_saturated`
incident was recovered by guarded Canary-then-Production API-only restarts.
Both environments remained on beta.106 and returned `/live` and `/ready` 200;
no new admission rejections were observed after recovery. Pre-restart metrics
prove held HTTP handlers rather than a semaphore accounting leak, but the
exact route/trigger is unknown. Preserve the secured log snapshot and do not
claim a permanent code fix. PR #313 passed all 5 required checks at head
`67db21d569c533c6b1e33cbb7126f18135602320` and merged to `main`
`bfc26c962bf3456cb1f811c421156245240ad1ac`. The clean new
`codex/beta107-relational-account-erasure` worktree starts from that commit.
No beta.107 artifact exists yet, no account deletion or grant has occurred,
and the current card remains In progress. Historical beta.106 7/7 is Done.
[Incident/Development record](../NT-Analyzer/docs/changelog/2026-10-02-api-admission-recovery-and-beta107-erasure.md).

The dated bullets below describe the pre-recovery/PR-draft checkpoint and are
kept as historical evidence; they do not override this latest checkpoint.

The earlier seven-function product package is closed at Production beta.106;
do not repeat provider/report acceptance or reopen its Timeline card. The
owner requested a new In progress card for the post-release Local startup
incident, environment parity and AI_CONTEXT/documentation governance.

- Task-start `main`: `9483bac868d829f3891e5e09fe84c18d242cf9c6` (PR
  #312 docs-only); deployed source `e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885`.
- Old Local: root checkout `feat/shared-model-access` at `77eda536`, dirty;
  owner workspace `ws_owner_training_c1fe3f2f8a52` rejected with
  `agent_world_local_disabled` because the old startup lacked its exact
  admission environment. Desktop shortcut pointed to that root. The previous
  correct launcher was coupled to the now-disabled reporting task; do not
  re-enable `StratForge Vitek` just to start Local.
- Recovery: tracked binary patch and 36-file untracked manifest remain in
  ignored recovery evidence. Quiesced snapshot
  `a76544b4-20f8-4940-857e-dc3a140f5879` verified 2,898 files and five
  SQLite databases; subsequent WAL checkpoint/integrity checks passed.
  Nothing in the old dirty checkout was reset, cleaned or merged.
- Canonical Local: permanent `local-current` worktree on
  `codex/local-runtime-doc-canonicalization`, initial clean runtime commit
  `b809911c73c219b92e43c9b46d0d79b26a118b7a`, beta.106 application
  baseline. Documentation-only branch commits can advance the launcher SHA;
  the exact active build is exposed at `/api/runtime/env`. The fail-fast
  launcher reuses the original owner data root,
  enables exact Local workspace admission, leaves newer unaccepted mechanism
  flags OFF, and disables Local Telegram/report delivery. Actual browser
  owner overview and AI Center tabs loaded without the former denial.
  Desktop shortcut now targets this launcher; its old `.lnk` is backed up.
- This root `AI_CONTEXT/` is the new canonical context path. All 15 tracked
  files were moved with `git mv`; relative links have been rebased and
  validated. The exporter, agent instructions and CI documentation gate were
  updated; 21 focused documentation tests PASS locally. The owner-stable old
  root `AI_CONTEXT` path is now a junction to this exact canonical directory;
  its handoff file hash matches through both paths. PR #313 remains draft;
  all five required checks passed at clean branch head `2c60367fc593`, but
  PR/main adoption and real Windows reboot acceptance are not complete.
- Fresh read-only owner browser click-through loaded Social, Chat and all six
  Agent World tabs in Local/Canary/Production. Public Canary/Production
  registration reached step 1/3. The separate Chrome non-owner Professional
  session has an expired trial in both server environments, preventing a new
  chart/security click-through without a legitimate access change. Local
  guest registration and actual post-reboot startup were not independently
  observed. These are limits of the *new* parity task, not a reversal of
  beta.106's already accepted 7/7 Product/Production evidence.
- The Chrome Google account was matched in owner UI: Production user
  `8813453773725695`, Canary user `8798656225084765`, both active and
  non-owner. Its `Полное управление` workspace label does not provide product
  entitlement. Owner UI supports audited Pro grant with `0=бессрочно`, but
  no fresh grant has been applied during the current diagnosis;
  Pro includes Live-read/Live-control as well as AI/SF Chat/charts.
- The owner clarified that Chrome is their second personal Google identity for
  full ordinary-user lifecycle QA. Read-only PostgreSQL inspection on
  2026-10-02 found five hours of used trial time in both environments, plus
  preserved but expired one-day manual Pro grants: Canary 2026-09-28/29 and
  2026-09-30/10-01 UTC; Production 2026-09-30/10-01 UTC. The apparent loss of
  access is explained by grant expiry plus exhausted trial, not missing
  entitlement rows or a reused cross-environment user ID. No fresh grant,
  deletion, provider request or server change was made.
- Full server account delete/re-register is blocked by the current shipped
  contract: `account_lifecycle._preflight` returns 503 for non-Development or
  PostgreSQL-backed storage because relational erasure is not implemented.
  Do not use direct database deletion or call Local/Preview deletion server
  acceptance. Canary and new Edge Production navigation were also blocked by
  the browser client before the page loaded. PR #313 must remain draft and
  the current Timeline card In progress; post-reboot Local acceptance is
  still unobserved. The closed beta.106 7/7 product card is unchanged.
- A separate read-only health probe at 2026-10-02T14:27–14:30Z found Local
  live/ready 200, but Canary and Production public live/ready 503 with
  `api_admission_saturated`; repeated public live stayed 503. Host-local
  Production `api-app` health was also 503 although Supervisor showed
  processes RUNNING. No runtime change or restart was made. This current
  availability failure blocks fresh QA independently of server account
  erasure; do not present historical beta.106 PASS as a current health PASS.

Next: investigate and restore current server API admission health through a
separately authorized, data-safe operational diagnosis. Then owner decision
on whether to authorize a separately versioned server relational-erasure
implementation or narrow QA to the supported non-destructive lifecycle.
Do not merge PR #313 as a full-lifecycle PASS,
set the new card Done, alter Production/Canary, re-enable Local reporting or
make another provider call for parity while this is unresolved.
[Current scoped change record](../NT-Analyzer/docs/changelog/2026-10-01-local-runtime-documentation-canonicalization.md).

## Current beta.106 release handoff (2026-10-01 UTC)

The owner-authorized narrow patch merged through PR #311 to exact `main`
`e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885`.
Canary/Production non-daily periodic generation now reads the one active
general owner Persona model through the existing PostgreSQL Agent World store,
ServerSecrets, universal provider client, workspace budget and usage ledger.
Daily remains deterministic and Development/Local retains the legacy route.
No secret, permission, schema, provider, feature, sender or schedule is added.
Python compilation, 8 focused tests and 336 related regression tests PASS. A
full collection recorded 6,131 PASS/140 skipped plus 13 expected isolation
failures caused by a repository-local temporary root; the complete affected
subset passed 91/91 with an external temporary root.
Final-main CI 36857075970 PASS. Immutable artifact
`art_7aebf504ae354ce7981c58359a1ff546` passed Canary and is Production live as
deployment `dep_bf86528c36c944d1a5906f0586126b93`; public `/live` and `/ready`
match exact beta.106 identity. The existing owner-authenticated browser session
submitted exactly one accepted event per Weekly, Monthly and Quarterly type via
the shipped CSRF-protected application API. Each completed with one real Gemini
provider response, durable usage/report, corresponding SF Chat message and
Telegram outbox `sent` with attempts=1. Stable report keys and matching message
and outbox dedupe hashes establish one delivery per acceptance request. Daily
and control audit had prior Production PASS on the unchanged route. Post-check
Production `/live` and `/ready` are 200; one Production coordinator lease is
active, Canary remains non-sender and Local `StratForge Vitek` is Disabled.
The product card is Done; Release Center's terminal state is `production_live`
with verification PASS (there is no separate `completed` state).
[Change record](../NT-Analyzer/docs/changelog/2026-10-01-beta106-periodic-owner-model-route.md).

Historical pre-acceptance note: the initial browser attempt did not submit an
event. A raw POST without the CSRF token returned 403 and created no job. The
subsequent sanctioned `window.API.http.vitekEvent` client used the real owner
session and CSRF protection; no new runtime control or beta iteration was needed.

## Historical release/program checkpoints — not the current handoff

All following beta.105-and-earlier sections retain original evidence and
then-current decisions only. They do not override the task and beta.106
snapshot above; older headings saying “current” refer to their own date.

### Historical beta.105 handoff (2026-10-01 UTC; superseded by beta.106)

PR #309 merged to `main` SHA `91d8a4c1ac25f988b643ff71e119502a1df3d3f7`;
mandatory final-main CI 36790534580 PASS. Exactly one signed immutable
beta.105 artifact `art_dda57f0beab14b83a3375d6ecff1caa8` (archive SHA256
`2D1DD117E550A5DAD9EB07951DE938AD60BCD44B0F1E4994C258CD9DBAFF482F`,
manifest/runtime SHA256
`0BE1FDFD05880F589F8CA36EFEFDB24719A44E57379E825AD662D31614DBFDF9`)
passed focused Canary and was promoted unchanged after verified Production
backup. Canary and Production point to the same release directory; Production
`previous` is beta.104. Real Professional shared Gemini POST completed without
524, once through worker and SF Chat delivery, with a genuine durable receipt,
26/3 tokens, cost and caller/owner audit. One post-share-off foreign request
was denied before job/provider/usage; `/live` and `/ready` 200. No full-package
retest was performed. PR #307 preserves the prior Canary PARTIAL/PASS history
and is already merged as evidence, not runtime code.

Reporting cutover: Production's one active coordinator lease produced
`backtest-audit:2026-09-30` once: SF Chat message `MSG-72C68BD8C118`, Telegram
outbox `tgo_902fca40f5f647259c1773c4d61d0848` sent on attempt 1. Local
`StratForge Vitek` task and Telegram notification gate are OFF, and Canary is
non-sender; all histories are preserved. The owner then explicitly accepted
possible repeat reports and authorized same-day activation. The delayed
watcher was stopped with no successor. All four Production schedule settings
were enabled from their verified backup boundary. `daily:2026-09-30` was
delivered once (SF Chat `MSG-9E555D9F4351`, Telegram outbox
`tgo_b07fe747dbe44116ab05b01f2482566c`, sent attempt 1). Monthly and
quarterly failed after three bounded claims before provider dispatch:
`agent_router` has zero registered/enabled legacy models on Linux, where its
DPAPI-only secret store is unavailable, and the new server owner-model store
is not connected to this periodic route. Full reporting remains PARTIAL; do
not close the product card as Done or attempt DB/secret bypasses. The next
step needs a narrow authorized code iteration and real Canary/Production
acceptance for weekly/monthly/quarterly, while beta.105 remains immutable.
Protected settings backups and beta.104 previous slot are the rollback
boundary. The ordinary-user Telegram path #296, backup role without
`BYPASSRLS`, and noncritical UI remain separate next work; Cloudflare
Web Analytics/CSP is post-release only. [Current release record](../NT-Analyzer/docs/changelog/2026-09-30-beta105-production-model-completion.md).

## Historical beta.104 handoff (2026-09-30)

Production beta.103 is live/ready on schema 24 with Production-specific model secrets readable by API and worker. Exact owner/non-owner Agent World workspace admission was corrected with backed-up Production config. The remaining real blocker is authenticated AI Center model/overview latency and intermittent Cloudflare 524. Isolated read-only timing of the exact Production code found hundreds of recursive authority checks and about 1,500 PostgreSQL connections per overview, versus fast anonymous 401; no provider dispatch occurred. A narrow beta.104 Development fix reuses authority within one read-only HTTP projection and performs fresh fail-closed revalidation before response. Focused tests PASS; PR, final-main CI, immutable artifact, Canary and Production remain PENDING. After focused Canary PASS, promote the same artifact and finish the agreed one-call Professional shared-model Production smoke, then reporting cutover and closeout. Scheduler OFF, Local `StratForge Vitek` ON. [Evidence and gates](../NT-Analyzer/docs/changelog/2026-09-30-beta104-ai-center-read-timeout.md).

## Historical beta.103 pre-promotion handoff (2026-09-30)

**Production promotion remains STOPPED.** The initial Production backup helper failure was traced to on-host Cloudflare HTTP 403 `1010`, not an API startup defect. A corrected ignored helper eventually passed a new complete quiesced backup gate at `backups/pre-beta103-production-peer-20260930T043957Z` (manifest SHA256 `34EAF4F0314CF5D4653919A2F892369EBF0708A4BDF831B3FC12EF57148B1FF2`, dump/runtime verified, all four services RUNNING, direct and off-host `/live`/`ready` 200 on beta.99); two earlier failed snapshots remain historical. Backed-up Production worker secret-dir config, additive schema 24, separate Production encryption key and trusted Local-to-Production import of the same five owner models then passed. Read-only beta.103 code under the actual Production API and worker process environments decrypted one owner secret without dispatch. However active beta.99 subsequently returned `/ready` HTTP 503 `database_migration_pending` because its code requires schema 23 while the owner-required pre-promotion import needs schema 24; `/live` stayed 200 on beta.99. No promotion, Production provider call, scheduler cutover or destructive rollback was performed. Preserve the imported data and backups; the owner was asked to choose a data-safe targeted rollback or explicitly allow exact-artifact promotion through this transitional old-code readiness mismatch. [Full bounded preflight evidence](../NT-Analyzer/docs/changelog/2026-09-29-beta103-server-agent-world-queue.md).

Production promotion of exact artifact `art_9d38fcd7bd33454786fdbfaf0e9cc25a` was conditionally authorized, but **stopped at the backup gate before any config/import/promotion**. Quiesced beta.99 backup `backups/pre-beta103-production-peer-20260930T041641Z` has verified dump/runtime/manifest hashes; its helper exited 2 because the host-local post-restart HTTP probe returned `HTTPError`. Independent public `/live` and `/ready` both returned 200 on unchanged beta.99 afterward. Under the owner's fail-closed rule, the backup gate is not accepted; Production encryption key, owner-model import and worker wrapper remain untouched. Production scheduler OFF, Local `StratForge Vitek` ON. Resume only after the backup health-probe gate is resolved and remaining Production-specific prerequisites pass. [Exact preflight receipt](../NT-Analyzer/docs/changelog/2026-09-29-beta103-server-agent-world-queue.md).

PR #306 is merged to final `main` SHA `d695a8ddc5dccfc1252f0e94d59bb4e5325bc601`. All five required PR checks PASS, including a rerun of the same Windows job/head after an unrelated transient loopback socket failure. Mandatory final-main CI [36651073820](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36651073820) PASS. Exactly one signed immutable beta.103 artifact `art_9d38fcd7bd33454786fdbfaf0e9cc25a` exists, build `sf-0.10.0-beta.103-d695a8ddc5dc-20260930T013703Z`, archive SHA256 `7DB016ACD5E4CA96F02C8057778C1EDFD1E12702674E8642A71CBA764478A7EB`, manifest/runtime SHA256 `0F440F977D0B3C55A7D546AA330DE42DCEBB7772CB56BE957A95D69E9FB05154`, signature verified. Verified Canary backup `backups/pre-beta103-canary-peer-20260930T013728Z` (manifest `107F25C19DE782A58724A1851207CA8300933FA1444423DA14B1AB26007CC190`) preserves DB/runtime/config and beta.102 rollback. The exact artifact was deployed as `dep_d7084bd26b5341fabccfce5b41d750fe`, state `canary_checking`; public `/live` and `/ready` PASS on beta.103 source/runtime identity. Production remains beta.99; scheduler OFF, Local `StratForge Vitek` ON. [Change record](../NT-Analyzer/docs/changelog/2026-09-29-beta103-server-agent-world-queue.md).

**Current focused Canary acceptance: PASS.** Read-only tracing of the original failed task `9edf9bc0-891b-57d9-b689-d34b79f10842` established that the Canary worker lacked `STRATFORGE_SECRETS_DIR`; `model_secure_storage_unavailable` was masked as `model_provider_error` before outbound provider dispatch. The original wrapper was backed up with verified original SHA256 `C3C8FE0C875ABF6CF572813DDBDCB2325E0F28023F8F615D91774CB033555FD2`; Canary-only export and worker restart produced wrapper SHA256 `B7299A932EAC5A9810F3F4032494E7D02A0A4A0D9FC5AB57A141F349F4CB62FD`. Actual worker environment read the same owner secret as the API. One new authenticated Professional task `854edfb0-cc97-5a5e-82a1-10f664e40566` ran once via PostgreSQL worker and got genuine Gemini response plus durable receipt, 57/33 tokens, $0.00, matching `sf_ai_usage_events` request ID and owner/caller usage audit. Owner Edge switched sharing off; exactly one new foreign Chrome request was denied before job/provider dispatch, with no new usage or lost history. The Gemini share remains off; re-enabling requires an owner access decision. Post-check `/live` and `/ready` HTTP 200 with beta.103 SHA/artifact identity. Local Release Center `rc_58652a4181e3497ca53003bacace24da` now records `canary_passed`, check `chk_0002fdbe50e44a9aa99823951f195369`, verification PASS, after a protected ledger backup. No application-code or artifact rebuild, no full-package retest. The earlier HTTP 524 overview did not block the required path and is not expanded in this acceptance. Production remains beta.99, scheduler OFF, Local `StratForge Vitek` ON. Read-only Production audit found its worker also lacks the secret-dir configuration (API has it); backed-up Production config correction plus Production-specific encrypted owner-model import are mandatory after separate artifact-specific approval. [Detailed receipt](../NT-Analyzer/docs/changelog/2026-09-29-beta103-server-agent-world-queue.md).

Historical first beta.103 Canary **PARTIAL / FAIL**: after fresh owner authorization, Edge assigned the same real non-owner Canary user ID `8798656225084765` a one-day Pro grant; Chrome showed two permitted owner Gemini connections. The older ambiguous beta.102 task `68623761-57ca-5694-af1b-c41471f5fad6` remained `ready` without a PostgreSQL job. One bounded task `9edf9bc0-891b-57d9-b689-d34b79f10842` entered `interactive_ai`, ran once and reached queue `succeeded`, but the domain task ended `failed / model_provider_error` without provider receipt/usage. A separate AI Center `/overview` HTTP 524 was observed. At that checkpoint no retry/share-off or Production approval occurred; the subsequent diagnosis and PASS above supersede only its Canary verdict. [Original PARTIAL and follow-up evidence](../NT-Analyzer/docs/changelog/2026-09-29-beta103-server-agent-world-queue.md).

### Historical beta.102 Canary PARTIAL handoff

beta.102 release checkpoint: owner-authorized PR #305 passed all five head checks and merged at 2026-09-29T18:44:02Z into exact `main` SHA `244d67805445571dda1aa1ec9d8c7f89f5923922`. Mandatory final-main CI [36614172579](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36614172579) PASS. Exactly one signed immutable artifact `art_96bbd72be42744389b7876792a66aaf8`, build `sf-0.10.0-beta.102-244d67805445-20260929T194554Z`, archive SHA256 `57C0CDADBE46172C0014F9AD50A69AF6FEA15BFE8204FF30269AD34A4952AC94`, manifest/runtime SHA256 `15A385A9ABE8222FD097373282DED2ED30AB694893C448678740DA90D3513F77`. Verified backup `backups/pre-beta102-canary-peer-20260929T194605Z` (manifest `4782211E2E7D1AB2CBA277DC999EDC6349B6D03D6B44831BA5A2106FF5EBB032`) retains DB/runtime/config/secrets and beta.101 rollback. Canary deployment `dep_2320924563b544ecab4ffa22d9225a41` is `canary_checking`; public `/live` and `/ready` identity PASS. Remaining owner browser/post-restart provider, real non-owner shared invocation, usage/cost/audit, share-off and isolation checks are still pending. Production beta.99, scheduler OFF, Local `StratForge Vitek` ON. [Release record](../NT-Analyzer/docs/changelog/2026-09-29-beta102-migrated-model-projection.md).

beta.102 Canary acceptance is **PARTIAL**: owner “Мои модели” projection and all four active post-restart provider tests PASS; retired GLM is history and a valid new task is denied `model_connection_inactive`. The real non-owner Professional sees the two shared Gemini connections but its first real AI Center `json_arithmetic` task returned HTTP 500. No retry was sent. Sanitized server stack identifies the server PostgreSQL queue refusing `agent_world_model` because the kind is absent from `production_workers.KIND_WORKER_CLASS`; the local worker handler already exists. A narrow beta.103 technical iteration of the same open product card must register the three existing scoped Agent World kinds with the interactive server worker and retest after a new PR/main CI/signed artifact/Canary. **Do not request Production approval or promote beta.102.** [Canary evidence](../NT-Analyzer/docs/changelog/2026-09-29-beta102-migrated-model-projection.md).

Read-only scoped check after the ambiguous 500: the second user's Task `68623761-57ca-5694-af1b-c41471f5fad6` is `ready` with no matching PostgreSQL queue job, so no provider dispatch occurred. Do not replay or delete it on beta.102; preserve the browser form's stable idempotency key if possible for a later safe retry on a newly accepted artifact.

Historical beta.103 Development source [PR #306](https://github.com/OMNOM-111/NT-Analyzer/pull/306), branch `codex/beta103-agent-world-production-queue`, changed only the existing server worker-kind allowlist and its regression tests; `VERSION.json` advanced because beta.102 artifact was immutable. The owner-authorized merge, final-main CI, signed beta.103 artifact and Canary deployment are recorded in the current checkpoint above. [Technical change record](../NT-Analyzer/docs/changelog/2026-09-29-beta103-server-agent-world-queue.md).

Historical beta.101/102 owner UI finding: all five imported `ProviderAccount → Model` connections had server-decryptable keys; the separate owner Lab registry was empty, so AI Center incorrectly rendered “Мои модели” empty and classified them as additional. All four active connections passed real provider tests with persisted cost and `provider_verified`; an ordinary DeepSeek invocation also succeeded. The fifth GLM record was retired and intentionally non-callable. No key re-entry or duplicate connection. The owner's empty inbound-shared list was expected; two outbound Gemini shares existed before the focused beta.103 share-off test. Technical beta.102 was the narrow UI projection fix, not a rebuilt beta.101. This historical checkpoint did not establish full Canary PASS; the later focused beta.103 result above does. [Diagnosis and exact mapping](../NT-Analyzer/docs/changelog/2026-09-29-beta102-migrated-model-projection.md).

The owner kept one frozen Local beta.95 → beta.96 product package approved 7/7; beta.101 is its technical release iteration. PR #303 was owner-authorized and merged to final `main` SHA `58fbb23d1551e267dd7fe622c2414580820f3f8c`; mandatory CI [36526068091](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36526068091) PASS. Exactly one signed immutable artifact `art_ed57f7076b6b46b78cc3309c55470016`, build `sf-0.10.0-beta.101-58fbb23d1551-20260929T063217Z`, archive SHA256 `E493DCE15A7B59AD1E4412046003754F29CA1A8492C5B317813374DAC565AFFE`, manifest/runtime SHA256 `99795E581E84C1CC4C2D42A233F8E337EA4ABB9267A15BF42353B1D963E87496` was deployed to Canary (`dep_45db3f6c48c549ad978b0f9a3e895501`, `canary_checking`) only after verified DB/runtime/config/secret backup `backups/pre-beta101-canary-peer-20260929T063236Z` (manifest SHA256 `C90F4A17F98F25BA386B04A1DF06B6E34B98C23BAE5549D7E4F4533586D659B3`); beta.100 is the immediate rollback slot. Public `/live` and `/ready` and Linux `ServerSecrets` without DPAPI PASS. The trusted Windows Local process transferred the original five owner models through pinned SSH stdin to Canary server re-encryption, migration `caea5f06-d5e6-5625-ab08-db5e6c944fcc`; no plaintext was persisted/output. Read-only real non-owner PostgreSQL/RLS probe now confirms two secret-free shared descriptors and no access to an owner model/key; the owner model-detail DTO contains no plaintext. Real owner direct BYOK, live provider test, non-owner shared invocation/ledger, creation and isolation of a second-user private model, share-off, restart persistence and frozen-package full Canary smoke are still PENDING. Do not call this Canary PASS or request Production approval yet. Production beta.99, scheduler OFF and Local `StratForge Vitek` ON are unchanged. [beta.101 record](../NT-Analyzer/docs/changelog/2026-09-28-beta101-server-secret-migration.md).

## Previous beta.100 checkpoint (historical Canary PARTIAL; immediate rollback slot)

At this beta.100 checkpoint the single owner-approved (7/7) product card was
labeled `0.10.0-beta.100`, originating in Local beta.95 → beta.96. beta.97–beta.100
are technical server iterations inside that still-open card; beta.101 now continues it.
Source `7b66bcb6abd486891870b0419afd93f8828dbb85`
passed final-main CI and produced signed immutable artifact
`art_de49135714cf48b6aace2a977fad334f`. It is deployed only to Canary;
Production still runs beta.99. The owner approved a one-day Canary Pro grant
for the separate Google user `8798656225084765`; the owner UI issued it and
the refreshed Chrome session opened AI Center. Canary Models shows no shared
model. Existing Local owner model/registry bindings depend on Windows DPAPI;
beta.100 server execution requires protected owner-scoped PostgreSQL/RLS vault
credentials. Copying metadata or ciphertext cannot make them callable. No
provider secret was transferred; real connection test, non-owner invocation
and full Canary parity are NOT PASS. Preserve the beta.100 artifact and backup,
leave Production unchanged, and implement only a scoped, tested secure
migration/re-encryption plus server binding path in the next technical source
iteration before repeating Canary acceptance. The reported promo-code failure
is for this same user but lacks a reproduced original request/result; do not
change redemption logic or claim a cause from the currently unrestricted,
unused voucher inventory alone. Production scheduler OFF; Local `StratForge
Vitek` ON. [Exact record](../NT-Analyzer/docs/changelog/2026-09-28-beta100-server-parity-release.md).

- Owner decision (2026-09-27 America/Los_Angeles): all seven Local beta.96 package tasks are explicitly approved as one frozen product package, `ownerApproval=approved` 7/7. Do not request another Local acceptance. The single remaining server-parity blocker is authenticated Agent World/AI Center plus a real non-owner shared-model invocation; see [decision and read-only probe](../NT-Analyzer/docs/changelog/2026-09-28-beta96-owner-decision-server-parity.md). A real separate Canary Professional user displayed live MBT TopstepX candles; server Preview sandbox being disabled is expected, not a chart blocker.
- Active beta.100 technical iteration inside the open product card: PR #300 merged with owner permission to `main` SHA `c36a84bf528c63e511fac6714e83417e48ffa68c`. PR #301 corrected only release identity and handoff; all five checks passed on final PR head, and the owner-authorized merge produced exact final source SHA `7b66bcb6abd486891870b0419afd93f8828dbb85`. Mandatory `main` CI [run 36471503031](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36471503031) passed on rerun attempt 2 after one reproduced intermittent Windows loopback test abort on attempt 1. From the clean exact SHA, Release Center built and signed one immutable beta.100 artifact `art_de49135714cf48b6aace2a977fad334f`, build `sf-0.10.0-beta.100-7b66bcb6abd4-20260928T210349Z`, archive SHA256 `2CCB46F376C4A6445295D7221BB753B959F08FBE1970065996AF7460C6CB4DB1`, manifest/runtime SHA256 `5FFE722FD86DE9892E7C150287C63CC3C8D3388DADD61AF3BA756C0A446812FF`; candidate `rc_2aab86a85ef84ca7ad1e6733aebdbefb` is `canary_checking`. Verified pre-change backup `backups/pre-beta100-canary-peer-20260928T210636Z` (manifest SHA256 `7B8EB4C484A7BF6CD580B310460D52E752DE386C7450207697F3BEF82E7EEEDF`) preserves DB/runtime/config/secrets and beta.99 rollback target. Canary deployment `dep_7cb0afa2c3ee48d9b0c3956bc8dbb15f` runs beta.100; `/live` and `/ready` PASS, migration 0024 applied, previous slot beta.99. An isolated TLS PostgreSQL database with non-`BYPASSRLS` app role passed 74/74 tests, including separate-principal share/key/usage isolation. The [beta.100 technical release record](../NT-Analyzer/docs/changelog/2026-09-28-beta100-server-parity-release.md) retains source and gates. Server workspace opt-in is ON only for the confirmed owner and separate Google workspace; a fresh Canary-only protected infrastructure encryption key is installed. No provider BYOK key was copied from Local. The non-owner's former five-hour trial-expired overlay was resolved by an owner-approved one-day Canary Pro grant, not by changing role or bypassing entitlement. The Models tab shows no shared models; full Canary parity and real shared-model invocation remain blocked by the missing secure Local-to-server migration/binding path. Production remains beta.99 and periodic reports remain OFF; Local `StratForge Vitek` stays ON.
- Historical Production beta.99 identity detail: archive SHA256 `BD6FDEC99112154E9B0B4FBA26A2F1E257399D9B8FC15BC4500E1BD65AEBDC43`; runtime artifact SHA256 `081C9A99480C49BFBC13C29EA061E994B8310FB6A82EE431B31A38661952A2FB`.

Current product line: Local beta.95 → beta.96 is the single open product card;
beta.97 is its first server release, beta.98 is its reload-loop hotfix and
beta.99 is its server entitlement-storage correction. They are exact technical
iterations inside beta.96, not separate product milestones. Do not rename or
collapse their SHA/artifact history. The
[chronology record](../NT-Analyzer/docs/changelog/2026-09-27-beta96-beta98-timeline-reconciliation.md)
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
record](../NT-Analyzer/docs/changelog/2026-09-27-beta98-production-reload-loop-hotfix.md) and
[storage blocker](../NT-Analyzer/docs/changelog/2026-09-27-canary-professional-registration-storage-blocker.md).

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
[beta.97 Telegram/report candidate](../NT-Analyzer/docs/changelog/2026-09-26-beta97-telegram-report-cutover-release-candidate.md).

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
[beta.99 record](../NT-Analyzer/docs/changelog/2026-09-27-beta99-canary-entitlement-storage-routing.md).

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
[beta.96 product-card parity and status contract](../NT-Analyzer/docs/changelog/2026-09-27-beta96-product-card-parity-and-status-contract.md).

Checkpoint `f455043f`, draft PR #294: full Local regression **6087 passed / 134
skipped / 0 failed** in 1:07:38. The exact 650-file pre-release bundle, context
validator, timeline JavaScript syntax and diff checks PASS. Static, bridge and
Ubuntu PR checks PASS; Windows and full `python-tests` remain pending at this
checkpoint. Merge and environment release gates are unchanged.

Scoped Local work completed: **BETA** — [Preview parity/account lifecycle](../NT-Analyzer/docs/changelog/2026-09-23-preview-parity-account-lifecycle.md). Historical DEMO acceptance is superseded by the current live-mirror contract below. Ordinary registration permissions; public surfaces shared, private data isolated. Fresh Preview/owner browser walkthrough, deletion/reset/exit receipts and full regression PASS. Test containers removed; owner access snapshot unchanged. Owner review and remote CI remain separate. No server/Canary/Production work authorized.
- Local source verified SHA: 56945ac68e94cb7ffa031ef2312dec5a9ad80a54 (canonical live mirror; 6080 passed / 134 skipped across 293 files after complete affected-module reruns; full Preview/owner walkthrough plus final chart-lifetime follow-up; browser-tool interruption/recovery documented in the canonical receipt)
- Local verification UTC: 2026-09-24T04:08:00Z; pack-wide deployment anchor above remains historical, not a claim of new Production verification
- Historical UI correction: [SF Chat dialog receipt](../NT-Analyzer/docs/changelog/2026-09-05-sf-chat-app-dialogs.md); existing backend/data/flags unchanged, no release
- Historical protected Local program snapshot: [integrated review record](../NT-Analyzer/docs/changelog/2026-09-05-agent-world-program-review.md) — clean 2b6d0112 was active; genuine report/PNG observations, real fact handoff and deduplicated manual SF Chat delivery verified; 4235/44 skipped full suite, 542-file bundles and CI 33984524477 3/3 PASS. New unified-source evidence is separate below; full-program/owner acceptance remains open.
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Protected Local branch snapshot: `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282) above foundation PR #281 and integration PR #280; the active final branch is identified below, while #285 is an accepted integration input
- Historical Local origin: `0.10.0-beta.96`, source `56945ac6` on Local 8765. It was not itself promoted; beta.97 was the later server release of the evolving package and beta.98 is the subsequent hotfix.
- Integration state: scoped model/domain/Chat/NT/Desktop, real fact handoff, manual discussion, separate application observations, Consensus and Court verified; owner-dependent and full-program work remain
- Historical 2026-09-24 snapshot: Production was then beta.92. The current technical runtime is beta.99 on Canary and Production as recorded at the top; the earlier snapshot is retained only as history. See [timeline audit](../NT-Analyzer/docs/changelog/2026-09-24-timeline-source-audit.md).
- The root [`timeline.html`](../timeline.html) is the owner-facing handoff. Read it, the [mandatory workflow](../NT-Analyzer/docs/TIMELINE_MAINTENANCE.md) and this current handoff before development, merge or release. Update the same open product card until verified Production closeout; a merely live technical artifact does not create a new product milestone. After the card legitimately reaches `Done`, new functionality starts the next version/card. A version must have source/commit plus Development/CI evidence before artifact/Canary/Production. All current/future cards use `Done / In progress / Ready for owner review / Planned` and retain separate Development / Local test / Owner / Canary / Production stages.
- 2026-09-25 prepublication Local QA: 430 focused tests PASS; live owner MES/MNQ 12-26 and disposable Preview MBT 09-26 charts painted TopstepX/WS; checked Social/Chat/Agent World screens opened without console errors; 646-file bundle 4/4 PASS. With owner authorization, Preview registration, terms and first-device trust completed; a fresh Preview user received an SF Chat AI reply via an owner-shared model. A separate real Development user sent a private message to the owner; the owner saw it and sent a reply; the disposable user and conversation were self-deleted. The receiving side of that reply was not separately checked. A stale Preview bridge expires after 1800 seconds and breaks Social/Chat reads until a fresh launch. Permanent Social comment was blocked by automated action review, so no public write is claimed. Agent World still has the partial items in its master status, and the UI's chart task example says `MNQ 09-26` while the active chart is `MNQ 12-26`. The timeline shows a separate ✓ for checked internals and retains the overall ! and owner-approval gate. [Exact QA record](../NT-Analyzer/docs/changelog/2026-09-25-prepublication-local-qa.md).
- Scope: Agent World integrated Local implementation and pending full owner acceptance; Production deployment facts are inherited evidence
- Status: IN DEVELOPMENT

Current follow-up: **BETA** — [Local TopStep mirror and Preview corrections](../NT-Analyzer/docs/changelog/2026-09-24-local-preview-social-followup.md). The latest owner-approved contract is personal NinjaTrader first, otherwise common live TopStep mirror for active chart-capable trial/subscription users, including disposable Preview. No DEMO fallback. Legacy source flags do not gate end-user mirror admission. Social/avatar, sharing labels, shared-model revoke and one-click owner-session return passed the fresh Preview/owner walkthrough on clean 003e00d1. Charts follow the active disposable process rather than the paid-model 30-minute limit; final regression is 6080 PASS / 134 skipped across 293 files. Final runtime 56945ac6 retains active Preview charts beyond the AI-call time budget. The last browser-control interruption and canonical disposable cleanup are documented in the receipt; no owner session was replaced. Local only; no Server/Canary/Production changes.

Local chart recovery (2026-09-23), branch `codex/fix-local-chart-gateway`: the supervisor origin correction is preserved in the 0a9bcf09 baseline and subsequent Local UX checkpoint; owner Desktop TopstepX charts were verified. The separate chart PR keeps its own closeout. Preserve TopstepX/SignalR and entitlement gates. Saved MBT 08-26 and the empty MNQ probe remain separate contract/provider observations. [Canonical incident](../NT-Analyzer/docs/changelog/2026-09-23-local-chart-gateway.md).

- Isolated memory handoff (2026-09-21): `codex/unified-memory-service` adds the
  common read facade, context builder, stable identifiers, typed graph records,
  reconciliation and reversible write routing described in
  [ADR-0013](../NT-Analyzer/docs/adr/0013-unified-agent-world-memory.md). All new flags are OFF;
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
  See [correction receipt](../NT-Analyzer/docs/changelog/2026-09-14-agent-world-historical-acceptance.md).
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
  Use [OWNER_ACCEPTANCE_GUIDE.md](../NT-Analyzer/docs/current/OWNER_ACCEPTANCE_GUIDE.md), not its
  deprecated historical Agent World guide. Exact receipt:
  [final integration record](../NT-Analyzer/docs/changelog/2026-09-12-agent-world-final-integration.md).
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
  acceptance. See [master status](../NT-Analyzer/docs/current/AGENT_WORLD_MASTER_STATUS.md).
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
  [master parallel handoff](../NT-Analyzer/docs/current/AGENT_WORLD_MASTER_STATUS.md) and
  [P1-5 change record](../NT-Analyzer/docs/changelog/2026-09-10-external-agent-onboarding.md).
- Historical saved/pushed executable source (superseded by the integration above):
  **`e45b64b0121014c5d796553ae8b512d98a5782ae`**, task branch
  `codex/agent-world-unified-acceptance`, draft PR #285. Clean immutable full
  **5416 PASS / 119 SKIP / 0 FAIL / 0 ERROR**, 5834.82 s; legacy **13/13 PASS**.
  At preservation, 329 focused, root static/context and 593-file bundle PASS.
  Fresh separate PostgreSQL receipts: **69 AW PASS**, **41 legacy PASS**,
  **7 Persona identity PASS**, actual API/worker/SQL/replay/restart/RLS **PASS**
  with TLS/NOBYPASSRLS on a new disposable cluster. The generic full skips
  remain 68 AW PG + 7 Persona PG + 41 legacy PG + 3 platform cases.
  [Exact e45 hashes and receipts](../NT-Analyzer/docs/changelog/2026-09-09-agent-world-e45-verification.md).
  The inspected PR check rollup was empty, not CI PASS.
- New delta after e45: Persona selection is retained in Execution V2 approved
  identity reconstruction after a browser-reproduced
  `execution_v2_approved_scope_changed`. Read-only live refresh and narrow table
  wrapping are being corrected after completed Work/stale header observations.
  Late interaction/page/focus preservation, bounded Chat error details and inert
  closed drawers are in the [continuity delta](../NT-Analyzer/docs/changelog/2026-09-10-agent-world-state-continuity.md).
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
  [owner browser route](../NT-Analyzer/docs/current/AGENT_WORLD_OWNER_ACCEPTANCE_GUIDE.md), then
  remaining non-overlapping integrated gates; completed e45 tests are not missing
  work. Owner key/real consent/specific permanent publication/design remain
  distinct holds. Protected 8765 is not switched, restarted or migrated.
- Historical checkpoint: `376b400dc3c8ab3a008f1e45800d401dd02c4b6f`,
  588-file bundle/static/context PASS. Immutable full: 5262 PASS / 1 FAIL /
  112 SKIP; legacy 13/13 PASS. Later bounded Persona chat/transport changes and
  the stale cancel-command fixture correction are separate from that snapshot.
  [Next checkpoint](../NT-Analyzer/docs/changelog/2026-09-08-agent-world-persona-chat-checkpoint.md)
  adds main/alias/UUID selection and receipt-only assistant responses, no
  professional score or model/tool authority. Its later full/PG are e45 above;
  the old failed 376 result is not relabelled.
  [Exact 376 PG evidence](../NT-Analyzer/docs/changelog/2026-09-08-agent-world-postgres-376-acceptance.md):
  69 AW + 41 legacy PASS, separate TLS/NOBYPASSRLS API/worker/restart PASS;
  seven later Persona PG cases are separate e45 evidence. Isolated 8804 used
  clean376 before e45; protected8765 unchanged.
- Historical shared checkpoint: `a03ec82b686a9f6f05c056fe5a500ecbdb3babac`, pushed to PR #285,
  clean at preservation; mandatory static/context/artifact checks passed.
  Subsequent scoped work covers canonical Connector result binding, rejected
  origin correction, Persona voice in saved SF Chat messages and preservation
  of the speaking Persona across Router executor changes. See the
  [boundary record](../NT-Analyzer/docs/changelog/2026-09-08-agent-world-trusted-report-boundary.md).
  Detached exact-a03 full: 5124 PASS / 12 FAIL / 112 SKIP; legacy 13/13 PASS.
  Skips separate 68 Agent World PostgreSQL, 41 legacy PostgreSQL and 3 platform
  cases. Later fixes preserve scoped provenance/isolation assertions; final
  integrated full/browser remains pending. The
  [Chat review boundary](../NT-Analyzer/docs/changelog/2026-09-08-agent-world-chat-review-boundary.md)
  prevents timer/message stars from accepting a Task; the
  [Router identity contract](../NT-Analyzer/docs/changelog/2026-09-08-agent-world-router-persona-preservation.md)
  preserves speaking Persona separately from executor. No flag/Local/Production
  activation occurred.
- Historical preserved core: `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`, draft
  PR #285 on `codex/agent-world-unified-acceptance`. The subsequent shared
  API/worker/Chat/UI delta and remaining gates are in the
  [shared checkpoint](../NT-Analyzer/docs/changelog/2026-09-08-agent-world-shared-integration-checkpoint.md)
  and single [program matrix](../NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).
  New isolated PostgreSQL evidence is 69 Agent World
  plus 41 legacy PASS and separately hash-bound API/worker/restart/RLS acceptance,
  not a new full-regression PASS. See the
  [takeover record](../NT-Analyzer/docs/changelog/2026-09-08-agent-world-integration-takeover.md).
  Local 8765 and original worktrees are unchanged; localhost:8804 is isolated QA.
- Historical independent review snapshot (already included in the unified source): `claude/agent-world-review-and-hardening`,
  local and unpushed, base `45ab4361`, HEAD `c865db2248a12f6927d077dc31efe8b05c02426e`.
  Findings, deliberate non-changes and the exact next operation are in
  [AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md](../NT-Analyzer/docs/current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md)
  with its [change record](../NT-Analyzer/docs/changelog/2026-09-06-agent-world-status-presentation-review.md).
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
[Canonical continuation record](../NT-Analyzer/docs/changelog/2026-09-22-shared-models-local-continuation.md).

## Resume point — 2026-09-09

Continue in `codex/agent-world-unified-acceptance` from saved e45 and its owned
Persona/V2/live-refresh WIP, not from the old mechanisms or review branch.
The combined source `f0bafe8ea46653827bc836afcb2197964390cf08` is an earlier
intake checkpoint, not a request to reconstruct integration.
The [intake manifest](../NT-Analyzer/docs/changelog/2026-09-08-agent-world-integration-takeover.md)
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
operation: [mechanisms WIP record](../NT-Analyzer/docs/changelog/2026-09-06-agent-world-mechanisms-wip.md).

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
Canonical status/evidence: [dialog change record](../NT-Analyzer/docs/changelog/2026-09-05-sf-chat-app-dialogs.md)
and [program status](../NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

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
[canonical status](../NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) and
[integrated changelog](../NT-Analyzer/docs/changelog/2026-09-05-agent-world-integrated-local.md).

## Historical protected-Local implementation checkpoint — 2026-09-05

This preserved section describes the accepted 2b6d0112-era Local scope, not the
new unified source's missing mechanisms or its next operation. Use the active
resume point and canonical program matrix above for current work.

[AGENT_WORLD_IMPLEMENTATION_STATUS.md](../NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
is the canonical current program handoff. It records base/current checkpoint,
file ownership, flag state, tests and skips, rollback and the next safe step.
The task worktree is isolated from the clean active runtime and does not modify
PR #280. Code aa54c294 is committed/pushed with exact-code CI PASS and a separate
operational documentation closeout. The integrated page is ready for visual review,
not only two isolated demonstrations. `LOCAL VISUAL REVIEW AVAILABLE: YES`;
full `OWNER ACCEPTANCE READY: NO`, because the ordinary-user own-key,
real multi-user sharing/revocation and permanent Social scenarios are still open.
Stages 0–13 and final program/release closure are not claimed.

[ADR-0012](../NT-Analyzer/docs/adr/0012-agent-world-integrated-local.md) now defines the integrated
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
[integrated change record](../NT-Analyzer/docs/changelog/2026-09-05-agent-world-integrated-local.md).

The earlier code `fc78677df` full **3369 passed, 44 skipped**, legacy **13/13**,
**517-file** bundle checks and synthetic browser results are preserved in the
[pre-model checkpoint archive](../NT-Analyzer/docs/archive/AGENT_WORLD_PRE_MODEL_CHECKPOINT_486DB834.md).
[ADR-0010](../NT-Analyzer/docs/adr/0010-agent-world-owner-review.md) and
[ADR-0011](../NT-Analyzer/docs/adr/0011-agent-world-real-local-jobs.md) remain historical scope and
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
| Current Git SHA | `e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885` (pack-wide deployed artifact source) |
| Local accepted base SHA | `4ae766ea0c3258a8bb049644ac2afbba6cb89330` |

This task did not access Canary/Production. The last recorded operational
snapshot remains beta.87:
`8f42158661e8247832c90bea8fc4d9f0071e647b`,
build `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`,
artifact `art_9ce9dbcb9a7a4fee9df6a54d40f29806`.
Canary acceptance and same-artifact Production promotion are recorded in
[the canonical beta.87 closeout](../NT-Analyzer/docs/changelog/2026-08-31-beta85-forward-only-promotion.md).
These inherited facts are not a live re-verification or a release of beta.96.

The former isolated PR #270/#278 descriptions, earlier test counts, operational
metrics, and `c9b2883` Preview snapshot are preserved in
[pre-foundation historical context](../NT-Analyzer/docs/archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md).
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

- [Foundation change record](../NT-Analyzer/docs/changelog/2026-09-04-agent-world-foundation.md)
- [Preview closeout](../NT-Analyzer/docs/changelog/2026-09-04-beta96-visual-audit-and-first-device.md)
- [Current status](../NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
- [Exact e45 full and fresh PostgreSQL/runtime receipts](../NT-Analyzer/docs/changelog/2026-09-09-agent-world-e45-verification.md)
- [Integrated Local ADR](../NT-Analyzer/docs/adr/0012-agent-world-integrated-local.md)
- [Integrated change and verification record](../NT-Analyzer/docs/changelog/2026-09-05-agent-world-integrated-local.md)
- [Environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and automation](07_AI_AGENTS_AND_AUTOMATION.md)
- [Market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)

Local new-user follow-up: runtime `0a9bcf09` preserves d9c53860 and checkpoints
fdd40f90, 20ddf9dc, a06db104, 687b7b0d and fc737e96. Manual registration, shared
test/task/Chat, separate owner usage, revoke, isolated Memory, disposable cleanup
and trial page navigation passed. Owner Chat pages 181 saved messages without
large-history rendering timeouts; collapse/reopen and console checks passed on
the actual Local origin. Final native Windows regression passed: 6044 passed / 134 skipped / 0 failures; bundle/context/root-secret checks PASS.
Market-data/trading permissions are unchanged. TopStep strategy tab is IN DEVELOPMENT. Canonical evidence: [new-user Local completion](../NT-Analyzer/docs/changelog/2026-09-23-new-user-local-completion.md).

Local UX follow-up (2026-09-23): model checks now show progress/result inside
an open card, with collapsible diagnostics and no duplicate connection button.
New-user Preview conversations use a scoped Deputy response without creating
Task/review records; explicit text work retains the task lifecycle and usage.
[Change and verification record](../NT-Analyzer/docs/changelog/2026-09-23-model-card-deputy-chat-ux.md).
Manual acceptance, 368 final-code related tests, successful disposable cleanup
and full Windows coverage (6057 passed / 134 skipped; no unresolved failures)
are recorded there. The first sweep found 24 test-port dependency failures;
both affected whole files passed on rerun (66 tests), without runtime changes.
No Canary/Production activation is authorized.
