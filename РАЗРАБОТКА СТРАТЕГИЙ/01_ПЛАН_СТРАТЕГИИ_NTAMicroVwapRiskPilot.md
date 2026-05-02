# План первой стратегии: NTAMicroVwapRiskPilot

> Финальная версия. Базируется на `ПЛАН_РАЗРАБОТКИ_СТРАТЕГИЙ.md` и
> учитывает критерии приёмки оттуда. Любое расхождение между этим
> файлом и базовым планом разрешается в пользу базового плана.

**Имя стратегии:** `NTAMicroVwapRiskPilot`
**Класс NinjaScript:** `NTAMicroVwapRiskPilot : Strategy`
**Назначение:** первая базовая intraday-стратегия для маленького счёта
**1000 / 2000 / 3000 USD**, использующая Risk Profile из NT-Analyzer,
тестируемая циклом `код → /api/jobs → анализ result.json → доработка`.

> Стратегия не обещает доход. Цель — устойчивое положительное
> математическое ожидание после комиссий, slippage и ограничений капитала.

---

## 1. Главная идея

Три режима, включаемых параметрами (по умолчанию активен только №1):

1. **VWAP/EMA Trend Pullback** — основной режим первой версии.
2. **Opening Range Breakout (ORB)** — добавляется после прохождения §15 на режиме 1.
3. **Mean Reversion к VWAP** — только в "тихие" дни (низкий ATR/ADX),
   включается после успешного теста режимов 1 и 2.

## 2. Базовые инструменты

| Приоритет | Символ | Intraday margin | Когда включать |
|---|---|---:|---|
| 1 | **MES** | $50 | Старт, основной |
| 2 | **MYM** | $50 | После прохождения MES |
| 3 | **M2K** | $50 | После прохождения MES |
| 4 | **MNQ** | $100 | Только если капитал ≥ 2000 и MES прошёл OOS |
| 5 | **MCL / MGC** | $100 / $200 | Только после §15 на 3 micro-equity |

Стратегия **не выбирает** инструмент сама — он передаётся из NT-Analyzer
job'а. Стратегия проверяет, разрешён ли он по Risk Profile.

## 3. Контракт «Стратегия ↔ NT-Analyzer»

### 3.1. Реальная схема `risk_profile` в job (как сейчас работает)

```jsonc
"risk_profile": {
  "schema_version": "...",
  "currency": "USD",
  "starting_capital": 2000,
  "intraday_only": true,
  "margin_source": { "broker": "...", "...": "..." },
  "instrument_margins": {
    "MES 06-26": {
      "root": "MES",
      "margin_type": "intraday",            // или "initial"
      "margin_per_contract": 50,            // одно число под выбранный режим
      "max_contracts_by_capital": 40,
      "status": "allowed"                   // allowed | blocked | unknown
    },
    "...": { "..." : "..." }
  },
  "status": "informational_only",
  "status_text": "..."
}
```

Поле `margin_per_contract` уже **скаляр под активный режим** (зависит
от `intraday_only`), отдельных `intraday/overnight` под-полей **нет**.
`max_contracts_by_capital` лежит **внутри** записи инструмента, а не
на верхнем уровне.

### 3.2. Текущее поведение bridge (ограничение MVP)

`bridge\src\Execution\StrategyAnalyzerRunner.cs` →
`ApplyStrategyParameters()` применяет к стратегии **только**
`job.strategy.parameters`. Объект `job.risk_profile` сейчас идёт мимо
стратегии — он сохраняется в `result.context`, но в свойства
`NinjaScriptProperty` **не транслируется**.

Поэтому **прямо сейчас** стратегия не может «само-получить» Risk Profile.
Нужен один из двух путей:

- **Путь A (временный, без правок backend):** UI / клиент при сборке
  job'а **дублирует** значения Risk Profile в `strategy.parameters`
  (см. §3.3). Это работает уже сегодня.
