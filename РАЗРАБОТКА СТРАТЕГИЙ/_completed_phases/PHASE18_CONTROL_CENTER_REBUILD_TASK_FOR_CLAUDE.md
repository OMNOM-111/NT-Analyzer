# Phase 18 Task for Claude — полный rebuild Strategy Control Center + исправление запуска

Дата: 2026-05-01 PT.

## Контекст

Сейчас paper-кандидат только один:

- `NTAMicroVwapRiskPilot` в режиме **B1 ShortOnly**
- `MNQ 06-26`, `Minute/1`, paper/demo only
- locked params:
  - `EnableLong=false`
  - `EnableShort=true`
  - `TradeStartTime=635`
  - `TradeEndTime=700`
  - `MinStopTicks=12`
  - `MaxStopTicks=12`
  - `RewardRiskRatio=3.5`
  - `RiskPerTradePct=2.0`
  - `UserMaxContracts=5`
  - `RoundTurnCommission=1.90`
  - `SlippageTicks=1`
- baseline job: `ui_20260501T185820607Z`
- qty-aware baseline: 92 trades / Adj +2738.30 / aPF 2.49 / DD -174 / 8/8 positive quarters.

Rejected/archived:

- `NTAMicroOrbPilot`
- `NTAMicroVwapGapMirrorPilot`
- `NTAMicroVwapMeanRevertPilot`
- B1 Long / B1 LongShort / ORB / MR

Live trading stays forbidden until paper review passes.

## Что сейчас сломано / неприемлемо

1. **UI вводит в заблуждение.**
   В `Strategy Control Center` кнопка “Запустить” ставила команду в `data/runtime/commands.jsonl`, но C# bridge её не исполнял. Это выглядело как запуск, хотя NinjaTrader ничего не включал.

2. **C# runtime exporter сейчас read-only.**
   `bridge/src/Runtime/RuntimeTelemetryExporter.cs` прямо говорит:
   `SAFETY: read-only. No order placement. No strategy enable/disable.`
   Поэтому endpoint `/api/ops/runtime/command` сейчас должен считаться незавершённым протоколом, а не рабочим запуском.

3. **Панель неудобна.**
   Нужна не карточная страница, а рабочая панель как основной NT-Analyzer:
   верхняя таблица/список стратегий, справа параметры выбранной стратегии, снизу подробные данные и вкладки.

4. **Непонятно, что именно запускается.**
   Запуск должен явно показывать:
   - strategy class
   - account
   - account mode (`paper`, `playback`, `live_locked`)
   - instrument / contract month
   - timeframe / bars period
   - quantity
   - locked params / runtime params diff
   - risk profile
   - expected state after launch

5. **Runtime показывает, что сейчас включён rejected `NTAMicroOrbPilot`.**
   Это надо подсвечивать как аварийное состояние:
   `Rejected strategy running — disable immediately`.
   B1 ShortOnly при этом `runtime_detected=false`.

6. **Главная backtest-панель должна быть проверена.**
   Backend `/api/jobs` работает: smoke job `ui_20260501T230301170Z` создан и завершился `done`.
   Но пользователь видит, что нажатие кнопки “запуск” иногда просто перезагружает страницу / ничего не делает. Нужно проверить frontend, события формы, ошибки консоли и сделать regression test.

## Маленькие hotfixes уже сделаны

- `app/static/ops.js`: `onLaunchClick()` / `onStopClick()` теперь сразу показывают предупреждение, что авто-запуск отключён, потому что bridge read-only.
- `app/static/ops.html`: текст кнопок заменён на “Проверить запуск вручную” / “Проверить остановку вручную”, добавлено предупреждение.
- `bridge/src/Util/AtomicFile.cs`: добавлен fallback для `File.Replace` IOException, чтобы telemetry не падала при transient Windows file lock.

Эти hotfixes НЕ являются финальным решением.

## Цель Phase 18

Сделать **полностью рабочую русскоязычную Operations-панель**, через которую удобно:

