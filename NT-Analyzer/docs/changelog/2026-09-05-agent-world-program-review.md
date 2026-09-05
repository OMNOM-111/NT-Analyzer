# Agent World — integrated owner review continuation

- Release title: Agent World — verified results, explicit handoff and manual review
- Change summary: retain completed SF Chat in-app dialogs; finish the integrated
  owner-review path with separate application-result observations, explicit
  fact handoff between Personas, manual routine/calendar discussions and HTTP
  Memory isolation evidence. No replacement of working execution authorities.
- Canonical status: `IN DEVELOPMENT`; Local review is not whole-program acceptance.
- Branch/PR: `codex/agent-world-owner-preview`, draft
  [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282), above unmerged #281/#280.
- Source baseline: `f80d67f730bcd4734893ee7f83643f580138be9a`; active code before
  this delta `95912cbff8152905966e6bb7bfc2a45d3db15f80`.
- Version: `0.10.0-beta.96` unchanged. No merge, deploy, signing, SQL migration,
  owner-key copying, budget increase or trading order.

## User-visible changes

The accepted three-tab page remains Overview / Work / Agents, with contextual
drawers and existing SF Chat. Genuine report/PNG outcomes stay visible before
later model-check outcomes. Real backtest and chart receipt observations appear
separately in agent profiles: distinct verified inputs, exact provenance, NEW
below three observations, no pooled profitability or general-quality score.
Failed and pending attempts remain in history; they are not verified receipts.

An owner may explicitly transfer an existing verified application's allowlisted
facts to a different active Persona/model. It creates a typed dependent Task in
the same SF Chat, sharing correlation with its parent. Only faithful fact
transfer is independently evaluated (`extract_facts`), not strategy correctness
or visual chart analysis. Before any provider transmission, the source revision,
artifact hashes, original/child messages, target, account/device membership and
existing budget are rechecked. Recursive or implicit delegation is not added.

Accepted routines/calendar events now have an explicit **Open manual review in
SF Chat** action. The existing worker delivers one neutral system message with
source/revision/date and an immutable receipt. Repeated requests do not duplicate
it. Queued does not mean delivered; the page shows the saved conversation only
after delivery. This is immediate human-requested discussion, **not execution at
the event's due time**. Automatic scheduling and model spending remain OFF.

Own-model connection has an inline guide to a separate OpenRouter inference key,
the real password field, and `openrouter/free`. Owner credentials are never
copied. A compatible external agent means a supported HTTPS chat-completions
endpoint, not arbitrary MCP/desktop access. Free-router selection/availability
is provider-controlled; no particular underlying model is invented.

Readonly-session, entitlement and exhausted-budget projections now hide
unavailable actions in lists, details and Overview without hiding prior evidence.
The existing POST authority was already fail-closed; this aligns the UI with it.
All Aurora pages receive the same updated shared-script cache key; the completed
in-app dialog behavior/theme and native-prompt boundary remain unchanged.

## Verification and evidence classification

- Presentation/UI: 206 PASS; current presentation/dialog/Aurora regression:
  135 PASS. Pure rendering tests do not assert live provider behavior.
- Final integrated gateway/model/follow-up/presentation subset: 267 PASS,
  zero skipped, 278.92 s.
- Memory: 26 actual loopback HTTP/SQLite tests with synthetic ordinary sessions;
  190 combined PASS. Covers grants, private artifacts, member/foreign scope,
  source supersession/revoke/TTL, device/session/membership revocation and CSRF.
  This is not a live multi-human browser acceptance claim.
- Frozen full regression: **4235 PASS, 44 skipped, zero failures**, 1129.40 s.
  Skips: 41 PostgreSQL cases without the isolated acceptance DB and three
  Windows-inapplicable shell/POSIX cases. Skipped is not verified; the previous
  real PostgreSQL run is historical evidence only. An interrupted pre-freeze
  run is not PASS.
- Exact staged bundle: **542 files, PASS** for static scan inside bundle,
  required runtime reads, Python compilation and shipped JavaScript syntax.
  Two repository-only current-document links were found by the first bundle
  run and corrected to explicit accepted exclusions, then the bundle passed.
- Repository-root CSP/secrets/Markdown scan, context validator and diff check:
  PASS. No source outside the named Agent World/Chat presentation scope changed.

Scoped evidence: [application evaluations](2026-09-05-agent-world-application-evaluation-projection.md),
[typed handoff](2026-09-05-agent-world-typed-result-handoff.md),
[manual discussion](2026-09-05-agent-world-manual-followup-chat.md),
[Memory HTTP](2026-09-05-agent-world-memory-http-e2e.md),
[gateway contracts](2026-09-05-agent-world-program-gateway-contracts.md).

The real historical NT result remains task `62182839-1c4c-563d-8186-bcef081ec599`:
64 trades, net after commission -969.70, PF after commission 0.7252. The genuine
Desktop PNG remains task `c691534b-0670-5313-af39-491b46564248`, 140 rendered of
800 historical bars, not a fresh live quote. These are prior actual executions
being retained and reverified, not newly executed jobs or fixture statistics.

## Remaining program and approval boundaries

Separate ordinary-user registration/device/key acceptance and an independently
configured external-agent endpoint remain unverified. An expired email challenge
was observed in the ordinary-user registration draft; no completed ordinary
account or successful user-key test is claimed. These block only those scenarios.