- **Путь B (правильный, требует Phase 0):** в backend / bridge
  добавляется маппер `risk_profile → strategy.parameters` для
  whitelisted-имён (`StartingCapital`, `IntradayOnly`,
  `ActiveMarginPerContract`, `MaxContractsByCapital`,
  `InstrumentStatus`). После Phase 0 UI больше ничего не дублирует.

Обе версии стратегии **одинаковы** — разница только в том, кто
заполняет parameters.

### 3.3. Маппинг Risk Profile → параметры стратегии

| Параметр стратегии (`NinjaScriptProperty`) | Источник в `risk_profile` |
|---|---|
| `StartingCapital` | `risk_profile.starting_capital` |
| `IntradayOnly` | `risk_profile.intraday_only` |
| `ActiveMarginPerContract` | `risk_profile.instrument_margins[<symbol>].margin_per_contract` |
| `MaxContractsByCapital` | `risk_profile.instrument_margins[<symbol>].max_contracts_by_capital` |
| `InstrumentStatus` | `risk_profile.instrument_margins[<symbol>].status` |
| `MarginSourceBroker` | `risk_profile.margin_source.broker` (опц., только для лога) |

`<symbol>` = инструмент текущего job'а (`job.instrument`).

### 3.4. Phase 0 — обязательный этап до написания торговой логики

Перед `NTAMicroVwapRiskPilot.cs` нужно сделать минимум один из вариантов:

1. **Путь A (быстрый):** в UI (`app.js`, функция, собирающая job
   payload перед `POST /api/jobs`) добавить копирование 5 полей из
   §3.3 в `strategy.parameters`. Зафиксировать в коде комментарий
   «temporary — until backend mapper lands».
2. **Путь B (правильный):** в `bridge` (или в backend перед отправкой
   в bridge) реализовать функцию `mapRiskProfileToParameters(job)`,
   которая дописывает в `strategy.parameters` те же 5 полей
   **только если** их там ещё нет (явный override от пользователя
   имеет приоритет). Имена — whitelist; всё остальное игнорируется.

**Acceptance для Phase 0:** запускается smoke-job на dummy-стратегии,
которая просто `Print()`-ит все 5 полей. В `result.json` (или в логе
NinjaScript) видно корректные значения, совпадающие с тем, что выбрано
в панели Account / Risk Profile.

### 3.5. Поведение стратегии при отсутствии данных

- `InstrumentStatus ∈ {blocked, unknown}` → стратегия **не открывает
  ни одной сделки**, пишет причину в `Print()` (логи попадут в
  диагностические артефакты NinjaScript / output bridge'а; в
  `result.json` гарантированно попадает только агрегированная
  диагностика — не каждая строка `Print`).
- `ActiveMarginPerContract ≤ 0` или `MaxContractsByCapital < 1` →
  то же поведение: торговля заблокирована, причина — в логах.
- `StartingCapital ≤ 0` → стратегия немедленно вызывает `SetState
  (State.Finalized)`-семантику (через флаг `StopTrading=true`).

## 4. RiskManager (внутренний модуль стратегии)

Считает каждый бар:

```text
CurrentEquity        = StartingCapital + RealizedPnL + UnrealizedPnL
DailyPnL             = sum(realized PnL за текущую сессию)
DailyStopUSD         = StartingCapital * MaxDailyLossPct
MaxContractsByMargin = floor(CurrentEquity / ActiveMargin)
MaxContractsByRisk   = floor((CurrentEquity * RiskPerTradePct) / ContractRisk)
FinalQuantity        = min(MaxContractsByMargin, MaxContractsByRisk, UserMaxContracts)
```

где `ActiveMargin = ActiveMarginPerContract` (приходит из
`risk_profile.instrument_margins[<symbol>].margin_per_contract`,
этот скаляр уже выбран под текущий режим `intraday_only` —
см. §3.1).

