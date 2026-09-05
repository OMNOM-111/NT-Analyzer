# Aurora UI API map

Актуально на 2026-09-05 для интегрированного Development-кода. Виктор является AI-собеседником по умолчанию, а StratForge
Orchestrator — единым внутренним AI-шлюзом внутри пользовательской оболочки
`SF Chat`. Единственный HTTP-адаптер интерфейса находится в
`app/static/aurora/assets/api.js`. Production не загружает mock-данные.

Local 8765 уже работает на чистом `486db834850d465006a3983d2d83ee809202df60`,
beta.96, с исходными owner-данными после проверенного переключения. Новые
model/domain/social-контракты ниже пока находятся в незакоммиченном diff отдельного
task worktree и ещё не активированы на этом runtime. Их статус — `IN DEVELOPMENT`;
live model/browser acceptance не заявлена. Canary/Production в этой задаче
не проверялись и не обновлялись. Канон:
[Agent World status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) и
[ADR-0012](../adr/0012-agent-world-integrated-local.md).

Планируемый multi-user слой не должен расширять текущую роль auth до подписки
или владения NinjaTrader. Новые контракты `workspace`, `subscription`,
`promo voucher` и `NinjaTraderConnection` описаны в
`MULTI_USER_ACCOUNT_ARCHITECTURE.md`.

Именованные domain agents добавляют `/api/ai-lab/accounting`,
`/api/ai-lab/strategy-analysis`, `/api/ai-lab/domain-agents` и POST
`/api/ai-lab/domain-agents/message`. Общий endpoint Orchestrator также
распознаёт обращения `Марина, ...` и `Толик, ...`.
Новостной агент использует `/api/ai-lab/news-analysis`; общий чат также
распознаёт `Никита, ...`.

## Страницы

| Страница | Источники данных | Изменяющие действия |
|---|---|---|
| Обзор | `/api/health`, `/api/performance`, `/api/coverage`, `/api/ai-lab/summary`, `/api/reports`, `/api/news`, accounts/account-history | системные действия вынесены в общее меню |
| Бэктест | catalog, instruments, profiles, coverage, reports, jobs, trades, bars, draw objects, favorites, batches | создать job/batch, отменить/удалить job, favorite/unfavorite; серверные фильтры/сортировка не изменяют данные |
| Торговля | accounts, account-history, strategies, positions, orders, executions, errors, commands/results/status, runtime history, strategy history/display, start dates, performance, diagnostics, strategy journal | paper-only enable/disable существующих strategy instances, reconnect modeling для paper/demo/playback, ручное движение, CSV-импорт, классификация движения, восстановление скрытого класса |
| Финансы | performance, performance/trades, AI accounting, accounts, account-history, CSV | единые фильтры доходности и бухгалтерии, пагинация, drilldown и выгрузка; спорные записи не исправляются моделью |
| Стратегии | profiles/archive, AI lifecycle/cell history, coverage, instruments, persistent portfolio registry | статус/удаление профиля, add root/cell, archive cell, hide runtime class, NinjaTrader cleanup |
| AI Lab | summary, experiments/activity, staged run/current status, параллельно проектируемая следующая стратегия, Orchestrator conversation/model/actions, performance board, model-performance, cloud-agent roles/pricing/usage, calendar, compile source, errors, LM Studio | natural-language Orchestrator chat; ручной run/cancel, bootstrap/unload, operator note, stale sweep, user-research scan; локальная настройка cloud keys, role routes и hard budgets |
| AI Agents / API Keys | `/api/ai-agents`, usage, account/provider/role catalogs, DPAPI status, shared grant/budget totals | Add/Edit/Delete model, Test Connection, Enable/Disable, supported balance sync; transport/auth определяются автоматически, ключ возвращается только маской |
| AI Center (`IN DEVELOPMENT`) | `/api/ai-control-center/overview`, `/tasks`, `/tasks/<UUID>`, `/domains/<domain>`, private evidence и отдельные active Memory grants | ровно три основные вкладки «Обзор / Работа / Агенты»; Task Inspector, Persona, Models, Decisions/Court, Memory, Experiments, Projects, routines/calendar, System и SF Social — drawers той же страницы; явные действия через существующие полномочия/worker/budget/SF Chat |
| Новости | `/api/news`, `/api/news/live`, `/api/ai-lab/news-analysis` | read-only; официальный календарь, анализ Никиты, рекомендации, здоровье источников и приоритетные ленты |
| TopStep | `/api/topstep/status` | read-only scaffold; live-действия принудительно отключены до отдельной валидации |
| Telegram, вход и безопасность | `/api/auth/status`, `/api/auth/login/*`, `/api/auth/profile`, `/api/auth/me`, `/api/account/security`, `/api/account/{devices,machines,sessions}/*`, `/api/telegram/status` | новый human access: pending → OTP через Telegram/verified email → permanent или current-session-only; machine/client rename, раздельные session/client/machine revoke; секреты не возвращаются |
| SF Social (`BETA` в DEV-ветке) | `/api/community/v2/*`, совместимые `/api/community/*` Channels | профили/privacy, server-side feed/search/pagination, follow/block, реакции, комментарии, bookmarks, soft delete, жалобы/moderation; публикация завершённого Demo/Backtest result только через server-attested snapshot |
| SF Chat (`BETA` в DEV-ветке) | `/api/sf-chat/*` + существующие `/api/ai-lab/orchestrator*` | единые human conversations/messages/attachments/unread/read/block enforcement и прежние AI conversations в общей оболочке; Community не хранит отдельные DM |
| Виктор | `/api/ai-lab/orchestrator*`, `/api/vitek/*` | единый естественный диалог; status/time-windows, event scan, rest/resume, plans, tasks and incident decisions; в сообщении видны фактический агент, модель/provider и проверяемые action-status без скрытых рассуждений |
| Документы | governance documents, runtime defaults, history | save с actor/reason и подтверждением |

