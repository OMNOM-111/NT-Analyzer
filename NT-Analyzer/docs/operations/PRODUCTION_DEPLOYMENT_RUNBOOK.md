# StratForge Production deployment runbook

Актуальная целевая схема содержит только два окружения: приватный Windows
Development и общий Linux Production. MacBook, публичный staging и отдельные
`api.*`/`admin.*`/`www.*` в эту схему не входят.

## Каноническое решение

| Элемент | Решение |
|---|---|
| Пользовательский origin | `https://app.stratforges.com` |
| Apex `stratforges.com` | не публиковать до появления отдельной landing page; redirect сейчас не нужен |
| API | same-origin `/api/*` |
| Connector | outbound TLS на `/connector/v1/*`; вводится Stage 3 |
| Origin listener | только `127.0.0.1:18765` |
| Edge/TLS | отдельный Cloudflare Named Tunnel на Linux Production |
| Service manager | `systemd --user`, не PM2 |
| Windows VM | owner Connector + NinjaTrader; не web/API server |
| Redis | отсутствует до доказанной необходимости |

Production не принимает wildcard Host, HTTP scheme, прямой origin request или
`X-Forwarded-*` от неизвестного peer. Приложение проверяет это повторно после
Cloudflare. Порт 18765 не открывается в firewall/router/security group.

## Обязательный release contract

Production deployment всегда подчиняется схеме `DEV → CANARY → PRODUCTION`:

1. DEV — локальная рабочая версия и источник готового релиза. Перед сборкой
   release требуется доказать чистый или намеренно сохранённый Git commit.
2. Из точного commit собирается один signed immutable artifact с manifest,
   archive SHA256, runtime/manifest SHA256, build id и Git SHA.
3. Этот artifact сначала разворачивается в CANARY. CANARY acceptance проверяет
   тот же код, UI/static assets, backend logic, Documents, Charts, функции и
   поведение, что и DEV. Различаться могут только environment-specific DB,
   secrets, sessions, cookies, origins, runtime config и state/artifact roots.
4. Только после полного CANARY PASS тот же release directory / artifact без
   rebuild и без изменения файлов продвигается в PRODUCTION.
5. PRODUCTION после promotion обязан быть функционально 1:1 с проверенным
   CANARY. Любое новое изменение после Canary acceptance требует нового
   commit, нового artifact и полного повторения цикла.

Запрещено: собирать отдельную Production-версию, копировать отдельные файлы,
делать частичный hotfix-deploy, менять код между CANARY и PRODUCTION или
лечить Production отличающимся artifact. Если обнаружен дефект, релиз
останавливается или начинается новый полный цикл.

### Обычный релиз выполняется кнопками в Release Center

Ручные SSH/Git-команды для обычного релиза не нужны. Owner открывает Release
Center на LOCAL DEV и проходит последовательность:

| Кнопка | Состояние после | Что происходит |
| --- | --- | --- |
| Новый релиз-кандидат | `draft` | проверяется чистый worktree и текущий commit |
| Собрать артефакт | `built` | bundle уходит на хост, там собирается и подписывается один immutable artifact |
| Проверить подпись | `signed` | сверяются archive/manifest SHA256, build id и Git SHA |
| Развернуть в Canary | `canary_checking` | blue/green на Canary, восемь стадий с их статусами на странице |
| Отметить проверку: PASS | `canary_passed` | owner подтверждает Canary после реальной проверки |
| Одобрить Production | `approved_for_production` | отдельный gate перед Production |
| Продвинуть в Production | `production_deploying` | **тот же artifact SHA** без пересборки |
| Подтвердить production_live | `production_live` | фиксация итога |
| Откатить Production | `rolled_back` | доступна из `production_live`, `production_deploying`, `production_failed` |

Если Canary-деплой упал, доступна кнопка «Повторить Canary (тот же артефакт)» —
пересборка не требуется, идентичность артефакта проверяется на каждой попытке.

Для работы кнопок на LOCAL DEV должны быть заданы
`STRATFORGE_RELEASE_DEPLOY_ADAPTER=stage9_ssh`, `STRATFORGE_RELEASE_SSH_HOST`,
`STRATFORGE_RELEASE_SSH_USER`, `STRATFORGE_RELEASE_SSH_KEY`,
`STRATFORGE_RELEASE_SSH_PROXY_COMMAND`, а для Production —
`STRATFORGE_RELEASE_PRODUCTION_EXECUTION=owner_approved`. В Development они
живут в `data/development/integrations/secrets.local.json` (gitignored).
Состояние адаптера видно на самой странице: `mode: real` означает, что кнопки
выполняют настоящий деплой, `dry_run` — что выполняется только план.

## Неподлежащие публикации поверхности

