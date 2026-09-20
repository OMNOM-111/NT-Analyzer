# Agent World — отдельная оценка реальных результатов приложения

Change summary: сохранённые результаты цепочки SF Chat → Model → NinjaTrader/Рабочий стол автоматически появляются в списке оценок задачи и в отдельной проекции execution conformance. Оценка арифметики, проверка плана модели и подтверждение фактического исполнения не объединяются.

Status: BETA — аддитивная DEV-проекция поверх существующих Evaluation/Outcome/artifacts. Исходный checkout: `f80d67f730bcd4734893ee7f83643f580138be9a`, код Local до этой правки: `95912cbff8152905966e6bb7bfc2a45d3db15f80`, branch `codex/agent-world-owner-preview`, PR #282. Итоговый source SHA и общий verification result фиксирует основной исполнитель при Git closeout. Версия остаётся `0.10.0-beta.96`; это не merge, release, Canary/Production deployment или разрешение на них.

## Что исправлено

- Существующий adapter уже сохранял отдельный `application_execution` Evaluation, но `task_detail.evaluations` возвращал только оценку текста/плана модели. Теперь он включает оба доказательства; совместимое поле `evaluation` остаётся оценкой текста, новое `application_evaluation` содержит отдельно подтверждение приложения.
- `evaluations(..., rubric_key="application_execution")` использует существующие scoped записи, перепроверяет исходный ответ модели, typed связи Task/Model/Outcome/Evaluation, request digest и доступность immutable artifacts. Запрос чтения не создаёт оценок, не запускает модель/приложение, не меняет очередь или рейтинг Router.
- Conformance разделена на `backtest` / `ninjatrader_report` и `chart` / `desktop_chart`. Сводный `score_pct` всегда `null`: разные классы не усредняются. Внутри класса до трёх разных requests показывается `NEW`, затем только наблюдаемая conformance с `confidence=low`.
- `receipt_count` показывает уникальные реальные source receipts, `sample_size` — разные проверенные requests. Повтор доставки/source receipt и повтор одинакового запроса не увеличивают размер независимой выборки. Различаются подтверждённые байты результата и качество решения модели.
- Denominator явно равен `distinct_verified_application_requests`. Это проверка соответствия сохранённых receipts, не доля успешных запусков, не прибыльность/свежесть рыночных данных и не общая оценка модели. Failed/cancelled/pending/no-source attempts остаются в истории с настоящим статусом и без выдуманного application PASS.
- Synthetic, самооценки, неизвестный evaluator, неподтверждённый source, несоответствующая identity/hash или недоступные исходные artifacts не дают зачёт. Обычный `json_arithmetic` рейтинг не меняется.

## Проверки

Добавлен `tests/test_agent_world_application_evaluation.py`: 38 изолированных mock-provider/source сценариев — автоматическая history-проекция, разные классы и выборки, повторы/restart, ошибки/ожидание/отмена, synthetic/self-score rejection, typed lineage и integrity, user/workspace isolation, отсутствие записей и provider calls при чтении.

Scoped regression: **241 passed**, 276.26s, без пропусков (`test_agent_world_application_evaluation`, `test_agent_world_models`, `test_agent_world_application_chat`, `test_agent_world_model_delivery`, `test_agent_world_social_publication`). `py_compile` двух изменённых runtime-модулей и нового тестового файла — PASS; `git diff --check` — PASS. Общие bundle/context/static/full gates фиксирует основной исполнитель.

Это contract evidence, не новый live backtest/PNG. Текущие документы, UI-проекцию, общий full regression и проверку фактического Local обновляет основной исполнитель в рамках общего end-to-end поручения. Пропущенный реальный пользовательский API-key сценарий не объявляется PASS.

## Release impact и rollback

В artifact входят два изменённых runtime-модуля, тесты и эта scoped запись; API совместим и миграция не требуется. Данные владельца, текущие receipts, permissions, budgets, worker jobs, Router/Execution Engine, auth/devices/Preview, Connector/market data и торговое исполнение не изменяются. Rollback — предыдущий проверенный код без восстановления/удаления runtime-данных; сохранённые Evaluation остаются совместимыми.
