# Stage 11 proposal

Status: **proposal only — implementation not started**

Prerequisite: [Stage 10 closure](STAGE10_CLOSURE_2026-08-01.md)

## Objective and sequencing

Stage 11 turns the operational dev.15 deployment into a formally managed,
multi-user, MFA-capable product and release system. It must preserve the Stage
10 separation of Development, Canary and Production and must not enable live
trading or real payments as a side effect.

Recommended order:

1. **11A Authentication, Identity and MFA** — establish the security model.
2. **11B Admin Panel and Permissions** — expose only the approved model.
3. **11C Release Center** — automate the already-proven release workflow.
4. **11D Environment and Release Branding** — present authoritative identity.
5. **11E Stable Certification** — provision external trust and complete beta.

Each section has an independent acceptance decision and rollback boundary.
Production promotion requires the preceding sections on which it depends to be
accepted; partial work remains disabled behind server-side gates.

## Stage 11A — Authentication, Identity and MFA

| Field | Proposal |
|---|---|
| Scope | Retain the current server-verified Telegram app/web/QR flow; add Google login, passwordless email, identity linking, Passkey/WebAuthn, TOTP, recovery codes and step-up authentication. Formalize protected owner bootstrap and require Telegram + verified email + MFA before Connector pairing or other sensitive operations. |
| Dependencies | Canonical Production user/workspace/membership model; protected Telegram numeric owner identity; email delivery provider; Google OAuth project; WebAuthn RP ID/origin policy; secure encryption/signing keys; Admin permissions from an agreed authorization design. |
| Migrations | Add normalized identity/provider links, verified-email challenges, WebAuthn credentials/counters, encrypted TOTP enrollment, one-way recovery-code hashes, MFA policy and step-up grants. Use additive, forward-compatible migrations first; dual-read only during a bounded transition. |
| Security risks | Account linking takeover, OAuth redirect confusion, email token replay, WebAuthn origin/RP mismatch, TOTP seed exposure, recovery-code leakage, MFA fatigue, owner bootstrap reassignment and session fixation. Numeric provider IDs and server-verified assertions remain authoritative; usernames and browser claims never assign owner. |
| Acceptance | Desktop/mobile Telegram fallback; Google and email happy/deny paths; link/unlink with recent MFA; Passkey and TOTP enrollment/recovery; replay/CSRF/open-redirect/session-rotation tests; one canonical owner after repeat logins; Connector pairing denied without required step-up; cross-workspace isolation. |
| Rollback | Keep Telegram login and existing sessions compatible while new providers are gated. Disable new provider enrollment first, retain encrypted records, roll application code back only to a schema-compatible release, and revoke incomplete step-up grants. Never delete identities during rollback. |
| Commit boundaries | A1 identity schema/repository; A2 Google; A3 passwordless email; A4 account linking; A5 WebAuthn; A6 TOTP/recovery; A7 step-up and Connector policy; A8 migration/operations documentation. Each commit includes focused security tests. |

## Stage 11B — Admin Panel and Permissions

| Field | Proposal |
|---|---|
| Scope | Add a separate Admin Panel for owner/developer operators, granular permissions, user/workspace/session/Connector controls, system settings migration, audit views and security controls. Do not expose application employee personas or provider keys as implicit administrators. |
| Dependencies | 11A identity assurance and step-up; existing owner workspace model; central `permissions.resolve()` contract; durable audit/event storage; documented operator roles and least-privilege policy. |
| Migrations | Add role/permission assignments with scope and expiry, privileged-action audit records, settings versions and approval state. Migrate current owner controls without changing effective owner access; no client-supplied role migration. |
| Security risks | Horizontal/vertical privilege escalation, confused deputy, stale permission cache, self-lockout, hidden developer backdoors, unsafe impersonation and disclosure of secrets/PII in audit views. Enforce every decision server-side and redact by default. |
| Acceptance | Permission matrix for owner/developer/support/read-only users; cross-workspace deny cases; recent-MFA requirements; audit completeness; self-lockout recovery; session revocation; settings rollback; API/UI parity; no Production test-auth or bypass. |
| Rollback | Feature-gate the Admin UI and new mutations. Restore the previous settings version and permission snapshot, preserve append-only audit events, and retain owner emergency access through the protected canonical identity. |
| Commit boundaries | B1 authorization model; B2 settings migration; B3 admin APIs; B4 Admin Panel shell; B5 user/session/Connector controls; B6 audit/security views; B7 acceptance and runbook. |

## Stage 11C — Release Center

