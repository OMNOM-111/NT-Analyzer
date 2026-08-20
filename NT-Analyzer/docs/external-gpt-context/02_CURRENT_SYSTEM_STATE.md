# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-20T23:00:44Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: main `3102a534ab569d0cbf162462726d516378dc82a8`
- Candidate in this closeout: `0.10.0-beta.28` (pre-release; Git SHA and artifact are not asserted before merge/build)
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL
- Acceptance note: beta.28 Canary and Production live acceptance is not complete yet.
- Current Production version/build/artifact when known: `0.10.0-beta.26`; build `sf-0.10.0-beta.26-3353e3836306-20260817T230438Z`; artifact SHA256 `27B6316E934F0D727B9D158B34EE601A0A59EF78F0D71B484DD29ADD37617AAB`

## Evidence modes

- Repository evidence is the current code and tests in the beta.28 acceptance
  change set.
- Operational evidence is queried from `/api/runtime/env`, `/api/live` and
  `/api/ready`. Before beta.28, Canary is beta.27 and Production is beta.26;
  they are healthy but not in release parity.
- The canonical pre-release snapshot is
  [2026-08-20-final-product-acceptance-beta28.md](../changelog/2026-08-20-final-product-acceptance-beta28.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` | LOCAL has one canonical owner UUID with Telegram identity; Canary and Production keep separate DB, sessions, cookies and storage | Google OAuth and transactional email remain `EXTERNAL BLOCKED`; four Google/Resend secrets are not rotated in this closeout |
| Admin / Release Center | `BETA` | One environment/release module exposes DEV, Canary, Production, compare and pipeline. LOCAL submits a signed request; only Canary/Production may decide from authoritative registry state | beta.28 live browser acceptance is pending |
| Release security | `BETA` | Exact artifact, exact candidate, responder environment and decision TTL are verified client-side; server request signature, timestamp and nonce provide fail-closed replay protection | Real negative-path probes and final promotion evidence are pending |
| Test isolation | `AVAILABLE` | Every test receives separate disposable Production/Development roots; tracked governance baselines are copied there; any live `data/` mutation fails the suite | Full mandatory CI must confirm on hosted/self-hosted runners |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only chart source; accepted history/realtime architecture is unchanged | Licensed live acceptance must be repeated in LOCAL and Canary; an external feed never grants execution authority |
| Charts | `BETA` | Aurora Desktop chart pipeline, realtime bars and price marker baseline are preserved | Real browser checks for multiple symbols/timeframes and stale marker are pending in this closeout |
| NinjaTrader / Connector | `PARTIAL` | NinjaTrader remains the execution/backtest/runtime truth and is not required for independent TopstepX charts | Physical enrollment of a new Connector device requires Windows/NinjaTrader interaction and is reported separately, never simulated |
| Documents | `BETA` | Governance source, compact revision UI, legal DRAFT status and Documents surface exist | Browser parity and access-control sweep are pending |
| AI agents | `PARTIAL` | Vitek, orchestration and specialist surfaces exist | Per-workspace team and some external-provider paths remain incomplete |
| Legal | `IN DEVELOPMENT` | Structured legal package exists | It remains DRAFT until owner/legal decisions and counsel review |

## Operational identity before beta.28

| Environment | Live/ready | Version | Git SHA | Runtime artifact SHA256 |
| --- | --- | --- | --- | --- |
| Canary | `200 / 200` | `0.10.0-beta.27` | `1f3e2ce7198fec5a90e85d9b49e7a086103e4b62` | `A905E784BD2794F8ACC1760D1697A1B410FC96C24A5BCD25223B8D48FD2EC270` |
| Production | `200 / 200` | `0.10.0-beta.26` | `3353e3836306dca4628c759064139cdac94517e0` | `27B6316E934F0D727B9D158B34EE601A0A59EF78F0D71B484DD29ADD37617AAB` |

These rows are the starting point. They must be superseded with one exact
beta.28 artifact only after Canary acceptance and same-artifact Production
promotion.

## Deprecated current-state claims

- Do not use the 2026-08-14 beta.1 / `1fae1f39` snapshot as current live state.
- Do not describe the combined Admin environment/release UI or LOCAL-driven
  server-authoritative promotion as unfinished; they are implemented.
- Do not treat DRAFT legal documents as effective terms.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Replaced obsolete beta.1 state with verified beta.27 Canary, beta.26 Production and beta.28 final-acceptance scope.
-->
