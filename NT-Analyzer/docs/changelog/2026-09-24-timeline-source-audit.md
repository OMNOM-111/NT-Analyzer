# StratForge history timeline — source audit and correction

Release title: StratForge product history from verified MVP to current Local work.

Change summary: The standalone root `timeline.html` presents one horizontal
product history from the first Git baseline through the first documented public
Linux baseline and later releases to current Local work. Three environment
snapshots show cumulative major capabilities; milestone cards show only deltas.
Technical identity and evidence live in a right-side drawer.

Affected surfaces: standalone `timeline.html`, root developer instructions and
README, documentation governance and timeline upkeep rule, plus factual
deployment snapshots in External GPT Context Pack 00, 02, 04 and 11. The
application runtime, release artifact selection, market data and Connector
code are unchanged.

Source branch at audit: `feat/shared-model-access`, checkout HEAD
`77eda536f9909afd325ffcd2c89900c17744d4f3`; local remote-tracking branch
`origin/feat/shared-model-access` at `256af9db`. The correction is isolated
on `codex/fact-checked-timeline` from `origin/main` `c3b320e6`; its final commit
and PR are recorded by Git closeout. Verification result for the initial source
audit: nine documented source events grouped into seven chronological product
cards, three environment snapshots, Context Pack validator PASS, and
pre-release bundle gate PASS (629 files, all four checks). The later visual and
UX revision is recorded below. Browser visual QA remains BLOCKED: the browser
refused the local file URL and forbade alternate browser routes for that action.

## Source hierarchy and correction

- Canonical environment names and the historical `staging` compatibility
  profile: `app/runtime_env.py`, `deploy/canary/canary.env.example`,
  `deploy/production/production.env.example`.
- Local server version: `VERSION.json` = `0.10.0-beta.96`. A direct read of
  `http://127.0.0.1:8765/api/runtime/env` on 2026-09-24 returned
  Development, build `dev-0.10.0-beta.96-56945ac68e94`, clean source
  `56945ac68e94cb7ffa031ef2312dec5a9ad80a54`. The running process is
  separate from the checkout HEAD and from the remote-tracking branch.
- The older `02_CURRENT_SYSTEM_STATE.md` beta.87 and
  `04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md` beta.86 headings were stale. The
  ignored local `data/audit/release-center.jsonl` has a later beta.92 sequence:
  signed artifact `art_57db4318cb8745d399d98bccf48de396`, Canary PASS
  `2026-09-02T03:54:35Z`, Production `production_live`
  `2026-09-02T03:57:03Z`. The tracked
  [Connector 0.4.5 closeout](2026-09-02-connector-0.4.5-catalog-snapshot-identity.md)
  independently records the Production server beta.92 build. Both sources
  identify source SHA `9d800770d08e0072ec453c2611e98726e295b2e4`,
  build `sf-0.10.0-beta.92-9d800770d08e-20260902T035324Z`, archive
  SHA256 `FAD094C243B8EDE0B365BE9874466FA9C53C414CB0C9588D4EF4DC0CE62FF315`
  and manifest SHA256 `07A3961277E3879357EE92A8471911FAFA4B57E1B3BF2D046E1BCA41D27A9169`.
  Public Canary and Production endpoints were inaccessible from this tool
  environment on 2026-09-24, so beta.92 is the **last recorded deployment**,
  not a fresh assertion of today's live identity.
- Connector `0.4.5-dev.1+ff6fe049...` was accepted on the Production
  installation at `2026-09-02T06:14:52Z` according to the Connector closeout.
  This component version is not a server version. That record does not prove
  a Canary Connector installation, so the timeline leaves it unconfirmed.

## Original August–September audit events and their evidence

| Date | Event / component | Evidence | Development | Canary | Production |
| --- | --- | --- | --- | --- | --- |
| 2026-08-13 | Server beta.1 artifact `7ebda6fa` acceptance | [Canary closeout](2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) | checked | accepted | that artifact not promoted |
| 2026-08-23 | Server beta.29 artifact `4d15f1d2` | [release closeout](2026-08-22-market-data-responsive-release-beta29.md) | checked | accepted | live |
| 2026-09-01 | Server beta.87 artifact `8f421586` | [release closeout](2026-09-01-beta87-owner-backtest-demo-fix.md) | checked | accepted | live |
| 2026-09-02 03:57 UTC | Server beta.92 artifact `9d800770` | Release Center audit and [Connector closeout](2026-09-02-connector-0.4.5-catalog-snapshot-identity.md) | built | accepted | live |
| 2026-09-02 06:14 UTC | Connector `0.4.5-dev.1` | [Connector closeout](2026-09-02-connector-0.4.5-catalog-snapshot-identity.md) | unconfirmed in that record | unconfirmed in that record | health accepted |
| 2026-09-03 | Local server beta.95 integration `d6a4a626` | [beta.95 record](2026-09-04-beta95-unified-local-integration.md) and Git commit timestamp | checked | no deploy | no deploy |
| 2026-09-04 | Local server beta.96 `42a99a85` | [beta.96 record](2026-09-04-beta96-visual-audit-and-first-device.md) | checked | no deploy | no deploy |
| 2026-09-14 | Agent World beta.96 candidate `2debb2d6` | [exact-SHA acceptance](2026-09-14-agent-world-historical-acceptance.md) | candidate checked, owner acceptance open | no deploy | no deploy |
| 2026-09-23 | Shared Models Local work, `256af9db` remote-tracking ref | Git history and 2026-09-22 Local handoff in the feature checkout | branch/QA only | no deploy | no deploy |

