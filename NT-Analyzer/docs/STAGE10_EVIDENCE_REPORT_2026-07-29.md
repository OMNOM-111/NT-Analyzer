# Stage 10 evidence report — final cutover update 2026-08-01

## Verdict

**PRODUCTION CUTOVER COMPLETE — LIVE/READY, NO OPEN P0/P1.**

`https://app.stratforges.com` now serves Linux Production Server
`0.9.0-dev.13` from instance `stratforge-linux-production-01`.
`canary.stratforges.com` remains the independent canary hostname on instance
`stratforge-linux-canary-01`. Local Windows Development remains
`development/0.9.0-dev.10` on `127.0.0.1:8765` and was stopped and restored
during a post-cutover isolation drill without affecting either Linux endpoint.

The deployed artifact is operationally healthy and has no open P0/P1 defect.
Formal stable signing, an outer-host reboot proof, and non-owner beta sign-off
remain external governance evidence; therefore this report does not relabel the
development-signed `dev.13` bytes as a formally signed stable release.

## Final gate matrix

| Gate | State | Sanitized evidence |
|---|---|---|
| Owner checkout preservation | PASS | Stage 10 Git work used only `C:\SF10\development`; the owner checkout remains on its original branch/commit with an empty index and non-empty owner/runtime state |
| Canonical Development history | PASS | `codex/stage10-development`; source commit `8917ffad9e14d9899f8532cbec86ed0f0f742035` plus Stage 10 evidence-only commits |
| Production source reference | PASS | `codex/stage10-production` fast-forwarded atomically from `2bf50278` to exact deployed source `8917ffad`; rollback ref retains the old value |
| Source regression | PASS | 924 pytest; migrations 0001–0004; legacy 13/13; Python, JavaScript, JSON, C#, CSP, redaction and secret gates PASS; source did not change during cutover, so this was not repeated |
| Linux release | PASS | current `0.9.0-dev.13-8917ffad`; previous `0.9.0-dev.12-847f69f3`; `pending=[]`; both runtime preflights PASS |
| Application rollback | PASS | real `dev.13 → dev.12 → dev.13`; exact bytes restored |
| Off-host backup/restore | PASS | encrypted Cloudflare R2 repository, `restic check --read-data`, isolated PostgreSQL/artifact restore, matching migrations/counts/hashes, temporary restore targets removed |
| Scheduled backup | PASS | supervisor scheduler RUNNING; newest R2 snapshot `e6bec09d…` at `2026-08-01T03:30:23Z`, 14.055 hours old at final probe; RPO 24 h |
| Linux services | PASS | PostgreSQL, canary API, Production app API, worker, operations, artifact server, cloudflared, off-host scheduler and Telegram all RUNNING |
| Public Production | PASS | `app` live/ready HTTP 200, TLS validated, HTML UI HTTP 200, diagnostics and metrics remain 404 |
| Canary | PASS | live/ready HTTP 200 and unchanged throughout promotion/rollback/promotion |
| DNS promotion/rollback | PASS | real `Development dev.10 → Linux dev.13 → Development dev.10 → Linux dev.13` route drill; final Linux route active |
| Telegram | PASS | identity, silent delivery acknowledgement, webhook on `app`, one consumer, controlled restart and supervisor persistence PASS |
| Gemini AI | PASS | model probe, minimal inference, pre-provider budget reservation, durable usage accounting and oversized-budget denial PASS |
| Windows Connector | PASS | `0.4.2-dev.6`, signed hello, current heartbeat, telemetry and paper-only capability on Linux Production |
| Required market data | PASS | NinjaTrader → Connector → Linux received 2 batches / 128 items for `MES 09-26` `1m`; stale/offline fail-closed behavior previously passed |
| Development/Production isolation | PASS | local listener and local tunnel were stopped; three consecutive `app` and `canary` probes remained Linux Production; Development restored with protected source hashes unchanged |
| Safety | PASS | test auth/bypass absent; live trading `false`; real payments `false`; DEMO confirmed, zero positions and zero active strategies at acceptance |
| Container-internal persistence | PASS | supervisor autostart/autorestart configured; Telegram controlled restart returned exactly one consumer; API/cloudflared service restarts retained readiness |
| Outer container/host reboot proof | DEFERRED_EXTERNAL | granted SSH boundary is inside the container and exposes neither Docker control nor host systemd/reboot authority |
| Production signing | DEFERRED_EXTERNAL | development P-256 manifest signature verifies; protected Production P-256 material and trusted Authenticode certificate/timestamp evidence are not provisioned |
| External beta | DEFERRED_EXTERNAL | no consenting non-owner beta user or sign-off was supplied; automated/owner Production acceptance passed |
| TopstepX / Databento / DXFeed | OPTIONAL_DEFERRED | failover providers only; direct TopstepX auth is not a Stage 10 gate and was not attempted from Linux |

