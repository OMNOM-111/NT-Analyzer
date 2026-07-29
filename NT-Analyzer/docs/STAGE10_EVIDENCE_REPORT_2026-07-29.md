# Stage 10 evidence report — 2026-07-29

## Verdict

**PRE-CUTOVER BLOCKED — NOT STABLE.**

The local code histories are converged into a canonical Development branch,
the owner worktree is preserved, Development isolation is proven, the final
source regression passes, and a reproducible immutable Development Server
release exists. Production cannot be declared ready because off-host backup,
credentials, host persistence tests, Production signing, external beta, and
the explicit cutover authorization are not available.

## Gate matrix

| Gate | State | Evidence |
|---|---|---|
| Owner checkout preservation | PASS | Original `56f6da02`, 12 tracked + 1 untracked unchanged; verified backup set exists |
| Canonical Development history | PASS | merge `b0539a09`; release-source commit `8917ffad` |
| Separate Production reference | PASS | `codex/stage10-production` remains at Stage 9 closeout `2bf50278` |
| Local Development isolation | PASS | localhost `127.0.0.1:18780`, dedicated data root, UI 200, no Production DB env |
| Source regression | PASS | 924 pytest; migrations 0001–0004; legacy 13/13; Python/JS/JSON/C#/static gates PASS |
| Immutable Development build | PASS | dev.13 archive/manifest/signature verified and tagged |
| Existing Linux canary | PASS | dev.12 current, dev.11 previous, public health alive, safety flags false |
| Deploy dev.13 to canary | BLOCKED | mandatory independent off-host backup target is absent |
| Production credentials | BLOCKED | Telegram, AI, and market-data credential names are unset |
| Off-host backup/PITR | BLOCKED | Restic installed, but no repository config; backups share the data LV |
| Host persistence/reboot | BLOCKED_EXTERNAL | no Docker socket or host systemd access from the container |
| Production signing | BLOCKED | no protected P-256 key, Authenticode certificate/thumbprint, or `signtool` |
| External beta | BLOCKED | no consenting beta-user execution or sign-off supplied |
| Main Cloudflare cutover | BLOCKED | prerequisite gates open and exact authorization phrase not supplied |

## Six external blockers

| Blocker | Classification | Exact missing capability |
|---|---|---|
| Production signing | NEEDS USER ACTION | externally protected P-256 key, Authenticode certificate/private key, thumbprint, `signtool`, timestamp policy |
| Telegram / AI / market data | NEEDS USER ACTION | protected Production credentials for credentialed probes |
| Independent backup | NEEDS USER ACTION | S3/B2/R2/restic repository outside the server's physical failure domain |
| Container restart / host reboot | BLOCKED_EXTERNAL | host or Docker control outside the granted container |
| External beta | NEEDS USER ACTION | one or two consenting non-owner users and final sign-off |
| Main cutover | NEEDS USER ACTION | all prior gates plus the exact phrase `ПЕРЕКЛЮЧАЙ PRODUCTION` |

## Cryptographic and rollback evidence

Pre-convergence backup root:
`C:\SF10\pre-convergence-20260729T211708Z`.

| Object | SHA-256 |
|---|---|
| Git bundle | `AD73CD74DB9CF8510A0DE9BBFF62120AFB116E8FC9ABE9BBDA5EA9AD3DCA062B` |
| HEAD archive | `D7855E05C5F663DA079ADC16007F6D9209BC2BA0EBE67743B43D71E4E4F40006` |
| Exact checkout archive | `D72281F37405650B8D451061E0D2879D3D29E8143223FCF2C8FD655F7BB988D0` |
| Binary working-tree diff | `7BCFD4BFAE0B7C2653D31A36E9C1FDF60672DFB1A2DECE5F2092A10B2E4BAD9A` |
| Untracked snapshot | `31A25912DB3CE7F0E518EBD1B9C5C70E769EED5033C522A64FDF6095AD58A988` |
| Tested source patch | `7C55CD05B0AB55C7C9432054C975D799AD0DEA9FA0FA610AE1ACBB0C8BB28398` |
| Final regression PostgreSQL dump | `e3f72cb6804cf4bc874494315cd82bb5b8c109908bcea276e1fb9c2b5300dfbf` |
| dev.13 Server archive | `B52299A2460BFACBCE1484086658967375E9FED65498B6030F96AF3025D8F693` |
| dev.13 Server manifest | `4BC7AD4267E032203CF7B62C371953E9C5B055ADDDC911D2B5E07B7B7457E6A0` |

Final gate evidence is retained under
`C:\SF10\evidence\final-regression-final-20260729`. The pytest log SHA-256 is
`DDC7BFD3CE3EEF8842A11C66C39F5EEE373F294242104051D5C78DCEFC8C3B39`;
the C# build log SHA-256 is
`D33604A56958F31EE008313E54957980D4DFC563FD0EFCB58D8B557688E24AA7`;
the static-scan log SHA-256 is
`40EAA4D8A33F480B86140A3A34C9FFD986BD49D85A2246DA746B65E6605584D2`.

## Safety conclusion

The system remains safe at the pause point: the public main domain was not
changed, the known-good Linux canary was not replaced, the local owner backend
was not stopped, and live trading and real payments remain disabled. The next
authorized action is to attach an independent encrypted backup repository;
only then may the fresh backup, isolated restore, dev.13 canary deployment, and
rollback drill proceed.
