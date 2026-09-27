# beta.99 — Canary entitlement storage routing

Release title: Canary entitlement storage routing

Change summary: Route subscription and entitlement state through the existing
authoritative PostgreSQL storage boundary in both Canary and Production, while
preserving Development's DPAPI-backed fail-closed behavior.

Release issue: #298

Source checkpoint SHA: `c68b19f9fa0c3161b31f42cb994db49f2f00faa3`;
final source SHA requires merge to `main` and mandatory final-main CI.

Verification result: IN PROGRESS (focused regression PASS; PR CI, merged-main
CI, immutable artifact and full Canary acceptance remain gated)

Affected subsystems: subscription/entitlement document read, reference read,
write, storage status and audit routing. No auth/device policy, Telegram,
report scheduler, reload-loop logic, market data or Production data is changed.

Release impact: new immutable release cycle `0.10.0-beta.99`. beta.98 remains
unchanged on Canary and beta.97 remains unchanged in Production until the full
release contract is completed.

Date: 2026-09-27. Status: **BETA / Development**. Requester: project owner.
Implementation: AI-assisted change.

## Incident

Real separate-user beta.98 Canary registration created an active non-owner
Professional account with `initial_trial_pending=true`, then failed to create
the trial or personal workspace because `subscriptions.py` selected Windows
DPAPI on Linux Canary. The browser remained unauthenticated. Exact evidence is
in [the blocker record](2026-09-27-canary-professional-registration-storage-blocker.md)
and issue #298.

## Scoped correction

`subscriptions.py` now uses the same authoritative-server predicate already
used by account and workspace stores. The predicate delegates to
`storage_router.production_enabled()`, which is true only for an explicit
Canary/Production server environment with PostgreSQL storage enabled.
Development continues to use the encrypted local DPAPI store and still fails
closed when DPAPI is unavailable.

The change covers the five subscription storage surfaces that previously used
the literal Production condition:

- document read;
- cached/reference read;
- document write;
- storage status;
- audit append.

No direct entitlement/workspace seeding and no server-side hotfix are allowed.
After deployment the existing pending registration outbox should complete
idempotently through normal login/registration flow; that recovery must be
verified before deleting the test account.

## Verification

- focused affected registration/workspace/cabinet regression: 37 PASS;
- new Canary-path test proves read/reference/write/status/audit use the
  authoritative server router even when Windows DPAPI is unavailable;
- new Development-path test proves the DPAPI fail-closed behavior is preserved;
- broader regression, pre-release bundle scan and CI remain required.

Current closeout: **IMPLEMENTATION COMPLETE**; **GIT CLOSEOUT IN PROGRESS**;
**STAGE NOT CLOSED**.
