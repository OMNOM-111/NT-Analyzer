# Контракт данных NT-Analyzer

Это рабочее соглашение между backend, UI и NinjaTrader bridge. Формальная
JSON Schema может быть добавлена позже, но текущие поля ниже уже используются
приложением и сохраненными job/result артефактами.

`schema_version` обязателен с самого начала, чтобы будущие миграции
работали корректно.

---

## job.json

Создаётся backend/CLI по двухшаговому протоколу
(см. ниже раздел **«State machine очереди» → «Создание задания»**):

1. сначала `pending/.staging/<job_id>/job.json` (write-temp-then-rename внутри staging);
2. затем атомарный `Directory.Move` `pending/.staging/<job_id>/` → `pending/<job_id>/`.

Поллер AddOn видит job только после второго шага.

```jsonc
{
  "schema_version": "0.1",
  "job_id": "string, ulid/uuid",
  "created_at_utc": "2026-04-26T12:34:56Z",
  "kind": "historical_backtest",

  "strategy": {
    // ЕДИНСТВЕННЫЙ доверенный селектор стратегии — class_name.
    // Bridge ищет тип в reflected whitelist из NinjaTrader.Custom.dll
    // (только классы, унаследованные от NinjaTrader.NinjaScript.Strategies.Strategy
    //  и физически расположенные в .../bin/Custom/Strategies/...).
    "class_name": "SampleMACrossOver",

    // Подсказка для логов и сверки. НЕ используется для загрузки кода.
    // Если путь не совпадает с реально найденным через reflection — bridge
    // добавляет verification_warning, но использует именно reflected путь.
    "source_file_hint": "C:\\Path\\To\\NinjaTrader 8\\bin\\Custom\\Strategies\\@SampleMACrossOver.cs",

    "parameters": {
      // имя параметра -> значение, как ожидает NinjaScriptProperty
      // можно оставить пустым => дефолты из стратегии
    }
  },

  "instrument": "MES 06-26",
  "timeframe": {
    "bars_period_type": "Minute",
    "value": 1
  },

  "period": {
    "from_utc": "2026-03-12T00:00:00Z",
    "to_utc":   "2026-04-24T00:00:00Z"
  },

  "risk_profile": {
    // Информационный профиль счёта. Он сохраняется в job/result,
    // но не ограничивает NinjaTrader-прогон, пока стратегия явно не
    // поддерживает общий RiskManager.
    "schema_version": "0.1",
    "mode": "informational",
    "currency": "USD",
    "starting_capital": 2000.0,
    "intraday_only": true,
    "margin_source": {
      "broker": "NinjaTrader",
      "source": "auto_refresh",
      "fetched_at_utc": "2026-04-30T01:53:16Z"
    },
    "instrument_margins": {
      "MES 06-26": {
        "root": "MES",
        "margin_type": "intraday",
        "margin_per_contract": 50.0,
        "max_contracts_by_capital": 40,
        "status": "allowed"
      }
    },
    "status": "informational_only",
    "status_text": "Профиль сохранится в запуске; стратегия пока не ограничивается."
  },

  "execution": {
    "calculate": "OnBarClose",          // OnBarClose | OnPriceChange | OnEachTick
    "is_tick_replay": false,
    "order_fill_resolution": "Standard",
    "slippage_ticks": 0,
    "commission": 0.0,
    "session_template": "CME US Index Futures RTH",
    "timezone": "UTC"
  }
}
```

### Жёсткие требования

- Все timestamps в UTC, ISO-8601 с суффиксом `Z`.
- Поля `strategy.class_name` и `instrument` — обязательны.
- `parameters` может быть пустым объектом — тогда AddOn использует значения по умолчанию.
- `source_file_hint` — **не доверенный** ввод. Bridge никогда не загружает код по этому пути,
  не компилирует его и не передаёт его в reflection. Реальный класс выбирается только
  из reflected whitelist `NinjaTrader.Custom.dll`.
