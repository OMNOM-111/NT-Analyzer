# ADR-0001: Окружения и идентичность сборки

История поправки: 2026-08-02T00:53:55Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 0 — утвердить модель Development, Canary, Production и release metadata.

- Статус: Принято
- Дата решения: 2026-08-01

## Решение

StratForge остаётся одной кодовой базой, но имеет три самостоятельных deployment environment: `development`, `canary`, `production`. Каноническая переменная — `DEPLOYMENT_ENV`; существующий `STRATFORGE_ENV` сохраняется как переходный alias. Если обе переменные заданы и различаются, startup завершается fail-closed.

Release channel — отдельная ось: `dev`, `beta`, `stable`. Git branch, SemVer, deployment environment и release status не подменяют друг друга.

Полная build identity содержит:

- `version` (SemVer);
- `deployment_environment`;
- `release_channel`;
- `build_id`, `git_commit_sha`, `artifact_sha256`;
- `build_date` и признак `dirty`.

Development может быть dirty и показывает `DEV · v... · dirty`. Canary показывает `CANARY · v...`. Публичный Production с beta-версией показывает `BETA · v...`; stable Production показывает только версию без надписи `STABLE`.

## Изоляция

Development, Canary и Production не разделяют writable database/role, secrets, directories, ports, queues, storage namespaces, cookies, CSRF keys, local-storage namespaces, Telegram configuration, updates или Connector sessions. Canary проектируется на том же Linux-сервере отдельными сервисами; отсутствие явной конфигурации закрывает запуск.

## Совместимость и проверка

Переходный alias удаляется только отдельным contract-решением. Негативные тесты обязаны проверять конфликт переменных и пересечение namespace. Phase 0 не меняет runtime.
