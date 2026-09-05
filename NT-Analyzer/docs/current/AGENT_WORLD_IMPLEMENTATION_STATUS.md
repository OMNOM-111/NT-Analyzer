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
| Starting checkpoint | `486db834850d465006a3983d2d83ee809202df60`; subsequent integrated model/domain delta is being verified before commit |
| Active Local 8765 | Clean detached runtime checkout `StratForge-worktrees/agent-world-local-runtime`, SHA `486db834850d465006a3983d2d83ee809202df60`, beta.96 |
| Preserved real state | Original Development data root; actual owner identity/workspace, account/balance/history/configuration and authenticated NinjaTrader preserved |
| Build identity | `dev-0.10.0-beta.96-486db834850d`; new delta is not yet claimed as the active build |
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
| Persona | Toolbar → Persona; create/edit/activate/suspend | DomainService + immutable Persona profile | Domain/contract tests PASS; final browser: **реализовано, но не проверено** |
| Own models / supported compatible agent | Toolbar → Models; connect/test/task/disconnect | ModelService → existing secret store, universal client and worker | Scoped transport/authority/idempotency tests PASS; ordinary live credentials: **внешний blocker** until a user-owned connection is available; no owner key copying |
| Existing owner connections | Models → bind existing approved connection | Fresh owner/runtime authority, exact existing registry ID/caps | Revocation/scope tests PASS; final real calls: **реализовано, но не проверено** |
| SF Chat → model → real backtest | Tolik command with explicit catalog strategy/instrument/period | application_chat → model plan → existing jobqueue/NT → verified source report | Application/receipt/cancel tests PASS; fresh live E2E: **реализовано, но не проверено** |
| SF Chat → model → actual Desktop screenshot | Ivan command; open Desktop matching instrument/timeframe | Existing Desktop command queue/canvas/snapshot store | Named-source/hash/PNG tests PASS; live capture/attachment opening: **реализовано, но не проверено** |
| Task Inspector / trace / history | Work row or task card → drawer → SF Chat/evidence | Intent/Task/Contribution/model Execution + application Execution/Outcome/Evaluation | Same-store lineage/idempotency tests PASS; live inspection: **реализовано, но не проверено** |
| Automatic observed rating | Agents → profile/rating | Independent versioned deterministic rubric, distinct-input dedupe | NEW below n=3; no self-scoring/synthetic mixing. Live multiple-model samples: **реализовано, но не проверено** |
| Experiments / comparisons | Toolbar → Experiments → same-input comparison | ModelService + existing worker; separate actual responses | Contract tests PASS; live comparison: **реализовано, но не проверено** |
| Decisions / Consensus / Court | Toolbar → Decisions/Court; proposal, three isolated judges | DomainService + ModelService.judge; sealed packet, immutable votes, 2-of-3 | State/diversity/replay tests PASS; live judges: **реализовано, но не проверено**; verdict never executes work |
| Memory / lessons / sharing | Toolbar → Memory; edit/promote/publish/revoke | Existing private artifacts + active TTL/purpose/source-revision grant | Own/shared/revocation tests PASS; browser retrieval: **реализовано, но не проверено** |
| Strategy Projects | Toolbar → Projects; definition/version/history | DomainService immutable StrategyProject revisions | Contract tests PASS; browser: **реализовано, но не проверено** |
| Routines / calendar | Toolbar → routines/calendar; propose/accept/manual follow-up | DomainService → existing worker follow-up receipt | Contract tests PASS; browser: **реализовано, но не проверено**. Autonomous scheduling is **не реализовано**; automation stays OFF |
| System | Toolbar → System | Existing runtime/capabilities/registry flags, no secrets | Server/UI checks PASS; browser: **реализовано, но не проверено** |
| SF Social publication | Toolbar → В SF Social; select source → exact preview → explicit permanent confirmation | SocialPublicationService → existing Community store/idempotency | 41 service checks PASS plus HTTP/UI contracts; local publication/browser: **реализовано, но не проверено** |
| Restart / cancel / retry / isolation | Existing Local worker, task status and same conversation | Existing queues/leases/inbox; fresh authority before transmission | Contract tests PASS; live restart: **реализовано, но не проверено** |
| Existing PostgreSQL regression | Disposable loopback test DB only | Existing migrations 1–22 and RLS-enabled app role, TLS | **готово и проверено**: 41 PASS, zero skips, 122.71 s on repeated actual DB run |
| General Router / new Execution Engine / Agent World PostgreSQL adapter | Not switched into runtime | Existing Router/executors remain authorities | **не реализовано** for new replacement systems; no new PG adapter or Production fallback is claimed |
| Full suite / final SHA CI / owner design | Verification and draft PR | Existing test/static/context/bundle/CI gates | **реализовано, но не проверено** on final commit; owner visual acceptance remains separate |

The manual historical job `ui_20260905T003301149Z` (1273 bars, 64 trades) remains
excluded from Agent World statistics. It proves the original executor can return
real reports, not that the new model/chat chain has passed. A fresh scoped task
must supply that evidence. Backtesting page redesign remains outside this task.

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

- Latest broad pre-final run: **3803 passed, 44 skipped**, 578.02 s.
  The earlier two stale cache-token expectations are corrected. This is the
  pre-delivery-recovery checkpoint, not final acceptance of later fixes.
- Rating class-label focused regression: **96 passed**. A transient SF Chat
  delivery gap is being repaired using the existing worker/inbox; persisted
  results must be delivered without another provider call or budget charge.
- Actual isolated PostgreSQL rerun: **41 passed**, 122.71 s, zero skipped;
  migrations 1–22, app/admin roles non-superuser and NOBYPASSRLS, TLS.
- Forty-one of the 44 generic Windows skips are the separately executed PG
  cases. The other three are two shell tests and one POSIX permissions test,
  unavailable on this Windows runner; they are not Windows PASS.
- UI/domain/application/service focused evidence is in the
  [integrated change record](../changelog/2026-09-05-agent-world-integrated-local.md)
  and delegated scoped records. Fixture provider tests are not live model tests.
- Historical branch CI on `b05ee124` is not current-delta CI. Final commit,
  push, mandatory/dispatched checks and clean Git are still to be recorded.
- The owner requested a separate ordinary test account and a ready connection
  wizard. A personal test key will be entered by the owner, not copied from
  owner connections. Its real call is **PENDING OWNER KEY**; other work continues.

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
