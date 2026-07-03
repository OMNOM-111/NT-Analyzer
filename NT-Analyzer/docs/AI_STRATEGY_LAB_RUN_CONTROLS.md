# AI Strategy Lab — Run Controls

Эта инструкция объясняет **новые поля запуска** и **как читать прогресс** AI Strategy Lab. Дата: 2026-06-17.

---

## 1. Два независимых параметра

### 1.1. «Количество стратегий» (внешний цикл)

- Поле: **`Стратегий за запуск`** (`#ai-strategy-count`).
- Значения: 1 / 2 / 3 / 5 / 10.
- Каждая стратегия = **новый AI-CELL**, новый `class_name`, новый `.cs` файл.

### 1.2. «Итераций на стратегию» (внутренний цикл)

- Поле: **`Итераций на стратегию`** (`#ai-iterations-per-strategy`).
- Значения: 1 / 2 / 3 / 4 / 5 / **«Без лимита (до остановки)»**.
- Каждая итерация = **mutation внутри того же AI-CELL** (тот же `class_name`,
  переписывается `current.cs`, история v1..vN в `ai_lab/mirrors/{cell}/history/`).
- Итерация запускается, если verdict = `reject` или `mutate` и budget ещё есть.

### 1.3. Время и стоп

- **`Макс. время`** — потолок длительности всего запуска: 30 мин / 1 ч / 6 ч /
  12 ч / 24 ч / **«Без лимита»**.
- **`Стоп на первом кандидате`** — если включено, выходит из outer-loop
  после первого `sandbox_candidate/champion_candidate`.
- Кнопка **«Остановить»** отменяет и внутренний (текущий experiment), и
  внешний (run) циклы.

### 1.4. Дефолты

| Поле | Default | Max |
|------|---------|-----|
| Стратегий за запуск | 1 | 10 |
| Итераций на стратегию | 3 | 5 или Без лимита |
| Макс. время на запуск | 1 ч | 24 ч или Без лимита |
| Стоп на первом кандидате | off | — |

---

## 2. LM Studio: жёсткая блокировка

- При старте каждого run пайплайн делает **preflight probe** ролей `judge` и
  `coder` через `/chat/completions`.
- Если хотя бы одна роль недоступна — **ни один experiment не создаётся**,
  API возвращает `409 blocked_lm_studio`, кнопка «Запустить» в UI становится
  серой, чип LM Studio красный с текстом «недоступна — запуск заблокирован».
- Тихий `fallback_template` **отключён**. Чтобы намеренно собрать страт без
  LM Studio (для отладки), нужно явно включить `allow_template_fallback=true`
  (скрытый debug-чекбокс). В этом случае в журнале активности появится
  крупный жёлтый warn-блок «⚠️ Код сгенерирован ШАБЛОНОМ, не LLM».

Что делать, если получили `blocked_lm_studio`:

1. Запустить LM Studio.
2. Убедиться, что в нём загружены модели из `ai_lab/model_roles.json` (как
   минимум роли `judge` и `coder`).
3. На вкладке **«LM Studio»** в UI — должно быть `available: ✅` и пустой
   список `missing_roles`. После этого «Запустить» снова станет активной.

### 2.1. Автоподготовка среды

Быстрый запуск:

```powershell
.\00_START_AI_LAB.cmd
```

Что делает launcher:

1. Проверяет/запускает NinjaTrader.
2. Проверяет/запускает LM Studio.
3. Если доступен `lms`, выполняет `lms server start`.
4. Запускает backend и открывает `/ui/ai-strategy.html`.

Модели работают в lazy-режиме:

- при простое модели не загружаются в RAM/VRAM;
- перед конкретным `/chat/completions` backend делает `lms load <model>`;
- между соседними LLM-вызовами одного run модель по умолчанию **остаётся
  загруженной**, чтобы LM Studio мог повторно использовать стабильный prompt
  prefix / KV-cache;
- повторный `lms load <model>` для уже активной модели пропускается;
- после завершения research run выполняется `lms unload --all`;
- API-сервер LM Studio по умолчанию остаётся запущенным: это не занимает VRAM, но
  убирает ложный status «LM Studio недоступна» между итерациями;
- кнопка **«Освободить AI-память»** выгружает модели; сервер останавливается только при
  явном `stop_server=true` или `AI_LAB_AUTO_STOP_LM_SERVER=1`.

