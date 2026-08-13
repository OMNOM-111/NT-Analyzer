# Canary deployment assets

This directory is the rootless Linux contract for the separate Canary contour
`canary.stratforges.com`. It contains templates only; tunnel credentials,
database DSNs, signing keys, bot tokens and OAuth secrets never belong in a
release artifact or Git.

Canary is a **fully isolated** environment from Production. It has its own
PostgreSQL database, app/migration roles, job queue, object-storage namespace,
Connector test contour, cookie/CSRF namespace and browser local-storage
namespace. A separate Canary Telegram bot identity is optional and is not
required for owner login; Canary can reuse the existing owner bot through
environment-marked login payloads (`[CANARY]` / `canary_login_*`) and the
Production webhook forwarder into Canary's isolated Telegram queue. A
Production session token, Connector installation or storage namespace must
never be reachable from Canary, and vice versa.
`assert_environment_isolation()` fails closed at startup and in the service
preflight if any Canary identity is ever set equal to the Production reference
identity carried in `canary.env`.

Canonical topology (independent from Production):

`Cloudflare edge -> outbound Named Canary Tunnel -> 127.0.0.1:18766 -> StratForge (canary)`

## What this contour deliberately does NOT do here

The Phase 7 change set implements the Canary contract, isolation guards, config
templates and tests only. It does **not** perform, and this runbook must not be
read as authorization for, any of the following without explicit owner approval:

- a real Canary deployment or a real Production deployment;
- any Cloudflare or DNS change (including creating the `canary.stratforges.com`
  hostname or tunnel);
- creating the real Canary PostgreSQL database or applying migrations to any
  real database;
- installing a real Canary Telegram webhook/token or pairing a real Connector;
- any change to a running server.

## Files

- `canary.env.example` — copy to `~/.config/stratforge/canary.env`, replace every
  placeholder, then `chmod 600`. Contains `DEPLOYMENT_ENV=canary`, the isolated
  Canary identities and the Production reference identifiers used by the
  isolation guard. No secret values.
- `cloudflared.yml.example` — copy to `~/.config/stratforge/cloudflared-canary.yml`
  and `chmod 600`. A **separate** tunnel from Production.
- `connector-releases.example.json` — the Canary Connector control-plane catalog
  (`beta`/`canary` channels). Publishing is two-phase and immutable; Canary
  membership is an explicit installation-id allowlist. Connector installations
  are environment-stamped and a Production Connector session is rejected here
  with `connector_environment_mismatch`.
- `stratforge-canary.service`, `stratforge-canary-worker.service`,
  `stratforge-canary-telegram.service`, `stratforge-canary-operations.service`,
  `stratforge-canary-operations.timer`, `cloudflared.service` — systemd user
  units. Install under `~/.config/systemd/user/`, place the protected
  configuration under `~/.config/stratforge/`.

## Access model

Canary is reachable only by owner/developer/admin roles holding an explicit
Canary capability grant on a **real Canary account**. There is no Development
dev-login bypass in Canary: the Developer Preview / View-As switcher and the
single-use loopback bootstrap link are Development-only and fail closed in
Canary and Production.

## Preflight

`tools/production_preflight.py --app-root <release> --skip-runtime-binaries`
validates the typed Canary config and runs `environment_isolation`. Temporary
database reachability and real Telegram/Connector acceptance remain manual
readiness checks performed only after real Canary provisioning is approved. Do
not expose port 18766, RDP, NinjaTrader IPC, a Windows share, debug routes or
metrics to the Internet.

## Real host topology note (owner-approved provisioning, 2026-08-11)

The systemd units above describe the aspirational rootless-systemd target.
The actual current production host runs **no systemd**; a single root
`supervisord` instance manages every process (`api`, `api-app`, `worker`,
`operations`, `telegram`, `cloudflared`, `postgresql`, `artifact-server`).
For this real topology, provisioning and promotion are done with:

