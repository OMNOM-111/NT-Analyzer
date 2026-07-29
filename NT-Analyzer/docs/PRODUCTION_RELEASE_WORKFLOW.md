# StratForge immutable release workflow

This is the canonical update path for the two supported environments:

- `codex/stage10-development` — local Windows Development;
- `codex/stage10-production` — exact code currently deployed on Linux.

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

## 4. Promote without rebuilding

Promotion is permitted only when the candidate archive, manifest, source
revision, and SHA-256 values are byte-for-byte identical to the canary evidence.
Point the stable Connector catalog at the same archive and change the Server
runtime release channel to `stable`. The main Cloudflare hostname is switched
only after the owner writes the exact authorization phrase required by the
Stage 10 runbook.

Keep `canary.stratforges.com` as the internal release lane. Keep local
Development bound to localhost and independent of the Linux database, tunnel,
credentials, and artifact store.

## 5. Roll back

For an edge failure, restore the previous Cloudflare route first. For an
application failure, stop API/worker/operations, atomically restore the saved
`current` and `previous` links plus active version configuration, then start and
verify the previous release. Never mutate an immutable release directory.

If a schema change is not backward compatible, restore the pre-release backup
into a new isolated database/artifact target and verify it before switching;
never destructively downgrade the live database in place.
