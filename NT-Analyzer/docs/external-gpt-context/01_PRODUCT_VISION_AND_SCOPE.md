# 01. Product Vision and Scope

- Context Pack document: 01_PRODUCT_VISION_AND_SCOPE.md
- Last verified UTC: 2026-08-13T09:49:37Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Product purpose, users, boundaries and principles
- Status: DONE

## Что такое StratForge AI

StratForge AI - это local-first торгово-аналитическая платформа, в которой
Aurora web UI, NinjaTrader 8, StratForge Connector, market-data adapters и AI
Agent Team работают как единый контур: идея стратегии -> код -> compile ->
backtest -> анализ -> controlled runtime.

Ключевая продуктовая идея: снять с трейдера ручную рутину и дать ему систему,
которая понимает стратегии, рынок, историю прогонов и рабочие ограничения
торгового контура.

## Кому нужен продукт

| Пользователь | Что получает сейчас |
| --- | --- |
| Владелец / главный оператор | полный owner-level контроль над продуктом, релизами, агентами, документами, Telegram и локальным NinjaTrader-контуром |
| Трейдер с личным NinjaTrader | целевая модель personal workspace + pairing; часть сущностей и контрактов уже есть, но массовый multi-user rollout ещё не завершён |
| Пользователь учебного owner-training контура | read-only и ограниченный paper/demo доступ по разрешениям; чужие live-полномочия не выдаются |
| Developer / support / admin | scoped capabilities, diagnostics, release/admin surfaces, без автоматического доступа к личным аккаунтам пользователей |

## Основные возможности

| Возможность | Status | Фактический current scope |
| --- | --- | --- |
| Aurora command center | `DONE` | обзор, backtesting, trading/runtime, performance, strategies, AI Lab, news, documents |
| Backtests через NinjaTrader Strategy Analyzer runtime | `DONE` | задания выполняются через NinjaTrader; baseline manual parity against Strategy Analyzer зафиксирован |
| Read-only charts и market data | `DONE` | TopstepX даёт независимые графики и realtime/history даже при выключенном NinjaTrader |
| AI Strategy Lab | `PARTIAL` | цикл idea -> code -> compile -> backtest -> arbitration есть, но не вся продуктовая автоматизация завершена |
| Paper/demo runtime control | `PARTIAL` | безопасные enable/disable/reconnect workflows доступны для paper/demo/playback |
| Account-mode aware execution controls | `PARTIAL` | Simulation vs real/live определяется подключённым NinjaTrader account; конкретное действие разрешают или блокируют permissions, safety gates, release gates и account capabilities |
| Multi-user personal workspaces | `PARTIAL` | модель описана и частично реализована, но полный продуктовый rollout ещё не закрыт |
| Team/shared collaboration around one NinjaTrader contour | `PARTIAL` | owner-training/shared patterns есть, но leasing/scaling/permissions продолжают усиливаться |

## Personal vs shared NinjaTrader

- `Owner training` - текущий общий учебный контур владельца, из которого нельзя
  выводить вывод, что любой пользователь получает live-control.
- `Personal workspace` - целевая и частично реализованная модель, где у каждого
  пользователя свой workspace, своё pairing и своя локальная NinjaTrader-машина.
- NinjaTrader credentials не собираются приложением. Пользователь логинится в
  терминал локально; StratForge видит только bridge telemetry, accounts и
  разрешённые результаты команд.

## Фактическая модель Simulation / Demo / real broker trading

- UI label `Simulation/Live` отражает подключённый NinjaTrader account mode, а
  не придуманное приложением состояние.
- Paper/demo workflows доступны через backend gates и требуют явных capability /
  confirmation rules.
- Если NinjaTrader подключён к real/live account, это по-прежнему только факт
  account mode. Разрешение на конкретное execution-действие определяется
  application permissions, safety gates, release gates и account capabilities;
  отсутствие такого разрешения сейчас является gate, а не отдельным будущим
  продуктом под названием “Live Trading”.

## Границы продукта

- StratForge не является брокером и не хранит broker credentials.
- TopstepX и другие chart/data providers используются как read-only источники;
  внешний chart feed не авторизует ордера.
- NinjaTrader остаётся единственным execution path и источником истины по
  fills, trades, runtime-state и реальному account mode.
- Репозиторий хранит код, схемы, docs, prompts и safe static catalogs, но не
  runtime logs, secrets, личные API keys или generated trading archives.

## Product principles

1. Local-first by default; server surfaces must be explicit and isolated.
2. Fail closed for environment, identity, release and critical trading actions.
3. Separate chart source, strategy source and execution authority.
4. Keep user/workspace isolation explicit rather than inferred from role names.
5. Prefer immutable release promotion and auditable approvals over in-place mutation.

## Canonical evidence

- [../../README.md](../../README.md)
- [../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md](../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md)
- [../architecture/UI_API_MAP.md](../architecture/UI_API_MAP.md)
- [04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [06_MARKET_DATA_TRADING_CONNECTOR.md](06_MARKET_DATA_TRADING_CONNECTOR.md)
- [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md)
