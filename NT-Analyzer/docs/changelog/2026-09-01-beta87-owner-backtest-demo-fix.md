# beta.87 - Owner Backtest Demo Gate Fix

Release summary: Бэктест владельца больше не помечается демоверсией с нереальными данными и предложением подписки; серверные права не менялись, исправлена только страница Бэктеста, а Context Pack приведён к фактическому состоянию beta.86.
Release PRs: #257, #258
Affected subsystems: Aurora Backtest page, Aurora shell demo-tier flag, Context Pack documentation
Release impact: Владелец видит бэктест как настоящий; легитимный демо-тир, демо-кнопка и бейдж настоящего демо-отчёта сохранены; market data, Connector, NinjaTrader execution и Release Center не затронуты.

## Что вошло

- PR #258: панель демо-сценариев на странице Бэктеста рендерилась без единого условия, поэтому аккаунт с полным `backtesting` (включая владельца) видел «Демоверсия. Данные нереальные.» и «После подписки откроются полный бэктест». Панель ограничена демо-тиром; глобальный флаг демо в `ui.js` теперь явно исключает владельца.
- PR #258: новый набор регрессионных тестов `tests/test_owner_backtest_not_demo.py` (9 проверок).
- PR #257 и PR #258: Context Pack записывает beta.86 как живой релиз с фактической identity вместо «promotion pending».

## Root cause

Введено `0f1b71f1` (2026-07-15, демо-тир бэктеста). Кнопка запуска была защищена `isDemoOnly` с исключением владельца, а сам рендер панели с водяным знаком и апселлом - нет. Латентный дефект, не регрессия beta.86.

Тесты его не поймали, потому что проверяли резолв прав и серверные гейты, но никогда - что tier-специфичная панель скрыта у аккаунта с полным доступом.

## Сохранено

- Серверные права: `permissions.resolve()` всегда возвращал владельцу `demo_tier: False` и все capabilities.
- Настоящий демо-тир, кнопка «Демо-бэктест» и бейдж демо-отчёта по фактическому `kind == demo_backtest`.
- Историческая история бэктестов, market data/TopstepX, Connector, NinjaTrader execution, Release Center и security-контракты.

## Release sequence

`final main -> mandatory CI -> one signed immutable artifact -> Canary acceptance -> same artifact without rebuild -> Production`

Операционные candidate, build, artifact hashes, результат Canary и Production дописываются в этот файл после завершения живого релиза.
