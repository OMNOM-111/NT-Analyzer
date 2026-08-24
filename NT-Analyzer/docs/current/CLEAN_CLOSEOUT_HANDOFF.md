# Clean closeout — beta.30 Canary rejected; beta.31 correction in Development

Дата проверки: `2026-08-24T04:22:21Z`.

## Current beta.31 corrective cycle — 2026-08-24T04:22:21Z

PR #145 слит owner-authorized merge
`27184197ea5d495b8e0d90d0cc5c06d6539f7ab9`; все пять mandatory CI jobs
были зелёными. Из clean merge один раз собран beta.30 artifact
`art_6ae472715d594d99a55a0c0efbb1ebf6`: build
`sf-0.10.0-beta.30-27184197ea5d-20260824T035054Z`, archive SHA256
`7A4B23D15BCF2DBCFA95CD2E9C091D59857BDFC60D45A56B84FA1E7A74779BF3`,
runtime/manifest SHA256
`B958DE90A2211B84C5F38D87BE202392A300D4482F0C8F6EDDAF443E59227F98`.

Canary deployment `dep_dd7c5ac3c9d94f6f9c85baa8616a16ff` **не принят**.
Два одновременных 36-chart layout визуально оставались `36/36 live`, а общий
browser fan-out держал ровно два WebSocket, но deep-history polling постепенно
занял все 24 bounded HTTP handler slots; `/api/ready` и Admin начали отвечать
503. Acceptance не записывался, beta.30 в Production не продвигался;
Production остаётся на принятом beta.29.

Воспроизведённая причина ограничена consumer adapter: viewport
`start_time/end_time` не передавались в существующий gateway endpoint, поэтому
клиент повторно получал latest chunk вместо следующего диапазона. Beta.31
передаёт эти две границы и возвращает уже вычисленные gateway metadata
`cache_hit/chunks/history_exhausted`. TopstepX auth/session, SignalR,
history provider, cache/failover, rollover, realtime и chart rendering не
менялись.

LOCAL с тем же `STRATFORGE_API_MAX_INFLIGHT=24`: два одновременных 36-chart
клиента держались `10.26 min` и завершили `36/36 external_live + live marker`;
readiness probes — `20/20` HTTP 200; admission peak `8`, rejected `0`;
consumer direct provider/auth/loginKey `0`, общий upstream SignalR `1`.
Финальный MNQ/MES sample в обоих клиентах точно совпал по WebSocket price →
last close → цветному rendered marker. Чистый regression является последним
LOCAL gate перед beta.31 PR/CI и новым immutable release cycle.

Чистый LOCAL gate завершён: full regression `1946 passed`, `32 skipped`,
`0 failed`; custom runner `13/13`; targeted market-data/gateway + governance/
docs `121 passed`; bridge Debug build `0 warnings / 0 errors`; compileall, 22
JavaScript syntax checks, CSP, secrets, Markdown, Context Pack и
`git diff --check` — PASS.

## Previous beta.30 release preparation — 2026-08-24T02:41:31Z

Beta.29 ниже остаётся неизменённым accepted live baseline. На ветке
`codex/release-beta30-20260824` из clean `main` merge
`fb7d7f9b973a77efde629c75ab97daf82dbeafce` готовится versioned beta.30 release:

- anonymous blurred/preview entry удалён;
- verified human registration получает один полный 7-дневный trial;
- owner продлевает trial по дням или точной UTC-дате с before/after history;
- после expiry аккаунт остаётся активным и может настроить собственный
  TopstepX/NinjaTrader;
- HTTP и browser WebSocket используют единый scoped market-data admission;
- owner TopstepX history/SignalR/cache/failover baseline не рефакторился.

LOCAL automated evidence: `1945 passed`, `32 skipped`, `0 failed`; custom
runner `13/13`; bridge Debug build `0 warnings / 0 errors`; compileall, 22
Aurora JavaScript syntax checks, CSP/secret/Markdown/link, External GPT Context
и `git diff --check` — PASS.

LOCAL browser evidence: два одновременных клиента держали MNQ 5m и MES 5m
`10m56s`; WebSocket `lastPrice`, close последнего бара и фактически
отрисованный цветной right-side marker совпали в обоих клиентах. Fan-out peak:
`browser_ws=2`, `logical=4`, `wire=2`, общий upstream `signalr=1`, direct
provider/auth/loginKey `0`; после закрытия browser/logical/wire вернулись к
нулю. Загруженные `api.js`, `ui.js`, `chart-engine.js`, `pages/desktop.js`
совпали с disk bytes, service worker отсутствует.

Physical Development Connector acceptance также PASS. После owner save/close
NinjaTrader установлен проверенный `0.4.1-dev.14`; enrollment/device key
сохранены, signed hello/heartbeat приняты, MNQ/MES 5m history/live дошли до
gateway. Доказанный transport-дефект «одна отправка перед 15-секундным
long-poll» исправлен bounded burst drain: за `3m02s` source sequence
`110 → 375`, `drops=0`, `transport_errors=0`. Безопасный demo-backtest
`#18781` завершил 28 синтетических сделок и не создавал реальных ордеров.

PR #144 прошёл mandatory CI и слит owner-authorized merge commit
`fb7d7f9b973a77efde629c75ab97daf82dbeafce`. На этом clean SHA повторно
подтверждены signed Connector hello/heartbeat, непрерывные MNQ/MES history/live
batches и безопасный UI demo-backtest `#18782` без реальных ордеров. Следующий
gate — versioned beta.30 release-preparation PR, затем один signed immutable
artifact. Cross-user shared trial feed остаётся `EXTERNAL BLOCKED` без
письменного provider/exchange redistribution authority; публичный Production
Connector package требует разрешённого Authenticode tool/material. На момент
этой предыдущей подготовки Canary и Production не менялись и оставались beta.29.

