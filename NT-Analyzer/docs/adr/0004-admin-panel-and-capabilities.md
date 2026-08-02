# ADR-0004: Admin Panel и capability permissions

История поправки: 2026-08-02T03:06:47Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 2 — уточнить реализованный capability catalog, expiring grants и переходную security boundary.

История поправки: 2026-08-02T00:53:55Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 0 — утвердить административную границу и server-side authorization.

- Статус: Принято
- Дата решения: 2026-08-01

## Решение

Системные функции переносятся из пользовательского меню и cabinet tabs в отдельную оболочку Admin Panel. Скрытие UI не является авторизацией: каждый API endpoint проверяет capability на сервере.

Реализованный каталог capabilities: `admin.view`, `users.manage`, `workspaces.manage`, `connectors.manage`, `operations.view`, `operations.execute`, `releases.view`, `releases.create`, `releases.deploy_canary`, `releases.promote_production`, `releases.rollback_production`, `environment.switch`, `docs.manage_global`, `docs.manage_workspace`.

Owner получает полный административный набор. Developer получает только явные structured grants с необязательным будущим UTC expiry. Тариф, promo и product permission не выдают административный доступ. Невалидный, истёкший или legacy-unstructured grant закрывается fail closed. Обычный пользователь не видит Admin Panel и не может вызвать административные endpoints напрямую. Чтение и выполнение операций разделены.

В Phase 2 критические действия защищены server-side capability, CSRF, существующим audit trail и явным UI confirmation. Обязательный trusted-device step-up добавляется в Phase 4; до этого фактические release deploy/promote/rollback workflows не реализуются и не должны считаться доступными только из-за наличия capability ID.

Старые endpoints сохраняются на переходном этапе, но используют тот же permission resolver. Старые UI entry points скрываются только после server-side и role-contract tests.

## Статус реализации Phase 2

- Личный кабинет отделён от Admin Panel; системные операции удалены из three-dot menu и cabinet tabs.
- Admin Panel получает только server-filtered modules, разрешённые эффективными capabilities.
- Environment Switcher не меняет backend текущей вкладки: отдельный origin открывается в новой вкладке без переноса credentials или browser storage; Local DEV требует loopback identity probe.
- Release Center, trusted-device step-up и реальные Canary/Production workflows остаются следующими фазами.
