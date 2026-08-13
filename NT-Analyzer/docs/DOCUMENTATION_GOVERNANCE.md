# Documentation Governance — «documentation is part of Definition of Done»

Этот документ обязателен к соблюдению **всеми будущими разработчиками и
AI-агентами** StratForge AI. Он фиксирует, как документация поддерживается в
соответствии с фактическим состоянием продукта.

## 1. Принцип

**Документация — часть Definition of Done.** Задача не считается завершённой,
пока затронутые current-документы не приведены в соответствие с фактическим
состоянием кода. Current-документы всегда описывают продукт **как он есть
сейчас**, а не как он задуман.

## 2. Единая таксономия статусов функций

Каждая пользовательская функция в current-документах имеет **ровно один**
канонический статус:

| Статус | Значение |
|---|---|
| `AVAILABLE` | Реализовано и доступно пользователю сегодня. |
| `BETA` | Доступно, но помечено как незавершённое/экспериментальное. |
| `IN DEVELOPMENT` | В активной разработке; частично в коде, ещё не доступно пользователю. |
| `PLANNED` | Запланировано, кода нет или он не задействован. |
| `EXTERNAL BLOCKED` | Реализация есть, но заблокирована внешним условием (credentials, adapter, разрешение, регуляторика, deployment). |
| `DEPRECATED` | Устарело/удалено; сохраняется только как история. |

Правило точности: если функция присутствует в коде, но выключена gate/флагом —
это `EXTERNAL BLOCKED` или `IN DEVELOPMENT` с явной пометкой **implementation
gap**, а не `PLANNED` и не «будущая стадия продукта». Нельзя маскировать
фактическое состояние формулировками.

## 3. Обязательный workflow при завершении разработки

При завершении любой разработки исполнитель обязан:

1. **Определить затронутые документы** (current, governance, product, legal,
   architecture, а также вкладку «Документы»).
2. **Обновить их одновременно с кодом** в той же задаче/PR.
3. **Выставить/сменить статус функции** по таксономии §2. При завершении
   разработки статус **обязан быть пересмотрен** (например, `IN DEVELOPMENT` →
   `AVAILABLE` / `BETA` / `EXTERNAL BLOCKED` по факту), а не остаться устаревшим.
4. **Убрать устаревшие формулировки** из current-секции.
5. **Перенести историческую информацию** в `changelog`/`archive`, а не оставлять
   несколько противоречащих current-описаний одной функции.
6. **Не допускать** существования нескольких противоречащих current-описаний
   одной функции: у функции один канонический current-источник.

### 3.1. External GPT Context Pack

Канонический внешний пакет находится в `docs/external-gpt-context/` и должен
поддерживаться в том же Definition of Done.

Исполнитель обязан перед Git closeout проверить, изменила ли задача:

- architecture;
- current system state;
- API/schema;
- auth/security;
- environment/release/deployment;
- Connector/market data/trading;
- agents;
- UI product contract;
- documentation/governance/legal status;
- active blockers или roadmap.

Если да, соответствующий файл Context Pack обновляется в **той же задаче/PR**.
Минимум после каждой значимой законченной задачи перепроверяются
`02_CURRENT_SYSTEM_STATE.md` и `11_ACTIVE_WORK_AND_HANDOFF.md`.

После подтверждённого Canary/Production deployment или release acceptance
исполнитель обязан обновить `02_CURRENT_SYSTEM_STATE.md`,
`04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md` и `11_ACTIVE_WORK_AND_HANDOFF.md` в том
же release closeout и зафиксировать exact: `version`, artifact git SHA,
authoritative manifest/archive SHA256 из release evidence, `build ID`,
Canary/Production status, `same_release_dir` при наличии,
`previous`/rollback slot и все `PARTIAL` / `EXTERNAL BLOCKED` пункты.

Если operational release evidence ещё не записано в канонической repo
документации, сначала создаётся/обновляется компактный canonical
release-snapshot / handoff document в `docs/changelog/` или другой уже
утверждённой current/changelog зоне, и только затем обновляется Context Pack.

Даты не переписываются автоматически по всему пакету. Обновляется только тот
документ, чьи факты реально затронуты. Для проверки используется
`python tools/validate_external_gpt_context.py`.

## 4. Разделение current / история / внутреннее

- **Current** (`docs/current/`, `docs/architecture/`, `docs/governance/` rendered,
  product-документы, вкладка «Документы») — только актуальное состояние.
- **История** (`docs/changelog/`, `docs/archive/`) — снимки, closeout-записи,
  Git/PR/CI evidence, устаревшие описания.
- **Внутреннее / owner-only** — amendment log, роли AI-инструментов, технические
  owner-записи, административные журналы, Git/Claude/Codex closeout — не должны
  быть первым содержанием приложения и не показываются обычному пользователю.

## 5. Позиционирование первого документа

Главный первый документ (product overview / `CHARTER` / вкладка «Документы»)
начинается с **цели StratForge AI, назначения платформы, текущих возможностей,
принципов и направления развития**, а не со StartingCapital, комиссий или
owner-процессов. Параметры риска/капитала — раздел для разработчиков стратегий,
ниже.

## 6. Юридические документы

Опубликованные юридические документы **версионируются отдельно** (`docs/legal/`,
собственные `version` + `effective_date`). Их статус **не меняется на
действующий**, пока не закрыты обязательные owner/legal-решения (см.
[legal/README.md](legal/README.md)). В интерфейсе такие документы показываются
как **проекты (DRAFT)**, а не как опубликованные Terms.

## 7. Журнал редакций в пользовательском интерфейсе

- Справа показывается компактная карточка: `Редакция №N`, дата, автор, основание
  и короткое смысловое `Было → Стало`.
- Удалённое значение показывается красным зачёркнутым, новое — зелёным. Полный
  line/code diff, путь файла, version id и внутренние сведения находятся только
  в закрытом по умолчанию блоке `Подробнее`.
- `Редакция №1` означает создание/регистрацию документа и содержит дату,
  фактического автора или AI-инструмент, инициатора и основание. Неизвестная
  историческая атрибуция не заменяется именем владельца.
- Автор не вводится вручную: human определяется authenticated account, AI/dev
  tool — authenticated service account; инициатор фиксируется автоматически.
- Журнал и owner/developer metadata недоступны обычному пользователю ни в UI,
  ни через governance API.

## 8. Ссылки и целостность

Внутренние ссылки не должны ломаться. Перед закрытием задачи прогонять
`python tools/release_static_scan.py --scan markdown` и профильные
documentation-тесты (например, `tests/test_phase10_docs_governance.py`).
Если менялся Context Pack, дополнительно прогонять
`python tools/validate_external_gpt_context.py`.

Этот принцип закреплён также в корневом `AGENTS.md` (раздел Definition of Done).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-11T08:13:16Z | GPT-5.5 через Codex по запросу owner | Закреплены компактный журнал редакций, Revision 1, автоматическая authenticated attribution и запрет раскрытия internal metadata обычному пользователю; история убрана из верха документа.
-->
