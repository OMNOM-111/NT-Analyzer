# Aurora UI API map

Актуально на 2026-07-01 после добавления безопасного реестра AI Agents и
Витёк является пользовательским лицом, StratForge Orchestrator — его внутренним шлюзом. Единственный HTTP-адаптер интерфейса находится в
`app/static/aurora/assets/api.js`. Production не загружает mock-данные.

Планируемый multi-user слой не должен расширять текущую роль auth до подписки
или владения NinjaTrader. Новые контракты `workspace`, `subscription`,
`promo voucher` и `NinjaTraderConnection` описаны в
`MULTI_USER_ACCOUNT_ARCHITECTURE.md`.

Именованные domain agents добавляют `/api/ai-lab/accounting`,
`/api/ai-lab/strategy-analysis`, `/api/ai-lab/domain-agents` и POST
`/api/ai-lab/domain-agents/message`. Общий endpoint Orchestrator также
распознаёт обращения `Марина, ...` и `Толик, ...`.
Новостной агент использует `/api/ai-lab/news-analysis`; общий чат также
распознаёт `Никита, ...`.

## Страницы

| Страница | Источники данных | Изменяющие действия |
|---|---|---|
| Обзор | `/api/health`, `/api/performance`, `/api/coverage`, `/api/ai-lab/summary`, `/api/reports`, `/api/news`, accounts/account-history | системные действия вынесены в общее меню |
| Бэктест | catalog, instruments, profiles, coverage, reports, jobs, trades, bars, draw objects, favorites, batches | создать job/batch, отменить/удалить job, favorite/unfavorite; серверные фильтры/сортировка не изменяют данные |
| Торговля | accounts, account-history, strategies, positions, orders, executions, errors, commands/results/status, runtime history, strategy history/display, start dates, performance, diagnostics, strategy journal | paper-only enable/disable существующих strategy instances, reconnect modeling для paper/demo/playback, ручное движение, CSV-импорт, классификация движения, восстановление скрытого класса |
| Финансы | performance, performance/trades, AI accounting, accounts, account-history, CSV | единые фильтры доходности и бухгалтерии, пагинация, drilldown и выгрузка; спорные записи не исправляются моделью |
| Стратегии | profiles/archive, AI lifecycle/cell history, coverage, instruments, persistent portfolio registry | статус/удаление профиля, add root/cell, archive cell, hide runtime class, NinjaTrader cleanup |
| AI Lab | summary, experiments/activity, staged run/current status, параллельно проектируемая следующая стратегия, Orchestrator conversation/model/actions, performance board, model-performance, cloud-agent roles/pricing/usage, calendar, compile source, errors, LM Studio | natural-language Orchestrator chat; ручной run/cancel, bootstrap/unload, operator note, stale sweep, user-research scan; локальная настройка cloud keys, role routes и hard budgets |
| AI Agents / API Keys | `/api/ai-agents`, usage, account/provider/role catalogs, DPAPI status, shared grant/budget totals | Add/Edit/Delete model, Test Connection, Enable/Disable, supported balance sync; transport/auth определяются автоматически, ключ возвращается только маской |
| Новости | `/api/news`, `/api/news/live`, `/api/ai-lab/news-analysis` | read-only; официальный календарь, анализ Никиты, рекомендации, здоровье источников и приоритетные ленты |
| TopStep | `/api/topstep/status` | read-only scaffold; live-действия принудительно отключены до отдельной валидации |
| Telegram | `/api/telegram/status` | token validation, one-time private-chat pairing, notification settings, test send, disconnect; токен и chat id не возвращаются |
| Витёк | `/api/ai-lab/orchestrator`, `/api/ai-lab/orchestrator/message` | единый естественный диалог; внутреннее распределение через Управляющего и агентов, безопасные действия и краткие решения без показа технического маршрута |
| Документы | governance documents, runtime defaults, history | save с actor/reason и подтверждением |

## Новые постоянные контракты

- `GET/POST /api/portfolio/*` использует `app/portfolio_registry.py`. ID ячейки
  неизменяем, архивный ID не переиспользуется. Базовая схема `CELL-001..180`
  сохранена, включая `MNQ slot 11 = CELL-126`.
- `GET /api/billing/plans`, `GET /api/billing/me`,
  `POST /api/billing/promo/{preview,redeem}` и `GET/POST /api/owner/vouchers`
  используют `app/subscriptions.py`. Промокод хранится только как hash; plaintext
  code показывается owner один раз при создании. `read_only` пользователь может
  выполнить только self-service preview/redeem, owner-voucher endpoints остаются
  owner-only.
- `GET /api/workspaces`, `POST /api/workspaces/{personal,select}`,
  `GET /api/bridge/connections`, `POST /api/bridge/pair/{start,complete}` и
  `POST /api/bridge/connections/<id>/revoke` используют `app/workspaces.py`.
  Auth status возвращает `workspaces`, `active_workspace` и
  `active_membership`. Runtime endpoints читают общий `data/runtime/*` только
  для `owner_training`; personal workspace получает isolated empty runtime до
  pairing, после pairing читает `data/tenants/<workspace_id>/runtime` и имеет
  собственный tenant statement ledger. Bridge поддерживает `runtime_data_dir` в
  `NTAnalyzerBridge.config.json`.
