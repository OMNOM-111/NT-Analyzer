# 04. Environments, Release and Deployment

- Context Pack document: 04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md
- Last verified UTC: 2026-08-26T18:22:14Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Verified deployed artifact Git SHA: `ae9c5c913e4a3250dd978ce2bf682e52590e82ef`
- Scope: Environment isolation, immutable release, promotion and rollback
- Status: DONE

## Only supported release model

```mermaid
flowchart LR
  Dev[LOCAL DEV] --> Clean[clean merged main SHA]
  Clean --> CI[mandatory CI]
  CI --> Build[one signed immutable artifact]
  Build --> Canary[CANARY]
  Canary --> Accept[acceptance PASS]
  Accept --> Prod[same artifact PRODUCTION]
```

- Build once from the exact clean merged commit.
- Canary and Production receive identical code, UI/static assets, Documents and
  backend logic. Only environment DB, secrets, sessions, cookies, origins,
  queues and runtime state/configuration differ.
- Any application change after Canary acceptance starts a new cycle.
- Production promotion is a switch to the accepted artifact, never a rebuild,
  manual copy or server hotfix.

## Environment isolation

| Environment | Origin | Isolation |
| --- | --- | --- |
| Development | `http://127.0.0.1:8765/ui/` | Development data root, loopback session and local release initiator |
| Canary | `https://canary.stratforges.com` | separate Canary DB/storage/queues/sessions/cookies |
| Production | `https://app.stratforges.com` | separate Production DB/storage/queues/sessions/cookies |

The Environment Switcher opens the selected origin and never carries session
or browser storage between origins.

## Current beta.48 release

| Field | Value |
| --- | --- |
| Candidate | `rc_f4554de031954dca87bff3b2c54cfa0e` |
| Artifact | `art_dba8625e0b3b427896f8d1ead2382fa2` |
| Version / Git SHA | `0.10.0-beta.48` / `ae9c5c913e4a3250dd978ce2bf682e52590e82ef` |
| Build ID | `sf-0.10.0-beta.48-ae9c5c913e4a-20260826T181306Z` |
| Archive SHA256 | `B9C56184222AE4DADF6C979949A7FEC6A31F23D6048663425DD0BBCD69894E97` |
| Runtime/manifest SHA256 | `F7856E1EFEEEC6CDACECA48DB4851FFEA9F59CE31F90BEFE6BCAD6ABF6787ED6` |
| Signature / migrations | verified production trust / pending `0` |

Canary deployment `dep_a5abb0353395450889ff3d1013dc9050` completed all
blue-green stages and final acceptance
`chk_4e9892b9c99d464ea3b8560217269aa5`. Production deployment
`dep_e955efac5b1a4d189ba3b6b521aa8bd4` then promoted the exact same artifact
without rebuild.

| Environment | Release directory | Previous / rollback | Ready |
| --- | --- | --- | --- |
| Canary | `production_data/releases/0.10.0-beta.48-ae9c5c913e4a` | `0.10.0-beta.47-a40367fe8027` | PASS |
| Production | same | `0.10.0-beta.47-a40367fe8027` | PASS |

Both live endpoints report the same Git SHA, build ID and runtime artifact
SHA256. Production readiness includes config, data root, signing key, object
storage, database, connector control, Telegram consumer and queue.

## Promotion authority

Development owns the release ledger and submits the action, but Canary or
Production must answer from authoritative environment state. Candidate,
artifact, signature, timestamp, nonce, decision TTL, running identity, CI,
migrations and acceptance all verify fail-closed. `canary_passed` is followed
by owner approval and server-authoritative promotion; it does not authorize a
different artifact.

## Verification

- PR #182 and PR #183: mandatory CI `5/5` GREEN;
- full regression `2033 passed`, `32 skipped`, `0 failed`;
- Canary and Production deployment evidence:
  `identity_verified`, `signature_verified`, `readiness_verified`,
  `same_immutable_artifact` all true;
- static beta.48 JS assets on Canary matched LOCAL bytes;
- no pending migration and no secret rotation.

## Canonical evidence

- [beta.48 LIVE Connector closeout](../changelog/2026-08-26-beta48-live-connector-storage-reconciliation.md)
- [environment and release identity ADR](../adr/0001-environments-and-release-identity.md)
- `app/runtime_env.py`
- `app/release_control.py`
- `app/release_center.py`
- `tools/stage9_remote_release.sh`

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-26T18:22:14Z | GPT-5.5 через Codex по запросу owner | Replaced historical non-accepted beta.30/beta.31 body with the current accepted beta.48 one-artifact Canary-to-Production release identity.
-->
