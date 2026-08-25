# Clean closeout — beta.38 accepted and live in Production

Дата проверки: `2026-08-25T18:40:00Z`.

## Current beta.38 cycle — accepted and promoted

Production больше не beta.29 и не beta.33: тот же самый immutable beta.38
artifact принят на Canary и без пересборки продвинут в Production.

- candidate `rc_dbd76fe013c341c382a3fe2b3b9fb5e8`;
- artifact `art_a426dbe3ae214d8a9854e9e92d052b31`;
- build `sf-0.10.0-beta.38-39c00b83d8ad-20260825T173719Z`;
- archive SHA256 `F0FDC106001AAAA4A79735F08DD388D02848597B2A850E8AB6A643262F22766A`;
- runtime/manifest SHA256 `BDCD96CEA12E4AEF0435A99C314AE7EE52F381DE766CD0C975A8212FF878D530`;
- clean SHA `39c00b83d8ad02b0d72b1845f2d575c93f08d465`, `dirty=false`.

Три исправления в этом цикле, каждое найдено на реальном оборудовании, а не в
тестах:

1. **Canonical owner.** Владелец определялся сравнением Telegram chat id с
   `NTA_TELEGRAM_CHAT_ID`; там, где переменная не экспортирована, канонический
   владелец попадал в registration-trial и получал 7-дневный trial (в beta.29 —
   `Free Preview`). Теперь единственный авторитет — `owner_claim()`: строка
   хранилища, канонический UUID, связанная provider identity, и только затем
   legacy chat id. Во всех трёх окружениях один и тот же
   `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f`, `owner/founder/unlimited`.
2. **QR login.** Popup удалён, контакт больше не обязателен. QR несёт
   `tg://resolve`, потому что iOS Camera не обрабатывает Universal Links и
   открывала Safari; https-ссылка осталась видимым fallback под QR. Жизненный
   цикл challenge стал явным `pending → opened → confirmed → consumed`:
   открытие повторяемо, тратит challenge только подтверждение и ровно один раз.
3. **Shared-bot routing.** Подтверждение перестало быть `callback_query`.
   Один бот обслуживает все окружения, Production владеет updates и маршрутизирует
   по тексту сообщения, а Production работал на beta.33, где обработчика
   login-callback нет вовсе. Нажатие приходило на Production, не совпадало ни с
   чем и терялось без изменения состояния. Теперь кнопка reply-keyboard
   отправляет свой label обычным сообщением — тем самым каналом, которым уже
   работает `/login [CANARY] CODE`.

Отдельно исправлен LOCAL logout: development подписывал владельца обратно при
каждом запросе, поэтому «Выйти» не работал и login flow нельзя было проверить
локально. Теперь logout ставит явный development-only hold, который снимается
реальным входом.

Acceptance: owner физически отсканировал Canary QR на iPhone, Telegram открылся
напрямую, нажатие `Подтвердить вход` автоматически авторизовало ожидающий
browser без reload и без контакта. Машинные доказательства, полный список PR и
открытые вопросы — в
[2026-08-25-beta38-qr-login-shared-bot-routing.md](../changelog/2026-08-25-beta38-qr-login-shared-bot-routing.md).

## Current beta.32 corrective cycle — 2026-08-24T16:33:38Z

PR #146 и deterministic-governance sync PR #147 прошли обязательные пять CI
jobs и были автоматически слиты в `main`; итоговый clean SHA
`8e83d4ccbad9d9fadf10109f0afdd6b3ce9fe6eb`. Из него один раз собран и
развёрнут только в Canary beta.31 artifact: candidate
`rc_ff501b06706b430d953a08d41b83b573`, artifact
`art_a519c4cf670c4d4c95b4e7d243bab330`, build
`sf-0.10.0-beta.31-8e83d4ccbad9-20260824T155841Z`, archive SHA256
`EC5F730C730BB764A7A4F4F98E756678A9086A6316C1BCAA7DEBB9ECCEA15EFF`,
runtime/manifest SHA256
`826625D73702EB8D63E5EF2ABE0F2B291AB1FB8616B3E3C52D4AA70E48B8E7EE`,
deployment `dep_89b9dde9b15e492ba177e33f8af7ffaf`.

Canary viewport/capacity correction прошла основную проверку: два
authenticated 36-chart клиента держались `13m26s`, оба завершили `36/36`
live; MNQ/MES TopstepX WebSocket `lastPrice` совпал с last-bar close и
цветным rendered marker в обоих клиентах. `/api/ready` — `20/20` HTTP 200,
загруженные `api.js`, `chart-engine.js` и `pages/desktop.js` byte-for-byte
совпали с clean SHA.

Однако acceptance не записан: при дополнительной смене MNQ `5m → 1m → 15m`
15m history request получил воспроизводимый HTTP 429. Авторитетные
PostgreSQL rate buckets показали `api.write=145–183/min` при лимите 120.
Первое расхождение — read-only consolidated endpoint
`POST /api/ops/runtime/bars/batch` ошибочно классифицировался как mutation.
Beta.32 меняет только его rate-limit class на `read`; TopstepX auth/session,
SignalR, history provider, cache/failover, rollover, realtime, candle и chart
rendering не меняются.

