# Live identity 1fae1f39 + server Documents/Charts fix

Дата записи: `2026-08-14` UTC. Это **не STAGE CLOSED**. Live Canary+Production
process identity for `1fae1f39` is proven. Authenticated page/chart PASS on the
Documents/Charts follow-up still needs a new signed artifact, DEV restart, and
an owner session.

## Operational HTTP identity (public `/live`, `/ready`, `/runtime/env`)

Canary и Production API отвечают одним signed artifact:

| Field | Value |
| --- | --- |
| Git SHA | `1fae1f3966dc53294b73772be47992d844575115` |
| Build ID | `sf-0.10.0-beta.1-1fae1f3966dc-20260814T052203Z` |
| Artifact SHA256 | `08265412DECF4D04962A14A0D17208BB7E67031F09AF62FB525634749B6B449B` |
| Version / channel | `0.10.0-beta.1` / `beta` |
| Canary | `https://canary.stratforges.com`, `instance=stratforge-canary-01`, `/ready` `ok` including `telegram_consumer` and `queue` |
| Production | `https://app.stratforges.com`, `instance=stratforge-linux-production-01`, `/ready` `ok` including `telegram_consumer` and `queue` |

Host SSH (`ssh-canary.stratforges.com` via Cloudflare Access) доказал active
symlink **и** `/proc/<pid>/cwd` для всех восьми app-процессов:

| Slot | Path |
| --- | --- |
| `canary-current` = `current` | `/home/stratforge/production_data/releases/0.10.0-beta.1-1fae1f3966dc` |
| `canary-previous` = `previous` | `/home/stratforge/production_data/releases/0.10.0-beta.1-0f2a90ead358` |

`same_release_dir=true`. Canary `api` / `worker-canary` / `operations-canary` /
`telegram-canary` и Production `api-app` / `worker` / `operations` / `telegram`
все имеют `cwd` в `.../0.10.0-beta.1-1fae1f3966dc`; Python app `exe` is
`/usr/bin/python3.12` (venv `.venv/bin/python`). Operations wrappers are bash
launchers whose cwd is the same release directory.

**`0f2a90ea` contradiction:** это previous-slot artifact
`0.10.0-beta.1-0f2a90ead358` (git `0f2a90ead358ddf725291709792f535ca4fb9bf4`,
предок `1fae1f39` в `main`, PR #35). Ни один RUNNING app-процесс не имеет cwd
в previous slot.

Production telegram env already has
`STRATFORGE_CANARY_INTERNAL_ORIGIN=http://127.0.0.1:18765`.

Local DEV `http://127.0.0.1:8765` в этой сессии не слушает. Unauthenticated UI
shell (`/ui/` mode picker, `/ui/desktop.html`) у Canary и Production совпадает.
Authenticated page-by-page sweep и живой TopstepX history/realtime на сервере
после Documents/Charts follow-up ещё требуют нового artifact и owner-сессии.

## Repository defects found on that live artifact

Live Production owner session (предыдущий Codex прогон) показал:

1. `/api/admin/releases` и `/api/documents` — HTTP 500 `Unknown repository`,
   потому что `production_storage.core.REPOSITORIES` не содержал `releases` и
   `doc_specs`.
2. Charts endpoint возвращал `workspace_runtime_not_connected` / пустой warning
   object: `runtime_stub` глотал `/api/ops/runtime/bars*`, а server-environment
   ветка `_market_bars_payload` не вызывала TopstepX.

## Repository fix in this change set (not yet the live artifact)

- Allowlist: `releases`, `doc_specs`.
- Chart paths больше не stub'ятся для personal workspace без NinjaTrader.
- Во всех environment, включая Canary/Production: TopstepX → свежий Connector
  snapshot → другой credentialed live provider → OFFLINE.
- Регрессии: `test_document_repository_allowlist_covers_live_modules`,
  `test_runtime_stub_does_not_swallow_independent_chart_paths`,
  `test_server_environment_uses_topstepx_when_connector_snapshot_is_missing`.
- Optional host env: `STRATFORGE_CANARY_INTERNAL_ORIGIN=http://127.0.0.1:18765`
  для Production telegram forward в обход Cloudflare 1010. Live
  `production-app.env` already has this value.

Этот фикс **ещё не** является live `1fae1f39`. Нужен новый signed artifact и
тот же путь DEV → CANARY → PRODUCTION, затем `/proc` identity на новом SHA и
живой TopstepX history/realtime на сервере.
