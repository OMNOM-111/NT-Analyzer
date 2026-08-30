# ADR-0005: Immutable artifact и promotion без пересборки


- Статус: Принято
- Дата решения: 2026-08-01

## Решение

Release candidate создаётся из чистого commit и один раз собирается в immutable artifact с manifest, signature, SHA-256, build ID, test/SBOM evidence. В Canary и Production разворачивается один и тот же artifact; promotion при несовпадении checksum или build ID запрещён.

Release Center хранит candidates, deployments, checks, approvals и rollbacks как auditable state machine. `BLOCKED` и `NOT RUN` никогда не трактуются как `PASS`.

Blue-green строится поверх существующей systemd/current-release symlink архитектуры. Переключение выполняется только после health/readiness; rollback возвращает предыдущий уже проверенный artifact. Branch, version, environment и channel остаются разными полями.

## Approval boundary

Текущая программа разрабатывает и тестирует tooling локально, но не выполняет Canary/Production deployment, DNS/Cloudflare changes, Production migrations или secrets changes. Production promotion, rollback и merge integration branch в `main` требуют отдельного разрешения owner.
