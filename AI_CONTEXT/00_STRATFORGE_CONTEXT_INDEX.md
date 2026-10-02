# StratForge AI — AI_CONTEXT

- Context Pack document: 00_STRATFORGE_CONTEXT_INDEX.md
- Last verified UTC: 2026-10-02T05:14:45Z
- Verified against Git SHA: e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885
- Scope: Entry point, pack inventory, reading order and status legend
- Status: DONE

## Назначение

`AI_CONTEXT/` в корне репозитория — единственный канонический технический
контекст для Codex, Claude, Dots и внешних моделей. Его можно загружать без
доступа к GitHub, локальному компьютеру, серверу или секретам. Перед новой
работой читать этот индекс, `02_CURRENT_SYSTEM_STATE.md`,
`11_ACTIVE_WORK_AND_HANDOFF.md` и корневой `timeline.html`. Старый
`NT-Analyzer/docs/external-gpt-context/` выведен из роли источника истины.

## Snapshot

| Поле | Значение |
| --- | --- |
| Продукт | StratForge AI |
| Техническое имя репозитория | `NT-Analyzer` |
| Проверенный Git root | корень репозитория; живой продуктовый код находится в `NT-Analyzer/` |
| Current public version | `0.10.0-beta.106`; Canary and Production passed the same immutable artifact |
| Release status | `beta`, `pre_release` |
| Git main at task start | `9483bac868d829f3891e5e09fe84c18d242cf9c6` (PR #312 docs-only closeout) |
| Deployed application source | `e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885` |
| Operational artifact | `art_7aebf504ae354ce7981c58359a1ff546`; build `sf-0.10.0-beta.106-e7ecd2133c65-20261001T150927Z`; [release record](../NT-Analyzer/docs/changelog/2026-10-01-beta106-periodic-owner-model-route.md) |
| DEV | `http://127.0.0.1:8765/ui/`; clean beta.106 application baseline in `local-current`, original owner data root; first clean launch `b809911c73c219b92e43c9b46d0d79b26a118b7a`, exact current build/SHA from `/api/runtime/env`; owner Agent World/Social/Chat click-through PASS; some new-user surfaces remain partial |
| CANARY | `https://canary.stratforges.com`; beta.106 same artifact, live/ready 200; owner Agent World/Social/Chat and public registration step 1/3 observed; real non-owner trial expired |
| PRODUCTION | `https://app.stratforges.com`; beta.106 same artifact, 7/7 product package PASS, live/ready 200; owner UI and public registration step observed; real non-owner trial expired for fresh chart/security check |
| Current task | Local Runtime & Documentation Canonicalization — In progress; [handoff](11_ACTIVE_WORK_AND_HANDOFF.md) |

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
| [07_AI_AGENTS_AND_AUTOMATION.md](07_AI_AGENTS_AND_AUTOMATION.md) | Agent World, Deputy, specialists and bounded automation |
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

## Evidence model

- **Repository evidence**: current code, schema, config and current canonical docs
	that describe what the repository implements.
- **Operational evidence**: latest accepted release/deployment closeout in
	[beta.106 release record](../NT-Analyzer/docs/changelog/2026-10-01-beta106-periodic-owner-model-route.md).
- **Historical evidence**: plans, older audits and handoffs used only to explain
	why the system looks the way it does today.

When the question is “what is deployed now”, prefer operational evidence. When
the question is “what does the current repository implement”, prefer repository
evidence. Do not collapse the two into one undifferentiated claim.

## Canonical repo evidence to pair with this pack when needed

- Product/runtime overview: [../../README.md](../NT-Analyzer/README.md)
- Docs tree and governance: [../DOCS_STRUCTURE.md](../NT-Analyzer/docs/DOCS_STRUCTURE.md), [../DOCUMENTATION_GOVERNANCE.md](../NT-Analyzer/docs/DOCUMENTATION_GOVERNANCE.md)
- Environment and identity ADRs: [../adr/0001-environments-and-release-identity.md](../NT-Analyzer/docs/adr/0001-environments-and-release-identity.md), [../adr/0002-unified-identity.md](../NT-Analyzer/docs/adr/0002-unified-identity.md), [../adr/0003-trusted-devices-and-step-up.md](../NT-Analyzer/docs/adr/0003-trusted-devices-and-step-up.md), [../adr/0004-admin-panel-and-capabilities.md](../NT-Analyzer/docs/adr/0004-admin-panel-and-capabilities.md), [../adr/0005-immutable-release-promotion.md](../NT-Analyzer/docs/adr/0005-immutable-release-promotion.md)
- Connector and market-data contracts: [../architecture/CONNECTOR_PROTOCOL_V1.md](../NT-Analyzer/docs/architecture/CONNECTOR_PROTOCOL_V1.md), [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../NT-Analyzer/docs/architecture/MARKET_DATA_RESILIENCE_PLAN.md), [../architecture/UI_API_MAP.md](../NT-Analyzer/docs/architecture/UI_API_MAP.md)
- Operational release evidence: [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../NT-Analyzer/docs/changelog/2026-08-22-market-data-responsive-release-beta29.md), [../current/CLEAN_CLOSEOUT_HANDOFF.md](../NT-Analyzer/docs/current/CLEAN_CLOSEOUT_HANDOFF.md), [../current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md](../NT-Analyzer/docs/current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md), [../changelog/NEXT_ARCHITECTURE_CHANGELOG.md](../NT-Analyzer/docs/changelog/NEXT_ARCHITECTURE_CHANGELOG.md)