## Current release identity

| Environment | Version | Git SHA | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- |
| LOCAL | `0.10.0-beta.31` | base `27184197ea5d495b8e0d90d0cc5c06d6539f7ab9` + scoped correction | not built | 10.26-minute two-client/capacity PASS; PR/CI pending |
| Canary | `0.10.0-beta.30` | `27184197ea5d495b8e0d90d0cc5c06d6539f7ab9` | `B958DE90A2211B84C5F38D87BE202392A300D4482F0C8F6EDDAF443E59227F98` | NOT ACCEPTED; readiness saturated; candidate `canary_checking` |
| Production | `0.10.0-beta.29` | `4d15f1d2250e2c52bde02b902d88ec7aad043543` | `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379` | live/ready + owner UI/charts/responsive PASS |

Accepted Production baseline identity:

- candidate `rc_a7c6c0afb95d410f92474614efeb1b35`;
- artifact `art_ccaadc3a536e4272809d32073f072918`;
- build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`;
- archive SHA256 `882FF3520DDD43BF65925F3DFA5AA95DA56107336DA98EFDC64146A81981195B`;
- runtime/manifest SHA256 `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`;
- active Production release directory
  `/home/stratforge/production_data/releases/0.10.0-beta.29-4d15f1d2250e`;
- Production rollback: `0.10.0-beta.28-36600dba3d73`.

## Acceptance evidence

- [PR #142](https://github.com/OMNOM-111/NT-Analyzer/pull/142) mandatory CI:
  all five required jobs green; merge SHA `4d15f1d2250e`.
- Targeted market/chart/Operations/responsive regression: `251 passed`.
- Full regression: `1924 passed`, `32 skipped`, `0 failed`.
- `compileall`, 32 JavaScript syntax checks, CSP/secret/Markdown/link scans,
  external-context validation and `git diff --check`: PASS.
- Expected skips: 31 real-PostgreSQL-DSN integration checks and 1 Windows
  bash-syntax check.
- Development load: 12 pages / 24 charts across three isolated profiles;
  `browser_ws 14→2`, `logical 22→4`, `wire=2`, `signalr=1`, direct/loginKey=0.
- Responsive matrix: 84/84 page/viewport checks from 2560×1440 to 360×800;
  real mobile pointer journeys and whole-document overflow checks PASS.
- Canary large layout: 36 charts; second client, Documents and MNQ 5m/15m
  smoke PASS. Production two-client MES/MNQ smoke produced matching closes and
  colored live markers; mobile/tablet whole-document overflow was zero.
- Canary deployment `dep_de061542f96641e1a10b7bb4456c2df0` and Production
  deployment `dep_8716b7cf463f4cf8af092ba6a4e5bdae`:
  external PASS, identity/readiness/signature verified,
  `same_immutable_artifact=true`, no rebuild and no pending migration.

## Product boundary

TopstepX remains the primary independent read-only history/realtime chart
source. NinjaTrader remains the execution/backtest/runtime truth and was kept
OFF during independent TopstepX chart acceptance. The current Development
Connector device then completed physical install/enrollment/heartbeat,
MNQ/MES history/live and safe no-order demo-backtest acceptance. A public
Production Connector package remains externally blocked on authorized
Authenticode material, not on runtime protocol behavior.

Google OAuth, transactional e-mail and legal publication remain their existing
`EXTERNAL BLOCKED` / `IN DEVELOPMENT` boundaries. Legal documents remain DRAFT.

Canonical operational evidence:
[2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Удалён устаревший beta.20 handoff; зафиксированы фактические beta.27 Canary, beta.26 Production и исполнимый beta.28 closeout.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Зафиксирован реальный blocker canary_passed→approved_for_production в authoritative promotion gate; artifact 2790fb43 не продвигался, Production остался beta.26.
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Final beta.28 artifact принят в Canary и без пересборки продвинут в Production; точная identity, rollback slots, tests и chart evidence записаны в current handoff.
2026-08-23T02:27:02Z | GPT-5.5 через Codex по запросу owner | Заменён beta.28 handoff фактическим beta.29 closeout: PR/CI, exact artifact, Canary/Production deploy IDs, fan-out, responsive и owner browser evidence.
2026-08-23T21:36:03Z | GPT-5.5 через Codex по запросу owner | Opened the new verified-trial and per-user market-data admission cycle, recorded complete LOCAL automated evidence and retained exact redistribution, Authenticode and physical NinjaTrader blockers; beta.29 live environments remain unchanged.
2026-08-23T22:20:31Z | GPT-5.5 через Codex по запросу owner | Зафиксирован LOCAL acceptance нового trial/access candidate: 1943/32/0 и 10m56s двухклиентный MNQ/MES visual fan-out PASS; внешние Connector/redistribution gates сохранены.
2026-08-24T01:52:25Z | GPT-5.5 через Codex по запросу owner | Закрыт physical Development Connector acceptance: проверенный dev.14, сохранённое enrollment, heartbeat, MNQ/MES history/live, bounded transport drain без drops и безопасный demo-backtest; следующий gate — PR #144 CI.
2026-08-24T02:41:31Z | GPT-5.5 через Codex по запросу owner | PR #144 слит owner-authorized merge fb7d7f9b; на clean merge повторно подтверждены Connector heartbeat/history/live и demo-backtest #18782; VERSION подготовлен к единственному immutable beta.30 cycle.
2026-08-24T04:22:21Z | GPT-5.5 через Codex по запросу owner | Beta.30 Canary не принят после воспроизводимого saturation deep-history polling; Production сохранён на beta.29; открыт минимальный beta.31 viewport-range corrective cycle без изменения TopstepX/SignalR baseline.
-->
