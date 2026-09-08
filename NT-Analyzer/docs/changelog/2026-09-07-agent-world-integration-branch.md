# Agent World — integration branch: merged mechanisms, live defects, mechanism scenarios

- Release title: Agent World — one state logic across the merged build, and the
  mechanisms exercised where they work rather than only where they refuse
- Change summary: the mechanisms checkpoint and the independent review branch
  are merged on a separate integration branch, with one integrator. The 30 test
  failures the checkpoint carried are traced to it alone and fixed, two of them
  real defects. Three defects that were only visible on a running build are
  fixed: two live endpoints answering 500 for a module that exists in no branch,
  a full progress bar drawn on work that has not finished, and an inspector that
  described a task on a different basis from the card that opened it. The
  automation capability is pinned on all three sides — refused without a grant,
  admitted with one, and stopped after withdrawal inside a running worker and a
  restarted one. A Router decision is shown being followed rather than only
  computed, a scheduled run is carried from the ordinary scan to a collected
  result with no tick and no chat request, and a finished source with damaged
  evidence is shown recording a deviation instead of completing.
- Canonical status: `IN DEVELOPMENT` unchanged. This is an integration and
  verification pass, not program acceptance and not owner visual acceptance.
- Branch: `claude/agent-world-integration`, local and unpushed. No PR opened;
  PR #282, #283, #284 and their bases were not touched, and nothing was pushed
  to a Codex branch.
- Source baselines: mechanisms checkpoint
  `f9b9444524aa497781fe3de7254d1bfb0e3b062c`, review branch
  `7d347d204ea99103e33abdd2a011eee500028fff`, merged at
  `922c5d52bf5d467608f4e5d9bfc0ab3622ee1b93`. Commits applied in order after
  the merge: `ee3252b5187529003f4397e4c8957a1ef96b55e2`,
  `69875444627f72b2a6fdad93c49b307d64e10426`,
  `0386621db882e4513c49e992f466681416cf2715`,
  `203eed18672a778246b30424f36a1d25f7ee539c`,
  `be05226f75ff49d3fc03d5dbe05d521734d486f2`,
  `9e1fb7adf69d69224c30a058ec8adcc1e1a316c5`,
  `6126dc10246fdb3b6a53f9e310580ceea3f04d17`,
  `a223ef084014ca47dbbb2202bb2f82ba3b93fe07`,
  `68021953bcd85b45e56405ec5a68d96d0fcdab2a`,
  `15cf6d761a4ec8a379853791c1c4c28e8696684b`.
- Version: `0.10.0-beta.96` unchanged. No merge to main, deploy, signing, new
  API route, flag default change, owner-key copying, budget increase or trading
  order. No new SQL migration: migrations remain 1–23 as the checkpoint left
  them. The owner Local on 8765 was not switched, not restarted and not read.

## Why

Part B of the review recommended a merge order and named the overlap that had
to be resolved into one state logic. Carrying that order out was the only way to
find out what the combined build actually does, and three of its defects existed
only there: they are invisible in either branch alone and invisible to a suite
that never starts the server.

## What changed

### Defects the running build revealed

`domain_gateway` dispatches the `automation` and `router` domains, and the
`automation_watch` worker phase, to a module called `mechanism_gateway`. That
module exists in no branch and in no worktree. On the merged build both
endpoints answered `500 {"error": "internal server error"}` with no code,
because the `ModuleNotFoundError` escaped the handler. The call sites are left
exactly as they are so the module drops in unchanged when its author lands it;
only the import is guarded, and it raises the project's own error type, which
the live layer already maps to a 409 carrying `mechanism_domain_unavailable`.
Writing that module remains backend work owned by GPT/Codex.