Локальные beta.32 gates завершены: full regression `1947 passed`, `32 skipped`,
`0 failed`; расширенный market-data/chart набор `167 passed`; первоначальный
targeted набор `70 passed`; custom runner `13/13`; Connector Debug build —
`0 warnings / 0 errors`; Python, JavaScript, CSP/secrets/Markdown,
External GPT Context и `git diff --check` — PASS.

В той же acceptance обнаружена отдельная честная UI-ошибка: внешний
Cloudflare ingress намеренно возвращает 404 для `/api/diagnostics`, но remote
Admin показывал активную кнопку и затем пустой `HttpError`. Beta.32 оставляет
этот security deny без изменений и на Canary/Production показывает кнопку
disabled с объяснением; безопасная Worker/Telegram/Connector сводка остаётся
доступной. Production по-прежнему beta.29 и не затрагивался.

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
| LOCAL | `0.10.0-beta.38` | `39c00b83d8ad02b0d72b1845f2d575c93f08d465` | not built | 2007 passed, 32 skipped, 0 failed |
| Canary | `0.10.0-beta.38` | `39c00b83d8ad02b0d72b1845f2d575c93f08d465` | `BDCD96CEA12E4AEF0435A99C314AE7EE52F381DE766CD0C975A8212FF878D530` | ACCEPTED; real iPhone QR → confirm → auto-login |
| Production | `0.10.0-beta.38` | `39c00b83d8ad02b0d72b1845f2d575c93f08d465` | `BDCD96CEA12E4AEF0435A99C314AE7EE52F381DE766CD0C975A8212FF878D530` | live/ready; same artifact, no rebuild |

Beta.34–beta.37 не продвигались: beta.34/35 остановились на реальном mobile QR,
beta.36/37 — на подтверждении, которое не пересекало границу окружений.

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
2026-08-24T22:50:07Z | Claude Code on the web по запросу owner | Пере-верифицирован beta.32 source на merge SHA 848579362f: 1948/31/0, compileall, 32 JS checks и git diff --check PASS; зафиксировано, что LOCAL browser smoke, artifact build, Canary и Production промоушен физически недостижимы из ephemeral remote-контейнера (нет runtime, egress 403, нет NinjaTrader).
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Удалён устаревший beta.20 handoff; зафиксированы фактические beta.27 Canary, beta.26 Production и исполнимый beta.28 closeout.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Зафиксирован реальный blocker canary_passed→approved_for_production в authoritative promotion gate; artifact 2790fb43 не продвигался, Production остался beta.26.
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Final beta.28 artifact принят в Canary и без пересборки продвинут в Production; точная identity, rollback slots, tests и chart evidence записаны в current handoff.
2026-08-23T02:27:02Z | GPT-5.5 через Codex по запросу owner | Заменён beta.28 handoff фактическим beta.29 closeout: PR/CI, exact artifact, Canary/Production deploy IDs, fan-out, responsive и owner browser evidence.
2026-08-23T21:36:03Z | GPT-5.5 через Codex по запросу owner | Opened the new verified-trial and per-user market-data admission cycle, recorded complete LOCAL automated evidence and retained exact redistribution, Authenticode and physical NinjaTrader blockers; beta.29 live environments remain unchanged.
2026-08-23T22:20:31Z | GPT-5.5 через Codex по запросу owner | Зафиксирован LOCAL acceptance нового trial/access candidate: 1943/32/0 и 10m56s двухклиентный MNQ/MES visual fan-out PASS; внешние Connector/redistribution gates сохранены.
2026-08-24T01:52:25Z | GPT-5.5 через Codex по запросу owner | Закрыт physical Development Connector acceptance: проверенный dev.14, сохранённое enrollment, heartbeat, MNQ/MES history/live, bounded transport drain без drops и безопасный demo-backtest; следующий gate — PR #144 CI.
2026-08-24T02:41:31Z | GPT-5.5 через Codex по запросу owner | PR #144 слит owner-authorized merge fb7d7f9b; на clean merge повторно подтверждены Connector heartbeat/history/live и demo-backtest #18782; VERSION подготовлен к единственному immutable beta.30 cycle.
2026-08-24T04:22:21Z | GPT-5.5 через Codex по запросу owner | Beta.30 Canary не принят после воспроизводимого saturation deep-history polling; Production сохранён на beta.29; открыт минимальный beta.31 viewport-range corrective cycle без изменения TopstepX/SignalR baseline.
2026-08-24T16:33:38Z | GPT-5.5 через Codex по запросу owner | Beta.31 Canary не принят после воспроизводимого chart-batch 429; зафиксирован 13m26s live baseline и открыт минимальный beta.32 rate/UI corrective cycle без Production promotion.
2026-08-25T18:40:00Z | Claude Opus 5 через Claude Code по запросу owner | Beta.38 принят и продвинут в Production тем же artifact: canonical owner во всех окружениях, QR/one-tap login без popup и контакта, явный challenge lifecycle и маршрутизация подтверждения через общий бот; beta.34–37 не продвигались.
-->
