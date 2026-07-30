# Stage 10 execution log — 2026-07-29

Status: **PRE-CUTOVER BLOCKED**. This log records completed work and the exact
external gates that remain. It does not claim Production readiness or STABLE.

## Source preservation and convergence

1. Confirmed the owner checkout at
   `C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader` was on
   `antigravity/stage10-partitioned` at
   `56f6da0272f6d51d59605884060044f2b419d55e`, with 12 tracked changes,
   one untracked file, and an empty index.
2. Created and verified the rollback set at
   `C:\SF10\pre-convergence-20260729T211708Z`: Git bundle, HEAD archive,
   exact checkout archive, binary diff, untracked snapshot, and SHA-256
   manifest.
3. Created the isolated worktree `C:\SF10\development` and branch
   `codex/stage10-development`.
4. Merged Stage 9 acceptance commit
   `2bf502784f65e4a6e91b48bf7d845299fea751db` with the owner baseline in merge
   commit `b0539a09550c770eafd448de52dd7ecadf8ea7af`.
5. Preserved the owner checkout exactly. The closing check still showed the
   original branch, commit, 12 tracked changes, and one untracked file.
6. Kept `codex/stage10-production` at
   `2bf502784f65e4a6e91b48bf7d845299fea751db`. It is not advanced until the
   same signed candidate is accepted and deployed.

No reset, clean, checkout-discard, rebase, or force operation was used.

## Stage 10 source changes

- Excluded mutable Development data, SQLite files, tokens, dialogs, reports,
  logs, and portfolio state from Server releases. Only the two required static
  catalog files under `data/catalog/` are selected.
- Added external P-256 fingerprint pinning to Server archive verification.
  Stable/canary channels cannot downgrade themselves to Development trust.
- Bound reused Production candidate reports to the independently loaded
  Production key rather than trusting their self-reported fingerprint.
- Required explicit Authenticode timestamp configuration and post-signing
  `signtool verify /pa /all /tw` for Setup, Updater, and Bridge.
- Routed explicit Development and Production AI registry, rating, job queue,
  and NinjaTrader mutable paths through their environment data root.
- Kept source recovery disabled in explicit Production.
- Added the clean-worktree, immutable, one-command release orchestrator and
  the two-environment release/rollback runbook.
- Replaced one obsolete PostgreSQL test harness with the real public
  `PostgresClient` and `DocumentRepository` contract.

The tested release-source tree was committed as
`8917ffad9e14d9899f8532cbec86ed0f0f742035` with tree
`e7eb8a07464f040e93bf756e70b5ea34a40f04c7`. Its staged binary patch SHA-256
was `7C55CD05B0AB55C7C9432054C975D799AD0DEA9FA0FA610AE1ACBB0C8BB28398`.

## Verification chronology

- Pre-merge focused PostgreSQL tests: 21 passed; 12 credential-gated tests
  skipped before the real test database was attached.
- Hardened release/isolation focused tests: 51 passed.
- Final trust-pin focused tests: 41 passed.
- First full PostgreSQL run preserved as failed evidence: 921 passed, one
  failed because the restored test referenced removed internal functions.
  No application defect was hidden; the test was rewritten against the real
  repository API.
- Targeted real PostgreSQL reproduction after that correction: PASS.
- Intermediate full run: 922 passed, followed by all non-pytest gates PASS.
- Final run after the last source change: 924 passed, zero failed, zero
  skipped; migrations 0001–0004 applied to a fresh database with `pending=[]`.
- Legacy runner: 13/13 suites PASS.
- Python compileall: PASS.
- JavaScript syntax: 32 files, zero failures.
- JSON parse: 73 files, zero failures.
- C# Release builds: four projects, zero warnings, zero errors.
- CSP, secret, and Markdown static scans: PASS.

The final regression database was archived and then dropped. Its custom dump
SHA-256 is
`e3f72cb6804cf4bc874494315cd82bb5b8c109908bcea276e1fb9c2b5300dfbf`.

