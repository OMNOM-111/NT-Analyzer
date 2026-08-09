# StratForge — Production auth, Connector и TopstepX acceptance audit

История поправки: 2026-08-09T00:57:35Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: полный повторный аудит и исправление Google/email/Telegram auth, личного NinjaTrader Connector, TopstepX read-only market data и Production readiness.

Дата проверки: 2026-08-08 (UTC evidence: 2026-08-09).

Ветка реализации: `codex/architecture-production-acceptance-audit`.
Base commit: `b36c2875df1f46377b7e50e22333661f8e070783`.

## Итог

Локальная реализация и автоматизированная проверка завершены. Canary/Production
deployment, merge и операции с боевыми секретами не выполнялись: они требуют
отдельных owner approval gates.

Текущий публичный сервер **не содержит эти исправления**. Read-only HTTP-проверка
в окне 2026-08-09T01:00Z–01:10Z показала:

- `app.stratforges.com/api/live` — 200;
- `app.stratforges.com/api/ready` — 200 по старому набору компонентов;
- build `0.9.0-dev.15`, build date `2026-08-01`;
- environment `production`, но release channel `canary`, status `pre_release`;
- unauthenticated auth status всё ещё требует только Telegram;
- новый Google status публично недоступен в этой развёрнутой версии.

Поэтому текущий `ready=200` не доказывает готовность требований этого аудита:
развёрнутый build ещё не знает обязательные probes Google auth, email delivery,
Connector release catalog и independent market data.

## Матрица требований

| Контур | Локальная реализация | Автоматизированная проверка | Реальная внешняя приёмка |
|---|---|---|---|
| Первый вход через Google | Реализован OAuth login/link с canonical redirect, подписанным self-contained state, browser-bound HttpOnly cookie и обязательным `email_verified=true`; auto-merge по email отсутствует | PASS | BLOCKED: в проверенном local protected config нет client ID/secret/redirect; новая версия не развёрнута |
| Первый вход через отдельный email | Реализован шестизначный OTP через authenticated SMTP с STARTTLS/SSL; код не возвращается клиенту вне Development test-auth | PASS | BLOCKED: SMTP provider/credentials/from отсутствуют в проверенном protected config |
| Telegram login и OTP confirmation | Сохранён первый вход через одноразовый bot challenge; numeric OTP для step-up/new-device доставляется через Telegram bot и не возвращается клиенту; startup сверяет token с публичным username | PASS | PARTIAL/BLOCKED: Production bot/webhook и `getMe` отвечают, но новый numeric OTP код не развёрнут и реальная user-delivery не подтверждалась |
| Личный NinjaTrader: два фактора | Pairing/default-account/live-capability требуют подтверждённые Telegram + email; Google считается email-фактором только по verified Google identity; step-up одноразовый, action/user/environment-bound | PASS | BLOCKED до реального входа пользователя и Connector acceptance |
| Кнопка «Подключить свой NinjaTrader» | Setup payload берёт immutable stable artifact из проверенного release catalog; UI спрашивает consent до download и объясняет Setup/UAC; Setup автоматизирует компоненты/updater; фиктивная ссылка удалена | PASS + 13 installer probes | BLOCKED: собранные local binaries `NotSigned`; опубликованный stable catalog/URL и end-user install не предъявлены |
| Режим NinjaTrader account | Heartbeat передаёт masked account summaries; runtime classifier различает `paper/demo/live/playback/unknown`, unknown не становится live; updater ждёт safe restart и rollback при failed health | PASS + .NET build + 15 updater probes | BLOCKED: нет доказанного heartbeat от owner Windows VM и отдельной внешней установки после этой версии |
| TopstepX для графиков | ProjectX auth, root→active/exact contract search, REST bars и SignalR reconnect; provider read-only, trade routing отсутствует | PASS на contract tests с mock provider | BLOCKED: нет реальных username/key в активной проверенной конфигурации; remote/public policy не разрешена |
| Графики без NinjaTrader | Production charts вызывают независимый failover при отсутствии/просрочке Connector; cache TTL позволяет восстановившемуся провайдеру быть повторно вызванным | PASS | BLOCKED до реального лицензированного provider call и теста с остановленным NinjaTrader |
| Production fail-closed | Preflight/readiness требуют Google, authenticated TLS SMTP, Telegram token+webhook secret, stable Connector catalog и licensed independent chart feed | PASS | BLOCKED до Canary/Production provisioning и deployment |

