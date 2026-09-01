# beta.86 - Legacy Isolation + Telegram Bot Cleanup

Release summary: Текущий StratForge полностью отделён от legacy UI и Telegram Mini App, при этом исторические отчёты сохранены в отдельном read-only Legacy Viewer, а текущие Telegram login, confirmations и notifications остаются рабочими.
Release PRs: #254, #255
Affected subsystems: Aurora UI, Legacy Viewer, Telegram bot URL flow, Release Center, release governance
Release impact: Удалён вход в legacy UI и Mini App из текущего продукта; добавлен понятный обязательный release/change record без изменения market data, Connector или trading execution.

## Что вошло

- PR #254: legacy UI и исторические данные изолированы в localhost-only read-only Legacy Viewer; текущие legacy routes fail closed.
- PR #255: Telegram `/start` открывает StratForge обычной URL-кнопкой без возврата Mini App/WebApp binding.
- Release Center показывает название, описание, PR, SHA, build/artifact, этап, проверки, длительность и identity DEV/Canary/Production; Production блокируется без полного release/change record.

## Сохранено

- Current Telegram auth, login confirmation, NinjaTrader confirmation, bot notifications and callbacks.
- Historical reports, audit/history and the temporary Legacy Viewer launcher.
- Existing market data, Connector, trading execution and release artifact invariants.

## Release sequence

`final main -> mandatory CI -> one signed immutable artifact -> Canary acceptance -> same artifact without rebuild -> Production`

Operational candidate, build, artifact hashes, Canary result and Production result are appended to the canonical closeout after the live release completes.
