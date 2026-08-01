# StratForge immutable release workflow

This is the canonical update path for the two supported environments:

- `codex/stage10-development` — local Windows Development;
- `codex/stage10-production` — exact source currently deployed on Linux.

Current pinned state after the Stage 10 cutover:

- Development branch contains the tested source plus evidence-only closeout
  commits;
- Production branch and Server tag point to deployed source
  `8917ffad9e14d9899f8532cbec86ed0f0f742035`;
- Linux `current=0.9.0-dev.13-8917ffad` and
  `previous=0.9.0-dev.12-847f69f3`;
- `app.stratforges.com` and `canary.stratforges.com` are Linux-hosted;
- local Development remains `127.0.0.1:8765` and does not serve Production.

Do not develop on the Production branch and do not run Production from the
local Windows data root. A release promotion changes references to an existing
artifact; it never rebuilds that version.

## 1. Save a Development change

Work only in the Development checkout. Review and commit explicit paths; never
use `git add -A` in a checkout containing owner runtime files.

```powershell
git status --short
git add -- <explicit paths>
git commit -m "Describe the completed change"
```

Increment `VERSION.json` before the first build for changed Server bytes. Server
and Connector have independent SemVer namespaces. A version becomes burned as
soon as an artifact is built and must not be reused for different bytes.

The exact one-command local Server publication check is:

```powershell
py -3 tools/release_candidate.py --server-only
```

It requires a clean commit, creates one immutable Development artifact, pins it
to `HEAD`, verifies the manifest/signature/file set, and writes a composite
report below `.artifacts/release-candidates/`. It never deploys anything.

If Connector code changed, choose its next unused development SemVer and use:

```powershell
py -3 tools/release_candidate.py --connector-version 0.4.2-dev.N
```

## 2. Create the signed Production candidate

Use a separate clean worktree on `codex/stage10-production`. Merge the accepted
Development commit with an ordinary merge. Set `VERSION.json` to the first
unused stable Server SemVer, `channel=stable`, and
`status=release_candidate`, then commit that release identity.

Production signing material belongs in a user-only local file such as
`$HOME\.stratforge\production-signing.ps1`, never in Git, chat, command
arguments, logs, or evidence. That file sets only these names:

- `STRATFORGE_RELEASE_SIGNING_KEY_PEM`;
- `STRATFORGE_RELEASE_SIGNING_KEY_PASSWORD` when the key is encrypted;
- `STRATFORGE_AUTHENTICODE_THUMBPRINT`;
- `STRATFORGE_AUTHENTICODE_TIMESTAMP_URL`.

After dot-sourcing the protected file, the single build command is:

```powershell
py -3 tools/release_candidate.py --production --connector-version 0.4.2
```

The command refuses dirty source, prerelease Production versions, missing P-256
material, an invalid Authenticode thumbprint, missing `signtool`, or a missing
explicit timestamp endpoint. It signs and verifies all three Windows binaries,
requires a timestamp, pins the Server verification to the external key
fingerprint, and emits exact archive and manifest SHA-256 values.

Create annotated Server and Connector tags on that exact commit only after the
candidate report is PASS. Preserve the report and both archives off-host.

## 3. Deploy the same candidate to canary

Before changing Linux, require a fresh verified PostgreSQL/artifact/config
backup and a verified off-host copy. Upload the Server archive, its checksum,
and the candidate report to a non-release incoming directory. On Linux, obtain
the non-secret public-key fingerprint from the protected Production config and
verify before extraction:

```bash
python tools/verify_server_release.py "$ARCHIVE" \
  --expected-key-fingerprint "$STRATFORGE_RELEASE_SIGNING_KEY_FINGERPRINT"
```

Create a new immutable release directory named from Server SemVer plus the full
source revision. Install dependencies and run preflight before stopping the
current service. Save `current`, `previous`, the active-release file, and the
environment file; then switch them atomically. On any failed migration,
preflight, readiness, or smoke, restore those saved references automatically.

The Connector archive is built with manifest channel `stable`. The canary
catalog may offer that exact archive only to explicit installation IDs. This
allows the identical bytes to be promoted later; do not rebuild a `canary`
variant.

Targeted canary gates are liveness/readiness, schema `pending=[]`, auth and
workspace isolation, owner dashboard, Connector catalog, one paper-only
Connector command, redaction, and live trading/payments both `false`.

The deployment runner must print and retain its exact immutable release ID and
rollback directory. Verify both before promotion:

```powershell
ssh -i "$HOME\.ssh\codex_stratforge_stage9" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes `
  -o "UserKnownHostsFile=$HOME\.ssh\known_hosts_stratforge_stage9" `
  -o 'ProxyCommand="C:\Program Files (x86)\cloudflared\cloudflared.exe" access ssh --hostname %h' `
  stratforge@ssh-canary.stratforges.com `
  "sudo -n sh -c 'readlink -f /home/stratforge/current; readlink -f /home/stratforge/previous'"
```

Run a reviewed release-specific deployment script through strict SSH. The
script must pin the candidate version, source commit, archive SHA, manifest
SHA, expected old `current`/`previous`, backup directory and automatic rollback
checks; do not reuse a one-shot script for different bytes:

```powershell
$DeployScript = 'C:\SF10\deploy-<exact-release-id>.sh'
$Ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
Get-Content -LiteralPath $DeployScript -Raw | & $Ssh `
  -i "$HOME\.ssh\codex_stratforge_stage9" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes `
  -o "UserKnownHostsFile=$HOME\.ssh\known_hosts_stratforge_stage9" `
  -o 'ProxyCommand=C:\PROGRA~2\cloudflared\cloudflared.exe access ssh --hostname %h' `
  stratforge@ssh-canary.stratforges.com 'sudo -n bash -s --'
```

