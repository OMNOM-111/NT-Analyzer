# Staging QA — глаза пользователя без реального телефона/Google

**Дата:** 15 июля 2026  
**Связь:** `STRATFORGE_ГЕНЕРАЛЬНЫЙ_ПЛАН.md` · пункт 6 · Фаза A

## Зачем

Владелец должен пройти путь нового пользователя на **отдельной staging-среде**, не трогая production DB, production Telegram owner chats, реальные платежи и live-ордера.

## Переменные окружения

| Переменная | Значение | Назначение |
|---|---|---|
| `NTA_APP_ENV` | `staging` | Включает staging-режим |
| `NTA_ENABLE_TEST_AUTH` | `1` | Разрешает virtual users / fake Google |
| `NTA_ENABLE_IMPERSONATION` | `1` (по умолчанию на staging) | «Войти как пользователь» |
| `NTA_NT_GOOGLE_REQUIRED` | `1` | Google нужен перед управлением NinjaTrader (не для входа) |
| `NTA_NT_TELEGRAM_CONFIRM_REQUIRED` | `1` | Повторное подтверждение NT в Telegram |
| `NTA_DUAL_AUTH_REQUIRED` | alias → `NTA_NT_GOOGLE_REQUIRED` | Устаревший синоним |
| `NTA_STAGING_ALLOW_OWNER_TELEGRAM` | `0` (рекомендуется) | Не зеркалить в prod owner chats |
| `NTA_STAGING_ALLOW_REAL_PAYMENTS` | `0` | Запрет реальных платежей |
| `NTA_STAGING_ALLOW_LIVE_ORDERS` | `0` | Запрет live-ордеров |

### Production safety

- В `production` флаг `NTA_ENABLE_TEST_AUTH=1` **убивает старт** (`runtime_env.assert_production_safe`).
- Impersonation и test-auth API отвечают 403 вне staging.
- Секреты Google: `NTA_GOOGLE_CLIENT_ID` / `NTA_GOOGLE_CLIENT_SECRET` или DPAPI `data/integrations/google_oauth.dpapi` — **не в git**.

## Изоляция данных

Поднимайте staging с **отдельным** каталогом данных (копия только схем, не prod `accounts.dpapi`):

```text
set NTA_APP_ENV=staging
set NTA_ENABLE_TEST_AUTH=1
# отдельный working directory / отдельный data/ volume
python -m app.server
```

Не копируйте production `accounts.dpapi` и Telegram owner токены в staging без понимания, что mirror может писать в те же чаты (держите `NTA_STAGING_ALLOW_OWNER_TELEGRAM=0`).

## Быстрый сценарий владельца

1. Кабинет → вкладка **Staging QA**.
2. Создать virtual user (preset: `new` / `no_google` / `demo` / `paid` / `blocked`).
3. **Войти как** → красный banner «Тестовый режим…».
4. Пройти онбординг / демо / practice (когда будут в фазах B+).
5. **Вернуться в админку**.
6. Кабинет → **Мониторинг**: online, CPU/heap/network вкладки, auth-сессии, «Завершить».

### Presets

| id | Смысл |
|---|---|
| `new` | Новый, Google уже «привязан» тестово, онбординг не завершён |
| `no_google` | Telegram-only → экран «Подключите Google» |
| `demo` | Demo-доступ |
| `paid` | Платный тариф (роль full_control) |
| `blocked` | Заблокирован |

## API (staging)

- `GET /api/runtime/env`
- `GET /api/auth/test/status`
- `POST /api/auth/test/virtual-user` `{preset, display_name?}`
- `POST /api/auth/test/google-link` `{user_id?, google_sub?, email?}`
- `POST /api/owner/impersonate` `{user_id}`
- `POST /api/owner/impersonate/end`
- `GET /api/owner/support/monitoring` (+ `auth_sessions`)
- `GET /api/owner/sessions`
- `GET /api/owner/google-migration`

## Dual-auth на staging без настоящего Google

Если OAuth client ещё не создан:

1. Создайте user с preset `no_google`.
2. Impersonate / login.
3. На экране «Подключите Google» нажмите **Привязать тестовый Google (staging)**  
   → `POST /api/auth/test/google-link`.

Для реального OAuth задайте client id/secret (или сохраните через `POST /api/owner/google/secrets`) и redirect URI  
`https://<host>/api/auth/google/callback`.

## Чеклист ручной приёмки пункта 6

- [ ] Test auth полностью выключен в Production (старт падает при `NTA_ENABLE_TEST_AUTH=1`).
- [ ] Impersonation недоступен обычным пользователям и вне staging.
- [ ] Staging не пишет в production DB (отдельный data root).
- [ ] Banner всегда виден в режиме «как пользователь».
- [ ] Return to admin работает.
- [ ] Presets меняют доступ (`no_google` → needs_google, `blocked` → status).
- [ ] Audit: события `impersonation_started` / `impersonation_ended` / `virtual_user_upsert` в journal.
- [ ] Нет реальных платежей и live orders из staging.
