# AI Agents / API Keys: подключения, роли, ключи и бюджет

Актуально на 2026-07-02. Универсальный реестр теперь подключён непосредственно к
historical-only AI Lab через role-aware router. Итоговый benchmark и фактические
замеры: `docs/AI_AGENT_STACK_RESEARCH_2026-07-01.md`.

1. универсальный реестр **AI Agents / API Keys** для ручного подключения и
   проверки OpenAI, Microsoft Foundry / Azure OpenAI, DeepSeek, OpenRouter,
   Gemini, Z.AI/GLM, Mistral, Groq и Custom OpenAI-compatible API;
2. совместимый старый controlled fallback, сохранённый только для обратной
   совместимости конфигурации.

Наличие ключа не даёт агенту право запускать стратегии, торговать, отправлять
Telegram-сообщения или обходить validator/backtest/arbitration. Эти интеграции
подключаются к ролям отдельно и только после собственных safety gates.

## Операторский экран

Открыть `/ui/ai-agents.html` или пункт **AI Agents** в навигации. Экран позволяет:

- Add / Edit / Delete Model;
- Test Connection явным коротким запросом;
- Enable / Disable Agent;
- указать provider, account/quota, model/deployment и ключ;
- автоматически определить chat/embeddings transport и auth;
- классифицировать аккаунт как grant/credit, free tier, pay-as-you-go или unknown;
- при необходимости позже раскрыть advanced-настройки role/rotation/priority;
- учитывать grant/credit и ручной снимок остатка из billing portal;
- видеть расход по агенту, provider и model, а также журнал запросов.

Цена не вводится при добавлении модели. Она берётся из централизованного model
catalog, который обновляется вместе с документацией. Если тарифа ещё нет,
приложение считает tokens, но показывает **цена не настроена**, а не фиктивные
`$0`. Free tier явно отображается как `$0`; invoice провайдера имеет приоритет.

## Безопасность ключей

- plaintext ключа шифруется Windows DPAPI в контексте текущего пользователя;
- encrypted store: `data/integrations/ai_agent_keys.dpapi`;
- метаданные без ключей: `data/integrations/ai_agents.registry.json`;
- оба пути исключены из Git;
- HTTP API возвращает только маску вида `sk-****abcd`;
- ключ не попадает в usage log, error, telemetry или prompt history;
- URL с credentials и внешние HTTP endpoints отклоняются;
- `YOUR_API_KEY_HERE` и пустой ключ не принимаются при создании;
- ключ нельзя восстановить из UI; при редактировании можно только заменить его.

DPAPI привязан к Windows-пользователю. Перенос encrypted-файла на другой аккаунт
или компьютер не переносит доступ. Для миграции ключ вводится повторно через UI.

## Microsoft Foundry / Azure OpenAI

Для показанных deployments создаются два агента:

| Поле | Chat agent | Embedding agent |
|---|---|---|
| Provider | Microsoft Foundry / Azure OpenAI | Microsoft Foundry / Azure OpenAI |
| Endpoint type | `chat` | `embeddings` |
| Model / deployment | `gpt-5-mini` | `text-embedding-3-small` |
| Auth header | `api-key` | `api-key` |
| Role | например `coder` | `embedding` |

Можно вставить базовый resource URL или полный endpoint из **Endpoints and keys**.
Клиент распознаёт v1 Responses/Chat/Embeddings и legacy deployment URL и не
дописывает маршрут повторно. Сам ключ вводится только в локальном drawer.

Дата прекращения deployment/model на экране Foundry не равна сроку действия
студенческого гранта. Поле **Grant expiry** заполняется только датой из Azure
Cost Management / Sponsorship / Credits.

Рекомендуемый первый запуск:

1. создать агента выключенным;
2. выбрать account `Azure Student Grant ($100)` и тип `Grant / prepaid credit`;
3. выполнить **Test Connection** и проверить tokens/status;
4. включить модель только после успешного теста.

Inference API key не даёт приложению права читать Azure billing account. Поэтому
Azure balance синхронизируется ручным снимком из portal; приложение вычитает из
него только собственные последующие вызовы. Автоматический Azure balance потребует
отдельной Azure identity/RBAC-интеграции и не должен использовать model key.

## Grant, budget и стоимость

Это разные ограничения:

- **credit/grant** — внешний ресурс провайдера;
- **daily/monthly budget** — необязательный локальный предел расхода модели;
- **hard cap `$0.50/call`** — общий предел одного запроса;
- общий максимум конфигурации: `$10/day` и `$20/month` на агента.

Остаток считается так:

- без portal snapshot: `grant total − все локально учтённые вызовы`;
- после snapshot: `reported remaining − вызовы StratForge после snapshot`.

