# Stage 10 execution log — closed available scope 2026-08-01

Status: **LINUX PRODUCTION CUTOVER COMPLETE; NO OPEN P0/P1.** Formal stable
signing, outer-host reboot proof and non-owner beta sign-off remain external
evidence and are not misreported as completed.

## 1. Source preservation and branch convergence

1. The owner checkout remained on `antigravity/stage10-partitioned` at
   `56f6da0272f6d51d59605884060044f2b419d55e`. Stage 10 did not stage, reset,
   clean, discard, rebase or force-push any owner path.
2. Before convergence, the verified backup set at
   `C:\SF10\pre-convergence-20260729T211708Z` captured a Git bundle, HEAD
   archive, exact checkout archive, binary diff, untracked snapshot and
   SHA-256 manifest.
3. Work continued only in the isolated worktree
   `C:\SF10\development\NT-Analyzer` on `codex/stage10-development`.
4. Stage 9 acceptance `2bf502784f65e4a6e91b48bf7d845299fea751db`
   was merged with the owner baseline in `b0539a09550c770eafd448de52dd7ecadf8ea7af`.
5. The fully tested release source is
   `8917ffad9e14d9899f8532cbec86ed0f0f742035`, tree
   `e7eb8a07464f040e93bf756e70b5ea34a40f04c7`.
6. After cutover, `codex/stage10-production` was atomically fast-forwarded
   from `2bf50278` to exact deployed source `8917ffad`. The hidden rollback ref
   `refs/stage10-backups/production-pre-cutover-20260801` preserves the former
   value.

The owner checkout had an empty index at the final audit. Its changing
tracked/untracked runtime files were left intact; no Git operation was run
against them.

## 2. Source verification and immutable build

The last source-changing commit passed:

- 924 pytest, zero failures and zero skips;
- PostgreSQL migrations 0001–0004 with `pending=[]`;
- legacy runner 13/13;
- Python compile, 32 JavaScript syntax checks and 73 JSON parses;
- four C# Release builds with zero warnings and zero errors;
- CSP, static, Markdown, redaction and secret scans.

No application or Connector source changed during the final configuration,
cutover and documentation work, so the full regression and four C# builds were
not repeated.

From clean source `8917ffad`, `tools/release_candidate.py --server-only`
produced Server `0.9.0-dev.13`:

- archive SHA-256
  `B52299A2460BFACBCE1484086658967375E9FED65498B6030F96AF3025D8F693`;
- manifest SHA-256
  `4BC7AD4267E032203CF7B62C371953E9C5B055ADDDC911D2B5E07B7B7457E6A0`;
- exact files: 325;
- migrations: four;
- development P-256 signature and external fingerprint verification: PASS;
- tag: `stratforge-server-v0.9.0-dev.13`.

This is not represented as Authenticode-signed or as a formally stable-channel
artifact.

## 3. Access boundary and topology

- Linux control used `stratforge@ssh-canary.stratforges.com` through Cloudflare
  Access with strict host-key pinning and the existing Stage 9 key.
- `sudo` is scoped to the Docker container. The accessible boundary contains
  `/home/stratforge/production_data`; it does not expose the outer Docker
  daemon, host systemd or host reboot control.
- Windows VM control used the container network target
  `Ninja@192.168.122.33:22` through local tunnel `127.0.0.1:12222`.
- RDP remained private through `127.0.0.1:13389 → 192.168.122.33:3389`.
  No RDP/VNC/SSH management port was published to the Internet.
- The main Windows computer was never rebooted or powered off.

## 4. Off-host backup and isolated restore

Cloudflare R2 access was verified as private and bucket-scoped. A restic v2
repository with ID
`d3a9a38adf1799b895499b6433394e9353de66394bd137d44e3b419e65464115`
was initialized only after the empty/uninitialized state was confirmed.

Snapshot
`839d2519c209d0bd5490f9221a20e6d8ec17f8faf536fd507abce38ce47a59b8`
contains a coordinated PostgreSQL dump, artifacts and manifest. Full data check
passed. An isolated restore matched migrations `[1,2,3,4]`, database counts,
artifact hashes and a byte-identical manifest. The temporary restore database
and directories were removed only after PASS; same-host backups remain.

