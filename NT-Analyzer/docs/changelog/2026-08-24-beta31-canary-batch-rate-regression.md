# Beta.31 Canary Batch Rate Regression and Beta.32 Correction

- Date: 2026-08-24 UTC
- Clean beta.31 SHA: `8e83d4ccbad9d9fadf10109f0afdd6b3ce9fe6eb`
- Status: `BETA.31 CANARY NOT ACCEPTED / BETA.32 DEVELOPMENT`
- Production: unchanged accepted `0.10.0-beta.29`

## Evidence

The signed beta.31 artifact passed its original viewport correction: two
authenticated 36-chart Canary clients remained live for `13m26s`; both ended
`36/36`, readiness passed `20/20`, and exact MNQ/MES WebSocket price, last-bar
close and colored right-side marker matched in both clients. Loaded chart
assets matched the clean artifact bytes.

Acceptance remained open while the same UI changed MNQ through 1m and 15m.
The 15m request then returned HTTP 429. Authoritative PostgreSQL rate buckets
showed `api.write=145–183/min` against the 120/min mutation limit. The first
divergence was not TopstepX or SignalR: the read-only consolidated chart route
`POST /api/ops/runtime/bars/batch` was classified by HTTP method as a write.

Beta.32 classifies this one endpoint as `read` while preserving request shape,
authorization, gateway fan-out, TopstepX session ownership, cache/failover,
rollover, realtime events and rendering. A regression pins this action class.

Remote Admin also exposed a Diagnostics button for an endpoint deliberately
denied by the Cloudflare ingress. The security deny remains intact; Canary and
Production now disable that local-only control and explain that safe
Worker/Telegram/Connector status is already shown. Development keeps the real
local NinjaTrader/bridge-log diagnostic.

No beta.31 acceptance or Production promotion was recorded.
