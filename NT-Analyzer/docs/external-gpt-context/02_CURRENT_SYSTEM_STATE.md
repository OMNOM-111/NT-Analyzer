# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-21T03:50:00Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: main `36600dba3d739601660768db98b429b0f752ad1a` plus this operational docs-only closeout
- Candidate in this closeout: final `0.10.0-beta.28` immutable artifact from `36600dba` is accepted in Canary and live in Production
- Scope: Current factual subsystem snapshot only
- Status: DONE
- Acceptance note: software release cycle is complete; Production owner UI recheck waits only for the physical environment-isolated Telegram login confirmation already open in the browser.
- Current Production version/build/artifact when known: `0.10.0-beta.28`; build `sf-0.10.0-beta.28-36600dba3d73-20260821T031309Z`; runtime artifact SHA256 `864F7D16C03999EF2119EA13C73FBD05DD7FF160E49ADD8EA6D02E91555D916C`

## Evidence modes

- Repository evidence is the current code and tests in the beta.28 acceptance
  change set.
- Operational evidence is queried from `/api/runtime/env`, `/api/live` and
  `/api/ready` and from Release Center candidate/deployment records. Canary and
  Production now report the same beta.28 build/runtime digest.
- The canonical pre-release snapshot is
  [2026-08-20-final-product-acceptance-beta28.md](../changelog/2026-08-20-final-product-acceptance-beta28.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` | LOCAL has one canonical owner UUID with Telegram identity; Canary and Production keep separate DB, sessions, cookies and storage | Google OAuth and transactional email remain `EXTERNAL BLOCKED`; four Google/Resend secrets are not rotated in this closeout |
| Admin / Release Center | `BETA` | One environment/release module exposes DEV, Canary, Production, compare and pipeline. LOCAL submits a signed request; only Canary/Production may decide from authoritative registry state. The corrected ordinary approve→promote flow completed in Production | no release-control blocker remains |
| Release security | `BETA` | Exact artifact, exact candidate, responder environment and decision TTL are verified; server signature/timestamp/nonce provide fail-closed replay protection. Final Production deployment recorded signature/readiness/identity and same-artifact evidence | rotate only through a future owner-approved release cycle |
| Test isolation | `AVAILABLE` | Every test receives separate disposable Production/Development roots; tracked governance baselines are copied there; any live `data/` mutation fails the suite; full local and mandatory hosted/self-hosted CI passed | no open release blocker |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only chart source; accepted history/realtime architecture is unchanged and passed final Canary on the Production artifact identity | an external feed never grants execution authority |
| Charts | `BETA` | Final MES/MNQ 5m Canary soak on `36600dba` ran 610 s with 13 samples / 26 row checks and 0 visual/OFF violations; raw TopstepX price, last bar close and rendered marker matched | no chart implementation changed; physical NT verification is separate |
| NinjaTrader / Connector | `PARTIAL` | NinjaTrader remains the execution/backtest/runtime truth and is not required for independent TopstepX charts | Physical enrollment of a new Connector device requires Windows/NinjaTrader interaction and is reported separately, never simulated |
| Documents | `BETA` | Governance source, compact revision UI, legal DRAFT status and canonical revision hydration are in the accepted artifact; Canary owner showed CHARTER revisions through №7 | post-release operational handoff updates are repository evidence for the next artifact |
| AI agents | `PARTIAL` | Vitek, orchestration and specialist surfaces exist | Per-workspace team and some external-provider paths remain incomplete |
| Legal | `IN DEVELOPMENT` | Structured legal package exists | It remains DRAFT until owner/legal decisions and counsel review |

## Current operational identity

| Environment | Live/ready | Version | Git SHA | Runtime artifact SHA256 |
| --- | --- | --- | --- | --- |
| Canary | live/ready + owner UI/Documents/charts PASS | `0.10.0-beta.28` | `36600dba3d739601660768db98b429b0f752ad1a` | `864F7D16C03999EF2119EA13C73FBD05DD7FF160E49ADD8EA6D02E91555D916C` |
| Production | live/ready + exact public UI PASS | `0.10.0-beta.28` | `36600dba3d739601660768db98b429b0f752ad1a` | `864F7D16C03999EF2119EA13C73FBD05DD7FF160E49ADD8EA6D02E91555D916C` |

Both rows are the same signed immutable artifact. Archive SHA256 is
`A5E906D27B49118AF4E7155B4F08217E433EF03CC598BF6BFB60DBF087005D8A`;
active release-directory suffix is
`production_data/releases/0.10.0-beta.28-36600dba3d73` (the environment-owned
absolute data root is intentionally not copied into this external pack).

## Deprecated current-state claims

- Do not use the 2026-08-14 beta.1 / `1fae1f39` snapshot as current live state.
- Do not describe the combined Admin environment/release UI or LOCAL-driven
  server-authoritative promotion as unfinished; they are implemented.
- Do not treat DRAFT legal documents as effective terms.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Replaced obsolete beta.1 state with verified beta.27 Canary, beta.26 Production and beta.28 final-acceptance scope.
2026-08-21T00:53:04Z | GPT-5.5 через Codex по запросу owner | Recorded the first beta.28 Canary candidate as not accepted after a live archive/runtime digest mismatch; Production remained beta.26.
2026-08-21T02:03:00Z | GPT-5.5 через Codex по запросу owner | Recorded the non-accepted 8865fad0 Canary artifact and scoped isolated governance-ledger hydration correction; Production remained beta.26.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Recorded 2790fb43 Canary visual acceptance and the real approved_for_production authoritative-gate blocker; Production remained beta.26.
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Recorded final 36600dba signed identity, 610-second exact MES/MNQ 5m Canary PASS and same-artifact Production live promotion.
-->
