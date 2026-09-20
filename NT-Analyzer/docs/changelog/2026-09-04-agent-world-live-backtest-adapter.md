# Agent World: bounded real NinjaTrader backtest adapter

Status: IN DEVELOPMENT. Local implementation checkpoint, not a Canary or Production release.

## Change summary

An additive adapter submits explicitly specified, registered strategies to the existing NinjaTrader jobqueue and projects their existing reports into Agent World. It never generates a strategy, starts an LLM, recomputes a simulated backtest, changes the job engine or assigns manually launched jobs to an agent.

The job's atomic origin records authenticated workspace/user, owner UUID, Tolik persona, conversation, correlation, request hash and stable Task UUID. Same scoped idempotency key reuses the canonical job; changed parameters/conversation conflict. New work is bounded to 31 days, explicit instrument/timeframe/session/commission configuration, research High-fill and existing honest accounting governance. Only catalog-exposed parameters are accepted.

Read models filter with canonical job_in_scope plus the owner UUID and Agent World provenance marker before limiting the visible tasks, including when more than 100 unrelated reports precede an owned task. Pending, running, requested cancellation, failed and cancelled remain actual source states. A done directory is not verified success: verification checks NinjaTrader provenance, request identity, effective parameters/execution, run hash, actual bars fingerprint, complete trades/count metadata and source file SHA256. Source replacement during report projection fails closed. Result metrics use the existing report calculation, not a second performance calculator. Actual zero-trade results with historical data remain distinct from infrastructure failure. No LLM quality scores or reputation are invented.

The existing chief monitor may call reconciliation and publish to its existing SF Chat store. The callback receives a stable result-checksum idempotency key and the original private conversation scope. Read-only GET/overview never publish messages. The adapter does not create a background worker or delivery ledger. Existing Reports links open the actual report drawer.

## Boundaries and integration

- Local Development owner only; Preview independently rejected. Root gateway supplies current auth/device/membership/capability/budget and explicit workspace flag admission on each checkpoint.
- Existing jobqueue, Connector, chart engine, market data and manually launched runtime jobs are unchanged. The adapter itself never calls an external provider.
- Per-process submit serialization complements canonical job-id collision checks; this is not distributed concurrency acceptance.
- Current contract is a compatibility projection of canonical jobs, not a duplicate persisted Task/job/report ledger. The root implementation owns gateway, chief hooks, UI and current/context documentation.
- Source files larger than 32 MiB or incomplete Connector transfers remain unverified; extending acceptance requires separate evidence, not fallback metrics.

## Verification and handoff

- `python -m pytest tests/test_agent_world_live_backtests.py -q`: **57 passed**, 14.62 seconds. These use the actual canonical queue/report functions with isolated temporary catalogs and job/result artifacts; NinjaTrader itself is not started.
- Python compilation of the adapter/test: **PASS**. `git diff --no-index --check -- NUL <each owned new file>`: **PASS**, including untracked files (not an empty tracked-only check).
- Tests cover scoped replay, changed-body conflict, same-process concurrent submit, current catalog/parameter/type/range gates, the 31-day limit, fresh admission, Preview/non-Development rejection, original report/hash linkage, real source schemas, missing/tampered/incomplete/changed reports, zero trades versus no data, cancellation/error status, private pagination and idempotent completion-callback keys/retry.
- No actual runtime tasks were executed by this adapter's unit-test run. The owner's earlier manually launched job remains unmarked and excluded from Agent World evidence.
- Three new files only; root integration owns staging/commit and PR/source SHA. Full regression, current/context-document updates, live chat/NT proof and owner visual acceptance belong to that closeout. No version bump, merge, deployment or Production DB/secrets action.
