# Жизненный цикл стратегий (Strategy Lifecycle)

Единая модель этапов для **всех** стратегий — и ручных (production), и созданных
локальным ИИ (AI / LM Studio). Доска «Стратегии по этапам» на `/ui/strategies.html`
показывает обе ветки в одних и тех же четырёх колонках, разделяя их фильтром
источника (Все / Production / AI / LM Studio) и бейджем «AI / LM Studio».

## Четыре этапа (`lifecycle`)

| `lifecycle`        | Колонка                              | Смысл |
|--------------------|--------------------------------------|-------|
| `trial`            | Испытание                            | Стратегия в разработке/проверке. Резервирует ячейку, показывает остаток срока/прогресс. У каждой — индивидуальный `trial_plan` (время / условие / усилие / гейты), заданный при планировании. |
| `approved_demo`    | Утверждено для демо                  | Прошла испытания, торгуется на демо. Несёт `demo_plan` (срок + прогноз) и сверку «история ↔ факт». Считается в портфель. |
| `approved_live`    | Утверждено для реальной торговли      | Только **после прибыльного демо**. |
| `failed_archived`  | Провалено → Архив                    | Провалила все испытания. Удаляется из NinjaTrader, фиксируется причина и `fingerprint` в реестре «не создавать повторно». |

**Главное правило:** каждую начатую стратегию доводим до **терминального** этапа —
либо `approved_demo`/`approved_live`, либо `failed_archived`. Нельзя оставлять
стратегию «висящей» в середине пайплайна без решения.

## Правило: в NinjaTrader — только актуальные стратегии

В списке «Доступные стратегии» NinjaTrader должны быть **только утверждённые**
стратегии (`approved_demo` / `approved_live`) **плюс базовые движки, от которых
они наследуются** (компиляционная зависимость — без них approved-классы не
скомпилируются). Всё остальное (архивные обёртки, AI-песочница, reference
library, исследовательские движки без approved-потомков) держим **вне** NinjaTrader.

### Как это работает технически

NinjaTrader показывает в пикере КАЖДЫЙ класс, скомпилированный в
`NinjaTrader.Custom.dll`. Класс компилируется, если его `.cs` лежит в любой папке
под `Documents/NinjaTrader 8/bin/Custom/Strategies/`. Поэтому, чтобы стратегия
исчезла из списка, нужно **два** шага:

1. Убрать её `.cs` из всех compile-папок Custom (делает приложение → карантин).
2. **Перекомпилировать NinjaTrader (F5)** — иначе класс остаётся в DLL. Этот шаг
   делает оператор (NinjaScript Editor → F5) или происходит при перезапуске NT.

### Механизм уборки (реализован)

- Кнопка **«Очистить NinjaTrader»** на доске (`/ui/strategies.html`) или endpoint
  `POST /api/profiles/ninjatrader/cleanup` (`{dry_run, include_ai_sandbox, include_ref_lib}`).
- `ninjatrader_ops.cleanup_to_approved`:
  1. `approved_strategy_classes` — классы approved-профилей (seed).
  2. `build_class_index` + `compute_keep_closure` — keep-set = approved + замыкание
     по наследованию (`class X : Base`) и прямым ссылкам в коде. Узлами замыкания
     считаются только классы, у которых есть одноимённый файл (вложенные хелперы
     вроде `RiskManager` не создают ложных связей).
  3. Всё, что не в keep-set, переносится в `ninjatrader/strategies/_quarantine/`
     (обратимо). **Репозиторий-исходники НЕ трогаются** — история разработки
     сохраняется; чистятся только compile-папки NinjaTrader Custom.
- `dry_run=True` показывает план без перемещения. После реального запуска —
  оператор жмёт **F5** в NinjaTrader.

Так разработка остаётся гибкой (ИИ/пользователи пробуют любые движки в песочнице
и репозитории), а боевой список NinjaTrader содержит только готовые стратегии.


## Production-стратегии

Каноничный источник — `data/profiles/strategies.json`. Поле `lifecycle` выводится
из `status` (`app/strategy_lifecycle.py::classify_lifecycle`) и синхронизируется
обратно при изменении через UI/endpoint. Удаление из NinjaTrader при архивации:
флаг + чек-лист, перемещение CELL-обёртки в `ninjatrader/strategies/_quarantine/`
(`app/ninjatrader_ops.py`). Общие базовые классы не трогаются.

## AI / LM Studio-стратегии

