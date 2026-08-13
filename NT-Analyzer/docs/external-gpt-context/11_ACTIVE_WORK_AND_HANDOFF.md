# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-13T04:59:15Z
- Verified against Git SHA: cad53f682e413db86bc3a77e57f8942baf4d4bc3
- Scope: Dynamic current work, blockers, next actions and dangerous zones
- Status: DONE
- Current Production version/build/artifact when known: operational release evidence says Production is on `0.10.0-beta.1`, artifact git `6b6dc4589407855526cf6cc345376d64cf95200e`, build `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256 `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`, archive SHA256 `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730`, `previous=0.10.0-beta.1-795db0c1`.

## Snapshot

| Field | Value |
| --- | --- |
| Current Git SHA | `cad53f682e413db86bc3a77e57f8942baf4d4bc3` |
| Current branch | `main` |
| Public version | `0.10.0-beta.1` |
| Current operational artifact git SHA | `6b6dc4589407855526cf6cc345376d64cf95200e` |
| Current operational build ID | `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z` |
| DEV identity | `http://127.0.0.1:8765/ui/`, `[DEV]`, app identity `6b6dc458`, `dirty=false`, `deployment_environment=development`, `config_profile=local-development`, local owner session |
| CANARY identity | `https://canary.stratforges.com`, `[CANARY]`, `instance=stratforge-canary-01`, `config_profile=production-canary`, DB `stratforge_canary`, topology `api / worker-canary / operations-canary`, same artifact as Production, Telegram `PARTIAL` |
| PRODUCTION identity | `https://app.stratforges.com`, `[BETA]`, `instance=stratforge-linux-production-01`, `config_profile=production-primary`, DB `stratforge_production`, Supervisor `api-app / worker / operations / telegram`, previous `0.10.0-beta.1-795db0c1` |
| Active PR / release candidate | not evidenced inside the repository at this snapshot |

## Last clearly completed milestone

- Phase 12 live closeout recorded the current operational baseline: signed
  artifact `6b6dc458`, Canary acceptance, same release directory promoted to
  Production, readiness hang fixed.
- External GPT Context Pack and owner export mechanism are now merged on `main`.
- ADR set `0001` through `0008` plus migrations `0005` through `0011` remain the
  repository-contract foundation under that live snapshot.

## Current work visible in the repo

- Working tree already contains in-progress governance/documents UI/backend edits.
- Working tree already contains in-progress desktop/chart-related edits and an
  untracked `tests/test_desktop_instrument_fallback.py`.
- Future Production/Canary release closeouts must refresh the canonical
  operational snapshot and the three dynamic Context Pack files together.

## Current blockers

- Canary Telegram bot is still not separately provisioned.
- Google OAuth remains externally blocked in Production.
- Transactional email auth remains externally blocked in Production.
- Fresh-browser authenticated Production TopstepX/chart smoke remains partial
  because it still requires a real owner Telegram tap; no session may be fabricated.
- Production Connector acceptance still depends on a real Windows VM path.
- Licensed-provider market-data parity and broader load acceptance remain open.
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
4. Final policy for separate Canary bot identity and live acceptance evidence retention.
5. Legal entity/placeholders and counsel review timing for publication.

## Next actions

1. Keep [02_CURRENT_SYSTEM_STATE.md](02_CURRENT_SYSTEM_STATE.md), [04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md) and this file in sync with every accepted Canary/Production closeout.
2. Refresh [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) or its successor on the next accepted deployment.
3. Close the unrelated current governance/documents/desktop edits in their own scoped change.
4. Provision a separate Canary Telegram bot or keep its absence explicitly documented as PARTIAL.
5. Complete trusted-device / step-up UX for critical release and personal-NinjaTrader actions.
6. Finish real Windows Connector acceptance evidence.
7. Finish licensed-provider and higher-load market-data acceptance.
8. Continue hardening the Admin Panel and Release Center user-facing shell around existing backend permissions.

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