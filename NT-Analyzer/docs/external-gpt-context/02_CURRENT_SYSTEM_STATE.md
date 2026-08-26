# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-26T18:22:14Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Verified deployed artifact Git SHA: `ae9c5c913e4a3250dd978ce2bf682e52590e82ef`
- Current Production version/build/artifact when known: `0.10.0-beta.48`; `sf-0.10.0-beta.48-ae9c5c913e4a-20260826T181306Z`; runtime SHA256 `F7856E1EFEEEC6CDACECA48DB4851FFEA9F59CE31F90BEFE6BCAD6ABF6787ED6`
- Current live release: `0.10.0-beta.48`, accepted Canary and Production
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL

## Evidence modes

- Repository evidence: merged PR #182 root-cause fix and PR #183 beta.48
  identity, both mandatory CI `5/5` GREEN.
- Operational evidence: Release Center candidate/deployments, public
  `/api/ready`, server symlinks and read-only Production PostgreSQL audit/mirror
  queries.
- Canonical release snapshot:
  [2026-08-26-beta48-live-connector-storage-reconciliation.md](../changelog/2026-08-26-beta48-live-connector-storage-reconciliation.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` | One canonical owner UUID is preserved across isolated environments; Telegram QR/one-tap confirmation uses the shared environment-routed bot flow | Google OAuth and transactional email remain separately `EXTERNAL BLOCKED`; four Google/Resend secrets were not rotated |
| User entry and trial access | `BETA` | Anonymous preview access is removed. A verified new account receives one full seven-day product trial; owner extension records actor, reason and before/after history | Product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | Development creates one signed immutable artifact, Canary records acceptance and Production promotes the same artifact through the server-authoritative control plane | any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Full beta.48 regression passed `2033 passed, 32 skipped, 0 failed`; live data roots are excluded from test fixtures | real-PostgreSQL groups require their explicit test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was not changed in beta.48 | cross-user owner-feed redistribution remains `EXTERNAL BLOCKED` without written authority |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | Existing Production installation recovered without reenrollment. Challenge, signed hello, market-data ingest and repeated heartbeats passed; installation is `online` | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material |
| Documents | `BETA` | Current handoff and Context Pack reflect beta.48; detailed technical history lives in changelog rather than current document bodies | legal publication remains separate |
| Legal | `IN DEVELOPMENT` | Structured legal package exists and remains DRAFT | owner/legal decisions and counsel review are still required |

## Current operational identity

| Environment | Version | Git SHA | Build ID | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- | --- |
| Canary | `0.10.0-beta.48` | `ae9c5c913e4a3250dd978ce2bf682e52590e82ef` | `sf-0.10.0-beta.48-ae9c5c913e4a-20260826T181306Z` | `F7856E1EFEEEC6CDACECA48DB4851FFEA9F59CE31F90BEFE6BCAD6ABF6787ED6` | accepted / ready |
| Production | `0.10.0-beta.48` | same | same | same | live / ready / Connector online |

Archive SHA256:
`B9C56184222AE4DADF6C979949A7FEC6A31F23D6048663425DD0BBCD69894E97`.
Both environments use release-directory suffix
`production_data/releases/0.10.0-beta.48-ae9c5c913e4a`; previous/rollback is
`0.10.0-beta.47-a40367fe8027`.

## Deprecated current-state claims

- beta.29–beta.47 release identities are history, not current live state.
- The target Production installation is no longer offline or blocked by
  `sf_connector_installations_workspace_id_fkey`.
- DRAFT legal documents are not effective terms.
- A StratForge product trial is not a provider/exchange redistribution grant.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-26T18:22:14Z | GPT-5.5 через Codex по запросу owner | Replaced stale beta.31/beta.29 state with exact beta.48 live identity and the verified Production Connector recovery.
-->
