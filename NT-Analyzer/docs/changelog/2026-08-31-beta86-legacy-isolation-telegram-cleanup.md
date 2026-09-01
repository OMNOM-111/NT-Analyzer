# beta.86 - Legacy Isolation + Telegram Bot Cleanup

Release summary: Текущий StratForge полностью отделён от legacy UI и Telegram Mini App, при этом исторические отчёты сохранены в отдельном read-only Legacy Viewer, а текущие Telegram login, confirmations и notifications остаются рабочими.
Release PRs: #254, #255, #256
Affected subsystems: Aurora UI, Legacy Viewer, Telegram bot URL flow, Release Center, release governance
Release impact: Удалён вход в legacy UI и Mini App из текущего продукта; добавлен понятный обязательный release/change record без изменения market data, Connector или trading execution.

## Что вошло

- PR #254: legacy UI и исторические данные изолированы в localhost-only read-only Legacy Viewer; текущие legacy routes fail closed.
- PR #255: Telegram `/start` открывает StratForge обычной URL-кнопкой без возврата Mini App/WebApp binding.
- PR #256: Release Center показывает название, описание, PR, SHA, build/artifact, этап, проверки, длительность и identity DEV/Canary/Production; Production блокируется без полного release/change record.

## Сохранено

- Current Telegram auth, login confirmation, NinjaTrader confirmation, bot notifications and callbacks.
- Historical reports, audit/history and the temporary Legacy Viewer launcher.
- Existing market data, Connector, trading execution and release artifact invariants.

## Release sequence

`final main -> mandatory CI -> one signed immutable artifact -> Canary acceptance -> same artifact without rebuild -> Production`

Operational candidate, build, artifact hashes, Canary result and Production result are appended to the canonical closeout after the live release completes.

## Operational closeout - 2026-09-01

Released. Development, Canary and Production all run the same immutable
artifact; Production was promoted without a rebuild.

| Field | Value |
| --- | --- |
| Final main SHA | `22ed7097b4ac9e863304197e118b1d3ce5109e8a` |
| Version | `0.10.0-beta.86` |
| Candidate | `rc_049d14ab6af640758a69b00432bb6e3d` |
| Artifact ID | `art_e627d14a2dbb49fdaf98a0cc9847e8c2` |
| Build ID | `sf-0.10.0-beta.86-22ed7097b4ac-20260901T005018Z` |
| Archive SHA256 | `8052B7A5FC36E1519A7AFCD3B60E5A221F744DE768585D765145245911BABE7D` |
| Manifest SHA256 | `0E95CF8B879AE6D66D11F70BAD566E2658180AE432CD8EAEEE12CC50B4CFBCA4` |
| Signature | verified |
| Final state | `production_live` - stage DONE, verification_result PASS |

Gates: PR #256 CI 5/5 on `b0f0773f`; final main CI PASS on `22ed7097`;
`pre_release_check` PASS; release static scan PASS; External GPT Context
validator PASS; `git diff --check` clean.

Canary acceptance (owner attested): artifact identity, signature, `/live` 200,
`/ready` 200, `/api/health` 401, auth, current Aurora surfaces, `/ui/legacy/`
410, Mini App and remote/tunnel 410, classic assets 404, current Telegram
endpoints alive at 401, market data role `consumer`, Connector `ok`, Release
Center record visible.

Production verification: `/live` 200 and `/ready` 200 (both 404 before this
release, so the PR #254 aliases prove the new artifact is serving), build id and
Git SHA on `/live` match the artifact exactly, Aurora surfaces 200, retired
surfaces 410, classic assets 404, Telegram and market-data endpoints alive and
auth-gated. Canary and Production report the same artifact SHA256.

Telegram bot `@StratForgeAI_bot`: the `web_app` chat menu button was retired
after Production was confirmed on this release. Menu button is now
`{"type": "commands"}` at bot level and in the owner chat; `/start` and `/login`
are registered; webhook healthy with no pending updates or errors. `/start`
answers with a plain inline URL button to `https://app.stratforges.com/` and
never a Web App button.

Legacy Viewer and historical reports remain in place; no destructive Legacy
decommission was performed.