## Новые постоянные контракты

- `GET /api/ai-control-center/overview|tasks`, `GET /tasks/<UUID>` и
  `GET /domains/<domain>[/<UUID>]` используют свежую существующую confirmed
  session, UUID, membership и capabilities. Scope/actor не берутся из payload.
  Read-only repository не создаёт отсутствующую DB/схему и читает существующий
  WAL. GET не ставит задачи, не вызывает модели, не подтверждает delivery и
  не публикует посты. История после исчерпания trial/budget не даёт права на
  новые model calls/jobs/posts. Local domain storage — только Development SQLite;
  настоящие PG regression-тесты проверяют существующие migrations 1–22, не
  отсутствующий Agent World PG adapter.
- `POST /api/ai-control-center/domains/<domain>/<new-or-UUID>/<action>` принимает
  `{payload, expected_revision, idempotency_key}`. Серверные actions/capabilities
  определяют доступные действия; stale revision и повтор ключа с другим смыслом
  конфликтуют. `personas` создаёт/изменяет профиль, `models` подключает собственную
  модель, тестирует и запускает bounded task; `bind_existing` доступен только
  действительному owner в рамках уже существующих caps. `model_tasks`/`tasks`
  показывают историю и отмену, `experiments` сравнивает одинаковый input.
  `decisions`/`court`, `memory`, `projects`, `routines`/`calendar`, `publications`
  и `system` переиспользуют существующие authority и stores. Точные actions и
  payload описаны в [API reference](../external-gpt-context/12_API_AND_SCHEMA_REFERENCE.md).
- Настоящее SF Chat поручение модели использует сохранённое user message и
  выбранную собственную Model. Проверенный план Толика/Ивана поступает в
  существующие NinjaTrader/Desktop механизмы; план сам по себе не завершает
  задачу. Только исходный проверенный report/PNG receipt создаёт application
  Outcome/Evaluation и окончательный статус в том же чате. UI открывает
  существующий conversation через `POST /api/ai-control-center/tasks/<UUID>/chat`
  с пустым `{}`; этот endpoint ничего не дописывает. Независимые оценки
  реальных distinct inputs не меняют Router; при n < 3 статус остаётся NEW.
- `GET /api/ai-control-center/artifacts/<UUID>` остаётся private owner read.
  Shared Memory открывает `/api/ai-control-center/memory-artifacts/<memory-UUID>/<artifact-UUID>`
  только через активный same-workspace grant с проверкой TTL, source revision
  и hash. Публикация/отзыв явные; читатель не может изменять чужой private source.
  Court запечатывает evidence packet, использует три изолированных судейских
  контекста и неизменяемые голоса 2-of-3; verdict не исполняет работу.
  Принятие routine/calendar создаёт ручной follow-up в существующей очереди,
  не автономный scheduler; automation остаётся OFF.