Observed restore RTO was 4.004 seconds. Target RPO is 24 hours. Supervisor runs
the 03:30 UTC daily schedule with retention 14 daily, 8 weekly, 12 monthly and
3 yearly. The final check found scheduled snapshot
`e6bec09d6e242008c964ac47e24c3bfc642e735e931b04322207f929cde8acb5`
created at `2026-08-01T03:30:23Z`, proving that the schedule executes rather
than merely existing in configuration.

## 5. Linux release, application rollback and services

The immutable release was deployed atomically as:

- current: `0.9.0-dev.13-8917ffad`;
- previous: `0.9.0-dev.12-847f69f3`.

A real application drill switched `dev.13 → dev.12 → dev.13`, verified public
health in both directions and restored exact dev.13 bytes. After the separate
`api-app` and persistent Telegram processes were added, that drill was repeated
against the current topology. Both `app` and `canary` returned ready dev.12 and
then ready dev.13; `api`, `api-app`, worker, operations and Telegram were all
covered. PostgreSQL remained healthy, migrations were `[1,2,3,4]`,
`pending=[]`, and temporary Stage 10 databases/directories were absent.

The current-topology backup and executable rollback pair are at
`/home/stratforge/production_data/backups/application-rollback-current-topology-20260801T175303Z`.
The rollback/restore controller SHA-256 is
`6A74E050DA666081D25981711A4057D1FC1D9E53025DABC9BCC6355BA2AC7324`;
evidence SHA-256 is
`8618E8682B4284E4B56917ED5512C85A6EB9810A3C847BDACDF4DAA754C1DF28`.

Two preparation attempts failed closed before live change because the service
user could not traverse the root-only backup directory to read candidate
preflight env files. The candidates were instead copied to protected temporary
runtime paths and both dev.12 preflights passed 14 checks. During the successful
drill, the first driver-level evidence write raced Supervisor's sequential
startup; public per-version probes and an independent stabilized postcheck
closed the evidence without repeating the live transition.

The final supervisor inventory had all nine required processes RUNNING:
PostgreSQL, canary API, Production app API, worker, operations, artifact
server, cloudflared, off-host backup scheduler and Telegram.

Canary and Production use separate API processes so the strict canonical-host
security contract is preserved:

- canary API: `127.0.0.1:18765`, instance
  `stratforge-linux-canary-01`, origin `canary.stratforges.com`;
- app API: `127.0.0.1:18767`, instance
  `stratforge-linux-production-01`, origin `app.stratforges.com`.

They intentionally share the same immutable Linux release and Production
PostgreSQL/state. The app API deployment backup is
`/home/stratforge/production_data/backups/pre-app-api-20260801T123842Z`.

## 6. Windows Connector and NinjaTrader market data

The final installed Connector is `0.4.2-dev.6`; Server `dev.13` is a separate
version namespace. Verified values:

- installation `33265A4F57D24DFE`;
- manifest SHA-256
  `21796A45682991AF3A84A03D25E972428ABF5F389AB7E2F84150F4D9231157E7`;
- installed DLL SHA-256
  `7ED279BA6FDA1B00734BA74B973D6F38D801C2B8F5C6E0B4CA4AA33AF2CA2990`;
- server origin `https://canary.stratforges.com`;
- channel `canary`; update policy `safe_restart`.

Following repair/pairing and the final NinjaTrader restart:

- signed hello accepted; final recorded hello `2026-08-01T17:22:35Z`;
- heartbeat current; final consolidated heartbeat `2026-08-01T17:26:55Z`;
- Connector status `online`, NinjaTrader `8.1.8.1`;
- telemetry contained four accounts, zero positions, zero strategies and zero
  active strategies;
- capabilities included `accounts_read`, `paper_commands`, `telemetry`;
- the user confirmed DEMO, no positions/orders and disabled strategies;
- no current 401, 403, pairing, signature, timestamp, TLS, DNS, origin,
  channel, stale-client or clock-skew error was present.

The required market-data path
`Windows NinjaTrader → Connector → Linux Production` delivered two ordered
batches, 128 items and one 64-bar `MES 09-26` / `1m` snapshot. Payload SHA-256
is `8DBDDC5B51AC62AD0A6F3E43F3E0FAFD67709BACA7CFBE6BF15EE602F16C11EF`.
The Saturday probe correctly classified Friday data as stale; stale/offline
execution denial remained fail-closed. Direct TopstepX, Databento and DXFeed
are optional deferred failover providers and were not treated as blockers.

## 7. Telegram and Gemini

