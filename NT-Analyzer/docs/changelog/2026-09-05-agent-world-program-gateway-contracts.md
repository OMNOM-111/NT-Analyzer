# Agent World — gateway actions и проверяемые read projections

Change summary: characterization-проверки ручной передачи фактов другому агенту,
открытия ручного разбора в SF Chat и отображения отдельных прикладных наблюдений.
Проверки защищают соответствие кнопок серверным правам: доступ к истории не
означает разрешения на новое задание или отправку данных провайдеру.

Source checkpoint: Local `95912cbff8152905966e6bb7bfc2a45d3db15f80`,
`0.10.0-beta.96`. Новый slice относится к рабочему дереву
`codex/agent-world-owner-preview`, [draft PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282).
Итоговый commit/CI и общую current/External GPT документацию фиксирует основной
исполнитель после объединённой проверки. Этот record не объявляет release.

## Изменение и границы

Добавлен только `tests/test_agent_world_program_gateway.py` и этот record.
Production/shared-файлы изменяет основной исполнитель, не данный test slice.
Gateway HTTP handlers и SQLite services не подменяются; используются
контролируемые auth/session/membership, provider/source fixtures из существующих
наборов. В сценариях ручного разбора работают настоящие одноразовые worker queue
и SF Chat files. Handoff DTO проверяется на dispatch seam без отправки запроса.
UI presentation functions выполняются в Node без браузера и запущенного Local.

Все identity/model/source данные здесь synthetic fixtures. Surrogate application
bytes предназначены для проверки агрегации, не доказывают получение настоящего
NinjaTrader отчёта, валидного PNG или ответа внешнего провайдера. Отдельные
application/source suites отвечают за эти контракты; live owner acceptance
не выводится из тестовых результатов.

31 новый сценарий покрывает:

- Оба action aliases `tasks`/`model_tasks` передают только выбранный
  `target_model_id`; факты, lineage, chat scope и workspace из клиента отклоняются.
- Ordinary session не становится Local owner. Read-only session не вызывает
  handoff, даже при разрешённой подписке и собственной workspace.
- Routines/Calendar list и detail сохраняют принятую запись и provenance, но
  не показывают `open_chat`/другие мутации после потери membership, capability
  или получения read-only session role.
- Состояние queued не рисует кнопку сохранённого диалога. После действительной
  доставки UI открывает тот же системный SF Chat message, не выдаёт ему рейтинг,
  не создаёт модельную задачу и не считает уведомление исполнением агента.
- Недоступный/изменённый источник убирает ручную action и показывает limitation;
  чтение не создаёт новый job или запись. Сохранённую доставку можно читать
  после истечения права на новые действия.
- Model factories получают копию trusted chat scope для fresh-source handoff
  проверки, без client-supplied constructor authority.
- Overview хранит прикладные наблюдения отдельно от арифметики. Два разных
  receipt одного входа дают `receipt_count=2`, но `n=1`, `NEW`, без общей оценки
  модели, объединения task classes или влияния на routing.
- После потери model entitlement/бюджета overview и task history одинаково
  скрывают handoff/cancel, сохраняя evidence. Независимые Persona actions не
  отключаются из-за model budget; read-only session скрывает все мутации.

Review выявил два UI/authority mismatch: session read-only role терялась при
построении read projection, а overview не применял model capability/budget
фильтрацию к task actions. Основной исполнитель исправил trusted
`session_read_only` projection и адресную фильтрацию model actions. POST admission
не расширяется; это согласование отображения с существующими отказами сервера.

## Verification result

**PASS — 267 passed**, 278.92 s, без пропусков:

```text
python -m pytest -q tests/test_agent_world_program_gateway.py tests/test_agent_world_program_presentation.py tests/test_agent_world_domain_gateway.py tests/test_agent_world_followup_chat.py tests/test_agent_world_application_evaluation.py tests/test_agent_world_result_handoff.py
```

Все 31 новый сценарий входят в этот прогон. Python compilation нового теста и
проверка trailing whitespace двух новых файлов — PASS. Неподтверждённых новых
production-дефектов в просмотренном gateway/UI scope после исправления двух
описанных projection расхождений не выявлено.

Первый прогон нового файла: 29 passed / 2 failed. Два падения относились к слишком
строгому тестовому ожиданию отсутствия budget lookup в overview. Assertion
уточнён: сама доставка не вызывает бюджет, overview вправе читать существующий
budget gate с `amount=0`, без расхода/reservation.

Полный regression, context/static/bundle gates и Git/CI closeout выполняет
основной исполнитель. Непроверенные live user/provider сценарии остаются pending.

## Release impact

Нет смены версии, merge/deploy, Production/Canary DB, новых прав, бюджета или
очереди. Auth/devices/Preview, owner keys/data, SF Social, market data, Connector
и торговое исполнение не изменены этим тестовым slice. Rollback — исключить
новый тест и record из последующего изменения; runtime rollback не требуется.
