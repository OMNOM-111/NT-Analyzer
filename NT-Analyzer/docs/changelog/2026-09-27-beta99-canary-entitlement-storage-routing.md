# beta.99 — Canary entitlement storage routing

Release title: Canary entitlement storage routing

Change summary: Route subscription and entitlement state through the existing
authoritative PostgreSQL storage boundary in both Canary and Production, while
preserving Development's DPAPI-backed fail-closed behavior.

Release issue: #298

Source checkpoint SHA: `c68b19f9fa0c3161b31f42cb994db49f2f00faa3`.
PR #299 merged to `main` as final source SHA
`68ba3a95f804800195bb6e8dff556dd843b8eb6e`.

Verification result: PASS in Development/CI and Canary. Production promotion is
not authorized and remains a separate artifact-specific owner gate.

Affected subsystems: subscription/entitlement document read, reference read,
write, storage status and audit routing. No auth/device policy, Telegram,
report scheduler, reload-loop logic, market data or Production data is changed.

Release impact: immutable release `0.10.0-beta.99` is accepted on Canary.
Production remains unchanged on beta.97 until the owner explicitly approves
this exact artifact.

Date: 2026-09-27. Status: **BETA / Canary PASS**. Requester: project owner.
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
- PR #299 mandatory checks PASS; PR #297 was confirmed to contain no unique
  changes and closed as superseded;
- mandatory CI on final `main` SHA PASS: run `36365092457`, including
  `bridge-build-if-nt8-present` and `python-tests`;
- `python tools/pre_release_check.py` PASS on the exact clean release checkout:
  654 bundle files, bundle static scan, runtime reads, Python compilation and
  shipped JavaScript syntax;
- pre-Canary backup verified at
  `/home/stratforge/production_data/backups/pre-beta99-canary-peer-20260928T022038Z`
  (78 tables; dump SHA256
  `C6E8D6B8F952768E1DB63D85A603AC05FC3E1DFC094450381BC1E1045B00F328`);
- Canary identity/readiness PASS with all readiness checks green;
- real second Google Professional user PASS: exactly one active non-owner
  identity, one owned personal workspace, one active workspace, one active
  `trial_full` entitlement and one active session. The additional membership is
  viewer-only in the owner-training workspace, not owner authority;
- cold start with browser cache disabled: one expected top-level navigation in
  30 seconds, zero runtime exceptions and no reload loop. Two 403 responses from
  owner-gated AI Lab endpoints were expected ACL denials and did not destabilize
  the page;
- Canary services restarted; the same release identity, browser session,
  personal workspace and entitlement persisted. Post-restart reload again had
  one expected top-level navigation and zero runtime exceptions;
- Release Center candidate `rc_dd6b884b2bfe4f7dace6c76bb6cbf12c`
  records the final Canary acceptance as PASS.

## Immutable release identity

| Field | Value |
| --- | --- |
| Version | `0.10.0-beta.99` |
| Source SHA | `68ba3a95f804800195bb6e8dff556dd843b8eb6e` |
| Build ID | `sf-0.10.0-beta.99-68ba3a95f804-20260928T021954Z` |
| Artifact | `art_3ae473a96bb24d439fd5cb6d3a1d1096` |
| Archive SHA256 | `BD6FDEC99112154E9B0B4FBA26A2F1E257399D9B8FC15BC4500E1BD65AEBDC43` |
| Manifest/runtime SHA256 | `081C9A99480C49BFBC13C29EA061E994B8310FB6A82EE431B31A38661952A2FB` |
| Signature | `ECDSA_P256_SHA256_RAW`, verified, production trust |
| Canary | PASS; exact artifact deployed and restart-persistent |
| Production | beta.97 unchanged; beta.99 not authorized |

Production report schedulers remain OFF and Local `StratForge Vitek` remains ON.
Ordinary-user Telegram onboarding remains separate issue #296 and was not added
to beta.99. The known backup-role `BYPASSRLS` gap remains infrastructure debt;
the verified Canary backup used the documented local PostgreSQL peer path.

Current closeout: **IMPLEMENTATION COMPLETE**; **GIT CLOSEOUT COMPLETE FOR
APPLICATION SOURCE**; **CANARY PASS**; **PRODUCTION APPROVAL PENDING**.