1. Видеть все стратегии из NinjaTrader и из нашего registry.
2. Сразу понимать, какая стратегия реально запущена в NinjaTrader.
3. Видеть account / instrument / timeframe / params / PnL / orders / executions.
4. Запускать только paper/playback стратегии безопасно и понятно.
5. Блокировать live.
6. Не показывать fake controls: если команда не поддержана bridge, кнопка должна быть disabled и явно объяснять почему.
7. Проверять main backtest panel, чтобы исторический запуск из UI не перезагружал страницу и реально создавал job.

## Обязательная архитектура UI

Новая страница: `app/static/ops.html` + `app/static/ops.js`.

Макет:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Header: Strategy Control Center | NT runtime status | LIVE LOCKED | Refresh │
├──────────────────────────────────────────────────────────────────────────────┤
│ TOP TABLE: strategies                                                         │
│ columns: status | class | registry status | runtime | account | instrument   │
│          timeframe | params | today pnl | risk | action required             │
├─────────────────────────────────────────────┬────────────────────────────────┤
│ BOTTOM DETAIL TABS                          │ RIGHT PARAMS / LAUNCH PANEL    │
│ Overview | Runtime | Executions | Orders    │ selected strategy              │
│ Position | Journal | Backtests | Audit      │ account/instrument/timeframe   │
│                                             │ locked params diff             │
│                                             │ manual launch checklist        │
└─────────────────────────────────────────────┴────────────────────────────────┘
```

Все visible labels — на русском языке, без mojibake.

## Верхняя таблица стратегий

Должны быть строки:

- `B1 ShortOnly` (`NTAMicroVwapRiskPilot`) — active paper candidate
- rejected strategies из registry
- любые стратегии, которые runtime видит в NinjaTrader, даже если их нет в registry

Для каждой строки:

- `registry_status`: `paper_ready`, `paper_running`, `rejected`, `unknown`
- `runtime_enabled`: yes/no
- `runtime_state`: `Realtime`, `Historical`, disabled, missing
- `account_name`
- `account_mode`: `paper`, `playback`, `live`, `unknown`
- `instrument`
- `bars_period` / timeframe if available
- `params_ok`: ok / mismatch / not checked
- red alert if `rejected && runtime_enabled`
- red alert if `live && runtime_enabled`
- yellow alert if `runtime_enabled && registry not confirmed`
- yellow alert if `registry paper_running && runtime disabled`

## Правая панель параметров

Для выбранной стратегии:

- Strategy class
- account selector
- instrument selector/input
- contract month
- timeframe selector (`Minute/1` default for B1)
- quantity
- locked params table
- runtime params diff
- risk profile summary
- validation baseline summary

Для B1 ShortOnly должна быть кнопка:

- `Скопировать locked-параметры`
- `Проверить runtime-параметры`
- `Открыть paper journal`

Если bridge не умеет автозапуск:

- `Запустить из панели` disabled
- рядом текст: `Недоступно: C# bridge read-only. Включите вручную в NinjaTrader.`

Если решаешь реализовывать автозапуск:

- см. раздел “Command protocol” ниже.

## Command protocol — если реализуешь настоящий запуск

Это большая часть. Делать только если можешь закончить end-to-end.

### Backend

`POST /api/ops/runtime/command` должен создавать command с:

- `command_id`
- `command`: `enable_strategy` / `disable_strategy`
- `strategy_id`
- `strategy_class`
- `account_name`
- `instrument`
- `bars_period_type`
- `bars_period_value`
- `quantity`
- `params`
- `created_at_utc`
- `expires_at_utc`
- `operator`
- `paper_only=true`

`GET /api/ops/runtime/command-results` должен показывать результат.

### C# bridge

В NinjaTrader AddOn нужен отдельный `RuntimeCommandProcessor`, не смешивать с telemetry exporter.

Он должен:

