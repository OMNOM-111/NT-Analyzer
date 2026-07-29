# Карта агентов StratForge

Актуально на 2026-07-15. Это **входной документ** по всем in-app агентам.
Остальные файлы ниже — канон по своей теме; не дублируйте сюда длинные
процедуры.

## Три разных «агента» — не путать

| Что | Где живёт | Документ |
| --- | --- | --- |
| **Сотрудники приложения** (Витёк, Управляющий, Марина…) | чат Aurora / Telegram | этот файл + карточки ниже |
| **API Agents / ключи** (OpenAI, Azure, DeepSeek…) | `/ui/ai-agents.html` | [AI_LAB_CLOUD_AGENTS.md](AI_LAB_CLOUD_AGENTS.md) |
| **Каналы разработки** (Cursor, Codex, Claude…) | репозиторий | [governance/ROLES.md](governance/ROLES.md) |

Имя «Марина» — стабильная персона над Auto-маршрутизатором. Ключ в AI Agents —
отдельная учётная запись провайдера. Это разные сущности.

## Иерархия

```
Владелец
  └─ Виктор (Витёк) — правая рука, собеседник по умолчанию
       └─ Управляющий — организация исполнения
            ├─ Заместитель — альтернативная управленческая позиция (+ ярус `standard`)
            ├─ Секретарь — скорость и порядок (+ ярус `light`)
            └─ специалисты: Марина · Толик · Никита · Иван
```

Личности и манера: [`domain_agents.py`](../app/ai_lab/domain_agents.py); стандартные
голосовые профили: [`agent_tts.py`](../app/ai_lab/agent_tts.py).
`StratForge Orchestrator` — название **технического шлюза** (`chief_agent.handle_message`),
а не отдельный начальник над Витьком. Подробности маршрутизации:
[CHIEF_AI_AGENT.md](CHIEF_AI_AGENT.md). Поведение Витька, события, отдых, API:
[VITEK.md](VITEK.md). Публичный тон ответов: [AI_DIALOGUE_CONTRACT.md](AI_DIALOGUE_CONTRACT.md).

## Кто за что отвечает

| Участник | Роль | Как вызвать | Канон |
| --- | --- | --- | --- |
| **Виктор / Витёк** | итог перед владельцем, поручения, инциденты | по умолчанию; `Витёк, …` | [VITEK.md](VITEK.md) |
| **Управляющий** | координация, важные решения, `critical` | `Управляющий, …` или меню «Максимальная» | [AI_MANAGEMENT.md](AI_MANAGEMENT.md) |
| **Заместитель** | средние задачи, `standard` | `Заместитель, …` / «Стандартная» | [AI_MANAGEMENT.md](AI_MANAGEMENT.md) |
| **Секретарь** | быстрые справки, `light` | `Секретарь, …` / «Быстрая» | [AI_MANAGEMENT.md](AI_MANAGEMENT.md) |
| **Марина** | финансы, ledger, P&L | `Марина, …` | [AI_ACCOUNTANT.md](AI_ACCOUNTANT.md) |
| **Толик** | жизненный цикл стратегий, бэктест | `Толик, …` | [AI_STRATEGY_ANALYST.md](AI_STRATEGY_ANALYST.md) |
| **Никита** | новости и влияние на стратегии | `Никита, …` | [AI_NEWS_AGENT.md](AI_NEWS_AGENT.md) |
| **Иван** | графики: снимок, линии, алерты | `Иван, …` или команда графика без имени | [AI_CHART_OPERATOR.md](AI_CHART_OPERATOR.md) |

Имя или роль должны стоять **в начале** сообщения. Обычное упоминание «финансов»
в середине фразы диалог не перехватывает. Выбор «Быстрая / Стандартная /
Максимальная» меняет только силу модели, а не персону: команда графика всё равно
уйдёт Ивану.

## Как устроен один ответ

1. Единый шлюз: приложение, Telegram и legacy endpoint → `chief_agent.handle_message`.
2. Адресация по имени → иначе Витёк.
3. Локальный `intent_classifier` + `capability_map` для известных операций.
4. Профильный специалист или управленческий ярус / Orchestrator.
5. Один публичный ответ с именем фактического собеседника; `single_response=true`.

Законы: [LOCAL_AI_LAWS.md](governance/LOCAL_AI_LAWS.md) (`GOV-AI-*` про capability,
anti-refusal, authorship). Восстановление стратегии из карантина:
[STRATEGY_RECOVERY.md](STRATEGY_RECOVERY.md).

## Аватары

Исходники: `/Agents/<Имя>/*.webm`.  
UI: `app/static/aurora/assets/agents/<id>/speaking.webm`.

Пауза на первом кадре — обычный аватар; наведение — полный проигрыш;
пока пишется ответ или агент `working` — loop. Круг зумит лицо
(`object-position` + `scale`). При уменьшении движения анимация не запускается.

### Озвучка сообщения (hover в чате Orchestrator)

В чате StratForge Orchestrator наведение на аватар **ответа ассистента**
(`.orch-msg-face`) делает две вещи одновременно:

1. **Анимация** — `speaking.webm` крутится в loop, пока идёт речь.
2. **Речь** — читается текст соседнего `.orch-msg-body` голосом **профиля этого агента**.

#### Голосовые профили сотрудников

