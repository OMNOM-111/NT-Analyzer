# Canary Professional registration storage blocker

Change title: Canary entitlements fall through to Windows DPAPI

Change summary: Record the real ordinary-user beta.98 Canary acceptance failure
without changing code or mutating the signed artifact.

Date: 2026-09-27. Status: **BLOCKED / issue #298**. Requester: project owner.
Record: AI-assisted change.

## Reproduction and facts

1. The Canary owner session was signed out.
2. A real separate Google account was selected and consented for Canary.
3. A Canary-only profile name was entered and the current terms were accepted.
4. **Create profile** returned
   `Аккаунт подтверждён, но trial пока не сохранён: Windows DPAPI недоступен; подписки не могут быть сохранены.`

Read-only authoritative-store inspection proved:

- exactly one matching account row;
- `status=active`, `role=full_control`, `ux_mode=professional`;
- `is_owner=false` and `initial_trial_pending=true`;
- zero matching personal workspaces;
- zero matching entitlements;
- the browser remained unauthenticated, so there was no usable Canary session.

No Telegram linking or owner-forum membership was attempted. Production profile,
workspace, entitlement and session data were not changed.

## Cause and blast radius

`account_auth.py` and `workspaces.py` route both explicit Canary and Production
through authoritative PostgreSQL storage. `subscriptions.py` still uses
`runtime_env.is_production() and runtime_env.environment_explicit()` for its
document read, reference read, write, storage-status and audit paths. Explicit
Linux Canary therefore tries the Development Windows DPAPI store and fails
closed.

Blast radius: Canary subscription/entitlement persistence, initial-trial
provisioning and any ordinary-user registration that requires it. The beta.98
reload-loop correction is not implicated, but the required real Professional
cold-start acceptance cannot begin without a personal workspace and session.

## Release decision

Canary result is not PASS. No manual server hotfix, test exception, direct data
seeding or artifact mutation was used. Issue #298 tracks the correction. Any
application-code fix starts the next source commit/version, mandatory CI, signed
immutable artifact and full Canary acceptance. beta.99 Development now contains
the narrowly scoped routing correction and regression tests; merge and every
release gate remain open. The pending account row remains recoverable until the
fixed outbox completes or a separately confirmed normal account-delete cleanup
is available.
