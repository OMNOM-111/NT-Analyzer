# Clean closeout — beta.48 accepted and live in Production

Дата проверки: `2026-08-26T18:22:14Z`.

## Outcome

Scoped LIVE Connector closeout завершён. Root cause находился в Production
relational mirror: terminal historical orphan rows из авторитетного Connector
JSON повторно попадали под FK при каждом challenge. Исправление сохраняет
историю, исключает из mirror только доказанно terminal orphan rows и продолжает
fail-closed блокировать любой non-terminal orphan.

Существующая installation `inst_9rVbadz0rNu0xlbbfsVSnkvY` восстановилась без
reenrollment: challenge и signed hello приняты, одна активная session дала
последовательность heartbeat `24 → 34 → 38`, status остаётся `online`, после
момента beta.48 live новых отказов нет. Connector market-data batch также
принят; старый source timestamp остаётся честно stale.

## Current release identity

| Environment | Version | Git SHA | Build / runtime artifact | Status |
| --- | --- | --- | --- | --- |
| LOCAL release source | `0.10.0-beta.48` | `ae9c5c913e4a3250dd978ce2bf682e52590e82ef` | clean, `dirty=false` | release source verified |
| Canary | `0.10.0-beta.48` | same | `sf-0.10.0-beta.48-ae9c5c913e4a-20260826T181306Z` / `F7856E1E…7ED6` | accepted, ready |
| Production | `0.10.0-beta.48` | same | same build / same runtime hash | live, ready, Connector online |

- candidate `rc_f4554de031954dca87bff3b2c54cfa0e`;
- artifact `art_dba8625e0b3b427896f8d1ead2382fa2`;
- archive SHA256
  `B9C56184222AE4DADF6C979949A7FEC6A31F23D6048663425DD0BBCD69894E97`;
- runtime/manifest SHA256
  `F7856E1EFEEEC6CDACECA48DB4851FFEA9F59CE31F90BEFE6BCAD6ABF6787ED6`;
- shared release directory
  `production_data/releases/0.10.0-beta.48-ae9c5c913e4a`;
- Canary previous and Production rollback
  `0.10.0-beta.47-a40367fe8027`.

Canary deployment `dep_a5abb0353395450889ff3d1013dc9050` прошёл до final
acceptance `chk_4e9892b9c99d464ea3b8560217269aa5`. Затем тот же artifact
без rebuild стал Production deployment
`dep_e955efac5b1a4d189ba3b6b521aa8bd4`.

## Verification

- PR #182 fix и PR #183 release identity: mandatory CI `5/5` GREEN;
- full regression: `2033 passed`, `32 skipped`, `0 failed`;
- targeted storage/Connector: `131 passed`, `19 skipped`, `0 failed`;
- project runner: `13/13`;
- compile/static/CSP/secrets/Markdown/Context/diff gates: PASS;
- Production audit после beta.48 live: unexpected refusals `0`;
- market-data/chart baseline preserved: TopstepX/SignalR/session/history,
  rollover, cache/failover, WebSocket fan-out and chart rendering files не
  изменялись.

## Retained boundaries

- TopstepX остаётся основным независимым read-only источником графиков;
  NinjaTrader остаётся execution/backtest/runtime truth и отдельным fallback.
- Cross-user redistribution owner feed остаётся `EXTERNAL BLOCKED` без
  письменного provider/exchange разрешения.
- Public Production Connector package остаётся `EXTERNAL BLOCKED` на
  разрешённом Authenticode tool/material; это не блокирует существующий
  enrolled runtime.
- Два Google Client Secret и два Resend key не ротировались в этой задаче.
- Legal documents остаются DRAFT до отдельного owner/legal closeout.

Подробная техническая и release evidence:
[beta.48 Production LIVE Connector storage reconciliation](../changelog/2026-08-26-beta48-live-connector-storage-reconciliation.md).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-26T18:22:14Z | GPT-5.5 через Codex по запросу owner | Старый многоцикловый handoff заменён текущим beta.48 snapshot; подробная история вынесена в canonical changelog.
-->
