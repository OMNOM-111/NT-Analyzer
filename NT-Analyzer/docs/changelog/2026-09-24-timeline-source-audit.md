# StratForge history timeline — source audit and correction

Release title: Fact-checked development and deployment timeline.

Change summary: The standalone root `timeline.html` now uses dated Git and
release events instead of example artwork as project history. The three
canonical environments are Development, Canary and Production. Server and
Connector versions remain separate, and each card distinguishes Local work,
Canary acceptance and Production publication.

Affected surfaces: standalone `timeline.html` and factual deployment snapshots
in External GPT Context Pack 00, 02, 04 and 11. The application runtime, release
artifact selection, market data and Connector code are unchanged.

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

## Nine timeline events and their evidence

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

## Owner-facing presentation follow-up

The standalone timeline groups related technical records into seven
product-oriented milestones. The 2026-09-02 server catalog fix and the later
Connector installation appear together, with separate version and environment
notes in the right-side detail panel. The Local beta.95/beta.96 work appears as
Social, SF Chat, registration and security rather than a list of commits.

The three top cards now list only functions present in their specified build,
with version, build and commit shown in smaller type. The Local card describes
the active `:8765` process; Agent World remains identified as a separate
candidate below. The Canary/Production cards describe the last confirmed
beta.92 artifact, not an unverified current live state. The new three-step
registration is ahead of that artifact; beta.92 still had basic login.

Every milestone card uses the same compact structure: date, version, product
change, two to four feature chips, three environment statuses and a details
control. SHA, artifact identity and long descriptions are confined to the
right-side panel. Clicking anywhere on a card opens it; the details control
provides a keyboard path. The panel closes by button, backdrop or Escape,
restores focus, and keeps focus inside while open. The page uses a fluid
seven-column horizontal timeline through 1440 px, a vertical timeline below
1361 px, and complete Light/Dark themes with localStorage preference. The
source-audited facts and deployment statuses were not changed by the UX work.

UX verification: static HTML contract PASS for seven sorted cards, 2–4 feature
chips and three statuses per card, no SHA in the main cards, three compact
environment snapshots, and existing source links. Inline JavaScript syntax
PASS with `node --check`; `validate_external_gpt_context.py` PASS with a
pre-existing pack SHA warning; `pre_release_check.py` PASS (629 bundle files,
all four checks). Width calculations were checked at 3840, 3440, 2560,
1920, 1440 and 390 px; these are static layout checks, not rendered
screenshots. Actual Light/Dark and viewport visual acceptance remains BLOCKED
by the browser URL policy noted above.

Release impact: documentation and standalone review page only; no server
artifact, Canary or Production deployment. If this page is later shipped in an
application artifact, that requires its own release cycle and exact-artifact
verification.
