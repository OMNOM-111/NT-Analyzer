# New-user Local completion

Status: IN DEVELOPMENT. Verification: PENDING. No release or deployment approval.

## Preserved source

Continue Shared Models WIP after f5cb49d5, through 77eda536 and the active Local
chart gateway correction d9c538605e8e6cade81524fc1b41850b7f500980. Work proceeds in
`codex/shared-model-local-completion`, an isolated checkout of that exact ancestry.
The original branch and all dirty runtime/governance/cache files remain intact.

## Changes under verification

- Ordinary Preview registration gets the existing initial trial and its own empty
  personal workspace. The shared-model bridge serves ordinary Preview scenarios;
  an explicit AI-denied profile retains the negative authorization check.
- Actual registry cards gain a short connection test and explicit binding for
  sharing. Shared descriptors render alongside the registry, including when empty.
- Shared connection tests use the same grant, budget and usage accounting.
- Chat can recover a saved reply by exact request identity through a scoped GET,
  with no provider retry. Preview task detail uses the same persisted task store.
- TopStep strategy tab opens under the existing live-read trial capability and
  honestly reports IN DEVELOPMENT. It does not display owner chart credentials
  or alter market-data policy, chart routing, or trading authorization.

## Verification and cleanup

Initial browser reproduction on d9c53860: GitHub/phi-4 card had neither test nor
share control; shared Preview chat returned a real saved answer but its task
state was unavailable. Models tab then failed to load. Browser checks continue.
The embedded browser timed out; hands-on QA uses Chrome through computer-use.
Owner access baseline: 2 users, 1 workspace, 3 memberships; projected access
SHA256 dfcdf0b471112eb88388f3651350b5a5efb6082c172935de1209658af3011ccd.
Disposable Preview was closed through Exit Preview. DeepSeek sharing was
temporarily enabled for QA and must be restored before closeout.

Server, Canary and Production remain untouched. PR and final evidence pending.

## Local browser follow-up

Ordinary registration was completed in the disposable UI (email fixture, agreement, temporary device, cabinet). Shared DeepSeek and Gemini appeared without owner settings. A real connection test exposed an overview crash: the Preview demo projection assumed `persona_key` on real task checkpoints. The HTTP overview now reads the real scoped domain projection; regression covers a completed shared chat followed by overview/tasks reads. Desktop navigation retains the trial entitlement independently of market-data admission. The internal model chooser includes shared entries. Preview manifest writes retry transient Windows reader locks without truncating existing state.

Verification: 67 focused tests passed before fixing a test-only permissions field typo; the complete Preview module then passed 27 tests. Browser delivery recovery asserts one POST and one history GET, never a repeated model invocation. Manual acceptance and full regression remain pending.
