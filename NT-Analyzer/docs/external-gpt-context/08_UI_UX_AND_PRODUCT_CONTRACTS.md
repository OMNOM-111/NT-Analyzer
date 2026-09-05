# 08. UI, UX and Product Contracts

- Context Pack document: 08_UI_UX_AND_PRODUCT_CONTRACTS.md
- Last verified UTC: 2026-09-05T04:22:06Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 34deb827e4ed0e6a29d5693650b575e86e0f33d6 (clean beta.96 runtime; rating/rejected-response follow-up under verification)
- Active Local 8765: clean `34deb827e4ed0e6a29d5693650b575e86e0f33d6`, build `dev-0.10.0-beta.96-34deb827e4ed`, original owner data, Preview=false
- Unified Local accepted base: beta.96, open PR #280; no Canary/Production promotion
- Scope: Major UI areas, visibility rules and important UX contracts
- Status: IN DEVELOPMENT

The Agent World rows below describe the integrated Development delta, not a
completed live browser acceptance. The initial Local switch is complete, while
the newer UI/model/domain code still requires clean activation and owner review.
The shared deployment anchor above is unchanged; Production was not rechecked.

## Major product areas

| Area | Audience | Status | Contract summary |
| --- | --- | --- | --- |
| Overview / Dashboard | ordinary user + owner | `DONE` | health, performance, coverage, reports, news |
| Backtesting | ordinary user + owner | `DONE` | jobs, reports, catalog, instrument/profile controls |
| Trading / Runtime | owner + allowed operators | `PARTIAL` | paper/demo/playback control, diagnostics, account history, safe confirmations |
| Finance / Performance | ordinary user + owner | `DONE` | P&L, trades, accounting overlays, filtered analysis |
| Strategies | ordinary user + owner | `PARTIAL` | profiles, lifecycle, cleanup, archive, portfolio cells |
| AI Lab | ordinary user + owner | `PARTIAL` | orchestration, runs, cloud-agent settings, compile/backtest loop |
| AI Agents / API Keys | owner | `BETA` in Local | current owner-only provider registry; using premium models does not grant access to provider settings |
| AI Center | controlled Preview or explicitly opted-in Development workspace with existing authenticated permissions | `IN DEVELOPMENT` | Exactly three primary tabs: Overview/Work/Agents; Task Inspector and Persona, Models, Decisions/Court, Memory, Experiments, Projects, routines/calendar, System and SF Social tools are drawers on that page; real domain tools are unavailable in Preview |
| SF Social / SF Chat | permitted users + owner | `BETA` in Unified Local | social network and human/AI messenger are integrated; technical `community*` compatibility remains |
| News | ordinary user + owner | `DONE` | calendar events, live headlines, provider status |
| Telegram / auth entry | ordinary user + owner | `PARTIAL` | login, profile, pairing, notifications, session revoke |
| Device confirmation / Security | ordinary user + owner | `BETA` in Unified Local | two-minute pending window, permanent/session choice, narrow fresh first-device proof, OTP for later clients, success and separate Devices / My sessions / Login history |
| Legacy Viewer | owner local reference | `AVAILABLE` | separate localhost-only read-only classic viewer over an isolated data snapshot |
| Documents | ordinary user + owner | `PARTIAL` | governance/public docs with actor/reason aware saves and revisions |
| Environment Switcher | owner / developer / admin | `PARTIAL` | separate-origin navigation by capability, not an in-place backend swap |
| Release Center | owner / explicitly permitted operator | `BETA` | real clean-candidate/build/sign/Canary/check/rollback workflow; Production promotion remains a separate owner gate |
| Responsive shell and drawers | all audiences | `DONE` | desktop/tablet/mobile reflow preserves important data and controls without whole-page horizontal overflow; chart geometry stacks below the compact breakpoint |

## Visibility contracts

- Ordinary users should not see admin-only modules just because routes exist.
- Owner/developer/admin surfaces still require server-side capability checks.
- Production does not rely on mock data.
- Documents UI must preserve public/internal metadata separation.
- Social rail/header now says SF Social; messenger remains SF Chat. Technical
  community routes and stores are unchanged.
- AI Center uses the existing Aurora shell and supplied Agent World composition.
  Its source labels distinguish Preview synthetic benchmarks from actual
  NinjaTrader reports and Desktop snapshots. Real tasks show queued/running/
  verified or failure/review states; execution success does not mean profit.
  A small real Desktop image and canonical report link appear beside the task.
  NEW is honest insufficient model-quality evidence, not a generated rating.
  The owner's collage remains the composition reference. No extra pages or
  empty top-level tabs are introduced; existing Desktop and Backtesting remain
  canonical destinations for their respective full artifacts.
  Owner visual acceptance is pending; no general feature cutover is claimed.
