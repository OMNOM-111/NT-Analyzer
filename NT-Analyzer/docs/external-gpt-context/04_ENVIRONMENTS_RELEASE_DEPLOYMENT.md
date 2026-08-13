# 04. Environments, Release and Deployment

- Context Pack document: 04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md
- Last verified UTC: 2026-08-13T09:49:37Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Deployment environments, release channels, immutable promotion and rollback boundaries
- Status: DONE

## Evidence modes

- **Repository evidence** in this document describes what the repo implements:
  env/channel split, fail-closed startup, build scripts, Release Center schema
  and deploy templates.
- **Operational evidence** is environment-specific. Current Canary evidence is
  [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md); Production remains on the
  [2026-08-12 snapshot](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md).
- Do not answer a “what is live right now” question from repository templates
  alone when operational closeout evidence exists.

## Canonical promotion model

```mermaid
flowchart LR
  Dev[Local DEV] --> Clean[clean commit]
  Clean --> Build[signed immutable artifact]
  Build --> Canary[CANARY deploy]
  Canary --> Checks[acceptance + evidence]
  Checks --> Promote[same artifact SHA]
  Promote --> Prod[PRODUCTION deploy]
```

## Two separate axes

| Axis | Current meaning |
| --- | --- |
| `DEPLOYMENT_ENV` | where the software runs: `development`, `canary`, `production` |
| `RELEASE_CHANNEL` | maturity of the build: `dev`, `beta`, `stable` |

Git branch, deployment environment and release channel are not synonyms.

## Environment identities

| Environment | Origin / opening mode | Isolation contract | Operational snapshot |
| --- | --- | --- | --- |
| DEV | `http://127.0.0.1:8765/ui/` | local data only, local owner session, no Production data, loopback-only assumptions | `[DEV]`, app identity `7ebda6fa`, `dirty=false`, `deployment_environment=development`; final MNQ/MES multi-browser acceptance PASS |
| CANARY | `https://canary.stratforges.com` | separate DB/queues/storage/cookies/Connector sessions; owner/admin/developer only | `[CANARY]`, git `7ebda6fa`, build `sf-0.10.0-beta.1-7ebda6faf2e7-20260813T093530Z`, `instance=stratforge-canary-01`, DB `stratforge_canary`, topology `api / worker-canary / operations-canary`; Telegram `EXTERNAL BLOCKED` |
| PRODUCTION | `https://app.stratforges.com` | separate DB/queues/storage/cookies/Connector sessions; public app | `[BETA]`, `instance=stratforge-linux-production-01`, `config_profile=production-primary`, DB `stratforge_production`, Supervisor `api-app / worker / operations / telegram`, previous slot `0.10.0-beta.1-795db0c1` |

## Current release/build identity

- Public version file: `0.10.0-beta.1`.
- Build timestamp in `VERSION.json`: `2026-08-11T18:35:00Z`.
- Repository evidence snapshot for this sync pass: `7ebda6faf2e7c64d4a707a41062b29857882181a`.
- Current Canary artifact: build
  `sf-0.10.0-beta.1-7ebda6faf2e7-20260813T093530Z`, archive SHA256
  `AFBCEADF571A925AED91D959B5AE9AF8E8B14207E4A27FACE5C6CE73386E4782`, manifest
  SHA256 `CE09030A2050CBF7D2BCE985D90E36D0C0294F298178B862F4AFBDB0C3D351D3`.
- Current Production artifact remains git
  `6b6dc4589407855526cf6cc345376d64cf95200e`, build
  `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256
  `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`, archive
  SHA256 `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730`.
- `7ebda6fa` passed Canary and is eligible for exact-artifact Production
  promotion only after a separate owner approval. No Production rebuild or
  switch occurred in this closeout.

## Release Center and signing

| Area | Current state |
| --- | --- |
| Artifact creation | protected `stage9_ssh` signer builds a production-trust artifact from the verified clean selected `HEAD`; `tools/build_server_release.py` produces manifest, checksum and signature metadata |
| Release ledger | `app/release_center.py` records candidates, artifacts, real deployments, granular checks, approvals, notifications and rollbacks; `7ebda6fa` lifecycle was completed through the Release Center |
| Blue-green | real Canary stages and a real rollback→re-promote rehearsal passed; `app/blue_green.py` and `0010_blue_green_deploy_steps.sql` retain the step/maintenance evidence |
| Exact-artifact promotion | same artifact fingerprint is stored and compared in schema/contracts |
| Live execution proof | `7ebda6fa` has current real Canary build/deploy/rollback proof; earlier `6b6dc458` retains accepted Canary→Production same-directory proof |

## Environment Switcher

- Environment Switcher is a product/admin surface, not a way to reuse the same
  cookies or browser storage across origins.
- The contract is separate-origin open in a new tab; current tab backend does
  not silently switch under the user.
- Local DEV access requires loopback identity probing rather than production-like
  trust assumptions.
- Accepted 2026-08-12 browser evidence: DEV / CANARY / PROD open in new tabs,
  sessions/cookies/CSRF do not carry across, and ordinary users do not see
  DEV/CANARY.

## Git / PR / CI model visible from repo

- Main CI runs on push and pull request to `main`.
- Next Architecture CI adds static gates and cross-platform pytest.
- Root workflow explicitly disallows direct `main` closeout without owner
  confirmation; current pull-request template checks `No direct main changes`.

## Readiness and rollback limitations

- Migrations in Phases 3-11 are additive-first; rollback is expected to disable
  newer surfaces rather than drop identity links or release evidence.
- Promotion from Canary to Production is restricted to the **same artifact**.
  This was operationally confirmed for `6b6dc458`; `7ebda6fa` has passed Canary
  but has not been approved or promoted.
- Canary previous is `0.10.0-beta.1-de7acaed`. Production previous is
  `0.10.0-beta.1-795db0c1`.
- Real Canary rollback rehearsal restored `de7acaed`, verified readiness and
  re-promoted `7ebda6fa` (`rollback_verified=true`, `re_promoted=true`).
- The `/ready` hang root cause was full Connector JSON deserialization under
  lock plus overlapping short-timeout curl polling; the live fix uses a
  lightweight DB/Connector probe, bounded per-request timeouts, single-flight,
  `/live` before `/ready`, and one bounded deadline.
- This Context Pack task itself should never trigger runtime deployment.

## What to treat as historical only

- Sibling `StratForge Releases/server-0.9.0-dev.*` bundles are useful evidence of
  artifact naming, but they are not current source of truth for the live app.
- Older pre-`6b6dc458` live snapshots are historical once a newer accepted
  closeout supersedes them.

## Canonical evidence

- [../adr/0001-environments-and-release-identity.md](../adr/0001-environments-and-release-identity.md)
- [../../README-RUN-MODES.md](../../README-RUN-MODES.md)
- `app/runtime_env.py`
- `app/release_center.py`
- `app/blue_green.py`
- [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md)
- [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md)
- [../current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md](../current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md)
- [../../../.github/workflows/ci.yml](../../../.github/workflows/ci.yml)
- [../../../.github/workflows/next-architecture-ci.yml](../../../.github/workflows/next-architecture-ci.yml)