Каждый сотрудник (Виктор, Управляющий, Марина…) имеет отдельный голосовой профиль.
Он **не зависит** от chat-модели, которая написала ответ (DeepSeek / Gemini / GPT / local).

| Элемент | Значение |
| --- | --- |
| UI | `AI Agents` → блок «Голоса сотрудников Orchestrator» → «Настройки · Голос» |
| Хранение | `data/integrations/agent_voices.json` (без API-ключей; gitignored) |
| Defaults | `app/ai_lab/agent_tts.py` → `DEFAULT_PROFILES` |
| Пресеты | глубокий/спокойный/молодой мужской, строгий руководитель, мягкий/уверенный/молодой женский, спокойный аналитик, энергичный помощник, нейтральный |
| Endpoint list | `GET /api/ai-lab/domain-agents/voices` |
| Endpoint one | `GET /api/ai-lab/domain-agents/{id}/voice` |
| Save / reset | `POST .../voice`, `POST .../voice/reset` (только owner) |
| Preview | `POST .../voice/preview` (можно до сохранения, с draft-телом) |
| Catalog | `GET /api/ai-lab/tts/catalog` |
| Speak | `POST /api/ai-lab/orchestrator/speak` — подтягивает профиль по `agent_id` |
| Debounce | ~350 ms |
| Mouseleave / закрытие чата | сразу stop |
| TTS-модели | `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts` (instructions только у mini-tts) |
| Ключ | Порядок: `NTA_OPENAI_API_KEY` → OpenAI-агент → **Azure-агент с моделью Speech** (`gpt-4o-mini-tts` / `tts-1`, можно оставить `enabled=false` чтобы чат не брал её) → прочие Azure chat (угадывание деплоя на том же ресурсе) |
| Без ключа | badge `browser fallback` — onyx/nova **не** применяются; только системный speechSynthesis |
| Azure body | в JSON обязательно поле `model` (даже если deployment уже в URL) |
| Кэш | `data/runtime/tts-cache/` — ключ = agent+provider+model+voice+speed+style+instructions+language+text |
| Fallback | нет ключа / ошибка провайдера / provider=browser → `speechSynthesis` |
| Pitch | OpenAI не поддерживает — в UI не показывается как рабочий |
| CSP | `media-src 'self' blob:` обязателен — иначе браузер блокирует `blob:` MP3 и пишет `Failed to load because no supported source was found` |

**2026-07-16 — Azure `gpt-4o-mini-tts`:** добавлен агент `AGT-B8F24346E288`
(`tratforge-openai-1.openai.azure.com` … `/audio/speech`). Резолвер TTS предпочитает
Speech-модели даже при `disabled` (чтобы роутер чата их не выбирал). Live-проверка:
статус `TTS готов: Azure gpt-4o-mini-tts`, synthesize Виктора/Марины → `audio/mpeg`.
Chat-ключи (GPT-4.1, Gemini, gpt-5-mini без TTS-деплоя) по-прежнему не дают голос.

Стандартные голоса (канон: [`agent_tts.py`](../app/ai_lab/agent_tts.py)):

| id | Пол | Voice | Speed | Характер |
| --- | --- | --- | --- | --- |
| `vitek` | муж | onyx | 0.98 | тёплый уверенный «правая рука» |
| `manager` | муж | sage | 0.90 | строгий операционный директор |
| `deputy` | муж | fable | 0.96 | дипломатичный советник |
| `secretary` | жен | coral | 1.06 | быстрый дружелюбный помощник |
| `marina` | жен | nova | 0.93 | сдержанный финансовый контролёр |
| `tolik` | муж | echo | 0.97 | увлечённый скептичный исследователь |
| `nikita` | муж | ash | 1.02 | спокойный новостной брифинг |
| `ivan` | муж | alloy | 1.02 | короткий технический оператор |

Модуль: `app/ai_lab/agent_tts.py`.

| id | Портрет |
| --- | --- |
| `vitek` | Виктор |
| `marina` / `tolik` / `nikita` / `ivan` | специалисты |
| `manager` | Управляющий; Секретарь и Заместитель — тот же файл |

Подробнее: [`Agents/README.md`](../../Agents/README.md).
Модуль: `app/ai_lab/agent_tts.py`.

## Связанные технические документы

- [AI_LAB_CLOUD_AGENTS.md](AI_LAB_CLOUD_AGENTS.md) — ключи, роли pipeline, бюджеты
- [AI_STRATEGY_LAB_QUALITY.md](AI_STRATEGY_LAB_QUALITY.md) / [AI_STRATEGY_LAB_RUN_CONTROLS.md](AI_STRATEGY_LAB_RUN_CONTROLS.md) — sandbox AI Lab
- [AI_LAB_COMPETITIVE_FEEDBACK.md](AI_LAB_COMPETITIVE_FEEDBACK.md) — feedback ledger
- [AI_AGENT_STACK_RESEARCH_2026-07-01.md](AI_AGENT_STACK_RESEARCH_2026-07-01.md) — **архивный** benchmark (не operating guide)
- [PRODUCTION_READINESS_2026-07-13.md](PRODUCTION_READINESS_2026-07-13.md) — release-аудит

Исходники персон: `app/ai_lab/domain_agents.py` (`PERSONAS`, `MANAGEMENT`).
Диалог: `app/ai_lab/dialogue_policy.py`. Шлюз: `app/ai_lab/chief_agent.py`.
Витьёк: `app/vitek.py`.
