# OPERATIONS CONTROL CENTER (Phase 16)

Operational dashboard внутри NT-Analyzer для управления paper-стратегиями.
Не торговая стратегия. Не оптимизатор. Не autotrader.

URL: <http://127.0.0.1:8765/ui/ops.html> (или порт, который выберет сервер)

## ВАЖНО — Hard safety rules
1. **LIVE TRADING ЗАПРЕЩЁН** через UI и API. Все live-эндпоинты возвращают
   `403 blocked until paper-review passed`.
2. По умолчанию все стратегии идут только в **PAPER / DEMO / SIM**.
3. Каждая кнопка `Start/Stop/Pause/Arm` пишет audit-log (`data/ops/audit_log.jsonl`).
4. Bridge не управляет NinjaTrader live-стратегией. UI **создаёт intent** —
   оператор включает стратегию вручную в NinjaTrader, затем нажимает
   `Confirm Started`. То же для остановки.
5. **Trading logic B1 не меняется.** Никаких параметров не оптимизируется.
6. Все метрики adjusted: `pnl_currency − RTC × quantity`, RTC = $1.90 round-turn.
7. Все таймстемпы интерфейса в Pacific Time (PT).
8. Стратегии со статусом `archived/rejected` показываются только в разделе
   Archived. Кнопок запуска у них нет.

## Структура

| Уровень | Что делает |
|---|---|
| `app/ops.py` | Registry, state machine, метрики, audit log, journal |
| `app/server.py` | HTTP routes `/api/ops/*` и `/ui/ops.html` |
| `app/static/ops.html` + `ops.js` | UI Strategy Control Center |
| `data/ops/registry.json` | Persistent registry стратегий |
| `data/ops/state.json` | Текущее состояние state-machine на стратегию |
| `data/ops/audit_log.jsonl` | Append-only журнал действий оператора |
| `data/ops/notes/{id}.md` | Свободные заметки оператора |

## Active strategies

### B1 ShortOnly  (`b1_shortonly`)
- Class: `NTAMicroVwapRiskPilot`
- Mode: **paper / sim only**
- Status by default: **paper_ready**
- Validation job: `ui_20260501T185820607Z` (Phase 15: 92 trades, +$2 738.30 adj, aPF 2.49, DD −$174)
- Locked параметры: см. `PAPER_B1_SHORTONLY_PROFILE.json`
- Журнал: `PAPER_B1_SHORTONLY/PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv`
- Workbook: `PAPER_B1_SHORTONLY/PAPER_B1_SHORTONLY_DAILY_JOURNAL.xlsx`

### Archived / Rejected (не запускать)
- `NTAMicroOrbPilot` — phase 14 reject
- `NTAMicroVwapGapMirrorPilot` — phase 14 reject
- `NTAMicroVwapMeanRevertPilot` — phase 13 reject

## State machine

```
paper_ready ──arm──▶ armed ──start-intent + manual confirm──▶ paper_running
                                                              │
                          ┌─── stop-today ───────────────────┤
                          ├─── pause                         │
                          ├─── risk-blocked (auto)           │
                          └─── paper_review_due (60d & 25t)──┘
                                  │
                                  └── manual mark-passed ──▶ paper_passed
                                                              │
                                                              └─▶ live_locked (dead end)
```

`paper_passed` НЕ открывает live. Live-trading требует отдельного ручного
unlock-токена + код-ревью; UI этого не делает.

## API

Read-only:
- `GET /api/ops/strategies`
- `GET /api/ops/strategies/{id}`
- `GET /api/ops/strategies/{id}/metrics`
- `GET /api/ops/strategies/{id}/trades`
- `GET /api/ops/strategies/{id}/journal`
- `GET /api/ops/strategies/{id}/risk`
- `GET /api/ops/strategies/{id}/notes`
- `GET /api/ops/audit-log[?strategy_id=&limit=]`
- `GET /api/ops/live-lock-status`

Paper workflow (все требуют POST + JSON-body, audit-log запись):
- `POST /api/ops/strategies/{id}/paper/arm`
- `POST /api/ops/strategies/{id}/paper/start-intent`
- `POST /api/ops/strategies/{id}/paper/confirm-manual`  body: `{"action":"started"|"stopped"}`
- `POST /api/ops/strategies/{id}/paper/stop-intent`
- `POST /api/ops/strategies/{id}/paper/pause`
- `POST /api/ops/strategies/{id}/paper/resume`
- `POST /api/ops/strategies/{id}/paper/stop-today`
- `POST /api/ops/strategies/{id}/paper/mark-passed`
- `POST /api/ops/strategies/{id}/paper/evaluate-review`
- `POST /api/ops/strategies/{id}/journal/day`  body: `{"row":{...}}`
- `POST /api/ops/strategies/{id}/notes`        body: `{"text":"..."}`

