# Agent World — real Local tasks, isolated Preview and SF Chat evidence

## Change summary

Continue the accepted beta.96 foundation into a clickable, three-tab AI Center
with a task drawer and two explicitly separate paths. Controlled synthetic
Preview retains transactional fixture tasks/artifacts and low-confidence shadow
evaluation. The added real Local owner path submits explicit historical
NinjaTrader jobs, requests real Desktop chart captures and returns evidence to
the originating existing SF Chat conversation. SF Social receives its intended
user-visible label without changing community APIs.

Initiator: owner request to continue to visual acceptance and then to exercise
actual historical NT/Charts work through chat. Technical attribution:
AI-assisted change; no model identity inferred from persona names. This change
does not claim the broader Agent World program or owner visual review is closed.

## Scope and source

- Version: `0.10.0-beta.96`, unchanged Development; not a release.
- Accepted source: `4ae766ea0c3258a8bb049644ac2afbba6cb89330` (PR #280).
- Foundation: `d5d07ac6817cd10f57d916dab0ce655347a8cbde` (PR #281).
- Branch: `codex/agent-world-owner-preview`; source SHA / separate PR pending
  integration closeout. Neither dependency PR is modified or merged.
- Current HEAD: `c62c5547ef6f82c561bb12b474ee6f3aa21d7c28` plus dirty
  integration changes. This is a checkpoint reference, not the final source SHA.
- Code: additive ai_control_center modules; small server/permission/shared
  transport/nav/chief/Preview lifecycle integration; new UI, tests/docs.
- Real composition: `live_gateway.py`, `live_http_api.py`, `live_backtests.py`
  and `live_charts.py`; existing jobqueue, Desktop commands, snapshots and Chief
  monitor/SF Chat remain the runtime authorities. No second worker or task engine.
- AI Center navigation is exactly Overview / Work / Agents plus a task drawer.
  Future domains are not presented as additional active placeholder tabs.
- Common API/UI cache marker is updated consistently on Aurora pages. A real
  HTTP test checks the new static page allowlist as well as action/artifact APIs.
- Existing Preview tests now restore the generated promo environment variable;
  production registration assertions and flow are not weakened.
- The Windows subscription retry test now patches a module-local OS proxy,
  avoiding unrelated background writers changing its exact retry counter.
- No market-data engine, chart engine, Connector, jobqueue, trading or numbered
  migration changes. `assets/pages/desktop.js` is the explicit changed-hash
  exception: additive PNG capture metadata/receipt/ACK integration only, not a
  rendering/provider/view refactor. Auth/permanent-session device behavior and
  existing Social/Chat remain regression contracts.

## Safety and product limits

All flags default OFF in the existing single registry. Ordinary Local has no new
action access unless its exact workspace is enabled by the trusted server setting
`STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES`. Empty, malformed or wildcard values
fail closed; Preview and Canary/Production cannot activate this real-owner path.
Fresh existing owner/UUID/workspace/permissions/capabilities/device and zero-cost
budget checks remain mandatory, including the established trusted Local entry.

| Path | Enabled flags after admission | Evidence and rating boundary |
| --- | --- | --- |
| Real Development owner | read model, UI, task graph only | original NT jobs/reports and actual Desktop PNG receipts; evaluation OFF, model quality NEW/unassessed |
| Controlled synthetic Preview | read model, UI, task graph, evaluation shadow | private fixed-input benchmark evidence and low-confidence per-class scores; not real work or LLM quality |
| Ordinary/non-opted-in Local, uncontrolled Preview, Canary/Production | none | no new authority or fallback |

Router, consensus, Court, execution V2, memory and social publishing remain OFF.
No LLM call, strategy generator, terminal/trading command or second permission,
budget, queue or chat system is introduced. The historical executor is the
existing NinjaTrader Strategy Analyzer; negative parameters, losses and canonical
commission/performance results are retained rather than replaced with a demo.

Live tasks require server-attested Agent World origin plus exact owner/user/
workspace scope. An ordinary old job is not backfilled or counted. Original job
status and checksummed evidence determine pending/succeeded/review/failed; an
HTTP success or queued job is not a finished result. The existing Chief monitor
returns results through replay-safe SF Chat messages without Telegram effects.

Desktop capture requires the real open page with bars and a bounded PNG receipt
for the same command/instrument/timeframe/conversation. The current view is
preserved. The existing snapshot store and command result retain the saved image
and receipt before chat delivery, allowing retry recovery. PNG structure/hash
and bounded capture metadata are checked; authenticated canvas provenance does
not prove quote freshness, independent screenshot authenticity or LLM quality.

In Preview only, three fixtures create twelve completed deterministic tasks
after three explicit runs. Retries do not increase unique samples. Its SQLite
records, fixture identities and synthetic images remain in the disposable root,
never copied into owner data or versioned Git. Real Local records instead stay
in their existing canonical job/command/snapshot/chat stores after authorized
requests. The two sets of metrics and artifacts are not merged.

The runtime at port 8765 was observed read-only as beta.93 / SHA
`7062f749ee92299356c774d01dc0c7b59cdcbba3` / dirty Development owner.
The beta.96 review child is separate. No server switch or owner data replacement
is represented as completed. Permission to switch only Local onto the new code
while preserving data/settings is pending the owner's answer. Exit Preview
returns to the unchanged full owner runtime.

## Historical checkpoint and actual runtime evidence

The first bounded implementation under ADR-0010 was synthetic-only. Its SQLite,
fixture execution, low-confidence shadow scores and Preview-controlled facade
remain valid as that separate path. The owner's subsequent real NT/Desktop
request is recorded in ADR-0011 instead of silently rewriting ADR-0010 or the
archived foundation decision. This does not upgrade the historical `c9b2883`
source snapshot into a current baseline.

On the existing owner 8765 runtime, manual job `ui_20260905T003301149Z` returned
an actual NinjaTrader result: **1273 bars, 64 trades**, service verification
**passed**, `reasons=[]`. This supports the existing execution/report contract.
It was not created with Agent World origin, is excluded from the new statistics
and is not proof that the new SF Chat ingress or completion monitor has passed.
A fresh chat-created real run is still required after approved Local handoff.

The real Desktop command -> open browser -> saved PNG receipt -> originating
SF Chat/drawer pipeline is also **PENDING**. Unit/contract or synthetic screenshot
checks must not be relabeled as real browser acceptance.

## Verification

**IN PROGRESS** — final combined results must be recorded after the current live
integration stabilizes. No earlier run is the final result for this dirty diff.

- Historical initial full run: 3 failed, 3059 passed, 44 skipped (common cache
  marker contracts and Preview promo fixture environment leak). Scoped fixes
  preserve the original assertions.
- A subsequent historical repeat reported 1 failed, 3069 passed, 44 skipped in
  the Windows subscription retry test. The isolated shared-OS monkeypatch issue
  was reproduced and fixed in the test fixture without an application rewrite.
  The absent original untruncated failure log is not claimed as exact causal proof.
- Real Local gateway/SF Chat contracts: 77 passed; with live-backtests, Preview
  identity and subscription retry: 136 passed; with existing Chief, Router and
  SF Chat: 205 passed. Python compilation and whitespace checks passed at that
  scoped checkpoint. See the [gateway test record](2026-09-05-agent-world-live-gateway-contracts.md).
- Strict crash-repair and no-Telegram tests exposed two shared-chat issues:
  replay omitted conversation work-state repair, and first-title metadata could
  schedule a Telegram topic update. The integration owner fixed both; assertions
  remain strict and pass. These focused results do not replace full regression.
- Current full/static/context/bundle gates, real chat/NT/Desktop pipeline and
  owner visual acceptance are pending final integration evidence.
- Latest integrated full run: **1 failed, 3368 passed, 44 skipped**, 428.64 s.
  The sole failure was the old Desktop script cache marker assertion. The marker
  now matches the additive receipt build; all original backend/live-freshness
  assertions remain. Aurora/receipt repeat: **90 passed**. Full repeat running.
- HTTP/UI/Desktop targeted run: **156 passed** (36 actual Handler HTTP, 91 UI,
  29 Desktop). Live backtest/chart contracts: **113 passed** (57 + 56).
- Legacy runner: **13/13 suites passed**. Exact staged bundle: **517 files**, all
  four pre-release gates PASS (static, runtime reads, Python, JavaScript).
  Repository-root-configured secrets/platform-values/Markdown scan PASS;
  External GPT Context validator PASS with the historical deployment-anchor
  warning, not a claim of refreshed deployed state.
- Browser: three explicit fixture runs produced **12 tasks**, four personas with
  **n=3**, low-confidence synthetic results; profile/task drawers remain on the
  same three-tab page. A browser-rendered PNG was visibly delivered to SF Chat.
  Exit Preview returned to the unchanged full owner Local, including its account,
  balance, online NinjaTrader state and real report. Browser warning/error log
  inspection was empty. These are synthetic UI/Exit checks, not real chat/NT E2E.
- Documentation handoff checks: repository-root invocation of
  `python NT-Analyzer/tools/release_static_scan.py --scan markdown` returned
  `MARKDOWN OK`; `test_phase10_docs_governance.py`, `test_phase11_doc_specs.py`
  and `test_documents_single_section.py` passed **38 tests**. This is not the
  final artifact gate or acceptance of the separately maintained Context Pack.

Inherited baseline/foundation results remain historical evidence, not new runs.

No paid-provider, real PostgreSQL or remote release acceptance is implied.
Previously reported Windows full-suite skips: 41 PostgreSQL acceptance tests
without explicit test DSNs; 2 shell and 1 POSIX permissions case. The latest run
must list its actual skips again. Skipped is not PASS.

## Release impact and rollback

This PR publishes source/tests/docs for review, not an artifact or a deployment.
The production bundle gate must include the new shipped code/static assets and
canonical changelog; owner/developer docs remain accepted non-shipped exclusions:
current status, ADRs, archives and External GPT Context Pack. Repository URLs below
deliberately resolve those documents outside the restricted bundle composition.

`IMPLEMENTATION COMPLETE`: pending final bounded integration verification.
`GIT CLOSEOUT COMPLETE`: pending clean commit, separate stacked PR and CI.
`STAGE CLOSED`: NO for the overall stages 0–13; owner visual acceptance pending.

Owner design acceptance, general program gaps, dependency merges, main-target CI
and immutable release promotion remain separate gates. Exit/close Preview and
leave the real Local allowlist absent to preserve ordinary runtime behavior.
No runtime DB/logs, secrets or screenshots are staged.

After code/tests/static/context/bundle checks and a clean commit/PR checkpoint,
only an explicitly approved Local switch may replace the exact 8765 supervisor,
backend and worker. Bind the new code root to the existing owner data root without
copying secrets or running a second writer; retain the original launcher. The
standard supervisor Development profile currently resets data root from checkout,
so an environment override before that standard command alone is insufficient.
No ready one-command rollback or backward-data migration is claimed. Code
rollback does not automatically undo new account/session/receipt writes.

The next owner-facing gate is a new real SF Chat backtest and Desktop capture,
followed by visual inspection of the populated Overview/Work/Agents UI and drawer.
This is local acceptance, not permission to merge or deploy remotely.

- [Canonical status](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-owner-preview/NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
- [ADR-0010](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-owner-preview/NT-Analyzer/docs/adr/0010-agent-world-owner-review.md)
- [ADR-0011](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-owner-preview/NT-Analyzer/docs/adr/0011-agent-world-real-local-jobs.md)
