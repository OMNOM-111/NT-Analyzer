# Platform secrets

Canonical contract for credentials the deployment owns. Written 2026-08-29,
reflects the state live in Production on `0.10.0-beta.79`.

## Three kinds of credential

They are not interchangeable and the rules differ.

| Kind | Examples | Where it lives |
| --- | --- | --- |
| **Platform secret** | Google OAuth client secret, Resend API key, Telegram bot token, owner market-data gateway token, Connector release signing key | external secrets directory, one file per environment |
| **User / workspace BYOK** | a person's own OpenAI / Anthropic key | their workspace, encrypted at rest, never returned to a client |
| **Non-secret configuration** | ports, origins, feature flags, build identity | ordinary config files in the repository |

Until 2026-08-29 the first two shared one store: `configure_provider()` wrote a
user's AI key into the same `secrets.local.json` the deployment used for its
Google client secret, keyed by an environment variable name. They are now
separate.

## Where platform secrets live

```
$STRATFORGE_SECRETS_DIR/development.env
$STRATFORGE_SECRETS_DIR/canary.env
$STRATFORGE_SECRETS_DIR/production.env
```

Production host: `/home/stratforge/production_data/secrets/`, exported by
`config/run-api-app.sh` and `config/run-api-canary.sh`. Default when the
variable is unset: `%PROGRAMDATA%\StratForge\secrets` on Windows,
`/etc/stratforge/secrets` elsewhere.

Guarantees enforced by `app/platform_secrets.py`:

- **never in Git** — a directory inside the checkout is *refused*, not warned
  about; it is one `git add -A` away from publishing live credentials;
- **environments never share** — Canary and Production read only their own
  file, so one cannot serve the other's credential;
- **least permission** — files are written `0600`; on POSIX a group- or
  world-readable file is refused on read;
- **fail closed** — a missing required secret raises, naming the variable and
  the environment. An empty string would produce an integration that looks
  configured and silently does nothing;
- **atomic replacement with rollback** — one previous copy is kept, so a bad
  value is reverted without going back to the provider;
- **audit without values** — name, environment, timestamp, actor. Never the
  value, not masked, not partially;
- **redaction** — `redact()` scrubs any configured value out of text before it
  can reach a log, an exception, a health payload or a support bundle.

`secrets.example.env` is committed and carries **names only**. A value in it
fails the release.

## Containment

A platform secret must not travel inside anything shipped or kept. Three guards,
all in `tools/release_static_scan.py --scan secrets`, which runs both in CI and
inside `build_server_release.py`:

1. `scan_secrets` — credential *shapes* (`GOCSPX-`, `re_`, `sk-ant-`, `AKIA`,
   private-key headers, Telegram/Slack tokens) anywhere in tracked files;
2. `scan_secret_template` — a value in the committed template;
3. `scan_platform_secret_values` — any `NAME=value` assignment for a platform
   secret, and any `secrets/` directory inside the packaged tree.

`tools/production_blue_green_promote.sh` refuses to promote when the production
config still carries a platform-secret value, *before* it creates a backup.

This guard exists because it did not. Every promotion copied
`production-app.env` into a backup kept indefinitely; **314 files** had
accumulated copies of two live credentials by 2026-08-29. All were scrubbed
during the rotation; the promotion guard prevents the next one.

Shell scripts (`.sh`, `.bash`) are scanned — previously they were not, which
left `export SECRET=...`, the shape most likely to carry a credential, as the
one shape never checked.

## Owner surface

`GET /api/admin/platform-secrets` and `/audit` — owner only, status only:
configured, required, missing, last rotated, by whom. **No route returns a
value**, and there is no "Show secret" to build one behind.

`POST /api/admin/platform-secrets/replace` and `/rollback` require owner
capability **and** a fresh step-up grant with the owner exemption explicitly
disabled — holding the session is necessary and deliberately not sufficient.

A UI for this is not built; the API is the interface today. See backlog.

## Rotation runbook

Proven on 2026-08-29 for four credentials. Sequential, one environment fully
finished before the next is touched.

1. Create the new credential at the provider. **Do not revoke the old one.**
2. Write the value into `$STRATFORGE_SECRETS_DIR/<environment>.env`
   (`0600`). Never paste it into chat, a ticket or a commit.
3. Remove the legacy `NAME=` line from that environment's config env file,
   keeping a temporary backup — the process environment wins over the file, so
   a stale line would silently shadow the new value.
4. Restart **only** that environment's service.
5. Verify: `/api/auth/providers` reports `configured: true` while the process
   environment no longer carries the variable — that combination proves the
   file is being read. Then a real end-to-end check.
6. Only after that environment passes, repeat for the next.
7. Once every environment passes, revoke the old credentials at the provider,
   then run the smoke again.
8. Shred the temporary backups and verify no copy of a revoked value remains.

**Google client secrets cannot be verified server-side.** They participate only
in the authorization-code exchange, which needs an interactive redirect. The
only real check is a human signing in. Resend can be verified with a real send.
