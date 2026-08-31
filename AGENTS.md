# Обязательные правила стабильности Codex

## Использование встроенного браузера в этом workspace

- По умолчанию не запускать Codex in-app browser / Browser skill / `agent.browsers` / browser-client для открытия и проверки локальных страниц этого проекта.
- Исключение: если пользователь явно просит запустить браузер или провести визуальную проверку, запустить встроенный браузер для проверки. Такое явное поручение считается разрешением на повторную проверку; отдельное подтверждение обновления Codex не требуется.
- Причина: 13 июля 2026 года открытие локальной страницы через встроенный браузер несколько раз приводило к зависанию или закрытию Codex. Windows ранее зарегистрировал это как `AppHangTransient` для `ChatGPT.exe`; backend проекта при этом продолжал работать.
- Для проверки интерфейса использовать безопасный путь без GUI: прямые HTTP-запросы, тестовый HTTP-клиент, DOM/HTML-контрактные тесты, `node --check`, `python -m py_compile` и `pytest`.
- Если нужна именно визуальная ручная проверка без явного поручения пользователя, сообщить точный локальный URL и попросить пользователя открыть его самостоятельно. Не открывать браузер автоматически.

Это ограничение важнее обычного требования выполнять браузерную QA-проверку и действует для всех вложенных каталогов workspace.

## Закрытие задач и Git hygiene

- Не использовать слепой `git add -A`. Перед stage/commit классифицировать tracked, untracked и ignored изменения: код, документация, runtime data, generated output, локальные архивы, rollback/artifact файлы.
- Runtime state, локальные telemetry/log/registry файлы, временные архивы и rollback bundles не должны попадать в обычную историю Git. Если такие файлы уже tracked, снимать их с индекса только через `git rm --cached` с сохранением локального файла на диске и с owner-approved scope.
- Generated governance output можно коммитить только вместе с каноническим source-of-truth и changelog/amendment evidence. Date-only rendered noise без такого evidence надо восстанавливать к HEAD.
- После реализации scoped-задачи автоматически пушить task branch и создать или обновить PR, если это не main, не merge, не release, не deployment, не Production secrets/server/DB и не необратимая миграция.
- Merge, прямые изменения main, Production/Canary deployment, release и любые действия с Production secrets/server/DB требуют отдельного явного подтверждения owner.
- Закрытый этап должен иметь commit SHA, branch, PR URL, проверенный `git status`, результаты тестов/статических проверок и явное разделение `IMPLEMENTATION COMPLETE`, `GIT CLOSEOUT COMPLETE`, `STAGE CLOSED`.
- Перед merge задавать owner ровно один вопрос о слиянии. Production readiness или Production confirmation всегда отдельны от вопроса о merge.

## Обязательный release contract DEV → CANARY → PRODUCTION

- Единственная разрешённая схема обновления StratForge: `DEV → clean Git commit → one signed immutable artifact → CANARY acceptance → same exact artifact → PRODUCTION`.
- DEV — локальный источник готового релиза. Если в локальном working tree есть полезные изменения относительно HEAD, сначала сохранить их в Git, протестировать и строить artifact только из этого итогового commit. Нельзя считать старый или dirty DEV равным релизу без классификации `git status`/diff.
- CANARY и PRODUCTION должны получать один и тот же artifact без rebuild, изменения файлов, ручных hotfix-копий или изменения кода между средами. Различаться могут только environment-specific DB, secrets, sessions, cookies, origins, runtime config и изолированные state/artifact roots.
- CANARY acceptance должна доказать тот же код, UI/static assets, backend logic, Documents, Charts и функции, что и DEV. После PASS в CANARY Production promotion — только переключение того же artifact.
- Любое новое изменение после Canary acceptance начинает цикл заново: новый commit, новый immutable artifact, новый CANARY, затем PRODUCTION. Запрещены отдельная Production-версия, частичный deploy и «быстрый» hotfix поверх уже проверенного artifact.
- Перед любым release/deploy closeout обязательно фиксировать exact identity: Git SHA, build id, archive SHA256, manifest/runtime artifact SHA256, release dir, Canary/Production symlink targets, readiness/live status и результаты проверок.

## AI Provenance Policy

