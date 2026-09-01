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

## Operational closeout - 2026-09-01

Released. Development, Canary and Production run the same immutable artifact;
Production was promoted without a rebuild.

| Field | Value |
| --- | --- |
| Final main SHA | `8f42158661e8247832c90bea8fc4d9f0071e647b` |
| Version | `0.10.0-beta.87` |
| Candidate | `rc_afebdc07e6e743d7be2f99cd91cf8617` |
| Artifact ID | `art_9ce9dbcb9a7a4fee9df6a54d40f29806` |
| Build ID | `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z` |
| Archive SHA256 | `8889D38817409067E9A9EBE583DDF8225DF6383B328F09EA4F06053C70989A9D` |
| Signature | verified |
| Final state | `production_live` |

Gates: PR #258 CI 5/5 on `f6f1c8e8`; main CI PASS on `b121bb18`; PR #259 CI 5/5
on `d2b9e802`; final main CI PASS on `8f42158661e8`; `pre_release_check` PASS
(bundle 468); release static scan PASS; External GPT Context validator PASS;
full pytest 2449 passed / 32 skipped.

Canary acceptance: artifact identity, signature, `/live` 200, `/ready` 200,
`/api/health` 401, current Aurora surfaces 200, `/ui/legacy/` 410, Mini App 410,
classic assets 404, Telegram endpoints alive at 401, market data role `consumer`,
Connector `ok`, and the shipped Backtest demo-gate fix verified in the delivered
`backtesting.js` and `ui.js`.

Production verification: `/live` and `/ready` 200, build id and Git SHA match the
artifact exactly, Aurora surfaces 200, retired surfaces 410, classic assets 404,
Telegram and market-data endpoints auth-gated. In the delivered Production
bundle the subscription upsell sits inside the `if (host && isDemoOnly)` guard,
and the only unguarded watermark occurrence is the per-report badge keyed on a
real `kind == demo_backtest`. The Production Backtest page reports
`demoTier=0` with no demo or subscription text.

The owner-authenticated Backtest run was proven on Development against this exact
code: job `ui_20260901T015052691Z` completed and produced report No 18790
(`B1EarlyWindowMGC5mC006` / `MNQ 09-26`) with a real equity curve and the
Strategy Analyzer validation badge. Signing in as the owner in Production
requires the owner's own Telegram session and was not performed by automation.

Repository hygiene in the same pass: 27 stashes removed after proving each held
only generated `governance-rendered` output, a `margins.json` timestamp or
`star_ratings.json` runtime counters; 10 worktrees removed whose commits were
already in main; 6 worktrees with unique unmerged commits were kept and listed.