The reference image supplied only layout, color and visual hierarchy. Its
versions, dates, generic product title and automatic green deployment checks
were not used as factual sources. No future version or roadmap date was added.

## Verified earlier baseline and cumulative product history

The first Git commit `004bcc4121d2` dated 2026-04-29 is a **working Local
MVP-1**, not a demonstrated public deploy. Its `NT-Analyzer/README.md` and
`app/static/index.html` show the NinjaTrader Bridge, strategy/instrument
catalogs, single and batch backtests, job history, results, trades, metrics,
equity and price-chart tabs. Strategy creation, AI, sharing, owner workspaces
and public Production are not claimed for that first commit.

The historical tag `v1.0.0-backtest-working` points to `7fc22e484cf1` on
2026-05-02: the first locked B1 ShortOnly strategy and accepted backtest
baseline. The earlier `c52656ec` commit added an informational Risk Profile.
The tag is a backtest milestone, not a later Server SemVer or deployment.

`docs/changelog/UI_INTEGRATION_LOG.md` records the 2026-06-28 Aurora cutover
of seven real API-backed application pages. Its phrase "production cutover"
refers to the application's default UI route; that record alone does not
establish a public Linux deployment. No SemVer for that UI milestone was
found, so the card explicitly says no SemVer.

The earliest **exactly identified public Linux baseline** in the checked
operational history is Stage 10: Git `1031437b` contains
`NT-Analyzer/docs/STAGE10_CLOSURE_2026-08-01.md`. It records Canary and
Production ready on Server `0.9.0-dev.15`, source `f05f287d3233`, release
directory `0.9.0-dev.15-f05f287d`, and a separate Windows Local contour.
Its dev.13 was the initial Linux cutover during the same stage; dev.15 is the
accepted final state. The closeout also confirms owner onboarding, workspaces,
NinjaTrader Connector, AI and Telegram paths, release rollback and that live
trading remained disabled. The later 2026-08-12 beta.1 snapshot is therefore
not presented as the birth of StratForge.

The page now has nine milestones: Local MVP-1, working backtest tag, Aurora,
public Stage 10 baseline, beta.1 release, beta.29 graphics/UI, beta.87 owner
backtest correction, beta.92 catalog/Connector, and **one open post-beta.92
Local delivery batch**. The batch combines Social/Chat/registration, Agent
World work, the `Поделиться` model switch and graphs for Preview test accounts.
Its detail panel retains dated subevents and technical sources. Agent World is
still `IN DEVELOPMENT` and is not counted as an accepted Local capability.
Its appearance in the delivery batch does not assert Canary or Production
promotion. The list of 23 numbered capabilities is defined once and rendered
in identical order for all three environments. The counters count confirmed
presence: Local 22/23; last-recorded Canary and Production 16/23 each.

The top Local card uses `/api/runtime/env` checked on 2026-09-24:
`0.10.0-beta.96`, build `dev-0.10.0-beta.96-56945ac68e94`, commit
`56945ac68e94`. Canary and Production show the last confirmed beta.92
artifact from the release record, not a fresh live-server claim. All three
cards retain earlier core functions, including backtest, reports, charts,
strategy/instrument work, market data, practice/paper, NinjaTrader, AI Lab,
AI helpers, documents, identity and Release Center; the Local card adds
confirmed Social, SF Chat and new
registration/security. Connector `0.4.5-dev.1` is only claimed as accepted
on Production; its Local and Canary installation remain unconfirmed.

## Presentation and verification

The desktop and mobile timeline stays horizontal. Nine equal-height cards
sit under the date/version and aligned timeline dots. The nine-card width
calculation fits 2560/3440/3840 px; at 1920, 1440 and narrow widths only the
history viewport scrolls horizontally. The whole card opens the right drawer
with click, Enter or Space; the drawer closes through X, Escape or backdrop.
The open batch shows dated subevents; SHA, artifact and sources remain there.
Light and Dark choices persist in localStorage.

Static validation results and the browser visual-review status are recorded
in the task closeout. A prior browser action rejected the local file URL and
explicitly prohibited alternate browser routes for that action; calculated
layout widths are not presented as rendered screenshots.

Revision verification on 2026-09-24: JavaScript parsed; the data contract
checked 23 unique chronologically ordered capability IDs, counts 22/16/16,
nine milestones, one open post-beta.92 card, 2–4 chips and complete environment
statuses. HTML IDs, date/point order and whole-card click/keyboard handlers
passed. `validate_external_gpt_context.py` returned OK.
`pre_release_check.py` returned PASS for a 629-file bundle (static scan,
runtime reads, Python compilation and shipped JavaScript syntax). A first
pre-release scan exposed a link from the shipped changelog to the repository-
only maintenance doc; the link was changed to a plain path and the gate passed.
`git diff --check` passed. Rendered visual acceptance remains blocked by the
prior local-URL browser rejection.

The upkeep rule is repository-only `NT-Analyzer/docs/TIMELINE_MAINTENANCE.md`,
linked from root developer instructions, the README, documentation governance
and the External GPT Context Pack. Future developers append confirmed Local
work to the current batch and advance the same card through exact-artifact
Canary/Production acceptance before opening the next delivery batch.

Release impact: standalone review page and canonical changelog only. No
server runtime or deployment was changed. A later shipped application artifact
would require its own release cycle and exact-artifact verification.
