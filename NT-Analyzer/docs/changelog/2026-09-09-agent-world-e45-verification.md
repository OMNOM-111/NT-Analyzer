# Agent World — exact e45 regression and PostgreSQL evidence

Program status: **IN DEVELOPMENT**. This is a verification receipt, not owner
acceptance or a release. Branch `codex/agent-world-unified-acceptance`, draft
[PR #285](https://github.com/OMNOM-111/NT-Analyzer/pull/285).
Executable source: `e45b64b0121014c5d796553ae8b512d98a5782ae` (beta.96).
The [Persona checkpoint](2026-09-08-agent-world-persona-chat-checkpoint.md)
describes its changes. This record certifies only that exact source; it neither
certifies the subsequent executable delta recorded alongside it, relabels an
older failing checkpoint nor authorizes activation.

## Full regression, immutable clean source

The detached `agent-world-regression-e45b64b0` worktree reports:

- `python -m pytest -q -ra -p no:cacheprovider`: **5416 PASS / 119 SKIP /
  0 FAIL / 0 ERROR**, 5834.82 s. JUnit has 5535 cases, 5831.988 s; wrapper
  elapsed time is 5844.7944003 s. These are distinct timing measurements.
- Started `2026-09-09T02:12:43.8215451Z`, finished
  `2026-09-09T03:50:08.9422949Z`.
- Legacy `python -m tests`: **13/13 suites PASS**, 183.0977726 s.
- Both receipts record exact e45 before/after, empty tracked/untracked status,
  exit code 0 and `git diff --check` exit 0. The runner scrubbed configured
  credentials/runtime test overrides; test output remains outside Git.
- The 119 skips are **68 existing Agent World PostgreSQL**, **7 new Persona
  PostgreSQL**, **41 legacy PostgreSQL** (12 storage, 12 workers, 9 relational
  SF Chat, 8 Stage 8), and **3 platform cases**. The platform reasons are
  unavailable bash/shell for two shell syntax tests and POSIX permission bits
  for one secret-store test. They are not PASS in this Windows run.

Raw evidence is under the detached worktree's
`NT-Analyzer/.artifacts/qa-e45b64b0/`:

| File | SHA256 |
| --- | --- |
| pytest.log | `3411d7e82a59338502ef8c25b8c43d535879e8e4df7e627a642ed8debb8318b2` |
| pytest.xml | `708916a3c8fcedb29179aa77bc7688a0d74cd3811b0146bc6bdf983e1a61a738` |
| pytest-result.json | `f8a18b075b4597f6ca49a7499723629b300fa914f8bde28727c73e1b5f6f6f1f` |
| legacy.log | `956aafff953aa5b112e75a9c0e165b6e8049da3f5138a19a2655d1f112d71401` |
| legacy-result.json | `affb3a4ab2e9a309f0809af175123f287bd238fea8381479e4d6b5a92048acd5` |

## Fresh PostgreSQL suites — not inherited PASS

A separate clean `agent-world-postgres-e45b64b0` worktree provisioned a new
disposable PostgreSQL **16.4**, loopback port **56632**, database
`aw_disposable_eb7ae4aa6dbd`. TLS is on; application role `stratforge_app` has
neither SUPERUSER nor BYPASSRLS. Existing migration set 1–23 was applied only
to that empty disposable database, with no pending migrations. Set SHA256:
`3e5a1ccf5c1e1fa75ef9ba66e8e9926ceebc3aac97adc7bea470c3f534ee38e3`.

- Existing Agent World suite: **69 PASS / 0 SKIP**, 78.89 s.
- Legacy PostgreSQL suites: **41 PASS / 0 SKIP**, 132.36 s.
- New Persona identity PostgreSQL suite, run separately before runtime:
  **7 PASS / 0 SKIP**, 49.73 s.
- All three report zero failures/errors. App Python tree before/after:
  `bda995ce582f8183be0ea8812d92e709332716b9554e199d2c0424c3d18ec172`;
  source remains clean exact e45.

These supplement, but do not silently remove, the 116 database skips in the
generic full run. The 69-case suite contains one case that needs no live server.
The [376 PostgreSQL receipt](2026-09-08-agent-world-postgres-376-acceptance.md)
remains historical evidence for a different source and cluster.

## Actual PostgreSQL application runtime

Canonical harness `deploy/testing/agent-world-postgres-runtime-acceptance.py`
ran on isolated **8805**. It used authenticated API, the existing queue and a
real owned worker process, not direct insertion of a finished Task.

- **PASS**: create Persona/connection, diagnostic and bounded model task,
  actual worker result, SQL persistence, idempotent replay, stop/restart,
  read the same pending-review result and cross-scope refusals.
- Task `23086a0c-f893-5826-94d6-3cb3fedf5682`, workspace
  `ws_owner_training_2dba2dd8f4f2`, remains **awaiting_review** after restart.
- Receipt names `agent-world-local-test-executor-v1`, `synthetic=true`,
  `external_call=false`, **0 external calls**. This is not a provider-quality
  check, genuine owner registration, BYOK acceptance or human review.
- 20 PostgreSQL records, 65 revisions, one evaluation; two source jobs each
  succeeded with one attempt under worker `proc-16084` and the correct scope.
- Ten Agent World tables have FORCE RLS. Foreign workspace, environment and
  empty scope read zero records. Foreign insertion fails SQLSTATE `42501`.
- Another principal in the **same** workspace legitimately sees 20 shared
  headers and 65 revisions. Private artifacts/events/inbox/outbox/mutations
  remain unavailable; do not misreport workspace headers as private leakage.
- Agent World SQLite fallback is **false**. The already existing durable queue
  still uses its intended isolated SQLite store; that is not a second Agent
  World repository or a claim that every subsystem moved to PostgreSQL.
- Owned 8805 server/worker trees were stopped after verification; original
  test data and receipts retained. Protected 8765 and browser 8804 were untouched
  by the PostgreSQL worker.

Raw receipts in `agent-world-postgres-e45b64b0/NT-Analyzer/.artifacts/`
`pg-persona-acceptance-20260908/pg-runtime-acceptance-e45b64b0/`:

| File | SHA256 |
| --- | --- |
| suite-evidence.json | `33eea1cf92a284bab01500f180634555d94e335d1b602f931246980e76e962e5` |
| persona-identity-evidence.json | `d850553ae0f1ac7af6aa6f93543263a3b2ee61856bf3ba83b8007b8b800c6d8a` |
| runtime-state.json | `981ac6996b3307a57e3b1093c31b1357b7c1014c88111c2da0603b59307d7170` |

Never copy `acceptance.env`, database credentials or runtime stores into Git.

## Browser, Git and release boundary

The observed full Aurora 8804 used a separate immutable e45 checkout with retained synthetic
data; its pre-e45 41-file cold backup and matching hashes are preserved. The
browser has reopened Persona `b7f4bfff-50f9-55d5-85d7-d42b117d0aff` (Ариадна QA),
confirmed aliases/main-assistant/style/Marina face survived the restart, and
explicitly activated it (revision 2). A separate synthetic connection was
created in the UI with an obvious non-secret test placeholder; no owner key
was used. Its named-executor connection check completed. This is not a real
DeepSeek connection and does not close the ordinary-user BYOK gate.

The browser also exposed a reproducible presentation discrepancy: Work had
already loaded the completed diagnostic while the header retained the older
“1 в работе” count; the narrow stage cell wrapped words into single characters.
The executing/result/manual-review/error/retry route is therefore **not yet
accepted**. Preserve this evidence; subsequent corrections require their own
tests and exact-code browser repeat. No full relayout or plan rewrite is implied.

The same browser run's selected-Persona chat returned
`execution_v2_approved_scope_changed`. A regression test reproduced the
rejection with Execution V2 actually enabled; approved-request reconstruction
omitted the optional Persona identity. The subsequent fix preserves that field
in the digest and rejects changed/deleted selections. It is a separate change,
not a reason to alter the e45 full-run result or erase the failed attempt.

PR #285 was pushed at e45; its inspected check rollup was empty, **not CI PASS**.
No protected Local activation, migrations, real orders, external paid calls,
merge, release or deployment. Program matrix and next browser steps remain in
`docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md` (developer checkout only;
intentionally excluded from the production bundle, not a shipped hyperlink).
