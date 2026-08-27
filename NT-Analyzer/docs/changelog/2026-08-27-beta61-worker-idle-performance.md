# beta.61 — production worker idle scheduling

Closeout UTC: `2026-08-27T22:33:11Z`.

Status: **ACCEPTED / PRODUCTION LIVE**.

## Release identity

| Field | Value |
| --- | --- |
| Version | `0.10.0-beta.61` |
| Artifact Git SHA | `60d922b2600d1d31e611c7a670cbddebc889beef` |
| Code PR / merge | [#198](https://github.com/OMNOM-111/NT-Analyzer/pull/198) / `60d922b2600d1d31e611c7a670cbddebc889beef` |
| Candidate / artifact | `rc_8016843875644befbbd681c5cc2bde0e` / `art_77d98a4ed8aa4473bb241addf19c45b3` |
| Build ID | `sf-0.10.0-beta.61-60d922b2600d-20260827T175814Z` |
| Archive SHA256 | `E61B8C9293308D522AE3017EEBCF09B73A01CABA689EA8636A0C2BDA12236534` |
| Runtime/manifest SHA256 | `E9195140BDB22C53EB83405FCF5655E76FD60068637FED1A0CAE35B1A769AF53` |
| Canary deployment / acceptance | `dep_9f5c8b6e10d64a299b2c9a9e41738486` / `chk_63c486896c474479a8c8b765b2d30b10` |
| Production deployment | `dep_9a552fc7bbb54297ad8da764adae3659`, `production_live` |

Canary and Production resolve to release directory suffix
`0.10.0-beta.61-60d922b2600d`; both previous/rollback slots are
`0.10.0-beta.60-101d7c447e2d`. Public readiness reports the same Git SHA,
build ID and runtime SHA256. Production promotion reused the accepted artifact
without rebuild; pending migrations were `0`.

## Reproduction and correction

On beta.60, an empty queue still ran every one of the 11 configured worker
slots approximately every 250 ms. Every `run_once()` also executed
`sweep_stale(limit=100)`. Equal 180-second live windows measured about 34.5
claims and 34.5 sweeps per second per environment and about 84% of one CPU core
in each worker process.

The beta.61 change is limited to application worker scheduling:

- one stoppable `WorkerService` coordinator owns stale sweeping every 30 s;
- idle workers back off through 500 ms, 1 s and approximately 2 s with jitter;
- a claimed job resets the delay to 250 ms;
- storage failure waits at least 1 s and cannot create a tight retry;
- concurrency remains `interactive_ai=4`, `chart=4`, `telemetry=2`,
  `maintenance=1`.

No TopstepX, SignalR, Connector protocol, market-data history/realtime,
cache/failover, chart rendering, Docker, VM, firewall, Supervisor or Linux host
setting changed.

## Equal-window live evidence

All rows used an empty queue at both the beginning and the end of the window.

| Environment / metric | beta.60 before | beta.61 after | Change |
| --- | ---: | ---: | ---: |
| Canary worker CPU | 83.711% | 4.839% | -94.2% |
| Canary total DB TX/s | 155.378 | 28.700 | -81.5% |
| Canary worker SQL/s | 138.302 | 17.267 | -87.5% |
| Production worker CPU | 83.778% | 5.522% | -93.4% |
| Production worker-attributable TX/s | 69.002 | about 5.822 | -91.6% |
| Production worker SQL/s | 138.003 | 17.367 | -87.4% |
| Production total DB TX/s | 259.069 | 175.194 | -32.4% |

The Production total is intentionally reported separately from queue-worker
activity. A further read-only 60-second attribution window measured the API
process at 59.267% CPU, the worker at 5.650% and Telegram at 4.367%.
`sf_connector_sessions` recorded 25,124 updates in that interval. Thus the
remaining Production DB rate is dominated by the already active
Connector/API mirror path, not by the 11 empty queue loops. This release does
not modify that accepted Connector baseline.

`pg_stat_statements` is not installed on the host. Before counts were visible
through queue index statistics. Afterward, the sweep statement chose a plan
that did not expose a statement counter, so beta.61 does not mislabel that
counter as zero: one live coordinator thread, its 30-second schedule, and
successful real stale-lease recovery establish the effective rate of about
0.033 sweep/s.

## Functional and regression evidence

- Canary pickup, eight sustained-idle samples: p50 `1.371834 s`, max
  `1.455477 s`;
- Production pickup, eight sustained-idle samples: p50 `1.392059 s`, max
  `1.467681 s`;
- both environments: cancel, timeout, advancing lease heartbeat, retry,
  stale-lease recovery and empty-queue return PASS;
- Canary and Production probe job IDs were mutually absent in the other
  environment DB;
- browser-loaded dashboard and AI Agents pages displayed beta.61 and produced
  no console errors; readiness included database, queue, Telegram consumer,
  Connector control and object storage;
- full regression: `2134 passed`, `32 skipped`, `0 failed`;
- project runner: `13/13` suites; targeted scheduling/isolation:
  `55 passed`, `12 skipped`, `0 failed`;
- mandatory GitHub CI: `5/5` GREEN;
- compile, release/static scan, JavaScript syntax, CSP, secrets, Markdown,
  Context Pack and `git diff --check`: PASS.

Known skips remain the explicitly gated real-PostgreSQL integration cases and
the platform-specific Windows bash-syntax check. The two Google Client Secrets
and two Resend keys were not changed.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-27T22:33:11Z | GPT-5.5 через Codex по запросу owner | Recorded the independently reproduced worker busy-polling root cause, scoped scheduler correction, equal-window Canary/Production measurements, same-artifact release identity and measured non-worker Production residual.
-->
