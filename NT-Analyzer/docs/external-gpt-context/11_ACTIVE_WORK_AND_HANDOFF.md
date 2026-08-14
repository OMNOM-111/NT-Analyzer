# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-14T17:12:00Z
- Verified against Git SHA: 77e8645f1725d20545992efdeabafdf2f3d0e684
- Scope: Dynamic current work, blockers, next actions and dangerous zones
- Status: DONE
- Current Production version/build/artifact when known: LOCAL/CANARY/PRODUCTION git `77e8645f1725d20545992efdeabafdf2f3d0e684`, build `sf-0.10.0-beta.1-77e8645f1725-20260814T164341Z`, public artifact SHA256 `1F0C95E48447632CB97EF88A85E38354D6A71AC32C41285600DACA182A8748C6`, archive SHA256 `DBC79FC6834C82AC383240ED03C1A505C1367AEB2DE0D02DBDD17BBCAE4F2980`. `canary-current` = `current` = `.../0.10.0-beta.1-77e8645f1725`; previous is `1fae1f39`. All eight app `/proc` cwd match. Owner Documents/Release Center 200 and TopstepX LIVE on Canary and Production.

## Snapshot

| Field | Value |
| --- | --- |
| Current Git SHA | `77e8645f1725d20545992efdeabafdf2f3d0e684` |
| Live public API Git SHA | `77e8645f1725d20545992efdeabafdf2f3d0e684` |
| Public version | `0.10.0-beta.1` |
| Live operational build ID | `sf-0.10.0-beta.1-77e8645f1725-20260814T164341Z` |
| Live artifact SHA256 | `1F0C95E48447632CB97EF88A85E38354D6A71AC32C41285600DACA182A8748C6` |
| DEV identity | `http://127.0.0.1:8765/ui/`, `[DEV]`, git `77e8645f`, `build_id=dev-0.10.0-beta.1-77e8645f1725` |
| CANARY identity | `https://canary.stratforges.com`, `[CANARY]`, DB `stratforge_canary`, topology `api / worker-canary / operations-canary / telegram-canary`; `/proc` cwd `77e8645f` |
| PRODUCTION identity | `https://app.stratforges.com`, `[BETA]`, `instance=stratforge-linux-production-01`, DB `stratforge_production`, Supervisor `api-app / worker / operations / telegram`; same `/proc` cwd `77e8645f` |
| Follow-up in repository | Documents/Charts server defects closed on this live artifact |

## Last clearly completed milestone

- PR #37 merged; CI green; one signed artifact from merge SHA `77e8645f`
  promoted Canary then Production without rebuild.
  [../changelog/2026-08-14-live-release-77e8645f-documents-charts.md](../changelog/2026-08-14-live-release-77e8645f-documents-charts.md).
- Owner Documents/Release Center are HTTP 200 (no `Unknown repository`).
- Server charts serve TopstepX history + realtime when NinjaTrader is down.
- Historical `1fae1f39`, Canary `7ebda6fa` and hang-fix `6b6dc458` remain in
  changelog as prior closeouts.

## Current work visible in the repo

- Documents/Charts server defects from live `1fae1f39` are closed on `77e8645f`.
- Host overlays outside the signed zip: TopstepX credentials + remote
  authorization flags in Canary/Production env files; `websockets==16.0` in
  the release `.venv`. `requirements.txt` now names `websockets` for the next
  build.
- `STRATFORGE_CANARY_INTERNAL_ORIGIN=http://127.0.0.1:18765` remains on
  Production telegram.

## Current blockers

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

1. Keep Google OAuth, transactional email and legal publication accurately
   blocked until their external requirements are supplied and accepted.
2. Next signed build must install `websockets` from `requirements.txt` into
   the release `.venv` instead of relying on host overlay drift.

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
2026-08-14T17:12:00Z | Grok 4.6 через Cursor по запросу owner | STAGE CLOSED: live 77e8645f LOCAL/CANARY/PRODUCTION; Documents+TopstepX PASS.
2026-08-14T06:45:00Z | Grok 4.6 через Cursor по запросу owner | Handoff: live process identity 1fae1f39; 0f2a90ea previous slot; Documents/Charts follow-up not deployed.
-->
