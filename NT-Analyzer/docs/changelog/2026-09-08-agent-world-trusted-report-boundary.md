# Agent World — trusted report binding and origin correction

Status: **IN DEVELOPMENT**. AI-assisted change. Version `0.10.0-beta.96`.
Task branch `codex/agent-world-unified-acceptance`, draft PR #285; baseline
`a03ec82b686a9f6f05c056fe5a500ecbdb3babac`. This is a subsequent bounded fix,
not release acceptance, a Local update, a merge or deployment.

## Reason and scope

The two withdrawn reports in the earlier handoff were written by privileged
test code directly into trusted server files. An ordinary model/browser could
not upload those files by merely claiming `execution_source=ninjatrader`.
The genuine historical owner run is not invalidated by those separate fixtures.

Further disposable testing did confirm a different boundary defect: an enrolled
Connector's authenticated result was not bound to the original canonical job
dispatch before filesystem settlement. The protocol validated its own command
and device, but a caller-chosen idempotency name was insufficient authority for
the server's job directory. No anonymous access or model-text upload is claimed.
Only a newly created test root was used; no owner job or real device was touched.

## Change

- Before result persistence, validate the authenticated stored command against
  the canonical job, exact projected payload, issuer, source/target workspace,
  command/connection IDs and server-written dispatch record. Return an explicit
  refusal without consuming the result/sequence on a mismatch.
- Cancellation receipts require their own server dispatch record. A cancel
  acknowledgement is not a completed or cancelled run.
- Job IDs are names, never paths. Validate resolved canonical state directories
  before writes/moves. Refuse symlink redirects and destination collisions;
  do not delete prior result directories to make room for a new result.
- Preserve normal authenticated completion and duplicate delivery semantics.
  No change to market-data/chart behavior, trading authority or NinjaTrader
  source verifier. Legacy dispatch records require the same original identity
  and source workspace; new records explicitly pin both workspace identities.
- Propagate rejected synthetic origin into nested results, outcomes and Chat.
  A corrective Chat message is accepted only when it exactly matches the current
  scoped saved report/verification. Its separate versioned delivery identity
  appends the correction; it does not rewrite the earlier audit.

Synthetic reports remain ineligible for verified application-execution evidence
and model quality. A Desktop PNG is separately validated media from the bound
capture flow, not proof of professional model quality or of market freshness.

## Verification / continuation

Initial disposable boundary reproduction: **5 failed / 2 passed**, with two
command/path-binding cases and three origin projection mismatches. After the
first fix, trusted-boundary + Connector dispatch/protocol + live-backtest scope:
**189 passed**, 21.50 s. Expanded positive/replay/negative, corrected Chat,
Preview and application regression: **206 passed**, 135.48 s. The expanded
boundary/Connector/live-backtest suite including cancel: **208 passed**, 27.49 s;
six touched Python modules compile. Final integrated receipt belongs to the
next preserved source. These are fixtures and loopback HTTP, not live NinjaTrader.

Broader tests also found outdated expectations that every Preview domain is
disabled. The approved manual Persona/Memory/Project expansion is now asserted
explicitly: reads create no records, only an isolated empty schema; real models,
publication, worker execution and implicit grants remain forbidden. Invalid
manual CRUD stays invalid, with its precise validation response. Model-plan
provenance is asserted separately from still-pending application execution.

Protected owner Local remains on `2b6d0112`, port 8765, unchanged. Original
worktrees and all existing data are preserved. Rollback is the preceding saved
integration checkpoint; there is no working-database migration or release.
Current program status is maintained in the repository-only
`docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md` (accepted exclusion from the
production artifact), not replaced by this scoped receipt.