**Полная остановка торговли (`StopTrading=true`) при:**
- `CurrentEquity ≤ 0` (израсходован весь стартовый капитал) — навсегда;
- `|DailyPnL| ≥ DailyStopUSD` — до конца сессии;
- `ConsecutiveLosses ≥ MaxConsecutiveLosses` — до конца сессии;
- `TradesToday ≥ MaxTradesPerDay` — до конца сессии;
- `FinalQuantity < 1` — пропуск конкретного входа.

## 5. Размер позиции

```text
risk_budget    = CurrentEquity * RiskPerTradePct
contract_risk  = StopTicks * TickValue
                 + RoundTurnCommission
                 + SlippageTicks * TickValue
quantity       = floor(risk_budget / contract_risk)
final_quantity = min(quantity, MaxContractsByCapital, UserMaxContracts)
```

Если `final_quantity < 1` — вход запрещён.

**Стартовые `RiskPerTradePct`:**

| Капитал | Консерв. | Рост |
|---:|---:|---:|
| 1000 USD | 0.75% (≈$7.5) | 1.0% (≈$10) |
| 2000 USD | 0.75% (≈$15)  | 1.0% (≈$20) |
| 3000 USD | 1.0%  (≈$30)  | 1.5% (≈$45) |

Режим «Рост» включается **только** после ≥ 60 прибыльных live-сделок.

## 6. Intraday-режим

При `IntradayOnly = true`:

```text
NoEntryMinutesBeforeClose   = 30
ForceFlatMinutesBeforeClose = 15      # совпадает с моментом, когда NT повышает intraday margin
AvoidNewsMinutesBefore      = 15
AvoidNewsMinutesAfter       = 5
AllowOvernight              = false
```

`ForceFlatMinutesBeforeClose = 15` обязательно — это окно, когда
NinjaTrader повышает intraday-маржу до overnight-уровня.

## 7. Торговые окна (Pacific Time / California)

Все пользовательские параметры времени и все отчёты ведутся в **Pacific Time
(`America/Los_Angeles`)**, потому что NinjaTrader на этом PC использует
`Time[0]` в локальном времени California. ET можно писать только как пояснение
в скобках. UTC допускается только как техническое поле `job.json/API`.

```text
Primary window:    06:35 – 08:30 PT  (= 09:35 – 11:30 ET)
Secondary window:  10:30 – 12:00 PT  (= 13:30 – 15:00 ET)
Force flat:        12:45 PT          (= 15:45 ET)
```

Любой новый отчёт должен показывать время сначала в PT. Формат типа
`09:35-10:00 ET` без PT-эквивалента считается неполным.

## 8. Индикаторы

**v1 (обязательные):** Session VWAP · EMA(20) · EMA(50) · ATR(14) · ADX(14) · Volume SMA(20).

**v2 (после прохождения v1):** RSI(2), Bollinger(20, 2), Opening Range
High/Low (первые 15 мин сессии), Cumulative Delta (если доступно).

## 9. Сетап «VWAP/EMA Pullback»

**Long:**
1. `Close > VWAP` и `EMA20 > EMA50`;
2. `ADX(14) ≥ MinAdx` (старт 18);
3. `Volume[0] ≥ VolumeSMA(20) * MinVolumeFactor` (старт 0.8);
4. был откат: цена касалась `VWAP` или `EMA20` за последние `PullbackLookback` баров (старт 5);
5. сигнальный бар закрылся выше своей середины и выше `EMA20`;
6. вход: **stop-buy** на `High[0] + 1 tick`, отмена через `EntryTimeoutBars` (старт 3).

**Short:** зеркально.

## 10. Stop / Target / Trailing

```text
StopTicks       = clamp(round(ATR_ticks * AtrStopMult), MinStopTicks, MaxStopTicks)
TargetTicks     = round(StopTicks * RewardRiskRatio)

AtrStopMult         = 0.6
MinStopTicks        = 6
MaxStopTicks        = 24
RewardRiskRatio     = 1.5     # базово; для Asymmetric R/R режима — 2.5–3.0
MoveToBreakevenAtR  = 0.8
TrailAfterR         = 1.2
TrailDistanceTicks  = round(StopTicks * 0.5)
```