Live (всегда блокируется):
- `POST /api/ops/live/unlock-request` → `403 blocked`

## Метрики (qty-aware)

- `adj = gross_pnl − 1.90 × quantity`
- `today_adj_pnl`, `weekly_adj_pnl`, `cumulative_adj_pnl`, `high_water_mark`
- `current_drawdown` (от HWM)
- `win_pct`, `adj_pf`, `avg_trade`
- `median_slippage_ticks`, `max_slippage_ticks`
- `active_days`, `consec_losing_days`, `days_since_last_trade`
- `progress.trading_days_completed / 60`
- `progress.trades_completed / 25`
- `review_verdict`: `in_progress | review_due | pass | fail`

## Risk breach detection

| Trigger | Действие |
|---|---|
| `today_adj_pnl ≤ −$200` | `risk_state = risk_blocked` (daily stop) |
| `weekly_adj_pnl ≤ −$400` | `risk_state = risk_blocked` (weekly stop) |
| `current_drawdown ≤ −$300` | `risk_state = risk_blocked` (trailing) |
| 4 подряд убыточных дня | `risk_state = pause`-warning |
| `median_slippage > 1.5 ticks` | `risk_state = warn` |
| `<10 trades` за 90 дней | research-review warning |

UI показывает причину; оператор обязан вручную приостановить стратегию в NT.

## Workflow — как запустить paper

1. Откройте Strategy Control Center: <http://127.0.0.1:8765/ui/ops.html>
2. Карточка `B1 ShortOnly` → нажать `Arm`.
3. Нажать `Start Intent`. UI запишет audit-log и покажет manual-checklist.
4. В NinjaTrader:
   - Откройте Strategy Analyzer / Live Strategies.
   - Выберите `NTAMicroVwapRiskPilot` с параметрами из `PAPER_B1_SHORTONLY_PROFILE.json`.
   - Аккаунт = **PAPER / SIM**, не live.
   - Включите стратегию.
5. Вернуться в UI → `Confirm Started`. Состояние станет `paper_running`.
6. Каждый торговый день в конце сессии:
   - Нажать `Stop Intent`, выключить стратегию вручную в NT, нажать `Confirm Stopped`.
   - Открыть вкладку `Daily Journal` → заполнить строку дня и `Append day`.
7. Через ≥60 торговых дней и ≥25 сделок UI автоматически пометит стратегию
   `paper_review_due`. Сделать ручной review: если pass — нажать `Mark Passed`.
   Live по-прежнему остаётся заблокированным.

## Workflow — остановить paper

- В обычной ситуации: `Stop Intent` → выключить в NT → `Confirm Stopped`.
- На день: `Stop Today` (state → `stopped_today`).
- При нарушении риска: state перейдёт в `risk_blocked` автоматически —
  оператор обязан выключить стратегию в NT и не включать без ручного review.

## Что автоматизировано / что вручную

| Задача | Автоматически | Вручную |
|---|---|---|
| Чтение validation trades | ✅ | — |
| Расчёт adjusted метрик | ✅ | — |
| Risk breach detection | ✅ | — |
| Audit log | ✅ | — |
| Включение стратегии в NT | ❌ | Оператор в NT |
| Выключение стратегии в NT | ❌ | Оператор в NT |
| Подтверждение факта запуска/остановки | UI кнопка | Оператор нажимает |
| Запись paper-сделки в journal | UI form / CSV | Оператор переносит из NT |
| Live trading | **ЗАБЛОКИРОВАНО** | Требует отдельного manual unlock |

## Восстановление после рестарта NinjaTrader

1. Состояние UI не меняется — оно хранится в `data/ops/state.json`.
2. После рестарта NT: оператор должен заново включить стратегию в NT
   (PAPER, тот же шаблон).
3. Если предыдущее состояние было `paper_running` — нажать `Stop Intent`
   → `Confirm Stopped`, затем `Arm` → `Start Intent` → включить в NT →
   `Confirm Started`. Audit log сохранит факт перезапуска.

## Контракт-ролл

1. До экспирации текущего контракта: `Stop Today`.
2. Обновить `instrument` / `contract_month` в `data/ops/registry.json`
   (например, `MES MAR26` → `MES JUN26`). Без этого вкладка Trades будет
   ссылаться на старый job.