- `risk_profile` является информационным контекстом счёта. Он обязан
  сохраняться в истории запуска, но не должен менять NinjaTrader-compatible
  backtest без явной поддержки RiskManager внутри стратегии.

---

## result.json

Создаётся AddOn. Точный протокол записи и финализации — см. раздел
**«State machine очереди»** ниже.

```jsonc
{
  "schema_version": "0.1",
  "job_id": "...",                     // совпадает с job.json
  "run_hash": "sha256:...",            // hash канонического контекста запуска
  "started_at_utc":  "2026-04-26T12:34:57Z",
  "finished_at_utc": "2026-04-26T12:35:42Z",
  "duration_ms": 45123,

  "source": {
    "execution_source": "ninjatrader",
    "ninjatrader_version": "8.x.x.x",
    "addon_version": "0.1.0",
    "rd_variant_used": "1_strategy_analyzer | 2_manual_bars_request",
    "ninjatrader_custom_dll_sha256": "..."
  },

  "context": {
    // САМОДОСТАТОЧНОСТЬ: всё, что нужно, чтобы понять прогон без job.json.
    "strategy": {
      "class_name": "SampleMACrossOver",
      "resolved_source_file": "C:\\Path\\To\\NinjaTrader 8\\bin\\Custom\\Strategies\\@SampleMACrossOver.cs",
      "source_file_sha256": "sha256:...",
      "source_file_mtime_utc": "2026-04-20T10:00:00Z",
      "ninjatrader_custom_dll_sha256": "sha256:...",
      "final_parameters": {
        // полный набор параметров после применения дефолтов
        "Fast": 10,
        "Slow": 25
      }
    },
    "instrument": "MES 06-26",
    "timeframe": { "bars_period_type": "Minute", "value": 1 },
    "period": { "from_utc": "...", "to_utc": "..." },
    "risk_profile": { /* эхо risk_profile из job.json */ },
    "execution": { /* эхо execution из job.json */ },

    // Отпечаток исторических данных, использованных в прогоне.
    // Если NT перекачает/обновит history, тот же run_hash может дать другой
    // результат — поэтому фиксируем fingerprint отдельно.
    // Если fingerprint недоступен, используется заглушка с явным verification_warning.
    "historical_data_fingerprint": {
      "method": "sha256_of_concatenated_db_files | placeholder",
      "value": "sha256:...",
      "files": [
        // относительные пути файлов NT db, которые реально читались
      ]
    }
  },

  "metrics": {
    "trade_count": 0,
    "winning_pct": 0.0,
    "gross_profit": 0.0,
    "gross_loss": 0.0,
    "net_profit": 0.0,
    "profit_factor": 0.0,
    "max_drawdown": 0.0
  },

  "trades": [
    {
      "trade_no": 1,
      "direction": "long",            // long | short
      "entry_time_utc": "...",
      "entry_price": 0.0,
      "exit_time_utc": "...",
      "exit_price": 0.0,
      "quantity": 1,
      "pnl_currency": 0.0,
      "pnl_ticks": 0
    }
  ],

  "artifacts": {
    // относительные пути от jobs/done/<job_id>/
    "trades_file": "trades.json",
    "equity_curve_file": null,
    "drawdown_curve_file": null,
    "logs_file": "ninjascript.log",
    "raw_bridge_result_file": "raw.json"
  },

  "verification_warnings": [
    // строки описаний рисков несовпадения с NinjaTrader,
    // например "session_template not provided, used default"
    // или "rd_variant_used=2_manual_bars_request: order/fill semantics may differ from Strategy Analyzer"
  ]
}
```

### Жёсткие требования

- `job_id` в result.json **обязан** совпадать с job.json.
- `context.strategy` обязан содержать `class_name`, `resolved_source_file`,
  `source_file_sha256`, `ninjatrader_custom_dll_sha256` и `final_parameters` —
  result.json должен быть полностью самодостаточным для истории/AI/повторного открытия.
