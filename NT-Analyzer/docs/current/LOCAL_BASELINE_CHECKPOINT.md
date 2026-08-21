# LOCAL baseline — ЗАКРЫТО

Дата: `2026-08-18` UTC. LOCAL приведён к canonical baseline и доказан после
перезапуска. Продолжать с раздела **«СЛЕДУЮЩЕЕ ДЕЙСТВИЕ»**.

## Ловушка, которую нужно помнить

`start.ps1` экспортирует `STRATFORGE_DEVELOPMENT_DATA_ROOT = <project>/data`.
Ad-hoc python без неё резолвит `<project>/data/development` — **другой**
`accounts.dpapi`, другие пользователи, брошенный с 3 августа. Первая версия
инвентаризации в этой программе прочитала именно его и выдала полностью ложную
картину (owner `2c347848…`, Telegram `999`, четыре `preview_*`).

**Любая проверка LOCAL обязана экспортировать переменные `start.ps1` либо
спрашивать запущенный сервер.** Признак подмены: owner без username или
пользователи, которых нет в `/api/auth/users`.

## Что было в живом LOCAL до очистки

7 аккаунтов, из них **два owner**: настоящий `1647145559` `dimon_check`
(uuid `6b0738c8…`) и синтетический `424242` (uuid `643f4ab5…`), плюс
`ARTUR_CA` и четыре `virtual_*` с фикстурными `google`/`test` identities.
Два owner-аккаунта — прямое доказательство того, что прежний `ensure_owner`
действительно создавал второго владельца.

## Что сделано

**Root cause (PR #126).** Владельца определяет неизменяемый UUID; Telegram,
Google, email — это identities этого UUID. `ensure_owner` больше не создаёт
второго владельца и не переписывает существующего молча: оба случая поднимают
`OwnerIdentityConflict` (409) с указанием конфликтующих значений.
`STRATFORGE_CANONICAL_OWNER_UUID` — конфигурация, не константа; тест
запрещает попадание реального UUID в исходники. 8 регрессионных тестов.

**Реконсиляция.** Backup живого store: `BACKUPS/local-live-store-20260818T060254Z`.
Сервер остановлен на время записи. Owner `6b0738c8…` → `eb9d8e32…`:
13 ссылок в auth document, workspace `ws_owner_training_c1fe3f2f8a52`
перевёден на canonical. Удалены 6 аккаунтов и 11 зависимых строк, затем
подчищены осиротевшие строки: 1 `trusted_device`, 2 workspace, 7 memberships,
принадлежавшие аккаунтам, которых уже нет.

**Канонический UUID** записан в `data/integrations/secrets.local.json`
(git-ignored, проверено `git check-ignore`), поэтому пустой store поднимется
как тот же владелец, а не как новый человек.

## Доказательство после перезапуска

```
users = 1            id=1647145559 dimon_check owner=True active
owner uuid           eb9d8e32-8db0-d590-9b35-ef1bd07ec61f
telegram identity    1647145559 (настоящая, сохранена)
orphan references    none (auth и workspaces)
identities unique    yes
второй owner         не восстановлен ensure_owner
```

Поверхности после рестарта: `/api/auth/me`, `/api/account/card`
(uuid canonical, 1 identity, 2 unbound client), `/api/workspaces` (1),
`/api/account/security` (2 device), `/api/admin/development-sync` = `current`
(running == head). LOCAL DB остаётся изолированной от Canary/Production.

## Текущий checkpoint — FINAL PRODUCT ACCEPTANCE

Ранее указанная работа по UI завершена: единый модуль «Окружения и релизы»
выпущен в PR #130, Admin navigation консолидирована в PR #131, а управление
промоушеном из LOCAL с authoritative server-side решением — в PR #135.

Текущая release-кандидатура `0.10.0-beta.28` закрывает воспроизводимые
closeout-дефекты без изменения market-data/chart архитектуры:

1. LOCAL принимает решение о Production только от Canary/Production и только
   для точных `candidate_id` + artifact SHA с действующим коротким TTL;
   ответ другого кандидата, stale/replayed решение и Development-responder
   блокируются fail-closed.
2. Pytest больше не читает и не изменяет живой LOCAL `data/` как test root:
   Production и Development получают раздельные disposable roots, а полный
   suite завершается ошибкой при любом изменении live state. Корректность CI
   больше не зависит от shared concurrency group.
3. DEV dirty-state не выдаёт недоказанное утверждение о запущенном процессе,
   HTTP observability считает реально отправленный status, а штатный abort при
   навигации не создаёт ложную console/UI ошибку.
4. В layout на 36 charts единая виртуальная сетка масштабируется под viewport;
   соседнее окно больше не перекрывает timeframe/settings hit targets из-за
   CSS minimum-размеров.

Финальный LOCAL regression: `1910 passed`, `32 skipped`, `0 failed`; legacy
release runner `13/13 suites passed`; live `data/` digest до и после совпал.
TopstepX с NinjaTrader OFF подтверждён двумя MNQ/MES 5m browser clients на
clean implementation commit непрерывно `610.473 s`; marker оставался live и
прошёл две границы новых 5m candles.

Следующее действие в этом же acceptance: mandatory CI → merge → один signed
immutable artifact → Canary browser/live acceptance → тот же artifact в
Production → повторная live-проверка и operational release snapshot.

Физическое enrollment нового NinjaTrader Connector остаётся отдельной
hardware-зависимой проверкой и не имитируется. Текущий Connector/NinjaTrader
не перезапускается без воспроизводимой необходимости.

Релизы только: `LOCAL → mandatory CI → PR → merge → immutable candidate →
Canary → acceptance → SAME artifact Production`.

Четыре Google/Resend secrets не ротировать.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Актуализирован LOCAL checkpoint: закрытые PR #130/#131/#135, fail-closed release decision и полная test-root isolation для final acceptance beta.28.
-->