3. Запустить новый validation job через NT-Analyzer на новых данных
   (Phase 11/15-style). Прописать новый `validation_job_id` в registry.
4. Только после этого `Arm` → `Start Intent` на новом контракте.

## Экспорт journal для review

- Канонический источник: `PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv`.
- Workbook: `PAPER_B1_SHORTONLY_DAILY_JOURNAL.xlsx` остаётся для ручной работы.
- Из UI: вкладка `Daily Journal` показывает все строки. Скопируйте/выгрузите
  CSV напрямую с диска для review-пакета.

## Что нужно ДО live-review

1. Минимум 60 торговых дней + 25 сделок (`paper_review_due`).
2. Нет risk-breach в последних 20 днях.
3. `adj_pf ≥ 1.50`, `current_drawdown ≥ −$300`, `win_pct` или
   compensating R-multiple — см. таблицу в `ПЛАН_РАЗРАБОТКИ_СТРАТЕГИЙ.md`.
4. Полный audit-log без ручных вмешательств в код стратегии.
5. Манual review-запись + `Mark Passed`.
6. Только после этого делается отдельная безопасная процедура
   live-unlock — она вне scope Phase 16.


---

## Phase 17 — NinjaTrader Runtime Bridge (2026-05-01)

Phase 16 covered the NT-Analyzer registry / state-machine workflow. Phase 17 adds the
**actual NinjaTrader runtime bridge** so the Strategy Control Center reflects what
NinjaTrader is doing right now, not just what was registered.

### File protocol — `NT-Analyzer/data/runtime/`

The NinjaScript AddOn `RuntimeTelemetryExporter` (under `bridge/src/Runtime/`) writes:

| File              | Purpose                                                                 |
| ----------------- | ----------------------------------------------------------------------- |
| `heartbeat.json`  | exporter alive marker, timestamp_utc, ninja_version, exporter_version    |
| `strategies.json` | per-strategy runtime snapshot (account, enabled, state, params, hash)   |
| `positions.json`  | account position snapshot                                                |
| `executions.jsonl`| append-only execution stream from `Account.ExecutionUpdate`              |
| `orders.jsonl`    | append-only order stream from `Account.OrderUpdate`                      |
| `errors.jsonl`    | exporter-side errors                                                     |

The exporter writes atomically (`*.tmp` → rename) every ~5s. The Python backend
treats heartbeat as fresh if `age_sec ≤ 60`. Stale heartbeat → `runtime_detected=false`
and a `STALE_HEARTBEAT` warning is shown — locked-param check is **not** trusted while
heartbeat is stale.

### NinjaTrader-side install

1. In NinjaTrader 8 open NinjaScript Editor → press **F5** to compile the bridge
   project (the new `bridge/src/Runtime/RuntimeTelemetryExporter.cs` is auto-included by
   the SDK-style csproj).
2. Restart NinjaTrader so the AddOn loads.
3. Within ~10s `data/runtime/heartbeat.json` should appear and update.

If the file does not appear, see `data/runtime/errors.jsonl` and
`bridge/logs/bridge-*.log`.

### Backend endpoints (read-only telemetry)

```
GET  /api/ops/runtime/heartbeat
GET  /api/ops/runtime/strategies
GET  /api/ops/runtime/strategies/<built-in function id>
GET  /api/ops/runtime/positions
GET  /api/ops/runtime/executions?strategy_id=&limit=
GET  /api/ops/runtime/orders?strategy_id=&limit=
GET  /api/ops/runtime/errors?limit=
GET  /api/ops/runtime/health
```

State-changing endpoints are limited to **paper / playback** accounts and require
operator confirmation in the UI:

```
POST /api/ops/strategies/<built-in function id>/runtime/confirm-started   (paper-only)
POST /api/ops/strategies/<built-in function id>/runtime/confirm-stopped   (paper-only)
POST /api/ops/strategies/<built-in function id>/journal/autofill          (paper-only)
```

### Param check (B1 ShortOnly locked params)

The backend compares runtime params against the locked dict:

```
EnableLong=false, EnableShort=true,
TradeStartTime=635, TradeEndTime=700,
MinStopTicks=12, MaxStopTicks=12,
RewardRiskRatio=3.5, RiskPerTradePct=2.0,
UserMaxContracts=5, RoundTurnCommission=1.90, SlippageTicks=1
```

Any mismatch → UI shows `PARAM MISMATCH` (red) and **blocks** confirm-started and
paper-state advancement. Also surfaces `params_hash` from the AddOn for spot-checks.

