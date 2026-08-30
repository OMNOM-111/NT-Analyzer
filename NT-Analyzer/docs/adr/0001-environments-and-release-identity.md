# ADR-0001: Окружения и идентичность сборки



- Статус: Принято
- Дата решения: 2026-08-01

## Решение

StratForge остаётся одной кодовой базой, но имеет три самостоятельных deployment environment: `development`, `canary`, `production`. Каноническая переменная — `DEPLOYMENT_ENV`; существующий `STRATFORGE_ENV` сохраняется как переходный alias. Если обе переменные заданы и различаются, startup завершается fail-closed.

Release channel — отдельная ось: `dev`, `beta`, `stable`. Git branch, SemVer, deployment environment и release status не подменяют друг друга.

Полная build identity содержит:

- `app_version` (SemVer);
- `deployment_environment`;
- `release_channel`;
- `build_id`, `git_commit_sha`, `artifact_sha256`;
- `build_timestamp_utc` и признак `dirty`.

Development может быть dirty и показывает `DEV · v... · dirty`. Canary показывает `CANARY · v...`. Публичный Production с beta-версией показывает `BETA · v...`; stable Production показывает только версию без надписи `STABLE`.

## Изоляция

Development, Canary и Production не разделяют writable database/role, secrets, directories, ports, queues, storage namespaces, cookies, CSRF keys, local-storage namespaces, Telegram configuration, updates или Connector sessions. Canary проектируется на том же Linux-сервере отдельными сервисами; отсутствие явной конфигурации закрывает запуск.

## Совместимость и проверка

Переходный alias удаляется только отдельным contract-решением. Негативные тесты обязаны проверять конфликт переменных и пересечение namespace. Phase 0 не меняет runtime.

## Реализация Phase 1

Runtime принимает `DEPLOYMENT_ENV=development|canary|production` и `RELEASE_CHANNEL=dev|beta|stable`; прежние `STRATFORGE_*` имена остаются проверяемыми aliases. Canary и Production требуют полный build identity, `DIRTY=0`, HTTPS origin, явные resource identities и отдельный data root. Development получает Git SHA и dirty-state непосредственно из checkout; отсутствие artifact checksum в source-run выражается пустым значением, а не вымышленным hash.

Immutable server artifact не содержит целевое deployment environment: один и тот же подписанный пакет допускает продвижение `canary → production`. SHA-256 самого ZIP хранится в detached checksum/build report и передаётся запущенному deployment через `ARTIFACT_SHA256`, поскольку архив не может содержать собственный итоговый hash без циклической зависимости.
