# 05. Auth, Users and Security

- Context Pack document: 05_AUTH_USERS_SECURITY.md
- Last verified UTC: 2026-08-31T00:00:00Z
- Verified against Git SHA: 1279645e48e32000978364b38fb20d3dcd303843
- Scope: Identity, providers, sessions, devices, permissions and critical security gates
- Status: PARTIAL

## Identity model

| Layer | Current fact | Evidence |
| --- | --- | --- |
| Internal identity | canonical user identity is an opaque UUID; Telegram numeric id is an external provider identity | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `app/auth_identity.py`, `0005_identity_uuid.sql` |
| External identities | Telegram / Google / email are modeled as provider identities, not as the primary key | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `sf_auth_identities` |
| Sessions | authenticated sessions remain explicit and environment-scoped | `app/account_auth.py`, `sf_auth_sessions` |
| Workspaces | identity and workspace/membership are separate entities | [../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md](../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md) |

## Login providers

| Provider | Status | Current state |
| --- | --- | --- |
| Telegram | `DONE` | Existing owner login/session works in isolated Canary and Production on beta.29. Canary reuses the existing bot through `[CANARY]` shared-webhook forwarding and its own queue/session state; no separate Canary bot is required. |
| Google | `EXTERNAL BLOCKED` | code path exists, but Production OAuth client/provider configuration is not accepted live yet |
| Email | `EXTERNAL BLOCKED` | code path exists, but Production transactional email provider is not accepted live yet; DEV test auth is not Production email acceptance |

## Account linking rules

Telegram Mini App is `DEPRECATED` and is not a login/session transport for the
current runtime. This does not deprecate Telegram provider login, identity, bot
or notifications. Stale `remote_enabled` state cannot change current desktop
auth; explicit desktop auth remains fail-closed by default.

- Matching email is **not** enough for automatic merge.
- Linking requires fresh proof of control over both auth methods.
- Owner-assisted recovery is the explicit exception path and should produce audit
  evidence instead of silent merging.

## Roles and permissions

| Surface | Current rule |
| --- | --- |
| Owner | receives the full administrative capability set |
| Developer / admin | receives only explicit structured grants, optionally with expiry |
| Ordinary user | no admin capabilities by default |
| Workspace roles | remain separate from auth status and include `owner`, `admin`, `operator`, `viewer`, `developer` |

Key admin capability names already in the contract: `admin.view`,
`users.manage`, `workspaces.manage`, `connectors.manage`, `operations.view`,
`operations.execute`, `releases.view`, `releases.create`,
`releases.deploy_canary`, `releases.promote_production`,
`releases.rollback_production`, `environment.switch`, `docs.manage_global`,
`docs.manage_workspace`.

## Development candidate: registration and one trial clock

- Anonymous visitors receive only the protected sign-in/registration surface;
  the former blurred application shell and "watch without sign-in" path are
  removed.
- A new human account activates only after an identity provider has verified
  the subject, the required profile is complete and terms are accepted.
- The verified account receives `full_control`, professional UX and exactly one
  `trial_full` entitlement for seven days. Linking another identity or signing
  in on another browser/device returns the existing clock and never restarts it.
- Revoked, denied, blocked, deleted, owner and service accounts never receive
  an automatic trial through this path.
- Trial expiry does not revoke the identity or sessions. Authorization falls
  back to the authenticated account baseline; provider setup remains reachable.
- Owner-only `POST /api/owner/trial/extend` extends by whole days or an exact
  future UTC date. Every grant/extension records actor, source, reason and
  compact `before -> after` access history shown in the Admin user card.
- Account activation and subscription persistence use an idempotent outbox
  marker. If the entitlement store is unavailable, session creation fails
  closed instead of silently opening an unrecorded trial.

## Sessions, trusted devices and step-up

- Device identity is not IP-based.
- Trusted devices use lifecycle `pending -> trusted -> revoked|expired`.
- Security challenges are single-use, environment-bound and hashed at rest.
- Step-up is the intended gate for linking identities, trusting a device,
  personal NinjaTrader pairing, Connector revoke and release approvals.

## Operational auth snapshot

- Production browser serves Sign in/Register and existing owner login is
  operational; authenticated beta.29 owner acceptance passed.
- Canary owner login is operational through the existing shared bot routing,
  while Canary DB, queue, sessions, cookies and browser storage stay isolated.
- No separate Canary bot or second auth architecture is required.
- Google and email must remain `EXTERNAL BLOCKED` in Production until their
  external provider configurations exist.

## Personal NinjaTrader security requirements

1. User identity must already be authenticated.
2. Critical pairing/revoke actions should pass step-up.
3. Connector pairing must bind to workspace plus device-owned key material.
4. Broker credentials stay inside the user's own NinjaTrader login context.
5. Live-trading authority is not implied by having chart data or paper access.

## Current EXTERNAL BLOCKED / incomplete areas

- Treat Production email login as incomplete until a real transactional backend is
  clearly configured and accepted for the target environment.
- Treat Production Google login as blocked until the real external OAuth client,
  secret and callback configuration are accepted for Production.
- Treat trusted-device hard enforcement for every release-critical action as
  incomplete until the step-up workflow is fully rolled out across those paths.
- Treat wide public personal-NT onboarding as incomplete even though the model,
  endpoints and schema are already present.
- Treat the new automatic-trial UX as Development-only until its PR/CI and
  immutable Canary acceptance complete.

## Threat-model summary

- No broker credentials are collected or stored by StratForge.
- Absolute trust is not derived from UI visibility, IP address or JSON claims.
- Global governance mutation is separated from workspace/strategy documents.
- Per-environment cookies, CSRF keys, storage namespaces, bots and connector
  sessions are part of the isolation model.

## Canonical evidence

- [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md)
- [../adr/0003-trusted-devices-and-step-up.md](../adr/0003-trusted-devices-and-step-up.md)
- [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md)
- `app/account_auth.py`
- `app/auth_identity.py`
- `app/security_devices.py`
- `app/personal_nt_security.py`
- [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md)
