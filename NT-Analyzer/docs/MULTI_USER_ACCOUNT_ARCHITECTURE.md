# Multi-user accounts, subscriptions and NinjaTrader connections

Цель: превратить текущий личный NT-Analyzer в многопользовательское приложение,
где ваш аккаунт NinjaTrader может оставаться учебным read-only окружением, а
каждый другой пользователь получает собственный изолированный контур: профиль,
подписку, рабочую область, локальное подключение NinjaTrader и отдельные данные.

## Текущее состояние

- `app/account_auth.py` уже даёт identity layer: Telegram user id, профиль,
  сессии, роли `read_only`, `full_control`, `owner`, подтверждение владельцем и
  DPAPI-хранилище `data/integrations/accounts.dpapi`.
- `/api/auth/users` и экран `Пользователи` управляют доступом к одному backend,
  а не к независимым рабочим областям.
- Runtime endpoints вроде `/api/ops/runtime/accounts` читают один локальный
  NinjaTrader bridge и один набор файлов `data/runtime/*`.
- Mini App намеренно запрещает live-действия. Paper/demo действия проходят через
  отдельные backend gates.

Из этого следует главный архитектурный запрет: нельзя расширять поле `role` до
"подписки", "владельца счета" или "подключения NinjaTrader". Эти понятия
должны быть отдельными сущностями.

## Новая модель

### IdentityUser

Глобальная личность пользователя. Это развитие текущего `account_auth`:

- `user_id` - Telegram id, неизменяемый внешний идентификатор;
- `username`, `first_name`, `last_name`, `email`, `phone_hash`;
- `avatar_path` или `avatar_blob_id` для фотографии профиля;
- `status`: `pending`, `active`, `revoked`, `denied`;
- `is_global_owner`: true только у владельца системы;
- сессии, CSRF и audit остаются в auth layer.

Identity отвечает только на вопрос "кто вошел".

### Workspace

Рабочая область изолирует данные, NinjaTrader-подключения и лимиты:

- `workspace_id` - случайный стабильный id;
- `kind`: `owner_training`, `personal`, `team`, `support`;
- `owner_user_id` - владелец рабочей области;
- `display_name`, `created_at_utc`, `status`;
- `data_root`: например `data/tenants/<workspace_id>/`;
- `default_runtime_connection_id`;
- `entitlement_id` - активная подписка или промо-грант.

Ваш текущий локальный контур мигрирует в `owner_training` workspace. Другие
пользователи могут открыть его только как учебный read-only просмотр, если вы
явно выдаёте такой доступ.

### WorkspaceMembership

Связь пользователя с workspace:

- `workspace_id`, `user_id`;
- `role`: `owner`, `admin`, `operator`, `viewer`, `developer`;
- `permissions`: вычисляемые capabilities, не редактируются руками в UI;
- `support_expires_at_utc` для временного доступа разработчика/поддержки;
- `created_by_user_id`, `revoked_at_utc`.

Роли доступа к приложению и роли внутри workspace не смешиваются. Например,
пользователь может быть `active` в auth, `viewer` в вашем учебном workspace и
`owner` в своём personal workspace.

### NinjaTraderConnection

Подключение к конкретному локальному NinjaTrader на компьютере пользователя:

- `connection_id`, `workspace_id`, `owner_user_id`;
- `device_id`, `bridge_instance_id`, `machine_label`;
- `mode`: `local_node`, `relay_node`, `owner_local`;
- `status`: `pairing`, `online`, `offline`, `revoked`;
- `capabilities`: `accounts_read`, `paper_commands`, `live_read`,
  `live_commands`;
- `last_heartbeat_utc`, `bridge_version`, `ninjatrader_version`;
- `account_names`: masked/listed accounts discovered from that bridge.

NinjaTrader credentials are never collected by NT-Analyzer. User logs into
NinjaTrader locally; app sees only bridge telemetry and allowed command results.

Recommended topology for MVP: local-first personal node. Each user installs
NT-Analyzer/bridge on the same Windows machine as NinjaTrader. A future hosted
control plane can add an outbound relay, but live commands must still terminate
on the user's local node and be signed/audited there.

### SubscriptionEntitlement

Право пользоваться функциями:

- `entitlement_id`, `user_id`, optional `workspace_id`;
- `plan_id`: `owner_unlimited`, `developer_free`, `learner_viewer`,
  `personal_basic`, `personal_pro`;
- `status`: `trial`, `promo_grant`, `active`, `past_due`, `cancelled`,
  `expired`;
- `features`: derived capabilities, for example `ai_lab`, `personal_nt`,
  `paper_commands`, `live_read`, `live_commands`, `team_seats`,
  `max_backtests_per_day`;
- `starts_at_utc`, `expires_at_utc`, `renew_at_utc`;
- `source`: `owner_grant`, `promo_code`, `payment_provider`, `manual`.

Owner всегда получает `owner_unlimited`. Разработчикам для тестирования выдаётся
`developer_free` или план через promo voucher без требования карты.

### PaymentProfile

