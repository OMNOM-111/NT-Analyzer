# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-23T21:36:03Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: beta.29 remains live in Canary and Production; a new Development-only trial/access and per-user market-data admission candidate is based on `653f2b5bcfae2597dc0d14a22f07e741acd84cc8`
- Candidate in this closeout: unversioned Development candidate; no Canary or Production deployment yet
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL
- Acceptance note: beta.29 remains the accepted live release. The new Development candidate has automated/browser LOCAL and physical Development Connector acceptance; PR/CI and a new immutable release cycle remain open.
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
| User entry and trial access | `IN DEVELOPMENT` | Anonymous blurred/preview entry is removed in the Development candidate. A newly verified human registration activates one non-renewing full seven-day trial per canonical account; owner can extend by days or exact UTC date with immutable before/after history | not released; legacy already-issued `pending_owner` challenges remain supported only for migration/recovery |
| Post-trial account | `IN DEVELOPMENT` | Expiry does not block the account. The authenticated baseline keeps profile, Documents, practice and personal provider/Connector setup; shared live charts require both an active extension and explicit remote-server/redistribution authority, while a verified user-owned TopstepX or fresh personal Connector can authorize the chart source independently | browser and physical provider acceptance still required |
| Admin / Release Center | `BETA` | One environment/release module exposes DEV, Canary, Production, compare and pipeline. LOCAL submits a signed request; only Canary/Production may decide from authoritative registry state. The corrected ordinary approve→promote flow completed in Production | no release-control blocker remains |
| Release security | `BETA` | Exact artifact, exact candidate, responder environment and decision TTL are verified; server signature/timestamp/nonce provide fail-closed replay protection. Final Production deployment recorded signature/readiness/identity and same-artifact evidence | rotate only through a future owner-approved release cycle |
| Test isolation | `AVAILABLE` | Every test receives separate disposable Production/Development roots and any live `data/` mutation fails the suite. Current candidate full local regression passed `1945 passed, 32 skipped, 0 failed`; custom runner passed `13/13` | live PostgreSQL integration groups remain intentionally skipped without their test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only chart source. Beta.29 preserves history/SignalR/cache/failover and fixes only reproduced consumer ref/disconnect observability defects | the owner gateway does not grant cross-user redistribution rights |
| Owner market-data gateway | `AVAILABLE` | Production is the single designated hub; Canary/Development consume it. A 12-page Development load held one gateway SignalR connection and two wire subscriptions, made zero direct provider/loginKey calls, then returned browser/logical refcounts exactly to baseline | unrelated-user redistribution remains `EXTERNAL BLOCKED` pending written authority and entitlement mapping |
| Per-user market-data admission | `IN DEVELOPMENT` | One fail-closed resolver now gates HTTP and same-origin WebSocket delivery: owner runtime, verified private provider, fresh online personal Connector, or a bounded shared trial only when both remote-server and redistribution authority are explicitly configured. Cache/broadcast scope prevents User A data from falling through to User B or the owner feed | shared trial charts remain denied under the current false redistribution policy |
| Charts | `BETA` | Beta.29 Development load plus authenticated Canary/Production clients showed matching MES/MNQ closes and colored live markers with NinjaTrader OFF; closed-market heartbeat kept unchanged prices live honestly | a moving raw trade could not be generated while CME was closed |
| Responsive UI | `BETA` | 84/84 page/viewport checks passed from 2560×1440 to 360×800; real 390×844 pointer-click journeys passed core UI/Admin modules. The byte-identical Production artifact had zero whole-document overflow at 390×844 and 768×1024 | wider product design acceptance remains independent from functional responsiveness |
| NinjaTrader / Connector | `BETA` | NinjaTrader `8.1.7.2` runs Development Connector `0.4.1-dev.14`: retained device-owned enrollment, signed hello/heartbeat, two configured MNQ/MES 5m history/live streams and bounded transport drain all passed; a safe synthetic demo-backtest completed with no real orders. NinjaTrader remains execution/backtest/runtime truth and is not required for independent TopstepX charts | public Production Connector download remains `EXTERNAL BLOCKED` on authorized Authenticode material; one physical NinjaTrader instance binds to one environment at a time |
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
- Do not interpret a StratForge product trial as a provider/exchange redistribution
  grant. The two permissions are deliberately independent.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Replaced obsolete beta.1 state with verified beta.27 Canary, beta.26 Production and beta.28 final-acceptance scope.
2026-08-21T00:53:04Z | GPT-5.5 через Codex по запросу owner | Recorded the first beta.28 Canary candidate as not accepted after a live archive/runtime digest mismatch; Production remained beta.26.
2026-08-21T02:03:00Z | GPT-5.5 через Codex по запросу owner | Recorded the non-accepted 8865fad0 Canary artifact and scoped isolated governance-ledger hydration correction; Production remained beta.26.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Recorded 2790fb43 Canary visual acceptance and the real approved_for_production authoritative-gate blocker; Production remained beta.26.
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Recorded final 36600dba signed identity, 610-second exact MES/MNQ 5m Canary PASS and same-artifact Production live promotion.
2026-08-23T01:29:45Z | GPT-5.5 через Codex по запросу owner | Opened beta.29 release state after Development fan-out/responsive acceptance; preserved beta.28 as current live identity and recorded the cross-user entitlement blocker explicitly.
2026-08-23T02:27:02Z | GPT-5.5 через Codex по запросу owner | Closed beta.29 as the current live Canary/Production identity with exact artifact, CI, browser chart, gateway and responsive evidence; beta.28 moved to rollback-only status.
2026-08-23T21:36:03Z | GPT-5.5 через Codex по запросу owner | Opened the Development-only unified trial/access candidate, removed anonymous preview entry, recorded per-user HTTP/WS market-data admission and retained the cross-user redistribution and physical Connector gates honestly.
2026-08-24T01:52:25Z | GPT-5.5 через Codex по запросу owner | Recorded physical Development Connector dev.14 acceptance, exact package identity, authenticated MNQ/MES ingestion and safe demo-backtest; retained PR/release, Authenticode and redistribution gates.
-->