The exact current `dev.13` runner is retained at
`C:\SF10\stage10-deploy-dev13.sh` as evidence only. It is deliberately
one-shot and must not be rerun or generalized by changing a version string.

## 4. Promote without rebuilding

Promotion is permitted only when the candidate archive, manifest, source
revision, and SHA-256 values are byte-for-byte identical to the canary evidence.
For future formal releases, point the stable Connector catalog at those same
bytes and change the Server runtime release channel to `stable` only after
Production signing and beta policy are satisfied. Never relabel or rebuild an
already published version.

The Stage 10 owner explicitly authorized the current dev.13 cutover after the
runtime safety gates passed. That exception does not waive signing requirements
for the next formally stable release.

The Linux tunnel already has validated `app.stratforges.com` ingress. For DNS
routing commands, never allow the local default Cloudflare config to override
the positional tunnel ID. Use an intentionally non-routing config and explicit
IDs:

```powershell
$Cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$RoutingConfig = 'C:\SF10\cloudflared-route-empty.yml'
$LinuxTunnel = '1f6f3ab3-f181-47bd-8cd9-d088bd89e2d1'
& $Cloudflared --config $RoutingConfig tunnel route dns --overwrite-dns `
  $LinuxTunnel app.stratforges.com
```

After DNS propagation, require `app` to report the same stable version and
source revision as canary, TLS/UI/API/auth/catalog/redaction to pass, and both
safety flags to remain false. A failed check restores the edge route first.

For the current release, the externally verified contract is Production
`0.9.0-dev.13`, instance `stratforge-linux-production-01`, ready HTTP 200.

Keep `canary.stratforges.com` as the internal release lane. Keep local
Development bound to localhost and independent of the Linux database, tunnel,
credentials, and artifact store.

## 5. Roll back

For an edge failure, restore the previous Cloudflare route first. For an
application failure, stop API/worker/operations, atomically restore the saved
`current` and `previous` links plus active version configuration, then start and
verify the previous release. Never mutate an immutable release directory.

The current edge rollback command is:

```powershell
$Cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$RoutingConfig = 'C:\SF10\cloudflared-route-empty.yml'
$DevelopmentTunnel = 'd0439b3c-bce5-48eb-810a-1b84f5770874'
& $Cloudflared --config $RoutingConfig tunnel route dns --overwrite-dns `
  $DevelopmentTunnel app.stratforges.com
```

For the application rollback, execute the root-owned `rollback.sh` from the
exact directory printed by the deployment evidence. For current canary dev.13
that verified script is:

```powershell
ssh -i "$HOME\.ssh\codex_stratforge_stage9" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes `
  -o "UserKnownHostsFile=$HOME\.ssh\known_hosts_stratforge_stage9" `
  -o 'ProxyCommand="C:\Program Files (x86)\cloudflared\cloudflared.exe" access ssh --hostname %h' `
  stratforge@ssh-canary.stratforges.com `
  "sudo -n /home/stratforge/production_data/backups/pre-deploy-dev13-20260730T013050Z/rollback.sh"
```

If a schema change is not backward compatible, restore the pre-release backup
into a new isolated database/artifact target and verify it before switching;
never destructively downgrade the live database in place.

## 6. Run local Development independently

Start the local Development supervisor from the owner application directory:

```powershell
Start-Process C:\Python312\python.exe `
  -ArgumentList '-m','app.backend_supervisor','--development-profile','--port','8765','--retry-seconds','10' `
  -WorkingDirectory 'C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer' `
  -WindowStyle Hidden
```

It binds the backend to localhost and runs the separate Development tunnel.
Stopping that supervisor/backend does not stop Linux; this was verified after
cutover while both public `app` and `canary` continued to serve dev.13. Never
point Development at the Production database, data root, secrets, or artifact
store.

## 7. Daily operator commands

Open local Development health and Production health:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health/live
Invoke-RestMethod https://app.stratforges.com/api/health/ready
```

Restore Development if localhost is not listening:

```powershell
Start-Process C:\Python312\python.exe `
  -ArgumentList '-m','app.backend_supervisor','--development-profile','--port','8765','--retry-seconds','10' `
  -WorkingDirectory 'C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer' `
  -WindowStyle Hidden
```

Restore the private RDP tunnel to the NinjaTrader VM:

```powershell
& C:\SF10\Start-StratForge-VM-RDP-Tunnel.ps1
Test-NetConnection 127.0.0.1 -Port 13389
```

Check the current Linux release and Connector-facing services without exposing
credentials:

```powershell
$Ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
& $Ssh -i "$HOME\.ssh\codex_stratforge_stage9" `
  -o BatchMode=yes -o StrictHostKeyChecking=yes `
  -o "UserKnownHostsFile=$HOME\.ssh\known_hosts_stratforge_stage9" `
  -o 'ProxyCommand=C:\PROGRA~2\cloudflared\cloudflared.exe access ssh --hostname %h' `
  stratforge@ssh-canary.stratforges.com `
  "sudo -n supervisorctl -c /home/stratforge/production_data/config/supervisord.conf status; readlink -f /home/stratforge/current; readlink -f /home/stratforge/previous"
```

The normal release loop is therefore:

1. commit a clean Development change;
2. build one immutable candidate and record its hashes;
3. run the release-specific canary deployment and targeted acceptance;
4. route `app` to the Linux tunnel without rebuilding;
5. on failure, route the edge back first, then execute the recorded release
   rollback script.
