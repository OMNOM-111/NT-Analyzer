# Agent World — scoped domain services and independent Court

Release title: Agent World domain services for Local owner review.
Change summary: add real scoped Persona, controlled Memory, versioned Strategy
Projects, manual routine/calendar follow-ups, Consensus proposals and independent
Court over the existing Agent World revision/event/outbox repository; add reviewed
SF Social publication and non-mutating repository reads for the integrated UI.

- Business requester: project owner; implementation attribution: AI-assisted change.
- Source baseline: `486db834850d465006a3983d2d83ee809202df60`.
- Branch: `codex/agent-world-owner-preview`; integrated task PR/source SHA is
  assigned by the root closeout after the final combined checks.
- Local product version remains `0.10.0-beta.96`; this record is not a release,
  merge, Canary/Production acceptance or confirmation of live provider calls.
- Current program status: [Agent World implementation status](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-owner-preview/NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

## Implemented scope

- Persona create, activate, versioned update, suspend and retire remain separate
  from Model, Provider Account, permissions and human identity.
- Memory has private/task/working/verified-lesson classes, source provenance,
  explicit human promotion, purpose-filtered retrieval, TTL and append-only
  revocation. Working context has a one-day maximum; task memory requires the
  exact task context. A disputed source Outcome removes a verified lesson from
  active retrieval without rewriting history.
- `publish_to_workspace` creates a separate explicit shared Memory publication.
  Other admitted users in the same workspace can read only the selected content
  and publication proof through that active record. Private artifact APIs are
  unchanged. Publication/source revocation, source-revision mismatch, expired
  retention or hash corruption remove access. No publisher impersonation or
  cross-workspace fallback is used. The runtime's existing membership gate
  remains authoritative; repository isolation tests are not a claim that group
  access has been enabled in the running owner workspace.
- Strategy Projects retain immutable parameter-version snapshots, including
  negative values; subsequent metadata updates do not rewrite old versions.
- Routine/calendar suggestions can be accepted or dismissed. Acceptance requires
  an injected existing-queue adapter, uses a stable per-record idempotency key,
  and records the returned manual-follow-up receipt. Automation remains OFF;
  no new scheduler, queue, permission registry or budget account is created.
  Dismissing a suggestion is not cancellation of an independently queued job;
  job cancellation remains in the existing Work/job authority.
- Process Intelligence accepts only structured verified Outcomes as suggestion
  provenance; it does not scan private chat transcripts.
- Consensus builds a proposal from two or three accepted, same-input model
  Contributions with distinct model/task identities. It does not count duplicate
  observations or Court votes as independent candidate paths.
- Court stores one immutable evidence/policy packet and three distinct session
  identities. Each trusted model adapter receives that packet without peer votes,
  chat history, shared working memory or executable tools. Votes are separate
  terminal records. Simple 2-of-3 voting ignores confidence weights and preserves
  dissent. Critical cases require at least two provider failure domains.
- Each Court vote is bound to an accepted Contribution, succeeded model Task,
  exact session/case/model/packet/policy/prompt checkpoint and matching provider
  receipt. Missing providers, stale models, revoked admission, invalid provenance,
  no quorum or insufficient diversity cannot approve a proposal. Judge tasks are
  not strategy/model-quality ratings. Court approval is advisory and grants no
  trade, job or tool execution permission.
- Partially completed reviews resume committed votes after restart. API replay
  returns the original revision even after later edits, using the existing atomic
  mutation ledger. Ordinary explicit task-authorization Decisions remain visibly
  distinct from Court proposals; no legacy committee is renamed.

## Integration contract

`DomainService(repository, judge_runner=None, enqueue=None, now=None)` provides
`list`, `get`, `create` and `act` with trusted `context` and mandatory fresh
`admit` callback. Scope is never accepted from a browser payload. Mutation results
include `item`, `replayed` and `correlation_id`; collection results include an
opaque scope/user/domain-bound cursor and capability/limitation fields.

Supported collections are `personas`, `memory`, `projects`, `routines`,
`calendar`, `decisions` and read-only `court`. Extra services are
`retrieve_memory`, `evidence_candidates`, `suggest_routine` and
`propose_consensus`. The unified HTTP facade and server-side flag composition
are integrated separately by the task owner; there is no alternate public API.

The server callback must recheck existing membership, owner/writer role,
`ai_lab`, environment and exact-workspace configuration, plus the appropriate
existing registry flag: task graph for Persona/Projects/Routines/Calendar,
`AI_MEMORY_V2` for Memory, `AI_CONSENSUS_V2` for proposals and
`AI_COURT_V1` for Court review. Flags are never permission grants. The domain
module does not activate flags or create a background worker.

Storage adds the reviewed domain kinds to the existing strict codec/state
registry and adds bounded read-only `get_revision`, `lookup_mutation` and
`read_memory_artifact` methods. There is no numbered migration or competing
store. A PostgreSQL implementation must support the same methods and prove its
own actual database/RLS behavior; SQLite remains Development-only. No Agent World
PostgreSQL domain adapter is present in this slice. Existing relational PostgreSQL
regression evidence is not acceptance of these new domain contracts; non-DEV
domain access must remain fail-closed.

## Additive integration fixes and explicit SF Social publication

- `SQLiteAgentWorldRepository(path, read_only=True)` returns empty authorized
  read views when the database is absent, without creating directories, a DB or
  schema. An existing DB is opened with SQLite `mode=ro`/`query_only` and validated
  without migration or metadata writes. Mutations fail with a read-only error.
  Ordinary WAL reads remain current and do not take exclusive writer locks.
  SQLite may create operational `-wal`/`-shm` sidecars while opening an existing
  WAL database read-only; this is not a domain/schema/data mutation. No
  `immutable=1` shortcut discards committed WAL data.
- `events.is_acknowledged` reads the existing consumer inbox only through the
  caller's scoped visible event. It creates no receipt or parallel delivery
  ledger; restart, consumer separation and foreign-user/workspace denial are
  covered. SF Chat reconciliation can skip already delivered final events.
- Shared Memory DTOs expose content/publication artifacts through the explicit
  active-Memory grant route `/api/ai-control-center/memory-artifacts/{memory}/{artifact}`.
  Private artifacts retain the owner-only artifact route. No shared reader
  receives publisher impersonation or direct access to private source artifacts.
- `SocialPublicationService` prepares a read-only public snapshot, then requires
  a separate human publish action with exact approved SHA256, source revision,
  existing server-side identity, visibility and permanent-publication consent.
  The root facade also enforces the existing Community capability. Preview,
  synthetic receipts, non-Development contexts and agent-initiated publication
  are rejected. No GET, job completion or judge action publishes automatically.
- Sources are owned verified Outcomes or real independently reviewed Court
  Decisions. Model receipts are re-evaluated against their exact bounded input;
  application results retain actual Task/Execution/source/hash linkage. Desktop
  evidence is validated as a bounded PNG, not mistaken for independent visual
  quality assessment. NinjaTrader summaries retain canonical source checksums
  and allowlisted metrics. An optional trusted scoped backtest loader reuses the
  existing report authority; it is not a client-supplied result object.
- Published cards contain selected metrics, advisory vote counts and artifact
  hashes, not model prompts/answers, Memory, proposal packets, judge rationales,
  credentials, raw trades, local paths or source images. Arbitrary artifacts and
  Memory cannot be relabelled as a verified publication. These cards make no
  profitability or general model-quality claim and grant no execution authority.
- The explicitly approved snapshot is immutable in the existing SF Social store.
  Its private content-addressed approval records human actor and business
  requester separately. Existing `community.create_social_post` idempotency
  handles interrupted publication; semantic request digests reject same-key
  changed-body retries without rewriting the standing post. There is no second
  social store, permission registry or publication ledger. Existing permanent
  post/correction/moderation policy remains unchanged.

Service signatures:

```text
SocialPublicationService(repository, community_api=None, backtest_loader=None)
prepare(context, admit, source_kind, source_id)
  -> snapshot, snapshot_sha256, source_revision, permanent,
     requires_explicit_confirmation
publish(context, admit, user_id, source_kind, source_id,
        approved_snapshot_sha256, expected_revision, idempotency_key,
        text="", visibility="network", confirm_permanent=False)
  -> ok, post, deduplicated, snapshot_sha256, approval, permanent, published_to
```

`context`, numeric `user_id` and `admit` are server-authoritative, never browser
scope fields. Public preparation and explicit publication are integrated in the
root's existing domain facade, not a new API authority.

## Verification at this scoped checkpoint

- `python -m pytest tests/test_agent_world_domain_service.py
  tests/test_agent_world_contracts.py tests/test_agent_world_storage.py -q`:
  **299 passed**, including 46 domain cases and additive codec/transition tests.
- The domain cases use real isolated SQLite files and mocked provider transport,
  not owner data or network calls. The actual `ModelService.judge` adapter is
  exercised through real Task/Contribution/Outcome/Evaluation records with mocked
  responses; this is not live-model acceptance evidence.
- Covered: immutable revisions, durable replay, conflicting keys/CAS, private and
  shared owner/workspace isolation, cursor binding, credential/scope injection,
  fresh admission, source revocation/TTL, negative strategy parameters, queue/commit
  crash retry, isolated judge packets, unweighted quorum, dissent, critical
  diversity, provider failure/resume, contribution/receipt binding, and GET without
  domain mutations or dispatch.
- Python compilation of the touched domain/codec/storage modules: **PASS**.
- `git diff --check`: **PASS** at this checkpoint.
- Repository-root `release_static_scan.py --scan markdown`: **PASS**.
- Additional compatibility/demo run: **402 passed, 1 failed**. The existing
  runtime-import purity test still allows only `server.py`/`chief_agent.py`, while
  concurrent root integration introduces worker composition imports. Its narrow
  allowlist requires root review; the core purity assertion was not weakened by
  this scoped change. This is not a full-regression PASS.
- Full combined regression, static artifact gates, final CI, actual PostgreSQL,
  credentialed model calls and browser/owner acceptance are owned by the root
  integration and are not asserted by these focused tests.
- Additive SQLite read-only/inbox suite: **71 passed**, including missing-store
  filesystem non-creation, unchanged persisted DB bytes and committed-WAL reads.
- Final combined scoped run of `test_agent_world_social_publication.py`,
  `test_agent_world_storage.py`, `test_agent_world_domain_service.py` and
  `test_agent_world_contracts.py`: **348 passed** in 126.87 seconds. This includes
  41 SF Social publication cases and verified model-linked PNG/NinjaTrader
  summary snapshots. Tests use isolated Community/SQLite stores and mocked
  provider transport; they do not publish owner data or call real providers.
- Updated Python compilation, repository-root Markdown scan and
  `git diff --check`: **PASS** after the additive read-only/publication changes.

No version bump, stage/commit, push, merge, live process switch or deployment was
performed by this scoped executor. Shared current/handoff and External GPT Context
Pack updates remain with the root integration writer so their facts describe the
final combined code rather than a competing intermediate status.
