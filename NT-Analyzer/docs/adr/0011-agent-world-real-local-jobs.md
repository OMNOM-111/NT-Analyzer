# ADR-0011 — real Local owner jobs and Desktop receipts in Agent World

Historical decision checkpoint: the Local-switch authorization and domain/model
scope were extended by [ADR-0012](0012-agent-world-integrated-local.md). Statements
below about an unanswered switch and evaluation/domain flags OFF describe this
earlier checkpoint, not the current program status.

Status: implemented in the current Development checkout; final integration
verification and owner visual acceptance are pending. This decision extends the
bounded owner-review implementation, not the overall completion of stages 0–13.
The business requester is the project owner. Technical attribution is
AI-assisted change; persona names are not model provenance.

## Context and decision boundary

The owner explicitly requested actual historical NinjaTrader tasks and a chart
snapshot from the application's real Desktop, with results returned through
SF Chat. A synthetic benchmark alone cannot satisfy that request. Keep the
isolated fixture workflow described in [ADR-0010](0010-agent-world-owner-review.md)
and add a separate, default-OFF real Local owner composition. Do not relabel
fixture output or an old manually created report as new Agent World work.

[ADR-0009](0009-agent-world-foundation.md) remains the proposed foundation
contract; its entities are not collapsed or silently rewritten. The current
[program status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) is the sole
current handoff. Historical foundation and Preview decision records remain.

The branch is `codex/agent-world-owner-preview`, stacked above the beta.96 source
and foundation dependencies, PR #280 and PR #281. At this documentation
checkpoint HEAD is `c62c5547ef6f82c561bb12b474ee6f3aa21d7c28` with dirty
integration changes; it is not the final source commit. Version remains
`0.10.0-beta.96`. No merge, release, signing, Production/Canary operation or
numbered shared-storage migration is authorized by this decision.

The owner runtime on 8765 is still beta.93 / `7062f749ee92299356c774d01dc0c7b59cdcbba3`
in the original checkout. The separate question permitting a switch to the new
checkout remains unanswered. Implementing this path does not constitute
permission to stop that runtime or move its data/settings/secrets.

## Authorities and storage

| Boundary | Existing authority reused | Additive integration |
| --- | --- | --- |
| Human identity and device access | `account_auth`, existing Handler Local entry and browser device confirmation | fresh active owner UUID and confirmed session checks; no new login or bypass |
| Workspace and actions | `workspaces`, `permissions`, current capabilities | exact owner workspace/membership; repeat checks before work and delivery |
| Resource admission | `ai_budgets` | existing zero-cost check; no new paid budget ledger |
| Historical backtest execution | `jobqueue` and local NinjaTrader Strategy Analyzer/Bridge | `live_backtests.py` creates existing canonical jobs and projects their IDs/status/evidence |
| Desktop actions and images | existing chart-command queue, Desktop canvas and snapshot store | `live_charts.py` correlates commands, PNG receipts and their existing saved artifacts |
| Progress and result delivery | existing Chief monitor and scoped AI conversation store | replay-safe SF Chat messages; no second worker loop, chat database or delivery engine |
| Availability | foundation `flags.py` registry and existing audit events | trusted real-owner configuration snapshot, separate from Preview |

Real jobs remain authoritative in their existing queue/report stores. Stable
Task UUIDs are projections of those job IDs, not a second task executor or a
parallel source of truth. The live path does not write the Preview SQLite
database. Desktop receipts remain in the existing command result and SF Chat;
saved images remain in the existing snapshot store. Human/DM and AI conversation
authorities keep their accepted separation behind SF Chat.

## Admission and default-OFF flags

The only real Local opt-in is the trusted server setting
`STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES`, a comma-separated list of exact
`ws_*` identifiers. An empty allowlist or a malformed/wildcard identifier fails
closed; this is not a global owner grant. The setting is ineffective outside Development and
inside synthetic Preview. No browser payload, query string or localStorage
value can create it.

Each request must come through the existing authenticated owner context. Browser
sessions require active Device Confirmation; the established trusted Local
`source=local` entry remains unchanged. Current owner UUID, active owner workspace,
owner membership, `uses_owner_runtime`, `ai_lab` and `backtesting` capabilities,
existing permissions and budget admission are revalidated. A previously admitted
operation cannot retain authority after owner, UUID, membership or capability
revocation. Flags are availability only and never replace these checks.

| Registry flags | Real Local owner | Controlled synthetic Preview |
| --- | --- | --- |
| Read model / AI Center UI / task graph | ON only after real-owner admission | ON only after Preview-control admission |
| Evaluation shadow | OFF | ON for deterministic fixture checks |
| Router shadow / consensus / Court / execution V2 / memory / social publishing | OFF | OFF |

Ordinary non-opted-in Local and Canary/Production keep every new flag OFF.
Preview continues to require its owner-issued control cookie, confirmed
synthetic identity, private root and external-effects guard. The real Local
path cannot activate Preview credentials or weaken Reset/Exit isolation.

