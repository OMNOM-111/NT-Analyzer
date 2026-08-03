# Manual Validation vs NinjaTrader Strategy Analyzer

Документ для **ручной сверки** одного эталонного прогона нашего bridge
(`StrategyBase.RunBacktest()` через AddOn) против результата встроенного
**Strategy Analyzer UI** в NinjaTrader 8.

Цель: убедиться, что метрики и сделки в `result.json` / `trades.json`
совпадают (в пределах допусков) с тем, что показывает Strategy Analyzer
на тех же входных параметрах.

Текущий статус baseline: **PASSED**. Пользователь вручную сверил bridge
с NinjaTrader Strategy Analyzer и подтвердил совпадение. Повторять эту
процедуру нужно после изменений в `StrategyAnalyzerRunner`, применении
commission/trading-hours/execution settings или контракте результата.

---

## 1. Эталонный сценарий (reference run)

Эти параметры строго фиксируем — и в bridge, и в UI выставляем вручную
один-в-один.

| Параметр                | Значение                              |
|-------------------------|---------------------------------------|
| Strategy                | `SampleMACrossOver`                   |
| Instrument              | `MES 06-26`                           |
| Bars period type        | `Minute`                              |
| Bars period value       | `1`                                   |
| Period from (UTC)       | `2026-03-12T00:00:00Z`                |
| Period to (UTC)         | `2026-04-24T00:00:00Z`                |
| Strategy param `Fast`   | `10`                                  |
| Strategy param `Slow`   | `25`                                  |
| Calculate               | `OnBarClose`                          |
| Tick Replay             | `false` (выключен)                    |
| Order Fill Resolution   | `Standard`                            |
| Slippage (ticks)        | `0`                                   |
| Commission              | `0` (без комиссии)                    |
| Trading Hours           | `CME US Index Futures RTH`            |
| Account / Mode          | `Backtest`                            |

> ВАЖНО: если в нашем `job.json` какой-то из этих параметров
> отличается (commission, slippage, trading hours), сверка
> **бессмысленна** — приводим bridge к этому профилю и пересоздаём job.

---

## 2. Шаги ручной проверки

### 2.1. Прогон через нашу платформу

1. Открыть NinjaTrader 8 вручную, дождаться Control Center.
2. Запустить `00_START_NT_ANALYZER.cmd`.
3. В UI tab **Run** выставить параметры из таблицы выше → Submit.
4. Дождаться `status=done` в tab **Jobs**.
5. Зафиксировать:
   - `job_id`,
   - `result.run_hash` (если есть),
   - содержимое `metrics`,
   - первые 5 и последние 5 строк `trades.json`.

### 2.2. Прогон в Strategy Analyzer UI

1. NinjaTrader → **New → Strategy Analyzer**.
2. Strategy: `SampleMACrossOver`.
3. Instrument: `MES 06-26`.
4. Bars: `Minute / 1`.
5. Date range: с `2026-03-12 00:00` до `2026-04-24 00:00`
   (часовой пояс — как настроено в NT; учесть offset от UTC).
6. Parameters: `Fast=10`, `Slow=25`.
7. Properties:
   - `Calculate = OnBarClose`,
   - `Tick Replay = false`,
   - `Order Fill Resolution = Standard`,
   - `Slippage = 0`,
   - `Commission = 0`,
   - `Trading Hours = CME US Index Futures RTH`,
   - Account: Backtest.
8. **Run Backtest**.
9. Открыть вкладки `Performance` и `Trades`, выписать значения.

### 2.3. Сверка

Сравнить попарно поля из таблицы ниже. Любое расхождение,
выходящее за `tolerance`, — это **FAILED**, нужно записать причину.

---

## 3. Поля для сверки

### 3.1. Метрики (Performance)

| Поле                | Источник bridge          | Источник UI (Performance)        | Tolerance            |
|---------------------|--------------------------|----------------------------------|----------------------|
| Total trades        | `metrics.trade_count`    | `Total # of Trades`              | **0** (точно равно)  |
| Gross Profit        | `metrics.gross_profit`   | `Gross Profit`                   | ±0.01                |
| Gross Loss          | `metrics.gross_loss`     | `Gross Loss`                     | ±0.01                |
| Net Profit          | `metrics.net_profit`     | `Net Profit` (Cumulated)         | ±0.01                |
| Profit Factor       | `metrics.profit_factor`  | `Profit Factor`                  | ±0.0005              |
| Max Drawdown        | `metrics.max_drawdown`   | `Max. Drawdown` (Currency)       | ±0.01                |
| Winning %           | `metrics.winning_pct`    | `Percent Profitable`             | ±0.05 (п.п.)         |