## Что именно было исправлено

### Authentication и подтверждения

- Добавлен отдельный delivery layer для SMTP и Telegram OTP.
- Production email challenge активируется только после успешной отправки; при
  delivery failure challenge инвалидируется, API возвращает 503.
- Code/magic token никогда не попадает в Production response.
- Google redirect в Canary/Production строится только из
  `STRATFORGE_PUBLIC_ORIGIN`, а не из клиентских Host/forwarded headers.
- OAuth state подписан HMAC, переносим между несколькими API instances и
  дополнительно привязан к initiating browser через callback-scoped HttpOnly
  SameSite cookie, чтобы исключить login CSRF.
- Google callback требует явно подтверждённый email.
- Google linking требует `email_verified=true`; профильные поля сами по себе не
  превращаются в security factor.
- Новое устройство и step-up используют реально доступный verified channel:
  Telegram, email или verified Google email.
- Production Telegram consumer при старте проверяет injected token через
  `getMe`, сверяет его с публичным `NTA_TELEGRAM_BOT_USERNAME` и только после
  этого публикует username для одноразовых first-login deep links; readiness
  отдельно требует Telegram consumer и OTP delivery.

### TopstepX read-only market data

- Унифицированы canonical и legacy credential names:
  `NTA_TOPSTEPX_USERNAME|NTA_TOPSTEP_USERNAME` и
  `NTA_TOPSTEPX_API_KEY|NTA_TOPSTEP_API_KEY`.
- Удалена ошибочная зависимость status от `NTA_TOPSTEP_ACCOUNT_ID`.
- Contract search передаёт обязательный `live`; retrieve-bars передаёт
  `contractId`, `live`, `startTime`, `endTime`, `unit`, `unitNumber`, `limit` и
  `includePartialBar`.
- При отсутствии NinjaTrader и его catalog корневой символ (`MNQ`) разрешается
  по `activeContract` и `symbolId` ответа ProjectX в явный контракт (`MNQ 09-26`),
  поэтому независимый chart path не требует запущенного терминала.
- SignalR обработчики принимают официальный `(contractId, data)` callback и
  повторно подписываются после reconnect.
- Provider не содержит account/order/trade methods; chart source не становится
  execution authority.
- Production chart path теперь использует лицензированный independent failover
  при отсутствии или stale Connector snapshot.
- Cache key учитывает provider readiness, а payload cache имеет короткий TTL,
  чтобы recovery не блокировался старым offline snapshot.
- Production readiness больше не принимает одно наличие credentials: первый
  probe асинхронно выполняет реальный read-only bars-call, запоминает только
  secret-free результат и становится зелёным после валидного ответа. На
  закрытом рынке stale bars подтверждают reachability, но не превращаются в
  live price marker.

