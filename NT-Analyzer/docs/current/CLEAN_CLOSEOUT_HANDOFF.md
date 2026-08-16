# Clean closeout — executable handoff

Дата: `2026-08-17` UTC. Продолжать **с FIRST NEXT STEP**, повторный аудит не нужен.

## LIVE состояние (проверено)

| | |
| --- | --- |
| Canary | `0.10.0-beta.13`, artifact `CF2C053DEA3D6FA8…`, schema **13** |
| Production | `0.10.0-beta.13`, artifact `CF2C053DEA3D6FA8…`, schema **13** |
| Parity | EXACT MATCH, acceptance PASS |
| Human users | 1 canonical owner `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f`, identities Telegram+Google+email, 1 trusted device |

## FIRST NEXT STEP — 0014 не применяется: InsufficientPrivilege

`0.10.0-beta.14` (PR #90/#91, migration 0014 identity history) **не выкачена**.
Canary-деплой корректно отказал, откатился, обе среды остались на `beta.13`.
Это ровно то поведение, ради которого делался честный `expand_migrate`:
код не поехал на несмигрированную схему.

Прямой запуск под migration-ролью:

```
tools/production_storage_cli.py schema --apply --url-env STRATFORGE_MIGRATION_DATABASE_URL
  -> {"ok": false, "code": "storage_error",
      "error": "PostgreSQL migration failed: InsufficientPrivilege"}
```

Роль `stratforge_canary_migration` владеет таблицами и успешно применила 0013,
поэтому проблема в конкретном statement внутри 0014. **Проверено и исключено:**
`sf_identity_uuid_v1` не имеет REVOKE (PUBLIC может выполнять).

Наиболее вероятный кандидат — `CREATE POLICY`, чьё выражение вызывает
`sf_scope_global()` / `sf_scope_user()`: в 0001 у них
`REVOKE ALL ... FROM PUBLIC` и `GRANT EXECUTE ... TO stratforge_app`,
migration-роли EXECUTE не выдан. 0006 создаёт RLS-политику похожим образом —
надо сравнить, чем она отличается, и либо выдать EXECUTE migration-роли
отдельной миграцией, либо сформулировать политику 0014 так же, как в 0006.

Диагностика в один шаг (печатает конкретный failing statement):

```
scratchpad/apply_schema.py canary 0.10.0-beta.14-199e73cd5422 --apply sha:<set sha>
```

Полезно добавить вывод `exc.diag.message_primary`/`context` в
`production_storage_cli`, сейчас наружу отдаётся только имя класса ошибки.

## Программа (порядок задан владельцем)

`2 → 3 → 6 → 4 → 7 → 8 → 9 → 5 → 10 → 11 → 12`

| # | что | статус |
| --- | --- | --- |
| 1 | identity uniqueness + DB constraints | **ЗАКРЫТО**, 0013 live, UniqueViolation подтверждён |
| 2 | identity history | код смержен (PR #90); **ждёт применения 0014** |
| 3 | Physical Device → Clients → Sessions | не начато |
| 6 | Environment Registry (LOCAL публикует heartbeat) | не начато |
| 4 | User Card / Cabinet поверх итоговых моделей | не начато |
| 7 | Connectors: partial render + per-source timeout | не начато (frontend; backend уже 173→50 ms) |
| 8 | Documents: один раздел | не начато |
| 9 | Admin UX: Monitoring / Subscriptions / Journal | не начато |
| 5 | NinjaTrader per-environment binding | требует запущенного NT у владельца |
| 10 | security/adversarial suite | частично: 37 тестов identity + 19 history |
| 11–12 | new-user E2E, browser E2E | требуют provider consent |

## Что сделано в этой сессии

- **PR #88 + 0013** — verified e-mail уникален **по всем провайдерам**
  (старый индекс был `WHERE provider = 'email'` — дыра для Google-с-тем-же-адресом);
  `verified_phone_e164` с E.164 CHECK и unique index (раньше телефона в
  constraints не было вовсе); нормализация отвергает control/zero-width/RTL,
  сохраняет точки и plus-теги, предлагает исправление опечатки (включая
  транспозицию `gmial`→`gmail`) и **никогда не правит адрес молча**.
- **PR #89 / beta.13** — первый релиз, где `expand_migrate` реально
  **применил** миграцию: `{"applied_now": [13], "pending_after": 0}` на обеих
  средах.
- **PR #90** — `sf_identity_history`: append-only, `add → verify → activate →
  retire` одним шагом, два partial unique index (одна живая заявка на
  идентификатор глобально; одно активное значение на аккаунт на провайдер),
  `ON DELETE SET NULL` чтобы история пережила удаление аккаунта, маскированный
  рендер, переприсвоение только явным audited flow.

## Грабли

- Значение в `*-maintenance.env` **обязано** быть в одинарных кавычках: DSN
  содержит `&`/`?`/`=`, без кавычек `set -a; . file` даёт пустую переменную.
- Приложение перегенерирует `data/governance-rendered/*` при старте →
  `git stash push -- NT-Analyzer/data/` перед каждым билдом.
- `VERSION.json`: `build_date` обязан совпадать с датой `build_timestamp_utc`.
- Ad-hoc python-проба без окружения `start.ps1` резолвит другой data root и
  врёт про `isolated`/`not_configured`. Верить только запущенному серверу.

## WAITING FOR OWNER (не блокирует пункты 2–4, 6–9)

1. Физический Telegram/Google/e-mail consent для temporary user (пункты 11–12).
2. Запущенный NinjaTrader на LOCAL и на Production-машине (пункт 5).
3. Ротация 4 секретов — только после полного технического PASS.

## Item 9 — performance: ЗАКРЫТО (PR #85)

Профиль всех Admin-поверхностей. Выше 120 ms p50 оказались два эндпоинта, и
причина у обоих одна: `market_data_failover.status()` пересобирал снимок
провайдеров на каждый запрос (~90 ms тёплый, из них ~47 ms — один
`public_status()`), а читают его и bars/status, и дашборд коннекторов,
который UI опрашивает.

Снимок мемоизирован на 3 секунды, наружу отдаются независимые копии,
`fresh=True` обходит кэш.

| endpoint | p50 | p95 |
| --- | --- | --- |
| `/api/admin/connectors` | **173.5 → 49.9 ms** | 354.8 → 108.8 ms |
| `/api/ops/runtime/bars/status` | **128.0 → 30.9 ms** | 286.8 → 36.5 ms |

Остальное ниже 50 ms p50 — не трогалось. Payload'ы в норме после более раннего
сокращения аватара; самый крупный — снимок баров ~32 КБ, это сами данные.

## Release Center: терминальное состояние подтверждено

`0.10.0-beta.12` — первый релиз, дошедший до **`production_live`** (фикс
PR #79). `expand_migrate` на обоих окружениях отдал честный `skipped` с
реальным checksum набора.

## Осталось (не начато)

1. ~~LOCAL market data~~ — см. выше — код consumer'а смержен (PR #62), осталось положить
   `NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN` в LOCAL secret store и доказать
   LIVE на LOCAL + Canary + Production при одной provider connection.
3. RBAC/Admin во всех окружениях.
4. Встроенный Connectors/Telegram dashboard.
5. Environment Switcher auto-load.
6. New-user onboarding E2E + удаление тестового пользователя.
7. Market-data regression (репозиторная часть зелёная: 136 passed).
8. Browser E2E LOCAL → CANARY → PRODUCTION.
9. Повторный perf-замер.

## Готовые инструменты (в репозитории)

`tools/drive_release.py`, `tools/host_user_cleanup.py`, `tools/host_fk_audit.py`,
`tools/host_blockers.py`, `tools/admin_reach.py`.
Запуск host-скриптов: `scratchpad/run_host_script.py`,
интерпретатор через `SF_REMOTE_PYTHON=canary|production`.

## Грабли

- Прерванный деплой раньше делал версию непересобираемой — **исправлено
  (PR #68)**: каталог уходит в `$RELEASES/.quarantine`, живой не трогается.
- Приложение перегенерирует `data/governance-rendered/*` при старте, а Release
  Center отказывает на грязном дереве → `git stash push -- NT-Analyzer/data/`.
- `VERSION.json`: `build_date` обязан совпадать с датой `build_timestamp_utc`.
- **Значение в `*-maintenance.env` обязано быть в одинарных кавычках.** DSN
  содержит `&`, `?`, `=`; без кавычек `set -a; . file` даёт **пустую**
  переменную (bash читает `&` как оператор), и миграции падают с
  «Required database URL environment variable is empty». Ошибку видно только
  по пустому значению, не по ошибке sourcing.

## WAITING FOR OWNER

1. Физический Google/Telegram/email клик там, где OAuth-consent нельзя пройти
   автоматизацией.
2. Ротация четырёх секретов (Google ×2, Resend ×2) — **только после полного
   технического PASS**.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-16T21:30:00Z | Claude Opus 5 через Claude Code по запросу owner | Production migration credential восстановлен по санкции владельца (ACL temporary + exact restore), migration 0012 применена на обоих окружениях, четыре дефекта удаления аккаунта исправлены (PR #60/#62/#71/#73), база очищена до canonical owner на Canary и Production, parity beta.10 EXACT MATCH, orphan integrity PASS.
-->