Источник — реестр экспериментов `ai_lab/registry/experiments/EXP-*.json`. Каждый
эксперимент проходит собственную машину статусов (`app/ai_lab/registry.py`).
Соответствие статус → этап задаёт `app/strategy_lifecycle.py::lifecycle_for_ai_status`:

- **Испытание** (`trial`): `draft`, `generating`, `generated`, `awaiting_compile`,
  `catalog_visible`, `backtesting`, `backtest_done`, `analysis_ready`,
  `mutation_planned`, `mutation_candidate`, `sandbox_candidate`,
  `champion_candidate`, `human_review_candidate`.
- **Утверждено для демо** (`approved_demo`): `portfolio_contributor`.
- **Провалено → Архив** (`failed_archived`): `rejected`, `cancelled`,
  `validation_failed`, `compile_failed`, `compile_failed_after_fix_loop`,
  `awaiting_compile_timeout`, `blocked_by_real_environment_issue`,
  `blocked_lm_studio`, `backtest_failed`, `pipeline_failed`, `archived`.

### Механизм авто-распределения

1. Оркестратор (`app/ai_lab/orchestrator.py`) и пайплайн меняют `status`
   эксперимента на каждом шаге (генерация → компиляция → бэктест → арбитраж →
   вердикт).
2. **Любая** запись эксперимента идёт через `registry.write_experiment`, который
   автоматически проставляет `lifecycle` и `lifecycle_label` из текущего `status`.
   Отдельно ничего указывать не нужно — этап всегда соответствует статусу.
3. Доска читает агрегированные карточки (одна на `ai_cell_id`, последняя попытка)
   через `GET /api/ai-lab/lifecycle` (`app/ai_lab/read_model.py::lifecycle_cards`).
4. Провалённые AI-стратегии помечаются `removed_from_ninjatrader: true`
   (sandbox auto-quarantine) — AI-песочница чистится автоматически.

### Что делает ИИ при создании стратегии

- Создаёт эксперимент → он сразу виден в колонке **Испытание** ветки AI.
- Ведёт через этапы; статус (а значит и этап) обновляется автоматически.
- При успехе и прохождении гейтов → кандидат, далее ручное утверждение в портфель
  (`portfolio_contributor` → **Утверждено для демо**).
- При провале фиксирует причину/код (`verdict.rejection_code`) → **Провалено →
  Архив**, удаляет из песочницы; запись остаётся как «не создавать повторно».

## Шаблоны полей (для дальнейшей реорганизации/анализа)

- `trial_plan`: `{ basis: "time"|"condition"|"effort"|"gates", started_at_utc,
  planned_end_utc | duration:{value,unit}, total_gates, completed_gates,
  condition_text, notes }`.
- `demo_plan`: `{ basis, started_at_utc, planned_end_utc, duration, forecast_net, notes }`.
- `approved_demo.historical`: `{ avg_net_per_period, period_label, source_total_net, source_period }`.
- `failed_archive`: `{ reason, failure_codes[], fingerprint, removed_from_ninjatrader,
  removal_method: "ai_quarantine"|"production_checklist" }`.

Все эти поля видны в UI при наведении на карточку и используются для сверки,
аудита и предотвращения повторной разработки уже провалившихся идей.

## История попыток по ячейке (Cell attempt history)

Для каждой ячейки портфеля хранится **вся история стратегий**, которые пробовали
для неё (включая архивные варианты других классов). Это видно прямо со страницы
стратегий и AI:

- **Production** (`/ui/strategies.html`): клик по ячейке матрицы (в т.ч. по
  «пустой» ячейке с пометкой `архив: N`) открывает секцию «История ячейки
  CELL-xxx» со всеми стратегиями: что не подошло (архив) и что в итоге утверждено,
  с метриками, причиной отклонения, индивидуальным критерием успеха и ссылкой на
  отчёт. Источник — все профили с `cell_id == CELL-xxx` либо
  `archived_cell_id == CELL-xxx`.
- **AI / LM Studio** (`/ui/ai-strategy.html`): клик по ячейке AI-матрицы открывает
  «История AI-ячейки AI-CELL-ROOT-NNN» со всеми экспериментами этого `ai_cell_id`
  (`GET /api/ai-lab/cell-history?cell=...` → `read_model.cell_history`).

Так фиксируется путь вида «пробовали 100 стратегий, не подошло — 101-я прошла все
критерии»: каждая попытка остаётся в истории своей ячейки.