> Заметка: NT может показывать Max Drawdown как положительное число
> (величина просадки) или отрицательное (изменение equity). В нашем
> `result.json` принято хранить **отрицательное** значение
> (`-8938.75` и т.п.). Сравнивать по абсолютной величине.

### 3.2. Сделки (первые 5 и последние 5)

Из `trades.json` берём `[0..4]` и `[-5..-1]`. Из UI вкладка `Trades`
сортирована по времени входа — берём первые 5 и последние 5 строк.

Для каждой сделки сверяем:

| Поле                   | bridge (`trades.json`)         | UI Trades column      | Tolerance     |
|------------------------|--------------------------------|-----------------------|---------------|
| Entry time             | `entry_time_utc`               | `Entry time`          | ±1 bar        |
| Exit time              | `exit_time_utc`                | `Exit time`           | ±1 bar        |
| Direction (Long/Short) | `direction` (`long`/`short`)   | `Market position`     | строго равно  |
| Quantity               | `quantity`                     | `Quantity`            | строго равно  |
| Entry price            | `entry_price`                  | `Entry price`         | ±1 tick       |
| Exit price             | `exit_price`                   | `Exit price`          | ±1 tick       |
| PnL (currency)         | `pnl_currency`                 | `Profit` (Currency)   | ±0.01         |

> Если расходятся **только времена** (UI vs UTC) — проверь, что
> NT показывает в локальной TZ, а наш bridge — в UTC; это не баг,
> а сдвиг отображения.

---

## 4. Запись результата сверки

Каждый прогон-сверка фиксируется одной записью ниже.
Не удалять старые записи — они нужны как история валидаций.

### Run record template

```
- Date (UTC):        YYYY-MM-DDThh:mm:ssZ
- NinjaTrader build: 8.x.x.x          (Help → About)
- Bridge DLL build:  YYYY-MM-DD hh:mm (Get-Item .../NTAnalyzerBridge.dll | Last write)
- job_id:            ui_YYYYMMDDThhmmssZ
- run_hash:          <result.run_hash | "n/a">
- Status:            NOT_RUN | PASSED | FAILED
- Operator:          <кто прогонял>
- Discrepancies:     <список полей, где не сошлось, или "none">
- Notes:             <любые комментарии: TZ, изменённые параметры, и т.п.>
```

### Statuses

- **NOT_RUN** — сверка ещё не выполнялась.
- **PASSED** — все поля из §3 в пределах tolerance, первые/последние
  5 сделок совпали по направлению/количеству и в пределах tolerance
  по цене и PnL.
- **FAILED** — есть хотя бы одно расхождение вне tolerance.
  Обязательно заполнить `Discrepancies` и `Notes`.

---

## 5. Журнал сверок

### Run #1 — reference (SampleMACrossOver / MES 06-26 / 1m / 2026-03-12..2026-04-24)

- Date (UTC):        2026-04-29
- NinjaTrader build: 8.1.6.3
- Bridge DLL build:  2026-04-27 (post-period_mismatch fix)
- job_id:            `ui_20260428T010532382Z`
- run_hash:          `sha256:c208a44b262bb2d56f48a91c18c45cf300334fe94b9c0764fad050dc3ab54fd8`
- Status:            **PASSED**
- Operator:          dimon
- Discrepancies:     none (manual Strategy Analyzer cross-check confirmed)
- Bridge metrics (для сверки в UI):
    - trade_count   = 2021
    - gross_profit  = 24286.25
    - gross_loss    = -26132.5
    - net_profit    = -1846.25
    - profit_factor = 0.9294
    - max_drawdown  = -3070.00
    - winning_pct   = 34.8342
    - first entry   = 2026-03-11T22:56:00Z
    - last entry    = 2026-04-24T20:37:00Z
- Notes:             первая ручная сверка после фикса P1
                     (period_mismatch). До фикса bridge молча игнорировал
                     `From/To` из-за `BarsToLoad=200000` override и грузил
                     ~7 месяцев лишних данных (9232 trades, 7154 раньше
                     `from_utc`). Теперь `From/To` авторитетны, добавлен
                     post-run period invariant (±1 day tolerance).
                     Baseline принят как валидированный для дальнейшей
                     разработки стратегий.
