# Clean closeout — beta.79 live in Production

Дата закрытия: `2026-08-29`. Предыдущая редакция описывала beta.61 и заменена
целиком: она отражала промежуточное состояние.

## Current system state

| Environment | Version | Runtime | Status |
| --- | --- | --- | --- |
| Production | `0.10.0-beta.79` | same immutable artifact as Canary | live |
| Canary | `0.10.0-beta.79` | тот же artifact, без пересборки | accepted |
| Development (LOCAL) | источник релизов, DIMONCHECK | собственный NinjaTrader | ready |
| Connector (VMNINJA) | `0.4.2-dev.20` (`ed634e09…`) | trust `SHA256:3a048138…` | live, `compatible` |

VMNINJA — единственная машина, зачисленная в Production; счёт `DEMO3369390`,
NetLiq `$11 017.42`. LOCAL и Production используют раздельные NinjaTrader.

## Что закрыто в этом этапе

### SERVER BACKTEST — PASS

- **Drawer показывает агрегаты устройства.** Раньше PF/P&L/комиссия
  пересчитывались по переданной выборке: отчёт показывал `+$547` и `PF 2.15`
  по 37 строкам рядом с числом сделок 3992, тогда как NinjaTrader дал
  `−$10 490.30` и `0.92`. Пересчёт отключён в обеих функциях чтения; таблица
  маркируется «Показано 37 из 3992 сделок».
- **Отмена работает кооперативно.** NinjaTrader не даёт прервать
  `RunBacktest()`: у метода нет ни токена, ни параметров, а `IProgress.IsAborted`
  доступен только `Optimizer`. Поэтому прерывается всё, что после него — наш
  собственный конвейер, закрытый семью границами вплоть до точки коммита
  `WriteJobOutputs`. Измерено: `CTS → cancelled` **0.71 с**, клик → **4.21 с**.
- **State machine честная:** `pending → running → cancel_requested → cancelled`,
  либо `done` + аудит `cancel_race_completed_before_abort_boundary`, если
  прогон успел завершиться. Терминальный `cancelled` даёт только
  `JobRunOutcome.Cancelled`.

### Connector state honesty — PASS

45-секундная heartbeat-аренда не менялась; отдельный презентационный порог
(`interval + 5 s`) даёт `confirmed / grace / offline`. В grace счёт показывается
как последний известный и не выбирается; в offline кэш не маскирует отсутствие
связи. Возврат в LIVE — без re-enrollment.

### Performance — PASS по hotspot

`ensure_owner()` читала весь документ аккаунтов из Postgres на каждом
авторизованном опросе (production-ветка `_read_doc` кэша не имела). Мемоизация
no-op результата: `/api/auth/status` медиана **43.2 → 19.0 мс**.

**CPU не изменился в пределах шума** (19.2 % → 18.9 % одного ядра за 60 с) —
приписывать снижение этой правке нельзя. Исходный baseline 28.0 % снят в другое
время суток без записи нагрузки и несопоставим.

### Secret management — PASS

Канонический контракт: [PLATFORM_SECRETS](../operations/PLATFORM_SECRETS.md).
Четыре скомпрометированных креда (2 Google, 2 Resend) заменены по
последовательному runbook, старые отозваны, 314 копий в promote-бэкапах
вычищены, постоянная защита от повторения добавлена.

## Test / acceptance matrix

| Область | Как доказано | Итог |
| --- | --- | --- |
| Drawer aggregates | Production-прогон 3992 сделки: 8 показателей = VMNINJA | PASS |
| Trades label | «Показано 37 из 3992 сделок» в UI | PASS |
| `running` виден серверу | 4.8–9.0 с после запуска (ранее не появлялся) | PASS |
| `cancel_requested` | держится, пока NinjaTrader считает | PASS |
| Terminal `cancelled` | `command_result: cancelled` + маркер runner boundary | PASS |
| Cancel latency | CTS → cancelled 0.71 с; клик → 4.21 с | PASS |
| Registry cleared | следующий бэктест принят и завершён | PASS |
| Race → `done` | доказано на реальном прогоне | PASS |
| Connector LIVE / GRACE / OFFLINE | API + визуальная проверка владельца | PASS |
| Recovery без re-enrollment | та же installation `…bbfsVSnkvY` | PASS |
| Auth hotspot | 43.2 → 19.0 мс, тот же метод | PASS |
| Production CPU | 18.9 % vs 19.2 % — в пределах шума | не улучшен |
| DB tx/s | безопасного пути нет | not measured |
| Secret rotation ×4 | Canary → Production → revoke → post-revoke smoke | PASS |
| Secret containment | 0 отозванных значений во всём `production_data` | PASS |

Полный набор: **2327 passed, 32 skipped, 0 failed**.

## Active work / handoff

Активной незавершённой работы нет. Открытых release candidate, pending
promotion и других блокеров следующего этапа нет.

## Backlog — известные долги, намеренно не исправленные

Ни один не блокирует разработку; каждый требует отдельного решения.

1. **`cancel_boundary` не сохраняется** у отменённого прогона: для исхода
   `cancelled` сервер пишет только маркер и не сохраняет `safe_result`
   устройства. Отмена доказана; страдает детальность разбора.
2. **dev.19 health-receipt / LKG.** При переходе на dev.20 устройство временно
   откатилось на dev.18. Механизм отработал по проекту — LKG создаётся из
   версии, стоявшей на момент применения. Почему активация dev.19 не была
   подтверждена health-квитанцией, доказать не удалось: артефакты лежат на
   VMNINJA, доступа нет. Bounded: downgrade без подписанного/LKG артефакта
   невозможен, enrollment сохраняется.
3. **Timing-sensitive тест**
   `test_operations_degrades_a_stalled_connector_without_holding_the_panel`
   промахнулся на 3 мс при пороге 200 мс под нагрузкой self-hosted раннера.
   Порог намеренно не менялся.
4. **Профилировщик Production отсутствует** (`py-spy`/`austin`/`perf`).
   Профилирование велось замерами с хоста — достаточно для найденного hotspot,
   но полного профиля не даёт.
5. **DB tx/s — not measured.** Обращений к `pg_stat_database` в коде нет,
   безопасного diagnostics-пути не существует.
6. **BYOK не workspace-scoped.** Ключи AI-провайдеров глобальные; требование
   «пользователь не читает credential чужого workspace» на уровне модели данных
   не выполнено. Закрыто: значение принимается только при создании и обратно
   не возвращается. Изменение схемы — отдельная задача.
7. **Platform Secrets UI** не рисовался по решению владельца; API готов.
8. **Проверить новые механизмы резервного копирования** на обход `secrets/`.
   Защита добавлена для promote и release-архива.

Из прошлой редакции сохраняются: Public Connector package остаётся
`EXTERNAL BLOCKED` на разрешённом Authenticode material; legal documents
остаются DRAFT до owner/legal closeout.

Подробная техническая evidence:
[beta.79 secret management и cancel closeout](../changelog/2026-08-29-beta79-secret-management-and-cancel-closeout.md).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-29 | Claude Opus 5 по запросу owner | Handoff обновлён до beta.79: SERVER BACKTEST cancel, connector grace-state honesty, auth hotspot, secret-management contract и ротация четырёх кредов. Backlog перечислен явно.
-->
