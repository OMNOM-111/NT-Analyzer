# StratForge AI External GPT Context Pack

- Context Pack document: 00_STRATFORGE_CONTEXT_INDEX.md
- Last verified UTC: 2026-08-13T02:25:57Z
- Verified against Git SHA: c4711ae3f876966f6bedcba8fc3b4ad9c309c836
- Scope: Entry point, pack inventory, reading order and status legend
- Status: DONE

## Назначение

Этот набор загружается во внешний ChatGPT Project, у которого нет доступа к
GitHub, локальному компьютеру, серверу или runtime-данным. Он даёт компактную
и текущую картину StratForge AI без копирования репозитория и без передачи
секретов.

## Snapshot

| Поле | Значение |
| --- | --- |
| Продукт | StratForge AI |
| Техническое имя репозитория | `NT-Analyzer` |
| Проверенный Git root | корень репозитория; живой продуктовый код находится в `NT-Analyzer/` |
| Public version | `0.10.0-beta.1` |
| Release status | `beta`, `pre_release` |
| DEV | локальный loopback development из `NT-Analyzer/`; dirty checkout разрешён и должен явно маркироваться |
| CANARY | отдельное deployment environment на `https://canary.stratforges.com`; тот же immutable-artifact принцип, что и для Production; текущий live build из репозитория не доказуем |
| PRODUCTION | публичный origin `https://app.stratforges.com`; release channel может быть `beta` или `stable`; live trading остаётся gated |

## Порядок чтения

