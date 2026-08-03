# AI Strategy Lab — quality pipeline

Дата проверки: 2026-06-29.

## Рабочая архитектура

1. Qwen выбирает один разрешённый `reference_id`, семейство, режим рынка,
   trigger, экономику выхода и параметры.
2. WEX и отклонённые AI-CELL используются как отрицательные уроки, а не как
   шаблоны для копирования.
3. NinjaTrader C# строится deterministic family renderer:
   фиксированный risk/session shell плюс семейная signal-логика.
4. Модель не может менять namespace, NT8 lifecycle, комиссию, slippage,
   quantity и окно `06:30–12:30 PT`.
5. GPT-OSS оставлен для compile-fix/review только при реальной ошибке
   компилятора.

Причина: реальные бенчмарки полного C# показали нестабильные ответы и timeout
300–480 секунд. Генерация hypothesis/spec стабильна, а NT8 boilerplate должен
быть детерминированным.

## Quality gates

- Reference shortlist исключает `do_not_use`, неподходящий инструмент и
  запрещённые generic-паттерны.
- Static validator запрещает `AddDataSeries`, `OnExecutionUpdate`, неверные
  NT8 API, production CELL-id и вход до stop/target.
- Signal sanity выбирает estimator по фактическому семейству.
- Overtrading и 0-trade отсекаются до NinjaTrader backtest.
- 14–45-дневный smoke отсекает 0 trades, overtrading и устойчивый
  `PF after commission < 0.65` при достаточном числе сделок.
- Full backtest запускается только после smoke.
- Arbitration сначала применяет hard gates, затем score:
  `reject`, `mutate` или `candidate`.
- При compile failure broken AI source автоматически переносится в
  `ai_lab/quarantine/compile_failed/<experiment>/`.

## Проверенная конфигурация LM Studio

- API: `127.0.0.1:1234`
- context: `8192`
- parallel: `1`
- retries: `0`
- local fallback for idea/spec/code/review: `openai/gpt-oss-20b`
- compile fixer/reviewer: `openai/gpt-oss-20b`

Перед запуском readiness обязан проверить `judge`, `coder` и
`compile_error_fixer` через реальный `chat/completions`.

## Controlled cloud fallback

AI Lab остаётся local-first. После некорректного локального hypothesis-контракта
может быть вызван `hypothesis_fallback`; после трёх повторных compile-fail
циклов — `compile_error_fixer_fallback`. Оба пути по умолчанию выключены,
требуют отдельного API-ключа и разрешения, ограничены `$20/месяц` и
`$0.50/run`. Cloud output снова проходит все deterministic gates и не имеет
права на verdict. Полный контракт: `docs/agents/AI_LAB_CLOUD_AGENTS.md`.

## Competitive feedback для AI-ролей

Управление ролями строится через проверяемую конкуренцию, а не через угрозы.
Analyst, Coder, Judge и Reviewer могут сравниваться внутри одного cycle по
фактическому результату: contract validity, compile, backtest, risk gates,
arbitration и честность `unclear/reject/no_signal`. Слабый ответ получает
feedback и временно меньший приоритет следующего вызова, но честный отказ при
недостатке данных не считается браком. Полный контракт и MVP внедрения:
`docs/agents/AI_LAB_COMPETITIVE_FEEDBACK.md`.

## Реальные E2E результаты

- `EXP-20260622-0006`: полный цикл до full backtest; compile/catalog/sanity
  прошли, стратегия честно отклонена как `NO_EDGE`.
- `EXP-20260622-0007`: две итерации одного AI-CELL; разные SHA, обе версии
  скомпилированы; первая остановлена smoke как `SMOKE_NO_EDGE`, вторая —
  signal sanity.
- `EXP-20260622-0008`: подтверждены фиксированное PT-окно,
  model-provided `volume_multiplier` в C# и smoke reject.
- `EXP-20260622-0009`: подтверждён EMA-slope regime filter; сделок стало
  меньше, но after-commission edge не появился.

Технический pipeline готов к исследовательскому использованию. На этой серии
прогонов прибыльный candidate не найден, поэтому ни одна стратегия не должна
автоматически переходить в portfolio/demo. Это корректный результат quality
gate, а не ошибка инфраструктуры.

## Рекомендуемый запуск

Начинать с:

- 1–2 стратегии;
- 2–3 итерации на стратегию;
- `stop_on_first_candidate=false`;
- `allow_template_fallback=false`;
- smoke 14–30 дней;
- один root за run.

NinjaTrader перезапускать не требуется. AI Lab пишет новый sandbox source,
отправляет F5 в уже открытый NinjaScript Editor и ждёт изменение
`NinjaTrader.Custom.dll`.

## Защита от повторения системных ошибок (02.07.2026)

Ноль сделок считается результатом стратегии только при подтверждённом ряде
баров: непустой `BarsArray[0]`, реальный `historical_data_fingerprint`,
положительный `bar_count`/`bars.json` и пересечение периода задания с
`data_first..data_last` контракта. Иначе это инфраструктурная блокировка, а не
отрицательный урок о стратегии.

Контракт выбирается по самой свежей фактической минутной свече. Smoke при
ошибке данных один раз пробует следующий подходящий контракт. Run-level и
mission-level circuit breakers прекращают новые генерации и платные вызовы
после двух одинаковых структурных ошибок либо пяти `SMOKE_ZERO_TRADES`.
Остановка отображается в AI Lab и отправляется в Telegram.

Signal sanity сначала ищет bars именно выбранного контракта. Данные другого
месяца того же root разрешены только как advisory: они не могут отклонить
стратегию до авторитетного NinjaTrader smoke текущего контракта.

Маршрут гипотез: бесплатный внешний пул → локальная модель → платный fallback.
Health gate локальной модели кэшируется на 15 минут. Динамические experiment
поля перенесены после cache marker, чтобы стабильный prefix действительно
переиспользовался.

Compile baseline снимается до записи sandbox `.cs`. NinjaTrader может
автоматически собрать DLL за несколько секунд ещё до явного F5; прежний порядок
терял это событие и ошибочно ждал второе изменение пять минут. Bootstrap также
сверяет собранную и установленную bridge DLL и безопасно разворачивает обновление
до старта NinjaTrader, если терминал закрыт.