Если рассчитанный `StopTicks` даёт `contract_risk` > `risk_budget` —
**сделка пропускается** (логируем причину).

## 11. Дневные лимиты

```text
MaxDailyLossPct      = 2.0    # → DailyStopUSD = StartingCapital * 0.02
MaxDailyProfitPct    = 4.0    # опц. фиксация дня
MaxConsecutiveLosses = 3
MaxTradesPerDay      = 6
MaxOpenPositions     = 1
```

Достижение лимита → закрыть позицию (если есть) → запретить входы до
следующей сессии → `Print()` причину.

## 12. Параметры (полный список `NinjaScriptProperty`)

**Risk Profile (заполняется из job; см. §3.3):** `StartingCapital`, `IntradayOnly`,
`ActiveMarginPerContract`, `MaxContractsByCapital`, `InstrumentStatus`,
`MarginSourceBroker` (опционально, для лога).

**Risk:** `RiskPerTradePct`, `MaxDailyLossPct`, `MaxDailyProfitPct`,
`MaxConsecutiveLosses`, `MaxTradesPerDay`, `MaxOpenPositions`,
`UserMaxContracts`, `RoundTurnCommission`, `SlippageTicks`.

**Setup toggles:** `EnableVwapPullback`, `EnableOpeningRangeBreakout`,
`EnableMeanReversion`.

**Indicators:** `EmaFastPeriod`, `EmaSlowPeriod`, `AtrPeriod`,
`AdxPeriod`, `MinAdx`, `VolumeSmaPeriod`, `MinVolumeFactor`,
`PullbackLookback`, `EntryTimeoutBars`.

**Stops:** `AtrStopMult`, `MinStopTicks`, `MaxStopTicks`,
`RewardRiskRatio`, `MoveToBreakevenAtR`, `TrailAfterR`,
`TrailDistanceTicks`.

**Time:** `TradeStartTime`, `TradeEndTime`, `SecondTradeStartTime`,
`SecondTradeEndTime`, `AvoidFirstMinutesAfterOpen`,
`NoEntryMinutesBeforeClose`, `ForceFlatMinutesBeforeClose`,
`AvoidNewsMinutesBefore`, `AvoidNewsMinutesAfter`,
`NewsBlackoutTimes` (CSV ручных окон).

## 13. Технические требования к коду

1. Класс `NTAMicroVwapRiskPilot : Strategy` в
   `Documents\NinjaTrader 8\bin\Custom\Strategies\NTAMicroVwapRiskPilot.cs`.
2. Все параметры через `[NinjaScriptProperty]` с `[Display]`-группами:
   `01-Risk Profile`, `02-Risk`, `03-Setup`, `04-Indicators`, `05-Stops`, `06-Time`.
3. Внутренний `RiskManager` — приватный nested-класс, без статики.
4. Indicators: `VWAP` (встроенный или OrderFlowVWAP), `EMA`, `ATR`,
   `ADX`, `SMA(Volume)`.
5. Управление ордерами: `EnterLongStopMarket / EnterShortStopMarket`,
   `ExitLongStopMarket / ExitLongLimit`, `SetStopLoss(CalculationMode.Ticks, …)`,
   `SetProfitTarget`. Trail — ручной через `OnBarUpdate`.
6. `OnStateChange`: `State.SetDefaults` — все дефолты; `State.Configure` —
   валидация параметров; `State.DataLoaded` — инициализация RiskManager.
7. **Логирование** причин: `[ENTRY]`, `[SKIP:reason]`, `[EXIT:reason]`,
   `[RISK:stop_trading]` через `Print()`. Эти строки попадают в
   диагностические артефакты NinjaScript / output bridge'а. В
   `result.json` гарантированно попадает агрегированная диагностика
   (`diag[]`, `final_parameters`, метрики), но не каждая строка
   `Print()` — это нужно для постмортем-анализа, а не как договорной API.
