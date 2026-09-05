# Архитектурные решения следующего этапа


ADR 0001–0008: `Принято`. Основание — поручения owner по следующей архитектуре
и изоляции окружений. ADR 0009 — `Proposed`, foundation-контракты Agent World.
ADR 0010 сохраняет решение об изолированном synthetic owner-review; ADR 0011
отдельно фиксирует добавленный real Local owner путь через существующие
NinjaTrader jobs и Desktop receipts. Реализация ограниченных путей не означает
принятия всех production-контрактов, закрытия этапов 0–13 или owner visual
acceptance. Изменение принятого решения требует нового ADR, а не молчаливой
правки реализации.

| ADR | Решение |
|---|---|
| [0001](0001-environments-and-release-identity.md) | Окружения, release channel и build identity |
| [0002](0002-unified-identity.md) | UUID-пользователь и связывание способов входа |
| [0003](0003-trusted-devices-and-step-up.md) | Trusted devices и step-up authentication |
| [0004](0004-admin-panel-and-capabilities.md) | Admin Panel и capability permissions |
| [0005](0005-immutable-release-promotion.md) | Immutable artifact, Canary и blue-green promotion |
| [0006](0006-ninjatrader-ownership-and-resource-lease.md) | Личный и общий NinjaTrader, агенты и lease |
| [0007](0007-document-governance.md) | Документы, области изменения и история поправок |
| [0008](0008-environment-cookie-and-storage-isolation.md) | Изоляция cookies и browser storage по окружениям |
| [0009](0009-agent-world-foundation.md) | Agent World: сущности, статусы, scope, events, repositories и default-off flags (`Proposed`) |
| [0010](0010-agent-world-owner-review.md) | Agent World: изолированный owner-review с SQLite, проверочными задачами, UI и SF Chat; production/design acceptance отдельно |
| [0011](0011-agent-world-real-local-jobs.md) | Agent World: explicit default-OFF Local owner, реальные исторические NT jobs, Desktop PNG receipts и существующий SF Chat; Local switch и real E2E/visual acceptance ещё не приняты |
| [0012](0012-agent-world-integrated-local.md) | Agent World: разрешённый Local switch, модели и проверенные application tasks, все domain drawers, память/Court и явная SF Social публикация; текущие acceptance gates в canonical status |

Главный аудит и поэтапный план: [STRATFORGE_NEXT_ARCHITECTURE_AUDIT_AND_IMPLEMENTATION_PLAN_2026-08-01.md](../current/STRATFORGE_NEXT_ARCHITECTURE_AUDIT_AND_IMPLEMENTATION_PLAN_2026-08-01.md).
