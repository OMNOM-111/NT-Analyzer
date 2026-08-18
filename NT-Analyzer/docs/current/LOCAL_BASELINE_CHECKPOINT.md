# LOCAL baseline — checkpoint

Дата: `2026-08-18` UTC. Продолжать **с раздела «СЛЕДУЮЩЕЕ ДЕЙСТВИЕ»**.
Диагностика уже выполнена, повторять её не нужно.

## Состояние

| | |
| --- | --- |
| main | `4349a9b8` |
| Canary / Production | `0.10.0-beta.26`, artifact `AC4465F0091AFA85…`, schema **18**, parity EXACT |
| LOCAL runtime | `0.10.0-beta.26`, commit `3353e3836306` — **синхронизирован** (был beta.20) |
| Merged в этой сессии | PR #124 — `development_sync` + `/api/admin/development-sync` |
| Destructive LOCAL cleanup | **НЕ выполнялся** |

Backup LOCAL сделан до любых изменений:

```
BACKUPS/local-owner-cleanup-20260818T003403Z/   (integrations + audit)
```

## Главная находка: в LOCAL три разных owner identity

Это не «неправильный UUID», а рассогласование между хранилищами.

| хранилище | uuid | legacy id | откуда |
| --- | --- | --- | --- |
| auth document | `2c347848-1eff-4493-a5d8-880ece389c1d` | `999` | создан `ensure_owner` из `NTA_TELEGRAM_CHAT_ID=999` в `start.ps1` |
| workspaces store | `6b0738c8-efca-4285-9100-905e34633d56` | `1647145559` | остался от работы с **настоящим** Telegram владельца |
| canonical (Canary/Production) | `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f` | `1647145559` | эталон |

`1647145559` в workspaces совпадает с реальным Telegram id владельца и с
Production. То есть LOCAL когда-то использовался с настоящим аккаунтом, а
позже auth-store был пересоздан dev-владельцем `999`.

### Что в auth document реально есть у owner `2c347848`

- identities: **только** `telegram` = `999` (это dev chat id, не реальная личность);
- Google — нет, verified email — нет, phone — нет;
- `identity_history` — **пусто**;
- 1 session, 1 trusted device;
- `physical_devices`, `device_pairings`, `security_challenges` — пусто;
- connector installations в LOCAL — **0**.

Итого **6 строк** ссылаются на owner в auth document (1 user + 1 identity +
1 session + 1 device, плюс legacy-совпадения).

Поэтому «сохранить легитимные Telegram/Google/email/phone/history» в LOCAL
нечего: там нет ничего настоящего, кроме workspace.

### preview-персоны

`9600000000000001–04` (`preview_ordinary`, `preview_owner_training`,
`preview_personal_nt`, `preview_developer`) — по 2 ссылающиеся строки каждая
(user + identity). **Ни один модуль их не создаёт** — это осевшие записи от
прошлых импersonation-тестов, безопасны к удалению после re-key.

## СЛЕДУЮЩЕЕ ДЕЙСТВИЕ — атомарная реконсиляция LOCAL

Цель: `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f` / legacy `1647145559` —
единственный owner в LOCAL, workspace сохранён, история не потеряна.

Порядок (одна атомарная операция на каждое хранилище, с проверкой после):

1. **Сначала `NTA_TELEGRAM_CHAT_ID`.** В `start.ps1` он равен `999`, и
   `ensure_owner` (`account_auth.py:1462`, `:1510`, `:1622`) пересоздаёт/чинит
   owner по нему при каждом старте. Если не поменять на `1647145559`, любой
   re-key будет откачен назад при следующем запуске LOCAL. **Это первопричина,
   а не косметика.**
2. Auth document: `2c347848…` → `eb9d8e32…`, legacy `999` → `1647145559`
   во всех полях (`user_uuid`, `legacy_user_id`, `user_id`, `owner_id`,
   `actor_user_uuid`, …) — 6 строк.
3. Workspaces store: `6b0738c8…` → `eb9d8e32…` (legacy `1647145559` уже верный),
   поля `owner_user_uuid` и `user_uuid` в memberships.
   **Внимание:** этот store читается только процессом сервера — ad-hoc python
   падает с `WorkspaceError` (DPAPI). Делать через запущенный сервер или
   в его окружении.
4. Удалить preview-персоны и их identities.
5. Доказать: `human users = 1`, owner uuid = canonical, orphan-ссылок нет,
   identities уникальны, sessions/devices принадлежат owner, LOCAL DB
   изолирована от Canary/Production.
6. Перезапустить LOCAL и убедиться, что `ensure_owner` **не** создал второго
   владельца.

Решение по Telegram `999`: не переносить его на canonical UUID как
подтверждённую личность. После смены `NTA_TELEGRAM_CHAT_ID` владелец входит в
LOCAL своим настоящим Telegram, и identity создаётся честно.

## Дальше по программе (не начато)

Единый модуль «Окружения и релизы» (Environment Switcher + Release Center с
кнопками pipeline и гейтами), Admin navigation consolidation, удаление двух
Documents-разделов из Admin, слияние Monitoring с Users & Sessions,
Subscriptions только в Admin, Owner Journal как компактный timeline,
Operations по capabilities окружения, Connector onboarding
(скачать → установить → авторизовать, manual pairing только в Advanced),
performance-проход по браузеру, финальный E2E.

## Правило релизов

`LOCAL development → mandatory CI → PR → merge → immutable candidate → Canary
→ acceptance → SAME artifact Production`. Чинить Canary отдельно от LOCAL
нельзя.

Четыре Google/Resend secrets не ротировать до полного технического PASS.
