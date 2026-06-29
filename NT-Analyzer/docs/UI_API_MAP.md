# Aurora UI API map

Актуально на 2026-06-28 после финального parity-аудита. Единственный HTTP-адаптер интерфейса находится в
`app/static/aurora/assets/api.js`. Production не загружает mock-данные.

## Страницы

| Страница | Источники данных | Изменяющие действия |
|---|---|---|
| Обзор | `/api/health`, `/api/performance`, `/api/coverage`, `/api/ai-lab/summary`, `/api/reports`, `/api/news`, accounts/account-history | системные действия вынесены в общее меню |
| Бэктест | catalog, instruments, profiles, coverage, reports, jobs, trades, bars, draw objects, favorites, batches | создать job/batch, отменить/удалить job, favorite/unfavorite; серверные фильтры/сортировка не изменяют данные |
| Торговля | accounts, account-history, strategies, positions, orders, executions, errors, commands/results/status, runtime history, strategy history/display, start dates, performance, diagnostics, strategy journal | paper-only enable/disable, ручное движение, CSV-импорт, классификация движения, восстановление скрытого класса |
| Доход | performance, performance/trades, accounts, account-history, CSV | фильтры, пагинация, drilldown и выгрузка; финансовые данные не изменяются |
| Стратегии | profiles/archive, AI lifecycle/cell history, coverage, instruments, persistent portfolio registry | статус/удаление профиля, add root/cell, archive cell, hide runtime class, NinjaTrader cleanup |
| AI Lab | summary, experiments/activity, run/current status, performance board, model-performance, external-agent status, calendar, compile source, errors, LM Studio | run/cancel, bootstrap/unload, operator note, stale sweep, user-research scan; внешние агенты read-only и execution-disabled |
| Новости | `/api/news` | read-only; пустое состояние без вымышленных событий, пока источники не настроены |
| TopStep | `/api/topstep/status` | read-only scaffold; live-действия принудительно отключены до отдельной валидации |
| Документы | governance documents, runtime defaults, history | save с actor/reason и подтверждением |

## Новые постоянные контракты

- `GET/POST /api/portfolio/*` использует `app/portfolio_registry.py`. ID ячейки
  неизменяем, архивный ID не переиспользуется. Базовая схема `CELL-001..180`
  сохранена, включая `MNQ slot 11 = CELL-126`.
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
- `GET /api/reports` поддерживает сортировку по PF, частоте и статистическому
  доверию, а также фильтры по всем операторским колонкам. Частота едина для UI и
  backend: `<2`, `2–7`, `>7` сделок в неделю. Тяжёлые metric-фильтры имеют
  явный охват `500/2000/all`; точный номер отчёта всегда ищется во всём архиве.
- `GET /api/integrations/status`, `/api/topstep/status`, `/api/news` и
  `/api/ai-lab/external-agents/status` не возвращают токены/API-ключи и не
  создают демонстрационные события.

## Safety

- Runtime-команды остаются paper/demo/playback-only. Backend отклоняет live и
  неизвестные счета.
- TopStep и внешние платные агенты остаются execution-disabled независимо от
  наличия ключей, пока не появятся отдельные risk/security gates.
- Все изменяющие действия требуют подтверждения в UI и показывают ошибку backend.
- P&L строится по закрытым сделкам после комиссии. NetLiq и движения средств
  отображаются отдельно.
- Старые broker cash transactions отсутствуют в исходной телеметрии. История
  средств начинается с первого сохранённого snapshot; прошлое не дорисовывается.
