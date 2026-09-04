# 05. Auth, Users and Security

- Context Pack document: 05_AUTH_USERS_SECURITY.md
- Last verified UTC: 2026-09-03T02:47:29Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Device-confirmation Development implementation SHA: `19e0f43a35bee5a2e396538962e8f24e92bed6ef` (PR #278; isolated branch; not deployed)
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

- The Development device-confirmation model is explicitly
  `Machine -> Client -> Session`. A Machine exists only after hardware-bound
  Connector identity or attested pairing. IP, hostname, User-Agent, browser
  version, VPN and approximate location are audit metadata, never proof of a
  machine or a grouping key.
- A new unknown human Client creates a server-side pending Session with a
  roughly five-minute deadline. Before confirmation, the global protected-route
  guard exposes only auth status, challenge/confirm/approve/resend/reject and
  logout; all other protected requests fail with
  `403 DEVICE_CONFIRMATION_REQUIRED`. Timeout invalidates the Session.
- Device confirmation uses a single-use six-digit challenge, hashed at rest
  and bound to user, environment, Client, current Session, purpose and selected
  mode. Delivery choices are confirmed Telegram and verified email only.
- `permanent` trusts the Client until explicit revoke. `session` activates only
  the current auth Session, keeps the Client pending and uses a non-persistent
  browser cookie. There is no fixed 24-hour trust mode.
- Ending a Session, revoking a Client and revoking a Machine are distinct
  scopes. Machine revoke cascades only through Clients with a proven binding.
- Fresh step-up remains the intended separate gate for linking identities,
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
- General new-login device confirmation and its protected-route guard are
  Development-complete on the isolated branch. Treat fresh action-specific
  step-up for every release-critical mutation as incomplete until that separate
  workflow is fully rolled out.
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
- The owner Preview sandbox (Development only) is a separate loopback process
  with its own data root, cookie name and synthetic non-owner identity. It has
  no localhost-owner bypass, cannot open outbound connections, and is rejected
  fail-closed in Canary and Production.

## Canonical evidence

- [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md)
- [../adr/0003-trusted-devices-and-step-up.md](../adr/0003-trusted-devices-and-step-up.md)
- [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md)
- [Device Confirmation Development record](../changelog/2026-09-02-device-confirmation-trusted-access.md)
- [Owner Preview sandbox Development record](../changelog/2026-09-03-owner-preview-synthetic-sandbox.md)
- `app/account_auth.py`
- `app/auth_identity.py`
- `app/security_devices.py`
- `app/personal_nt_security.py`
- [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md)