## Production topology and exact releases

| Item | Exact value |
|---|---|
| Production URL | `https://app.stratforges.com` |
| Canary URL | `https://canary.stratforges.com` |
| Local Development | `http://127.0.0.1:8765`, Server `0.9.0-dev.10` |
| Linux current | `/home/stratforge/production_data/releases/0.9.0-dev.13-8917ffad` |
| Linux previous | `/home/stratforge/production_data/releases/0.9.0-dev.12-847f69f3` |
| Server source | `8917ffad9e14d9899f8532cbec86ed0f0f742035` |
| Server tag | `stratforge-server-v0.9.0-dev.13` |
| Connector | `0.4.2-dev.6`; no Connector Git tag was created |
| Connector installation | `33265A4F57D24DFE` |
| Production app API | loopback `127.0.0.1:18767`, canonical host `app.stratforges.com` |
| Canary API | loopback `127.0.0.1:18765`, canonical host `canary.stratforges.com` |
| Linux tunnel | `1f6f3ab3-f181-47bd-8cd9-d088bd89e2d1` |
| Development tunnel | `d0439b3c-bce5-48eb-810a-1b84f5770874` |

The two Linux API processes intentionally share the same immutable release and
Production PostgreSQL/state, but retain separate canonical-host and instance
contracts. Windows Development has its own code checkout, environment, state,
database and Connector target and does not participate in the Production
request path.

## Connector, telemetry and market-data evidence

After the final NinjaTrader restart, Linux accepted a signed hello at
`2026-08-01T17:22:35Z` and a heartbeat at `2026-08-01T17:26:55Z`.
The final inventory reported Connector status `online`, NinjaTrader `8.1.8.1`,
capabilities `accounts_read`, `paper_commands`, and `telemetry`, four account
records, zero positions, zero strategies, and zero active strategies. The user
also visually confirmed the DEMO connection and disabled strategies.

NinjaTrader supplied two ordered batches, 128 total items and a 64-bar snapshot
for exact contract `MES 09-26`, timeframe `1m`, source sequences `1..2`.
The snapshot is stale only because the final probe ran on Saturday after the
Friday session; the execution path remains fail-closed for stale/offline data.
TopstepX, Databento and DXFeed are optional future failover providers.

## Cutover chronology

- `2026-08-01T17:12:23Z`: `app` promoted from Development dev.10 to Linux
  Production dev.13.
- `2026-08-01T17:13:57Z`: DNS rollback restored Development dev.10 and was
  externally verified.
- `2026-08-01T17:14:34Z`: final promotion restored Linux Production dev.13.
- `2026-08-01T17:25Z`: Telegram controlled restart completed with one consumer
  and public readiness HTTP 200.
- `2026-08-01T17:33:38Z`: consolidated Linux Production evidence PASS.
- `2026-08-01T17:35:47Z`: post-cutover Development stop/restore drill PASS.

No main-Windows reboot, live trading, real payment, real order, secret exposure,
destructive Git command, or owner-checkout Git mutation occurred.

## Cryptographic evidence

