# Agent World: evidence-backed local owner rehearsal

Status: `IN DEVELOPMENT`. This is a bounded synthetic workflow implementation,
not a release or a statement that all Agent World stages are closed.

## Change summary

The owner can request four small, real offline computations under the existing
Marina, Tolik, Nikita and Ivan role presentations: ledger arithmetic, series
statistics, event classification and a generated candle-chart SVG. Ivan depends
on Tolik's verified result. Inputs are explicitly invented observations from
three fixed benchmark cases, not a market feed, broker account or provider call.

Intent, Task, Contribution and Outcome records persist their actual transitions,
correlation, immutable evidence references and independent verification through
the new local repository. The caller must supply an admitted synthetic Preview
context and revalidate existing access, device, capability, flags and zero-cost
budget authority before each checkpoint. Admissions and work deadlines expire;
interrupted in-deadline runs resume from durable state without duplicate tasks.
Concurrent same-key requests coalesce to the first committed fixture and graph.

An independent deterministic checker recomputes expected arithmetic and validates
SVG geometry/provenance/hash. Producing and verifying services have distinct
actor IDs, with the authenticated human recorded separately as `on_behalf_of`.
The producing service does not accept its own contribution. No provider account,
model record, legacy rating registry, job queue or permission system is copied.

Read models expose scoped tasks, evidence, timeline and benchmark observations.
Ratings remain `NEW` until three distinct fixed cases exist. Replays and repeated
fixtures do not inflate sample size; the worst observed score for each fixture
is retained. Confidence is at most low and model quality is explicitly unassessed.
Each role is compared only within its own task class; identical fixture results
are not turned into an invented cross-role ranking. Ratings have no routing effect.

## Verification and identity

- Foundation base: `d5d07ac6817cd10f57d916dab0ce655347a8cbde`.
- Storage dependency: `386bad57` (equivalent local cherry-pick `9b159359`).
- Workstream: `codex/agent-world-workflows`, isolated worktree.
- Local version remains `0.10.0-beta.96`; no version assignment or publication.
- New workflow tests cover all 12 executor/fixture pairs, independent rejection
  of wrong outputs and changed chart geometry, durable graph/event/evidence
  writes, private owner/workspace access, deadline/admission denial, access-expiry
  resume, concurrent and sequential idempotency, fixture deduplication, accepted
  roster compatibility and absence of network/process effects.
- Focused repository + workflow regression: `98 passed`, no skips (57 storage
  tests and 41 workflow tests). New modules and tests pass Python compilation.
  `git diff --check` passes for the exact staged source/test/change-record scope.
- Full regression, browser evidence, SF Chat projection, Context Pack updates,
  final commit/PR identity and `STAGE CLOSED` are owned by the parent integration
  workstream in `docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md`.

## Release impact and limits

No market-data, chart-engine, Connector, trading, auth, device, SF Social or
SF Chat authority is modified by these modules. The SVG is an isolated artifact;
the parent integration handles its visible screenshot and chat projection.
No LLM/provider quality, Court, new execution engine, live chart modification,
paid task, production storage acceptance, worker lease or automatic routine is
claimed. Read projections are bounded to 100 records; the owner rehearsal is not
an unrestricted work scheduler. This workstream performs no merge, deployment,
Production DB/secrets operation or standalone release. Its code is published only
as part of the reviewed Agent World integration change.
