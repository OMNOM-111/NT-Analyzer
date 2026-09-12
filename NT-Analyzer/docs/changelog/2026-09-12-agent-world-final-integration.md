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

### Saved candidate a091ce67

Exact source: `a091ce6794da75064a9012dfe97d50bfc140e978`, draft PR #287.
Disposable PostgreSQL: **129 PASS / 0 FAIL / 0 ERROR / 0 SKIP** — **88** Agent
World/External/Persona, **29** legacy storage/chat, **12** workers. The three
`a091ce67-*-postgres.xml` receipts are retained in
`.artifacts/pg-runtime-acceptance-final-p15/`. Legacy runner: **13/13 PASS**.
Repository static/context/diff and **610-file production-bundle checks PASS**.
CI **34714150028 Linux: 5776 passed / 4 failed / 128 skipped**, 1480.45 s;
Windows is still running on this exact source and this same PC. Three stale
fixtures were corrected in follow-up work; **17 scoped cases + 1 aggregate case
PASS**, not a new full-suite PASS or a rewrite of the four failed CI cases.
A competing heavy local regression is not started. Final browser and
full-regression acceptance remain open. Earlier 51924538 fixture failure and
its corrected separate run remain historical evidence in Master Status.

Pre-final QA8815 browser evidence includes ordinary-user synthetic Court
2-of-3/dissent with three sessions and no execution, explicit Only-me synthetic
Social publication, and a private Memory revoke at revision 3 after prior
foreign-user denial. Exact record/snapshot identities are in Master Status.
These observations are not immutable-final-SHA UI acceptance: a091ce67 backend
can serve changed static files. QA device guard denial is expected; separate
test email/device setup requires owner approval, not a security bypass.

Published 95% / 70% remain provisional: final 36-row reconciliation is pending,
including the existing E2E-column arithmetic discrepancy (17 Y + 16 P + 3 N
gives 25 / 36 under the unchanged weights, not the printed 25.5 / 36). No new
percentage or methodology is introduced. The current click-through guide is
`docs/current/OWNER_ACCEPTANCE_GUIDE.md`; the older Agent World guide now points
there while retaining its historical observations.

### Earlier candidate verification history

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
