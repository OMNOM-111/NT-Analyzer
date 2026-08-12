# Canary deployment assets

This directory is the rootless Linux contract for the separate Canary contour
`canary.stratforges.com`. It contains templates only; tunnel credentials,
database DSNs, signing keys, bot tokens and OAuth secrets never belong in a
release artifact or Git.

Canary is a **fully isolated** environment from Production. It has its own
PostgreSQL database, secrets, job queues, object-storage namespace, Telegram
bot and webhook, Connector test contour, cookie/CSRF namespace and browser
local-storage namespace. A Production session token, Telegram bot, Connector
installation or storage namespace must never be reachable from Canary, and vice
versa. `assert_environment_isolation()` fails closed at startup and in the
service preflight if any Canary identity is ever set equal to the Production
reference identity carried in `canary.env`.

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
- `run-api-canary.sh.example`, `supervisor-canary-programs.conf.example` —
  Canary runs as a **single all-in-one Supervisor program** (`api`), exactly
  like Development: `app.server.run()` starts its own in-process worker
  loop, Telegram notifier, and AI/maintenance sweepers whenever
  `deployment.environment != "production"`. There is intentionally no
  separate `worker-canary` / `operations-canary` program: `app.production_workers`
  and `app.observability --maintenance` are hard-gated to
  `DEPLOYMENT_ENV=production` and only restart-loop under any other
  environment. `telegram-canary` is likewise not a separate program; the
  in-process Telegram notifier stays disabled fail-closed until a real,
  separate Canary Telegram bot token exists.
- `tools/canary_blue_green_promote.sh` — the real blue-green executor for
  this Supervisor topology: verifies the release manifest is
  `trust_tier: production` with a valid ECDSA P-256 signature, atomically
  swaps only the `canary-current`/`canary-previous` symlinks, restarts only
  the Canary `api` program, polls `canary.stratforges.com` health, and
  automatically rolls back on any failure. Production's `current`/
  `previous` symlinks and `api-app`/`worker`/`operations`/`telegram`
  programs are never touched.
- Readiness: `app/server.py`'s `create_http_server()` registers the same
  `database`/`object_storage`/`queue`/`signing_key`/`telegram_consumer`
  probes for Canary as for Production (against Canary's own isolated
  dependencies), per `service_readiness.PRODUCTION_COMPONENTS`. The `queue`
  probe currently cannot pass in Canary: `observability.heartbeat()` only
  persists worker/background_ai heartbeats to the database when
  `runtime_env.is_production()` is true, so Canary's in-process worker loop
  has nothing to report there. This is a known, disclosed readiness gap,
  not a deployment defect; closing it requires a deliberate, owner-reviewed
  change to the heartbeat persistence gate (not just Canary deploy tooling).

Canary's API already runs on `127.0.0.1:18765` (routed by the existing
Cloudflare ingress); no new port was required for this isolation pass.