- `GET /api/auth/me` собирает «личный кабинет»: профиль (с аватаром), роль,
  подписка, активная область, статус NinjaTrader, эффективные `features` и
  `feature_catalog`. `GET /api/auth/avatar/<id>` отдаёт кэшированный аватар
  (self или owner); `POST /api/auth/avatar/refresh` тянет фото профиля через Bot
  API (`getUserProfilePhotos`) в `data/integrations/avatars/` и в inline
  `avatar_data_url`. `POST /api/auth/users/<id>/features` (owner-only) включает
  или выключает пользователю раздел из каталога возможностей.
- `GET /api/ops/runtime/account-history` использует `app/account_ledger.py`.
  Необъяснённый delta NetLiq записывается только как
  `unclassified_adjustment`; он не становится прибылью или пополнением без
  ручной классификации.
- `POST /api/ops/runtime/account-history/classify` принимает подтверждённый тип
  `deposit|withdrawal|transfer|fee`, actor и основание.
- `POST /api/ops/runtime/account-history/events` создаёт подтверждённое ручное
  движение; `POST .../import` атомарно импортирует до 5000 строк и устраняет
  повторы по `source_id`.
- `GET /api/performance/trades` возвращает единый закрытый trade contract с
  `offset/limit`; `strategy_breakdowns` содержит day/week/month/hour/weekday/
  direction только по атрибутированным стратегиям.
- `GET /api/ai-lab/model-performance` агрегирует model/role request success,
  latency P95, usage tokens и результат связанных экспериментов.
- `GET /api/ai-lab/cloud-agents/status` возвращает безопасный catalog цен,
  назначения ролей, budget/spend и usage без ключей. POST endpoints
  `provider-key|provider-test|provider-disconnect|settings` управляют только
  локальными секретами и controlled fallback; лимиты `$20/month`, `$0.50/run`.
- `GET/POST /api/ai-agents*` использует `app/ai_lab/agent_registry.py`, DPAPI
  `app/secure_store.py` и единый `app/ai_lab/universal_llm.py`. Реестр поддерживает
  chat/embeddings, provider/model/role, тарифы, grant snapshot, budgets и usage;
  HTTP не возвращает plaintext key или prompt content.
- `GET /api/reports` поддерживает сортировку по PF, частоте и статистическому
  доверию, а также фильтры по всем операторским колонкам. Частота едина для UI и
  backend: `<2`, `2–7`, `>7` сделок в неделю. Тяжёлые metric-фильтры имеют
  явный охват `500/2000/all`; точный номер отчёта всегда ищется во всём архиве.
- `GET /api/news` разделяет подтверждённые расписания Fed/BLS/BEA/Census/EIA
  и оценки стандартного графика. Только подтверждённый high-impact может
  включить красный STOP/blackout. `GET /api/news/live` возвращает свежие
  заголовки и статус каждого провайдера; фоновое обновление запускается вместе
  с backend и записывает runtime-файлы атомарно.
- `GET /api/integrations/status`, `/api/topstep/status`, `/api/news`,
  `/api/news/live` и
  `/api/ai-lab/external-agents/status` не возвращают токены/API-ключи и не
  создают демонстрационные события.
- `GET /api/telegram/status` и `POST /api/telegram/{token,pair/*,settings,test,disconnect}`
  используют `app/telegram_service.py`. Фоновый notifier отслеживает heartbeat,
  runtime-стратегии, свежие ошибки, high-impact новости и расписание сводок.
  Свободный текст из единственного paired private chat передаётся Orchestrator;
  исполняются только действия allowlist, strategy enable/disable для paper/demo
  требует отдельного approve, а bounded reconnect paper/demo/playback остаётся
  автономным self-heal действием без live-полномочий.

## Safety

- Runtime-команды остаются paper/demo/playback-only. Backend отклоняет live и
  неизвестные счета; strategy enable/disable требует operator approval, а
  reconnect paper/demo/playback ограничен безопасным infrastructure self-heal.
- Multi-user isolation выполняется до чтения runtime: personal workspace не
  проваливается к owner `data/runtime/*`, а учебный workspace владельца остаётся
  read-only для не-owner пользователей.
- TopStep остаётся execution-disabled. Платные AI-роли могут выполнять только
  два sandbox fallback-сценария после отдельного разрешения и budget gate;
  runtime/account/paper/live действия для них всегда запрещены.
- Универсальный AI agent не получает полномочия из поля role. До явного
  подключения конкретного workflow он доступен только для ручного Connection Test.
- Все изменяющие действия требуют подтверждения в UI и показывают ошибку backend.
- P&L строится по закрытым сделкам после комиссии. NetLiq и движения средств
  отображаются отдельно.
- Старые broker cash transactions отсутствуют в исходной телеметрии. История
  средств начинается с первого сохранённого snapshot; прошлое не дорисовывается.
