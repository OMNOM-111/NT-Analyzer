# Clean closeout — executable handoff

Дата: `2026-08-17` UTC. Продолжать **с FIRST NEXT STEP**, повторный аудит не нужен.

## LIVE состояние (проверено)

| | |
| --- | --- |
| Canary | `0.10.0-beta.15`, artifact `022FD4034FE98EF1…`, schema **14** |
| Production | `0.10.0-beta.15`, artifact `022FD4034FE98EF1…`, schema **14** |
| Parity | EXACT MATCH — build stamp `sf-0.10.0-beta.15-d8ee4815b493-20260817T014256Z` на обеих средах |
| Human users | 1 canonical owner `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f`, identities Telegram+Google+email, 1 trusted device |

Item 2 закрыт. `sf_identity_history` живёт на обеих средах, backfill
email/google/telegram по одной active-записи, и все инварианты **проверены на
живой БД, а не только в тестах**: дубль active-ключа → UniqueViolation,
`active` без `verified_at` → CheckViolation, `active` с `valid_to` →
CheckViolation, вторая active-identity того же пользователя → UniqueViolation,
чтение без scope → 0 строк (RLS).

> Ловушка при проверке: запрос к `sf_identity_history` **до**
> `SET LOCAL stratforge.service_scope` возвращает пусто из-за RLS, и это
> выглядит как «backfill не сработал». `SET LOCAL` умирает вместе с
> транзакцией — после каждого `rollback()` scope нужно объявлять заново, иначе
> отказывает RLS, а не проверяемое ограничение.

## FIRST NEXT STEP — item 3 в релиз, дальше item 6

Код item 3 (physical device → clients → sessions) готов и смержен.
Осталось прогнать релизный цикл: `drive_release.py` → Canary
(`expand_migrate` должен показать `applied_now: [15]`) → проверка схемы →
`promote_prod.py` того же кандидата. После этого сразу item 6
(Environment Registry), без вопросов — порядок зафиксирован владельцем.

Миграция 0015 **проверена на живых Canary и Production** до коммита: все
statements применяются, и backfill отдельно прогнан на синтетических
Connector-строках внутри откатываемой транзакции (`scratchpad/backfill_0015.py`).
Результат: два разных installation → две машины; installation,
зарегистрированный дважды (revoked + trusted), схлопывается в одну машину с
двумя клиентами; машина наследует таймлайн живой записи, а не дату миграции;
browser-клиенты остаются непривязанными; hash, который считает приложение,
совпадает с тем, что пишет SQL.

## Программа (порядок задан владельцем)

`2 → 3 → 6 → 4 → 7 → 8 → 9 → 5 → 10 → 11 → 12`

| # | что | статус |
| --- | --- | --- |
| 1 | identity uniqueness + DB constraints | **ЗАКРЫТО**, 0013 live, UniqueViolation подтверждён |
| 2 | identity history | **ЗАКРЫТО**, 0014 live на обеих средах, инварианты проверены на живой БД |
| 3 | Physical Device → Clients → Sessions | **код готов**, 0015 проверена на живых средах; ждёт релизного цикла |
| 6 | Environment Registry (LOCAL публикует heartbeat) | не начато |
| 4 | User Card / Cabinet поверх итоговых моделей | не начато |
| 7 | Connectors: partial render + per-source timeout | не начато (frontend; backend уже 173→50 ms) |
| 8 | Documents: один раздел | не начато |
| 9 | Admin UX: Monitoring / Subscriptions / Journal | не начато |
| 5 | NinjaTrader per-environment binding | требует запущенного NT у владельца |
| 10 | security/adversarial suite | частично: 37 тестов identity + 19 history + 34 physical devices |
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

## Item 3 — модель устройств: что именно сделано

Три уровня вместо одного плоского: **машина → клиент → сессия**.
`sf_trusted_devices` всегда был *клиентом* (профиль браузера или установка
приложения) — он им и остался, expand-only, без переписывания строк.
Новая `sf_physical_devices` — это машина.

Главное правило, ради которого уровень и вводился: **машина никогда не
выводится эвристикой**. User-Agent, IP, hostname и имя аккаунта одинаковы для
всех пользователей деплоймента и меняются сами по себе — по ним один ноутбук
разъезжается на несколько «машин», а ноутбуки разных людей слипаются в один.
Единственный источник machine identity — hardware-bound credential Windows
Connector'а. Браузер такого не имеет и **не может** получить машину сам: он
входит в неё только через одноразовый pairing-код, выданный уже доверенным
Connector'ом на этой же машине. Клиент без машины — нормальное состояние.

Доверие раздельное по уровням:

- подтверждение Connector'а подтверждает и его машину (credential привязан к
  железу, код пришёл по уже верифицированному каналу);
- подтверждение браузера **не** подтверждает никакую машину;
- доверенная машина **не** делает доверенным новый клиент на ней;
- отзыв клиента не трогает машину и соседние клиенты;
- **отзыв машины каскадит**: все её клиенты и все их сессии, плюс живой
  pairing-код. Это единственное направление каскада, и ровно ради него уровень
  существует.

Два дефекта, найденных собственными тестами и исправленных здесь же:
`PhysicalDeviceError` уходил наружу мимо HTTP-слоя (500 вместо 404), и —
серьёзнее — неудачные попытки pairing не сохранялись, потому что исключение
летело до `_write_doc`; счётчик попыток не накапливался, и восьмизначный код
можно было подбирать без лимита.

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