`live_backtests` derives `progress_pct` from the source status, so a report that
reached `done` but failed verification arrived carrying 100 while the projection
put it in `awaiting_review`; the page draws a progress element whenever the
number is present, so a completed bar sat under a card that says the work still
needs a check. Failed and cancelled rows drew one too. The single-task route
returned adapter rows unprojected, so the inspector rendered from `status` and
`stage` while the list rendered from `display_status`. `projected_task` is now
the one seam both paths go through: it re-derives nothing, it projects a row
that has no computed state yet and then makes progress agree with that state.

### Mechanisms, on the side where they are supposed to work

The automation capability is granted separately and is withheld even from the
owner. Only the negative half of that was asserted before, and only through the
permission resolver. The new scenario drives the real stack on a disposable data
root — the real owner row, workspace, capability override, feature flags, budget
check, durable job payload and Agent World records — and pins all three sides:
without a grant neither the human approval nor worker ingress is admitted; with
a live grant, the mechanism flag, an approved plan and budget head room the run
is admitted; after withdrawal the open worker handle, the next mechanism step
and a restarted worker replaying the same durable payload are all refused, while
the approval, its human author and the completed records stay readable through a
read-only handle. Restoring the grant resumes the same approved plan, so the
exclusion is not a blanket automation ban.

Every existing Router case ended at a denial or at shadow advice. The new one
prices two connected candidates, has the caller arrive on the expensive one, and
runs the task through normal ingress at the model the active decision points to:
the provider call lands on the routed model. Shadow mode over identical evidence
keeps the caller where it was, which is what separates having an opinion from
changing the outcome.

Every existing scheduler case advances the occurrence with an explicit tick. The
new one never calls it: the ordinary recovery scan finds the due controller, the
existing worker claims and executes it, and the collected result is what the
next scan reports — one provider call, the accepted manual source untouched and
still not automated, and a drained queue that cannot produce a second run.

The application path was pinned for a source that reports `failed` and for one
that reports `done` with an intact report. Three kinds of damage to a real
terminal folder now cover the case in between, and each records a deviation
instead of completing on the strength of the request having been a backtest.

### Inherited failures and ported tests

The 30 failures the checkpoint carried were reproduced at `f9b94445` before the
merge, so none of them is attributable to it. Two were real: the mechanism
config parser kept the last value for a repeated JSON key, and the compatibility
agent row could not answer the availability and occupancy questions every other
agent card answers. The 21 residual mechanism flag tests were ported, expanding
to 73 cases with a provenance header recording the source file's sha256, and
exposed three further enforcement gaps — a caller-supplied flag snapshot that
survived a revocation, `ai_automation` granted by loop in the local-owner
bootstrap, and the duplicate-key parse above.

### PostgreSQL

`deploy/testing/provision-disposable-agent-world-postgres.py` brings up a
throwaway TLS cluster from the official Windows zip: its own directory, its own
free loopback port, no Windows service, no elevation, and no change to PATH,
firewall or any existing PostgreSQL configuration. Passwords are generated per
run into a git-ignored env file; nothing prints a secret and no DSN is
committed. The administrative role only creates and drops the throwaway
database; the suite connects as an application role created `NOSUPERUSER
NOCREATEDB NOBYPASSRLS`. Result: **69 passed**, migrations 1–23 applied,
`migration_set_sha256
3e5a1ccf5c1e1fa75ef9ba66e8e9926ceebc3aac97adc7bea470c3f534ee38e3`. No ALLOW
gate, DSN restriction or database protection was weakened to get there.

## Verification

Full detail, with the browser evidence and the four separated statuses, is in
Part C of `docs/current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md`.

## Not done

Merge to main; any change to PR #282, #283, #284 or their bases; any push to a
Codex branch; force push; switching or restarting Local 8765; Canary or
Production deployment; running any instance with
`STRATFORGE_AGENT_WORLD_STORAGE=postgres`; adapter verification against a real
NinjaTrader or a real Desktop capture; re-pinning the external GPT context
pack's verification SHA; installing Docker or Podman; using an owner, Canary or
Production DSN, credential or cookie; any real provider call, paid call or
trading order.
