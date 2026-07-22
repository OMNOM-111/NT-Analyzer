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

Install the two units as user services under `~/.config/systemd/user/`, place
the protected configuration under `~/.config/stratforge/`, and follow
`docs/PRODUCTION_DEPLOYMENT_RUNBOOK.md`. Do not expose port 18765, RDP,
NinjaTrader IPC, a Windows share, debug routes or metrics to the Internet.