1. [01_PRODUCT_VISION_AND_SCOPE.md](01_PRODUCT_VISION_AND_SCOPE.md)
2. [02_CURRENT_SYSTEM_STATE.md](02_CURRENT_SYSTEM_STATE.md)
3. [03_ARCHITECTURE_AND_DATA_MODEL.md](03_ARCHITECTURE_AND_DATA_MODEL.md)
4. [04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
5. [05_AUTH_USERS_SECURITY.md](05_AUTH_USERS_SECURITY.md)
6. [06_MARKET_DATA_TRADING_CONNECTOR.md](06_MARKET_DATA_TRADING_CONNECTOR.md)
7. [07_AI_AGENTS_AND_AUTOMATION.md](07_AI_AGENTS_AND_AUTOMATION.md)
8. [08_UI_UX_AND_PRODUCT_CONTRACTS.md](08_UI_UX_AND_PRODUCT_CONTRACTS.md)
9. [09_DOCUMENTATION_GOVERNANCE_LEGAL.md](09_DOCUMENTATION_GOVERNANCE_LEGAL.md)
10. [10_DECISIONS_HISTORY_AND_CHANGELOG.md](10_DECISIONS_HISTORY_AND_CHANGELOG.md)
11. [11_ACTIVE_WORK_AND_HANDOFF.md](11_ACTIVE_WORK_AND_HANDOFF.md)
12. [12_API_AND_SCHEMA_REFERENCE.md](12_API_AND_SCHEMA_REFERENCE.md) при необходимости точных surface names
13. [13_TEST_AND_ACCEPTANCE_MATRIX.md](13_TEST_AND_ACCEPTANCE_MATRIX.md) для test/release impact
14. [14_EXTERNAL_GPT_OPERATING_INSTRUCTIONS.md](14_EXTERNAL_GPT_OPERATING_INSTRUCTIONS.md) как режим работы внешней модели

## Состав пакета

| Файл | Роль |
| --- | --- |
| [00_STRATFORGE_CONTEXT_INDEX.md](00_STRATFORGE_CONTEXT_INDEX.md) | точка входа и legend |
| [01_PRODUCT_VISION_AND_SCOPE.md](01_PRODUCT_VISION_AND_SCOPE.md) | что такое StratForge и где его границы |
| [02_CURRENT_SYSTEM_STATE.md](02_CURRENT_SYSTEM_STATE.md) | текущий factual snapshot |
| [03_ARCHITECTURE_AND_DATA_MODEL.md](03_ARCHITECTURE_AND_DATA_MODEL.md) | компоненты, trust boundaries, ключевые сущности |
| [04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md) | DEV/CANARY/PRODUCTION и promotion model |
| [05_AUTH_USERS_SECURITY.md](05_AUTH_USERS_SECURITY.md) | identity, sessions, devices, step-up, permissions |
| [06_MARKET_DATA_TRADING_CONNECTOR.md](06_MARKET_DATA_TRADING_CONNECTOR.md) | NinjaTrader, Connector, TopstepX, trading gates |
| [07_AI_AGENTS_AND_AUTOMATION.md](07_AI_AGENTS_AND_AUTOMATION.md) | Vitek, Orchestrator, specialists, AI Lab |
| [08_UI_UX_AND_PRODUCT_CONTRACTS.md](08_UI_UX_AND_PRODUCT_CONTRACTS.md) | major UI surfaces and UX contracts |
| [09_DOCUMENTATION_GOVERNANCE_LEGAL.md](09_DOCUMENTATION_GOVERNANCE_LEGAL.md) | docs source-of-truth, governance, legal DRAFT status |
| [10_DECISIONS_HISTORY_AND_CHANGELOG.md](10_DECISIONS_HISTORY_AND_CHANGELOG.md) | why the system looks this way today |
| [11_ACTIVE_WORK_AND_HANDOFF.md](11_ACTIVE_WORK_AND_HANDOFF.md) | current branch/sha/blockers/next actions |
| [12_API_AND_SCHEMA_REFERENCE.md](12_API_AND_SCHEMA_REFERENCE.md) | compact endpoint/entity/permission index |
| [13_TEST_AND_ACCEPTANCE_MATRIX.md](13_TEST_AND_ACCEPTANCE_MATRIX.md) | gates, acceptance and rollback expectations |
| [14_EXTERNAL_GPT_OPERATING_INSTRUCTIONS.md](14_EXTERNAL_GPT_OPERATING_INSTRUCTIONS.md) | instructions to the external GPT itself |

## Легенда статусов

Pack normalizes repo-specific terms such as `AVAILABLE` and `BETA` into a
smaller external vocabulary.

| Status | Значение |
| --- | --- |
| `DONE` | работает сейчас и является реальной текущей возможностью/контрактом |
| `PARTIAL` | часть capability реализована, но есть явные gaps или незакрытая acceptance |
| `EXTERNAL BLOCKED` | код/дизайн есть, но доступность заблокирована внешним условием |
| `IN DEVELOPMENT` | активная разработка без завершённого current contract |
| `PLANNED` | целевое направление без готового current implementation contract |
| `DEPRECATED` | историческое или вытесненное решение; не считать current state |

## Source-of-truth hierarchy

1. Current code, current schema and current config contracts.
2. Current canonical docs and ADRs.
3. Current release manifests, build scripts and deployment runbooks.
4. Historical plans, handoffs and audits only as explanation of context, not as current truth.

## Canonical repo evidence to pair with this pack when needed

- Product/runtime overview: [../../README.md](../../README.md)
- Docs tree and governance: [../DOCS_STRUCTURE.md](../DOCS_STRUCTURE.md), [../DOCUMENTATION_GOVERNANCE.md](../DOCUMENTATION_GOVERNANCE.md)
- Environment and identity ADRs: [../adr/0001-environments-and-release-identity.md](../adr/0001-environments-and-release-identity.md), [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), [../adr/0003-trusted-devices-and-step-up.md](../adr/0003-trusted-devices-and-step-up.md), [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md), [../adr/0005-immutable-release-promotion.md](../adr/0005-immutable-release-promotion.md)
- Connector and market-data contracts: [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md), [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md), [../architecture/UI_API_MAP.md](../architecture/UI_API_MAP.md)