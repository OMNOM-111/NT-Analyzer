# Agent World — shared integration checkpoint

Status: **IN DEVELOPMENT**, not release or owner acceptance. Version stays
`0.10.0-beta.96`; source is the commit containing this record on
`codex/agent-world-unified-acceptance`, after preserved core
`13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`. Draft
[PR #285](https://github.com/OMNOM-111/NT-Analyzer/pull/285) remains based on
`codex/agent-world-owner-preview`; no other PR base or original worktree changed.

## Changes and rationale

- Wire Persona presentation/voice and Process Intelligence into the existing
  domain API and three-tab Aurora UI; retain existing assets and authority.
- Add a separate Preview operator and explicit six-record synthetic dataset,
  isolated from Local. Existing registration and device choices stay manual.
- Connect bounded Coordinator completion and individual/aggregate review to
  existing worker jobs, inbox and SF Chat. Child continuation is a separate
  job; delivery retries never repeat a provider call. Graph-specific consumer
  and Chat identity avoid collisions when graphs share a root review event.
- Pin named-test request origin before queueing. Flag OFF cannot silently
  convert queued test work into an external call. Historical receipts remain
  readable and are projected as synthetic, not rewritten as new evidence.
- Keep connection verification, automatic result verification, human acceptance
  and downstream execution authorization distinct. The test executor does not
  establish a real provider connection or real professional-quality score.
- Review persistence is independent from notification delivery: transport
  failures yield a non-secret pending notification status, not a failed review.
- Use one task projection in task detail, model history and counters; include
  aggregate results and their individual review links. System reports actual
  selected storage and separate implementation/flag/mode/availability facts.
- Add explicit Coordinator and Router preview/approval drawers. Source choice,
  revision and plan are pinned before normal worker admission. Old task results
  and errors are retained. No hidden consent, new authority or new queue.
- Add trusted worker-only history delivery for ordinary users whose browser
  session has expired, without weakening browser authentication or granting
  new execution after authorization expiry/revocation.

## Verification receipts at preservation time

These are overlapping focused suites, not a summed full regression:

- Shared API/Persona/Process Intelligence: **12 PASS**, 3.70 s.
- Coordinator API → actual normal worker → three-level graph → individual
  reviews → aggregate review → SF Chat: **1 PASS**, 199.42 s. Test executor
  only, no externally generated model result or hand-written ready graph.
- Unified page/shared API/security: **234 PASS**, 77.71 s, before the final
  trusted SERVICE-history delta; does not certify subsequent source changes.
- Persona/Process/Coordinator/Router UI contracts: **339 PASS**, 35.89 s.
  Node/DOM fixtures, not browser acceptance. Shared script cache identities
  are synchronized across Aurora HTML consumers without changing their layout.
- Preview-domain combined regression: **153 PASS**; final new suite
  **30 PASS**. Includes two-user private/shared memory and revocation through
  actual isolated HTTP handlers. This is SQLite, not PostgreSQL/RLS evidence.
- Security/model provenance/delivery after trusted-history integration:
  **118 PASS**, 160.00 s. A separate ordinary-user actual worker scenario passed
  after browser expiry. Final security scope: **54 PASS**, 56.62 s; shared
  security/Coordinator/HTTP domains: **165 PASS**, 332.11 s, no skips.
- Router preview/apply and core domains: **50 PASS**, 490.61 s, no skips;
  routed result to strict verified non-trading root: **1 PASS**, 20.49 s.
  These contract/worker fixtures make no real provider calls.

Initial failures and fixes are retained in contributor records: fixture
composition mismatches, client helper scope/fanout, stale System descriptions,
aggregate count, post-review notification errors, queued test-origin fallback,
ordinary SERVICE history and Router source/Execution pins. No failing scenario
was converted to skip, automatic review or weaker authority.

The earlier **4537 PASS / 110 skipped** full run certifies only `92436698`.
The separately recorded **69 Agent World PG PASS / 41 legacy PG PASS** and
API/worker/restart/RLS runtime receipt certify their earlier application hash.
Neither is a fresh full/runtime PASS for this checkpoint.

Read-only follow-up identified a residual DTO provenance mismatch: rejected
synthetic backtest results can still have false synthetic markers in nested
live projections. Trusted verification rejects the corrected fixture source;
this is not evidence of an ordinary-user ingress bypass. Reproduction and
the bounded projection correction are the first post-checkpoint follow-up.

## Remaining verification and rollback

The repository-only `docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md` is the
single program matrix (accepted exclusion: current developer documents are not
shipped in the production bundle). Final full/static/context/bundle, browser, fresh
PostgreSQL runtime and exact-SHA CI are pending. True provider/NinjaTrader
checks, a separate user's key, actual user consent and a specific permanent
owner Social publication are not fabricated or copied from older runs.

Original worktrees and owner Local 8765 remain untouched on `2b6d0112`; that
runtime is the protected review/rollback point. Only isolated QA on localhost
8804 may be restarted after a saved checkpoint, preserving its own data too.
Ignored data, queues, credentials, logs, artifacts and launchers are not staged.
No migration is applied to a working database. No paid/external calls or trades.

Next: save after mandatory short gates, restart only isolated 8804 on exact
source, run full manual Preview + Agent World routes and final immutable-code
regressions. Fix reproducible failures in separate later commits. No Local
activation, merge, deployment or whole-program acceptance is included.