- AI никогда не указывает и не угадывает собственное название, версию модели или среду выполнения.
- Эти метаданные могут появляться только из доверенного infrastructure/runtime context. Если инфраструктура их не предоставила, поля отсутствуют или содержат нейтральное `AI-assisted change` без выдуманной идентичности.
- Нельзя наследовать подпись модели из предыдущей редакции, prompt, шаблона или текста документа.
- История изменений хранится в структурированном `NT-Analyzer/data/governance/change_log.jsonl`; скрытые amendment-комментарии в Markdown запрещены.
- Requester/инициатор бизнес-решения и authenticated human/service actor фиксируются раздельно. AI не подменяет владельца как автора решения.
- Любой repository-wide governance/security/provenance scan запускается **от корня репозитория**, а не из `NT-Analyzer/` или другого подкаталога. Скан из подкаталога не считается доказательством отсутствия находок: он физически не видит tracked-файлы выше по дереву (например корневой `README.md`) и даёт ложный PASS на release-блокере.
- Перед PR/release, затрагивающим состав artifact, runtime-чтения или документы, запускается `python tools/pre_release_check.py`. Он собирает точный production-состав и выполняет `release_static_scan` **внутри bundle**, как это делает signing node. Repository-wide PASS не является доказательством: в checkout существуют файлы, которых в artifact нет, поэтому ссылки и runtime-зависимости резолвятся локально и падают на сборке.

## Definition of Done: документация — часть выполненной работы

- Документация — часть Definition of Done. Задача не закрыта, пока затронутые current-документы не приведены в соответствие с фактическим кодом. Полное правило: `NT-Analyzer/docs/DOCUMENTATION_GOVERNANCE.md`.
- У каждой пользовательской функции в current-документах ровно один канонический статус: `AVAILABLE` / `BETA` / `IN DEVELOPMENT` / `PLANNED` / `EXTERNAL BLOCKED` / `DEPRECATED`. Реализованная, но выключенная gate/флагом функция — это `EXTERNAL BLOCKED` или `IN DEVELOPMENT` с явной пометкой implementation gap, а не «будущая стадия продукта». Не маскировать фактическое состояние формулировками.
- При завершении любой разработки: определить затронутые документы, обновить их одновременно с кодом, сменить статус функции, убрать устаревшие формулировки из current-секции, перенести историческое в `changelog`/`archive`. Нельзя оставлять несколько противоречащих current-описаний одной функции.
- Главный первый документ (product overview / `CHARTER` / вкладка «Документы») начинается с цели, назначения, текущих возможностей, принципов и направления StratForge AI, а не со StartingCapital/комиссий/owner-процессов. Amendment log, роли AI-инструментов, технические owner-записи и Git/Claude/Codex closeout — только owner/developer и в самом конце, не как первое содержание приложения.
- Опубликованные юридические документы версионируются отдельно (`NT-Analyzer/docs/legal/`) и показываются в соответствии с текущим публичным статусом реестра. Owner-only реквизиты не регистрируются и не выдаются через публичные API.

## External GPT Context Pack

- Канонический upload-пакет для внешних моделей без доступа к репозиторию хранится в `NT-Analyzer/docs/external-gpt-context/`.
- Перед Git closeout каждый AI developer (Codex/GPT/Grok/Claude/Cursor/иная модель) обязан проверить, затронула ли задача External GPT Context Pack.
- Если задача изменила architecture, current system state, API/schema, auth/security, environment/release/deployment, Connector/market data/trading, agents, UI product contract, documentation/governance/legal status, active blockers или roadmap, соответствующий файл Context Pack обновляется в той же задаче и том же commit.
- Минимальная обязательная проверка после каждой значимой завершённой задачи: `NT-Analyzer/docs/external-gpt-context/02_CURRENT_SYSTEM_STATE.md` и `NT-Analyzer/docs/external-gpt-context/11_ACTIVE_WORK_AND_HANDOFF.md`.
- После подтверждённого Canary/Production deployment или release acceptance обязательно обновлять `NT-Analyzer/docs/external-gpt-context/02_CURRENT_SYSTEM_STATE.md`, `NT-Analyzer/docs/external-gpt-context/04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md` и `NT-Analyzer/docs/external-gpt-context/11_ACTIVE_WORK_AND_HANDOFF.md` как часть того же release closeout.
- Такой release closeout обязан сохранять exact operational release identity: `version`, artifact git SHA, authoritative manifest/archive SHA256 из release evidence, `build ID`, Canary/Production status, `same_release_dir` при наличии, `previous`/rollback slot и все `PARTIAL` / `EXTERNAL BLOCKED` пункты.
- Если operational release evidence ещё не отражено в канонических repo docs, сначала записать его в компактный canonical changelog/handoff snapshot, и только потом ссылаться на него из Context Pack.
- Нельзя массово переписывать даты или делать cosmetic refresh всего пакета. Обновляются только документы, чьи факты действительно изменились.
- Перед closeout прогонять `python tools/validate_external_gpt_context.py` из `NT-Analyzer/`.
