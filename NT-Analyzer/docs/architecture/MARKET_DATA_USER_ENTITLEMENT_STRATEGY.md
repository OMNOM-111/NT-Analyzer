# StratForge Market Data Pivot: Bring Your Own Market Data (BYOMD)

Local onboarding demo source: BETA (Local), [manual acceptance PASS](../changelog/2026-09-23-preview-parity-account-lifecycle.md).
An active bounded trial with chart capability and no own live provider receives
`demo_replay` when redistribution is not authorized: deterministic synthetic
educational candles, explicitly DEMO, never provider quotes. Normal and Preview
accounts use the same decision. No live upstream lease or owner fan-out is
allowed. Both existing flags remain mandatory for `shared_trial`; expired or
denied trial remains denied.

Status: Development implementation plus connector prototypes. The owner
TopstepX hub is accepted for the owner's own charts, while unrelated-user
redistribution remains fail-closed. Personal credentialed connectors remain
disabled/unverified until account-specific acceptance and contract review.

This document establishes the strategic, legal, and technical framework for the user-owned market data model. Under this architecture, StratForge remains free for the first 100 users by avoiding centralized enterprise data subscriptions, shifting the entitlement burden to the end-users.

## 1. Strategic Goals

- **No implied redistribution:** a StratForge product trial is not a provider or
  exchange market-data grant. The owner feed is not shared with unrelated users
  unless written authority is represented by both explicit runtime policy gates.
- **Optional Enterprise Provider:** Databento is reclassified as `OPTIONAL_ENTERPRISE_PROVIDER`, disabled by default, not required for the MVP, and blocked from auto-failover until user-explicit shadow parity checks pass.
- **Compliance & Anti-Scraping:** No web scraping, credential sharing, or private API interception is permitted. All user connections are authenticated using official protocols.
- **Fair-Use Multi-Chart Fanout:** 64 charts do not create 64 upstream connections. Connections are multiplexed per unique contract at the user's adapter level.

---

## 2. UserMarketDataEntitlement Schema

Every market data stream must be validated against a user's entitlement record. Plaintext credentials (passwords, tokens, API keys) must be stored encrypted using `app.secure_store` (backed by Windows DPAPI) and never stored in plaintext in databases, logs, or UI JSON responses.

### Fields
| Field | Type | Description |
|---|---|---|
| `workspace_id` | `str` | Logical workspace partition. |
| `user_id` | `str` | Owner of the entitlement. |
| `provider` | `str` | Provider ID (e.g., `ninjatrader`, `rithmic`, `topstep`, `cqg_tradovate`). |
| `account_id` | `str` | User's brokerage/platform account ID. |
| `entitlement_type` | `str` | `live`, `delayed`, `replay`, or `demo`. |
| `exchanges` | `List[str]` | List of authorized exchanges (e.g., `CME`, `CBOT`). |
| `channels` | `List[str]` | Allowed schemas/channels (e.g., `trades`, `quotes`). |
| `live_eligible` | `bool` | True if the connection can paint live composites. |
| `expiration` | `str` (ISO) | Expire time of token/credentials. |
| `sharing_scope` | `str` | Partitioning scope (default: `private`). |
| `API_access_enabled` | `bool` | Whether external API connections are permitted. |
| `credentials_ref` | `str` | Identifier mapping to `app.secure_store` key. |
| `runtime_state` | `str` | `CONNECTING`, `AUTHENTICATED`, `LIVE`, `DEGRADED`, `ERROR`, `DISABLED`. |

---

## 3. Per-User Cache & Route Isolation

To comply with exchange agreements (e.g., CME Group), data from User A must **never** be served to User B.

### Cache Key Structure
Cache keys are isolated per user group and workspace:
```text
md:v1:private:<workspace_id>:<user_id>:<account_id>:<provider>:<exchange>:<exact_contract>:<channel>:<timeframe>:...:epochN
```

Shared cache keys are permitted **only** for:
- Instrument metadata (definitions, tick sizes, point values).
- Trading session templates.
- Demo/Replay sessions.
- Publicly available/unrestricted historical files.

The Development transport admission order is fixed and fail-closed:

1. owner runtime;
2. verified private user-owned provider entitlement;
3. fresh online personal NinjaTrader Connector bound to that user/workspace;
4. a bounded shared trial only when both `remote_server_authorized` and
   `redistribution_authorized` are explicitly true;
5. deny.

HTTP bars/cache and WebSocket subscriptions/events use the same server-owned
scope. Browser payloads never supply provider credentials, account ids or a
trusted entitlement assertion. Live sockets are periodically revalidated and
released immediately when the grant expires or source changes.

---

## 4. Feasibility Audit of the Four Connectors

### A. NinjaTrader Local Bridge
- **Implementation:** authenticated localhost IPC, Connector protocol and
  exact-contract export.
- **Scope:** one user's local NinjaTrader process; no cross-user redistribution is
  implemented by this path.
- **Acceptance:** Bridge build and automated IPC contracts pass. The current
  workstation Connector is bound to Canary but is not enrolled and has no
  authenticated heartbeat/market-data streams; live callback, disconnect,
  fallback and recovery still require the owner-controlled physical NT run.
- **Contract note:** permitted use depends on the owner's NinjaTrader/data-provider
  agreements; this repository does not declare those rights on their behalf.

### B. TopstepX / ProjectX Connector
- **Official API:** ProjectX REST plus SignalR/WebSocket market hub. The owner
  adapter is the accepted read-only chart source in the current beta.29 hub, but
  this acceptance does not authorize a second user to consume that entitlement.
- **Credentials:** TopstepX username plus ProjectX API key, not a Tradovate login.
- **Current published cost (verified 2026-07-17):** Topstep says $29/month, or
  $14.50/month with its published trader code; prices can change.
- **Runtime restriction:** Topstep says trading API activity must originate from
  the trader's personal device and prohibits VPN/VPS/remote-server use. Therefore
  this connector must not be enabled on a shared/cloud host.
- **Sandbox:** Topstep currently states that no sandbox is available, so production
  claims remain blocked pending a separately authorized owner credential run.
- Official references: [TopstepX API Access](https://help.topstep.com/en/articles/11187768-topstepx-api-access),
  [ProjectX real-time API](https://gateway.docs.projectx.com/docs/realtime/).

### C. Rithmic Connector
- Rithmic publishes R | API+ developer capabilities, but this repository only has
  a credential schema placeholder. No vendor session, subscription or backfill is
  implemented, and no price/session/legal claim is accepted here.
- Contract and redistribution terms must be verified for the owner's broker/prop
  relationship before implementation or testing.
- Official reference: [Rithmic developer APIs](https://www.rithmic.com/documentation).

### D. CQG / Tradovate Connector
- This repository only has a credential schema placeholder; it does not implement
  a CQG or Tradovate vendor session.
- Access, pricing, display, server-processing, redistribution and session limits
  are broker/account-specific and must be confirmed from the applicable current
  agreement before implementation.

---

## 5. Implementation Roadmap

1. **Phase 1:** Complete physical NinjaTrader per-user Connector acceptance and
   signed installer publication.
2. **Phase 2:** Complete user-owned TopstepX / ProjectX opt-in acceptance on the
   user's authorized device/session; keep the owner shared feed denied for
   unrelated users unless written distribution authority exists.
3. **Phase 3:** Rithmic connector configuration interface & integration.
4. **Phase 4:** CQG/Tradovate connector integration.
5. **Phase 5:** Per-user failover between user's own connected sources.
