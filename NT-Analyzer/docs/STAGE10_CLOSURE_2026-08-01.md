# Stage 10 closure — Production migration and deployment

Date: 2026-08-01

Authority: this document supersedes dated Stage 9 status reports and earlier
Stage 10 current-state summaries. Historical evidence remains unchanged.

## Final decision

**STAGE 10 CLOSED**

**PRODUCTION RUNTIME OPERATIONAL**

**MIGRATION AND DEPLOYMENT PROJECT COMPLETE**

**STABLE CERTIFICATION NOT YET CLAIMED**

There are no open P0/P1 defects. `https://app.stratforges.com` and
`https://canary.stratforges.com` are served by Linux, while local Windows
Development remains an independent localhost contour. Live trading and real
payments are disabled.

## Completed architecture

| Contour | Current role and state |
|---|---|
| Local Development | Windows-only development runtimes with explicit `development` environment, local storage and localhost binding. The preserved owner runtime remains available at `127.0.0.1:8765` on dev.10. An exact-source dev.15 sandbox is independently live at `http://localhost:8766` with separate data roots and no Production credentials. |
| Canary | Linux instance `stratforge-linux-canary-01`; release-verification lane at `canary.stratforges.com`; ready on Server dev.15. |
| Production | Linux instance `stratforge-linux-production-01`; public application at `app.stratforges.com`; ready on Server dev.15. |

Canary and Production have separate API processes, canonical host/origin and
instance identities. They intentionally use the same authoritative Production
PostgreSQL/workspace state because canary validates the exact pending release
against the Production contract. Windows Development has a separate checkout,
data root, local store, integrations and process lifecycle. Stopping local
Development was previously proven not to affect either Linux endpoint.

## Exact release and Git state

| Item | Exact value |
|---|---|
| Production source commit | `f05f287d3233554049fa9086598905bacc46146b` |
| Production source branch | `codex/stage10-production` (fast-forward target: exact source commit above) |
| Development branch | `codex/stage10-development` (Production source plus documentation-only closure) |
| Server tag | `stratforge-server-v0.9.0-dev.15` at exact Production source |
| Preserved historical Server tag | `stratforge-server-v0.9.0-dev.13` |
| Closure tag | `stratforge-stage10-closed-2026-08-01` at the documentation closure commit |
| Linux current | `/home/stratforge/production_data/releases/0.9.0-dev.15-f05f287d` |
| Linux previous | `/home/stratforge/production_data/releases/0.9.0-dev.14-915832f2` |
| Server archive SHA-256 | `722B387DE6B0EDEABB90CDF2E732CBA858130E53A5A9F875D9220EFEC8A05172` |
| Server manifest SHA-256 | `C86E1DF4DADABBD2BE996088F57146135E8A628434F62E985A8CFBC9E0649F56` |
| Connector version | `0.4.2-dev.6` |
| Connector manifest SHA-256 | `21796A45682991AF3A84A03D25E972428ABF5F389AB7E2F84150F4D9231157E7` |
| Installed Connector DLL SHA-256 | `7ED279BA6FDA1B00734BA74B973D6F38D801C2B8F5C6E0B4CA4AA33AF2CA2990` |

dev.13 was the initial Linux cutover release. dev.14 closed canonical owner
workspace reconciliation. dev.15 is the immutable cache/auth completion patch
that is now current; dev.13 was not modified or retagged.

## Gate closure

| Gate | Result | Evidence summary |
|---|---|---|
| Public Linux cutover | PASS | `app` and `canary` ready on distinct Linux instance identities; Cloudflare promotion/rollback/promotion completed earlier. |
| Owner Production onboarding | PASS | Real owner login completed. Exactly one canonical owner user, one active owner workspace, one owner membership and one active owner session; profile complete; challenge consumed; owner role derived from protected numeric identity. |
| Authentication security | PASS | One-time browser nonce, same-origin enforcement, cancel/expiry/replay denial, server-side Telegram identity verification and blocked-account denial are covered by tests and canary probes. Previously verified contact can be reused only after a fresh one-time Telegram `/start`. |
| UI cache transition | PASS | Every Aurora page references cache version `20260801-stage10-1-auth2`; old dev.13 resource URLs are absent from the live dev.15 index. |
| Development/Production isolation | PASS | Preserved dev.10, exact-source dev.15 sandbox and Linux Production were simultaneously healthy. They use separate hostnames, ports, writable state, database, secrets, queue/storage namespaces and process lifecycle; Production uses PostgreSQL only. |
| PostgreSQL | PASS | Authoritative Production storage; migrations `[1,2,3,4]`, `pending=[]`; tenant/workspace isolation evidence retained. |
| Connector | PASS | Windows VM Connector signed hello, heartbeat, telemetry, paper-only command path, stale/offline denial and NinjaTrader market-data acceptance completed. Current owner workspace attribution and heartbeat are valid. |
| Telegram | PASS | One durable Production consumer, real login and delivery acceptance. |
| Gemini AI | PASS | Credentialed inference, pre-provider budget reservation, durable accounting and oversized-budget denial completed. |
| Required market data | PASS | `NinjaTrader → Windows Connector → Linux Production`; TopstepX, Databento and DXFeed remain optional deferred failover providers. |
| Observability/accounting | PASS | Durable worker, operations, alert and usage records verified during Stage 8–10 acceptance. |
| Off-host backup/recovery | PASS | Private bucket-scoped Cloudflare R2/restic backup, full check and isolated PostgreSQL/artifact restore completed; daily scheduler and retention active. |
| Immutable promotion | PASS | Signed dev.15 archive verified, staged read-only, deployed to canary, rolled back dev.15→dev.14→dev.15, then promoted as the same bytes. |
| Production rollback | PASS | Real Production dev.15→dev.14→dev.15 drill; PostgreSQL dump and rollback inputs hash-verified before promotion. |
| Safety | PASS | Live trading `false`; real payments `false`; no live order, main-PC reboot, destructive Git operation or secret disclosure. |

