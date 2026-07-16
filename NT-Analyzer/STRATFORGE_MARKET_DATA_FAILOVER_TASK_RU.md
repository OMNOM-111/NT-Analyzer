# STRATFORGE — независимые рыночные данные и failover

Дата реализации и проверки: 16 июля 2026 (America/Los_Angeles)  
Ветка: `codex/stratforge-release-20260716`  
Основные коммиты: `62f8c926`, `40101aa8`  
Статус кода: **реализовано и проверено**  
Статус production release в целом: **BLOCKED внешней/ручной матрицей, см. release audit**

## 1. Фактическая цепочка до исправления

До этой работы durable chart queue не создавала независимого источника. Она только переносила выполнение того же запроса за пределы HTTP handler.

Фактическая цепочка была:

1. браузер регистрирует `market_data_requests.json`;
2. NinjaTrader Bridge должен записать `market_bars.json`;
3. если Bridge не дал бары, backend читает последний Strategy Analyzer artifact;
4. при остановке NinjaTrader актуальный график исчезает.

Дополнительно Practice передавал в Bridge голый root `MNQ`. Реальный Bridge ответил `NinjaTrader instrument not found: MNQ`, потому что ему нужен текущий контракт.

## 2. Реализованная цепочка

```text
UI / API bars request
  -> root-to-current-contract resolver
  -> NinjaTrader runtime (primary)
  -> freshness + OHLC validation + gap detection
  -> independent provider chain
       1. Databento HTTP (если есть API key)
       2. Yahoo Chart best-effort (chart-only public fallback)
  -> timestamp merge (primary wins collisions)
  -> only real secondary bars fill gaps / append newer bars
  -> Strategy Analyzer artifact (последний offline fallback)
  -> unified bars + source/freshness/quote/gap_recovery metadata
```

Ключевое правило: **ни одна синтетическая OHLCV-свеча не создаётся**. Secondary заполняет только timestamp, который действительно присутствует в ответе независимого provider. При совпадении timestamp свеча NinjaTrader всегда имеет приоритет.

## 3. Providers

### Databento

- adapter: `DatabentoProvider`;
- dataset по умолчанию: `GLBX.MDP3`;
- continuous futures symbology: `[ROOT].v.0`;
- HTTP endpoint: `timeseries.get_range`;
- OHLCV: `ohlcv-1m`, `ohlcv-1h`, `ohlcv-1d`;
- 3m/5m/15m/30m/4h агрегируются локально из официальной меньшей гранулярности;
- credential: `NTA_DATABENTO_API_KEY` или `DATABENTO_API_KEY`;
- в текущем окружении credential отсутствует, поэтому adapter корректно сообщает `configured=false` и не блокирует следующий provider.

### Yahoo Chart

- adapter: `YahooChartProvider`;
- включён как независимый best-effort chart fallback без credential;
- mapping включает MNQ/MES/MGC и основные futures roots;
- source всегда явно помечен `tier=best_effort_public`;
- текущий CME futures ответ задержан примерно на 10 минут и поэтому честно получает `external_stale`;
- source не является authority для live-order, а рассчитанные вокруг last bid/ask помечены `bid_ask_estimated=true`.

Отключение public fallback: `NTA_MARKET_DATA_PUBLIC_FALLBACK=0`.  
Порядок providers: `NTA_MARKET_DATA_PROVIDERS=databento,yahoo`.

## 4. Автоматическое переключение и recovery

- provider abstraction отделена от NinjaTrader;
- circuit breaker: после трёх ошибок provider получает cooldown 60 секунд;
- следующий provider выбирается автоматически;
- кэш ограничивает внешние HTTP-запросы;
- freshness содержит `fresh`, `stale`, `age_sec`, `max_age_sec`, `data_as_of_utc`;
- gap diagnostics содержит интервалы до и после recovery;
- session-like большие перерывы не считаются автоматически восстанавливаемой внутрисессионной дырой;
- provider health/status сохраняется в runtime-файл `market_data_failover_status.json`;
- read-only API: `GET /api/ops/runtime/bars/status`;
- bars payload содержит `source`, `freshness`, `quote`, `gap_recovery`, `requested_instrument`, `resolved_instrument`.

