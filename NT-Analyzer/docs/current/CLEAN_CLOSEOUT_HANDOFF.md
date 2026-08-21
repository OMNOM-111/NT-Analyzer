# Clean closeout — executable handoff

Дата проверки: `2026-08-21T02:52:33Z`.

## Текущее состояние

| Environment | Version | Git SHA | Runtime artifact SHA256 | Readiness |
| --- | --- | --- | --- | --- |
| LOCAL | beta.28 scoped release-control correction | main `2790fb43992d29439aa939dea9e972862592c652` + current task branch | новый artifact ещё не создан | targeted regression PASS; full CI pending |
| Canary | `0.10.0-beta.28` | `2790fb43992d29439aa939dea9e972862592c652` | `CFBE5BDE78E0AC755673706289C56CF6FD08D1BF7FE1D3DAE41C925A90E63398` | live/browser/Documents/chart PASS, но artifact superseded новым code fix |
| Production | `0.10.0-beta.26` | `3353e3836306dca4628c759064139cdac94517e0` | `27B6316E934F0D727B9D158B34EE601A0A59EF78F0D71B484DD29ADD37617AAB` | `/api/live` + `/api/ready` PASS |

Canary и Production здоровы, но не находятся в release parity. Production не
менялся: штатный server-authoritative promotion выявил literal-state blocker
после approval. Это не финальный PASS.

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

Слить scoped fix и завершить beta.28 новым полным циклом:

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
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Зафиксирован реальный blocker canary_passed→approved_for_production в authoritative promotion gate; artifact 2790fb43 не продвигался, Production остался beta.26.
-->
