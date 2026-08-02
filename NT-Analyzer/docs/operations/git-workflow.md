# Git workflow

История поправки: 2026-08-01T23:47:37Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Stage 10 Repository Hygiene Closeout.

## Назначение

Этот workflow фиксирует минимальный порядок Git-работы для задач StratForge/NT-Analyzer. Он отделяет реализацию, Git closeout, PR и Production-подтверждение.

## Обязательные правила

1. Работать в task branch. Не коммитить напрямую в `main`.
2. Перед stage выполнить `git status --short --branch` и классифицировать все tracked/untracked изменения.
3. Не использовать слепой `git add -A`. Stage делать только точными путями, которые входят в scope задачи.
4. Runtime state, локальные telemetry/log/registry файлы, rollback bundles и временные архивы не коммитить в обычную историю.
5. Если runtime-файл уже tracked и owner разрешил cleanup, использовать `git rm --cached` и затем проверить, что локальный файл остался на диске.
6. Generated governance output коммитить только вместе с каноническим source-of-truth и changelog/amendment evidence. Date-only output без такого evidence восстанавливать к HEAD.
7. Каждый закрытый stage должен иметь commit SHA, ветку, PR URL, проверенный статус working tree и список проверок с результатом.
8. После scoped-commit автоматически пушить task branch и создать или обновить PR, если это не merge, не release и не Production action.
9. Перед merge задавать owner ровно один вопрос о слиянии.
10. Production/Canary deployment, release, Production secrets/server/DB и необратимые миграции требуют отдельного явного подтверждения owner.

## Closeout labels

- `IMPLEMENTATION COMPLETE` - scoped changes внесены, локальные проверки для scope выполнены или честно помечены blocked.
- `GIT CLOSEOUT COMPLETE` - intentional files committed, task branch pushed, PR created/updated, CI inspected, dirty state объяснён.
- `STAGE CLOSED` - owner-approved integration decision выполнен или owner явно закрыл stage без merge.

Эти labels нельзя ставить по одному только локальному diff или без результатов проверок.
