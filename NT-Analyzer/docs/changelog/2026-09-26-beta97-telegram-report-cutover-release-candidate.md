# beta.97 — единый путь отчётов и SF Chat ↔ Telegram

Release summary: Периодические отчёты владельцу формирует один контроллер Заместителя; SF Chat и Telegram используют одну scoped-беседу, а общий бот имеет ровно одну операционную среду без дублей и повторных model calls.

Release PRs: #294
Affected subsystems: AI Center Vitek Deputy SF Chat SF Social Telegram runtime isolation periodic reports
Release impact: Release candidate; merge, final-main-SHA CI, signed artifact, Canary acceptance and separate Production approval remain required.

Дата: 2026-09-26. Статус функции: **BETA / release candidate**. Инициатор
бизнес-решения: владелец проекта. Реализация: AI-assisted change. Ветка:
`codex/telegram-release-20260926`. Технический checkpoint кода: `73fa31ee`;
итоговый merge SHA, build ID и подписанный artifact фиксируются после merge и CI.

## Решение владельца

Владелец принял текущую Local-версию как основу выпуска; некритичные детали
дизайна вынесены в отдельную последующую работу. Это решение разрешает подготовку
кандидата, но не заменяет обязательные merge-, CI-, Canary- и Production-gates.

## Что обнаружено до исправления

- Периодические сообщения владельцу формировались именно в Local Development:
  отдельный deterministic notifier отправлял daily/weekly/monthly/quarterly
  summary, а Chief/Orchestrator независимо формировал второй модельный отчёт.
  Кроме того, Windows task `StratForge Vitek` держал Local runtime и запускал
  собственные плановые проверки. В сохранённой истории есть оба weekly-отчёта
  2026-09-25 и daily summary 2026-09-26.
- На Canary и Production автоматические Telegram-отчёты были выключены. При этом
  Local, Canary и Production использовали один защищённый bot token; webhook был
  закреплён за Production. Topic registry хранился отдельно в каждой data root,
  поэтому Production не мог безопасно сопоставить ответ теме, созданной Local или
  Canary. Изолированные очереди сами по себе не исключали конкурирующую отправку.
- Секреты не копировались в журнал. Для сверки использовался только необратимый
  fingerprint token; пользовательские переписки, отчёты и прежняя архитектура не
  удалялись.

## Исправленный контракт

Единая цепочка периодического отчёта:

`Пользователь → Заместитель (контроллер Витёк) → Марина/Orchestrator → тот же SF Chat → привязанная тема Telegram`.

- Только Vitek владеет расписанием: daily 16:00 PT, weekly Friday 16:05,
  monthly on the last day 16:10, quarterly on the last day 16:15 and scheduled
  audit 16:20. Отчёт строится только для owner workspace и только при включённой
  категории уведомлений.
- Stable report/request key сохраняет один SF Chat result, один Telegram delivery
  и один model result; повторный цикл или retry не создаёт новый вызов модели,
  дубль сообщения или параллельный отчёт.
- По умолчанию Production — единственный operational owner общего Telegram-бота.
  Development и Canary сохраняют login/access callbacks, но не создают темы, не
  зеркалируют чат, не poll-ят updates и не отправляют отчёты. Override требует
  точного явного назначения среды; Development дополнительно сохраняет прежний
  owner-only safety gate.
- Conversation mapping остаётся scoped по `user_id + workspace_id +
  conversation_id`; неизвестная тема отвергается, а durable inbox/outbox и
  message/update dedupe переживают перезапуск. Старые сообщения и registry не
  очищаются.

## Затронутые подсистемы

- AI Center / Deputy duty bridge и Vitek controller;
- SF Chat conversation history и durable delivery;
- Telegram webhook/polling/topic ownership;
- periodic operational and financial reports;
- runtime environment isolation and release configuration.

SF Social остаётся discovery/publication surface и не получает параллельное
хранилище личных сообщений. Диалоги продолжают принадлежать SF Chat.

## Проверки кандидата

- До изменения: 306 связанных тестов PASS.
- После изменения: 530 связанных тестов PASS; исправленный release-date contract
  1 PASS. Полная локальная регрессия на `f455043f`: **6087 PASS / 134 skipped /
  0 failed** за 1:07:38.
- `python tools/pre_release_check.py`: PASS для 650-файлового production bundle
  (static scan внутри bundle, runtime reads, Python compile, shipped JavaScript).
  `python tools/validate_external_gpt_context.py`, embedded timeline JavaScript
  syntax и `git diff --check`: PASS.
- PR #294: Static gates, bridge build и Ubuntu CI PASS; Windows и полный
  `python-tests` были ещё активны на момент этого checkpoint. CI итогового merge
  SHA, signed artifact и Canary acceptance выполняются только после отдельного
  решения владельца о merge. HTTP 200 или конфигурация сами по себе не считаются
  приемкой Telegram.
- Реальный короткий exchange выполняется только в обозначенном owner test dialog:
  один outbound, один ручной ответ владельца, один ответ системы. Массовая
  рассылка запрещена.

## Release impact и незакрытые gates

- Candidate version: `0.10.0-beta.97`.
- Current live Canary/Production до выпуска: `0.10.0-beta.92`, source
  `9d800770d08e0072ec453c2611e98726e295b2e4`, build
  `sf-0.10.0-beta.92-9d800770d08e-20260902T035324Z`, runtime artifact SHA256
  `07A3961277E3879357EE92A8471911FAFA4B57E1B3BF2D046E1BCA41D27A9169`.
- До merge требуется успешный PR и отдельное решение владельца о merge.
- После merge обязателен CI на итоговом `main` SHA, один подписанный immutable
  artifact и резервная копия/проверяемый rollback перед server data changes.
- Production approval запрашивается отдельно и только после Canary PASS для
  конкретной immutable artifact identity.

На этом checkpoint: **IMPLEMENTATION COMPLETE — pending final verification**;
**GIT CLOSEOUT IN PROGRESS**; **STAGE NOT CLOSED**.