- Model connections in the new drawer belong to the authenticated user. They
  do not expose the owner-only legacy provider registry. Guarded owner bindings
  reuse existing caps; ordinary users supply their own connection and allowance.
  The ordinary-test-account wizard and separate OpenRouter key (`openrouter/free`) entry are a pending
  acceptance path, not seeded credentials or a reason to share owner secrets.
- Task Inspector distinguishes the model plan from actual application work.
  A valid plan remains waiting for the canonical NT job or Desktop receipt;
  trace/history links open original evidence and the existing SF Chat, not a
  second messenger. A cancel request is not a confirmed cancelled source job.
- The follow-up Persona form explicitly selects application role separately from
  name/model. Exact linked model/application work counts once, with the original
  execution retained. Legacy performer history is not merged into model quality.
  Small positive model costs retain up to eight decimals instead of showing zero.
  Cabinet offers a Local confirmed human a personal container without NT pairing;
  AI access still requires exact server workspace opt-in and existing permissions.
- Ratings use independent observed checks and distinct real inputs, with failures,
  available cost and latency shown honestly. n < 3 stays NEW; comparisons use
  identical input. Synthetic Preview fixtures and old manual jobs never become
  real quality evidence, and observed ratings do not change Router weights.
- Court displays a sealed packet and three isolated advisory votes under a
  2-of-3 rule. It never executes a verdict. Memory promotion/sharing is explicit,
  purpose/TTL/source-bound and revocable; shared retrieval does not expose the
  private artifact API. Routines/calendar accept manual follow-ups only, with
  automation visibly OFF.
- The SF Social drawer first prepares a verified public snapshot, then requires
  explicit confirmation of the exact hash/revision and permanent publication.
  Only allowlisted results/verdicts/hashes go to the existing Community store;
  prompts, raw answers, private Memory, judge rationale and credentials are absent.
  Neither page opening nor task completion creates a post.
- All flags default OFF. Exact server-side Development workspace opt-in enables
  read/UI/tasks/evaluation/memory/consensus/Court/social; Router shadow and
  Execution V2 stay OFF. Preview has only its separate four fixture flags.
  UI capabilities/actions reflect fresh server admission, never grant it.
  Post-trial history may stay readable while new calls/tasks/posts are denied.

## Important UX rules

1. Environment and release maturity are labeled separately: `DEV`, `CANARY`,
   `BETA` and stable Production are not interchangeable.
2. Environment Switcher opens the target origin in a new tab and should not
   carry browser storage/credentials across environments.
3. Telegram Mini App and mirrored UI are `DEPRECATED`; current navigation and
   transport contain no Mini App entry. Telegram login/bot/notifications remain.
4. Save/update actions in documents should record actor and reason.
5. The first product explanation should start from product purpose and current
   capabilities, not from internal owner or amendment mechanics.
6. A fresh TopstepX quote heartbeat keeps the right-side price marker live even
   when the numeric price has not changed; candle direction and marker direction
   remain independent.
7. A pending login must take over the auth surface before the application shell
   starts. Product data is not rendered behind the confirmation card.
8. The two user choices are permanent Client trust and current-Session-only
   access. UI text must not promise a 24-hour window.
9. OTP entry uses six single-character numeric fields with keyboard, paste,
   Backspace and Enter support; resend availability and both deadlines come
   from server state.
10. Security UI may nest Clients under a Machine only for a proven binding.
    Remote, AI-hosted and ordinary browsers without signed identity are shown
    neutrally as standalone Clients, without invented hardware names.

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
- Documents UI uses a mission-led CHARTER, official versioned legal documents and compact
  red/green semantic revisions with details collapsed.
- Aurora is the only current UI. `/ui/legacy/*` returns HTTP 410; Legacy Viewer
  is not a rollback or current-product fallback.

## Canonical evidence

- [../architecture/UI_API_MAP.md](../architecture/UI_API_MAP.md)
- [Current Agent World acceptance](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
- [Integrated Local ADR](../adr/0012-agent-world-integrated-local.md)
- [Integrated Local verification ledger](../changelog/2026-09-05-agent-world-integrated-local.md)
- [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md)
- [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md)
- [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md)
- [Device Confirmation Development record](../changelog/2026-09-02-device-confirmation-trusted-access.md)
- `app/static/aurora/assets/ui.js`
- `app/static/aurora/assets/api.js`
- `app/static/aurora/assets/pages/desktop.js`
- `app/static/aurora/assets/pages/documents.js`
