# 2026-10-02 — API admission recovery and beta.107 relational-erasure development

Status: operational recovery PASS; incident trigger UNKNOWN; beta.107 DEVELOPMENT IN PROGRESS. This record extends the current post-beta.106 task, not the closed beta.106 product release.

## Current incident and recovery

Both Canary and Production beta.106 returned HTTP 503 `api_admission_saturated` on public and backend `/live` and `/ready` while Supervisor reported the API processes RUNNING. Canary had 24/24 HTTP admission slots occupied (4,734 accepted, 4,710 completed, at least 954 rejected); Production had 48/48 (27,689 accepted, 26,037 completed, 1,604 completed/promoted WebSockets, at least 886 rejected). The accounting identity `accepted - completed HTTP - completed WebSocket = active` held in both environments: this was occupied handler capacity, not a demonstrated semaphore leak. Canary had 22 backend `CLOSE-WAIT` sockets; Production had 41. PostgreSQL latency was below 13 ms with no waiting locks; worker, command and Telegram outbox queues had no active work. The specific route/stack that held the HTTP handlers cannot be established from the available pre-restart telemetry; do not attribute it to a provider, database, or particular endpoint without evidence.

The exact pre-restart API log prefixes were saved under restricted server backup path `/home/stratforge/production_data/backups/incident-api-saturation-20261002T1543Z/`. Their SHA256 checksums are Canary `7857d945af1cf03ba9ae559cf4615eb5df3f123347116c90a559c7d96bd898dc` and Production `181dddbc50adc1ab7f706feff751de8c88331c3201768e225e1e8e0cbecc22c2`. Logs remain outside Git and release artifacts.

Only Canary API was restarted first (PID 3637907 → 1102104); after five minutes it had `/live` and `/ready` 200, 0/24 active, no new rejections. Only Production API was then restarted (PID 1430432 → 1113900); after five minutes it had `/live` and `/ready` 200, 0/48 active, no new rejections. A later observation at 2026-10-02T17:02Z showed Canary 168 accepted/168 completed HTTP, no rejections; Production 380 accepted/300 completed HTTP/79 completed WebSocket/1 active WebSocket, no rejections. Database and operational queues remained healthy. Browser read-only smoke showed the existing Chrome non-owner Production profile and Edge owner Social/Chat/AI Center pages. No provider/report request was replayed. API restarts are recovery, not a root-cause code fix.

Both environments stayed on `0.10.0-beta.106`, source `e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885`, artifact `art_7aebf504ae354ce7981c58359a1ff546`, manifest SHA256 `0579C9C3FFD089EC91426D6F75B4E7ED257C612D9FBDD1F958561A50BEB0929C`. Production remains the sole operational Telegram sender; Canary remains non-sender; Windows `StratForge Vitek` remains Disabled. The historical 7/7 beta.106 acceptance is unchanged. Sustained `active=max_inflight` plus rising `rejected` must trigger route/thread capture before a guarded API-only restart; increasing capacity is not a fix. Until a captured stack/route or reproducible failure identifies the trigger, incident root cause and permanent prevention are unverified.

## Source checkpoint and next development stage

PR #313, a Local/documentation infrastructure checkpoint, passed all five required checks (Static, Ubuntu, Windows self-hosted, Python, bridge build) at head `67db21d569c533c6b1e33cbb7126f18135602320` and merged as `main` `bfc26c962bf3456cb1f811c421156245240ad1ac`. It did not change Canary/Production or complete the lifecycle task. A clean new branch `codex/beta107-relational-account-erasure` begins at that merged `main` for PostgreSQL account erasure and its tests. No beta.107 artifact or deployment exists yet. The current Timeline card stays `In progress`; Local post-reboot acceptance and real Chrome account delete/re-register are still pending.

## beta.107 Development checkpoint (2026-10-02T18:44Z)

The unmerged beta.107 branch now has PostgreSQL migration 0025 and a scoped,
two-phase server erasure adapter. Phase one blocks the account, revokes sessions
and active owner-model sharing. Phase two, in one PostgreSQL transaction,
removes exact private auth/workspace/entitlement/connector/Social/SF Chat and
Agent World rows, retains a minimal receipt, revokes identity history and
anonymizes historical usage/model-call display names. Referenced object files
are removed only after a durable database cleanup manifest commits. The
existing self-delete OTP/session/confirmation and `users.manage` owner-delete
admission remain in front of the adapter. Owner, service and shared-workspace
deletes fail closed. Late provider usage retains cost without resurrecting a
deleted identity; re-registration cannot reuse a deleted compatibility ID.

