# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-14T06:20:00Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Dynamic current work, blockers, next actions and dangerous zones
- Status: PARTIAL
- Current Production version/build/artifact when known: Canary and Production `/live` `/ready` `/runtime/env` plus active `canary-current`/`current` and `/proc` cwd for all eight app processes report git `1fae1f3966dc53294b73772be47992d844575115`, build `sf-0.10.0-beta.1-1fae1f3966dc-20260814T052203Z`, artifact SHA256 `08265412DECF4D04962A14A0D17208BB7E67031F09AF62FB525634749B6B449B`. Previous slot is `0f2a90ea`. Repository Documents/Charts follow-up is not that live artifact. Local DEV was not listening.

## Snapshot

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` |
| Live public API Git SHA | `1fae1f3966dc53294b73772be47992d844575115` |
| Public version | `0.10.0-beta.1` |
| Live operational build ID | `sf-0.10.0-beta.1-1fae1f3966dc-20260814T052203Z` |
| Live artifact SHA256 | `08265412DECF4D04962A14A0D17208BB7E67031F09AF62FB525634749B6B449B` |
| DEV identity | `http://127.0.0.1:8765/ui/`, `[DEV]`; local process was not listening in this session |
| CANARY identity | `https://canary.stratforges.com`, `[CANARY]`, DB `stratforge_canary`, topology `api / worker-canary / operations-canary / telegram-canary`; active slot and `/proc` cwd `1fae1f39` |
| PRODUCTION identity | `https://app.stratforges.com`, `[BETA]`, `instance=stratforge-linux-production-01`, DB `stratforge_production`, Supervisor `api-app / worker / operations / telegram`; same active slot and `/proc` cwd `1fae1f39` |
| Follow-up in repository | Documents/Release Center allowlist + server TopstepX chart fallback; not yet the live artifact |

## Last clearly completed milestone

- Public HTTP identity on Canary and Production agrees on `1fae1f39` / same
  artifact SHA256. Host `/proc` cwd for all eight app processes matches that
  active slot. `0f2a90ea` is previous-slot only.
- Historical Canary acceptance `7ebda6fa` and hang-fix Production `6b6dc458`
  remain in changelog as prior closeouts.

## Current work visible in the repo

- Production live owner session found two code defects on `1fae1f39`:
  `Unknown repository` for `releases`/`doc_specs`, and Charts returning
  `workspace_runtime_not_connected` instead of TopstepX.
- Repository now lets chart bars through `runtime_stub` and uses TopstepX →
  Connector → other live provider → OFFLINE in server environments.
- Optional `STRATFORGE_CANARY_INTERNAL_ORIGIN` is already set on live
  Production telegram (`http://127.0.0.1:18765`).
- Unauthenticated `/ui/` and `/ui/desktop.html` shells match between Canary
  and Production. Authenticated page sweep was not completed here.

## Current blockers

- This change set is not live until a new signed artifact is built and
  deployed DEV → CANARY → PRODUCTION.
- Local DEV `http://127.0.0.1:8765` was not listening in this session.
- Google OAuth remains externally blocked in Production.
- Transactional email auth remains externally blocked in Production.
- Production Connector acceptance still depends on a real Windows VM path.

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

1. Build/sign the Documents/Charts follow-up from a clean commit and deploy
   DEV → CANARY → PRODUCTION without rebuild; re-prove `/proc` cwd on the new SHA.
2. Re-test Production Documents, Release Center and TopstepX history/realtime
   with a real owner session.
3. Keep Google OAuth, transactional email and legal publication accurately
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

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T06:45:00Z | Grok 4.6 через Cursor по запросу owner | Handoff: live process identity 1fae1f39; 0f2a90ea previous slot; Documents/Charts follow-up not deployed.
-->
