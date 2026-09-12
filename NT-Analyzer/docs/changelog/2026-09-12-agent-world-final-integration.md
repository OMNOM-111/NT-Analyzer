# Agent World — unified final acceptance integration

Status: IN DEVELOPMENT. This is a task-branch change, not a release.

## Source and purpose

`codex/agent-world-final-acceptance` combines accepted P1-3 and P1-5 histories:
`9365695a` + `4d8ee514` → `334f086f`. No duplicate cherry-picks, history rewrite,
main merge or deployment. Local 8765 stays on its existing code/data.

The scope is a single testable Agent World programme, rather than separate
worktrees. Existing Persona/role/account/model/external connection records and
the shared typed Evaluation remain distinct.

## User-facing and security changes under verification

- Coordinator asks for the desired meaning using labelled choices before
  dispatch. The server binds the choice to goal, data, scope and connections;
  callers cannot submit arbitrary internal operations.
- An unstarted commitment can be superseded by a new request, with prior
  cancellation/history preserved rather than rewriting finalized Intent fields.
- Diagnostic process proposals and schedules retain synthetic provenance and
  require the existing explicit Development workspace opt-in. They do not become
  real-performance evidence or authorize a paid provider fallback.
- New live PostgreSQL tests cover an ordinary non-owner, storage/RLS, worker
  outcomes/Evaluation, restart and independent-process dispatch/revoke locking.
- A reusable isolated owner-acceptance launcher seeds only disposable QA users;
  network access is limited to loopback. No owner keys are copied.
- Controller Intent states follow actual running, waiting and terminal changes;
  old read-side discrepancies are exposed rather than rewritten or auto-accepted.
- The workflow's repository-wide static scan runs from the Git root, including
  tracked files above `NT-Analyzer`; the test jobs retain their 120-minute limit.

## Verification boundary

New final-SHA full regression, legacy runner, bundle/static/context, CI and
browser evidence remain pending. Interim evidence is recorded in the canonical
developer-only `docs/current/AGENT_WORLD_MASTER_STATUS.md`; it does not close the
programme. Historical P1-5 CI 34678502093 belongs to `c16b511d` only.

Release impact: version `0.10.0-beta.96` unchanged; no signed artifact, Canary or
Production publication. Rollback of testing is stopping only the new acceptance
process; source histories and existing Local data remain untouched.
