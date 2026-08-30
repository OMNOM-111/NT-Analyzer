# ADR-0002: Единая UUID-идентичность пользователя


- Статус: Принято
- Дата решения: 2026-08-01

## Решение

Внутренняя каноническая идентичность пользователя — непрозрачный UUID. Telegram ID, Google subject и нормализованный email являются внешними identities вида `(provider, provider_subject)`, а не primary key пользователя.

Поддерживаемые login providers: Telegram, Google и email. Email OTP/magic link строится через provider abstraction. В Development используется безопасный test backend; Production email login не считается operational до подключения реального transactional provider.

Автоматическое объединение аккаунтов по совпавшему email запрещено. Self-service link/merge требует свежего доказательства владения обоими способами входа. Исключение — audited owner-assisted recovery с причиной и security event.

## Миграция

Только последовательность `expand -> backfill -> dual-write -> cutover -> contract`. Нельзя удалять или терять существующих users, sessions, workspaces, memberships, dialogs, Telegram mappings, Connector identities и audit history. Legacy numeric mapping сохраняется как минимум до отдельного contract gate после restore/rollback evidence.

Каждая стадия обязана быть идемпотентной, иметь backup plan, isolated restore test, обратную совместимость и выключатель новых providers без разрушения уже созданных UUID mappings.