- `tools/canary_isolation_provision.py` — one-time, idempotent creation of
  the isolated Canary PostgreSQL role/database, a dedicated Canary data
  root, and `canary.env` with every identity distinct from Production
  (checked by `assert_environment_isolation`), including its own
  `STRATFORGE_SIGNING_KEY` runtime secret. Never prints a secret value.
  After migrations are applied to the Canary database, run the same tool
  with `--lockdown-privileges`; it revokes Production/PUBLIC privileges from
  Canary objects and writes the secret-free
  `canary-privilege-lockdown.ok.json` marker required by promotion. Without
  that marker, `tools/canary_blue_green_promote.sh` refuses before touching
  symlinks or Supervisor.
- `run-api-canary.sh.example`, `run-worker-canary.sh.example`,
  `run-operations-canary.sh.example`,
  `run-telegram-canary.sh.example`, `supervisor-canary-programs.conf.example`
  — Canary now runs a real split Supervisor topology: `api` (HTTP),
  `worker-canary` (PostgreSQL queue consumer + worker heartbeat),
  `operations-canary` (observability maintenance loop), and `telegram-canary`
  (Canary Telegram inbox/outbox consumer). `app.production_workers` and `app.observability
  --maintenance` are gated for Production **or Canary** via the server
  environment boundary, while the API process refuses worker-only roles and
  does not start the Development-local queue consumer. When the existing owner
  bot is reused, `telegram-canary` runs in shared-webhook mode and never calls
  `setWebhook` or `getUpdates`; Production forwards `[CANARY]` login/contact
  updates into Canary's isolated queue.
- `tools/canary_blue_green_promote.sh` — the real blue-green executor for
  this Supervisor topology: verifies the release manifest against a pinned
  trusted production public key, derives deploy identity only from the signed
  manifest, atomically swaps only the `canary-current`/`canary-previous`
  symlinks, restarts only configured Canary programs (`api worker-canary
  operations-canary telegram-canary` by default), polls `canary.stratforges.com` `/api/health/live`
  for the new git SHA first, then `/api/health/ready` with bounded per-request
  timeouts inside one overall deadline, and automatically rolls back only if the
  new identity never appears or mandatory `/ready` never becomes ready.
  Production's `current`/`previous` symlinks and `api`/`worker`/`operations`/`telegram`
  programs are never touched.
- Readiness: `app/server.py`'s `create_http_server()` registers the same
  `database`/`object_storage`/`queue`/`signing_key`/`connector_control`
  probes for Canary as for Production (against Canary's own isolated
  dependencies), per `service_readiness.PRODUCTION_COMPONENTS`. The queue
  probe requires the real `worker-canary` heartbeat, not Production's legacy
  `background_ai` heartbeat. `telegram_consumer` is required once the protected
  Telegram token/chat config exists; otherwise readiness still reports a
  disclosed unavailable component instead of fabricating a pass.

Canary's API already runs on `127.0.0.1:18765` (routed by the existing
Cloudflare ingress); no new port was required for this isolation pass.

## Live 0.10.0-beta.1 (2026-08-12)

The Canary-tested signed artifact
`0.10.0-beta.1` / git `2f9409c48a6c1480617749462323562ade3eb6fe` /
manifest SHA256 `FB302F809F7FD38A7BDB6CCFC0ADD1A1D01DA43B4C947EB0C9726F5FBB42C870`
was promoted to Production **without rebuild** by pointing
`/home/stratforge/current` at the same extracted release directory
`.../releases/0.10.0-beta.1-2f9409c4` and restarting only Production Supervisor
programs (`api-app`, `worker`, `operations`, `telegram`). Canary programs were
not restarted for that promotion. Rollback target remains
`0.9.0-dev.15-f05f287d`. Historical note: that release kept Canary Telegram
blocked; the current auth hotfix replaces that with shared owner-bot routing
and a Canary Telegram consumer.