- `POST /api/ai-control-center/domains/publications/new/prepare` формирует
  проверенный allowlisted snapshot из собственного Outcome/Decision без записи
  поста. Отдельный `.../publish` требует `approved_snapshot_sha256`, исходную
  revision и `confirm_permanent=true`; перед записью повторно проверяются
  source и community capability. Existing Community idempotency и private
  approval evidence сохраняют replay/actor/requester. Prompts, raw answers,
  private Memory, judge rationale и credentials в публикацию не попадают.
- Все десять flags по умолчанию OFF. Только exact server-side
  `STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES` в Development включает восемь:
  read/UI/tasks/evaluation/memory/consensus/Court/social. Router shadow и
  Execution V2 остаются OFF; Preview имеет отдельные четыре fixture flags и
  не вызывает реальные domain/provider/social side effects. Выбор UI не
  включает flag и не повышает permissions/budget.
- `GET /api/community/v2/feed|saved|profiles|search` выполняет social filtering,
  privacy и cursor pagination на сервере. Мутации `profile`, `follows`, `posts`,
  `reaction`, `comments`, `bookmark`, `blocks`, `reports` и owner-only
  `moderation` требуют текущую authenticated/CSRF-сессию. Клиентский
  `object_snapshot` запрещён.
- `GET /api/community/v2/objects` перечисляет только завершённые job текущего
  user/workspace scope. `POST /api/community/v2/objects` повторно проверяет
  ownership и entitlement, читает allowlisted job summary и формирует
  server-attested SHA-256 snapshot без raw trades, bars, paths, parameters или
  source code. Пока подключены Demo/Backtest results; Strategy/Chart/Live кнопки
  остаются честно выключенными до своих trusted adapters.
- `/api/sf-chat/conversations*`, `/messages`, `/read` — единственный human chat
  contract. ACL не раскрывает существование чужого диалога (404), block/privacy
  запрещают новые сообщения немедленно, `Idempotency-Key` устраняет повторы.
  AI conversation endpoints не мигрированы и продолжают работать через
  прежний Orchestrator authority.
- Pending session получает от `GET /api/auth/status` только минимальный
  `device_access` bootstrap. До OTP точный allowlist включает
  `/api/account/security/challenge`, `/challenge/resend`, `/challenge/confirm`,
  `/api/account/devices/approve|reject` и `/api/auth/logout`; другие protected
  endpoints отвечают `403 DEVICE_CONFIRMATION_REQUIRED`.
- `GET /api/account/security` возвращает Machine → Client → Session только для
  доказанных Connector/pairing связей, а unbound clients — отдельно. IP/VPN/UA
  не являются machine identity. `POST /api/account/devices|machines/rename`
  переименовывают user-owned сущность; session/client/machine revoke сохраняют
  разные scopes.
- `GET /api/vitek/status` и `GET /api/vitek/time-windows` возвращают
  безопасную owner-only проекцию состояния, активности агентов и рабочих окон.
  `POST /api/vitek/scan|events|rest|resume|plans|tasks` и
  `POST /api/vitek/incidents/<id>/decision` изменяют только контур Витька.
  События долговечны и дедуплицируются; полный scan не выполняется каждые пять
  минут.
- `GET/POST /api/ai-lab/orchestrator/conversations*` адресует историю ключом
  `user_id + workspace_id + conversation_id`. Для владельца прежние
  неразмеченные диалоги мигрируются один раз и идемпотентно; обычный пользователь
  их не видит.
- `POST /api/ai-lab/orchestrator/speak` озвучивает текст ответа агента при
  наведении на аватар в чате. Успех → `audio/mpeg` (профиль голоса агента →
  OpenAI Speech **или** Azure Foundry `gpt-4o-mini-tts` / `tts-1`); без
  рабочего Speech-бэкенда / ошибка → JSON `{ fallback: "browser" }`.
  Credentials: `NTA_OPENAI_API_KEY`, OpenAI-агент, либо Azure-агент с моделью
  Speech (в т.ч. `enabled=false`, чтобы не участвовать в chat-routing).
  Кэш учитывает agent+model+voice+speed+style+language+text.