Для OpenRouter доступна синхронизация `/api/v1/credits`. Для Azure/OpenAI и
остальных providers, где billing требует другой уровень авторизации, используется
ручной snapshot. Локальная цифра не включает чужие приложения, налоги, региональные
коэффициенты и тарифицируемые tools/search/media.

Значение budget `0` означает monitoring-only без блокирующего денежного лимита.
Это не означает «деньги закончились». Когда цена известна и лимит положительный,
перед сетевым запросом клиент резервирует консервативную стоимость. Если дневной,
месячный, grant или single-call limit исчерпан, запрос не отправляется, агент
автоматически выключается, а причина показывается в UI. Повторное включение —
явное решение пользователя после изменения лимита или проверки billing portal.

Исключение — `paid_budget_usd` автономной миссии Orchestrator: значение `0`
означает `local/free only`, поэтому credit/payg-модели не допускаются к committee
этой миссии. Это ограничение не меняет budget карточки самого API-агента.

Несколько моделей одного `provider + account name` используют общий credit:
два Azure deployments не создают два отдельных гранта по `$100`. Несколько
Google AI Studio keys помещаются в общий `rotation_group` и получают priority.
Router уже выполняет failover: `429`, quota, timeout и `5xx` включают cooldown
для проблемного ключа и переводят запрос на следующий. VPN не используется.

## DeepSeek V4 Flash, V4 Pro и StratForge Orchestrator

На 2026-07-01 официальный DeepSeek API предоставляет `deepseek-v4-flash` и
`deepseek-v4-pro` через `https://api.deepseek.com`. В приложении
`deepseek-v4-pro` назначен платным critical tier Orchestrator, а
`deepseek-v4-flash` — экономичным strategy/review fallback. Обе карточки
используют один DeepSeek account и общий local hard budget `$5/month`; UI
показывает расход каждой модели и общий расход аккаунта. Простые задачи сначала
идут в бесплатный пул. Цены берутся из
централизованного catalog:

| Модель | Input cache hit / 1M | Input cache miss / 1M | Output / 1M |
|---|---:|---:|---:|
| DeepSeek V4 Flash | $0.0028 | $0.14 | $0.28 |
| DeepSeek V4 Pro | $0.003625 | $0.435 | $0.87 |

Источник: [официальная таблица DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing).

Thinking включается с `reasoning_effort=max` только для критических ролей:
`orchestrator`, `chief_agent` (legacy alias), `final_judge`, `risk_manager`,
`overfit_detector`. Лёгкие задачи
идут сначала в free/low-cost pool. Для thinking-запросов используется увеличенный
output allowance; если reasoning занял весь лимит, запрос отмечается ошибкой, но
фактически выставленные provider usage/cost всё равно записываются.

Provider context cache включён автоматически. Приложение держит стабильные
system/data prefixes и считает provider-reported cached tokens. Дополнительно
exact-response cache в памяти процесса (TTL 1 час) обслуживает только
повторяемые analysis/audit/review запросы; генерация, мутация, события и разговор
не кэшируются. UI показывает provider cache и effective cache отдельно.
Фиксировать 90% нельзя: hit rate зависит от повторяемости, минимальной длины
префикса и правил провайдера.
Фактический общий UI-показатель на 2026-07-02 — около `2.1%`; это baseline для
последующих циклов, а не повод подменять provider usage расчётной цифрой.

## Исправленные ошибки подключения 2026-06-30

- `daily budget = 0` больше не вызывает `daily_budget_exceeded`;
- полный Azure embedding endpoint используется без повторного `/embeddings`;
- `gemini-2.5-flash` автоматически использует `generateContent`, а не
  `embedContent`; для Gemini embeddings используются отдельные embedding models;
- GPT-5 Responses test использует minimal reasoning и достаточный output budget,
  чтобы короткий ответ не был полностью вытеснен reasoning tokens.

## Универсальный LLM-клиент

`app/ai_lab/universal_llm.py` поддерживает:

- OpenAI-compatible chat completions и embeddings через
  `base_url + api_key + model`;
- Microsoft Foundry / Azure OpenAI v1 и legacy deployment URL;
- Gemini `generateContent` и `embedContent`;
- custom auth headers `Bearer`, `api-key`, `x-api-key`, `x-goog-api-key`.

## OpenRouter free models

`deepseek/deepseek-v4-flash:free` и другие устаревшие `:free` slug сейчас часто
отклоняются провайдером. Для бесплатного режима без баланса используйте:

| Назначение | Model slug |
|---|---|
| Общий чат | `openrouter/free` |
| Код | `cohere/north-mini-code:free` |

Платный DeepSeek через OpenRouter: `deepseek/deepseek-v4-flash` (нужен баланс на
openrouter.ai). При сохранении агента устаревшие free-slug автоматически
переназначаются на `openrouter/free`.

