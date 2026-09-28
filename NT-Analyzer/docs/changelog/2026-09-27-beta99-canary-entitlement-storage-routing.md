# beta.99 — Canary entitlement storage routing

Release title: Canary entitlement storage routing

Release summary: Route subscription and entitlement state through the existing
authoritative PostgreSQL storage boundary in both Canary and Production, while
preserving Development's DPAPI-backed fail-closed behavior.

Release issue: #298

Source checkpoint SHA: `c68b19f9fa0c3161b31f42cb994db49f2f00faa3`.
PR #299 merged to `main` as final source SHA
`68ba3a95f804800195bb6e8dff556dd843b8eb6e`.

Verification result: PASS for the scoped beta.99 storage correction in
Development/CI, Canary and Production. This is not full beta.96 product-card
acceptance; that wider parity gate remains PARTIAL.

Affected subsystems: subscription/entitlement document read, reference read,
write, storage status and audit routing. No auth/device policy, Telegram,
report scheduler, reload-loop logic or market data application code is changed.

Release impact: immutable technical iteration `0.10.0-beta.99` was accepted for
its scoped correction on Canary and the same artifact is live in Production
without rebuild. It remains inside the open beta.96 product card. The separate
operational report-delivery switches remain paused; Local reporting is not cut
over.

Date: 2026-09-27. Status: **BETA / scoped Production PASS; product card IN PROGRESS**. Requester: project owner.
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

## Production promotion and smoke

The owner explicitly approved Production promotion of artifact
`art_3ae473a96bb24d439fd5cb6d3a1d1096` at source SHA
`68ba3a95f804800195bb6e8dff556dd843b8eb6e`, without rebuild. Approval
`apr_07a3758b5207418bb70e2096971b2873` was consumed only for that identity.
Deployment `dep_48d36d71b00e480eac201c3f3a71e0f1` completed every blue/green stage;
there were no pending migrations.

- pre-promotion Production backup:
  `/home/stratforge/production_data/backups/pre-beta99-production-peer-20260928T024620Z`;
  78 tables, verified dump SHA256
  `547209A64001E68CF36B552B4521D3E9CDA1A5B0B67E69BB1E1E2B89A9A1A136`,
  manifest SHA256
  `EA99515C2A5BEACE747AF112849869580FC795ACE772957E7243EA1E2F52B962`;
- public `/api/health/live` and `/api/health/ready` PASS on beta.99; config,
  data root, signing key, object storage, connector control, database, Telegram
  consumer and queue checks are green;
- owner browser/API PASS: authenticated owner role, owner workspace and admin
  capabilities; cache-disabled cold start produced one expected top-level
  navigation, zero runtime exceptions and no reload loop;
- existing non-owner Professional identity PASS: active authenticated session,
  `ux_mode=professional`, own active personal workspace and active `trial_full`
  entitlement; cache-disabled cold start produced one expected top-level
  navigation, zero runtime exceptions and no reload loop. Its active-work-time
  UI is exhausted, so the stable post-login surface is the normal access gate;
- Production Telegram owner path remains configured with the existing topic
  mapping. Current update/reply queues are empty, recent deliveries have one
  attempt and no current delivery/command error. No second-user Telegram action
  was performed;
- the release record initially lacked parser-visible `change_summary` because
  this document used `Change summary:`. The exact existing summary was copied
  into the encrypted release ledger with an audited `release.record_reconciled`
  event, then this canonical label was corrected to `Release summary:`. No
  artifact or server code was changed.

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
| Production | PASS; exact same artifact, deployment `dep_48d36d71b00e480eac201c3f3a71e0f1` |

Production periodic delivery switches are OFF. Before changing the one remaining
`chief_agent_reports=true` switch, the exact settings file was backed up at
`/home/stratforge/production_data/backups/pre-beta99-scheduler-pause-20260928T030245Z`
(SHA256 `E951120C6925E563B0BEF58BCA799750315C1A685EB5F07C432AE2FB585B0EBC`).
The shared Telegram integration remains enabled for interactive owner traffic;
only periodic report delivery is paused. Local `StratForge Vitek` remains
enabled and Running. No report-scheduler cutover has occurred.
Ordinary-user Telegram onboarding remains separate issue #296 and was not added
to beta.99. The known backup-role `BYPASSRLS` gap remains infrastructure debt;
the verified Canary and Production backups used the documented local PostgreSQL
peer path.

Current closeout: **IMPLEMENTATION COMPLETE**; **GIT CLOSEOUT COMPLETE FOR
APPLICATION SOURCE**; **CANARY PASS**; **PRODUCTION PASS**. Documentation
closeout is carried by PR #300 and remains subject to its normal merge gate.