8. Стратегия видна в NT-Analyzer (`/api/strategies`) и принимает все
   параметры из job-payload.

## 14. Цикл разработки через NT-Analyzer

1. AI пишет/правит `NTAMicroVwapRiskPilot.cs`.
2. Компиляция в NinjaTrader (F5).
3. Если стратегия новая, переименована, изменились `[NinjaScriptProperty]`
   параметры или стратегия не видна в NT-Analyzer, нужно полностью
   перезапустить NinjaTrader, дождаться старта AddOn/bridge и обновить
   каталог NT-Analyzer (`POST /api/catalog/refresh`). Ожидаемый признак:
   `/api/strategies` содержит `NTAMicroVwapRiskPilot`, а
   `data/catalog/strategies.json` содержит `"class_name":
   "NTAMicroVwapRiskPilot"`. Без этого `/api/jobs` запускать нельзя:
   bridge может держать старую `NinjaTrader.Custom.dll` в памяти.
4. AI вызывает `POST http://127.0.0.1:8765/api/jobs` с payload
   (Content-Type: application/json):
   ```jsonc
   {
     "class_name":        "NTAMicroVwapRiskPilot",
     "instrument":        "MES 06-26",
     "bars_period_type":  "Minute",
     "bars_period_value": 5,
     "from_utc":          "2024-01-01T00:00:00Z",
     "to_utc":            "2025-12-31T00:00:00Z",
     "calculate":         "OnBarClose",
     "is_tick_replay":    false,
     "risk_profile": {
       "starting_capital": 2000,
       "intraday_only":    true
     },
     "parameters": {
       "RiskPerTradePct":          1.0,
       "RoundTurnCommission":      1.90,
       "SlippageTicks":            1
     }
   }
   ```
   > **Phase 0 mapper готов** (`app/jobqueue.py::_inject_risk_profile_parameters`).
   > Backend сам подставит в `strategy.parameters` поля `StartingCapital`,
   > `IntradayOnly`, `ActiveMarginPerContract`, `MaxContractsByCapital`,
   > `InstrumentStatus`, `MarginSourceBroker` из активного Risk Profile
   > по инструменту. Дублировать их в `parameters` вручную не нужно —
   > если они там явно заданы, mapper их не перезатрёт (whitelist + no-overwrite).
   >
   > Для прогона сразу на нескольких инструментах использовать
   > `POST /api/batches` с полем `"instruments": ["MES 06-26", "MYM 06-26"]`
   > (все остальные поля идентичны).
5. AI читает `jobs/<job_id>/result.json`: `winning_pct`, `net_profit`,
   `profit_factor`, `max_drawdown`, `trade_count`, `trades.json`.
6. Если метрики не проходят §15 — анализ худших сделок и кластеров
   просадок, правка **одной группы** правил за раз, повтор с шага 2.
7. Прогон на разных периодах + разных инструментах (MES → MYM → M2K).
8. Финальная ручная сверка в NinjaTrader Strategy Analyzer (validated baseline).

**Таймфреймы для тестирования:** базовый **5m**, контрольный **3m**.
1m запрещён как primary (шум, переторговка), допускается только как
секондари-серия для уточнения входов.

## 15. Критерии готовности

Стратегия принимается, если выполнен хотя бы **один** сценарий ниже
**на выборке ≥ 100 сделок** и **на out-of-sample периоде** (последние
30% данных или walk-forward с 3+ окнами):

| Сценарий | Win-rate | Profit Factor | Net Profit | Max DD |
|---|---|---|---|---|
| Минимум | > 50% | ≥ 1.30 | > 0 | < 25% капитала |
| Хорошо  | > 75% | ≥ 1.70 | положит. | < 20% |
| Идеал   | ≥ 90% | ≥ 2.50 | положит. | < 15% |
| **Asymmetric R/R** | может быть < 30% | ≥ 2.0 | > +100% от стартового капитала | < 30% |

