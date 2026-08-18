# LOCAL baseline — checkpoint (исправлено)

Дата: `2026-08-18` UTC. Продолжать с раздела **«СЛЕДУЮЩЕЕ ДЕЙСТВИЕ»**.

> **Предыдущая версия этого документа была неверна.** Инвентаризация читала
> **не тот** store. Ошибочные факты (owner `2c347848…`, Telegram `999`, четыре
> `preview_*` персоны) относятся к устаревшему `data/development/`, который
> сервер не использует. Ниже — состояние живого LOCAL.

## Ловушка, из-за которой это произошло

`start.ps1` экспортирует `STRATFORGE_DEVELOPMENT_DATA_ROOT = <project>/data`.
Ad-hoc python без этой переменной резолвит `<project>/data/development` —
другой каталог, другой `accounts.dpapi`, другие пользователи. Файл в
`data/development/` последний раз писался 3 августа и является брошенным.

**Любая проверка LOCAL обязана экспортировать те же переменные, что и
`start.ps1`, либо спрашивать запущенный сервер.** Симптом подмены: owner без
username, или пользователи, которых нет в `/api/auth/users`.

## Живое состояние LOCAL (data root `<project>/data`)

| user_id | uuid | owner | status | username |
| --- | --- | --- | --- | --- |
| `1647145559` | `6b0738c8-efca-4285-9100-905e34633d56` | **да** | active | `dimon_check` |
| `424242` | `643f4ab5-536c-4122-86e5-4d702a9f2043` | **да** | active | — |
| `1279070095` | `058b2049-539b-493a-8689-4ba5d1d4d70b` | нет | active | `ARTUR_CA` |
| `9446350708` | `b3b05ac8-edf5-4fb3-8fe6-3c7c3c6b6ebf` | нет | active | `virtual_…` |
| `9375041115` | `27280107-76f3-4068-a75a-ccc8049f84fd` | нет | active | `virtual_…` |
| `9102530131` | `f31b961e-822c-4991-b7b3-dadcb7fc4f71` | нет | blocked | `virtual_…` |
| `9810142813` | `f221a114-42c0-4b98-902a-ec3dfc990b12` | нет | active | `virtual_…` |

Коллекции: `auth_identities` 11, `sessions` 10, `trusted_devices` 3,
`identity_history` 0, `physical_devices` 0.

Идентичности: у реального владельца — `telegram 1647145559`; у `424242` и
`ARTUR_CA` — свои telegram; у четырёх `virtual_*` — по паре
`google test-google-*` + `test virtual-*`, то есть очевидные фикстуры.

### Что это меняет

1. **В LOCAL два owner-аккаунта** — `1647145559` и `424242`. Это прямое
   доказательство того, что старый `ensure_owner` действительно создавал
   второго владельца.
2. **Реальный владелец согласован между хранилищами.** Его UUID `6b0738c8…`
   совпадает с `owner_user_uuid` в workspace store. Расхождения auth↔workspaces
   нет; разошёлся только LOCAL с canonical.
3. **`NTA_TELEGRAM_CHAT_ID` живёт в `data/integrations/secrets.local.json`**
   (git-ignored) и уже указывает на настоящий id. `999` был артефактом
   брошенного store. Менять его не требуется.
4. У владельца **есть** legitimate state: настоящая Telegram identity, имя,
   сессии, устройства, workspace. Его нужно сохранить.

## Что уже сделано в этой сессии

- **PR #124** — `development_sync` + `/api/admin/development-sync`.
- **Не смержено, в рабочем дереве:** `ensure_owner` больше не создаёт второго
  владельца и не переписывает существующего молча. Введены
  `STRATFORGE_CANONICAL_OWNER_UUID` (конфигурация, не константа) и
  `OwnerIdentityConflict` (409, с указанием конфликтующих значений).
  8 тестов в `tests/test_owner_identity_boot.py`, полный прогон 1733 passed.

## СЛЕДУЮЩЕЕ ДЕЙСТВИЕ

1. Смержить hardening `ensure_owner` (CI → PR → merge).
2. Re-key владельца `6b0738c8…` → `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f`
   в auth document **и** workspace store. Оба сейчас держат `6b0738c8…`,
   поэтому это одна согласованная замена, а не сведе́ние расхождения.
   Telegram `1647145559`, имя, сессии, устройства, workspace — сохранить.
3. Удалить после dependency-проверки: `424242` (второй owner), `ARTUR_CA`,
   четыре `virtual_*`. Итог — `users = 1`.
4. Прописать `STRATFORGE_CANONICAL_OWNER_UUID` в
   `data/integrations/secrets.local.json` (git-ignored), чтобы пустой store
   поднимался как тот же владелец.
5. Перезапустить LOCAL и доказать: `users = 1`, UUID canonical, второй owner не
   восстановлен, login/Cabinet/Admin/User Card/workspaces работают,
   `development_sync` = `current`.

Все проверки — с переменными `start.ps1` либо через запущенный сервер.

Backup: `BACKUPS/local-owner-cleanup-20260818T003403Z` (сделан до изменений;
содержит копию `data/development`, то есть брошенного store — **перед записью
в живой store сделать новый backup `data/integrations`**).

## Дальше по программе

Единый модуль «Окружения и релизы», Admin navigation, Documents cleanup,
Users & Sessions + Monitoring, Subscriptions placement, Owner Journal,
Connector onboarding, Operations/Diagnostics, browser performance, финальный E2E.

Релизы только: `LOCAL → CI → PR → merge → immutable candidate → Canary →
acceptance → SAME artifact Production`.

Четыре Google/Resend secrets не ротировать.