| Object | SHA-256 |
|---|---|
| Server dev.13 archive | `B52299A2460BFACBCE1484086658967375E9FED65498B6030F96AF3025D8F693` |
| Server dev.13 manifest | `4BC7AD4267E032203CF7B62C371953E9C5B055ADDDC911D2B5E07B7B7457E6A0` |
| Connector dev.6 manifest | `21796A45682991AF3A84A03D25E972428ABF5F389AB7E2F84150F4D9231157E7` |
| Installed Connector DLL | `7ED279BA6FDA1B00734BA74B973D6F38D801C2B8F5C6E0B4CA4AA33AF2CA2990` |
| Connector market-data payload | `8DBDDC5B51AC62AD0A6F3E43F3E0FAFD67709BACA7CFBE6BF15EE602F16C11EF` |
| Off-host backup/restore evidence | `0AC768154598C0206B719CD27E2ED5A37421F3D1E6A29C2CE10E0D00C12BA855` |
| Off-host schedule evidence | `CF29E657C923FD662BB02865797D5B37478E6B492A36488C3C3CDF3B093D78C6` |
| Application rollback drill | `F4D0A1D2D09780B5F31F2085A8C7507144C2EB41AA362C7EAC19ABCEEB1BF133` |
| Parallel Production app API evidence | `117E8429F407BAD171EB3C356A822549D4FD4E143E9186783162B5079A869469` |
| DNS promotion/rollback/promotion evidence | `2D204CA0F6AD3CB4D85DB77B2A3BBD679A4A639B68E5E71E274BD720F7F4E10F` |
| Telegram persistence evidence | `9E0323E5A09E94C1155B9DC835E2878675CD53C7C248AB2841E5AAA7079E5447` |
| Final Linux Production state | `2D84656FFB8E3FDD378E094E7D413E048415802F6669453DC137F7D4BB629D16` |
| Post-cutover Development independence | `F7552F72908142F5254AD8BB49E095FE75C9C04540708D646F2F3993611F4C02` |
| Development drill backup manifest | `C51E4967EEC85225B791F379CB8E7AEFCE5B7A64E70A2F6F7CFBC2B66529B13A` |
| Development restore script | `DABB2A9EDA112BB70BE29318E794817C50E9854A2933CF6A33F944F73B48AC93` |
| Linux cloudflared config | `6EB3075FC9170A26837C2A99D10106F2A9208EC4F649AB50C2FE4069D8B1BD98` |
| Linux supervisor config | `197CCBB5FA8468EAEEA7A66218CBD8F111D1AB292AA95DFC4AD9E9F91440C601` |
| Production app environment | `B9AC213D51D8E4D25920994C1DA32409E658E54E63492B9912ECC9215FA7DC08` |
| Cloudflare routing-only config | `4B015F24D75D77390963147E2698DC824E0C05ACEB93FAFA9019C70A03B56949` |
| Full pytest log | `DDC7BFD3CE3EEF8842A11C66C39F5EEE373F294242104051D5C78DCEFC8C3B39` |
| C# Release build log | `D33604A56958F31EE008313E54957980D4DFC563FD0EFCB58D8B557688E24AA7` |

Sanitized final evidence is retained locally under `C:\SF10\evidence` and on
Linux under
`/home/stratforge/production_data/runtime/stage10-evidence`. Credentials,
private keys, pairing codes, bearer tokens and passwords are absent.

## Remaining external evidence

There are no open P0/P1 defects. Three non-runtime items require capabilities
outside the granted boundary:

1. Provision protected Production P-256 and trusted Authenticode signing
   material before the next formally stable Windows/Server release.
2. Grant outer Docker/host administration for a literal container-restart and
   host-reboot persistence proof.
3. Supply a consenting non-owner beta user for independent acceptance and
   sign-off.

These items do not change the observed state: Linux Production is currently
live and ready, local Development is independent, rollback is verified, and
all trading/payment safety switches remain disabled.
