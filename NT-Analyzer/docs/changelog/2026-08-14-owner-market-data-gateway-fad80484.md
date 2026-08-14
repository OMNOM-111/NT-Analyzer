# Designated owner market-data gateway live on Canary + Production (`fad80484`)

Дата записи: `2026-08-14` UTC. Один signed artifact собран из merge SHA и
промоучен на Canary, проверен, затем без пересборки промоучен на Production.

## Live identity

| Field | Value |
| --- | --- |
| Git SHA | `fad80484e0a9b2c4e1f910170ce0561e9e690c0d` |
| Build ID | `sf-0.10.0-beta.1-fad80484e0a9-20260814T200443Z` |
| Archive SHA256 | `68BB2E85C54A8CD5C5B7E471136CF231F13050D6B26FCD64FF26730B3A045AEE` |
| Manifest SHA256 | `33DE8BAB3AC055B73DF7A7C00846EF695448D55E90EA6E06254CD9AC43135BF5` |
| Version / channel | `0.10.0-beta.1` / `beta`, `signature_verified`, `trust_tier=production` |
| Canary | `https://canary.stratforges.com`, `instance=stratforge-canary-01` |
| Production | `https://app.stratforges.com`, `instance=stratforge-linux-production-01` |

Оба окружения отвечают одним и тем же `build_id` и `artifact_sha256`.
Blue/green promote прошёл все восемь стадий на обоих окружениях.

## Что изменилось

PR #39 — единый назначенный owner market-data gateway; PR #40 — исправление
резолва origin для явной роли `consumer`, найденное на живом Canary.

Роль задаётся `NTA_OWNER_MARKET_DATA_GATEWAY_ROLE` и по умолчанию fail-closed:
без явного назначения окружение не открывает provider session даже при наличии
owner credentials. Живая конфигурация:

| Environment | Роль | Provider connections |
| --- | --- | --- |
| Production `api-app` | `hub` | 1 |
| Canary `api` | `consumer` | 0 |

До этого релиза `NTA_TOPSTEPX_USERNAME` / `NTA_TOPSTEPX_API_KEY` присутствовали
и в `canary.env`, и в `production-app.env`, то есть один owner credential
использовали два процесса одновременно.

## Проверено на живых окружениях

- Owner Telegram-вход по реальному пути shared-bot: `/start` приходит на
  Production webhook, `[CANARY]` форвардится на внутренний origin Canary.
  Обе среды вернули аутентифицированную owner-сессию.
- Owner-поверхности HTTP 200 на обоих окружениях: Documents, governance
  documents, Release Center (`/api/admin/releases` с `blue_green`),
  Environment Switcher (`/api/admin/environment-targets`), integrations,
  workspaces, strategies, NinjaTrader allocation, chart runtime, identity.
- Изоляция сессий, 24/24: анонимный запрос отклонён на обоих окружениях;
  Canary-сессия **не** аутентифицируется на Production; Canary-сессия работает
  на Canary.
- Production hub: `lease.held=true`, `renewal_running=true`,
  `login_key_calls=1`, `signalr_connections_open=1`,
  `direct_provider_connections=1`, `wire_subscriptions=5` при
  `logical_subscription_deduplicated=16`, `warnings=[]`.
- Canary consumer: `direct_provider_connections=0`, `login_key_calls=0`,
  `signalr_connections_open=0`, графики `status=external_live`, `live=true`,
  `chart_source_mode=owner_gateway_consumer`, lease показывает владельцем
  Production.

Итог: живые графики на обоих окружениях при **одном** provider-подключении на
всю топологию.

## Известные различия и ограничения

- `/api/ops/runtime/status` отдаёт 200 на Production и `no route` на Canary при
  одном и том же артефакте. Это различие данных, а не кода: активная рабочая
  область owner на Production персональная (`uses_owner_runtime=false`), и
  greedy-заглушка `workspaces.runtime_stub` отвечает на любой путь под
  `/api/ops/runtime/`, включая несуществующий; на Canary активная область
  использует owner runtime, и заглушка не срабатывает.
- Lease защищает от дублей в пределах одного хоста. Кросс-хостовый дубль
  механически не блокируется — локальные копии должны консьюмить назначенный
  hub, а не назначать себя hub'ом.
- Google OAuth и transactional email остаются `configured: false` на обоих
  окружениях: внешние блокеры, кодом не закрываются.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T20:15:00Z | Claude Opus 5 через Claude Code по запросу owner | Live release fad80484 на Canary+Production: designated owner market-data gateway, один provider connection на топологию, owner login/Documents/Release Center/Charts/isolation PASS на обоих окружениях.
-->