В UI есть кнопка **«Подготовить среду»**. Она вызывает:

- `GET /api/ai-lab/bootstrap/status`;
- `POST /api/ai-lab/bootstrap/start`.

Автоподготовка внутри кнопки «Запустить» включается только явно:

```powershell
$env:AI_LAB_AUTO_BOOTSTRAP = "1"
$env:AI_LAB_LAZY_LM_STUDIO = "1"
$env:AI_LAB_AUTO_UNLOAD_MODELS = "1"
$env:AI_LAB_REUSE_LOADED_MODEL = "1"
$env:AI_LAB_UNLOAD_AFTER_EACH_REQUEST = "0"
$env:AI_LAB_AUTO_STOP_LM_SERVER = "0"
```

### 2.2. Prompt / prefix caching discipline

Для локального LM Studio это в первую очередь ускорение prefill/GPU, а для
облачных API — ещё и снижение стоимости input tokens. Правило проекта:

- большие стабильные блоки (`system_*`, `knowledge_prompt_context`, lessons,
  reference shortlist) идут **в начале** prompt;
- динамические поля (`AI Cell`, `class_name`, hypothesis, compile errors,
  operator notes) идут **после** маркера
  `<<<AI_LAB_PROMPT_CACHE_STABLE_PREFIX_END>>>`;
- prompt log пишет `prompt_cache.stable_prefix_sha256`,
  `stable_prefix_chars` и `dynamic_suffix_chars`, чтобы видеть, не сломался ли
  reusable prefix;
- не включать `AI_LAB_UNLOAD_AFTER_EACH_REQUEST=1` для обычных research runs:
  это освобождает VRAM раньше, но убивает выигрыш от повторного prefix/KV reuse.

Пути можно задать env-переменными или `ai_lab/bootstrap.json`:

```json
{
  "ninjatrader_exe": "C:\\Program Files\\NinjaTrader 8\\bin64\\NinjaTrader.exe",
  "lm_studio_exe": "%LOCALAPPDATA%\\Programs\\LM Studio\\LM Studio.exe",
  "lms_cli": "lms"
}
```

Не автоматизируется: первый логин NinjaTrader, установка/обновление bridge,
скачивание моделей LM Studio, paper/live trading.

---

## 3. Как читать прогресс

### 3.1. Activity log

В журнале появляются строки уровня run:

- `runner / strategy_started` — начало новой стратегии outer-loop.
- `runner / iteration_started` — начало итерации inner-loop, `iteration_idx
  N/{total или ∞}`.
- `runner / mutation_prepare` — между итерациями (когда verdict = reject/mutate).
- `runner / iteration_finished` / `strategy_finished` — закрытие цикла.

### 3.2. Run progress (под формой запуска)

Отдельная синяя плашка `#ai-run-progress` показывает:

`Run RUN-xxx: strategy 2/5, iter 3/∞, время осталось: 25 мин 14 с, кандидатов: 0`

Polling: каждые 3 секунды (endpoint `GET /api/ai-lab/run/status`).

### 3.3. iteration_history в experiment JSON

Внутри каждого `EXP-*.json`:

```json
{
  "current_iteration": 3,
  "mirror_history_dir": "...ai_lab/mirrors/AI-CELL-MNQ-001/history",
  "iteration_history": [
    {"iteration": 1, "sha256": "...", "verdict": "reject", "pf": 0.8},
    {"iteration": 2, "sha256": "...", "verdict": "reject", "pf": 0.95},
    {"iteration": 3, "sha256": "...", "verdict": "candidate", "pf": 1.3}
  ]
}
```

История .cs: файлы `v1.cs`, `v2.cs`, … в `mirrors/{cell}/history/`. NinjaTrader
видит и компилирует только `current.cs` — конфликта имён классов нет.

---

## 4. Вкладка «Память ошибок»

В шапке страницы — четыре вкладки: `Эксперименты | Портфолио | Память ошибок |
LM Studio`. На вкладке «Память ошибок»:

1. **Повторяющиеся паттерны** (последние 30) — `error_patterns.json`, что AI
   уже встречал и должен избегать.
2. **Уроки (lessons, последние 20)** — `lesson_log.jsonl`. После каждого
   `LOW_SCORE` reject, signal sanity fail или compile_failed_after_fix_loop
   сюда автоматически добавляется запись.