### Reconciliation banners

| Registry state                  | Runtime state          | Banner                                        | Action button             |
| ------------------------------- | ---------------------- | --------------------------------------------- | ------------------------- |
| paper_ready                     | enabled (paper)        | Runtime enabled but not confirmed             | Confirm Runtime Started   |
| paper_running                   | disabled / not present | Runtime stopped outside Control Center        | Confirm Runtime Stopped   |
| any                             | enabled (live)         | LIVE — read-only                              | (none — blocked)          |
| rejected / archived             | enabled                | Locked / archived — blocked                   | (none)                    |

### Daily journal auto-fill

`runtime/confirm-started`/`journal/autofill` aggregate `executions.jsonl` for `date_pt` (PT)
into a single journal row with quantity-aware metrics:

```
adjusted_pnl = gross_pnl - 1.90 * total_qty
```

Plus: `daily_win_count`, `daily_loss_count`, `median_slippage_ticks`,
`max_slippage_ticks`, `stop_hit_count`, `target_hit_count`,
`cumulative_adjusted_pnl`, `current_drawdown`. Manual edits on prior rows are
preserved (we only rewrite today’s row + extend the header with new columns when
needed). The `notes` column is left blank by auto-fill so the operator can edit it
freely.

### Live account behaviour

`account_mode = live` ⇒ read-only. All `runtime/confirm-*` requests refuse with
`live_locked`. UI displays the LIVE chip and a warning banner.

### Tests (`tests/test_runtime.py`)

12 tests cover: missing files, stale heartbeat, OK params, PARAM_MISMATCH, live block,
quantity-aware journal upsert, both reconciliation directions, rejected block, mismatch
blocks confirm, exec filtering, playback as paper-class. Run with:

```
python -m tests.test_ops      # Phase 16 (12 tests)
python -m tests.test_runtime  # Phase 17 (12 tests)
```


---

## Phase 18 — RuntimeCommandProcessor (auto-launch paper/sim)

Дата: 2026-05-01.

### Что добавлено

* Новый C# AddOn: `bridge/src/Runtime/RuntimeCommandProcessor.cs`.
* Polling файла `data/runtime/commands.jsonl` (раз в 1.5 сек).
* Запись в `data/runtime/command_results.jsonl`:
  `command_id`, `status` (accepted/rejected/failed/completed), `message`,
  `timestamp_utc`, `runtime_strategy_id`, `processor_version`.
* Кнопки «▶ Запустить (paper/sim)» и «■ Остановить» в правой панели
  Strategy Control Center теперь реально посылают команды в bridge.

### Жёсткие проверки в bridge

| Проверка                           | Результат              |
| ---------------------------------- | ---------------------- |
| account.Provider/Name == live      | rejected               |
| strategy_class в списке rejected   | rejected               |
| NTAMicroVwapRiskPilot + B1 mismatch| rejected (с детализацией) |
| account не найден                  | failed                 |
| экземпляр стратегии не найден      | failed (просьба добавить вручную) |
| `Strategy.SetState(Active/Terminated)` исключение | failed |

### Что AddOn НЕ делает

* Не размещает ордера.
* Не модифицирует ордера.
* Не создаёт новые экземпляры стратегий — экземпляр должен быть уже добавлен
  в окне «Стратегии» NinjaTrader (один раз).
* Не разблокирует live-аккаунты.

### Шаги после `git pull`

1. Открыть NinjaTrader → NinjaScript Editor → F5 (компиляция bin/Custom).
2. Если компиляция пройдена — перезапустить NinjaTrader (AddOn рестартует).
3. Открыть `/ui/ops.html` — кнопки запуска должны быть включены.
4. Один раз добавить экземпляр стратегии (например `NTAMicroVwapRiskPilot`)
   через «New → Strategy» в NinjaTrader, paper/sim account, MNQ 06-26.
5. После этого панель сможет включать/выключать его одной кнопкой.

### Top alarm strip (UI)

Строка алёртов над таблицей стратегий выдаёт:
* ⛔ красный — отклонённая стратегия запущена в NT.
* ⛔ красный — стратегия запущена на live-аккаунте.
* ⚠ жёлтый — runtime включён, реестр не подтверждает.
* ⚠ жёлтый — реестр считает paper_running, NT выключен.

### Тесты

`python -m tests.test_runtime` теперь содержит 18 кейсов
(t01–t12 Phase 17 + t13–t18 Phase 18 command protocol):
queue paper, hard-reject live, hard-reject rejected, неизвестная команда,
round-trip результата, disable_strategy на playback.
