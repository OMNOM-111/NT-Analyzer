# OVERVIEW

Дата актуализации: 2026-08-09T00:57:35Z

## Короткое предисловие

Это первый и главный документ. Здесь держится самая сжатая, но актуальная версия правил проекта.
Последняя рабочая версия всегда определяется текущими законами и этим файлом, а история всех поправок остаётся в журнале.

## Самое главное сейчас

- StartingCapital по умолчанию: `2000.00 USD`
- Max drawdown gate: `15%` от зафиксированного capital
- Минимальная комиссия: `1.90 USD` round turn
- Минимальный slippage: `1 ticks`
- Fill mode: `High`
- IntradayOnly по умолчанию: `Да`
- Канонический цикл: `Research Hub -> Deploy wrapper`
- Paper before live: `Да`
- Runtime должен совпадать с locked params: `Да`
- AI Lab sandbox only: `Да`
- AI Lab cloud API: `local-first fallback; 20.00 USD/month; 0.50 USD/run`
- Базовое PT-окно AI Lab: `06:30-12:30 PT`

## На что смотреть в первую очередь

- Бюджет стратегии: capital, MaxDD, комиссия и slippage.
- Любой live-допуск возможен только после paper и ручного решения владельца.
- Любое изменение закона должно быть видно и в документах, и в журнале поправок.
- Исторические approved/paper профили после смены capital или risk нужно ревалидировать отдельно.

## Где править и где проверять

- Удобнее всего работать через `/ui/docs.html`: там читать, редактировать и смотреть журнал.
- Законы менять в `LAWS` или `LOCAL_AI_LAWS`.
- После изменения смотреть `SYNC_MAP`, блок `Где проверять после изменения` и журнал поправок.
- Если нужна первичная проверка по файлам, открыть `docs/governance/OVERVIEW.md`, `docs/governance/LAWS.md` и `data/governance/change_log.jsonl`.

## Последние поправки

- Поправка 11 · 2026-08-09T00:57:35Z · `GPT-5.5 через Codex по запросу owner` · Production auth, Connector and TopstepX acceptance audit: Auth Connector TopstepX audit: `external auth, installer and TopstepX readiness not fully verified` -> `local implementation verified; exact Production external gates documented`; Connector and market data runbooks: `no active TopstepX read-only path and stale two-environment wording` -> `TopstepX policy/failover contract, consented Connector setup and Development/Canary/Production gates`
- Поправка 10 · 2026-08-02T03:17:45Z · `GPT-5.5 через Codex по запросу owner` · Next Architecture Phase 2 closeout: Stage status: `IMPLEMENTATION COMPLETE; GIT CLOSEOUT PENDING` -> `STAGE CLOSED`; PR and merge: `pending` -> `PR #8 merged at ca65be2e; task branch deleted`
- Поправка 9 · 2026-08-02T03:06:47Z · `GPT-5.5 через Codex по запросу owner` · Next Architecture Phase 2 Admin Panel: Administrative authorization: `owner-only controls mixed with product UI` -> `separate explicit expiring grants and server-side capability checks`; Personal UI: `system actions in three-dot menu and cabinet tabs` -> `personal menu/cabinet plus capability-gated Admin Panel`
- Поправка 8 · 2026-08-02T02:17:26Z · `GPT-5.5 через Codex по запросу owner` · Next Architecture Phase 1 closeout: Stage status: `IMPLEMENTATION COMPLETE; GIT CLOSEOUT PENDING` -> `STAGE CLOSED`; PR and merge: `PR pending` -> `PR #7 merged at f4bcb3fc; task branch deleted`
- Поправка 7 · 2026-08-02T01:55:27Z · `GPT-5.5 через Codex по запросу owner` · Next Architecture Phase 1 environment metadata: Environment и release metadata: `production|development; development|canary|stable; partial build identity` -> `development|canary|production; dev|beta|stable; complete build identity`; UI labels and icons: `DEV|CANARY|STABLE derived from channel` -> `DEV|CANARY|BETA derived from env/channel; stable Production unlabelled`