The final dev.15 source-changing commit passed 901 pytest tests with 32
environment-dependent PostgreSQL tests skipped locally, plus 80 focused
auth/Aurora/deployment tests, Python compilation and JavaScript syntax checks.
Production PostgreSQL migrations and both dev.15 preflights passed separately.
C# and Connector source did not change after their accepted builds, so those
builds and the full Stage 9 lifecycle were not repeated.

## Recovery paths

Current application rollback and restore:

- rollback: `/home/stratforge/production_data/backups/stage10-1-owner-promote-dev15-20260801T213852Z/rollback-production.sh`;
- restore: `/home/stratforge/production_data/backups/stage10-1-owner-promote-dev15-20260801T213852Z/restore-dev15.sh`.

Current canary rollback and restore:

- rollback: `/home/stratforge/production_data/backups/stage10-1-canary-dev15-20260801T213631Z/rollback-canary.sh`;
- restore: `/home/stratforge/production_data/backups/stage10-1-canary-dev15-20260801T213631Z/restore-canary.sh`.

The earlier DNS rollback drill and dev.13→dev.12→dev.13 application drill are
retained as historical cutover evidence. Immutable release directories and
same-host backups remain in place. Database restore is not part of the normal
dev.15→dev.14 application rollback because both releases use migrations
0001–0004; the verified pre-promotion dump is reserved for recovery.

## Evidence pointers

- Detailed Stage 10 evidence: [STAGE10_EVIDENCE_REPORT_2026-07-29.md](STAGE10_EVIDENCE_REPORT_2026-07-29.md)
- Execution chronology: [STAGE10_EXECUTION_LOG_2026-07-29.md](STAGE10_EXECUTION_LOG_2026-07-29.md)
- Release and rollback workflow: [PRODUCTION_RELEASE_WORKFLOW.md](PRODUCTION_RELEASE_WORKFLOW.md)
- Historical Stage 9 handoff: [../ANTIGRAVITY_STAGE9_HANDOFF.md](../ANTIGRAVITY_STAGE9_HANDOFF.md)
- Sanitized Linux evidence root: `/home/stratforge/production_data/runtime/stage10-evidence`
- Sanitized local evidence root: `C:\SF10\evidence`

Latest evidence SHA-256 values:

| Evidence | SHA-256 |
|---|---|
| dev.15 immutable staging | `AF96BDAE3318CEC4C4A030966EB548FAF2EA9A8B683F6D0B42E7787C9A9641D7` |
| dev.15 canary and rollback | `13C657961537390595EDE04189DE468DBBA47CFCC3A0D14C9A506A241D5BE9A6` |
| dev.15 Production promotion and rollback | `C3386C77A351B0BDA1AF7414C5342213FC6C8B197A645218072DB777EC4E75BD` |
| Final real owner acceptance | `D724832D81E89CE0BED10DE233E58B90F666D347A172031042FC23D0FA427EBE` |

## Stable certification boundary

Production runtime is operational, but `STABLE` is deliberately not claimed.
Formal certification still requires external evidence for:

1. trusted Authenticode signing and timestamping;
2. externally protected Production P-256 release signing;
3. literal outer-container and host reboot acceptance with host-admin access;
4. independent non-owner beta acceptance and sign-off.

These are Stage 11E governance/certification items, not open Stage 10 runtime
P0/P1 defects. New feature implementation starts only after approval of
[STAGE11_PROPOSAL.md](STAGE11_PROPOSAL.md).
