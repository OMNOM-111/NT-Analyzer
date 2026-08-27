# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-27T22:33:11Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Verified deployed artifact Git SHA: `60d922b2600d1d31e611c7a670cbddebc889beef`
- Current Production version/build/artifact when known: `0.10.0-beta.61`; `sf-0.10.0-beta.61-60d922b2600d-20260827T175814Z`; runtime SHA256 `E9195140BDB22C53EB83405FCF5655E76FD60068637FED1A0CAE35B1A769AF53`
- Current live release: `0.10.0-beta.61`, accepted Canary and Production
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL

## Evidence modes

- Repository evidence: merged PR #198 worker scheduler correction with
  mandatory CI `5/5` GREEN.
- Operational evidence: Release Center candidate/deployments, public
  `/api/ready`, server symlinks and read-only Production PostgreSQL audit/mirror
  queries.
- Canonical release snapshot:
  [2026-08-27-beta61-worker-idle-performance.md](../changelog/2026-08-27-beta61-worker-idle-performance.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` | One canonical owner UUID is preserved across isolated environments; Telegram QR/one-tap confirmation uses the shared environment-routed bot flow | Google OAuth and transactional email remain separately `EXTERNAL BLOCKED`; four Google/Resend secrets were not rotated |
| User entry and trial access | `BETA` | Anonymous preview access is removed. A verified new account receives one full seven-day product trial; owner extension records actor, reason and before/after history | Product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | Development creates one signed immutable artifact, Canary records acceptance and Production promotes the same artifact through the server-authoritative control plane | any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Full beta.61 regression passed `2134 passed, 32 skipped, 0 failed`; live data roots are excluded from test fixtures | real-PostgreSQL groups require their explicit test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was not changed in beta.61 | cross-user owner-feed redistribution remains `EXTERNAL BLOCKED` without written authority |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | The beta.60 accepted functional Connector baseline is preserved; beta.61 changed no Connector or market-data path | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material |
| Production worker queue | `AVAILABLE` | Eleven worker slots remain 4/4/2/1; empty workers use adaptive jittered backoff and one 30-second stale sweeper. Live worker CPU fell below 6% and worker DB activity fell about 88-92% | Production total DB activity also includes the separate active Connector/API mirror path |
| Documents | `BETA` | Current handoff and Context Pack reflect beta.61; detailed technical history lives in changelog rather than current document bodies | legal publication remains separate |
| Legal | `IN DEVELOPMENT` | Structured legal package exists and remains DRAFT | owner/legal decisions and counsel review are still required |

## Current operational identity

| Environment | Version | Git SHA | Build ID | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- | --- |
| Canary | `0.10.0-beta.61` | `60d922b2600d1d31e611c7a670cbddebc889beef` | `sf-0.10.0-beta.61-60d922b2600d-20260827T175814Z` | `E9195140BDB22C53EB83405FCF5655E76FD60068637FED1A0CAE35B1A769AF53` | accepted / ready |
| Production | `0.10.0-beta.61` | same | same | same | live / ready |

Archive SHA256:
`E61B8C9293308D522AE3017EEBCF09B73A01CABA689EA8636A0C2BDA12236534`.
Both environments use release-directory suffix
`0.10.0-beta.61-60d922b2600d`; previous/rollback is
`0.10.0-beta.60-101d7c447e2d`.

## Deprecated current-state claims

- beta.29–beta.60 release identities are history, not current live state.
- The target Production installation is no longer offline or blocked by
  `sf_connector_installations_workspace_id_fkey`.
- DRAFT legal documents are not effective terms.
- A StratForge product trial is not a provider/exchange redistribution grant.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-26T18:22:14Z | GPT-5.5 через Codex по запросу owner | Replaced stale beta.31/beta.29 state with exact beta.48 live identity and the verified Production Connector recovery.
2026-08-27T22:33:11Z | GPT-5.5 через Codex по запросу owner | Advanced current operational identity to beta.61 and recorded the scoped worker idle performance closeout while preserving accepted market-data and Connector baselines.
-->
