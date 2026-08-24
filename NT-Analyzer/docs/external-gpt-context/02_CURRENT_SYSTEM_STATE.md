# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-24T16:33:38Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: PR #146 and governance sync PR #147 are merged into clean `main` at `8e83d4ccbad9`; beta.31 was deployed only to Canary and not accepted; Production remains on accepted beta.29
- Candidate in this closeout: beta.32 minimal read-only batch rate-class and remote Admin diagnostics correction
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL
- Acceptance note: beta.31 Canary passed a 13m26s two-client 36-chart soak and 20/20 readiness, but a subsequent MNQ 15m history load reproduced HTTP 429 because read-only `POST /api/ops/runtime/bars/batch` consumed the 120/min write bucket (`145–183/min`). It was not accepted or promoted. Beta.32 changes only that rate class and disables a remote-only Diagnostics control whose endpoint is intentionally denied by the external edge.
- Current Production version/build/artifact when known: `0.10.0-beta.29`; build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`; runtime artifact SHA256 `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`

## Evidence modes

- Repository evidence is clean beta.31 SHA `8e83d4ccbad9d9fadf10109f0afdd6b3ce9fe6eb`, its non-accepted Canary artifact and the scoped beta.32 correction branch.
- Operational evidence is queried from `/api/runtime/env`, `/api/live` and
  `/api/ready` and from Release Center candidate/deployment records. Canary
  reports non-accepted beta.31 while Production remains ready on beta.29.
- The canonical pre-release snapshot is
  [2026-08-24-beta31-canary-batch-rate-regression.md](../changelog/2026-08-24-beta31-canary-batch-rate-regression.md);
  the accepted live baseline is
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
| Test isolation | `AVAILABLE` | Every test receives separate disposable Production/Development roots and any live `data/` mutation fails the suite. Beta.31 full regression passed `1946 passed, 32 skipped, 0 failed`; combined market-data/gateway and governance/docs regression passed `121 passed` | live PostgreSQL integration groups remain intentionally skipped without their test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only chart source. Beta.29 preserves history/SignalR/cache/failover and fixes only reproduced consumer ref/disconnect observability defects | the owner gateway does not grant cross-user redistribution rights |
| Owner market-data gateway | `AVAILABLE` | Production is the single designated hub; Canary/Development consume it. Beta.31 consumers forward viewport `from_ts/to_ts`; the real Canary artifact then kept two 36-chart clients live for 13m26s with exact MNQ/MES markers and readiness `20/20`. Beta.32 only classifies the read-only consolidated chart POST under the read rate bucket | unrelated-user redistribution remains `EXTERNAL BLOCKED` pending written authority and entitlement mapping |
| Per-user market-data admission | `IN DEVELOPMENT` | One fail-closed resolver now gates HTTP and same-origin WebSocket delivery: owner runtime, verified private provider, fresh online personal Connector, or a bounded shared trial only when both remote-server and redistribution authority are explicitly configured. Cache/broadcast scope prevents User A data from falling through to User B or the owner feed | shared trial charts remain denied under the current false redistribution policy |
| Charts | `BETA` | Beta.31 Canary produced exact TopstepX price → close → colored marker in two 36-chart clients for 13m26s. The candidate was not accepted because an extra 15m history load exposed the batch rate-class 429; beta.32 fixes only that reproduced admission defect | fresh beta.32 PR/CI/artifact/Canary acceptance remains required |
| Responsive UI | `BETA` | 84/84 page/viewport checks passed from 2560×1440 to 360×800; real 390×844 pointer-click journeys passed core UI/Admin modules. The byte-identical Production artifact had zero whole-document overflow at 390×844 and 768×1024 | wider product design acceptance remains independent from functional responsiveness |
| NinjaTrader / Connector | `BETA` | NinjaTrader `8.1.7.2` runs Development Connector `0.4.1-dev.14`: retained device-owned enrollment, signed hello/heartbeat, two configured MNQ/MES 5m history/live streams and bounded transport drain all passed; a safe synthetic demo-backtest completed with no real orders. NinjaTrader remains execution/backtest/runtime truth and is not required for independent TopstepX charts | public Production Connector download remains `EXTERNAL BLOCKED` on authorized Authenticode material; one physical NinjaTrader instance binds to one environment at a time |
| Documents | `BETA` | Governance source, compact revision UI, legal DRAFT status and canonical revision hydration are in the accepted artifact; Canary owner showed CHARTER revisions through №7 | this post-release operational handoff is repository evidence for the next artifact and does not mutate the accepted runtime |
| AI agents | `BETA` | Vitek, orchestration and specialist surfaces exist | Per-workspace team and some external-provider paths remain incomplete |
| Legal | `IN DEVELOPMENT` | Structured legal package exists | It remains DRAFT until owner/legal decisions and counsel review |

## Current operational identity

| Environment | Live/ready | Version | Git SHA | Runtime artifact SHA256 |
| --- | --- | --- | --- | --- |
| Canary | deployed / NOT ACCEPTED; chart soak passed but MNQ 15m load reproduced HTTP 429 | `0.10.0-beta.31` | `8e83d4ccbad9d9fadf10109f0afdd6b3ce9fe6eb` | `826625D73702EB8D63E5EF2ABE0F2B291AB1FB8616B3E3C52D4AA70E48B8E7EE` |
| Production | live/ready + authenticated owner UI/charts/responsive PASS | `0.10.0-beta.29` | `4d15f1d2250e2c52bde02b902d88ec7aad043543` | `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379` |

The accepted Production archive SHA256 is
`882FF3520DDD43BF65925F3DFA5AA95DA56107336DA98EFDC64146A81981195B`;
its active release-directory suffix is
`production_data/releases/0.10.0-beta.29-4d15f1d2250e` (the environment-owned
absolute data root is intentionally not copied into this external pack).
The Production previous/rollback suffix is
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
2026-08-24T02:41:31Z | GPT-5.5 через Codex по запросу owner | Recorded clean owner-authorized PR #144 merge fb7d7f9b, repeated Connector heartbeat/history/live and safe UI demo-backtest #18782, and opened the beta.30 version-only immutable release preparation.
2026-08-24T04:22:21Z | GPT-5.5 через Codex по запросу owner | Recorded beta.30 as non-accepted Canary after reproduced HTTP-slot saturation, kept Production beta.29 unchanged and opened the scoped beta.31 viewport-range correction.
2026-08-24T16:33:38Z | GPT-5.5 через Codex по запросу owner | Recorded beta.31 as non-accepted after the real two-client soak exposed read-only chart POST traffic in the write bucket; opened beta.32 and retained the external Diagnostics deny.
-->