- Голоса сотрудников: `GET /api/ai-lab/domain-agents/voices`,
  `GET/POST /api/ai-lab/domain-agents/{id}/voice`,
  `POST .../voice/reset`, `POST .../voice/preview`,
  `GET /api/ai-lab/tts/catalog`, `POST /api/ai-lab/tts/openai-key`.
  UI: страница AI Agents → «Голоса сотрудников».
  Канон: [AGENTS.md](../agents/AGENTS.md) § озвучка. Хранение:
  `data/integrations/agent_voices.json` (без секретов).
  **2026-07-16:** подключён Azure Student `gpt-4o-mini-tts`
  (`AGT-B8F24346E288`); chat-модели (GPT-4.1 / Gemini / gpt-5-mini) ≠ TTS.
- Сохранённая категория поручения определяет профильный handler: runtime остаётся
  у Виктора, финансы у Марины, lifecycle стратегии у Толика. GPT-5 mini может
  понять свободную речь, но не может перевести финансовое поручение в график.
  Статус `completed` записывается только после подтверждения целевой системой.

- `GET/POST /api/portfolio/*` использует `app/portfolio_registry.py`. ID ячейки
  неизменяем, архивный ID не переиспользуется. Базовая схема `CELL-001..180`
  сохранена, включая `MNQ slot 11 = CELL-126`.
- `GET /api/billing/plans`, `GET /api/billing/me`,
  `POST /api/billing/promo/{preview,redeem}` и `GET/POST /api/owner/vouchers`
  используют `app/subscriptions.py`. Промокод хранится только как hash; plaintext
  code показывается owner один раз при создании. `read_only` пользователь может
  выполнить только self-service preview/redeem, owner-voucher endpoints остаются
  owner-only.
- `GET /api/workspaces`, `POST /api/workspaces/{personal,select}`,
  `GET /api/bridge/connections`, `POST /api/bridge/pair/{start,complete}` и
  `POST /api/bridge/connections/<id>/revoke` используют `app/workspaces.py`.
  Auth status возвращает `workspaces`, `active_workspace` и
  `active_membership`. Runtime endpoints читают общий `data/runtime/*` только
  для `owner_training`; personal workspace получает isolated empty runtime до
  pairing, после pairing читает `data/tenants/<workspace_id>/runtime` и имеет
  собственный tenant statement ledger. Bridge поддерживает `runtime_data_dir` в
  `NTAnalyzerBridge.config.json`.
- `GET /api/auth/me` собирает «личный кабинет»: профиль (с аватаром), роль,
  подписка, активная область, статус NinjaTrader, эффективные `features` и
  `feature_catalog`. `GET /api/auth/avatar/<id>` отдаёт кэшированный аватар
  (self или owner); `POST /api/auth/avatar/refresh` тянет фото профиля через Bot
  API (`getUserProfilePhotos`) в `data/integrations/avatars/` и в inline
  `avatar_data_url`. `POST /api/auth/users/<id>/features` (owner-only) включает
  или выключает пользователю раздел из каталога возможностей.
- `GET /api/owner/support/monitoring` и `/api/owner/support/users/<id>` дают
  владельцу разбивку живой телеметрии вкладок по пользователям. Команды
  `POST .../reload` адресуются текущей браузерной сессии; точечное завершение
  использует `POST /api/auth/users/<id>/sessions` и не удаляет аккаунт.
  Клиентские `/api/support/{telemetry,poll,commands/ack}` работают только от
  имени текущего пользователя, включая владельца. `POST
  /api/owner/support/users/<id>/device-name` сохраняет понятное имя для
  стабильного browser-device ID; переподключение аккаунта не требуется.
- Снимок экрана создаётся только после отдельного диалога согласия и нативного
  `getDisplayMedia`-выбора экрана/окна пользователем. JPEG/PNG шифруется Windows
  DPAPI, доступен только через owner endpoint и автоматически удаляется через
  24 часа. Браузер передаёт показатели своей вкладки, а не скрытую системную
  телеметрию остальных программ компьютера.
