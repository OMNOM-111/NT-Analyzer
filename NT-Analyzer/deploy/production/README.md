# Production deployment assets

This directory is the rootless Linux contract for the single canonical host
`app.stratforges.com`. It deliberately contains templates only; tunnel
credentials, database DSNs, signing keys, bot tokens and OAuth secrets never
belong in a release artifact or Git.

`connector-releases.example.json` is the strict stable/canary control-plane
catalog. Publishing is two-phase: upload an immutable Authenticode-signed ZIP,
verify its SHA-256 from the origin, then atomically replace the protected local
catalog. Canary membership is an explicit installation-id allowlist. Pointing a
channel back to its previous immutable ZIP is the server-side rollback; local
updaters still retain their own last-known-good copy.

Canonical topology:

`Cloudflare edge -> outbound Named Tunnel -> 127.0.0.1:18765 -> StratForge`

Install the API, worker, Telegram and Cloudflare units
(`stratforge.service`, `stratforge-worker.service`,
`stratforge-telegram.service`, `cloudflared.service`) plus the Operations
service/timer (`stratforge-operations.service`,
`stratforge-operations.timer`) under `~/.config/systemd/user/`, place
the protected configuration under `~/.config/stratforge/`, and follow
`docs/PRODUCTION_DEPLOYMENT_RUNBOOK.md` plus
`docs/PRODUCTION_STORAGE_RUNBOOK.md`,
`docs/PRODUCTION_TELEGRAM_RUNBOOK.md` and
`docs/PRODUCTION_WORKER_RUNBOOK.md` and
`docs/PRODUCTION_OPERATIONS_RUNBOOK.md`. Apply the checksum-confirmed schema before
starting API/workers. The service preflight validates the
PostgreSQL runtime role/TLS contract and an isolated writable artifact root;
temporary database reachability remains a readiness check. Do not expose port 18765, RDP,
NinjaTrader IPC, a Windows share, debug routes or metrics to the Internet.
