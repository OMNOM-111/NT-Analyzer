# Release Governance Policy

## Единственный разрешённый конвейер

Любое изменение юридических документов, UI, кода или инфраструктуры проходит:

`локальная проверка → тесты → чистый Git → CI → один подписанный immutable artifact → Canary → acceptance → тот же artifact в Production`.

## Обязательные ограничения

- Artifact собирается только из точного чистого Git commit после успешного CI.
- Canary и Production получают один и тот же archive, manifest, подпись, SHA-256
  и build ID без rebuild.
- Canary acceptance проверяет код, UI/static assets, backend, документы и
  затронутые функции.
- Production promotion разрешён только после Canary PASS.
- Любое изменение после сборки начинает новый цикл с нового commit и artifact.
- Ручные hotfix-копии, частичный deploy и обход этапов запрещены.
- Release closeout фиксирует Git SHA, build ID, archive/manifest SHA-256,
  release directory, Canary/Production status и rollback target.
