# Clean closeout — executable handoff

Дата проверки: `2026-08-20T23:00:44Z`.

## Текущее состояние

| Environment | Version | Git SHA | Runtime artifact SHA256 | Readiness |
| --- | --- | --- | --- | --- |
| LOCAL | beta.28 change set, до merge/build | main baseline `3102a534ab569d0cbf162462726d516378dc82a8` | ещё не создан | change-set browser acceptance PASS; clean-SHA recheck pending |
| Canary | `0.10.0-beta.27` | `1f3e2ce7198fec5a90e85d9b49e7a086103e4b62` | `A905E784BD2794F8ACC1760D1697A1B410FC96C24A5BCD25223B8D48FD2EC270` | `/api/live` + `/api/ready` PASS |
| Production | `0.10.0-beta.26` | `3353e3836306dca4628c759064139cdac94517e0` | `27B6316E934F0D727B9D158B34EE601A0A59EF78F0D71B484DD29ADD37617AAB` | `/api/live` + `/api/ready` PASS |

Canary и Production здоровы, но до beta.28 не находятся в release parity. Это
не финальный PASS.

## Что доказано в репозитории

- один canonical LOCAL owner и изолированные environment stores;
- единый Admin-модуль окружений/релизов;
- signed LOCAL request с authoritative server-side promotion decision;
- exact candidate/artifact/TTL validation и fail-closed replay/stale handling;
- disposable Production/Development test roots и запрет любых live-data writes;
- правдивый DEV dirty-state, фактический HTTP status в observability и
  подавление только штатных navigation aborts;
- масштабируемая виртуальная сетка большого chart layout без перекрытия
  timeframe/settings controls;
- market-data/chart baseline не менялся в этом closeout.

## FIRST NEXT STEP

Завершить beta.28 одним циклом:

`LOCAL browser acceptance → mandatory CI → merge → one signed immutable
artifact → Canary acceptance → SAME artifact Production → live recheck`.

При любом исправлении после Canary цикл начинается заново. Production не
получает rebuild, partial copy или server hotfix.

## Честные deferred boundaries

- Новое физическое NinjaTrader Connector enrollment требует реального Windows/
  NinjaTrader interaction; оно не имитируется и не блокирует software closeout
  существующего Connector path.
- Google OAuth, transactional email и legal publication остаются отдельными
  `EXTERNAL BLOCKED` / `IN DEVELOPMENT` задачами.
- Четыре Google/Resend secrets в этой задаче не ротируются.

Канонический operational журнал:
[2026-08-20-final-product-acceptance-beta28.md](../changelog/2026-08-20-final-product-acceptance-beta28.md).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Удалён устаревший beta.20 handoff; зафиксированы фактические beta.27 Canary, beta.26 Production и исполнимый beta.28 closeout.
-->