## Z.AI / GLM

- general API: `https://api.z.ai/api/paas/v4`;
- Coding Plan endpoint не используется приложением без активного совместимого
  плана и не предназначен для general-purpose API integration;
- `glm-5.2` тарифицируется по официальному catalog и не маркируется permanent free;
- `glm-4.7-flash` и `glm-4.5-flash` автоматически маркируются free tier;
- trial-квота GLM-5.2 не считается фиксированным credit, пока Z.AI не возвращает
  доступный resource package или оператор не внесёт подтверждённый portal balance.

Роли подготовлены для: `orchestrator`, `chief_agent` (legacy), `coder`,
`strategy_analyst`, `backtest_analyst`,
`risk_manager`, `telegram_assistant`, `news_analyst`, `optimizer`,
`hypothesis_fallback`, `compile_error_fixer_fallback`, `embedding`, `general`.
Роль — назначение и будущая точка маршрутизации, не полномочие на действие.

## Usage audit

Файлы: `ai_lab/registry/agent_usage/YYYY-MM.jsonl` (gitignored). Записываются:

`timestamp_utc`, `request_id`, `agent_id/name`, `provider`, `model`, `role`,
`endpoint_type`, `input_tokens`, `cached_input_tokens`, `cache_miss_tokens`, `output_tokens`,
`total_tokens`, `cost_usd`, `status`, `elapsed_sec`, безопасная ошибка.

Prompt, response и API key не сохраняются. Если provider не вернул usage,
локальная стоимость может быть неполной; billing portal остаётся источником истины.

## Автоматическая маршрутизация AI Lab

Рабочий production-маршрут:

| Роль | Когда вызывается API | Право на verdict |
|---|---|---|
| `hypothesis` | Azure primary, затем Gemini/OpenRouter/local | нет |
| `coder`, `code_reviewer`, `compile_error_fixer` | Azure primary, затем OpenRouter/Gemini/local | нет |
| `backtest_analyst`, `optimizer` | Gemini pool, затем Azure/OpenRouter | нет |
| `risk_manager` | DeepSeek V4 Pro на critical tier, затем Azure/Gemini/free fallback | нет |
| `overfit_detector`, `final_judge` | DeepSeek V4 Pro на critical tier, затем safe fallback | нет |
| `orchestrator` | Auto: Gemini/Z.AI для light, free → DeepSeek Flash для standard, DeepSeek Pro → Flash для critical | только allowlist приложения |

Детерминированный renderer/validator/compile/backtest/arbitration остаётся
обязательным. На странице AI Lab видны активные requests, последние tokens/cost,
grant и порядок failover.

## HTTP API

| Метод | Маршрут | Назначение |
|---|---|---|
| GET | `/api/ai-agents` | безопасная сводка, catalog, budgets, usage |
| GET | `/api/ai-agents/usage?limit=N` | журнал без prompt/key |
| GET | `/api/ai-agents/{id}` | безопасная карточка агента |
| POST | `/api/ai-agents` | создать агента и сохранить ключ через DPAPI |
| POST | `/api/ai-agents/{id}` | изменить метаданные/заменить ключ |
| POST | `/api/ai-agents/{id}/toggle` | включить/выключить |
| POST | `/api/ai-agents/{id}/test` | явный тестовый API-вызов |
| POST | `/api/ai-agents/{id}/sync-balance` | поддерживаемая provider-синхронизация |
| POST | `/api/ai-agents/{id}/delete` | удалить метаданные и encrypted key |
| GET | `/api/ai-lab/orchestrator` | диалог, фактическая модель, миссия, budget/cache, allowlist, approvals |
| POST | `/api/ai-lab/orchestrator/message` | natural-language сообщение из локального UI |
| GET | `/api/ai-lab/chief-agent` | legacy alias статуса Orchestrator |
| POST | `/api/ai-lab/chief-agent/mission` | historical-only миссия до 168 часов |
| POST | `/api/ai-lab/chief-agent/mission/state` | pause/resume/stop миссии |
| POST | `/api/ai-lab/chief-agent/tasks` | локальная задача/календарная запись |
| POST | `/api/ai-lab/chief-agent/audit` | аудит сегодняшних backtest |
| POST | `/api/ai-lab/chief-agent/proposals` | создать paper/demo proposal |
| POST | `/api/ai-lab/chief-agent/proposals/decision` | approve/reject proposal |

Все POST доступны только локальному UI/CLI и проходят существующую проверку JSON
Content-Type и same-origin. Реальные ключи нельзя помещать в тесты: используется
только `YOUR_API_KEY_HERE` или явно фиктивные значения.