**Дополнительные обязательные условия:**
- Для intraday-стратегии одного модуля недостаточно быть прибыльным, если он
  торгует слишком редко: минимум **≥ 100 сделок за тест 2024-2025** и
  минимальная частота **не реже 1 сделки на 2 торговых дня** по портфелю.
  Практическая цель для готовой intraday-системы — **1-2 сделки в торговый
  день** без переторговки. Модуль с меньшей частотой остаётся
  **research baseline**, но не принимается как финальная стратегия.
- Для `stop-entry` логики с выходами внутри той же свечи обязателен
  **fill-realism audit**: same-bar %, доля same-bar выигрышей, где внутри
  бара были достигнуты и stop, и target, и повторный тест с более детальным
  исполнением (`High Order Fill Resolution` / 1-tick, Tick Replay или минимум
  1-minute bars). Конфигурация с большим числом ambiguous same-bar wins не
  принимается по 5-minute Standard backtest.
- `AverageWinningTrade ≥ 2 × RoundTurnCommission`;
- `RoundTurnCommission ≥ 1.90` для micro futures, если `commission_template=None`.
  В таком режиме решения принимаются только по `Adj Net`, `Adj Profit Factor`,
  `Adj Max Drawdown` после custom commission adjustment. `commission_template=None`
  без `RoundTurnCommission` не принимается.
- нет одиночной сделки с убытком `> 2 × DailyStopUSD`;
- результат **не зависит** от 1 сделки или 1 дня (удаление топ-1
  сделки сохраняет `NetProfit > 0`);
- OOS-период даёт `PF ≥ 0.7 × PF(IS)` (нет переоптимизации);
- стратегия **ни разу** не нарушила Risk Profile (margin / intraday).

## 16. Что НЕ принимается

- Игнор Risk Profile или хардкод капитала/контрактов.
- Открытие overnight при `IntradayOnly = true`.
- Использование маржи > доступной хотя бы в одной сделке.
- Прибыль только на одном инструменте или одном периоде.
- Одиночный backtest вместо группового сравнения Full / IS / OOS и нескольких
  инструментов, если гипотеза касается рынка/портфеля.
- Отчёт, где торговое окно указано не в Pacific Time или комиссия показана как
  `None` без adjusted metrics.
- `PF < 1.30` без компенсации сценарием Asymmetric R/R.
- Equity curve, где > 60% прибыли даёт одна сделка/день.

## 17. Первая практическая цель (MVP стратегии)

> **Pre-requisite:** Phase 0 из §3.4 (Путь A или B) выполнен и
> подтверждён smoke-job'ом. Без этого `NTAMicroVwapRiskPilot.cs`
> не запускается — стратегия получит нулевой капитал и заблокируется
> на старте.

```text
Strategy:   NTAMicroVwapRiskPilot v0.1
Instrument: MES 06-26
Timeframe:  5m  (контроль: 3m)
Period:     2024-01-01 .. 2025-12-31  (IS 70% / OOS 30%)
Capital:    тестируется отдельно при 1000, 2000, 3000 USD
Mode:       intraday_only = true
Setup:      EnableVwapPullback = true, остальные = false
Goal:       пройти "Минимум" из §15 на всех трёх уровнях капитала
```

Если v0.1 не проходит — **не добавлять новые индикаторы**. Сначала
проверить по порядку:
1. Ширину стопа (ATR mult);
2. Торговое окно;
3. `MinAdx` и `MinVolumeFactor` (фильтр тренда/активности);
4. `MaxTradesPerDay` (переторговка);
5. `RoundTurnCommission` (комиссии съедают edge?);
6. Сменить инструмент: MES → MYM → M2K.

Только после исчерпания этих 6 пунктов — включать ORB или Mean Reversion.
