# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-27T22:33:11Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Verified deployed artifact Git SHA: `60d922b2600d1d31e611c7a670cbddebc889beef`
- Current Production version/build/artifact when known: `0.10.0-beta.61`; `sf-0.10.0-beta.61-60d922b2600d-20260827T175814Z`; runtime SHA256 `E9195140BDB22C53EB83405FCF5655E76FD60068637FED1A0CAE35B1A769AF53`
- Scope: Production worker idle scheduling performance closeout
- Status: DONE

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` pack-wide verification baseline; deployed artifact `60d922b2600d1d31e611c7a670cbddebc889beef` |
| Code change | PR #198, merge/artifact SHA `60d922b2600d1d31e611c7a670cbddebc889beef` |
| Release | `0.10.0-beta.61`, candidate `rc_8016843875644befbbd681c5cc2bde0e`, artifact `art_77d98a4ed8aa4473bb241addf19c45b3` |
| Build | `sf-0.10.0-beta.61-60d922b2600d-20260827T175814Z` |
| Archive / runtime hashes | `E61B8C92…6534` / `E9195140…AF53` |
| Canary | accepted, ready, deployment `dep_9f5c8b6e10d64a299b2c9a9e41738486`, check `chk_63c486896c474479a8c8b765b2d30b10` |
| Production | same immutable artifact, live/ready, deployment `dep_9a552fc7bbb54297ad8da764adae3659` |
| Release parity | same release directory suffix `0.10.0-beta.61-60d922b2600d`; previous/rollback beta.60 |
| Worker concurrency | `interactive_ai=4`, `chart=4`, `telemetry=2`, `maintenance=1` |
| Canary idle result | CPU `83.711% → 4.839%`; total DB TX/s `155.378 → 28.700`; pickup p50/max `1.372/1.455 s` |
| Production idle result | worker CPU `83.778% → 5.522%`; worker-attributable TX/s about `69.002 → 5.822`; pickup p50/max `1.392/1.468 s` |
| Tests | full `2134 passed, 32 skipped, 0 failed`; targeted `55 passed, 12 skipped, 0 failed`; CI `5/5` |
| Market-data and Connector baseline | preserved; no functional path change |
| Secret rotation | explicitly deferred; Google/Resend secrets unchanged |

## Completed actions

1. Live beta.60 measurements independently confirmed 11 empty worker loops,
   approximately 250 ms polling and per-loop stale sweeping.
2. Stale sweeping moved to one stoppable 30-second coordinator; empty workers
   gained jittered adaptive backoff and storage outage waits at least 1 s.
3. Cancel, timeout, heartbeat, retry, stale recovery, graceful shutdown,
   outage behavior, unchanged parallel concurrency and environment isolation
   received regression coverage.
4. Mandatory CI passed; one signed immutable beta.61 artifact deployed to
   Canary, passed browser, readiness, queue and equal-window acceptance, then
   promoted unchanged to Production.
5. Production functional probes passed and synthetic job IDs were mutually
   absent across the Canary and Production databases.
6. Read-only attribution proved that residual Production DB activity is not
   queue-worker polling: worker CPU is below 6%, while the active API/Connector
   mirror path accounts for the dominant remaining transaction and CPU rate.

## Remaining boundaries, not blockers for this closeout

| Area | State | Boundary |
| --- | --- | --- |
| Production total DB rate | measured | `259.069 → 175.194 TX/s`; the queue-worker component fell about 91.6%, while the accepted active Connector/API mirror path remains separate and unchanged |
| Cross-user shared owner feed | `EXTERNAL BLOCKED` | written provider/exchange distribution authority and per-user entitlement policy |
| Public Connector installer | `EXTERNAL BLOCKED` | authorized Authenticode signing tool/material |
| Google / Resend rotation | deferred | separate final security closeout; two Google Client Secrets and two Resend keys untouched |
| Legal publication | `IN DEVELOPMENT` | DRAFT until owner/legal decisions and counsel review |

## Next development boundary

The worker scheduling release is closed. The next explicitly planned task is
the separate Google/Resend security closeout. Any future optimization of the
measured Connector/API mirror write rate must begin as a new scoped task with
its own reproduction and must preserve the accepted beta.60/beta.61 functional
Connector and market-data baselines.

## Canonical evidence

- [beta.61 worker idle performance closeout](../changelog/2026-08-27-beta61-worker-idle-performance.md)
- [current clean closeout](../current/CLEAN_CLOSEOUT_HANDOFF.md)
- [environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and worker queues](07_AI_AGENTS_AND_AUTOMATION.md)
- [market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-27T22:33:11Z | GPT-5.5 через Codex по запросу owner | Replaced the completed beta.48 handoff with exact beta.61 worker scheduling, test, live measurement, immutable release and bounded residual-attribution evidence.
-->