1. Читать `data/runtime/commands.jsonl`.
2. Игнорировать уже обработанные `command_id`.
3. Reject if account is live.
4. Reject if strategy is rejected/archived.
5. Reject if params mismatch B1 locked params.
6. Create/enable strategy only on paper/playback account.
7. Write `command_results.jsonl` with:
   - `command_id`
   - `status`: `accepted`, `rejected`, `failed`, `completed`
   - `message`
   - `timestamp_utc`
   - `runtime_strategy_id`
8. Never place orders directly. Only enable/disable NinjaScript strategy instance.

Если NinjaTrader API не позволяет safely enable strategy from AddOn, then do NOT fake it. Keep button disabled and document manual flow.

## Backtest panel regression

Проверить основной экран `/ui/index.html`:

1. `node --check app/static/app.js` must pass.
2. Browser/Playwright smoke:
   - open `/ui/index.html`
   - select `NTAMicroVwapRiskPilot`
   - set `MNQ 06-26`
   - period 2025-01-02..2025-01-03
   - High fill, slip=1, RTC=1.90
   - click run
   - page must NOT reload
   - `/api/jobs` POST must be called
   - job appears in Jobs table
3. API smoke already passes:
   - job `ui_20260501T230301170Z` completed `done`.

Add a frontend regression test if possible. If no browser automation is available, add a small JS-level event-binding check and document limitation.

## Runtime correctness tests

Add/keep tests for:

- fresh heartbeat
- stale heartbeat
- strategy running
- rejected strategy running
- live account running
- B1 params OK
- B1 params mismatch
- B1 runtime disabled while registry says running
- B1 runtime enabled while registry says ready
- journal autofill quantity-aware
- command disabled when bridge read-only
- command result flow if command processor implemented

## Current runtime bug to surface clearly

Right now runtime sees:

- `NTAMicroOrbPilot`
- account `DEMO3369390`
- instrument `MES JUN26`
- `enabled=true`
- `state=Realtime`
- `StartingCapital=0`
- `MaxContractsByCapital=0`

This must show as a red alarm:

`Отклонённая стратегия запущена в NinjaTrader. Остановите NTAMicroOrbPilot. После F5 compile она должна исчезнуть из списка.`

## Archive / compile requirement

Rejected source has been moved out of:

`Documents\NinjaTrader 8\bin\Custom`

to:

`Documents\NinjaTrader 8\_NTAnalyzer_ARCHIVE_REJECTED_20260501`

Also `NinjaTrader.Custom.csproj` was cleaned from `Strategies_ARCHIVE_REJECTED_20260501\...` Compile includes.

User still must:

1. Disable any running `NTAMicroOrbPilot`.
2. NinjaScript Editor → F5 compile.
3. Restart NinjaTrader if old compiled strategy still appears.

The UI should display this as a guided checklist, not as hidden documentation.

## Acceptance criteria

Phase 18 is done only when:

1. `/ui/ops.html` is fully readable in Russian and visually coherent.
2. Top strategy table correctly shows current runtime status from NinjaTrader.
3. Running rejected strategy is impossible to miss.
4. B1 ShortOnly manual launch flow is clear and unambiguous.
5. Fake launch buttons are gone, or real bridge command execution works end-to-end.
6. Live account controls are blocked.
7. Main `/ui/index.html` backtest Run button is verified and does not reload the page.
8. API smoke for historical job still passes.
9. Tests pass:
   - `python -m tests.test_ops`
   - `python -m tests.test_runtime`
   - new Phase 18 tests
10. Documentation updated:
    - `OPERATIONS_CONTROL_CENTER.md`
    - `PAPER_B1_SHORTONLY_RUNBOOK.md`
    - `ПЛАН_РАЗРАБОТКИ_СТРАТЕГИЙ.md`

## Non-negotiable

- Do not change B1 ShortOnly trading logic.
- Do not change locked B1 params.
- Do not enable live trading.
- Do not reintroduce rejected strategies.
- Do not pretend a command was executed unless NinjaTrader confirms it via runtime/command result.
