# Clean closeout — release accepted

Дата проверки: `2026-08-21T03:50:00Z`.

## Current release identity

| Environment | Version | Git SHA | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- |
| LOCAL | `0.10.0-beta.28` | `36600dba3d739601660768db98b429b0f752ad1a` | clean checkout build `dev-0.10.0-beta.28-36600dba3d73` | implementation/test baseline PASS |
| Canary | `0.10.0-beta.28` | `36600dba3d739601660768db98b429b0f752ad1a` | `864F7D16C03999EF2119EA13C73FBD05DD7FF160E49ADD8EA6D02E91555D916C` | live/ready + owner UI/Documents/charts PASS |
| Production | `0.10.0-beta.28` | `36600dba3d739601660768db98b429b0f752ad1a` | `864F7D16C03999EF2119EA13C73FBD05DD7FF160E49ADD8EA6D02E91555D916C` | live/ready + public UI PASS; isolated owner login recheck follows physical Telegram confirmation |

Immutable identity:

- candidate `rc_ceba7e31340d476faa79413f2c1d99d4`;
- artifact `art_3537e6c88e554b0094554c75e403ce31`;
- build `sf-0.10.0-beta.28-36600dba3d73-20260821T031309Z`;
- archive SHA256 `A5E906D27B49118AF4E7155B4F08217E433EF03CC598BF6BFB60DBF087005D8A`;
- runtime/manifest SHA256 `864F7D16C03999EF2119EA13C73FBD05DD7FF160E49ADD8EA6D02E91555D916C`;
- active Canary/Production release directory
  `/home/stratforge/production_data/releases/0.10.0-beta.28-36600dba3d73`;
- rollback: Canary `0.10.0-beta.28-2790fb43992d`, Production
  `0.10.0-beta.26-3353e3836306`.

## Acceptance evidence

- PR #140 mandatory CI: all five required jobs green.
- Targeted release/pipeline regression: `125 passed`.
- Full regression: `1915 passed`, `32 skipped`, `0 failed`.
- Legacy release runner: `13/13 suites passed`.
- `compileall`, 32 JavaScript syntax checks, CSP/secret/Markdown/link scans,
  external-context validation and `git diff --check`: PASS.
- Expected skips: 31 real-PostgreSQL-DSN integration checks and 1 Windows
  bash-syntax check.
- Canary MES 5m + MNQ 5m: 610 seconds, 13 samples / 26 row checks,
  zero visual/OFF violations; raw TopstepX lastPrice, last bar close and
  rendered green/red marker matched in every row.
- Large layout: 36 charts, zero overlap; second isolated browser loaded the
  exact build; all inspected browser consoles had zero errors.
- Production deployment `dep_030ba44c26bd4c3db40dc253adab5c42`:
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
[2026-08-20-final-product-acceptance-beta28.md](../changelog/2026-08-20-final-product-acceptance-beta28.md).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Удалён устаревший beta.20 handoff; зафиксированы фактические beta.27 Canary, beta.26 Production и исполнимый beta.28 closeout.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Зафиксирован реальный blocker canary_passed→approved_for_production в authoritative promotion gate; artifact 2790fb43 не продвигался, Production остался beta.26.
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Final beta.28 artifact принят в Canary и без пересборки продвинут в Production; точная identity, rollback slots, tests и chart evidence записаны в current handoff.
-->
