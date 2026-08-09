# StratForge Market Data Pivot: Bring Your Own Market Data (BYOMD)

История поправки: 2026-08-09; внёс `GPT-5.5 через Codex по запросу owner`; scope: актуализировать TopstepX read-only implementation, canonical enable flag и remote/redistribution policy gates.

Status: architecture plus connector implementation. NinjaTrader and TopstepX
read-only paths have automated contract coverage; credentialed vendor acceptance
and contractual remote/redistribution rights remain external release gates.

This document establishes the strategic, legal, and technical framework for the user-owned market data model. Under this architecture, StratForge remains free for the first 100 users by avoiding centralized enterprise data subscriptions, shifting the entitlement burden to the end-users.

## 1. Strategic Goals

- **Zero Platform Market Data Costs:** StratForge does not purchase or redistribute live market data for retail users.
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

Global cache keys are permitted **only** for:
- Instrument metadata (definitions, tick sizes, point values).
- Trading session templates.
- Demo/Replay sessions.
- Publicly available/unrestricted historical files.

---

## 4. Feasibility Audit of the Four Connectors

### A. NinjaTrader Local Bridge
- **Implementation:** existing authenticated localhost IPC and exact-contract export.
- **Scope:** one user's local NinjaTrader process; no cross-user redistribution is
  implemented by this path.
- **Acceptance:** Bridge build and automated IPC contracts pass; live callback,
  disconnect and recovery scenarios still require the owner-controlled NT run.
- **Contract note:** permitted use depends on the owner's NinjaTrader/data-provider
  agreements; this repository does not declare those rights on their behalf.

### B. TopstepX / ProjectX Connector
- **Official API:** ProjectX REST plus SignalR/WebSocket market hub. The adapter is
  read-only and enabled with `NTA_ENABLE_TOPSTEPX_MARKET_DATA=1`; the legacy
  `NTA_ENABLE_TOPSTEPX_LIVE` flag is read only for backward-compatible disable.
- **Credentials:** TopstepX username plus ProjectX API key, not a Tradovate login.
- **Implementation:** auth, root-to-active/exact contract search, REST OHLCV bars,
  official realtime callbacks and reconnect/resubscribe are covered by automated
  contracts. Account/order/trade APIs are not used.
- **Current published cost (verified 2026-07-17):** Topstep says $29/month, or
  $14.50/month with its published trader code; prices can change.
- **Runtime restriction:** Topstep says trading API activity must originate from
  the trader's personal device and prohibits VPN/VPS/remote-server use. Therefore
  this connector remains fail-closed on a shared/cloud host unless written
  remote-server and market-data redistribution authorization is recorded through
  both protected policy flags. Without that authorization it is personal-device
  only; a public StratForge server needs another licensed server-side feed.
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

1. **Phase 1:** NinjaTrader per-user local bridge.
2. **Phase 2:** TopstepX / ProjectX opt-in local feasibility prototype; correct
   ProjectX contract IDs and SignalR targets are covered by mocks, but credentialed
   acceptance remains blocked.
3. **Phase 3:** Rithmic connector configuration interface & integration.
4. **Phase 4:** CQG/Tradovate connector integration.
5. **Phase 5:** Per-user failover between user's own connected sources.