- `GET /api/ops/runtime/account-history` использует `app/account_ledger.py`.
  Необъяснённый delta NetLiq записывается только как
  `unclassified_adjustment`; он не становится прибылью или пополнением без
  ручной классификации.
- `POST /api/ops/runtime/account-history/classify` принимает подтверждённый тип
  `deposit|withdrawal|transfer|fee`, actor и основание.
- `POST /api/ops/runtime/account-history/events` создаёт подтверждённое ручное
  движение; `POST .../import` атомарно импортирует до 5000 строк и устраняет
  повторы по `source_id`.
- `GET /api/performance/trades` возвращает единый закрытый trade contract с
  `offset/limit`; `strategy_breakdowns` содержит day/week/month/hour/weekday/
  direction только по атрибутированным стратегиям.
- `GET /api/ai-lab/model-performance` агрегирует model/role request success,
  latency P95, usage tokens и результат связанных экспериментов.
- `GET /api/ai-lab/cloud-agents/status` возвращает безопасный catalog цен,
  назначения ролей, budget/spend и usage без ключей. POST endpoints
  `provider-key|provider-test|provider-disconnect|settings` управляют только
  локальными секретами и controlled fallback; лимиты `$20/month`, `$0.50/run`.
- `GET/POST /api/ai-agents*` использует `app/ai_lab/agent_registry.py`, DPAPI
  `app/secure_store.py` и единый `app/ai_lab/universal_llm.py`. Реестр поддерживает
  chat/embeddings, provider/model/role, тарифы, grant snapshot, budgets и usage;
  HTTP не возвращает plaintext key или prompt content.
- `GET /api/reports` поддерживает сортировку по PF, частоте и статистическому
  доверию, а также фильтры по всем операторским колонкам. Частота едина для UI и
  backend: `<2`, `2–7`, `>7` сделок в неделю. Тяжёлые metric-фильтры имеют
  явный охват `500/2000/all`; точный номер отчёта всегда ищется во всём архиве.
- `GET /api/news` разделяет подтверждённые расписания Fed/BLS/BEA/Census/EIA
  и оценки стандартного графика. Только подтверждённый high-impact может
  включить красный STOP/blackout. `GET /api/news/live` возвращает свежие
  заголовки и статус каждого провайдера; фоновое обновление запускается вместе
  с backend и записывает runtime-файлы атомарно.
- `GET /api/integrations/status`, `/api/topstep/status`, `/api/news`,
  `/api/news/live` и
  `/api/ai-lab/external-agents/status` не возвращают токены/API-ключи и не
  создают демонстрационные события.
- `GET /api/telegram/status` и `POST /api/telegram/{token,pair/*,settings,test,disconnect}`
  используют `app/telegram_service.py`. Фоновый notifier отслеживает heartbeat,
  runtime-стратегии, свежие ошибки, high-impact новости и расписание сводок.
  Свободный текст из единственного paired private chat передаётся Orchestrator;
  исполняются только действия allowlist, strategy enable/disable для paper/demo
  требует отдельного approve, а bounded reconnect paper/demo/playback остаётся
  автономным self-heal действием без live-полномочий.

## Safety

- Runtime-команды остаются paper/demo/playback-only. Backend отклоняет live и
  неизвестные счета; strategy enable/disable требует operator approval, а
  reconnect paper/demo/playback ограничен безопасным infrastructure self-heal.
- Multi-user isolation выполняется до чтения runtime: personal workspace не
  проваливается к owner `data/runtime/*`, а учебный workspace владельца остаётся
  read-only для не-owner пользователей.
- TopStep остаётся execution-disabled. Платные AI-роли могут выполнять только
  два sandbox fallback-сценария после отдельного разрешения и budget gate;
  runtime/account/paper/live действия для них всегда запрещены.
- Универсальный AI agent не получает полномочия из поля role. До явного
  подключения конкретного workflow он доступен только для ручного Connection Test.
- Все изменяющие действия требуют подтверждения в UI и показывают ошибку backend.
- P&L строится по закрытым сделкам после комиссии. NetLiq и движения средств
  отображаются отдельно.
- Старые broker cash transactions отсутствуют в исходной телеметрии. История
  средств начинается с первого сохранённого snapshot; прошлое не дорисовывается.
