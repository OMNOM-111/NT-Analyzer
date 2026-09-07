# Agent World — сохранение WIP механизмов, без активации Local

Status: **IN DEVELOPMENT**. Business requester: owner. AI-assisted change.
Release impact: checkpoint незавершённого кода, **не release candidate**.
Version: `0.10.0-beta.96`, без изменения.

## Точная исходная точка и владение

- Ветка: `codex/agent-world-mechanisms`.
- Parent: `45ab4361d5ab9b8422ec049c0c689953d548a318`.
- Checkpoint: commit, впервые добавивший этот документ; точный SHA записывается
  следующим handoff-коммитом, без amend и без изменения сохранённого снимка.
- Защищённый Local: `http://127.0.0.1:8765/ui/ai-command-center.html`,
  clean detached `2b6d0112bef88c5bfb73970de64ec5518443e56b`.
  Не перезапускался и не переключался; рабочие данные не изменялись.
- Сохранены только изменения собственной команды в отдельном mechanisms
  worktree. Staged до подготовки checkpoint был пуст. Runtime/caches,
  `.artifacts/`, credentials, базы, логи и результаты тестов в Git не добавлены.
- PR #282/#283, их base, ветка и тестовые материалы независимого reviewer
  не изменены. No merge, deploy, миграции рабочей БД, внешние платные вызовы
  или торговые действия.

## Состав сохранённой реализации

| Механизм | Что уже записано в коде | Граница готовности |
| --- | --- | --- |
| PostgreSQL / RLS | Новый repository, миграция 0023, 10 FORCE RLS таблиц, CAS/artifacts/inbox/outbox/Memory grants, explicit factory | Disposable SQL acceptance есть; новый путь не активирован на Local, миграции рабочих данных нет |
| Router V2 | Same-class scoped candidates, отдельные shadow/active flags, pricing/budget checks | Pure selector; актуальная application routing integration ещё не завершена |
| Execution V2 / Deviation | Отдельный immutable controller, fixed scope, existing worker claims, uncertain-response fence, application receipt guard | Focused fixture evidence есть; общая integration acceptance не закончена |
| Ограниченное делегирование | Typed source proof, finite tree depth <=3, fanout <=2, existing model queue | Нет законченного live approval/start/watch flow |
| Расписание | Finite occurrences, DST validation, due/missed/cancel/idempotency | Нет законченного автономного recovery/watch loop |
| Automation authority | Existing Decision approval + capabilities/device/budget recheck; SERVICE on behalf of human | Security review и actual grant-to-worker tests ещё не завершены |
| Статусы / ручная проверка | task_presentation/task_review и начатые общие DTO/SF Chat/UI изменения | Сохранены как WIP; новые UI и presentation объединения заморожены до согласования review |

Новые flags по умолчанию OFF: `AI_ROUTER_SHADOW_V2`, `AI_ROUTER_V2`,
`AI_EXECUTION_V2`, `AI_DELEGATION_V2`, `AI_SCHEDULER_V1`. Последние два
зависят от Execution V2. Новая capability `ai_automation` также default OFF,
включая owner; никакому реальному пользователю её не выдавали.
`STRATFORGE_AGENT_WORLD_LOCAL_MECHANISMS` — новый незавершённый
server-only exact environment/workspace opt-in, не UI grant.
Обычный repository остаётся SQLite. PostgreSQL требует отдельного
`STRATFORGE_AGENT_WORLD_DATABASE_URL`; Production DSN fallback отсутствует.

## Проверки: разные источники не объединяются

| Evidence | Результат | Что это доказывает |
| --- | --- | --- |
| Protected Local 2b6d0112, исторический full suite | 4235 PASS / 44 skipped | Только прежний checkpoint, не этот WIP |
| Исторические PostgreSQL acceptance до новых AW таблиц | 41 PASS | Stage 8 / SF Chat, не Agent World RLS |
| Новая disposable PG 17.11 TLS, 2026-09-05 | 69 PASS / 0 skipped, 97.59 s | Новые AW repository/RLS реальные SQL на synthetic fixtures |
| Существующие PG suites на той же новой disposable БД | 41 PASS / 0 skipped, 131.80 s | Совместимость существующих migrations/storage/worker/Chat |
| Новые AW PG tests без disposable DSN | 1 PASS / 68 skipped | Не PostgreSQL acceptance |
| Scoped Execution V2 final | 46 PASS, 123.77 s | Synthetic transport, real disposable queues/claims; не live provider |
| Earlier combined Execution/domain/models | 272 PASS, 302.32 s | Предшествующий scoped снимок, не весь текущий WIP |
| Самая свежая UI/permissions попытка 2026-09-06 | **3 FAIL / 88 PASS**, остановка maxfail=3 | Три UI contract расхождения перечислены ниже, permissions не полностью выполнен |
| Reviewer isolated WIP report, по сообщению owner | 113 PASS / 68 skipped | Предварительный чужой frozen snapshot; не full acceptance этого checkpoint |
| Full pytest на точном новом checkpoint | **NOT RUN** | Не ждём длительного прогона для сохранения WIP |
| Staged pre-release bundle | **PASS**, 556 файлов | Static/runtime reads/Python/JS gates; не функциональная приёмка |
| Root static, Context Pack, JS syntax, diff check | **PASS** | Короткие защитные проверки перед checkpoint |
| Browser E2E нового кода / model quality / owner visual | **NOT VERIFIED / NOT ACCEPTED** | Контрольный Local не заменён новым кодом |

