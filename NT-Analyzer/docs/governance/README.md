# Governance Docs

Эта папка — канонический слой governance для проекта.

- `OVERVIEW.md` — краткое главное предисловие и актуальная сводка.
- `CHARTER.md` — цель, границы и основные принципы.
- `ROLES.md` — роли владельца и всех ИИ-каналов.
- `LAWS.md` — общие законы проекта.
- `LOCAL_AI_LAWS.md` — отдельные законы локального ИИ и cloud fallback / AI Lab.
- `../agents/AI_LAB_COMPETITIVE_FEEDBACK.md` — контракт конкурентной обратной связи для AI-ролей.
- `REGISTRY_POLICY.md` — правила ведения реестра стратегий.
- `SYNC_MAP.md` — что синхронизируется автоматически, а что нужно проверять вручную.

Редактируемый machine source of truth:

- `data/governance/laws.json`
- `data/governance/documents.json`
- `data/governance/change_log.jsonl` — последовательный журнал поправок с датой, временем, автором и before/after.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T06:20:00Z | Grok 4.6 через Cursor по запросу owner | Зафиксировать live HTTP identity 1fae1f39 на Canary+Production и repository-фикс Documents/Release Center allowlist + TopstepX fallback на сервере. Не STAGE CLOSED: нет /proc cwd/exe и нет нового signed artifact.
-->
