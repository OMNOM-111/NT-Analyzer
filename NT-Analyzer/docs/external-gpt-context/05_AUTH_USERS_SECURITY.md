# 05. Auth, Users and Security

- Context Pack document: 05_AUTH_USERS_SECURITY.md
- Last verified UTC: 2026-09-05T04:04:22Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: bd239e76e548db818439bb77389f47c8aa9755f4 (clean beta.96 runtime; Azure PASS, Court dispatch correction under verification)
- Active scope: roles/private containers/claimed delivery plus rejection/rating/calendar fixes at ef4006eb; native Azure owner-binding compatibility fully regression-tested, activation pending
- Unified Local base: `0.10.0-beta.96`, PR #280; no Canary/Production promotion
- Scope: Identity, providers, sessions, devices, permissions and critical security gates
- Status: PARTIAL

## Current scoped follow-up

Azure owner binding is active and actually verified on clean bd239e76 (CI 3/3).
Court's actual synchronous/worker collision is under correction; no accepted vote
is claimed from its blocked task. Only single-dispatch and immutable-receipt
recovery change; API, SQL, authority, budgets and UI composition do not.
Exact evidence and limits: [canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

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
| Telegram | `BETA` in Unified Local | staged registration and existing shared-bot routing; contextual synthetic Preview passed. Earlier deployed owner-login evidence is historical, not repeated here |
| Google | `BETA` in Unified Local | staged registration and contextual synthetic Preview passed; real-provider acceptance of the beta.96 build is separate |
| Email | `BETA` in Unified Local | normal OTP state flow with Preview-only delivery passed; synthetic acceptance does not certify external delivery |

Historical beta.79 records include Google/Resend post-rotation smoke. Earlier
claims that Production has no provider configuration are stale. This slice
does not inspect live credentials or repeat provider acceptance; use the
environment's current release evidence before asserting live readiness.

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

## Unified Local beta.96: registration and active-use access

- Anonymous visitors receive only the protected sign-in/registration surface;
  the former blurred application shell and "watch without sign-in" path are
  removed.
- A new human account activates only after an identity provider has verified
  the subject, the required profile is complete and terms are accepted.
- The verified account receives `full_control`, professional UX and exactly one
  `trial_full` starting grant of five hours of active use by default. Idle time
  is not charged. Linking another identity or signing in on another client
  preserves the same grant and consumption. Legacy calendar fields do not
  define the active-use allowance.
- Revoked, denied, blocked, deleted, owner and service accounts never receive
  an automatic trial through this path.
- Trial expiry does not revoke the identity or sessions. Authorization falls
  back to the authenticated account baseline; provider setup remains reachable.
- Owner-only `POST /api/owner/trial/extend` retains its calendar-extension
  compatibility contract; it must not be confused with replenishing active-use
  seconds. Every grant/extension records actor, source, reason and
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
  two-minute deadline. Before confirmation, the global protected-route
  guard exposes only auth status, challenge/confirm/approve/resend/reject and
  logout; all other protected requests fail with
  `403 DEVICE_CONFIRMATION_REQUIRED`. Timeout invalidates the Session.
- Device confirmation uses a single-use six-digit challenge, hashed at rest
  and bound to user, environment, Client, current Session, purpose and selected
  mode. Delivery choices are confirmed Telegram and verified email only.
- A first device immediately after registration may consume the single-use
  login proof, at most fifteen minutes old, for that same client/session.
  The owner/user still chooses trust and confirms manually. Later unknown
  clients and expired/replayed proof require normal OTP.
- `permanent` trusts the Client until explicit revoke. `session` activates only
  the current auth Session, keeps the Client pending and uses a non-persistent
  browser cookie. There is no fixed 24-hour trust mode.
- Ending a Session, revoking a Client and revoking a Machine are distinct
  scopes. Machine revoke cascades only through Clients with a proven binding.
- Fresh step-up remains the intended separate gate for linking identities,
  personal NinjaTrader pairing, Connector revoke and release approvals.

## Operational auth snapshot

The following Production/Canary facts are historical deployment evidence, not a
fresh environment check. The shared deployed anchor
`8f42158661e8247832c90bea8fc4d9f0071e647b` is unchanged. Local `8765` now serves
the clean `ef4006eb` beta.96 runtime with original owner data/settings and the
scoped delivery/role/private-container changes active. Earlier `fc78677`
owner-review notes remain history. Remaining real-provider/browser acceptance is pending.
Native Azure binding compatibility permits only the canonical HTTPS api-version
query from the already approved owner registry. Query credentials, extra or
duplicate parameters, userinfo/fragments and non-Azure queries remain rejected;
ordinary private transports receive no exception or copied owner credential.

Development `POST /api/account/workspace/personal` creates/selects only the
confirmed authenticated human's own empty container. It rejects Preview,
non-Development, service/local-bypass/impersonated and unconfirmed/revoked
sessions, foreign caller scope and invalid Origin/CSRF. It grants no NT, key,
budget or AI opt-in. Original NT routes retain dual authentication. Ordinary
test registration is at final Terms; owner must confirm and enter a separate
OpenRouter key in the private wizard. Existing owner keys are never copied.

- Production browser serves Sign in/Register and existing owner login is
  operational; authenticated beta.29 owner acceptance passed.
- Canary owner login is operational through the existing shared bot routing,
  while Canary DB, queue, sessions, cookies and browser storage stay isolated.
- No separate Canary bot or second auth architecture is required.
- Current live delivery was not re-verified in this task. Baseline synthetic
  Preview evidence does not replace acceptance of the real target providers.

## Personal NinjaTrader security requirements

1. User identity must already be authenticated.
2. Critical pairing/revoke actions should pass step-up.
3. Connector pairing must bind to workspace plus device-owned key material.
4. Broker credentials stay inside the user's own NinjaTrader login context.
5. Live-trading authority is not implied by having chart data or paper access.

## Current EXTERNAL BLOCKED / incomplete areas

- Treat acceptance of real Google/email delivery for the new beta.96 build as
  a separate environment gate; no current credentials were read by this task.
- General new-login device confirmation and its protected-route guard are
  integrated and browser-verified in Unified Local beta.96. Treat fresh action-specific
  step-up for every release-critical mutation as incomplete until that separate
  workflow is fully rolled out.
- Treat wide public personal-NT onboarding as incomplete even though the model,
  endpoints and schema are already present.
- Treat the new active-use access UX as Development-only until its PR/CI and
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
- Agent World reuses this identity, permission and device context. Its new
  scoped flags do not grant capabilities, bypass pending-device access or
  authorize provider/command use. The historical stages 0–1 made no auth/security
  changes; the current integration adds only the read-only session-lease helper
  and narrow history-entitlement behavior described below, not another login flow.

## Agent World integration boundary

The Preview owner-review facade reuses existing session, permanent/session device,
membership, role, ai_lab capability, trial, CSRF and zero-cost budget checks;
synthetic identity does not receive owner privileges. New routes additionally
require trusted Preview control and scoped default-off flags. Mutation checkpoints
refresh access rather than trusting stale UI capabilities. Reset is serialized
with the new SQLite operations before it wipes only synthetic state.
See [ADR-0010](../adr/0010-agent-world-owner-review.md). Auth/provider registration
logic, real credentials and the ordinary Local owner runtime are not replaced.

The real Local adapter is independent: Development only, Preview forbidden,
`STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES` is an exact server-owned allowlist
(default empty; wildcard/invalid entries deny). Existing authenticated Local
owner entry or confirmed owner browser session is required; active owner identity,
UUID, owner workspace/membership and existing permissions/budget are rechecked.
The earlier clean adapter activated read/UI/tasks only. The new uncommitted
composition enables eight exact-workspace gates: read/UI/tasks/evaluation/memory/
consensus/Court/social. Router shadow and Execution V2 remain OFF; every flag still
defaults OFF globally. No synthetic identity,
master code, client-supplied owner/scope grant or new permissions catalog exists.
The durable chat worker uses its server-issued scope and fresh actor/membership
admission; this is not a claim that a persisted job carries a live browser cookie.
Neither pending devices nor other users/Canary/Production gain this access.

The added domain facade admits ordinary authenticated users only through fresh
active identity/UUID, current workspace membership, confirmed session and existing
capabilities. Own-workspace owner mutations require `ai_lab`; real model calls
also require `ai_pro_models` and the existing budget checks. Cross-user mutation,
client-supplied actor/workspace/caps, Preview identities and non-DEV access fail
closed. Current workspace members may read explicitly published same-workspace
Memory; private records/artifacts are not made public by that membership.

`account_auth.local_session_is_active` is a Development-only read of an already
admitted session ID/user pair. It checks active user, unrevoked/unexpired Session
and active Device Confirmation without creating a session, refreshing cookies or
persisting bearer tokens in jobs. Session revoke/expiry is rechecked before later
worker/provider actions; the helper is not a new authenticator or PG fallback.

After trial/entitlement expiry, authenticated professional users can still read
their scoped history/evidence and open an existing task's SF Chat conversation.
The legacy chat-link POST accepts only an empty body and appends nothing. This
history exception grants no new model call, job, domain mutation or social
publication; action controls are removed and POST admission remains independent.
Revoked sessions and foreign workspaces never gain history access.

Private model credentials stay in the existing DPAPI store, referenced by opaque
scoped IDs, never by browser-visible secret values. Private provider traffic uses
the existing model client through an exact registry scope and HTTPS guard: public
resolved IP, pinned connection with hostname TLS verification, bounded paths/body,
no redirects/proxy/private-address fallback. It cannot enumerate or fall back to
the owner registry. An explicit owner-only binding may reuse an existing owner
connection and its existing budget caps without copying keys or increasing limits.
New paid private connections remain blocked without an approved budget; provider
availability and live acceptance must not be inferred from configured records.

Social publishing requires the existing `community` capability plus its scoped
Agent World gate, exact reviewed snapshot hash/revision and explicit human
permanent-publication consent. Fresh admission precedes the Community write;
actor and requester remain separate in a private approval artifact. No implicit
publication from GET, completion, Court or shared Memory is permitted.

## Canonical evidence

- [Current Agent World baseline](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
- [Historical pre-foundation context](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md)
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