Платёжные данные не хранятся в приложении:

- `user_id`;
- `provider`: `stripe`, `yookassa`, `cloudpayments`, `manual_donation`, etc.;
- `provider_customer_id`, `provider_subscription_id`;
- `billing_status`, `last_payment_at_utc`, `next_action_url`;
- только masked metadata, без номеров карт и CVC.

На старте можно оставить `manual_donation` и promo-only режим, а позже добавить
checkout provider и webhook. Если промокод даёт 100% бесплатный доступ, карта не
нужна. Если остаётся сумма к оплате, пользователь идёт в checkout провайдера.

### PromoVoucher

Код генерирует только owner:

- `voucher_id`;
- `code_hash` - plaintext code показывается один раз при создании;
- `created_by_user_id`;
- `label`: например `DEV-JULY-2026`;
- `discount_percent` или `grant_plan_id`;
- `grant_duration_days` или `expires_at_utc = null` для бессрочного dev access;
- `usage_limit`, `used_count`;
- `per_user_limit`;
- optional `allowed_email_domains`, `allowed_telegram_ids`;
- `status`: `active`, `paused`, `exhausted`, `expired`.

Redeem создаёт `SubscriptionEntitlement` и audit-событие. Повторный ввод того же
кода должен быть идемпотентным для уже активированного пользователя.

## Регистрация пользователя

1. Пользователь входит через Telegram, отправляет contact и заполняет профиль.
2. Новый экран onboarding предлагает выбрать режим:
   - `Учебный просмотр аккаунта владельца` - read-only доступ к вашему
     `owner_training` workspace, если вы подтвердили пользователя.
   - `Мой личный NinjaTrader` - создание personal workspace.
3. Пользователь выбирает план. На этом шаге есть поле `Промокод`.
4. Backend проверяет voucher:
   - 100% free или developer grant - создаёт entitlement сразу;
   - partial discount - создаёт checkout session на остаток;
   - invalid/expired/exhausted - возвращает понятную ошибку без создания доступа.
5. После entitlement создаётся personal workspace.
6. Если выбран личный NinjaTrader, UI показывает pairing wizard:
   - установить/обновить bridge;
   - открыть NinjaTrader локально;
   - ввести одноразовый pairing code или отсканировать deep link;
   - дождаться heartbeat и списка accounts;
   - выбрать default account и risk profile.
7. UI переключает пользователя в его personal workspace. Ваш workspace остаётся
   отдельным пунктом переключателя, если у пользователя есть membership.

## Owner capabilities

Owner управляет системой, но не получает broker credentials пользователей:

- видеть список пользователей, их статусы, подписки, промо-активации и
  подключенные workspaces;
- генерировать, приостанавливать и отзывать promo vouchers;
- выдавать ручные grants разработчикам;
- отзывать доступ пользователя или membership;
- входить в support view пользователя только read-only по явному audit-событию;
- менять системные настройки, Telegram, tunnel, payment provider;
- управлять своим `owner_training` workspace без лимитов.

Live-действия в чужом personal workspace по умолчанию запрещены даже owner. Если
позже понадобится управляемая поддержка, она должна быть отдельным временным
permission с подтверждением пользователя и отдельным audit trail.

## API contracts

Добавить поверх существующих endpoints:

- `GET /api/auth/me` - identity, active workspace, memberships,
  subscription summary;
- `POST /api/auth/profile/avatar` - загрузка/удаление фото профиля;
- `GET /api/workspaces` - доступные рабочие области;
- `POST /api/workspaces` - создать personal/team workspace, если entitlement
  позволяет;
- `POST /api/workspaces/select` - установить active workspace в сессии;
- `GET /api/billing/plans` - планы, лимиты, цена, trial/promo policy;
- `POST /api/billing/promo/preview` - проверить код до оплаты;
- `POST /api/billing/promo/redeem` - применить код;
- `POST /api/billing/checkout` - создать external checkout session;
- `POST /api/billing/webhook/<provider>` - provider callback;
- `GET /api/owner/vouchers` и `POST /api/owner/vouchers` - owner-only;
- `POST /api/owner/vouchers/<id>/pause|resume|revoke` - owner-only;
- `GET /api/owner/subscriptions` - owner-only обзор подписок;
- `POST /api/bridge/pair/start` - создать pairing code для active workspace;
- `POST /api/bridge/pair/complete` - bridge подтверждает пару;
- `GET /api/bridge/connections` - список подключений active workspace;
- `POST /api/bridge/connections/<id>/revoke` - отозвать локальный bridge.

Все runtime endpoints получают workspace context из сессии, а не из глобального
состояния. Прямой query `workspace_id` допустим только для owner/admin и должен
проходить membership check.

## Storage layout

Минимальная миграция без внешней БД:

```text
data/
  integrations/
    accounts.dpapi              # identity + sessions, как сейчас
    entitlements.dpapi          # subscriptions, payment refs, vouchers
  tenants/
    <workspace_id>/
      tenant.json               # workspace metadata
      memberships.json          # local cache / migration stage
      runtime/                  # accounts, positions, executions for this workspace
      ops/                      # strategy state and audit scoped to workspace
      portfolio/                # cells scoped to workspace
      reports/                  # user/workspace reports
      statements/               # statement imports and cash events
  audit/
    account-auth.jsonl
    billing.jsonl
    workspace-access.jsonl
    bridge-pairing.jsonl
```

Когда появится hosted control plane, эти документы можно перенести в SQLite/Postgres
с теми же ключами. Важно сначала внедрить `workspace_id` во все read/write paths.

## UI changes

- В topbar добавить workspace switcher: `Мой NinjaTrader`, `Учебный аккаунт`,
  team/workspaces.
- В onboarding добавить шаги `План`, `Промокод`, `Оплата`, `Подключить
  NinjaTrader`.
- В `Пользователи` разделить вкладки: `Доступ`, `Подписки`, `Промокоды`,
  `Подключения`.
- В профиле пользователя добавить avatar, e-mail, телефон mask, подписку,
  активный workspace и историю выписок/движений средств.
- На trading/performance/AI Lab страницах показывать active workspace и
  capability badges. Если пользователь смотрит owner training workspace, все
  изменяющие действия скрыты и backend всё равно возвращает 403.

## Safety rules

- Любая запись runtime/account/report/portfolio должна иметь `workspace_id`.
- Нет `workspace_id` - нет записи. Старые глобальные файлы читаются только через
  migration adapter owner workspace.
- Live commands требуют одновременно: personal workspace, user-owned bridge,
  active entitlement, explicit capability, risk profile, UI confirmation,
  backend audit и local bridge confirmation.
- Owner training workspace всегда read-only для не-owner пользователей.
- AI agents не получают live/paper права из плана подписки автоматически.
- Payment provider хранит карты. NT-Analyzer хранит только provider ids и masked
  status.
- Promo code plaintext не сохраняется; хранится только hash.

## Implementation phases

1. **Contract and terminology**: добавить этот документ, UI/API ссылки и
   переименовать в коде понятия так, чтобы `role` не означала подписку.
2. **Entitlements and promo MVP**: модуль `app/subscriptions.py`, DPAPI storage,
   owner endpoints для voucher, user endpoints preview/redeem, тесты на 100%
   free developer codes.
3. **Workspace isolation**: `app/workspaces.py`, active workspace в auth context,
   миграция текущих `data/runtime`, `data/ops`, `data/portfolio` в owner
   workspace adapter.
4. **UI onboarding**: план/промокод/profile/avatar/workspace switcher. Оплата
   пока mock/manual donation + promo grants.
5. **Personal NinjaTrader pairing**: bridge connection registry, pairing code,
   heartbeat per workspace, runtime endpoints routed through selected connection.
6. **Payment provider**: checkout, webhook, subscription renewal/past_due,
   invoices/donation receipts.
7. **Owner console**: users, subscriptions, vouchers, workspaces, support view,
   audit export.

## First developer slice

Самый маленький полезный slice для команды:

1. Создать `app/subscriptions.py` с `plans`, `create_voucher`, `preview_voucher`,
   `redeem_voucher`.
2. Хранить vouchers/entitlements в `data/integrations/entitlements.dpapi`.
3. Добавить owner-only API для генерации кода и user API для redeem.
4. Добавить тест: owner создаёт бессрочный `developer_free` voucher, новый
   пользователь вводит код, получает active entitlement без карты.
5. UI: в экран `Пользователи` добавить вкладку `Промокоды`; в login/onboarding
   добавить поле промокода.

Этот slice не трогает live trading и не меняет bridge. Он проверяет самую
важную новую ось: доступ теперь выдаётся через entitlement, а не через одну роль
в auth layer.

## Implemented MVP status

- `app/subscriptions.py`: DPAPI-хранилище plans/vouchers/entitlements,
  owner-only генерация voucher, self-service preview/redeem, 100% free developer
  grants без карты и скидочные коды с `checkout_required=true`.
- `app/workspaces.py`: DPAPI-хранилище workspaces/memberships/active workspace,
  owner-training workspace, personal workspace, bridge pairing registry,
  isolated tenant statement ledger.
- `app/server.py`: `/api/auth/status` возвращает `workspaces`,
  `active_workspace`, `active_membership`; runtime GET endpoints читают owner
  `data/runtime/*` только в owner-training контуре. Personal workspace до bridge
  pairing получает безопасный empty runtime и не видит owner accounts. После
  pairing backend читает runtime из `data/tenants/<workspace_id>/runtime`.
- `bridge/`: конфиг получил `runtime_data_dir`, поэтому локальный NinjaTrader
  пользователя можно направить в tenant runtime directory без изменения кода
  bridge.
- Aurora API adapter поддерживает billing, workspaces and bridge pairing calls;
  topbar показывает active workspace и открывает drawer переключения.
- Regression coverage: `tests/test_account_auth.py`, `tests/test_subscriptions.py`,
  `tests/test_workspaces.py`.
