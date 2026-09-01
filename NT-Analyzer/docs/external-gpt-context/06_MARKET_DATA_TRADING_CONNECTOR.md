# 06. Market Data, Trading and Connector

- Context Pack document: 06_MARKET_DATA_TRADING_CONNECTOR.md
- Last verified UTC: 2026-08-26T23:46:20Z
- Verified against Git SHA: 22ed7097b4ac9e863304197e118b1d3ce5109e8a
- Verified deployed artifact Git SHA: `ae9c5c913e4a3250dd978ce2bf682e52590e82ef`
- Scope: NinjaTrader authority, Connector protocol, market-data gateway and trading safety gates
- Status: PARTIAL

## Non-negotiable current rules

1. NinjaTrader is the execution path and source of truth for fills, trades,
   metrics and runtime strategy state.
2. TopstepX is the primary independent read-only chart history/realtime source
   when configured.
3. Current chart order is TopstepX, then fresh personal NinjaTrader Connector,
   then another explicitly allowed provider, then honest offline/cache state.
4. A chart feed never authorizes an order; synthetic live candles are not
   invented and stale history is not labeled live.
5. One designated StratForge hub owns the authorized TopstepX loginKey and
   SignalR session. Browsers use same-origin `/ws/market-data`, receive no
   provider credentials and do not open their own upstream sessions.
6. Product access and provider/exchange permission are independent. Shared
   cross-user owner-feed delivery remains fail-closed without written authority
   and per-user entitlement mapping.

## Current status

| Area | Status | Current fact |
| --- | --- | --- |
| Connector protocol v1 | `BETA` | Pair/enroll/challenge/hello/heartbeat/market-data/commands use device-owned P-256 keys, bounded sessions and capabilities |
| Production LIVE Connector | `BETA` | Existing installation `inst_9rVbadz0rNu0xlbbfsVSnkvY` is `online`; no reenrollment was required |
| Functional NinjaTrader account data | `IN DEVELOPMENT` | beta.49 candidate requires a fresh signed account snapshot in addition to heartbeat; deployment and real AddOn restart acceptance are still pending |
| Read-only charts | `BETA` | Accepted TopstepX history/realtime, freshness, fan-out and marker baseline remains unchanged by beta.48 |
| Owner market-data gateway | `AVAILABLE` | One designated upstream fans out only to authorized scoped application consumers; browser delivery remains same-origin |
| Connector fallback | `BETA` | Fresh personal Connector bars are a separate chart fallback when the device is connected |
| Cross-user redistribution | `EXTERNAL BLOCKED` | Owner credentials and a product trial are not a provider/exchange distribution grant |
| Public Connector package | `EXTERNAL BLOCKED` | Authorized Authenticode tool/material is still required for public distribution |

## Production Connector root cause and correction

VMNINJA already had the correct DLL, device/DPAPI state, Production origin and
working DNS/TLS. beta.47 live audit proved repeated challenge requests but
named `sf_connector_installations_workspace_id_fkey` as the rejecting
constraint.

Production schema was current through migration 18. The authoritative
Connector document retained a revoked test installation whose workspace/user
had later been removed, 51 terminal sessions and 8 terminal commands with a
departed actor. Whole-document mirror projection attempted to insert that
history again during every valid challenge, so one historical orphan blocked
the active installation.

beta.48 keeps the authoritative JSON intact and omits only terminal orphan rows
from the constrained relational mirror. Revoked installations,
expired/revoked/superseded sessions and completed/failed/rejected/expired/
cancelled commands can be omitted only when their references are gone. Any
non-terminal orphan still denies the write fail-closed.

## Live Production evidence

| UTC | Evidence |
| --- | --- |
| `18:17:20Z` | challenge accepted and `challenge_issued` audited |
| `18:17:21Z` | signed hello accepted; active session created |
| `18:17:22Z` | Connector market-data batch accepted |
| `18:20:16Z` | active session sequence 24, fresh heartbeat |
| `18:21:35Z` | same session sequence 34, fresh heartbeat |
| `18:22:07Z` | same session sequence 38, fresh heartbeat |

Installation and normalized mirror stayed `online`; Connector version is
`0.4.2-dev.6`, NinjaTrader version `8.1.8.2`, environment binding
`production`. The first session reached sequence `114`. At each normal
15-minute TTL boundary the server returned expected `session_expired`, then the
Connector automatically completed a fresh challenge/hello within three
seconds. The next session reached sequence `113`; a third was active with
sequence `5` and fresh heartbeat at `18:48:01Z`. New `storage_constraint` or
other unexpected refusals after beta.48 became live: `0`.

The accepted batch produced an MES 09-26 1m snapshot. Its underlying source
timestamp was old, so the snapshot correctly remained stale; no false live
price claim is made. This closeout changed no TopstepX auth/session, SignalR,
history/realtime, rollover, cache/failover, WebSocket fan-out or chart rendering
file.

Transport `online` is no longer sufficient for a functional claim. The beta.49
candidate carries a bounded account snapshot in the existing signed heartbeat,
projects it only to the correct workspace (or the same owner's explicit
owner-training workspace), and reports heartbeat-without-data as degraded.
Development uses this signed path when a Connector installation is present,
instead of allowing an old local runtime directory or a Windows process check
to produce a false green state. This remains `IN DEVELOPMENT` until the server
artifact and Connector DLL pass real LOCAL/Canary/Production acceptance.

## Read-only versus execution boundaries

| Boundary | Can do | Cannot do |
| --- | --- | --- |
| TopstepX / chart provider | Supply authorized chart history and realtime | Authorize orders or grant redistribution rights |
| StratForge gateway | Deduplicate an authorized upstream and fan out scoped data | Expose credentials, create silent extra hubs or bypass entitlement |
| Connector market-data session | Deliver authenticated bounded OHLCV batches | Infer permissions beyond the session capabilities |
| NinjaTrader runtime | Backtest, manage runtime state and execute when explicitly allowed | Bypass product release, auth or trading safety gates |

## Change protection

The accepted market-data/chart pipeline is a protected baseline. Change
`market_data_*`, TopstepX auth/session, SignalR, rollover, cache/failover,
realtime or rendering only after a reproduced defect with targeted evidence.

## Canonical evidence

- [beta.48 LIVE Connector closeout](../changelog/2026-08-26-beta48-live-connector-storage-reconciliation.md)
- [Connector protocol v1](../architecture/CONNECTOR_PROTOCOL_V1.md)
- [market-data resilience plan](../architecture/MARKET_DATA_RESILIENCE_PLAN.md)
- `app/connector_protocol.py`
- `app/production_storage/core.py`
