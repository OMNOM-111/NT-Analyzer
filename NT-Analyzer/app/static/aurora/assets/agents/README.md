# Agent face assets

One webm per agent. UI shows paused frame; hover and live reply play it.

In StratForge Orchestrator chat, hovering an assistant message face also
reads the message aloud (OpenAI Speech `tts-1` by default; browser
`speechSynthesis` fallback). See `docs/AGENTS.md` § avatar TTS and
`app/ai_lab/agent_tts.py`.

Masters: repo `/Agents/<Имя>/`.

| id | file |
| --- | --- |
| vitek | speaking.webm |
| marina | speaking.webm |
| tolik | speaking.webm |
| nikita | speaking.webm |
| ivan | speaking.webm |
| manager | speaking.webm |

`secretary` / `deputy` resolve to `manager` in UI and `domain_agents._avatar_paths`.
