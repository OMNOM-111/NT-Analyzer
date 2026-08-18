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

## СЛЕДУЮЩЕЕ ДЕЙСТВИЕ

1. Единый модуль «Окружения и релизы»: Environment Switcher + Release Center,
   карточки Development/Canary/Production, pipeline-кнопки
   `Создать кандидата → Canary → Acceptance → Promote`, гейты (нет Canary
   acceptance / изменился artifact / не прошли миграции / CI не зелёный →
   promote запрещён), стадии `CI → Build → Sign → Migrations → Canary →
   Acceptance → Production`, Compare LOCAL↔CANARY↔PRODUCTION.
   `Открыть Development` активна только на самой development-машине; удалённый
   доступ fail-closed, localhost наружу не публикуется.
2. Admin navigation consolidation.
3. Удалить из Admin «Глобальные документы» и «Документы рабочих областей»;
   единственный раздел «Документы» — в основном приложении.
4. Monitoring объединить с «Пользователи и сессии».
5. Subscriptions/Grants — только в Admin.
6. Owner Journal → компактный timeline `time | actor | action | target |
   environment | result`.
7. Connector onboarding → «Подключить NinjaTrader / скачать / авторизовать»,
   manual pairing только в Advanced.
8. Operations/Diagnostics по capabilities окружения.
9. Browser performance pass.
10. Финальный E2E и единственный click-list.

Релизы только: `LOCAL → CI → PR → merge → immutable candidate → Canary →
acceptance → SAME artifact Production`.

Четыре Google/Resend secrets не ротировать.
