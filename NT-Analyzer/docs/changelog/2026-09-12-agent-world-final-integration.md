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
- Memory context scopes are orthogonal to existing private/shared/lifecycle
  classes. Explicit session, project, governance and operational bindings do not
  grant visibility or instruction authority; legacy records retain their policy.
- Named Development Court votes retain one actual local failure domain. Critical
  diversity checks still deny them; advisory votes are clearly diagnostic.
- Explicit synthetic Social publication preserves diagnostic provenance without
  turning local arithmetic checks into professional or market performance.
- An ordinary explicitly addressed SF Chat request now continues through the
  existing semantic Coordinator form, retaining its owned original message.
- Scheduling starts from an accepted Routine/Calendar revision and still needs
  separate approval. Court evidence pickers receive the validated artifact MIME.
- QA impersonation confirms inside the application; drawers respect the actual
  test-banner height rather than hiding their close button beneath it.
- Shared task cards and manual review include native external-agent tasks using
  their actual typed subject. Received results and completed reviews stay distinct.
- External SF Chat delivery retries the saved receipt, not the provider call.
- Schedule approval is pinned to the plan shown to the user; stale configuration
  or source consent is refused before granting automation authority.
- Restarting the disposable QA launcher preserves subsequent permission
  revocations. Connection metadata uses actual revisions and Persona names;
  technical workspace/verifier codes stay in accessible collapsed details.
- External history and task views use the same human-review state, distinguish
  verified output from pending acceptance, and retain unknown historical costs.
  PostgreSQL worker tests share the actual isolated SF Chat paths across spawn
  and verify persisted delivery, rather than substituting a fake source message.

## Verification boundary

New final-SHA full regression, legacy runner, bundle/static/context, CI and
browser evidence remain pending. Interim evidence is recorded in the canonical
developer-only `docs/current/AGENT_WORLD_MASTER_STATUS.md`; it does not close the
programme. Historical P1-5 CI 34678502093 belongs to `c16b511d` only.

At candidate `d7b480604871c9744e425185375a579240d6bd17`, real PostgreSQL was
129/0/0, legacy runner 13/13, bundle/static/context PASS. CI `34703741359` Linux
was 5745 passed / 1 failed / 128 skipped: an older security scenario omitted the
new explicit clarification step. The corrected scenario retains its authority
and session-expiry assertions. Final rerun is required; this is not release PASS.
The Windows job reached its unchanged 120-minute limit and was cancelled;
interrupted tests are not counted as PASS. Follow-up scoped and synthetic chain
results are recorded separately in Master Status.

Release impact: version `0.10.0-beta.96` unchanged; no signed artifact, Canary or
Production publication. Rollback of testing is stopping only the new acceptance
process; source histories and existing Local data remain untouched.
