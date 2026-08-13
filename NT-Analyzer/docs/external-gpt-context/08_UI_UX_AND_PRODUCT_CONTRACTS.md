# 08. UI, UX and Product Contracts

- Context Pack document: 08_UI_UX_AND_PRODUCT_CONTRACTS.md
- Last verified UTC: 2026-08-13T02:25:57Z
- Verified against Git SHA: c4711ae3f876966f6bedcba8fc3b4ad9c309c836
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
| Release Center | owner / developer / admin | `PARTIAL` | candidate/build/check/deploy/promote/rollback workflow |

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

## Admin and Release Center visibility

- Admin capability exists before the UI is considered complete.
- Release Center should be treated as a structured owner/admin workflow, not as
  a public user feature.
- Current repo evidence shows UI wiring and backend contracts, not a proof of a
  specific live deployment record.

## Canonical evidence

- [../architecture/UI_API_MAP.md](../architecture/UI_API_MAP.md)
- [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md)
- `app/static/aurora/assets/ui.js`
- `app/static/aurora/assets/api.js`
- `app/static/aurora/assets/pages/desktop.js`
- `app/static/aurora/assets/pages/documents.js`