PG receipt хранится локально в ignored
`.artifacts/agent-world-postgres-20260905/acceptance-evidence.json`.
Migration 0023 SHA256:
`c0c9fc74633581cabe1a8dd77d33b33368be6dd5fb00b19d02ad351757c838d7`.
JUnit hashes: new AW
`cfffebbb847e305794f0f28714aa417aa0a029d2a54f7774f7f47bd2da43afb3`;
existing PG
`b436bb4e558eba7590b8b526001362c9ad5192d9b450df0562baf8661e52faf9`.
Это не ключи/DSN и не результаты модели.

## Известные проблемы и следующий безопасный шаг

1. Gateway содержит начатые вызовы ещё отсутствующего
   `mechanism_gateway` для delegation/schedules/routing и automation_watch.
   Двухшаговые propose/approve/start и durable recovery не готовы.
   Нельзя включать новые механизмы на рабочем Local.
2. Automation authority review выявил недостаточные bindings
   chat_scope/RequestContext/approval Intent/Decision; начатые guards также
   включены в checkpoint, но реальные disposable auth/device/worker tests
   ещё не завершены. Это не подтверждённое закрытие security review.
3. Начато разделение provider plan и прикладного результата; raw succeeded
   сам по себе не доказывает проверку. V2 deviation/manual acceptance и
   race accept/reject имеют частичные guards, но требуют regression tests.
4. UI failures:
   `test_canonical_ready_tasks_remain_visible_as_queued_in_active_and_waiting_views`;
   `test_compact_overview_boots_without_hidden_tab_nodes_or_extra_api_requests`;
   `test_source_does_not_invent_quality_ranks_or_execute_risky_actions`.
   Причины: ready отсутствует в waiting-filter, изменён показ n, изменён
   ожидаемый текст ограничения. Не ослаблять тесты ради формального PASS.
5. Existing owner-all-capabilities tests могут требовать отдельного ожидания
   для новой default-OFF `ai_automation`; полный permissions run не завершён.
6. Реальные модели, live BYOK, multi-human Memory и постоянная Social
   публикация не пройдены этим WIP. Регистрацию, ключ и конкретное постоянное
   опубликование оставляет за собой owner.
7. Статистика diagnostics / real application / explicit human review ещё
   не сведена окончательно. Три json_arithmetic PASS не означают 100% качества.

**Следующая операция после checkpoint:** scoped security tests
automation_authority и fail-closed backend integration на disposable данных.
Новые backend исправления — отдельными commits. До сверки review не менять
UI, `ui.js`, не объединять `presentation.py` с
`task_presentation.py`/`task_review.py`.

## Координация с независимым review

Read-only проверка PR #283 показала remote head
`84115efcccbab2196dc444ed978fe5a05f728b06`; локальная review ветка уже
`c468b14f`, а `test_aurora_shell_boot_visibility.py` untracked.
Поэтому его ранний CI не приписывается более поздним изменениям.
Handoff прочитан как дополняющийся review, не как команда переносить PR.

Фоновая Aurora загрузка через requestAnimationFrame-only воспроизведена
reviewer; его regression надо учесть при согласованной интеграции.
Наш `ui.js` сохраняется без нового исправления этой области.

Точное совпадение с независимой 33-file frozen copy **не установлено**:
её manifest/path ещё не получен. Количество файлов не доказывает равенство.
После возобновления наша команда успела изменить backend opt-in в
`live_gateway.py` и gateway hooks; они сохраняются, а не откатываются
к чужому снимку. Exact собственный Git tree позволяет сравнить это позже.

## Rollback / stop point

Рабочий Local остаётся прежней контрольной версией, поэтому возвращать его
не требуется. Parent `45ab4361` — исходная точка code-only сравнения.
Никаких reset/delete/обратных миграций не выполнять. Сохранить историю задач,
ошибок и исходные результаты. При прерывании начать с этого документа и
`git status`, а не с повторного общего аудита.

IMPLEMENTATION COMPLETE: NO. GIT CHECKPOINT: prepared with short local gates;
full functional verification pending. GIT/CI CLOSEOUT: pending. STAGE CLOSED: NO. DESIGN ACCEPTANCE:
PENDING OWNER ACCEPTANCE.