## 5. Practice Trading

Исправлено:

- до создания счёта остаётся только virtual-deposit onboarding;
- после создания доступны instrument, 1m/5m/15m/1h, layout 1/2/4, chart, market/limit, отдельные Buy/Sell, qty, SL/TP;
- показаны bid/ask/last, provider, timestamp, stale/error/empty/loading/recovery;
- есть явный retry;
- balance/equity/day PnL/unrealized/virtual buying power/position capacity;
- позиции закрываются адресно, рабочие ордера отменяются адресно;
- reset действительно удаляет выбранный workspace practice account;
- UI не передаёт цену исполнения как доверенную: server получает trusted close через NinjaTrader или независимый failover;
- Practice по-прежнему не пишет ни в live, ни в Micro Live, ни в NT command queues.

## 6. Micro Live и TopStep

- Micro Live production UI больше не изображает готовый реальный продукт: без проверенных payment/broker adapters он `coming_soon`, `available=false`, `real_money=false`;
- staging остаётся simulator без внешних денег/orders;
- существующие production backend gates требуют verified provider/broker result и явные owner flags;
- TopStep помечен `safe_scaffold`, `available=false`, `live_actions_enabled=false`;
- прямые browser live-команды отсутствуют.

## 7. Реальная production-проверка с остановкой NinjaTrader

Перед остановкой проверено: активных стратегий 0, открытых позиций 0 по Backtest/Playback101/Sim101/DEMO3369390/1267509.

NinjaTrader PID 29124 был остановлен; backend остался доступен.

При `NinjaTrader=false`:

- `GET /api/ops/runtime/bars/status` -> HTTP 200, `reported_nt_running=false`;
- MNQ 1m -> HTTP 200, 180 bars;
- source -> `yahoo_chart`, `independent=true`;
- recovery -> `mode=independent_failover`, `primary_healthy=false`;
- headless chart snapshot -> HTTP 200, `image/png`, валидная PNG signature, 20 482 bytes.

После повторного запуска NinjaTrader:

- heartbeat восстановился: NinjaTrader 8.1.7.2, Bridge 1.3.0;
- request `MNQ` разрешился в `MNQ 09-26`;
- первый запрос обслужил independent fallback, не оставив график пустым;
- через 6 секунд Bridge опубликовал 120 bars;
- второй запрос: `status=live`, `source=ninjatrader_runtime`, `age_sec=0.056`, gaps 0.

Это подтверждает автоматический failover в обе стороны, а не только durable queue.

## 8. Автотесты и release gates

- `tests/test_market_data_failover.py`: independent NT-off chain, ordered provider failover, gap fill, collision priority, no invented bars;
- `tests/test_market_data.py`: corrupt snapshot recovery и root error-row exclusion;
- Practice/Micro/TopStep DOM/API contracts;
- полный pytest и остальные release gates перечислены в `docs/STRATFORGE_RELEASE_AUDIT_2026-07-15.md`.

## 9. Что остаётся внешним BLOCKER

1. Для credentialed low-latency production feed нужен Databento API key/entitlement или другой одобренный официальный CME adapter.
2. Yahoo fallback задержан и предназначен только для непрерывности графика/research, не для live execution.
3. Нужен ручной visual/mobile/role E2E в пользовательском Chrome; встроенный Codex browser исключён, потому что его инициализация уже вызвала restart Codex Desktop.
4. Нужен ручной NinjaTrader Strategy Analyzer comparison.
5. Payment/broker sandbox adapters и отдельное письменное разрешение нужны до любых Micro Live money/order tests.

Эти пункты не отменяют завершённость failover-кода, но не позволяют объявить весь production release принятым.
