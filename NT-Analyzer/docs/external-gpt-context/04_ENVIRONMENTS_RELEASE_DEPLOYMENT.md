# 04. Environments, Release and Deployment

- Context Pack document: 04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md
- Last verified UTC: 2026-09-27T21:30:00Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Current deployed artifact Git SHA: `4f6bb0b3a0d20712f249afdc9c93538567fd6a8d`
- Scope: Environment isolation, immutable release, promotion and rollback
- Status: PARTIAL

Production incident 2026-09-27: beta.97 was promoted as immutable artifact
`art_8fec9cdd6ed14dd19cb762291a2a756f`, but final closeout is blocked by a
confirmed authenticated overview full-page reload loop when runtime accounts are
already offline/unconfirmed. beta.92 contains the same trigger and is not a
reliable rollback for this state. The minimal code correction is a new beta.98
cycle; no server hotfix or artifact mutation is allowed. beta.98 is now deployed
to Canary from its own final main SHA and signed artifact. Production reports
stay OFF and Local `StratForge Vitek` stays ON. See the
[incident record](../changelog/2026-09-27-beta98-production-reload-loop-hotfix.md).

Historical pre-deployment contract (2026-09-26): beta.97 consolidates periodic owner reports under
the Vitek/Deputy controller and makes Production the sole default operational
owner of the shared Telegram bot. Development and Canary remain passive for
topic creation, update consumption, chat mirroring and reports while retaining
login/access callbacks. That candidate later completed its immutable promotion,
but its final closeout is superseded by the live incident above. The required
sequence for beta.98 remains merge → final-main-SHA CI → one signed immutable
artifact → Canary acceptance → separate owner approval → same artifact in
Production. [Candidate record](../changelog/2026-09-26-beta97-telegram-report-cutover-release-candidate.md).

Development supervisor origin correction (2026-09-23): default identity is the actual `http://127.0.0.1:<port>` listener, never the Production hub hostname. An explicitly configured Development HTTPS origin is supported. This prevents false gateway self-loop isolation while preserving true self-loop rejection. [Incident and verification](../changelog/2026-09-23-local-chart-gateway.md). No server release is included.

Local-only Preview change (2026-09-22): the two shared-model QA profiles may call
one authenticated parent loopback service for catalog/invoke only. Other outbound
connections remain blocked. The bridge expires after 30 minutes and allows at
most 32 calls / USD 0.25 while preserving the model's own caps. Exit removes the
child's data/process/container; minimal owner usage accounting remains. No
Canary/Production deployment or release identity changed.
Local 8765 now runs clean `c9a9d7e6a3080988af1c90ff65f2520b0e74cc70`, build
`dev-0.10.0-beta.96-c9a9d7e6a308`, Development, Preview=false. The owner Preview
launch endpoint passed real-provider acceptance and cleanup; owner access settings
matched the before snapshot exactly. This is a Local code switch, not a release artifact.
[Canonical evidence](../changelog/2026-09-22-shared-models-local-continuation.md).

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

Every candidate snapshots one canonical `docs/changelog/` release/change
record. The owner sees its title, summary, PRs, source SHA, version/build,
artifact, current stage/status, checks, duration and the identity reported by
DEV/Canary/Production. Approval and promotion fail closed unless title, change
summary, source SHA and final verification PASS are present.

## Environment isolation

| Environment | Origin | Isolation |
| --- | --- | --- |
| Development | `http://127.0.0.1:8765/ui/` | Development data root, loopback session and local release initiator |
| Canary | `https://canary.stratforges.com` | separate Canary DB/storage/queues/sessions/cookies |
| Production | `https://app.stratforges.com` | separate Production DB/storage/queues/sessions/cookies |

The Environment Switcher opens the selected origin and never carries session
or browser storage between origins.

## Current environments: beta.98 Canary / beta.97 Production

Canary now points to the signed beta.98 hotfix artifact. Identity/readiness,
restart persistence and owner offline cold-start passed; a real separate
Professional session/cookie cold-start remains required before Canary acceptance.
Production remains on beta.97 and has no beta.98 approval.

| Field | beta.98 Canary |
| --- | --- |
| Version / source SHA | `0.10.0-beta.98` / `0b9233d7c8983adc0a3a6c37350a3974770cb738` |
| Candidate / artifact | `rc_8b8b51c156f844ce9829edeceb70e484` / `art_b05720a1f2d44672805b45b513f0203e` |
| Build ID | `sf-0.10.0-beta.98-0b9233d7c898-20260927T210136Z` |
| Archive SHA256 | `FEC858A913F5B90455ED34E10071204859D2CB2CC64EC1E0BC8024FD50CB5029` |
| Manifest SHA256 | `F0E48884C3933E487349C8AB3673989FC5FEF180B85B72F7A507EE7EAA312D43` |
| Release dir | server data-root relative `releases/0.10.0-beta.98-0b9233d7c898` |
| Backup | server data-root relative `backups/pre-beta98-canary-peer-20260927T210222Z` |
| Stage | Canary deployed; Professional acceptance pending; Production not authorized |

