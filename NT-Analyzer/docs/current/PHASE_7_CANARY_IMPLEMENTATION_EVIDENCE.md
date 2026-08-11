# Phase 7 — Canary Environment Implementation Evidence

**Status: Phase 7 — IMPLEMENTATION COMPLETE; REAL CANARY PROVISIONING AND EXTERNAL ACCEPTANCE PENDING OWNER APPROVAL.**
This is explicitly **NOT STAGE CLOSED**: a real separate Canary database, DNS/tunnel,
Telegram bot/webhook and Canary Connector have **not** been provisioned or verified.

This document contains no secrets, tokens, DSNs or private hostnames beyond the
already-public `canary.stratforges.com` / `app.stratforges.com` identifiers.

## 1. Source state

- Repository: `OMNOM-111/NT-Analyzer`.
- Integration branch: `release/0.10.0-next-architecture` at `89ccb3db` (Phase 6 closeout).
- Phase branch: `phase/7-canary-environment`, created from `89ccb3db`.
- Baseline `origin/main` (`72f46a1a`) untouched.

## 2. Scope delivered

Two coordinated deliverables in a single Phase 7 change set:

1. **Canary contour isolation** — a fully separate Canary environment contract
   (`DEPLOYMENT_ENV=canary`, origin `https://canary.stratforges.com`) with its own
   database, secrets, queues, object-storage namespace, Telegram bot/webhook,
   Connector test contour, cookie/CSRF namespace and browser local-storage
   namespace, plus fail-closed protection against any Production crossing.
2. **Developer Preview / View-As** — a Development-only capability for the owner
   to view the application as any role via real server-side permissions, plus a
   single-use loopback bootstrap so a separate browser can open the app as the
   developer. Fail-closed in Canary and Production.

## 3. Changed files and why

### Canary isolation
- `app/runtime_env.py` — added `_PRODUCTION_REFERENCE_ENVS`, `session_cookie_name()`
  (Canary → `sf_canary_session`; Development/Production keep `sf_session`),
  `local_storage_namespace()` (Canary → `canary`), `telegram_environment_marker()`
  (`[CANARY] ` / `[DEV] ` / Production empty), `_reference_collision()` and
  `assert_environment_isolation(config)`. The isolation guard is fail-closed and
  wired into `assert_startup_safe()`: a Canary process is rejected if any identity
  (database/queue/object-storage/telegram/cookie/signing/log/instance/origin),
  the storage DSN, the data root or the allowed hosts collides with the Production
  reference identifiers; a symmetric guard rejects a Production process that
  declares the Canary Telegram bot id.
- `app/server.py` — per-environment session cookie name at every cookie
  set/clear/read site via `runtime_env.session_cookie_name()`; Canary is held to
  the same readiness contract as Production (control-plane probes required).
- `app/telegram_service.py` — `_send_raw()` prepends the environment marker to
  every outgoing message before both the Production outbox and the direct send
  path. Production is unmarked, so its wording is unchanged.
- `app/connector_protocol.py` — installations are stamped with
  `deployment_environment` at enrollment and refreshed on signed hello;
  `_assert_environment()` rejects a cross-environment installation
  (`connector_environment_mismatch`) in challenge, signed hello and every
  session-authenticated call (heartbeat/market-data/commands). Installations
  enrolled before stamping are grandfathered and adopt the current environment on
  next write.
- `app/service_readiness.py` — Canary registers the same authoritative
  control-plane probes as Production, so it can never report `ready` while an
  isolated dependency is missing.
- `tools/production_preflight.py` — a named `environment_isolation` check invokes
  `assert_environment_isolation` for Canary and Production and fails closed.
- `deploy/canary/*` — the rootless Linux Canary contract templates:
  `canary.env.example` (Canary identities plus the Production reference
  identifiers used by the collision guard, no secrets), `cloudflared.yml.example`
  (a separate tunnel, port `18766`), `cloudflared.service`,
  `stratforge-canary.service`, `stratforge-canary-worker.service`,
  `stratforge-canary-telegram.service`, `stratforge-canary-operations.service`,
  `stratforge-canary-operations.timer`, `connector-releases.example.json`
  (`beta`/`canary` channels), and `README.md` runbook.
- `app/static/aurora/assets/ui.js` — per-environment localStorage namespace
  helper `lsKey()` (Canary keys prefixed, Development/Production unchanged).

### Developer Preview / View-As
- `app/dev_preview.py` (new) — Development-only personas (unauthenticated,
  ordinary, owner-training, personal-NT, developer, owner), `start_view_as`,
  `exit_view_as`, `return_to_developer`, single-use loopback bootstrap
  (`mint_bootstrap_token` / `redeem_bootstrap_token`) and `status`. Every entry
  point is fail-closed via `runtime_env.require_test_auth()` (requires
  `DEPLOYMENT_ENV=development` plus `NTA_ENABLE_TEST_AUTH=1`). Personas are
  deterministic virtual accounts in a reserved id band, hold no real PII,
  Connector session or account, and can be reset. Preview permissions come
  entirely from the selected persona account; real roles are never changed. The
  developer persona receives only an explicit limited grant set
  (`admin.view`, `operations.view`, `environment.switch`), never the owner set.
  Audit events (`dev.view_as_started/ended`, `dev.bootstrap_minted/redeemed`)
  never carry a raw token.
- `app/server.py` — routes: public GET `/api/dev/bootstrap/redeem` (Development +
  loopback, single-use, sets the session cookie and redirects to `/ui/`), public
  GET `/api/dev/preview/return` (Development + loopback, restores the owner
  session even from the unauthenticated persona), authenticated GET
  `/api/dev/preview/status`, and POST `/api/dev/preview/view-as`,
  `/api/dev/preview/exit`, `/api/dev/preview/reset-personas`,
  `/api/dev/bootstrap/mint`. Helpers `_is_loopback_ip` and `_self_origin` were
  added.
