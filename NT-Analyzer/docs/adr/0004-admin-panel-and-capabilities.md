# ADR-0004: Admin Panel и capability permissions

История поправки: 2026-08-02T00:53:55Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 0 — утвердить административную границу и server-side authorization.

- Статус: Принято
- Дата решения: 2026-08-01

## Решение

Системные функции переносятся из пользовательского меню и cabinet tabs в отдельную оболочку Admin Panel. Скрытие UI не является авторизацией: каждый API endpoint проверяет capability на сервере.

Базовые capabilities: `admin.view`, `users.manage`, `operations.view`, `operations.execute`, `releases.view`, `releases.manage`, `environment.switch`, `docs.manage_global`, `docs.manage_governance`, `docs.read_changelog`.

Owner получает полный административный набор. Developer получает только явные grants. Обычный пользователь не видит Admin Panel и не может вызвать административные endpoints напрямую. Чтение и выполнение операций разделены; критические действия дополнительно требуют step-up и audit event.

Старые endpoints сохраняются на переходном этапе, но используют тот же permission resolver. Старые UI entry points скрываются только после server-side и role-contract tests.