SF Social exact snapshot `e4853566df3b4091b276f21503c64956b02a4502087e47a8af6362db6507eaee`
was reviewed again; permanent posting still awaits explicit owner confirmation
of the private visibility and caption. No source files/private Memory are public.

General autonomous delegation/Router shadow cutover, a replacement Execution
Engine/Deviation Control, autonomous due-time routines, and an Agent World
PostgreSQL adapter are not implemented by this slice. Existing safe adapters
remain authorities. Backtesting-page redesign is outside this program slice.
Owner design acceptance, scoped Git/CI closeout and full-stage closure are separate.

## Release impact and rollback

The future artifact would include the scoped Python adapters, Aurora JS/cache
references, tests and canonical documents. Runtime data, JSONL history, secrets,
operator scripts, logs/screenshots and backups under `.artifacts/` are excluded.
All ten flags default OFF; eight exact Development-workspace flags stay ON,
Router/Execution V2 stay OFF, and no Canary/Production flag is changed.

The prior clean Local code `95912cbff8152905966e6bb7bfc2a45d3db15f80` is the
code rollback point; preserve later owner writes before any data rollback.
No automatic state rollback is authorized. The verified Local activation helper
retains the original owner data root and refuses active work or an unknown PID.

## Operational closeout

Code verification result: **PASS**. Exact source commit:
`2b6d0112bef88c5bfb73970de64ec5518443e56b`, committed/pushed to the task branch
and draft PR #282. Local 8765 runs that clean detached code at beta.96,
build `dev-0.10.0-beta.96-2b6d0112bef8`, dirty=false, Preview=false.
Original owner data/settings remain in the original Development data root.
Isolated-copy startup/integrity/identity, staged and clean runtime 542-file
bundles PASS. No unrelated runtime or NinjaTrader process was changed.

[Exact-code CI 33984524477](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33984524477)
passed 3/3: Windows 4235 passed / 44 skipped in 1053.96 s, Ubuntu 4238 passed /
41 skipped in 305.64 s, static. These are dispatched branch checks, not absent
main-target merge checks. Local full suite is 4235/44 in 1129.40 s. The current
41 PostgreSQL skips are not a fresh repeat of the historical DB acceptance.

### Actual browser/runtime continuation

- Original report and PNG were reverified on 2b6d0112 without a new NT run.
  PNG is 718×424, 31,541 bytes, SHA256
  `45ba864f7ccb06c9fba8655a4839378e1e9fd049d0d5f3d350567ae3081e9c40`;
  an actual browser screenshot shows it in the original SF Chat message.
- New real handoff `bf665c7e-bdc4-5652-8c22-c2bfcdbc5df1` depends on
  `62182839-1c4c-563d-8186-bcef081ec599` revision 9, same correlation.
  Anna's Azure response passed `extract_facts`; estimated cost USD 0.000355.
  Eight allowlisted facts match source packet SHA256
  `2bfd4e23f74c09a1c99d302dda9e5612ddc2b1fe01bd5ac90851405e7fd2ccb2`.
  Chat `C-1322EA65B646` has eight messages and exactly one completed child
  `MSG-235DD76B5F2C`. The original source result remains intact.
- Accepted routine `a590f088-8ac5-59e1-ac62-b44142b66f9d` and calendar
  `4901ad4b-d44c-5f28-86c7-5d40543fcd62` each delivered one system message
  through the explicit manual action. Threads:
  `AW-FU-df856682d5195c3f69a61d4bbc6e` / `AW-FU-8bdfc131d0dcd300d6d04d46db34`.
  Message IDs `MSG-81B21C17C904` / `MSG-3A46C0147400`; hashes match their
  receipts. Repeated calendar action did not duplicate delivery. No model,
  provider or rating event in either receipt; automation/execution/scheduled
  delivery=false. This is not automatic scheduling.
- Agents show separate Tolik backtest n=1 and Ivan chart n=1, both NEW,
  independently of the n=3 arithmetic observations. Anna's fact-transfer
  evaluation appears in task/history, not a fabricated arithmetic score.
- The empty own-model wizard was opened in the real owner UI and cancelled
  without submission. Its inline guide, separate Persona/provider fields and
  `api_key` password/new-password field were checked without reading secrets.
  This does not certify an ordinary account or a real user-supplied key.
- Read-only post-action verifier: 12 GET, runtime source stable before/after,
  2026-09-05T19:05:43Z. Exact receipts, hashes and message counts are in local
  `.artifacts/program-review-20260905/`; no runtime data or secrets enter Git.

`IMPLEMENTATION COMPLETE: YES` for this bounded integrated owner-review slice
and the earlier SF Chat dialogs. `GIT CLOSEOUT COMPLETE: YES` for code 2b6d0112
(pushed, draft PR, exact-code CI PASS). Operational documentation advances the
branch separately; the active runtime code SHA above remains authoritative.
`STAGE CLOSED: NO`; full-program implementation/owner acceptance is **PENDING**
with the unverified, unimplemented and external/owner blockers listed above.
No merge or deploy was performed.

The repository-only `docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md`
is the single current handoff; this shipped record supplies scoped historical
evidence. Owner/developer current documents are excluded from the runtime bundle.
