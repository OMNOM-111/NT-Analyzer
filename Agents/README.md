# Аватары сотрудников StratForge

Только анимации (webm). Пауза на первом кадре = обычный аватар;
наведение / набор ответа = проигрывание.

В чате **StratForge Orchestrator** наведение на аватар ответа дополнительно
озвучивает текст сообщения голосом **профиля этого сотрудника** (OpenAI Speech
или browser fallback). Настройка: страница AI Agents → «Голоса сотрудников».
Канон: [NT-Analyzer/docs/AGENTS.md](../NT-Analyzer/docs/AGENTS.md)
§ «Озвучка сообщения».

Исходники: папка `Agents/` в корне репозитория.

| Папка | Файл | id |
| --- | --- | --- |
| `Виктор/` | `v_1.webm` | `vitek` |
| `Марина/` | `m_1.webm` | `marina` |
| `Толик/` | `avatar_*.webm` | `tolik` |
| `Никита/` | `n_1.webm` | `nikita` |
| `Иван/` | `i_1.webm` | `ivan` |
| `Управляющий/` | `u_1.webm` | `manager` (+ Секретарь/Заместитель) |

Рабочие копии:

`NT-Analyzer/app/static/aurora/assets/agents/<id>/speaking.webm`

После замены исходников скопируйте файл как `speaking.webm`.
Карта: [NT-Analyzer/docs/AGENTS.md](../NT-Analyzer/docs/AGENTS.md).