Provider secrets were read only from protected stores and never emitted,
hashed into reports or placed in commands/Git/history.

- Telegram identity and a silent delivery acknowledgement passed.
- The webhook now points to `app.stratforges.com`.
- A dedicated Production app runner uses the app canonical environment.
- Supervisor was backed up before persistence changed. The Telegram program now
  has `autostart=true`, `autorestart=true`, `startretries=10`.
- A controlled restart returned one and only one consumer; public readiness
  stayed HTTP 200. Backup:
  `/home/stratforge/production_data/backups/pre-telegram-persistence-20260801T172402Z`.
- Gemini model listing and a minimal inference passed. Budget was reserved
  before provider traffic, durable usage was recorded, and an oversized
  request was denied.

## 8. Cloudflare cutover and rollback drill

Linux ingress was backed up and extended for both `canary` and `app` without
weakening Host/Origin validation. The final cloudflared configuration SHA-256
is `6EB3075FC9170A26837C2A99D10106F2A9208EC4F649AB50C2FE4069D8B1BD98`.
Routing used the empty config
`C:\SF10\cloudflared-route-empty.yml`, SHA-256
`4B015F24D75D77390963147E2698DC824E0C05ACEB93FAFA9019C70A03B56949`,
so a local default config could not substitute the wrong tunnel.

The real public route sequence was:

1. initial Development `0.9.0-dev.10`;
2. promotion to Linux Production `0.9.0-dev.13` at
   `2026-08-01T17:12:23Z`;
3. rollback to Development at `2026-08-01T17:13:57Z`;
4. final promotion to Linux Production at `2026-08-01T17:14:34Z`.

Final public probes:

- `https://app.stratforges.com`: live 200, ready 200, Production dev.13, instance
  `stratforge-linux-production-01`, HTML UI 200;
- `https://canary.stratforges.com`: live 200, ready 200, Production dev.13, instance
  `stratforge-linux-canary-01`, HTML UI 200;
- `/api/diagnostics`: 404;
- `/metrics`: 404;
- live trading and real payments: false.

## 9. Post-cutover Development independence

Before the drill, a rollback directory and hash-verified restore script were
created at
`C:\SF10\rollback\development-independence-20260801T173547Z`.

The local supervisor, backend listener and its Development tunnel were stopped.
While `127.0.0.1:8765` was closed, three consecutive checks of both public
hostnames remained on their Linux Production instances. The exact Development
supervisor command restored localhost dev.10, and hashes of
`app/backend_supervisor.py` and `app/server.py` were unchanged. This proves
that stopping local Development does not stop Production and that Production
does not depend on the local checkout/database.

## 10. Final evidence and unresolved external items

Primary sanitized evidence:

- final Linux Production state:
  `/home/stratforge/production_data/runtime/stage10-evidence/final-production-state-20260801T173338Z.json`,
  SHA-256
  `2D84656FFB8E3FDD378E094E7D413E048415802F6669453DC137F7D4BB629D16`;
- public DNS promotion/rollback/promotion:
  `C:\SF10\evidence\stage10-production-dns-cutover-drill-20260801T171208Z.json`,
  SHA-256
  `2D204CA0F6AD3CB4D85DB77B2A3BBD679A4A639B68E5E71E274BD720F7F4E10F`;
- Telegram persistence:
  `/home/stratforge/production_data/runtime/stage10-evidence/telegram-persistence-20260801T172514Z.json`,
  SHA-256
  `9E0323E5A09E94C1155B9DC835E2878675CD53C7C248AB2841E5AAA7079E5447`;
- post-cutover independence:
  `C:\SF10\evidence\stage10-postcutover-development-independence-20260801T173547Z.json`,
  SHA-256
  `F7552F72908142F5254AD8BB49E095FE75C9C04540708D646F2F3993611F4C02`.
- current-topology application rollback:
  `C:\SF10\evidence\application-rollback-current-topology-20260801T175303Z.json`,
  SHA-256
  `8618E8682B4284E4B56917ED5512C85A6EB9810A3C847BDACDF4DAA754C1DF28`.

No P0/P1 remains open. These external items are deferred rather than falsely
marked PASS:

1. protected Production P-256 and trusted Authenticode signing material;
2. literal container restart and host reboot through outer-host administration;
3. independent non-owner beta acceptance/sign-off.

No live trading, real payments, real order, main-PC reboot, destructive Git
operation or secret disclosure occurred.
