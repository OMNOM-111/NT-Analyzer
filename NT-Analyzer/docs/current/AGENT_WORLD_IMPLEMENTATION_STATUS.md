# Agent World — implementation status

Canonical program status: `IN DEVELOPMENT`. This is the single current handoff.
The owner authorized continued implementation through an integrated clickable
Local review, not only two E2E demonstrations. `OWNER ACCEPTANCE READY: NO`
until the current delta has completed browser/provider and regression acceptance.
No merge, Canary/Production, real orders or budget increase is authorized.

## Source and Local identity

| Field | Current fact |
| --- | --- |
| Accepted Unified Local | `4ae766ea0c3258a8bb049644ac2afbba6cb89330`, beta.96; open [PR #280](https://github.com/OMNOM-111/NT-Analyzer/pull/280) |
| Foundation dependency | `d5d07ac6817cd10f57d916dab0ce655347a8cbde`; open [PR #281](https://github.com/OMNOM-111/NT-Analyzer/pull/281) |
| Integration branch | `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282), base `codex/agent-world-foundation` |
| Starting checkpoint | `486db834850d465006a3983d2d83ee809202df60`; integrated model/domain delta `ca505d83a25356df5de2fb468f5bc20666a436d5`; delivery/role/workspace checkpoint `34deb827e4ed0e6a29d5693650b575e86e0f33d6` committed, pushed and activated |
| Active Local 8765 | Clean detached runtime checkout `StratForge-worktrees/agent-world-local-runtime`, SHA `34deb827e4ed0e6a29d5693650b575e86e0f33d6`, beta.96 |
| Preserved real state | Original Development data root; actual owner identity/workspace, account/balance/history/configuration and authenticated NinjaTrader preserved |
| Build identity | `dev-0.10.0-beta.96-34deb827e4ed`; rejected-response/rating/calendar follow-up is not yet claimed as active |
| Preview | Separate loopback synthetic child/data/cookies; never the real Local data root |
| Version / release | `0.10.0-beta.96` unchanged; no next beta assigned, merge/deploy/signing not performed |
| Shared numbered migrations | Still 1–22; no new Production/Canary schema migration |

The earlier beta.93 discrepancy was a checkout/launcher mismatch: the scheduled
task served the original dirty `7062f749ee92299356c774d01dc0c7b59cdcbba3` checkout.
It was not the accepted Unified beta.96 code. The explicitly authorized switch
used a clean runtime checkout and retained the original real data root. A normal
development-profile launch would reset data to the code checkout, so the Local
wrapper reapplies the verified data root after loading that profile.

The previous source/test/CI snapshot is preserved in
[the pre-model archive](../archive/AGENT_WORLD_PRE_MODEL_CHECKPOINT_486DB834.md).
Desktop plans/images, historical `c9b2883`, foundation records and
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md) are not erased.
[ADR-0012](../adr/0012-agent-world-integrated-local.md) records the current scope.

## One-page product contract and requirements matrix

Exactly three primary tabs: **Обзор / Работа / Агенты**. All additional domains
open as drawers on the same AI Center page. Existing SF Social and SF Chat retain
their design and stores; compatible `community*` APIs remain unchanged.
The state column uses the owner's acceptance categories, not a percentage.
Automated fixture checks are distinct from actual browser/provider verification.

| Requirement | Where / action | Existing backend and additive adapter | Evidence / current acceptance state |
| --- | --- | --- | --- |
| Safe Local switch | Local 8765, runtime identity/account/status | Existing scheduled task/supervisor; clean code + original data root | **готово и проверено** for initial clean `486db834`: copy/cold backups, SQLite integrity, no active job loss, owner/runtime restored |
| Auth, registration, device permanent/session | Entry, account → Security | Existing account_auth / security_devices | Baseline retained; new read-only worker session checks: 17 PASS. Final browser recheck: **реализовано, но не проверено** |
| Preview registration and Exit | Owner Preview → New User, Reset, Exit | Existing sandbox credentials/state/backend flow | Baseline preserved; new real domain actions fail closed in Preview. Final walkthrough: **реализовано, но не проверено** |
| Persona | Toolbar → Persona; create/edit/activate/suspend | DomainService + immutable Persona profile; explicit application-role association | **готово и проверено**: explicit Tolik backtest / Ivan chart role assignment and exactly two projected personas on 34deb827; retired model history preserved |
| Own models / supported compatible agent | Toolbar → Models; connect/test/task/disconnect | ModelService → existing secret store, universal client and worker | Scoped transport/authority/idempotency tests PASS; ordinary live credentials: **внешний blocker** until a user-owned connection is available; no owner key copying |
| Existing owner connections | Models → bind existing approved connection | Fresh owner/runtime authority, exact existing registry ID/caps | DeepSeek Flash and Gemini Flash **готово и проверено**: real CONNECTION_OK; Z.AI **внешний blocker**: model_endpoint_unavailable; only its new binding retired, original registry preserved |
| SF Chat → model → real backtest | Tolik command with explicit catalog strategy/instrument/period | application_chat → model plan → existing jobqueue/NT → verified source report | **готово и проверено**: model task 62182839, source awnt_7ed6…, 64 trades, -969.70 after commission; five same-chat messages survived 34deb827 restart without duplication, one folded source workflow |
| SF Chat → model → actual Desktop screenshot | Ivan command; open Desktop matching instrument/timeframe | Existing Desktop command queue/canvas/snapshot store | Live Gemini specification rejected correctly; SF Chat failed to report sealed review. Follow-up fixes delivery without approving/retrying the plan. Successful actual PNG capture remains **реализовано, но не проверено** |
| Task Inspector / trace / history | Work row or task card → drawer → SF Chat/evidence | Intent/Task/Contribution/model Execution + application Execution/Outcome/Evaluation | Same-store lineage/idempotency tests PASS; live inspection: **реализовано, но не проверено** |
| Automatic observed rating | Agents → profile/rating | Independent versioned deterministic rubric, distinct-input dedupe | **готово и проверено** per model: DeepSeek and Gemini, n=3 distinct real arithmetic inputs each, 3/3, OBSERVED/low confidence. Not general/trading quality; no routing effect |
| Experiments / comparisons | Toolbar → Experiments → same-input comparison | ModelService + existing worker; separate actual responses | **готово и проверено** on ca505d83: three same-input comparisons, six actual verified model outputs; follow-up display/restart still to recheck |
| Decisions / Consensus / Court | Toolbar → Decisions/Court; proposal, three isolated judges | DomainService + ModelService.judge; sealed packet, immutable votes, 2-of-3 | State/diversity/replay tests PASS; live judges: **реализовано, но не проверено**; verdict never executes work |
| Memory / lessons / sharing | Toolbar → Memory; edit/promote/publish/revoke | Existing private artifacts + active TTL/purpose/source-revision grant | Private create/source binding/promote/read **готово и проверено** in browser on 34deb827. Sharing/revocation have contract PASS, separate multi-user visual acceptance pending |
| Strategy Projects | Toolbar → Projects; definition/version/history | DomainService immutable StrategyProject revisions | Browser create/version/history **готово и проверено** on 34deb827; follow-up records timestamps for new versions, never invents dates for old snapshots |
| Routines / calendar | Toolbar → routines/calendar; propose/accept/manual follow-up | DomainService → existing worker follow-up receipt | Browser creation/explicit acceptance **готово и проверено** on 34deb827. UTC storage correct; local-time display fix under verification. Autonomous scheduling is **не реализовано**; automation stays OFF |
| System | Toolbar → System | Existing runtime/capabilities/registry flags, no secrets | Server/UI checks PASS; browser: **реализовано, но не проверено** |
| SF Social publication | Toolbar → В SF Social; select source → exact preview → explicit permanent confirmation | SocialPublicationService → existing Community store/idempotency | 41 service checks PASS plus HTTP/UI contracts; local publication/browser: **реализовано, но не проверено** |
| Restart / cancel / retry / isolation | Existing Local worker, task status and same conversation | Existing queues/leases/inbox; fresh authority before transmission | Contract tests PASS; live restart: **реализовано, но не проверено** |
| Existing PostgreSQL regression | Disposable loopback test DB only | Existing migrations 1–22 and RLS-enabled app role, TLS | **готово и проверено**: 41 PASS, zero skips, 122.71 s on repeated actual DB run |
| General Router / new Execution Engine / Agent World PostgreSQL adapter | Not switched into runtime | Existing Router/executors remain authorities | **не реализовано** for new replacement systems; no new PG adapter or Production fallback is claimed |
| Full suite / final SHA CI / owner design | Verification and draft PR | Existing test/static/context/bundle/CI gates | 34deb827: 3906 PASS / 44 skips plus Windows/Linux/static CI PASS. Rejected-response/rating follow-up: 3913 PASS / 44 skips; subsequent calendar/version corrections require final rerun. Owner design acceptance separate/pending |

The manual historical job `ui_20260905T003301149Z` (1273 bars, 64 trades) remains
excluded from Agent World statistics. It proves the original executor can return
real reports, not the new chain. The fresh scoped task below supplies distinct
model/chat-chain evidence. Backtesting page redesign remains outside this task.

### Actual model-to-NinjaTrader receipt

The browser SF Chat command requested SampleMACrossOver / MNQ 09-26 / 5m /
2026-08-24 through 2026-08-29, Fast=10, Slow=25. Actual model response:
`deepseek-v4-flash`, 1256 ms, reported cost USD 0.00006776.
Model task `62182839-1c4c-563d-8186-bcef081ec599`, SF Chat `C-1322EA65B646`,
source task `b316f454-662f-5791-9808-322bd00f92f4`, original NT job
`awnt_7ed6b329cead8eac1391f5c8a0f3b59ad6d2d073baca9a6f` all match.
64 actual historical trades, net after commission -969.70, PF 0.725188.
Original `result.json` SHA256:
`202e31d6775e7e08cb3e4300110cc7ec3878f2023ead080944e119db2251bc6f`.
Immutable verified summary artifact `f1dae944-aaed-5afb-bd38-06dd5e362fdc`, SHA256
`7c9e8d550e1f161a81ac59f8139a041f400ccd62f3f4435954be708f839c51be`.
Execution-conformance PASS is not strategy profitability or general model quality.

Actual connection task `b7114186-079b-58be-98dc-e38c552c65d2` returned Gemini
`CONNECTION_OK` at 611 ms. Three browser comparisons used JSON inputs
`[13,-5,22,10]`, `[7,-11,23,9,12]`, `[101,-24,38,7,12,-8]` for both models.
Comparison IDs: `fe17dc14-2944-51c6-b125-7ea3065d7852`,
`c55cf8c8-e31d-5862-a12d-038df10414fe`, `5d749d7b-e4fa-564d-8f69-7626d0cd4333`.
All six outputs independently passed; n=3 per model is only low-confidence
bounded arithmetic evidence. Failed Z.AI connection remains visible in history.

### 34deb827 browser continuation

- Project `9f89fa8d-6018-52f7-aa2c-13982d21385e`: real backtest parameters,
  immutable version 1, revision 2, history reopened in the same drawer.
- Private Memory `58dc952d-16ff-5ea1-a96b-34036bb7f65d`: original verified
  summary artifact, 30-day retention, explicit promotion to active revision 2.
- Manual routine `a590f088-8ac5-59e1-ac62-b44142b66f9d`: accepted revision 2,
  source artifact retained; no automatic model, backtest or order execution.
- Calendar `4901ad4b-d44c-5f28-86c7-5d40543fcd62`: test-only historical interval
  2026-09-05 00:00–00:30 America/Los_Angeles saved as 07:00–07:30 UTC;
  explicit acceptance verified in the list. System drawer confirmed eight
  scoped active flags, Router/Execution V2 and external actions OFF.
- Decision `6fb853a7-cdfd-5739-8623-b1c2c352b2c8`: proposed review of the
  actual negative NT report using the exact verified summary artifact. No
  Court verdict or approval is claimed before three real judge responses.
- Chart model task `4d1d5b2f-61e9-57d6-90fa-cbd0e2cb611d`, conversation
  `C-9D163439293C`: actual Gemini response at 1355 ms wrapped the required JSON
  in another object/code fence. Independent verification FAIL; no chart command
  was sent. The saved failed evaluation is retained, never relabelled PASS.
- Desktop displayed actual cached historical candles with LIVE unavailable,
  then its browser renderer stopped responding. One reload did not recover it;
  repeated control attempts stopped. A separate lightweight AI Center tab works.
  Neither a blank screenshot nor a source timeout counts as chart acceptance.

Current corrective delta: one claimed delivery of sealed rejected responses,
stronger exact-JSON planning instructions (verification remains strict), active
model-only persona rating with retired history retained, local calendar time
display, neutral accepted label and timestamps for new project versions.

## Authority and flags

All ten flags default OFF. Trusted server configuration requires exact
`STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES` entries, Development environment and
fresh user/workspace admission; malformed/wildcard settings fail closed.

| Scope | Enabled flags |
| --- | --- |
| Admitted Development workspace | Read model, UI, task graph, evaluation shadow, memory, consensus, Court, explicit social publishing |
| Controlled synthetic Preview | Read model, UI, task graph, synthetic evaluation only |
| Unconfigured Local / Canary / Production | None |
| Every scope in this checkpoint | Router shadow and Execution V2 remain OFF |

Model/provider identity, Role and Persona remain distinct. Global owner registry
access is never an ordinary-user permission. New private paid connections fail
closed without approved allowances; no budget is raised by connection or testing.
Compatible private transport uses approved HTTPS origins, public IP pinning,
bounded responses and no redirects/hidden retries.

Workers retain only a non-secret session reference and recheck active confirmed
session, owner UUID, membership, capabilities and budget before calls. Expired
trial/budget blocks new work but not existing own history. Read-only members see
only their own records and explicitly published active Memory. Raw provider
secrets and private prompts do not enter public DTOs or social snapshots.

Preview remains credential-free and externally blocked. Its new domain drawers
explain the Local-only boundary instead of calling live providers. Reset/Exit
cannot replace, trim or reseed real Local data.

## Verification checkpoint

- Broad checkpoint before final claim/role/workspace changes: **3852 passed,
  44 skipped**, 622.61 s; not acceptance of subsequent changes.
- Scoped follow-up: **270 passed** (private workspace, application chat, domains,
  gateway, SQLite); **28 delivery** and **18 explicit-role/projection** tests PASS.
  Single claimed delivery jobs recover saved results through the existing
  worker/inbox; no repeat provider call or budget charge.
- Active 34deb827 scoped full rerun: **3906 passed, 44 skipped**, 770.01 s.
  Legacy **13/13 suites**, Python compile, **23 JS files**, root-level secret/
  Markdown/CSP scans, context validator and **533-file bundle** gates PASS.
  Forty-four skipped scenarios are not represented as generic Windows PASS.
- Final corrective full rerun: **3914 passed, 44 skipped**, 759.73 s, XML
  `.artifacts/verification-20260905/full-regression-final-domain-ui-v2.xml`.
  Focused UI/domain **218 PASS**; legacy **13/13**, Python compile, **23 JS**,
  root scan and context validator rerun PASS. Exact staged bundle and new-SHA
  CI remain required before the corrective closeout. The first new UI test
  used an incorrect fixture shape and failed (217 passed/1 failed); the fixture
  was corrected to the real top-level DTO. An early concurrent full run was
  interrupted and is not evidence; the final complete run above supersedes it.
- Actual isolated PostgreSQL rerun: **41 passed**, 122.71 s, zero skipped;
  migrations 1–22, app/admin roles non-superuser and NOBYPASSRLS, TLS.
- Forty-one of the 44 generic Windows skips are the separately executed PG
  cases. The other three are two shell tests and one POSIX permissions test,
  unavailable on this Windows runner; they are not Windows PASS.
- UI/domain/application/service focused evidence is in the
  [integrated change record](../changelog/2026-09-05-agent-world-integrated-local.md)
  and delegated scoped records. Fixture provider tests are not live model tests.
- Exact 34deb827 [CI run 33951941036](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33951941036)
  passed Windows, Ubuntu and static jobs. This does not certify the later delta;
  its exact commit/CI remains a separate gate. Stacked draft PR dependencies
  remain unmerged; main-target mandatory release checks are not inferred.
- Ordinary test registration `aw_model_review_0905` reached final Terms on
  localhost:8765, separate from the owner's 127.0.0.1 cookies. No account has
  been finalized on the owner's behalf. **PENDING OWNER REGISTRATION / KEY**.
  The prepared private-workspace route requires a real confirmed human session,
  creates only that user's container, and grants no NT/key/budget access. Exact
  workspace opt-in is still server-side. OpenRouter / `openrouter/free` is the
  supported test choice; owner types the key into **Ключ подключения** personally.
  Native Gemini is supported for existing owner bindings, not this private wizard.

## Shared-file ownership

| Area | Single writer / review responsibility |
| --- | --- |
| Server, permissions, auth session lease, live/domain/Preview HTTP, model chat, Local launcher and final evidence | Root integration |
| Domain records/service, SQLite read/receipt/grant methods and social publisher | Storage workstream; root integration review |
| Model transport/execution/evaluation/service, application bridge and named-source chart read | Workflows workstream; root integration review |
| AI Center HTML/CSS/JS and gateway/UI/publication contracts | UI workstream; root integration review |
| Canonical status, ADR-0012, integrated changelog, final matrix/Git/CI | Root |
| Market data/chart engine/Connector/jobqueue/trading | No refactor; original authorities retained |
| Auth/devices/SF stores | Preserved regression contracts; only named integration boundaries change |

## Backup, rollback and next safe action

Operator evidence is outside version control in
`.artifacts/local-switch-20260905/`: original scheduled-task XML/runtime identity,
preflight/cold manifests, isolated-copy verifier, Local bootstrap and ROLLBACK.md.
Cold manifest SHA256:
`8de8d943b0dcbd543085f56730551843f2af48c1e8b2ca9b09d6e5f92023fde9`.
No private data, keys, database dump or full task XML is shipped in Git.

Before another Local restart, recheck no active execution and exact owned PID
tree; stop only that scheduled task/server/worker. Update only the clean detached
runtime checkout to the next tested commit. Retain original data and avoid two
queue writers. Code rollback restores the original launcher; full-state rollback
also requires preserving later owner writes before restoring the checked copy.
Never use a Preview root as an owner-data source.

Next action is the final automated/static checkpoint, clean commit and safe Local
activation, then real browser/model/application/domain scenarios and restart
acceptance. This is not permission to stop at another partial handoff.

`IMPLEMENTATION COMPLETE: NO` for the full requested integrated acceptance.
`GIT CLOSEOUT COMPLETE: NO` for the new delta.
`STAGE CLOSED: NO`; owner visual acceptance and release stages remain distinct.
