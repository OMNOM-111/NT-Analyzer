# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-13T02:25:57Z
- Verified against Git SHA: c4711ae3f876966f6bedcba8fc3b4ad9c309c836
- Scope: Dynamic current work, blockers, next actions and dangerous zones
- Status: DONE
- Current Production version/build/artifact when known: public version is `0.10.0-beta.1`; the currently deployed Production artifact/build/slot is not provable from repository evidence alone.

## Snapshot

| Field | Value |
| --- | --- |
| Current Git SHA | `c4711ae3f876966f6bedcba8fc3b4ad9c309c836` |
| Current branch | `main` |
| Public version | `0.10.0-beta.1` |
| DEV identity | local `NT-Analyzer/` checkout, loopback development, dirty allowed |
| CANARY identity | `https://canary.stratforges.com`, separate deployment environment, current live build unknown from repo |
| PRODUCTION identity | `https://app.stratforges.com`, public app, current live build unknown from repo |
| Active PR / release candidate | not evidenced inside the repository at this snapshot |

## Last clearly completed milestone

- ADR set `0001` through `0008` exists and defines the target environment,
  identity, admin, release and document boundaries.
- Schema migrations `0005` through `0011` already exist for UUID identity,
  trusted devices, step-up, release center and documents.
- Public version metadata and top-level README were refreshed to current
  TopstepX-first / NinjaTrader-authority language on `0.10.0-beta.1`.

## Current work visible in the repo

- Working tree already contains in-progress governance/documents UI/backend edits.
- Working tree already contains in-progress desktop/chart-related edits and an
  untracked `tests/test_desktop_instrument_fallback.py`.
- This task adds a canonical external-context surface and validator; it should
  stay scoped to docs/static validation rather than runtime deployment.

## Current blockers

- Current Canary / Production deployed artifact and slot are not proven by repo
  evidence.
- Public live-trading release remains blocked by owner/regulatory/release gates.
- Production Connector acceptance still depends on a real Windows VM path.
- Licensed-provider market-data parity and broader load acceptance remain open.
- Trusted-device / step-up coverage is not yet fully uniform for every critical
  admin/release/personal-NT action.

## EXTERNAL BLOCKED

- public live broker automation;
- current live deployment proof for Canary/Production from repo alone;
- fully published legal package;
- any assumption that external chart feeds can authorize execution.

## Owner decisions needed

1. When to treat `beta` Production as ready for broader public exposure.
2. When and how to close the live-trading regulatory/release gate.
3. Which transactional email provider and operational policy to use for email auth.
4. Final policy for separate Canary bot identity and live acceptance evidence retention.
5. Legal entity/placeholders and counsel review timing for publication.

## Next actions

1. Keep [02_CURRENT_SYSTEM_STATE.md](02_CURRENT_SYSTEM_STATE.md) and this file updated after every architecture-level task.
2. Land this pack and its validator without mixing it into runtime deployment work.
3. Close the unrelated current governance/documents/desktop edits in their own scoped change.
4. Capture current Canary / Production artifact IDs in repo-visible release evidence when available.
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