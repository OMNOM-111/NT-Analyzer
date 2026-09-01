# beta.88 - Connector Instrument Catalog

Release summary: Реальный каталог контрактов NinjaTrader доставляется на сервер подписанными страницами через Connector, голые fallback-корни больше не считаются контрактами, а бэктест без полноценного каталога останавливается явно вместо тихого падения внутри NinjaTrader.
Release PRs: #261
Affected subsystems: Connector protocol, Connector bridge (CatalogWriter, ConnectorClient), server catalog assembly, backtest job validation
Release impact: Бэктест на сервере получает конкретные контракты вместо корней; market data, TopstepX, NinjaTrader execution и Release Center не затронуты; старый Connector остаётся совместимым.

## Что вошло

- PR #261: полный каталог доставляется как один snapshot с `catalog_id`, `generated_at` и `total_count`, разбитый на подписанные страницы. Размер страницы считается по фактически сериализованному payload: цель 12 KiB против жёсткого отказа в 16 KiB и менее 80 элементов против отказа на 100.
- PR #261: сервер копит страницы одного `catalog_id` и активирует каталог атомарно только после получения полного набора, совпадающего с `total_count`. Незавершённая доставка не заменяет предыдущий рабочий каталог; недостающая страница дозапрашивается по тому же подписанному каналу.
- PR #261: порядок round-robin по корням - активный месяц каждого корня попадает на первую страницу, остальной 400-дневный набор идёт следом, ничего не отбрасывается.
- PR #261: бэктест принимает только контракт, который есть в реальном каталоге. Голый корень получает конкретную подсказку, отсутствие каталога - явный отказ.

## Root cause, который это закрывает

Сервер не имеет базы NinjaTrader, поэтому его каталог инструментов работал на захардкоженном списке из 36 голых корней (`source: desktop_root_fallback`). Панель предлагала `MNQ` и `6A`, задача принималась, NinjaTrader не мог развернуть контрактный месяц, и владелец видел `failed` с пустой ошибкой. Все падения бэктеста в Production были этой формы.

## Сохранено

- Спотовые инструменты без контрактного месяца (`BTCUSD`, `BCHEUR`): голый корень определяется по отсутствию диапазона данных, а не по форме имени.
- Обратная совместимость в обе стороны: `page_index` не отправляется для нулевой страницы, а результат без полей пагинации трактуется как одна полная страница.
- Market data / TopstepX, Connector protocol за пределами каталога, NinjaTrader execution, Release Center и security-контракты.

## Доказано на реальном каталоге (1547 контрактов)

```
eligible contracts (400-day) : 292
delivered contracts          : 292/292
roots preserved              : 52/52
valid contracts lost         : 0
pages                        : 4
largest page                 : 11972 bytes / 80 items
incomplete snapshot keeps previous catalog : YES
spot instruments preserved   : BCHEUR, BTCUSD
old Connector activates      : YES
```

## Release sequence

`final main -> mandatory CI -> one signed immutable artifact -> Canary acceptance -> same artifact without rebuild -> Production`

Полный эффект появляется только после того, как на машине с NinjaTrader заработает новый Connector: контракты приходят от него. Операционные candidate, build, artifact hashes, результат Canary и Production дописываются сюда после завершения живого релиза.
