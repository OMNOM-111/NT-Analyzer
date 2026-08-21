# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-21T02:52:33Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: main `2790fb43992d29439aa939dea9e972862592c652` plus the scoped release-control state-milestone correction in this commit
- Candidate: `0.10.0-beta.28`
- Scope: Final product acceptance and release closeout
- Status: IN DEVELOPMENT
- Acceptance note: completion requires one immutable beta.28 artifact to pass Canary and Production live checks.
- Current Production version/build/artifact when known: `0.10.0-beta.26`; build `sf-0.10.0-beta.26-3353e3836306-20260817T230438Z`; artifact SHA256 `27B6316E934F0D727B9D158B34EE601A0A59EF78F0D71B484DD29ADD37617AAB`

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` as the pack-wide verification baseline; repository main is `2790fb43992d29439aa939dea9e972862592c652` plus the scoped release-control state-milestone correction in this commit |
| LOCAL | not running at the start of this acceptance; canonical live root remains `<project>/data` via `start.ps1` |
| Canary | beta.28 artifact from `2790fb43992d` is live and passed Documents/chart visual acceptance; runtime manifest `CFBE5BDE78E0AC755673706289C56CF6FD08D1BF7FE1D3DAE41C925A90E63398`; it is superseded by the promotion-gate code fix |
| Production | beta.26, Git `3353e3836306dca4628c759064139cdac94517e0`, artifact `27B6316E934F0D727B9D158B34EE601A0A59EF78F0D71B484DD29ADD37617AAB`, live/ready PASS |
| Release parity | NO before beta.28; final target is one exact artifact in both server environments |
| Market-data baseline | protected; no market-data/chart implementation refactor in this closeout |
| Secret rotation | explicitly deferred; do not rotate the four Google/Resend secrets |

## Implemented in the beta.28 change set

- Release-control responses now bind to an authoritative responder, exact
  candidate, exact artifact and a valid 120-second decision window.
- Stale/cross-candidate/cross-artifact/development responses fail closed.
- Test roots are isolated for both environments before imports and per test.
- Governance test baselines are copied from tracked repository files into the
  disposable test root.
- Any live `data/` mutation fails pytest; there are no known-writer exemptions.
- CI workflows no longer share a correctness-motivated concurrency group.
- A real signed release-control request found and failed closed on a digest
  namespace bug: the registry exposes runtime/manifest SHA while LOCAL sent the
  transport archive SHA. The scoped correction sends manifest SHA for the live
  equality gate and retains archive SHA as separate evidence.
- Canary Documents visual acceptance then found that the immutable artifact
  carried the canonical revision ledger but the isolated persistent data-root
  never imported it. The scoped correction appends only missing tracked rows by
  stable identity, preserves environment-local rows and is restart-idempotent.
- The next real approve→promote action found that the server required literal
  `canary_passed` after LOCAL had correctly advanced the candidate to
  `approved_for_production`. The correction treats acceptance as a reached
  milestone for advanced/retryable states and keeps pre-acceptance states
  fail-closed.

## Required execution sequence

1. Complete full local regression/static/markdown/CSP/link checks with zero failures.
2. Run the real LOCAL browser user and Admin journeys, console/network sweep,
   owner identity checks, Documents and TopstepX charts.
3. Commit, push, PR, mandatory CI and merge the release-control correction to main.
4. Build/sign exactly once from that merged main and verify archive/manifest hashes.
5. Replace the non-accepted Canary candidate, then run authenticated browser + API + chart acceptance and
   fail-closed release-control probes.
6. Promote the same artifact to Production without rebuild and repeat live checks.
7. Append exact operational identity and close the Context Pack/repository.

## Explicitly deferred / external

- Physical enrollment of a new Windows NinjaTrader Connector device. Existing
  Connector/NinjaTrader state may be observed, but no synthetic enrollment or
  unnecessary restart is allowed.
- Google OAuth and transactional e-mail remain `EXTERNAL BLOCKED` until their
  separate provider/security closeout.
- Legal package publication remains `IN DEVELOPMENT` / DRAFT.

## Stop conditions

Do not claim final PASS if Canary/Production artifact identity differs, any
mandatory check fails, owner login cannot be exercised, TopstepX chart evidence
is unavailable, or Production would require a rebuild/hotfix.

## Canonical evidence

- [LOCAL_BASELINE_CHECKPOINT.md](../current/LOCAL_BASELINE_CHECKPOINT.md)
- [2026-08-20-final-product-acceptance-beta28.md](../changelog/2026-08-20-final-product-acceptance-beta28.md)
- [04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- `app/release_control.py`
- `tests/conftest.py`
- `tests/test_release_control.py`

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Replaced obsolete beta.1 handoff with executable beta.28 final-acceptance checkpoint and explicit stop/deferred boundaries.
2026-08-21T00:53:04Z | GPT-5.5 через Codex по запросу owner | Recorded first beta.28 Canary as not accepted, the live archive/runtime digest diagnosis and mandatory corrected rebuild; Production stayed beta.26.
2026-08-21T02:03:00Z | GPT-5.5 через Codex по запросу owner | Recorded the non-accepted 8865fad0 Canary artifact and the isolated governance-ledger parity correction required before final acceptance; Production stayed beta.26.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Recorded 2790fb43 Canary visual acceptance, the real authoritative promotion state blocker and mandatory new release cycle; Production stayed beta.26.
-->
