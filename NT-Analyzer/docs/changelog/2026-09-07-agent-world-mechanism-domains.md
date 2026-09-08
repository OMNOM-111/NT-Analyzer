# Agent World — mechanism domains connected, review boundary closed

- Release title: Agent World — the automation and router domains answer their
  own state, and acceptance stops where the evidence does
- Change summary: the two mechanism domains stop being a permanent 409. An
  adapter connects them to the mechanisms that already exist, the scheduler
  gains the producer it never had, and the whole permit → run → stop path is
  walked over the normal API on an isolated instance. Alongside it, the boundary
  between a human accepting a result and the evidence holding up is pinned
  case by case: a deviated result is never offered for sign-off, a stale
  revision or hash is refused, acceptance cannot rewrite the hash it is bound to
  or turn a damaged result into a verified one, and an adapter row that asks for
  a check now says why acceptance is unavailable and links to its source instead
  of rendering with nothing to do.
- Canonical status: `IN DEVELOPMENT` unchanged. This closes named gaps in the
  integration pass; it is not programme acceptance and not owner visual
  acceptance.
- Branch: `claude/agent-world-integration`, local and unpushed. No PR opened;
  PR #282, #283, #284 and their bases were not touched, and nothing was pushed
  to a Codex branch.
- Source baseline: `d30439e439ceaca3a4748285c9a52331cb91e75c`, tagged
  `checkpoint/agent-world-integration-regression` after a full suite of
  **4521 passed, 110 skipped, 0 failed** (28m16s). Code commit applied on top:
  `92436698c279fa41530b96fc9ad5509cc56596ad`.
- Version: `0.10.0-beta.96` unchanged. No merge to main, deploy, signing, SQL
  migration, flag default change, owner-key copying, budget increase or trading
  order. Migrations remain 1–23. Local 8765 was not switched, not restarted and
  not read.

## Why

Part C recorded the two mechanism domains failing closed with
`mechanism_domain_unavailable`. That fixed an unhandled crash, but a route that
always refuses is not a working capability, and the report said so. The module
those routes dispatch to still exists in no branch and no worktree — the search
was repeated over every local ref and every checkout before anything was
written.

## What changed

### The domains

`app/ai_control_center/mechanism_domains.py` stands in for the absent
`mechanism_gateway`. It is an adapter, not a mechanism: every ranking, grant,
device check, flag check and budget check is made by `automation_authority`,
`scheduler` or `router_v2`. A request it cannot forward is refused by name, and
a test asserts that a forwarded request's refusal never carries one of this
adapter's own codes. `domain_gateway` resolves the real module first, so the
checkpoint's own file replaces this one rather than being merged with it; with
neither importable both routes still fail closed with a stable code.

Reading starts nothing: the read path never calls `select`, `admit` or a tick.
It reports stored approvals, the schedules they control, the capability state
beside the existing owner route that changes it, and — for one task — the model
that actually ran it with the same observation set the router itself reads. Only
`preview` computes a decision, always shadow, dispatching nothing. Delegation
and active routing are named in `limitations` rather than answered.

### The scheduler's missing producer

`scheduler.create` leaves a controller and queues nothing; `scan_due` had no
caller outside tests, so an approved schedule never started unless a person
opened the panel — the exact case the mechanism exists to cover.
`domain_gateway.reconcile_schedules` adds that producer beside the
model-delivery recovery already in `local_worker.run_once`: same throttle, same
bounded keyset read, same rule that a scope is reused from a job the workspace
already produced rather than assembled. It decides nothing, and every occurrence
is still admitted against its own stored grant, flag and budget.

### The review boundary

A deviated result is never offered for sign-off and a forced submit is refused;
the deviation and its reason survive. A stale revision, and a hash that does not
match the result the reviewer was shown, are both refused before anything is
written. Acceptance stores the server's own fingerprint, never the caller's
value, and leaves the automatic verdicts untouched — the human decision is a
separate evaluation record carrying `quality_claim: false`, the reviewer, the
revision and the source hash.

An adapter row whose evidence failed verification had no exit: awaiting review,
no action, no link, no reason. It now states why acceptance is unavailable and
links to the source report; the verified row and the model row with its own
review action are untouched, and an off-site link is never surfaced.

## Verification

Walked over HTTP on the isolated instance at `http://localhost:8802`, with no
process access: reading either domain leaves the task count unchanged;
`propose` returns a controller without creating one; `enable` is refused with
`automation_entitlement_required` until the owner grants `ai_automation` through
the existing `POST /api/auth/users/{id}/permission`, then creates the schedule;
the worker's own periodic scan starts the due occurrence with no panel and no
chat open; the run stops at the budget authority with
`model_private_budget_not_configured`, so no provider call is made; `cancel`
stops the schedule and `revoke` supersedes the grant. The Router view shows the
model that actually ran a task and the shadow decision's per-candidate reasons —
no external model was called and no comparison of real models is claimed.

The hidden-tab boot is confirmed rather than inferred: a load with
`document.visibilityState === 'hidden'` throughout renders the full shell and
issues exactly one `/api/auth/status` request. The mechanism was not changed for
this check.

Full detail, including the implemented / API connected / user scenario verified /
blocker table, is Part D of
`docs/current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md`.

## Not done

Delegation still has no domain surface. The Router has never applied an active
route. No instance has run with `STRATFORGE_AGENT_WORLD_STORAGE=postgres`. There
is no Aurora control for the `ai_automation` capability, only the owner route.
No merge to main; no change to PR #282, #283, #284 or their bases; no push to a
Codex branch; no force push; Local 8765 not switched or restarted; no Canary or
Production deployment; no external paid call and no trading order. No
programme-level item is closed by this set.