Disposable loopback TLS PostgreSQL with application role `NOSUPERUSER
NOBYPASSRLS` applied migrations 0001–0025 from scratch; six focused
real-database erasure cases and five pure-plan cases passed. The cases cover
transaction rollback/retry, foreign-user preservation, private Agent World
records/artifacts and BYOK ciphertext deletion, share revocation, historical
and late usage, identity-history retention, owned private documents, file
manifest cleanup, active live-control lease refusal and released Google
subject re-linking. The existing Device Trust/Agent World run yielded 138 PASS
and one pre-existing test-scope failure: its BYOK ciphertext assertion used a
global RLS scope, which is never allowed to see owner ciphertext. The test
was changed to the owner scope; its focused rerun passed. This was a test
correction, not a runtime/security relaxation. The full affected regression
suite and pre-release bundle checks still need a final rerun after the branch
is complete. No real account was deleted; no grant, server schema or artifact
was changed. Canary and Production remain beta.106.

## beta.107 Development PR checkpoint (2026-10-02)

The scoped branch was committed at `7979e32b1175d4730cd20e71a5c954206645027a`
and opened as PR #314. The final affected suite passed 170/170 against a
fresh disposable TLS PostgreSQL schema 25 and a `NOBYPASSRLS` application
role. `pre_release_check.py`, Context Pack validation and documentation-sync
validation passed. Legacy per-user orchestrator scopes were included in the
durable exact-object cleanup plan; the test proves another user's scope
survives. Git worktree was clean after commit. Required PR CI is pending;
no merge, beta.107 artifact, Canary/Production schema change or real-account
delete has occurred. The saturation trigger remains UNKNOWN despite both
environments' current public `/live` and `/ready` returning 200.

## PR #314 Windows CI queue diagnosis (2026-10-02T19:24Z)

The current PR head is `141dc2adeaec07618f1c878f74f2df4d6d42c67a`;
Static gates passed. The repository's only Windows runner (ID 21,
`stratforge-dev-DIMONCHECK`) is GitHub `online/busy`, and its Automatic Windows
service is Running with live Listener/Worker processes. It is running the
previous head `7979e32b` `python-tests` job `110989526878`, specifically its
full pytest step. Earlier setup, checkout, toolchain, dependencies and release
runner steps succeeded. The current-head Windows jobs are merely queued with
no runner assigned. No code failure, runner disconnect or service-start defect
is evidenced; no service restart, job rerun or application change was made.
Runner-local `_diag` access was denied, so no log contents were claimed. The
safe action is to let the active job finish and evaluate only the final-head
checks when the runner takes them.

## PR #314 full-CI failure classification (2026-10-02T20:20Z)

On head `57d5dfac253714f55cfc3a664e0ab845fb12d8ba`, Static and bridge
checks passed. Ubuntu completed full pytest with 25 failures, 6131 passes and
144 skips. This is a test/code-contract failure, distinct from the healthy
single Windows runner's queue. The failures comprise 21 mocked Production
tests trying to read the new authoritative PostgreSQL deletion receipt
without a configured DSN, two Local deletion tests missing explicit Local
context, one reverse-layer import and one stale 24-migration assertion. The
server receipt path remains fail-closed; the correction changes only test
contexts/stubs, the import to the existing production-storage core helper,
and the expected migration count to 25. Exact formerly failing cases pass
25/25 locally; all eight affected test files pass 382/382. Windows job is
still running full pytest on the superseded head, with another queued behind
the same `online/busy` runner. No runner service restart, code workaround for
queue contention, merge, artifact or deployment has occurred. This change
awaits commit and new required CI on its own final PR head.

## PR #314 merge / final-main CI checkpoint (2026-10-02T22:55Z)

The narrow correction was committed as
`6194ef0d247651c34729add32debcead9d2bc102` and passed all five required
PR checks. The two Windows full suites executed sequentially on the single
healthy `windows-self-hosted` runner; `python-tests` passed 6153 cases with
147 skips, and `Tests (windows-self-hosted)` passed after ~70 minutes. The
runner was never restarted; queued jobs were not misclassified as code
failures. PR #314 merged into exact `main`
`5e69165c8bc33dabdd9746059f3706ba8b92859b` at 22:54Z. Required
final-main `ci` run `37074945281` is in progress: bridge passed, Python
tests active. No beta.107 artifact, migration or environment deployment yet.
