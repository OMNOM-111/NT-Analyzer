# Clean closeout — release accepted

Дата проверки: `2026-08-23T02:27:02Z`.

## Current release identity

| Environment | Version | Git SHA | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- |
| LOCAL | `0.10.0-beta.29` | `4d15f1d2250e2c52bde02b902d88ec7aad043543` | clean checkout build `dev-0.10.0-beta.29-4d15f1d2250e` | implementation/load/responsive baseline PASS |
| Canary | `0.10.0-beta.29` | `4d15f1d2250e2c52bde02b902d88ec7aad043543` | `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379` | live/ready + authenticated owner UI/Documents/charts PASS |
| Production | `0.10.0-beta.29` | `4d15f1d2250e2c52bde02b902d88ec7aad043543` | `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379` | live/ready + owner UI/charts/responsive PASS |

Immutable identity:

- candidate `rc_a7c6c0afb95d410f92474614efeb1b35`;
- artifact `art_ccaadc3a536e4272809d32073f072918`;
- build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`;
- archive SHA256 `882FF3520DDD43BF65925F3DFA5AA95DA56107336DA98EFDC64146A81981195B`;
- runtime/manifest SHA256 `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`;
- active Canary/Production release directory
  `/home/stratforge/production_data/releases/0.10.0-beta.29-4d15f1d2250e`;
- rollback: Canary and Production `0.10.0-beta.28-36600dba3d73`.

## Acceptance evidence

- [PR #142](https://github.com/OMNOM-111/NT-Analyzer/pull/142) mandatory CI:
  all five required jobs green; merge SHA `4d15f1d2250e`.
- Targeted market/chart/Operations/responsive regression: `251 passed`.
- Full regression: `1924 passed`, `32 skipped`, `0 failed`.
- `compileall`, 32 JavaScript syntax checks, CSP/secret/Markdown/link scans,
  external-context validation and `git diff --check`: PASS.
- Expected skips: 31 real-PostgreSQL-DSN integration checks and 1 Windows
  bash-syntax check.
- Development load: 12 pages / 24 charts across three isolated profiles;
  `browser_ws 14→2`, `logical 22→4`, `wire=2`, `signalr=1`, direct/loginKey=0.
- Responsive matrix: 84/84 page/viewport checks from 2560×1440 to 360×800;
  real mobile pointer journeys and whole-document overflow checks PASS.
- Canary large layout: 36 charts; second client, Documents and MNQ 5m/15m
  smoke PASS. Production two-client MES/MNQ smoke produced matching closes and
  colored live markers; mobile/tablet whole-document overflow was zero.
- Canary deployment `dep_de061542f96641e1a10b7bb4456c2df0` and Production
  deployment `dep_8716b7cf463f4cf8af092ba6a4e5bdae`:
  external PASS, identity/readiness/signature verified,
  `same_immutable_artifact=true`, no rebuild and no pending migration.

## Product boundary

TopstepX remains the primary independent read-only history/realtime chart
source. NinjaTrader remains the execution/backtest/runtime truth and was kept
OFF during chart acceptance; it was not restarted. Physical enrollment of a
new Connector device remains a separate hardware acceptance, not a software
release blocker.

Google OAuth, transactional e-mail and legal publication remain their existing
`EXTERNAL BLOCKED` / `IN DEVELOPMENT` boundaries. Legal documents remain DRAFT.

Canonical operational evidence:
[2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Удалён устаревший beta.20 handoff; зафиксированы фактические beta.27 Canary, beta.26 Production и исполнимый beta.28 closeout.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Зафиксирован реальный blocker canary_passed→approved_for_production в authoritative promotion gate; artifact 2790fb43 не продвигался, Production остался beta.26.
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Final beta.28 artifact принят в Canary и без пересборки продвинут в Production; точная identity, rollback slots, tests и chart evidence записаны в current handoff.
2026-08-23T02:27:02Z | GPT-5.5 через Codex по запросу owner | Заменён beta.28 handoff фактическим beta.29 closeout: PR/CI, exact artifact, Canary/Production deploy IDs, fan-out, responsive и owner browser evidence.
-->