## Explicit historical backtest contract

SF Chat recognizes a bounded explicit backtest request, not arbitrary goals.
The owner supplies the registered strategy, instrument, timeframe, UTC interval
and parameters. The existing catalogs, strategy allowlist and canonical job
validator remain authoritative. Date validity/order and a maximum 31-day window
are checked; unsupported or missing inputs are blocked rather than invented.
Negative numerical parameters and negative results must not be filtered out.

The submitted canonical request retains the declared research assumptions,
including session/commission template, High fill and slippage. Existing Reports
normalizes performance and commission; the adapter does not recalculate results
from a sample of trades. No strategy code generation, compilation, live-order
command or alternative backtest engine is introduced.

Job identity is deterministic over Development/workspace/owner UUID/request key.
A fingerprint of the normalized specification and conversation detects changed
payloads on replay. The original job origin carries a server-written Agent World
marker and exact owner scope. Unmarked/manual, foreign, synthetic or UUID-spoofed
jobs are excluded; legacy/global scope fallback is disabled.

| Original job state/evidence | Agent World projection |
| --- | --- |
| pending / running | ready / running; no completion claim |
| cancel requested | blocked pending the existing executor's answer |
| failed / cancelled | failure / cancellation, not a verified successful result |
| done with valid matching canonical evidence | succeeded and verified historical result |
| done with missing, corrupt, changed or inconsistent evidence | review; no fabricated completion |

Verification checks original job/result/trades/bars provenance and checksums,
matching context and consistency. A genuine zero-trade result with valid bars
is distinct from missing historical data. A valid result may be unprofitable.
Execution verification does not measure the quality of the persona or any LLM.

## Desktop PNG receipt contract

Ivan queues an existing `snapshot` command for an explicit instrument/timeframe
and originating conversation. The real Desktop must be open, receive actual bars
through its existing providers and capture its current canvas without fit/view
reset. No hidden renderer, synthetic chart or alternate data provider stands in
for that browser step.

`assets/pages/desktop.js` has a deliberately narrow additive exception to its
previous unchanged-file boundary: Agent World PNG capture metadata, bounded
image submission and validation of the returned saved receipt/ACK. Its hash
changes for that reason. The chart engine, rendering/zoom/view logic, market-data
engine, provider transport, Connector and `jobqueue` are not refactored.

The server checks current owner admission, command/conversation/instrument/
timeframe correspondence, current bounded capture metadata, nonzero bar counts,
PNG structure/CRC and size (at most 256 KiB), then records the image hash and the
existing saved snapshot reference. It saves the receipt in the command result
before posting to chat. Retry recovers that same receipt, and a client ACK cannot
overwrite it with an unverified success. Missing/expired captures remain pending
or blocked; changed/missing saved files require review.

This is `authenticated_desktop_canvas_receipt` provenance. Client observations
such as bar count, visible range or connection state are bounded descriptive
metadata, not independent proof that the screenshot matches current exchange
data. The UI must not turn this receipt into a claim of live quote freshness,
independent visual certification or model quality.

## SF Chat, UI and verification semantics

The existing Chief ingress/monitor provides narrow dispatch and completion
projection. It keeps original conversation scope and hashes the complete source
request ID before the chat store's 120-character limit. Full-transcript dedupe
and metadata repair handle retries after message append/index failures. Receipt
revisions use source evidence identities; a retry is not a second job or score.
No Telegram send/topic update, social publication or conversation closure is
implied by these messages.

The current checkpoint UI has exactly Overview / Work / Agents and a task drawer,
not placeholder active pages for every future foundation domain. Real tasks show
their original report or saved Desktop image and honest progress/failure states.
Model quality stays NEW/unassessed, evaluation-shadow OFF and routing unchanged.
Synthetic per-class scores remain labeled in their separate Preview context.
Persona, Role, Provider Account and Model remain separate concepts.

## Evidence, risks and next gate

The existing manual owner job `ui_20260905T003301149Z` returned an actual
NinjaTrader result with 1273 bars and 64 trades. Service-level verification passed
with `reasons=[]`. This is useful evidence about the existing executor/report
contract, **not** proof of new Agent World ingress/delivery. Its origin is not
Agent World, so it stays excluded from new statistics and is not backfilled.

A fresh chat-created real job and real Desktop browser receipt are still required
after an approved Local handoff. Focused tests use temporary roots and no real
owner/network side effects; final combined regression, static/context/bundle
gates, clean commit/PR/CI and owner visual acceptance remain separate checkpoints.
No final real chat/browser pipeline PASS or overall stage closure is claimed.

The safe next sequence is checks -> clean integration commit and separate PR ->
owner-approved Local-only switch with preserved data and exact process ownership
-> real SF Chat/NT/Desktop end-to-end verification -> owner design acceptance.
Local rollback must restore the original launcher without a second writer;
code rollback does not automatically restore already-written data. Dependency
merges and any signed immutable artifact/Canary/Production cycle require their
own owner approvals.