Production beta.97 identity remains:

| Field | Value |
| --- | --- |
| Version / source SHA | `0.10.0-beta.97` / `4f6bb0b3a0d20712f249afdc9c93538567fd6a8d` |
| Artifact | `art_8fec9cdd6ed14dd19cb762291a2a756f` |
| Build ID | `sf-0.10.0-beta.97-4f6bb0b3a0d2-20260927T060203Z` |
| Archive SHA256 | `F7B522C845D4DEA93BFB15F09C37F5B25A95A0C474052FB70F27A2F6DA6F8FF3` |
| Manifest SHA256 | `B5FC667474ED38CD5AA3600F22E4DD97495958DCC906BCEAD1CA80CF2838F9D2` |
| Previous / rollback | beta.92 / `0.10.0-beta.92-9d800770d08e` (preserved; same latent reload trigger) |

Sources: [beta.98 incident record](../changelog/2026-09-27-beta98-production-reload-loop-hotfix.md),
[beta.97 candidate record](../changelog/2026-09-26-beta97-telegram-report-cutover-release-candidate.md).

### Historical beta.86 snapshot

| Field | Value |
| --- | --- |
| Candidate | rc_049d14ab6af640758a69b00432bb6e3d |
| Artifact | art_e627d14a2dbb49fdaf98a0cc9847e8c2 |
| Version / Git SHA | 0.10.0-beta.86 / 22ed7097b4ac9e863304197e118b1d3ce5109e8a |
| Build ID | sf-0.10.0-beta.86-22ed7097b4ac-20260901T005018Z |
| Archive SHA256 | 8052B7A5FC36E1519A7AFCD3B60E5A221F744DE768585D765145245911BABE7D |
| Manifest SHA256 | 0E95CF8B879AE6D66D11F70BAD566E2658180AE432CD8EAEEE12CC50B4CFBCA4 |
| Signature / worktree | verified / clean |

Canary accepted beta.86 and Production received the exact same artifact without
rebuild. live_trading_allowed stays false. Earlier cycles are in their
changelog entries.

The beta.86 release is named `Legacy Isolation + Telegram Bot Cleanup` and
contains merged PR #254 and PR #255 plus release-record PR #256. Its terminal
state is `production_live`; `/live` and `/ready` returned 404 before this
release and 200 after, which is what proves the new artifact is serving.

### Three gates stand between a candidate and Production

Approved main asks where the code came from: branch is main, worktree clean,
HEAD equal to origin/main, the commit an ancestor of origin/main, and that exact
SHA green in CI. A squash merge creates a new SHA, so a green pull request does
not make the commit that reached main green -- both beta.84 and beta.85 were
refused on the first attempt for exactly that, and published unchanged once the
merge commit finished CI.

Forward-only asks whether publishing would move Production forward. An old
commit on main is as approved as a new one, so provenance alone let a
superseded candidate sit one click from rolling Production back. Publication now
requires the candidate to be the deployed commit or a descendant of it.

Production identity is fail-closed. "Never deployed" permits a first
publication; "deployed but the commit cannot be read" refuses until identity is
restored. Conflating the two is how a rollback gets published by accident.

Rollback is untouched by all of this: going back has its own contract.

### The shipment has its own gate

python tools/pre_release_check.py assembles the exact production file set and
runs four checks inside it: the static scan as the signer runs it, runtime
reads, Python compilation and JavaScript syntax. The selection lives in
tools/release_bundle.py and is imported by the builder, so the check and the
signer cannot disagree. A public document that no release can carry is a
contradiction to resolve, not an exemption to record.

## Promotion authority

Development owns the release ledger and submits the action, but Canary or
Production must answer from authoritative environment state. Candidate,
artifact, signature, timestamp, nonce, decision TTL, running identity, CI,
migrations and acceptance all verify fail-closed. `canary_passed` is followed
by owner approval and server-authoritative promotion; it does not authorize a
different artifact.

## Verification

- beta.79 closeout through PR #230: mandatory CI GREEN;
- full regression `2327 passed`, `32 skipped`, `0 failed`;
- Canary and Production deployment evidence:
  `identity_verified`, `signature_verified`, `readiness_verified`,
  `same_immutable_artifact` all true;
- Canary and Production server surfaces display beta.79 from the same release
  directory;
- SERVER BACKTEST cancel, Connector state honesty, auth hotspot and secret
  containment closeout passed;
- no pending migration.

## Canonical evidence

- [beta.79 secret management and cancel closeout](../changelog/2026-08-29-beta79-secret-management-and-cancel-closeout.md)
- [environment and release identity ADR](../adr/0001-environments-and-release-identity.md)
- `app/runtime_env.py`
- `app/release_control.py`
- `app/release_center.py`
- `tools/stage9_remote_release.sh`