- RDP, NinjaTrader ports, local market-data IPC и Windows file shares;
- PostgreSQL, Redis и object-storage management ports;
- `/api/health/ready`, `/api/ready`, `/api/diagnostics`, `/api/admin/*`,
  `/metrics` и `/debug`;
- Development tunnel, test-auth, impersonation и rate-limit bypass;
- SSH password, Cloudflare credential JSON, DB DSN, signing private keys,
  Telegram/OpenAI/Google/PayPal secrets.

## Чек-лист администратора до первого запуска

Каждый пункт должен получить фактическое значение и доказательство, а не
предположение.

1. Linux distribution/version, CPU, RAM, disk quota и свободное место.
2. Python version и возможность создать private virtualenv.
3. `systemd --user` работает; администратор выполнил `loginctl enable-linger`
   для service account, иначе сервис остановится после logout.
4. Разрешено установить pinned `cloudflared` в `~/.local/bin`; исходящие 443 и
   DNS доступны.
5. Inbound firewall не публикует 18765, database, object storage, RDP или VM.
6. SSH password из первоначальной инструкции отозван; работает отдельный
   Ed25519 key, известен emergency revoke path. Password login выключен либо
   ограничен политикой администратора.
7. Известно, кто владеет Cloudflare zone, Named Tunnel, DNS change и rollback.
8. Выделены Production PostgreSQL и backup target; известны RPO/RTO и путь
   фактического restore. Операционные команды и fail-closed policy описаны в
   `docs/operations/PRODUCTION_STORAGE_RUNBOOK.md`; provider-side подтверждение обязательно.
9. Выделено artifact storage вне release directory; определены quota,
   retention и encryption at rest.
10. Windows VM имеет стабильный исходящий HTTPS маршрут, NinjaTrader 8,
    отдельную учётную запись и private admin access. Public RDP отсутствует.
11. Определён способ host/VM snapshot и проверен restore в изолированной цели.
12. Синхронизация времени включена на Linux и Windows; расхождение не больше
    30 секунд, иначе signed Connector handshake будет отклоняться.

Любой неизвестный пункт — `BLOCKED`, а не молчаливый default.

## Каталоги и права rootless service account

