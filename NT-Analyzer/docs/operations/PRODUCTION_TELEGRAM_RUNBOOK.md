# Production Telegram Consumer

История поправки: 2026-08-09; внёс `GPT-5.5 через Codex по запросу owner`; scope: startup validation of injected bot token/public username and Telegram login/OTP readiness.

The Production Telegram consumer is a separate Linux user service. It is the
only process that dispatches PostgreSQL-backed Telegram inbox rows and sends
outbox rows. The API accepts webhook deliveries into the durable inbox; it
does not run a local fallback consumer.

## Install

1. Apply the checked schema migrations before starting any service.
2. Install `deploy/production/stratforge-telegram.service` under
   `~/.config/systemd/user/` beside the API and worker units.
3. Keep `~/.config/stratforge/production.env` mode `0600`; provide the bot
   token and webhook secret through the protected host secret provider. Set the
   non-secret `NTA_TELEGRAM_BOT_USERNAME` to that token's public username.
4. Reload and start the unit:

```bash
systemctl --user daemon-reload
systemctl --user enable --now stratforge-telegram.service
```

The unit overrides `STRATFORGE_DEPLOYMENT_ROLE=telegram`. The process refuses
to start outside explicit Production or without the protected token.

## Verify

```bash
systemctl --user status stratforge-telegram.service
journalctl --user -u stratforge-telegram.service -n 100 --no-pager
curl -fsS https://app.stratforges.com/api/health/ready
```

At startup the consumer calls `getMe`, rejects a token whose public username
does not match `NTA_TELEGRAM_BOT_USERNAME`, and persists the verified username
used by first-login deep links. The readiness response requires both
`telegram_consumer=ready` and `telegram_delivery=ok`. A second consumer
does not process updates because the PostgreSQL service lease is exclusive.
Webhook configuration is retried by the consumer; short webhook outages fall
back to bounded polling while the lease remains valid.

## Recover

For a failed unit, inspect the redacted journal and database/object-storage
readiness first, then restart only the Telegram unit. Do not run a second
manual consumer alongside systemd. Lease loss is intentional: exit and let
systemd restart the process. Bounded operations-timer passes sweep only
completed/dead-letter inbox and sent/dead-letter outbox rows; queued, running,
or sending rows are never removed by retention. No raw bot token, webhook
secret, authorization header, provider error body, or incoming message body
belongs in logs.