The regression helper's generated `tested_tree` field used the pre-existing
Git index and is therefore not used as source identity evidence. The tests ran
against the working tree that was staged without source edits immediately
afterward; the authoritative identity is the commit/tree pair above, together
with the preserved gate logs and hashes.

## Development and immutable release

The isolated Development smoke ran on `127.0.0.1:18780` with a temporary
Development data root. Health was alive, `/ui/` returned HTTP 200 HTML,
Production database configuration was absent, and both live trading and real
payments were false. The pre-existing owner backend was not stopped.

From clean commit `8917ffad`, this command completed successfully:

```powershell
py -3 tools/release_candidate.py --server-only
```

It produced immutable Server `0.9.0-dev.13`:

- archive SHA-256:
  `B52299A2460BFACBCE1484086658967375E9FED65498B6030F96AF3025D8F693`;
- manifest SHA-256:
  `4BC7AD4267E032203CF7B62C371953E9C5B055ADDDC911D2B5E07B7B7457E6A0`;
- Development key fingerprint:
  `SHA256:124cb8285af3660877daabc0470b6552d82d05338b00e503c426ca8bd3de6a13`;
- exact file count: 325;
- migration count: four;
- signature, archive self-verification, and static scan: PASS.

Annotated tag `stratforge-server-v0.9.0-dev.13` points to the exact source
commit. After the off-host gate passed, the artifact, reports, and verifier
were uploaded to the isolated Linux incoming directory. Remote SHA-256,
manifest signature, external Development fingerprint pin, exact source
revision, and 325-file set all passed. The live canary symlink has not yet been
changed because that risk action requires explicit owner confirmation.

## Off-host backup and restore

- Cloudflare R2 access is bucket-scoped: account-level ListBuckets is denied,
  one designated bucket accepts signed access, and an anonymous listing does
  not return content.
- The previously empty bucket was initialized as a restic v2 repository. The
  repository ID is
  `d3a9a38adf1799b895499b6433394e9353de66394bd137d44e3b419e65464115`.
- A new quiesced PostgreSQL plus artifact backup was retained at
  `/home/stratforge/production_data/backups/stage10-offhost-source-20260730T010247Z`
  and encrypted into R2 snapshot
  `839d2519c209d0bd5490f9221a20e6d8ec17f8faf536fd507abce38ce47a59b8`.
- Full `restic check --read-data` passed.
- Restic restore produced a byte-identical manifest. The isolated PostgreSQL
  restore matched table counts and migrations 0001–0004; restored artifact
  hashes matched the manifest.
- The temporary restore database and both temporary restore directories were
  deleted only after PASS. Existing same-host backups remain.
- Observed isolated restore time was 4.004 seconds. Target RPO is 24 hours.
- Supervisor now runs the daily scheduler for 03:30 UTC. Retention is 14 daily,
  8 weekly, 12 monthly, and 3 yearly snapshots. Scheduler configuration has a
  verified rollback directory.

## External state at pause

- Linux current: `0.9.0-dev.12-847f69f3`; previous:
  `0.9.0-dev.11-77f68fb2`.
- PostgreSQL, API, worker, operations, artifact server, and Cloudflare are
  RUNNING. Telegram is STOPPED because its token is absent.
- `canary.stratforges.com` reports Production profile, dev.12, canary channel,
  live trading false, and real payments false.
- `app.stratforges.com` still reports local Development dev.10. It was not
  switched.
- Telegram, AI-provider, market-data, Production P-256, Authenticode, and
  public release-fingerprint configuration names are unset.
- `signtool` and the protected local Production signing file are absent.
- Restic 0.16.4 uses a root-only `0600` credential file and an independent
  Cloudflare R2 failure domain. The same-host backup copy remains on the data
  logical volume as an additional recovery tier.
- The process is inside a Docker container with no Docker socket and offline
  systemd. Container restart policy and host reboot cannot be verified from
  the granted boundary.

No Production domain cutover, live trading, real payment, Telegram delivery,
AI request, market-data request, external beta action, container restart, or
host reboot was performed.
