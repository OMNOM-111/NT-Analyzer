# 08. UI, UX and Product Contracts

- Context Pack document: 08_UI_UX_AND_PRODUCT_CONTRACTS.md
- Last verified UTC: 2026-08-23T02:27:02Z
- Verified against Git SHA: 1279645e48e32000978364b38fb20d3dcd303843
- Scope: Major UI areas, visibility rules and important UX contracts
- Status: DONE

## Major product areas

| Area | Audience | Status | Contract summary |
| --- | --- | --- | --- |
| Overview / Dashboard | ordinary user + owner | `DONE` | health, performance, coverage, reports, news |
| Backtesting | ordinary user + owner | `DONE` | jobs, reports, catalog, instrument/profile controls |
| Trading / Runtime | owner + allowed operators | `PARTIAL` | paper/demo/playback control, diagnostics, account history, safe confirmations |
| Finance / Performance | ordinary user + owner | `DONE` | P&L, trades, accounting overlays, filtered analysis |
| Strategies | ordinary user + owner | `PARTIAL` | profiles, lifecycle, cleanup, archive, portfolio cells |
| AI Lab | ordinary user + owner | `PARTIAL` | orchestration, runs, cloud-agent settings, compile/backtest loop |
| AI Agents / API Keys | owner + allowed operators | `PARTIAL` | local provider configuration, role routes, budgets, masked secrets only |
| News | ordinary user + owner | `DONE` | calendar events, live headlines, provider status |
| Telegram / auth entry | ordinary user + owner | `PARTIAL` | login, profile, pairing, notifications, session revoke |
| Documents | ordinary user + owner | `PARTIAL` | governance/public docs with actor/reason aware saves and revisions |
| Environment Switcher | owner / developer / admin | `PARTIAL` | separate-origin navigation by capability, not an in-place backend swap |
| Release Center | owner / explicitly permitted operator | `BETA` | real clean-candidate/build/sign/Canary/check/rollback workflow; Production promotion remains a separate owner gate |
| Responsive shell and drawers | all audiences | `DONE` | desktop/tablet/mobile reflow preserves important data and controls without whole-page horizontal overflow; chart geometry stacks below the compact breakpoint |

## Visibility contracts

- Ordinary users should not see admin-only modules just because routes exist.
- Owner/developer/admin surfaces still require server-side capability checks.
- Production does not rely on mock data.
- Documents UI must preserve public/internal metadata separation.

## Important UX rules

1. Environment and release maturity are labeled separately: `DEV`, `CANARY`,
   `BETA` and stable Production are not interchangeable.
2. Environment Switcher opens the target origin in a new tab and should not
   carry browser storage/credentials across environments.
3. Mini App / Telegram does not imply live-trading permission.
4. Save/update actions in documents should record actor and reason.
5. The first product explanation should start from product purpose and current
   capabilities, not from internal owner or amendment mechanics.
6. A fresh TopstepX quote heartbeat keeps the right-side price marker live even
   when the numeric price has not changed; candle direction and marker direction
   remain independent.

## Admin and Release Center visibility

- Admin capability is enforced server-side; UI visibility is only the secondary
  presentation layer.
- Release Center should be treated as a structured owner/admin workflow, not as
  a public user feature.
- The owner-facing workflow is live through beta.29 candidate
  `rc_a7c6c0afb95d410f92474614efeb1b35`: authenticated Canary acceptance and
  same-artifact Production promotion both passed.
- Functional responsiveness passed 84/84 page/viewport checks from 2560×1440
  to 360×800. Authenticated Production mobile/tablet smoke had zero
  whole-document overflow; two-client MES/MNQ and MNQ 15m charts retained
  colored live markers. Broader visual taste/design acceptance remains a
  separate owner decision, not a functional blocker.
- Documents UI uses a mission-led CHARTER, legal DRAFT badges and compact
  red/green semantic revisions with details collapsed.

## Canonical evidence

- [../architecture/UI_API_MAP.md](../architecture/UI_API_MAP.md)
- [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md)
- [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md)
- [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md)
- `app/static/aurora/assets/ui.js`
- `app/static/aurora/assets/api.js`
- `app/static/aurora/assets/pages/desktop.js`
- `app/static/aurora/assets/pages/documents.js`
