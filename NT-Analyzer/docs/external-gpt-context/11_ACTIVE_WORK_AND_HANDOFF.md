# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-13T09:49:37Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Dynamic current work, blockers, next actions and dangerous zones
- Status: DONE
- Current Production version/build/artifact when known: Production is still on `0.10.0-beta.1`, artifact git `6b6dc4589407855526cf6cc345376d64cf95200e`, build `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256 `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`, archive SHA256 `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730`, `previous=0.10.0-beta.1-795db0c1`. Canary runs accepted git `7ebda6faf2e7c64d4a707a41062b29857882181a`; Production promotion is pending a separate owner answer.

## Snapshot

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` |
| Current branch | `codex/final-acceptance-hardening-20260812` |
| Public version | `0.10.0-beta.1` |
| Current operational artifact git SHA | `6b6dc4589407855526cf6cc345376d64cf95200e` |
| Current operational build ID | `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z` |
| DEV identity | `http://127.0.0.1:8765/ui/`, `[DEV]`, app identity `7ebda6fa`, `dirty=false`, `deployment_environment=development`, isolated local owner session |
| CANARY identity | `https://canary.stratforges.com`, `[CANARY]`, DB `stratforge_canary`, topology `api / worker-canary / operations-canary / telegram-canary`; owner-login hotfix uses existing Telegram bot shared-webhook routing, pending live redeploy |
| PRODUCTION identity | `https://app.stratforges.com`, `[BETA]`, `instance=stratforge-linux-production-01`, `config_profile=production-primary`, DB `stratforge_production`, Supervisor `api-app / worker / operations / telegram`, previous `0.10.0-beta.1-795db0c1` |
| Active PR / release candidate | PR #30; candidate `rc_3be66a74f97d4c62b491ac071bd981ed`, artifact `art_4ef7bbcc95c34fd7a80b184a441e6bc1`, state `canary_passed`; Production approval not created |

## Last clearly completed milestone

- Final hardening built and accepted the production-signed `7ebda6fa` artifact
  on Canary through the in-app Release Center. Real blue-green and
  rollback→re-promote passed; Production stayed on `6b6dc458`.
- Clean-SHA DEV visual acceptance ran MNQ/MES for `619.899 s` across independent
  in-app and Chrome clients with `0` grey/OFF/non-live states. The accepted TopstepX architecture
  was preserved.
- Canonical evidence is
  [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md).

## Current work visible in the repo

- PR #30 contains scoped final-acceptance hardening, Release Center real Canary
  execution, chart-marker regression protection and documentation/UI closeout.
- Canary is accepted with explicitly recorded external blockers. No Production
  approval, schedule or deployment exists for this candidate.
- Any later Production closeout must promote the exact recorded artifact
  without rebuild and refresh the canonical operational snapshot.

## Current blockers

- Canary owner login hotfix is implemented in code but still needs live Canary redeploy from a clean signed artifact; this workspace's release executor currently reports `dry_run`.
- Google OAuth remains externally blocked in Production.
- Transactional email auth remains externally blocked in Production.
- Fresh-browser authenticated Canary and Production TopstepX/chart smoke remain
  externally blocked because they require real owner authentication; no session
  may be fabricated.
- Production Connector acceptance still depends on a real Windows VM path.
- DEV chart/API fanout reached 100 clients and Canary safe HTTP acceptance
  reached 100 clients. Authenticated server-side licensed-provider parity and
  full failover remain external.
- Trusted-device / step-up coverage is not yet fully uniform for every critical
  admin/release/personal-NT action.

## EXTERNAL BLOCKED

- Google OAuth in Production until external provider configuration is accepted;
- transactional email auth in Production until external provider configuration is accepted;
- fully published legal package;
- any assumption that external chart feeds can authorize execution.

## Owner decisions needed

1. When to treat `beta` Production as ready for broader public exposure.
2. When and how to close the live-trading regulatory/release gate.
3. Which transactional email provider and operational policy to use for email auth.
4. Final policy for long-term separate Canary bot identity versus existing-bot shared-webhook routing, and live acceptance evidence retention.
5. Legal entity/placeholders and counsel review timing for publication.

## Next actions

1. Keep [02_CURRENT_SYSTEM_STATE.md](02_CURRENT_SYSTEM_STATE.md), [04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md) and this file in sync with every accepted Canary/Production closeout.
2. Await the owner's explicit `Да / Нет` before any Production action for the
   exact `7ebda6fa` artifact. Do not rebuild between Canary and Production.
3. Deploy the Canary owner-login hotfix artifact and verify real owner login;
  a separate Canary bot is optional policy, not required for this fix.
4. Complete real authenticated Canary/Production chart and Windows Connector
   acceptance when the required external sessions/hardware are available.
5. Keep Google OAuth, transactional email and legal publication accurately
   blocked until their external requirements are supplied and accepted.

## Dangerous zones

- `app/runtime_env.py`
- `app/release_center.py`
- `app/connector_protocol.py`
- `app/market_data_failover.py`
- `app/market_data_live_adapters.py`
- `app/security_devices.py`
- migrations `0005_identity_uuid.sql` through `0011_document_specifications.sql`
- governance source/render pipeline under `data/governance/*` and `docs/governance/*`

Do not change these casually without a reproducible defect, explicit test scope
and release-impact reasoning.