- `run_hash` считается по каноническому job context.
  **Контракт 0.2 (Stage 2 runtime/backtest mismatch repair):** `historical_data_fingerprint`
  ТЕПЕРЬ входит в `run_hash` вместе с `execution` (session_template, timezone,
  order_fill_resolution, slippage_ticks, commission). Поэтому два прогона по
  разной NT history / session / fill-модели больше не сталкиваются на одном
  `run_hash`. Если `historical_data_fingerprint` остаётся `placeholder`, bridge
  добавляет запись в `verification_warnings`: прогон не воспроизводимо сравним.
  При изменении этого правила нужно явно поднять/описать версию контракта
  (`RunHashCalculator.ContractVersion`).
- Все timestamps в UTC.
- Если bridge не смог посчитать какое-то поле metrics — ставит `null`,
  а не выдумывает значение, и добавляет запись в `verification_warnings`.

---

## Strategy Profiles family metadata

`data/profiles/strategies.json` keeps locked strategy/profile cards. Family
metadata is overlaid from `data/profiles/strategy_families.json` when profiles
are exposed through `/api/profiles`, `/api/coverage`, and runtime registry
matching. The same family map also contains root-level stubs for Micros roots
that have no profile or Research Hub yet.

Current profile family fields:

```jsonc
{
  "root_family": "MNQ",
  "strategy_family": "mnq_session_edge",
  "family_status": "research_hub | active | active_locked | legacy_ready_frozen | legacy_rejected_frozen | research_only_standalone | archived | root_stub_no_hub",
  "family_role": "research_hub | deploy_wrapper | locked_profile | legacy_wrapper | standalone_research_engine | root_family",
  "hub_class": "NTAMnqResearchHub",
  "new_research_allowed": true
}
```

Rules:

- `root_family` groups instrument-level portfolio cells (`MNQ`, `MGC`, ...).
- `strategy_family` tracks lineage; it must not be used to collapse different
  deploy profiles into one portfolio cell.
- `hub_class` is the research source class. A deploy wrapper must still use
  `deploy_strategy_class` and locked parameters after promotion gates.
- `new_research_allowed=false` means the family can be maintained or audited,
  but should not receive new hypotheses without a separate re-approval.

`data/profiles/research_modes.json` keeps the Research Hub Mode registry and is
exposed through `/api/research-modes`. Mode status is independent from profile
status: a Mode can be `stub`, `active`, `research_only`, `promoted`,
`rejected`, or `archived`.

---

## State machine очереди (точный протокол)

Это единственный источник истины по перемещениям файлов.
И `bridge/README.md`, и любой backend/CLI обязаны следовать ему буквально.

### Структура одного job на диске

Каждый job — это **папка** `<job_id>/` (не одиночный файл), которая
последовательно живёт в одной из родительских папок: `pending/ → running/ → done/|failed/|cancelled/`.

Внутри папки могут лежать:
- `job.json` — исходное задание;
- `heartbeat.json` — обновляется bridge во время `running`;
- `cancel.flag` — создаётся backend/CLI для запроса отмены;
- `result.json` — финальный успешный результат;
- `error.json` — финальная ошибка;
- `trades.json`, `ninjascript.log`, `raw.json`, `*.tmp` — артефакты.

### Создание задания (backend/CLI)

1. Подготовить содержимое `job.json` в памяти.
2. Создать **во временном месте** `pending/.staging/<job_id>/`
   (одна и та же файловая система, чтобы `Move` был атомарным).
3. Записать `job.json` через write-temp-then-rename внутри staging:
   `job.json.tmp` → `Move` → `job.json`.
4. **Атомарно** переместить всю папку: `pending/.staging/<job_id>/` →
   `pending/<job_id>/` через `Directory.Move`.

Поллер AddOn никогда не читает `pending/.staging/`.

### Claim задания (AddOn)