Официальная документация подтверждает username + API key authentication,
обязательные поля contract/bars запросов и SignalR market hub:
[authentication](https://gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key/),
[contract search](https://gateway.docs.projectx.com/docs/api-reference/market-data/search-contracts/),
[retrieve bars](https://gateway.docs.projectx.com/docs/api-reference/market-data/retrieve-bars/),
[realtime](https://gateway.docs.projectx.com/docs/realtime/).

### Connector и установка

- `/api/bridge/setup` больше не возвращает постоянную hardcoded блокировку:
  stable artifact появляется только при валидном release catalog.
- Браузер скачивает пакет после consent; скрытая установка не обещается. Setup
  автоматически выполняет допустимую часть установки после явного запуска/UAC.
- Connector отправляет только masked structured account summaries.
- Telemetry/runtime account classifier больше не считает неизвестный account
  live по умолчанию.

## Точная причина статуса «TopStep не настроен»

В проверенном локальном secrets/config store не найдено ни одного TopstepX или
ProjectX setting. В частности отсутствуют username и API key под обоими
поддерживаемыми наборами имён. Значит ранее добавленный ключ либо был сохранён в
другом контуре/файле, либо не был доставлен в активный runtime environment.
Значение ключа в Git/документации/чат переносить нельзя.

Даже после передачи credentials публичный Linux server остаётся fail-closed:
Topstep прямо запрещает VPS/VPN/remote servers, а ProjectX Terms задают personal
use и запрещают неразрешённое коммерческое использование/распространение.
Источники: [TopstepX API Access](https://help.topstep.com/en/articles/11187768-topstepx-api-access),
[ProjectX Terms](https://www.projectx.com/terms).

Для именно TopstepX на публичных графиках нужно письменное разрешение Topstep/
ProjectX одновременно на remote-server execution и отображение/redistribution
market data пользователям StratForge. Только после него можно записать в
protected Production config:

~~~text
NTA_ENABLE_TOPSTEPX_MARKET_DATA=1
NTA_TOPSTEPX_USERNAME=<protected>
NTA_TOPSTEPX_API_KEY=<protected>
NTA_TOPSTEPX_DATA_MODE=sim|live
NTA_TOPSTEPX_REMOTE_SERVER_AUTHORIZED=1
NTA_TOPSTEPX_REDISTRIBUTION_AUTHORIZED=1
~~~

Если такого разрешения не дадут, TopstepX можно использовать только в
разрешённом personal-device контуре, а публичному серверу нужен лицензированный
server-side feed, например настроенный Databento entitlement.

## Verification evidence

- Baseline до изменений: `1202 passed, 31 skipped`.
- Финальный regression: `1225 passed, 31 skipped in 154.81s`.
- Focused auth/security: `207 passed`.
- .NET 4.8 Release build: Bridge, Setup, Updater и ConnectorInteropHarness —
  0 warnings, 0 errors.
- Connector interop probe: P-256/SHA-256 C#↔Python signatures, challenge proof,
  DPAPI reload и strict Production config — PASS.
- Standalone Setup probe: install/repair/migration consent/tamper rejection/
  uninstall/deep-link/DPAPI — `13/13 PASS`.
- Standalone updater probe: safe-restart deferral, N→N+1, authenticated health,
  failed-health rollback и private-key preservation — `15/15 PASS`.
- `python -m compileall -q app tools` — PASS.
- `node --check app/static/aurora/assets/pages/topstep.js` — PASS.
- `python tools/release_static_scan.py --scan all` — CSP, SECRETS, MARKDOWN PASS.
- `git diff --check` — PASS.
- Local build Authenticode: Bridge/Setup/Updater — `NotSigned`, поэтому release
  publication закономерно BLOCKED.

## Действия owner/external перед публикацией для всех

1. Защищённо добавить Google OAuth client ID/secret и canonical redirect
   `https://app.stratforges.com/api/auth/google/callback`.
2. Подключить transactional SMTP с username/password, STARTTLS/SSL и verified
   From domain; выполнить реальный inbox OTP acceptance. В Production env задать
   `NTA_TELEGRAM_BOT_USERNAME=StratForgeAI_bot` рядом с защищёнными bot token и
   webhook secret, затем выполнить реальный Telegram OTP acceptance.
3. Получить письменное Topstep/ProjectX разрешение либо выбрать licensed
   server-side feed. Затем передать username/API key через protected secret
   provider, не сообщением в чате.
4. Выпустить Authenticode-signed stable Connector archive/manifest, опубликовать
   immutable URL в release catalog и проверить чистую установку на отдельном ПК.
5. Подтвердить online heartbeat owner Windows VM и выполнить acceptance
   `NinjaTrader stopped → charts remain live from independent provider`.
6. После merge создать один immutable candidate, развернуть в Canary, пройти
   реальные Google/email/Telegram/TopstepX/Connector smoke и только отдельным
   owner approval продвинуть тот же SHA/artifact в Production.

До выполнения пунктов 1–6 итоговый статус: **IMPLEMENTATION COMPLETE;
PRODUCTION EXTERNAL ACCEPTANCE AND DEPLOYMENT BLOCKED — STAGE NOT CLOSED**.