3. **Глобальные правила оператора** — `global_operator_notes.jsonl`. Это ваши
   заметки с `priority=high` или с ключевыми словами:
   `ошибк | не повторяй | запрет | никогда | always | never | avoid | fix: | rule: | правило`.
   Их видят **все будущие стратегии в любых run-ах**, не только текущий experiment.
4. Поле для добавления **глобального правила вручную** + кнопка
   «**Очистить зависшие**» (вызов `POST /api/ai-lab/maintenance/sweep-stale` —
   помечает нетерминальные эксперименты без heartbeat > 6 ч как `cancelled`).

---

## 5. Уникальность стратегий

Перед каждым `write_to_sandbox` (включая mutation внутри AI-CELL) считается
fingerprint:

`sha256(family + normalized_hypothesis + sorted(indicators) + sorted(entry_keywords) + sorted(param_names))`

Параметры берутся **только по именам**, не по значениям — изменение
`StopLossTicks` с 20 на 25 не считается «новой стратегией».

Что блокируется:

- Совпадение fingerprint в последних 30 записях того же `target_root`.
- Совпадение с самой последней записью (immediate repeat).
- Hypothesis Jaccard similarity > 0.85 с любой из последних 5 записей того
  же root.

Что **НЕ** блокируется:

- Повторное исследование того же `family` — это разрешено и часто полезно.
- Просто новый набор параметров поверх старой логики — fingerprint этого
  не отлавливает напрямую (это работа уроков и memory).

При обнаружении дубля mutation/run помечает попытку `rejected` с
`rejection_code=DUPLICATE_FINGERPRINT`.

---

## 6. API — короткая шпаргалка

| Метод | Путь | Что делает |
|-------|------|------------|
| `POST` | `/api/ai-lab/run` | Запустить run (см. поля ниже) |
| `GET`  | `/api/ai-lab/run/status` | Текущий прогресс run |
| `POST` | `/api/ai-lab/run/cancel` | Отменить весь run (outer + inner) |
| `POST` | `/api/ai-lab/experiments/{id}/cancel` | Отменить только текущий experiment |
| `GET`  | `/api/ai-lab/errors/summary` | Паттерны, уроки, глобальные ноты |
| `POST` | `/api/ai-lab/lessons` | Добавить урок вручную |
| `POST` | `/api/ai-lab/operator-notes/global` | Добавить глобальное правило |
| `POST` | `/api/ai-lab/maintenance/sweep-stale` | Очистить зависшие experiments |
| `GET`  | `/api/ai-lab/lm-studio/health` | Текущий статус LM Studio |

Тело `POST /api/ai-lab/run`:

```json
{
  "goal": "Сделай лучшую стратегию",
  "target_root": "MNQ",
  "capital": 5000,
  "strategy_count": 2,
  "iterations_per_strategy": 3,
  "iterations_unlimited": false,
  "max_total_runtime_minutes": 1440,
  "stop_on_first_candidate": false,
  "allow_template_fallback": false,
  "use_llm": true
}
```

Backward compat: старые поля `max_cells_per_run` и `max_mutations_per_cell`
по-прежнему принимаются — runner нормализует их в `strategy_count` и
`iterations_per_strategy = max_mutations_per_cell + 1`.

---

## 7. Чеклист E2E (ручной прогон с LM Studio + NinjaTrader)

Артефакты класть в `ai_lab/experiments/AI_LAB_E2E_RUN_<date>/`:

1. **1 стратегия × 3 итерации** — открыть experiment JSON, проверить
   `iteration_history` длины 3, в `mirrors/{cell}/history/` три разных sha256.
2. **2 стратегии × 2 итерации** — два разных `experiment_id` и `class_name`,
   во втором экспирименте в `knowledge_context` виден lesson из первого
   (вкладка «Память ошибок» → раздел «Уроки»).
3. **Unlimited + cancel через 5 мин** — статус `cancelled`, runner idle,
   `run_status` возвращает `null`.
4. **LM Studio выключен** — POST `/run` отвечает `409 blocked_lm_studio`,
   ни один experiment не создан, кнопка «Запустить» disabled.
5. **Operator note во время run** с приоритетом high — следующая итерация
   видит note в global, activity log содержит `operator_note_applied`.
