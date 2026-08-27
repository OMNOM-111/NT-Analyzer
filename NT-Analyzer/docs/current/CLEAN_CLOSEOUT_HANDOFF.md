# Clean closeout — beta.61 accepted and live in Production

Дата проверки: `2026-08-27T22:33:11Z`.

## Outcome

Scoped performance closeout Production workers завершён. На beta.60 пустая
очередь не останавливала 11 worker loops: каждый примерно раз в 250 ms делал
claim и отдельно запускал stale sweep. На beta.61 concurrency сохранена
`4/4/2/1`, пустые worker slots переходят на jittered backoff до примерно 2 s,
после job сразу возвращаются к 250 ms, а stale leases обслуживает один
останавливаемый coordinator раз в 30 s.

Canary и Production прошли одинаковые функциональные probes: pickup менее 2 s,
cancel, timeout, advancing heartbeat, retry, stale recovery, пустая очередь и
изоляция job IDs. Market-data, TopstepX, SignalR, NinjaTrader/Connector protocol,
chart realtime/history/cache/failover/rendering не менялись.

## Current release identity

| Environment | Version | Git SHA | Build / runtime artifact | Status |
| --- | --- | --- | --- | --- |
| LOCAL release source | `0.10.0-beta.61` | `60d922b2600d1d31e611c7a670cbddebc889beef` | clean, `dirty=false` | current |
| Canary | `0.10.0-beta.61` | same | `sf-0.10.0-beta.61-60d922b2600d-20260827T175814Z` / `E9195140…AF53` | accepted, ready |
| Production | `0.10.0-beta.61` | same | same build / same runtime hash | live, ready |

- candidate `rc_8016843875644befbbd681c5cc2bde0e`;
- artifact `art_77d98a4ed8aa4473bb241addf19c45b3`;
- archive SHA256
  `E61B8C9293308D522AE3017EEBCF09B73A01CABA689EA8636A0C2BDA12236534`;
- runtime/manifest SHA256
  `E9195140BDB22C53EB83405FCF5655E76FD60068637FED1A0CAE35B1A769AF53`;
- shared release directory suffix `0.10.0-beta.61-60d922b2600d`;
- Canary previous и Production rollback `0.10.0-beta.60-101d7c447e2d`.

Canary deployment `dep_9f5c8b6e10d64a299b2c9a9e41738486` прошёл final
acceptance `chk_63c486896c474479a8c8b765b2d30b10`. Затем тот же artifact
без rebuild стал Production deployment
`dep_9a552fc7bbb54297ad8da764adae3659`.

## Performance evidence

| Environment / metric | Before | After |
| --- | ---: | ---: |
| Canary worker CPU | 83.711% | 4.839% |
| Canary total DB TX/s | 155.378 | 28.700 |
| Production worker CPU | 83.778% | 5.522% |
| Production worker-attributable TX/s | 69.002 | около 5.822 |
| Production total DB TX/s | 259.069 | 175.194 |

Остаток Production измерен отдельно: API process `59.267%` CPU, worker
`5.650%`, Telegram `4.367%`; `sf_connector_sessions` получил 25,124 updates за
60 s. Поэтому общий Production DB rate не выдаётся за worker result: scoped
worker activity снизилась примерно на 88–92%, а отдельный активный
Connector/API mirror path оставлен без изменений.

## Verification

- PR #198: mandatory CI `5/5` GREEN;
- full regression: `2134 passed`, `32 skipped`, `0 failed`;
- targeted worker/isolation: `55 passed`, `12 skipped`, `0 failed`;
- project runner: `13/13`;
- compile/static/CSP/secrets/Markdown/Context/diff gates: PASS;
- Canary pickup p50/max `1.372/1.455 s`;
- Production pickup p50/max `1.392/1.468 s`;
- dashboard и AI Agents на обоих server environments показали beta.61 без
  browser console errors;
- readiness: database, queue, Telegram consumer, Connector control и object
  storage PASS.

## Retained boundaries

- TopstepX остаётся основным независимым read-only источником графиков;
  NinjaTrader остаётся execution/backtest/runtime truth и отдельным fallback.
- Отдельная оптимизация измеренного Connector/API mirror write rate не входит
  в beta.61 и требует нового scoped reproduction без изменения принятого
  функционального baseline.
- Public Connector package остаётся `EXTERNAL BLOCKED` на разрешённом
  Authenticode material.
- Два Google Client Secret и два Resend key не ротировались; это следующий
  отдельный security closeout.
- Legal documents остаются DRAFT до owner/legal closeout.

Подробная техническая и release evidence:
[beta.61 production worker idle scheduling](../changelog/2026-08-27-beta61-worker-idle-performance.md).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-27T22:33:11Z | GPT-5.5 через Codex по запросу owner | Текущий handoff обновлён до exact beta.61 immutable release, worker idle performance evidence и честно отделённого Connector/API residual.
-->
