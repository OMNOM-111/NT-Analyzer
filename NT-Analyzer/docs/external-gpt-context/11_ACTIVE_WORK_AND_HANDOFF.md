# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-26T18:22:14Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Verified deployed artifact Git SHA: `ae9c5c913e4a3250dd978ce2bf682e52590e82ef`
- Current Production version/build/artifact when known: `0.10.0-beta.48`; `sf-0.10.0-beta.48-ae9c5c913e4a-20260826T181306Z`; runtime SHA256 `F7856E1EFEEEC6CDACECA48DB4851FFEA9F59CE31F90BEFE6BCAD6ABF6787ED6`
- Scope: Production LIVE Connector storage/schema closeout
- Status: DONE

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` pack-wide verification baseline; deployed artifact `ae9c5c913e4a3250dd978ce2bf682e52590e82ef` |
| Root-cause fix | PR #182, merge `51bf8705ea213940f046b888be371fb476cc0229` |
| Release identity | PR #183, merge/artifact SHA `ae9c5c913e4a3250dd978ce2bf682e52590e82ef` |
| Release | `0.10.0-beta.48`, candidate `rc_f4554de031954dca87bff3b2c54cfa0e`, artifact `art_dba8625e0b3b427896f8d1ead2382fa2` |
| Build | `sf-0.10.0-beta.48-ae9c5c913e4a-20260826T181306Z` |
| Archive / runtime hashes | `B9C56184…4E97` / `F7856E1E…7ED6` |
| Canary | accepted, ready, deployment `dep_a5abb0353395450889ff3d1013dc9050` |
| Production | same immutable artifact, live/ready, deployment `dep_e955efac5b1a4d189ba3b6b521aa8bd4` |
| Release parity | same release directory `0.10.0-beta.48-ae9c5c913e4a`; previous/rollback beta.47 |
| LIVE Connector | existing installation online; challenge, signed hello, market-data ingest and repeated heartbeat sequence `24 → 34 → 38` PASS |
| Production refusals | `0` after beta.48 live |
| Tests | full `2033 passed, 32 skipped, 0 failed`; targeted `131 passed, 19 skipped, 0 failed`; CI `5/5` |
| Market-data baseline | preserved; no TopstepX/SignalR/session/history/cache/failover/rendering change |
| Secret rotation | explicitly deferred; Google/Resend secrets unchanged |

## Completed actions

1. beta.47 refusal audit identified exact PostgreSQL constraint
   `sf_connector_installations_workspace_id_fkey`.
2. Production migrations were verified current through migration 18; no schema
   deployment gap existed.
3. The actual write path was traced to whole-document Connector mirror
   projection and its retained terminal orphan history.
4. A bounded fail-closed reconciliation was implemented with a regression that
   reproduces the real Production data shape.
5. Mandatory CI passed; the scoped fix and beta.48 identity merged cleanly.
6. One signed immutable artifact was built, deployed to Canary, accepted and
   promoted unchanged to Production.
7. The already enrolled NinjaTrader device recovered automatically. No DLL
   reinstall, device reset or enrollment replacement was needed.
8. Production audit and normalized rows proved challenge → signed hello →
   repeated heartbeat and accepted market-data ingest with no new refusal.

## Remaining boundaries, not blockers for this closeout

| Area | State | Boundary |
| --- | --- | --- |
| Cross-user shared owner feed | `EXTERNAL BLOCKED` | written provider/exchange distribution authority and per-user entitlement policy |
| Public Connector installer | `EXTERNAL BLOCKED` | authorized Authenticode signing tool/material |
| Google / Resend rotation | deferred | separate final security closeout; two Google Client Secrets and two Resend keys untouched |
| Legal publication | `IN DEVELOPMENT` | DRAFT until owner/legal decisions and counsel review |

## Next development boundary

No LIVE Connector release work remains from this checkpoint. Future product or
Connector changes must start from current `main`, preserve the accepted
market-data baseline and repeat the normal clean CI → one artifact → Canary
acceptance → exact same artifact Production cycle.

## Canonical evidence

- [beta.48 LIVE Connector closeout](../changelog/2026-08-26-beta48-live-connector-storage-reconciliation.md)
- [current clean closeout](../current/CLEAN_CLOSEOUT_HANDOFF.md)
- [environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-26T18:22:14Z | GPT-5.5 через Codex по запросу owner | Closed the beta.48 Production LIVE Connector task with exact release, CI, root-cause and live recovery evidence; only explicit external/security boundaries remain.
-->
