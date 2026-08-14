# Live release 77e8645f — Documents/Release Center and server TopstepX

Дата записи: `2026-08-14T17:12:00Z`. **STAGE CLOSED** for the Documents/Charts
server defects found on live `1fae1f39`. LOCAL / CANARY / PRODUCTION execute
the same signed artifact. Google OAuth and Production transactional email stay
`EXTERNAL BLOCKED`.

## Exact identity

| Field | Value |
| --- | --- |
| Git SHA | `77e8645f1725d20545992efdeabafdf2f3d0e684` |
| Merge | [PR #37](https://github.com/OMNOM-111/NT-Analyzer/pull/37) into `main` |
| CI | `ci` workflow run `31820399515` green on the merge SHA |
| Version / channel | `0.10.0-beta.1` / `beta` |
| Build ID | `sf-0.10.0-beta.1-77e8645f1725-20260814T164341Z` |
| Archive SHA256 | `DBC79FC6834C82AC383240ED03C1A505C1367AEB2DE0D02DBDD17BBCAE4F2980` |
| Manifest / public `artifact_sha256` | `1F0C95E48447632CB97EF88A85E38354D6A71AC32C41285600DACA182A8748C6` |
| Executor ref | `0.10.0-beta.1-77e8645f1725` |
| `canary-current` = `current` | `/home/stratforge/production_data/releases/0.10.0-beta.1-77e8645f1725` |
| previous slot | `/home/stratforge/production_data/releases/0.10.0-beta.1-1fae1f3966dc` |
| `same_release_dir` | true |

DEV `http://127.0.0.1:8765` reports the same git SHA, `channel=dev`,
`build_id=dev-0.10.0-beta.1-77e8645f1725`, `dirty=false`.

## `/proc/<pid>/cwd`

All eight app processes cwd the active slot. Python `exe` is `/usr/bin/python3.12`
(`.venv/bin/python`). Operations wrappers are bash launchers in the same directory.

| Program | Slot |
| --- | --- |
| Canary `api` / `worker-canary` / `operations-canary` / `telegram-canary` | `.../0.10.0-beta.1-77e8645f1725` |
| Production `api-app` / `worker` / `operations` / `telegram` | `.../0.10.0-beta.1-77e8645f1725` |

## Owner acceptance (authenticated)

| Check | DEV | CANARY | PRODUCTION |
| --- | --- | --- | --- |
| `/api/documents` | 200 `ok` | 200 `ok` | 200 `ok` |
| `/api/admin/releases` | 200 | 200 `environment=canary` `adapter=dry_run` | 200 `environment=production` |
| MNQ 5m bars, NT unavailable | TopstepX live | TopstepX `LIVE`, 20 bars, `MNQ 09-26` | TopstepX `LIVE`, 20 bars, `MNQ 09-26` |

Canary first returned OFFLINE because TopstepX credentials and remote-authorization
flags were absent on the host. After owner-authorized env overlay
(`NTA_TOPSTEPX_USERNAME` / `API_KEY` from the local secrets store,
`NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED=1`,
`NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED=1`) history worked and realtime stayed
`CONNECTING` until `websockets==16.0` was installed into the release `.venv`
overlay (the signed zip does not contain `.venv`; each extract copies
`canary-current/.venv`). Second poll: `runtime_state=LIVE`, quote age ~0.13s.

Production promote used the **same** eight identity arguments as Canary. No
rebuild. Production owner Telegram login then repeated Documents / Release
Center / TopstepX PASS.

## Asset hashes

JS/CSS used by Overview, Desktop, Documents (`theme.css`, `ui.js`, `api.js`,
`charts.js`, `chart-engine.js`, `desktop.js`, `documents.js`, `overview.js`)
match across local git, DEV, Canary and Production. HTML shells match Canary
to Production; DEV HTML matches the git files (no server inject).

## Pages

HTTP 200 for `/ui/`, `/ui/desktop.html`, `/ui/documents.html`,
`/ui/strategies.html`, `/ui/backtesting.html`, `/ui/ai-lab.html`,
`/ui/trading.html`, `/ui/performance.html`. Authenticated API sweep for
instruments/accounts/positions/strategies returned 200 on all three
environments. In-app browser was not used (workspace hang rule; no browser MCP).

## Host overlays that are not in the signed zip

- TopstepX username/api key plus remote/redistribution authorization flags in
  `canary.env` and `production-app.env` (values never committed).
- `websockets==16.0` in `.../0.10.0-beta.1-77e8645f1725/.venv`.

`requirements.txt` now declares `websockets>=14,<17` so the next signed build
does not depend on silent venv drift. That line is documentation/packaging for
the next artifact; live code SHA remains `77e8645f`.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T17:12:00Z | Grok 4.6 через Cursor по запросу owner | STAGE CLOSED: live LOCAL/CANARY/PRODUCTION 77e8645f; Documents/Release Center 200; TopstepX history+realtime LIVE with NT unavailable.
-->