| Field | Proposal |
|---|---|
| Scope | Represent immutable releases, canary deployment, targeted acceptance, Production promotion, rollback, notifications, scheduled updates, maintenance mode and low-downtime topology. Automate the proven runbook; do not rebuild artifacts during promotion. |
| Dependencies | Stage 10 immutable artifact verifier, PostgreSQL/R2 backups, supervisor/Cloudflare controls, 11A step-up and 11B release permissions, Production signing inventory, durable operations/alerting. |
| Migrations | Add release/artifact records, immutable hashes/signatures, deployment attempts, approvals, gate results, environment pointers, rollback records and maintenance windows. Store no signing private key or cloud credential in the database. |
| Security risks | Artifact substitution, replayed approval, promotion of untested bytes, concurrent deploy races, destructive rollback, secret leakage, maintenance bypass and UI/API authorization mismatch. Require hash pinning, signed manifests, leases, two-phase state and append-only evidence. |
| Acceptance | Create release from clean source; verify signature/hash; deploy exact bytes to canary; collect gates; promote without rebuild; fail a gate and auto-rollback; interrupted deployment recovery; scheduled update cancel; maintenance behavior; notification delivery; concurrent-action denial. |
| Rollback | Release Center always emits a root-owned release-specific rollback package before mutation. Disable the control plane without stopping the runtime; operators retain reviewed CLI/runbook commands. Schema changes remain backward compatible with the previous runtime. |
| Commit boundaries | C1 release ledger; C2 artifact verification; C3 canary controller; C4 gate engine; C5 promotion/rollback; C6 schedules/maintenance; C7 notifications/UI; C8 failure and recovery acceptance. |

## Stage 11D — Environment and Release Branding

| Field | Proposal |
|---|---|
| Scope | Define authoritative `DEV`, `CANARY`, `BETA` and `STABLE` identities; use approved assets from `C:\Users\dimon\Desktop\CEO`; show environment/version consistently in browser title, application shell, installer and diagnostics. Branding must reflect signed runtime metadata, not a client toggle. |
| Dependencies | Release records from 11C; explicit `STRATFORGE_ENV`; approved asset/licensing inventory; Server/Connector independent version namespaces; design approval. |
| Migrations | Usually none. If branding is centrally managed, add a versioned non-secret branding configuration with environment-scoped activation and immutable asset hashes. |
| Security risks | Production impersonating Stable, cached cross-environment assets, misleading screenshots, unsafe external assets and version drift between HTML/API/Connector. Environment and trust badges must be server-derived and cache-busted. |
| Acceptance | Exact title/logo/badge/version across every page and installer; cache transition; accessibility and DPI checks; DEV/CANARY/BETA/STABLE distinction; API/UI identity parity; no Stable badge for development-signed bytes. |
| Rollback | Keep the prior branding bundle and manifest; atomically restore its pointer. Branding rollback must not change Server release identity or environment configuration. |
| Commit boundaries | D1 identity contract; D2 approved asset inventory; D3 browser/app shell; D4 installer/Connector; D5 cache/accessibility/visual acceptance. |

## Stage 11E — Stable Certification

| Field | Proposal |
|---|---|
| Scope | Complete trusted Windows Authenticode signing, externally protected Production P-256 release signing, literal container/host reboot acceptance and independent non-owner beta acceptance. Issue the first `STABLE` release only after all evidence passes. |
| Dependencies | 11A–11D accepted; hardware/managed signing custody; trusted timestamp provider; outer-host administration; consenting beta users and acceptance protocol; incident/rollback ownership. |
| Migrations | No mandatory product schema migration. Evidence/attestation records may use the 11C release ledger. |
| Security risks | Private-key export, unsigned dependency substitution, timestamp failure, reboot persistence gaps, beta PII exposure and premature Stable labeling. Use non-exportable or managed keys, separation of duties and redacted attestations. |
| Acceptance | Verified Authenticode chain/timestamp on every Windows binary; Server manifest verified against protected Production P-256 public fingerprint; clean-machine install; container restart and host reboot with services/backups restored; non-owner beta login/workspace/Connector acceptance; final rollback rehearsal and owner sign-off. |
| Rollback | Failed certification leaves dev/canary runtime operational but blocks Stable tag/channel. Revoke compromised certificates/keys, withdraw affected artifacts, restore the previous verified release and rotate trust material through a documented incident process. |
| Commit boundaries | E1 signing policy/inventory; E2 managed P-256 integration; E3 Authenticode pipeline; E4 reboot evidence; E5 beta protocol/evidence; E6 Stable release decision and tags. |

## Global acceptance and change policy

- No Stage 11 migration may make the previous Production release unable to
  start until the new release and rollback have both passed canary.
- Every privileged browser action requires server-side authorization, CSRF
  protection, a bounded idempotency key and durable redacted audit evidence.
- Secrets remain in protected providers/files and are never accepted through
  Git, chat, release records or command arguments.
- A code-complete section is not Production-accepted until its credentialed,
  clean-machine or external gate has actually run.
- Live trading and real payments remain separate owner-authorized projects.
