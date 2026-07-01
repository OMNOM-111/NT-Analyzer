# AI Agents / API Keys: подключения, роли, ключи и бюджет

Актуально на 2026-07-01. Универсальный реестр теперь подключён непосредственно к
historical-only AI Lab через role-aware router. Итоговый benchmark и фактические
замеры: `docs/AI_AGENT_STACK_RESEARCH_2026-07-01.md`.

1. универсальный реестр **AI Agents / API Keys** для ручного подключения и
   проверки OpenAI, Microsoft Foundry / Azure OpenAI, DeepSeek, OpenRouter,
   Gemini, Mistral, Groq и Custom OpenAI-compatible API;
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

Несколько моделей одного `provider + account name` используют общий credit:
два Azure deployments не создают два отдельных гранта по `$100`. Несколько
Google AI Studio keys помещаются в общий `rotation_group` и получают priority.
Router уже выполняет failover: `429`, quota, timeout и `5xx` включают cooldown
для проблемного ключа и переводят запрос на следующий. VPN не используется.

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

Роли подготовлены для: `coder`, `strategy_analyst`, `backtest_analyst`,
`risk_manager`, `telegram_assistant`, `news_analyst`, `optimizer`,
`hypothesis_fallback`, `compile_error_fixer_fallback`, `embedding`, `general`.
Роль — назначение и будущая точка маршрутизации, не полномочие на действие.

## Usage audit

Файлы: `ai_lab/registry/agent_usage/YYYY-MM.jsonl` (gitignored). Записываются:

`timestamp_utc`, `request_id`, `agent_id/name`, `provider`, `model`, `role`,
`endpoint_type`, `input_tokens`, `cached_input_tokens`, `output_tokens`,
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
| `risk_manager`, `overfit_detector`, `final_judge` | Azure, затем OpenRouter/Gemini/local | нет |

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

Все POST доступны только локальному UI/CLI и проходят существующую проверку JSON
Content-Type и same-origin. Реальные ключи нельзя помещать в тесты: используется
только `YOUR_API_KEY_HERE` или явно фиктивные значения.
