# 05. Auth, Users and Security

- Context Pack document: 05_AUTH_USERS_SECURITY.md
- Last verified UTC: 2026-08-14T06:20:00Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Identity, providers, sessions, devices, permissions and critical security gates
- Status: DONE

## Identity model

| Layer | Current fact | Evidence |
| --- | --- | --- |
| Internal identity | canonical user identity is moving to opaque UUID rather than Telegram numeric id | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `app/auth_identity.py`, `0005_identity_uuid.sql` |
| External identities | Telegram / Google / email are modeled as provider identities, not as the primary key | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `sf_auth_identities` |
| Sessions | authenticated sessions remain explicit and environment-scoped | `app/account_auth.py`, `sf_auth_sessions` |
| Workspaces | identity and workspace/membership are separate entities | [../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md](../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md) |

## Login providers

| Provider | Status | Current state |
| --- | --- | --- |
| Telegram | `PARTIAL` | repository: primary bot-based login path exists. operational: Production `login/start` works; Canary and Production `/ready` telegram_consumer is `ready` on `1fae1f39`; Canary reuses the existing bot via `[CANARY]` shared-webhook forwarding. Live Production already sets loopback `STRATFORGE_CANARY_INTERNAL_ORIGIN=http://127.0.0.1:18765`. |
| Google | `EXTERNAL BLOCKED` | code path exists, but Production OAuth client/provider configuration is not accepted live yet |
| Email | `EXTERNAL BLOCKED` | code path exists, but Production transactional email provider is not accepted live yet; DEV test auth is not Production email acceptance |

## Account linking rules

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

## Sessions, trusted devices and step-up

- Device identity is not IP-based.
- Trusted devices use lifecycle `pending -> trusted -> revoked|expired`.
- Security challenges are single-use, environment-bound and hashed at rest.
- Step-up is the intended gate for linking identities, trusting a device,
  personal NinjaTrader pairing, Connector revoke and release approvals.

## Operational auth snapshot

- Production browser serves Sign in/Register and Telegram `login/start` is
  operational.
- Completing a fresh Production owner session still requires the real Telegram
  tap; no session is fabricated for acceptance.
- Canary intentionally stays `PARTIAL` until a separate Canary bot is
  provisioned.
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
- [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md)

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T06:20:00Z | Grok 4.6 через Cursor по запросу owner | Noted live Telegram login on 1fae1f39 and remaining Canary Cloudflare 1010 forward gap.
-->