~~~text
~/.config/stratforge/production.env       0600
~/.config/stratforge/cloudflared.yml      0600
~/.cloudflared/<tunnel-id>.json           0600
~/.config/systemd/user/*.service          0644
~/.local/bin/cloudflared                   0755
~/apps/stratforge/releases/<version>/      immutable release
~/apps/stratforge/current -> releases/...  active symlink
~/apps/stratforge/previous -> releases/... rollback symlink
~/var/stratforge/                          0700 persistent state/artifacts
~/backups/stratforge/                      0700 encrypted backup staging
~~~

Release и persistent state никогда не вложены друг в друга. Смена release не
удаляет data, ключи, Connector identities или backup.

## Подготовка конфигурации

1. Скопировать `deploy/production/production.env.example` в
   `~/.config/stratforge/production.env`.
2. Заменить placeholders, не добавляя секреты в Git или shell history.
3. Установить mode 0600.
4. Скопировать `deploy/production/cloudflared.yml.example`; подставить UUID и
   home path. Credential JSON передать защищённым out-of-band способом.
5. Установить три unit-файла — `stratforge.service`,
   `stratforge-worker.service`, `cloudflared.service` — в
   `~/.config/systemd/user/`.
6. Выполнить preflight из release virtualenv:

~~~bash
python tools/production_preflight.py \
  --app-root "$HOME/apps/stratforge/current" \
  --env-file "$HOME/.config/stratforge/production.env"
~~~

Preflight печатает только имена проверок и коды, но не значения конфигурации.

## Первый запуск и restart

~~~bash
systemctl --user daemon-reload
systemctl --user enable --now stratforge-worker.service stratforge.service
curl --fail --silent \
  -H 'Host: app.stratforges.com' \
  -H 'X-Forwarded-Host: app.stratforges.com' \
  -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:18765/api/health/live
curl --fail --silent \
  -H 'Host: app.stratforges.com' \
  -H 'X-Forwarded-Host: app.stratforges.com' \
  -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:18765/api/health/ready
systemctl --user enable --now cloudflared.service
~~~

Liveness доказывает, что процесс отвечает и отдаёт version/git/artifact identity.
Readiness возвращает 503, пока не готов хотя бы один обязательный компонент:
PostgreSQL, durable queue, artifact storage, signing key или Connector control
plane. Нельзя направлять Production traffic только по liveness.

Promotion health polling (Supervisor host, Canary or Production):

1. Poll `/api/health/live` with a per-request timeout of 3 seconds until the
   new git SHA is visible, or until the overall deadline.
2. Only then poll `/api/health/ready` with a per-request timeout of 8 seconds
   and a sleep between attempts. Do not overlap curls. Do not raise the
   timeout to hide a hung probe.
3. SUCCESS requires the new identity on `/live` and `status=ready` on `/ready`.
4. Rollback the symlink only if the new identity never appears or mandatory
   `/ready` never becomes ready. Do not roll back a switch that already serves
   the new git SHA on `/live` plus `/ui/` just because one `/ready` curl timed
   out during startup.

`/ready` probes are bounded (2s each, concurrent, single-flight). Connector
readiness is a `SELECT 1` ping and must not load the connectors JSON document.

После restart проверить PID, active release symlink, build version, liveness,
readiness и последние bounded journal lines. В логах не должно быть environment
values, token, DSN, private path из HTTP response или credential payload.

## Cloudflare/DNS cutover без потери rollback

Текущий Development tunnel нельзя просто перенести или выключить до готового
Production replacement.

1. Сохранить защищённую копию текущих локальных tunnel config/credentials и
   экспорт DNS record metadata без публикации содержимого.
2. Создать отдельный tunnel `stratforge-production`; не переиспользовать
   Development credential JSON.
3. Запустить новый tunnel на Linux и проверить local origin, unit restart и
   tunnel health до изменения DNS.
4. Убедиться, что ingress содержит ровно canonical hostname, внутренние path
   deny rules и final `http_status:404`.
5. Направить только `app.stratforges.com` на новый tunnel. Не создавать apex,
   `www`, `api`, `admin`, `dev`, `staging`, `docs` или `status` records.
6. Выполнить HTTPS/UI/API/Connector smoke, Host/Origin negative tests и raw
   origin port scan.
7. После стабильного окна остановить локальный Development tunnel. Сам backend
   остаётся localhost-only.

Rollback DNS: вернуть `app.stratforges.com` на предыдущий tunnel, убедиться в
HTTPS smoke, затем остановить неисправный Production tunnel. Удалять tunnel и
credential можно только после завершения окна rollback.

## Backup и restore contract

Точная процедура schema/owner migration, quota, retention, combined backup и
isolated restore находится в `docs/operations/PRODUCTION_STORAGE_RUNBOOK.md`.

Перед каждым изменением schema/release:

- immutable release artifact + manifest + signature сохраняются отдельно;
- PostgreSQL: consistent `pg_dump`/provider snapshot с шифрованием и checksum;
- artifact storage: versioned snapshot/replication + metadata manifest;
- protected config: encrypted administrative backup без выдачи приложению;
- audit journal фиксирует release, schema, backup IDs и результат проверки, но
  не секреты.

Retention baseline: 7 daily, 4 weekly, 12 monthly, если администратор не
предоставит более строгую политику. Backup считается рабочим только после
restore в отдельную database/state directory, checksum/referential checks и
read-only application smoke. Production restore поверх действующей базы без
явного incident decision запрещён.

## Windows VM role

Windows VM запускает NinjaTrader 8 и тот же signed Connector package, который
получают сторонние пользователи. Connector устанавливает только исходящее
TLS/WSS соединение с `app.stratforges.com/connector/v1/*`; сервер не входит на
VM для выполнения пользовательских команд. Broker password остаётся только в
NinjaTrader. Private admin RDP/PowerShell разрешены лишь через управляемый
административный tunnel/VPN, не через публичный application route.

## Stage 2 acceptance

`PASS` требует одновременно:

- чистый Linux install/start/restart и graceful SIGTERM;
- `app.stratforges.com` работает по valid TLS; лишние host/path получают 404;
- spoofed forwarding, HTTP scheme и direct origin получают 403/421;
- 18765, DB, RDP, IPC/debug не доступны извне;
- `systemd --user` переживает logout/reboot;
- backup и изолированный restore реально выполнены;
- Windows VM доступна только административно и готова к outbound Connector;
- readiness 200 только после фактической готовности всех компонентов.

Если доступа к Linux/Cloudflare/VM/DB нет, локальные тесты и deployment assets
могут быть `PASS`, но весь Stage 2 остаётся `BLOCKED_EXTERNAL` до предъявления
этих доказательств.

## Emergency rollback

1. Убрать Production tunnel из DNS route либо вернуть предыдущий tunnel.
2. `systemctl --user stop cloudflared.service stratforge.service stratforge-worker.service`.
3. Не удалять database/state/artifacts.
4. Вернуть `current` на `previous` только после проверки manifest/signature.
5. Если была migration, восстановить совместимый snapshot в отдельную цель;
   destructive in-place downgrade запрещён.
6. Запустить старый release, проверить local readiness, затем edge smoke.
7. Зафиксировать incident timestamps, release/schema/backup IDs и проверки.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T05:06:04Z | GPT-5.5 через Codex по запросу owner | Зафиксирован обязательный release contract DEV → CANARY → PRODUCTION: один immutable artifact, Canary acceptance, затем exact same artifact в Production без rebuild/partial hotfix.
-->
