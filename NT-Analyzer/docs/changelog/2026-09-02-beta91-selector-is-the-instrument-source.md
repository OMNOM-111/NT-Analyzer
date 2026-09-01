# beta.91 - The selector reads the catalog the backtest runs

Release summary: Селектор инструментов на сервере читал только файловый скан NinjaTrader, а контракты от Connector — нет, поэтому у корня не было front month и в поле бэктеста попадал голый корень. Селектор переведён на тот же собранный каталог, что отдаёт `/api/catalog`, а серверные проверки инструмента и истории убраны: как и в Local, инструмент разрешает NinjaTrader.
Release PRs: TBD
Affected subsystems: instrument selector endpoint, backtest job validation
Release impact: Выбор корня в Production даёт тот же конкретный контракт, что и в Local. Connector transport, signing/trust, auth, Release Center и market-data не затронуты.

## Фактический Local flow, взятый за эталон

1. `/api/ops/runtime/instruments` группирует каталог по корням и публикует `front_month`.
2. UI показывает корни; клик кладёт в поле инструмента `front_month.instrument` — конкретный контракт.
3. `/api/jobs` получает конкретный контракт.
4. Мост передаёт строку в `NinjaTrader.Cbi.Instrument.GetInstrument`, и прогон выполняет NinjaTrader.

Разворачивание корня в контракт всегда делал шаг 2, а не сервер.

## Что было сломано

`/api/catalog` мержит device-каталог Connector, а эндпоинт селектора читал только `read_instruments_catalog()`. Рядом с NinjaTrader это один и тот же список, поэтому расхождение было невидимым. На сервере файл — устаревший `desktop_root_fallback` из 36 голых корней: `front_month` пуст, UI подставляет `fm.instrument || r.root`, и в поле уходит `6M`.

## Что вошло

- Эндпоинт селектора собирает инструменты через `build_catalog_response(device_catalog=...)` — тот же источник и тот же merge, что у `/api/catalog`. Нового источника истины не появилось.
- Удалён `_validate_instrument_contract`: сервер больше не решает, какие инструменты существуют и есть ли по ним история. Это знание есть только у NinjaTrader, и он его сообщает — провалившийся прогон `10YR 10-25` в Local отчитался `instrument: resolved` и `variant1_no_historical_bars` / `historical_bars_missing`.
- Удалён серверный резолвинг корня из `create_job`: его роль выполняет селектор, как в Local.
- `resolve_front_month` остаётся общей функцией правила селектора.

## Проверено

Local, 56 корней, у каждого свой front month: `6M -> 6M 09-26`, `MNQ -> MNQ 09-26`, `MES -> MES 09-26`, `MCL -> MCL 09-26`, `6E -> 6E 09-26`.

Тесты закрепляют правило селектора и то, что сервер не фильтрует инструмент — включая формы `MNQ SEP26` и `10YR 10-25`, которые NinjaTrader принимает. Полный набор: 2487 passed, 32 skipped.

## Release sequence

`Local -> mandatory CI -> one signed immutable artifact -> Canary -> тот же артефакт без пересборки -> Production`
