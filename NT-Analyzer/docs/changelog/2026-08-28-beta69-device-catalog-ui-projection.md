# beta.69 — Device-backed Strategy Catalog in Backtesting UI

Status before release: **IMPLEMENTATION VERIFIED / RELEASE PENDING**.

## Reproduced acceptance gap

The signed `snapshot_runtime` flow and `/api/catalog` already contained the
four real VMNINJA strategy identifiers and four supported NinjaTrader
commission templates. In the real Canary and Production pages, however, the
strategy selector showed only `SampleMACrossOver` while the commission selector
showed all four templates.

The first divergence was the Backtesting page itself: commission templates
were read from authoritative `/api/catalog`, but strategy options were still
read from the legacy `/api/strategies` endpoint. On Linux that legacy endpoint
uses the conservative local fallback and cannot represent the enrolled Windows
device catalog.

## Scoped correction

- The Backtesting strategy selector now uses the same authoritative
  `/api/catalog` response already used for commission templates and parameter
  metadata.
- Device-backed display names and exact NinjaScript class identifiers are both
  visible when they differ.
- Fresh, stale/offline, missing and unavailable device-catalog states are
  labelled beside the selector. A failed catalog request produces an empty,
  explicitly unavailable list instead of silently substituting the legacy
  fallback.
- LOCAL continues to use its local NinjaTrader catalog. Canary remains a
  read-only projection, while Production remains the only Connector execution
  authority.

No Connector protocol, NinjaTrader DLL, server job transport, worker
scheduling, TopstepX, SignalR, market-data or chart behavior changed.