- `app/static/aurora/assets/api.js` — `devPreviewStatus`, `devPreviewViewAs`,
  `devPreviewExit`, `devPreviewResetPersonas`, `devBootstrapMint`.
- `app/static/aurora/assets/ui.js` — a persistent, deliberately loud `VIEW AS`
  banner, a Development-and-owner-only `Preview` topbar control, the persona
  switcher, the `Open Development as Developer` single-use link and the return
  action.
- `app/static/aurora/assets/theme.css` — the striped `.dev-view-as-banner`
  styling.

## 4. Access and boundary model

- Canary access is limited to owner/developer/admin roles holding an explicit
  Canary capability grant on a real Canary account. There is **no** dev-login
  bypass in Canary: the preview switcher and bootstrap are Development-only and
  fail closed in Canary and Production.
- Production has no dev bootstrap, no View-As and no authentication bypass.

## 5. Commands run and results

- Full regression: `python -B -m pytest -q -p no:cacheprovider` →
  **1059 passed, 31 skipped**.
- Focused Phase 7: `tests/test_phase7_canary_isolation.py` → **28 passed**;
  `tests/test_phase7_dev_preview.py` → **18 passed**.
- `python -m compileall -q app tools` → PASS.
- `node --check app/static/aurora/assets/ui.js` and `.../api.js` → PASS.
- `python tools/release_static_scan.py` → CSP OK, SECRETS OK, MARKDOWN OK.
- `git diff --check` → clean (a transient EOF blank line in `runtime_env.py` was
  found and fixed).

## 6. Errors encountered, root cause, fix and regression coverage

- **`Request` test doubles lacked a new instance method.** After introducing a
  per-environment session cookie name, five tests in `test_telegram_remote.py`
  and `test_ai_agents.py` failed because their hand-rolled `Request` doubles did
  not implement the wrapper method. Root cause: cookie-read sites depended on an
  instance method the doubles did not provide. Fix: cookie set/clear/read sites
  now call `runtime_env.session_cookie_name()` directly and the wrapper method
  was removed. The full regression suite (which includes those five tests)
  passes.
- **Bootstrap replay reported `token_not_found` instead of `token_used`.** The
  redeem path pruned the just-used token immediately, so an immediate replay
  could not identify it as used. Fix: the used token is retained (and cleaned up
  on the next mint) so a replay is explicitly rejected as `token_used`. Covered
  by `test_bootstrap_roundtrip_is_single_use`.

## 7. External checks intentionally NOT run

- No real Canary deployment and no Production deployment.
- No Cloudflare or DNS change; the `canary.stratforges.com` hostname/tunnel was
  not created.
- No real Canary PostgreSQL database created; no migration applied to any real
  database.
- No real Telegram webhook/token installed; no real Connector pairing.
- No change to any running server.
- Browser QA was not run per the workspace stability policy; UI was validated via
  `node --check`, source/DOM contract review and the CSS marking.

## 8. Missing real credentials / infrastructure

Real external acceptance requires (owner-gated): a provisioned isolated Canary
PostgreSQL database and DSN, a Canary Cloudflare tunnel + `canary.stratforges.com`
DNS, a separate Canary Telegram bot token and webhook secret, and a Canary
Connector test contour. None are present in this repository or environment.

## 9. Rollback

Revert the Phase 7 implementation commit on `phase/7-canary-environment`
(or the integration merge commit). No schema migration was added, so there is no
database rollback. The new `deploy/canary/*` templates and `app/dev_preview.py`
are inert unless `DEPLOYMENT_ENV=canary` / `development` is explicitly configured.

## 10. Known risks

- The Development bootstrap grants a real owner session; it is mitigated by
  Development-only + loopback-only + single-use + short TTL + hash-only storage,
  and is fail-closed in Canary/Production.
- Canary reports `not_ready` until real control-plane probes are provisioned;
  this is the intended fail-closed state, not a defect.
- The environment marker prepends a short prefix to outgoing Telegram text in
  Development/Canary; Production text is unchanged.

## 11. Environment impact

Only code, Development/Canary configuration templates and UI were changed.
Production and Canary servers, Cloudflare, DNS, real databases, real secrets,
real Telegram credentials and real Connector sessions were **not** touched.

## 12. Commit / PR / CI / merge evidence

- Implementation commit: `2a4f4839` on `phase/7-canary-environment` (from integration `89ccb3db`).
- PR: [#13](https://github.com/OMNOM-111/NT-Analyzer/pull/13) → base `release/0.10.0-next-architecture`.
- CI ([Actions run 30782625524](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30782625524)): Static gates PASS; Tests (ubuntu-latest) PASS; Tests (windows-latest) PASS.
- Merge commit: `5955f2e5`; task branch `phase/7-canary-environment` deleted locally and on origin; integration `release/0.10.0-next-architecture` in sync with origin after merge.
- Extraneous dirty/untracked files (`data/catalog/margins.json`, `data/development/durable/nt_analyzer.sqlite3`, `data/development/audit/`, `data/development/integrations/`, `data/governance-rendered/*`, `docs/AGENT_PERSONAS.md`, `docs/governance/*`) were preserved on disk and remained outside the Phase 7 delivery.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-11T08:13:16Z | GPT-5.5 через Codex по запросу owner | Removed the visible technical amendment header during final Development documentation closeout; historical evidence remains in Git history.
-->
