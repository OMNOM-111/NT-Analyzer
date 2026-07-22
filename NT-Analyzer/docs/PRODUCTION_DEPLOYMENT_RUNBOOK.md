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
   `docs/PRODUCTION_STORAGE_RUNBOOK.md`; provider-side подтверждение обязательно.
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

Liveness доказывает, что процесс отвечает. Readiness возвращает 503, пока не
готов хотя бы один обязательный компонент: PostgreSQL, durable queue, artifact
storage, signing key или Connector control plane. Нельзя направлять Production
traffic только по liveness.

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
isolated restore находится в `docs/PRODUCTION_STORAGE_RUNBOOK.md`.

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
