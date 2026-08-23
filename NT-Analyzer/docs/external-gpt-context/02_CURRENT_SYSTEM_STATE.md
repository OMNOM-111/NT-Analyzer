# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-23T02:27:02Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: beta.29 implementation merge is live in Canary and Production; this operational docs-only closeout follows it
- Candidate in this closeout: `0.10.0-beta.29`
- Scope: Current factual subsystem snapshot only
- Status: DONE
- Acceptance note: PR/CI, immutable Canary acceptance and no-rebuild Production promotion completed; authenticated live UI/charts/responsive smoke passed on both server environments.
- Current Production version/build/artifact when known: `0.10.0-beta.29`; build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`; runtime artifact SHA256 `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`

## Evidence modes

- Repository evidence is merge `4d15f1d2250e` and its regression contracts.
- Operational evidence is queried from `/api/runtime/env`, `/api/live` and
  `/api/ready` and from Release Center candidate/deployment records. Canary and
  Production report the same beta.29 build/runtime digest and `ready` status.
- The canonical pre-release snapshot is
  [2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md);
  beta.28 is retained only as the previous/rollback slot and historical
  evidence in [2026-08-20-final-product-acceptance-beta28.md](../changelog/2026-08-20-final-product-acceptance-beta28.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` | LOCAL has one canonical owner UUID with Telegram identity; Canary and Production keep separate DB, sessions, cookies and storage | Google OAuth and transactional email remain `EXTERNAL BLOCKED`; four Google/Resend secrets are not rotated in this closeout |
| Admin / Release Center | `BETA` | One environment/release module exposes DEV, Canary, Production, compare and pipeline. LOCAL submits a signed request; only Canary/Production may decide from authoritative registry state. The corrected ordinary approve→promote flow completed in Production | no release-control blocker remains |
| Release security | `BETA` | Exact artifact, exact candidate, responder environment and decision TTL are verified; server signature/timestamp/nonce provide fail-closed replay protection. Final Production deployment recorded signature/readiness/identity and same-artifact evidence | rotate only through a future owner-approved release cycle |
| Test isolation | `AVAILABLE` | Every test receives separate disposable Production/Development roots and any live `data/` mutation fails the suite. Beta.29 full local regression passed `1924 passed, 32 skipped, 0 failed`; all five PR #142 jobs passed | live PostgreSQL integration groups remain intentionally skipped without their test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only chart source. Beta.29 preserves history/SignalR/cache/failover and fixes only reproduced consumer ref/disconnect observability defects | the owner gateway does not grant cross-user redistribution rights |
| Owner market-data gateway | `AVAILABLE` | Production is the single designated hub; Canary/Development consume it. A 12-page Development load held one gateway SignalR connection and two wire subscriptions, made zero direct provider/loginKey calls, then returned browser/logical refcounts exactly to baseline | unrelated-user redistribution remains `EXTERNAL BLOCKED` pending written authority and entitlement mapping |
| Charts | `BETA` | Beta.29 Development load plus authenticated Canary/Production clients showed matching MES/MNQ closes and colored live markers with NinjaTrader OFF; closed-market heartbeat kept unchanged prices live honestly | a moving raw trade could not be generated while CME was closed |
| Responsive UI | `BETA` | 84/84 page/viewport checks passed from 2560×1440 to 360×800; real 390×844 pointer-click journeys passed core UI/Admin modules. The byte-identical Production artifact had zero whole-document overflow at 390×844 and 768×1024 | wider product design acceptance remains independent from functional responsiveness |
| NinjaTrader / Connector | `BETA` | NinjaTrader remains the execution/backtest/runtime truth and is not required for independent TopstepX charts | Physical enrollment of a new Connector device requires Windows/NinjaTrader interaction and is reported separately, never simulated |
| Documents | `BETA` | Governance source, compact revision UI, legal DRAFT status and canonical revision hydration are in the accepted artifact; Canary owner showed CHARTER revisions through №7 | this post-release operational handoff is repository evidence for the next artifact and does not mutate the accepted runtime |
| AI agents | `BETA` | Vitek, orchestration and specialist surfaces exist | Per-workspace team and some external-provider paths remain incomplete |
| Legal | `IN DEVELOPMENT` | Structured legal package exists | It remains DRAFT until owner/legal decisions and counsel review |

## Current operational identity

| Environment | Live/ready | Version | Git SHA | Runtime artifact SHA256 |
| --- | --- | --- | --- | --- |
| Canary | live/ready + authenticated owner UI/Documents/charts PASS | `0.10.0-beta.29` | `4d15f1d2250e2c52bde02b902d88ec7aad043543` | `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379` |
| Production | live/ready + authenticated owner UI/charts/responsive PASS | `0.10.0-beta.29` | `4d15f1d2250e2c52bde02b902d88ec7aad043543` | `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379` |

Both rows are the same signed immutable artifact. Archive SHA256 is
`882FF3520DDD43BF65925F3DFA5AA95DA56107336DA98EFDC64146A81981195B`;
active release-directory suffix is
`production_data/releases/0.10.0-beta.29-4d15f1d2250e` (the environment-owned
absolute data root is intentionally not copied into this external pack).
Previous/rollback suffix for both environments is
`0.10.0-beta.28-36600dba3d73`.

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
2026-08-23T01:29:45Z | GPT-5.5 через Codex по запросу owner | Opened beta.29 release state after Development fan-out/responsive acceptance; preserved beta.28 as current live identity and recorded the cross-user entitlement blocker explicitly.
2026-08-23T02:27:02Z | GPT-5.5 через Codex по запросу owner | Closed beta.29 as the current live Canary/Production identity with exact artifact, CI, browser chart, gateway and responsive evidence; beta.28 moved to rollback-only status.
-->