1. Поллер сканирует `pending/<*>/` (только директории, у которых внутри есть `job.json`).
2. Для попытки claim AddOn выполняет атомарный `Directory.Move`
   `pending/<job_id>/` → `running/<job_id>/`.
3. Если `Move` упал из-за того, что папки уже нет — задание забрал кто-то другой,
   ничего не делаем.
4. Успешный `Move` = эксклюзивный owner. Это и есть защита от двух AddOn /
   двух процессов: тот, кому удался `Move`, и есть единственный исполнитель.

Дополнительно AddOn пишет в `running/<job_id>/heartbeat.json` свой PID и
имя процесса. Если другой процесс видит свежий heartbeat от чужого PID —
он не трогает этот job.

### Запись result/error/heartbeat внутри running

- `heartbeat.json`: каждые ~5 сек, write-temp-then-rename
  (`heartbeat.json.tmp` → `Move` → `heartbeat.json`) **внутри той же папки**.
- Артефакты (`trades.json`, `ninjascript.log`, `raw.json`):
  пишутся как `*.tmp` и атомарно переименовываются.
- `result.json` пишется **последним**, тоже через `result.json.tmp` → `Move` → `result.json`.

### Финализация: success

1. Все артефакты и `result.json` уже лежат в `running/<job_id>/`.
2. AddOn выполняет атомарный `Directory.Move`
   `running/<job_id>/` → `done/<job_id>/`.
3. Появление папки `done/<job_id>/` = сигнал backend, что прогон завершён.

### Финализация: failure

1. AddOn пишет `error.json` через write-temp-then-rename внутри `running/<job_id>/`.
2. Атомарный `Directory.Move` `running/<job_id>/` → `failed/<job_id>/`.

### Финализация: cancel

1. Backend/CLI создаёт пустой файл `running/<job_id>/cancel.flag`
   (write-temp-then-rename: `cancel.flag.tmp` → `Move` → `cancel.flag`).
2. AddOn периодически (раз в heartbeat-цикл) проверяет наличие файла,
   корректно завершает прогон, пишет частичный `result.json`
   с `verification_warnings: ["cancelled by user"]`.
3. Атомарный `Directory.Move` `running/<job_id>/` → `cancelled/<job_id>/`.
4. Никогда не используется kill процесса NinjaTrader.

### Восстановление зависших jobs

При старте AddOn сканирует `running/`:
- если в папке есть `heartbeat.json` с чужим живым PID — не трогает;
- иначе считает job зависшим, пишет `error.json`
  (`error_type: "stale_running_recovered"`) и переносит в `failed/`.

Backend дополнительно может пометить running job как failed, если
`heartbeat.updated_at_utc` старше TTL (по умолчанию 60 сек).

---

## error.json

Создаётся AddOn при сбое и кладётся в `jobs/failed/<job_id>/error.json`.

```jsonc
{
  "schema_version": "0.1",
  "job_id": "...",
  "failed_at_utc": "...",
  "stage": "load_strategy | resolve_instrument | run_backtest | export",
  "error_type": "string",
  "message": "string",
  "stack_trace": "string|null",
  "ninjascript_log_excerpt": "string|null"
}
```

---

## heartbeat.json

Пишется AddOn в `jobs/running/<job_id>/heartbeat.json` каждые N секунд
(рекомендуется 5 секунд, TTL 60 секунд):

```jsonc
{
  "schema_version": "0.1",
  "job_id": "...",
  "updated_at_utc": "...",
  "pid": 12345,
  "process_name": "NinjaTrader.exe",
  "stage": "loading_bars | running | exporting",
  "progress_pct": 0
}
```

---

## cancel.flag

Создаётся backend/CLI как пустой файл `jobs/running/<job_id>/cancel.flag`.
AddOn периодически проверяет наличие файла и корректно завершает прогон,
после чего перемещает папку job в `jobs/cancelled/<job_id>/`.
