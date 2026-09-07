# Agent World — explicit routing, finite delegation and due-time mechanisms

Canonical feature status: `IN DEVELOPMENT`. Integration and live acceptance are
not inferred from this scoped implementation record. Business requester: owner.
Technical attribution: AI-assisted change. Branch: `codex/agent-world-mechanisms`.
Starting source: `45ab4361`; the root closeout records final SHA, PR and CI.

## Scoped changes

- `router_v2.py`: explainable same-workspace candidate selection with separate
  Persona, Role, Provider Account, Model and compatible external-agent identity.
  Current trusted permission/pricing/budget admission is independent of observed
  same-class latency. Unknown costs or insufficient/stale samples are denied.
  Arithmetic cannot qualify a backtest/chart task. Cost/latency ordering does
  not manufacture a professional-quality score. Shadow preserves the legacy
  effective choice; active selection requires a different server-side flag.
- `delegation.py`: explicit finite tree, depth at most three, fanout two and
  seven nodes including the source. Exact source revisions, model/persona
  identities, facts and verified outcome references survive restart. Child
  tasks use the existing model service and queue, with deterministic IDs and
  typed dependencies/correlation. The initial operation transfers verified
  scalar facts; it is not image/strategy analysis or a general planner.
- `scheduler.py`: an additional explicit controller, not a reinterpretation of
  accepted manual Routine/Calendar records. IANA timezones, DST gaps/folds,
  finite UTC occurrences, grace windows, missed occurrences, cancellation and
  queue idempotency are explicit. Recurrence is fixed elapsed seconds, not an
  inferred local-wall-clock cron. The existing worker recovery loop supplies
  ticks after gateway/recovery integration, which is still incomplete at the
  2026-09-06 WIP checkpoint; this module starts no scheduler thread or competing queue.

Every autonomous step requires the root's trusted, separately approved durable
automation grant and fresh entitlement/device/membership/budget validation.
The feature flags and an artifact alone are not grants. No implicit owner
exception, expired-browser authority, frontend capability, credential copy,
unlimited retry or trading/tool permission is introduced. Grant absence is a
fail-closed boundary, not a synthetic production success.

Root owns the shared flag registry, admission, ModelService typed constructor,
worker/recovery composition, UI and canonical current/context-pack updates.
Execution V2 independently validates the same immutable origin. Human review is
separate from successful execution and automatic evidence.

## Verification in progress

The first router-only subset passed 15 tests; the active-flag test was explicitly
deselected while the root integration was pending. That is not final acceptance.
Final scoped/full/static/CI counts will be recorded by the responsible workstream.
Tests use disposable storage and explicit fixture provider responses; no real
key, provider call, owner runtime, Local 8765, Production or PostgreSQL data is
touched by this workstream.

## Rollback and release boundary

Leave all new gates disabled to retain legacy routing/manual workflows. Rollback
removes additive code integration, not recorded tasks, approvals, source data,
history or artifacts. No data migration, merge, release, deploy or version
change is performed in this scoped workstream. Local implementation, Git/CI
closeout and program/owner acceptance remain distinct.
