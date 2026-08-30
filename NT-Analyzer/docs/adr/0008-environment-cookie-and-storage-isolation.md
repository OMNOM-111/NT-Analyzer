# ADR-0008: Изоляция cookie и local-storage по окружениям


- Статус: Принято
- Дата решения: 2026-08-03

## Контекст

Development, Canary и Production делят один браузер оператора и, для Canary и
Production, один registrable-домен `stratforges.com` (`canary.stratforges.com` и
`stratforges.com`). Браузерная per-origin изоляция storage/cookie надёжна для
Development (`localhost` — отдельный origin), но **не** гарантирует, что cookie,
установленная с `Domain=.stratforges.com`, не будет отправлена и на Canary, и на
Production. Поэтому одного origin isolation недостаточно между Canary и
Production.

## Решение

Каждое окружение использует **отдельное имя** session-cookie и **отдельный**
local-storage namespace:

| Окружение | Session cookie | local-storage prefix |
|---|---|---|
| Development | `sf_session` | (без префикса) |
| Canary | `sf_canary_session` | `canary:` |
| Production | `sf_production_session` | `production:` |

- Реализация: `app/runtime_env.session_cookie_name()` и
  `app/runtime_env.local_storage_namespace()`; браузерная сторона —
  `lsNamespace()` в `app/static/aurora/assets/ui.js` (детектит host).
- Cookie ставится host-only (без `Domain=`), `HttpOnly`, `SameSite=Strict`,
  `Secure` на HTTPS (`app/server.py` `_set_session_cookie`).
- Development сохраняет каноническое имя `sf_session` — существующие локальные
  сессии и тест-сьют не ломаются. Production ещё не развёрнут, поэтому явное имя
  `sf_production_session` не ломает миграцию существующих сессий.

## Threat analysis

| Угроза | Митигация |
|---|---|
| Cookie Production принимается Canary (общий parent-домен) | Отдельные имена cookie: Canary читает только `sf_canary_session`, Production — только `sf_production_session`; токен одного не виден как session другого. |
| Domain-wide cookie утекает на субдомен | Cookie host-only (без `Domain=`), поэтому не рассылается на другие хосты; отдельные имена — defence in depth. |
| Общий local-storage между контурами в одном браузере | Отдельный namespace-префикс на каждое окружение (defence in depth поверх per-origin storage). |
| Session fixation через чужой контур | `SameSite=Strict` + `HttpOnly` + отдельные имена; сессия не переносится между origin (`noopener,noreferrer` в Environment Switcher). |
| Development токен принимается Production | Разные origin (`localhost` vs `stratforges.com`) + разные имена cookie. |

## Тесты

`tests/test_phase7_canary_isolation.py` (session_cookie_name / local_storage_namespace
per env) и `tests/test_phase11_env_isolation.py` (полная матрица трёх окружений +
контракт host-only cookie в `_set_session_cookie`).

## Последствия

ADR-0001 утверждал, что окружения «не разделяют cookies … local-storage
namespaces»; этот ADR делает распределение имён явным и проверяемым. Реального
переkey-инга существующих Production-сессий не требуется (Production не
развёрнут).
