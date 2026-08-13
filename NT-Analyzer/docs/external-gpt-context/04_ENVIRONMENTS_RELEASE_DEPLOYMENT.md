# 04. Environments, Release and Deployment

- Context Pack document: 04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md
- Last verified UTC: 2026-08-13T04:59:15Z
- Verified against Git SHA: cad53f682e413db86bc3a77e57f8942baf4d4bc3
- Scope: Deployment environments, release channels, immutable promotion and rollback boundaries
- Status: DONE

## Evidence modes

- **Repository evidence** in this document describes what the repo implements:
  env/channel split, fail-closed startup, build scripts, Release Center schema
  and deploy templates.
- **Operational evidence** describes what the last accepted closeout actually
  deployed: the canonical source is
  [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md).
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
| DEV | `http://127.0.0.1:8765/ui/` | local data only, local owner session, no Production data, loopback-only assumptions | `[DEV]`, app identity `6b6dc458`, `dirty=false`, `deployment_environment=development`, `config_profile=local-development` |
| CANARY | `https://canary.stratforges.com` | separate DB/queues/storage/cookies/Connector sessions; owner/admin/developer only | `[CANARY]`, `instance=stratforge-canary-01`, `config_profile=production-canary`, DB `stratforge_canary`, topology `api / worker-canary / operations-canary`, same artifact as Production |
| PRODUCTION | `https://app.stratforges.com` | separate DB/queues/storage/cookies/Connector sessions; public app | `[BETA]`, `instance=stratforge-linux-production-01`, `config_profile=production-primary`, DB `stratforge_production`, Supervisor `api-app / worker / operations / telegram`, previous slot `0.10.0-beta.1-795db0c1` |

## Current release/build identity

- Public version file: `0.10.0-beta.1`.
- Build timestamp in `VERSION.json`: `2026-08-11T18:35:00Z`.
- Repository evidence snapshot for this sync pass: `cad53f682e413db86bc3a77e57f8942baf4d4bc3`.
- Operational live artifact: git `6b6dc4589407855526cf6cc345376d64cf95200e`,
  build `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256
  `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`, archive
  SHA256 `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730`.
- Accepted release path: Canary first, then the same release directory promoted
  to Production (`same_release_dir=true`, no rebuild).

## Release Center and signing

| Area | Current state |
| --- | --- |
| Artifact creation | `tools/build_server_release.py` and `tools/build_connector_release.py` produce manifest, checksum and signature metadata |
| Release ledger | `app/release_center.py` plus `sf_release_*` tables model candidates, artifacts, deployments, checks, approvals, notifications and rollbacks |
| Blue-green | `app/blue_green.py` and `0010_blue_green_deploy_steps.sql` model slot switching and maintenance windows |
| Exact-artifact promotion | same artifact fingerprint is stored and compared in schema/contracts |
| Live execution proof | accepted operational closeout exists for `6b6dc458` Canary -> same-directory Production |

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
- Promotion from Canary to Production is designed for the **same artifact** and
  this was operationally confirmed for `6b6dc458`.
- Previous Production slot is `0.10.0-beta.1-795db0c1`.
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
- [../current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md](../current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md)
- [../../../.github/workflows/ci.yml](../../../.github/workflows/ci.yml)
- [../../../.github/workflows/next-architecture-ci.yml](../../../.github/workflows/next-architecture-ci.yml)