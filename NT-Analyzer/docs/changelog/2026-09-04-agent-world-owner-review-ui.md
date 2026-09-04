# AI Центр — интерфейс локальной проверки владельца

## Назначение изменения

Добавлен нативный Aurora-интерфейс AI Центра для объединённого просмотра
задач, Persona, измеренных оценок и артефактов. Визуальная композиция следует
согласованным эскизам: работа, команда и требующие внимания события на обзоре,
подробности доступны в Task Inspector и профиле агента.

Статус функции: **IN DEVELOPMENT** до подключения facade, разрешённых
workspace-флагов и интеграционной проверки. Это не Canary/Production release.

## Пользовательские изменения

- Восемь локальных разделов, адаптивная компоновка, клавиатурная навигация,
  состояния загрузки, отсутствующих данных, ошибок и недостаточного доступа.
- Задачи с фильтрами, наблюдаемой активностью, проверками, результатами и
  scoped-артефактами. Нет публикации скрытой цепочки рассуждений модели.
- Отдельные Persona, Agent Role и Model. Проверочный рейтинг показывает
  размер выборки и уверенность; недостаточная выборка обозначена NEW.
- Локальные synthetic-задачи запускаются только по явному разрешению backend.
  Synthetic benchmark не называется оценкой качества внешней модели.
- Результат открывается в существующем SF Chat. SVG-график по явному клику
  растеризуется браузером в PNG и передаётся серверу для проверки и сохранения.
- Выключенные высокорисковые разделы не имитируют Court или торговые решения.
  Существующие исследования, подключения и настройки голосов не удалены.

## Scope и сохранённые границы

Изменены только новые `ai-command-center.html`, page-scoped CSS/JavaScript,
новые UI contract tests и эта запись. Общие `ui.js`, `api.js`, навигация,
server-side facade, permissions, реестр флагов и контекст-пакет интегрируются
в основной ветке задачи. Auth, Device Confirmation, SF Social, SF Chat stores,
Charts engine, Connector и торговое исполнение этим UI-slice не изменены.

Никакие credentials, cookies, runtime state или generated governance output
не включены в commit. Нет новой frontend-системы авторизации или хранения чата.

## Исходная точка и closeout

- Base SHA: `d5d07ac6817cd10f57d916dab0ce655347a8cbde`.
- Рабочая ветка UI-slice: `codex/agent-world-ui`.
- Интеграционная ветка: `codex/agent-world-owner-preview`; UI-slice передаётся
  туда отдельным commit, не добавляется в PR #280 или PR #281.
- Версия Local остаётся `0.10.0-beta.96`.
- Source commit, интеграционные проверки, PR и owner visual acceptance
  фиксируются основным change record этого implementation slice.

## Проверки и release impact

Проверки этого slice: `python -m pytest -q tests/test_agent_world_ui.py` —
**47 passed** (executable Node presentation contracts, HTML/CSP/assets,
keyboard/accessibility contracts, scope/URL validation и PNG rasterization).
`node --check`, Python compilation test-файла и `git diff --check` — **PASS**.
Полная регрессия, bundle/static/context gates и браузерная проверка проводятся
после подключения backend основной задачей; этот результат их не заменяет.

К публикации здесь ничего не подготовлено. Merge, artifact signing,
Canary/Production deployment и изменение версии не выполнялись.
External GPT Context Pack затронут; его current-state/UI/agents/handoff
изменения принадлежат основному интеграционному исполнителю этой же задачи.
