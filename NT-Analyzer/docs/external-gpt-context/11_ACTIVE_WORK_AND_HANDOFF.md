# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-21T03:50:00Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: main `36600dba3d739601660768db98b429b0f752ad1a` plus this operational docs-only closeout
- Candidate: `0.10.0-beta.28`
- Scope: Final product acceptance and release closeout
- Status: DONE
- Acceptance note: immutable software release cycle completed; Production owner UI recheck is waiting only for the physical isolated Telegram login confirmation already open in Chrome.
- Current Production version/build/artifact when known: `0.10.0-beta.28`; build `sf-0.10.0-beta.28-36600dba3d73-20260821T031309Z`; runtime SHA256 `864F7D16C03999EF2119EA13C73FBD05DD7FF160E49ADD8EA6D02E91555D916C`

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` remains the pack-wide verification baseline; deployed implementation main is `36600dba3d739601660768db98b429b0f752ad1a` |
| LOCAL | clean beta.28 implementation/test baseline; canonical live root remains `<project>/data` via `start.ps1` |
| Canary | beta.28 `36600dba`, runtime manifest `864F7D16...D916C`, authenticated owner UI/Documents/charts PASS |
| Production | same beta.28 `36600dba` and runtime manifest, public live/ready/exact UI PASS; isolated owner login awaiting physical confirmation |
| Release parity | YES: same candidate/artifact/build/archive/runtime identity; no rebuild |
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

## Completed execution sequence

1. Full local regression/static/Markdown/CSP/link checks passed with zero failures.
2. Real LOCAL/Canary owner and Admin journeys, Documents and TopstepX chart
   checks passed; exact Canary MES/MNQ 5m soak was 610 seconds.
3. PR #140 passed all mandatory CI and merged as `36600dba`.
4. Server built/signed exactly one final artifact and deployed it to Canary.
5. Canary acceptance recorded PASS under check
   `chk_071bcc9813764315b8b0bc50afb25089`.
6. The same artifact was promoted to Production without rebuild; public
   live/ready/exact identity passed.
7. This docs-only closeout records the operational identity. Physical
   Production Telegram login remains the only open acceptance interaction.

## Explicitly deferred / external

- Physical enrollment of a new Windows NinjaTrader Connector device. Existing
  Connector/NinjaTrader state may be observed, but no synthetic enrollment or
  unnecessary restart is allowed.
- Google OAuth and transactional e-mail remain `EXTERNAL BLOCKED` until their
  separate provider/security closeout.
- Legal package publication remains `IN DEVELOPMENT` / DRAFT.

## Stop conditions

Reopen the release cycle only if a new code/UI/document artifact change is
required. Do not rebuild or hotfix the accepted server artifact in place.

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
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Closed the immutable beta.28 release sequence through accepted Canary and same-artifact Production; retained the physical Production Telegram login as the sole explicit interaction.
-->
