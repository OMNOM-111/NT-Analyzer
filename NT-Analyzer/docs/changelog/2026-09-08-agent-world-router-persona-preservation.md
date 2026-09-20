# Router: исходная Persona отдельно от модели-исполнителя

Статус: IN DEVELOPMENT до интеграционного checkpoint и owner acceptance.
Исходный snapshot: `a03ec82b686a9f6f05c056fe5a500ecbdb3babac`.
Ветка: `codex/agent-world-unified-acceptance`; новый SHA назначает общий
интеграционный checkpoint, текущая запись не означает commit или release.

## Изменение

Router больше не подменяет личность исходного агента Persona, привязанной к
выбранной модели. Новый server-issued preview v2 связывает immutable refs
исходной Persona и Agent Role, исходное отображаемое имя, исходный Task,
его revision/checkpoint и показанный выбор модели. Явное применение использует
тот же preview; поля пользовательского action payload не изменены.

В Task сохраняются отдельно `speaking_identity` / `persona_id` и
`executor_persona_id` / `model_id` / Provider Account. Артефакты аватара,
voice/style и остальные Persona-настройки Router не изменяет. Обычные задания,
включая назначенных Coordinator специалистов, не получают Persona предыдущего
Router root: их existing ingress не изменён.

Новая preview/apply/transmit проверка требует текущие active Persona/Role
в том же user/workspace scope и точные revisions. Изменение после показа
останавливает новую работу и требует нового preview. Самовольного client
Persona/Role override нет. Execution V2 фиксирует отдельно speaking/executor
identity в approval и проверяет её перед исполнением и при наблюдении receipt.

Старые v1 snapshots/checkpoints читаются без переписывания истории и без
утверждения, что Persona была сохранена (`persona_preserved = null`). Новый
вызов по v1 preview не допускается. Новый routed результат показывает исходную
личность, фактическую модель/исполнителя и остаётся ожидающим человеческой
проверки; diagnostic checks не считаются профессиональным качеством.

## Проверки и ограничения

- Совместный disposable regression: **201 PASS / 0 failed / 0 skips**, 342.87 s:
  `test_agent_world_models`, `test_agent_world_router_v2`,
  `test_agent_world_mechanism_domains`, `test_agent_world_execution_v2`,
  `test_agent_world_router_persona` (16 новых сценариев в последнем файле).
- `test_agent_world_persona_roles`: **21 PASS / 0 failed / 0 skips**, 3.73 s.
  Четыре старых SimpleNamespace doubles дополнены настоящим scoped `_all`
  iterator поверх той же disposable repository для нового aggregate read;
  существующие assertions ролей, истории и отдельной оценки не ослаблялись.
- Покрыты изменение Persona между preview/apply и apply/transmit, client/foreign
  override, изменение speaking checkpoint/role, исторический read после смены
  имени/флагов, replay без повторного модельного вызова, сохранность настроек.
- Ordinary user/device → issued preview → explicit apply → existing durable
  worker → Execution V2 → response → pending human review выполнен с локальным
  transport double. Это проверка приложения, **не реальный ответ модели и не
  model-quality evidence**.
- Python compilation и scoped `git diff --check`: PASS.
- Immutable full regression исходного `a03ec82b`: **5124 passed / 12 failed /
  112 skipped**, 3187.56 s; legacy runner **13/13 PASS**, 67.375 s. Он не
  засчитывается как full PASS нового WIP. Его 68 Agent World PostgreSQL skips
  отделены от 41 старого PostgreSQL skip и 3 платформенных skips; отдельный
  PostgreSQL acceptance не подменяется данным прогоном.

Затронуты Router, private model task ingress/read projection, Execution V2.
Auth, approvals, application/NinjaTrader evidence, budgets, jobs и capabilities
не расширены. Default/защитные flags не включены. Local 8765, рабочие данные,
owner secrets, Production/Canary не менялись. Merge/deploy/release не выполнялись.

Current implementation status и External GPT Context Pack (`02`/`11`) должны
сослаться на этот bounded delta в том же общем интеграционном checkpoint.
