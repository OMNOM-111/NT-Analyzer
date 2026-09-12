# PostgreSQL acceptance — immutable 376b400d

Verification only, 2026-09-08. Source
`376b400dc3c8ab3a008f1e45800d401dd02c4b6f`, branch
`codex/agent-world-unified-acceptance`, draft PR #285. No new release,
owner acceptance, Local 8765 migration or deployment.

New disposable cluster used PostgreSQL 16.4, loopback port 64668, database
`aw_disposable_4a740afdbd7c`, TLS required and ordinary `stratforge_app`
NOSUPERUSER/NOBYPASSRLS role. Credentials, certificates, cluster and runtime
data stay ignored under `.artifacts/pg-runtime-acceptance-shared-20260908`.
No existing owner DB or earlier receipt cluster was copied or changed.

- Agent World suite: **69 PASS / 0 SKIP**, 59.23 s.
- Existing PostgreSQL suites: **41 PASS / 0 SKIP**, 100.44 s:
  storage 12, workers 12, SF Chat 9, Stage 8 eight.
- `suite-evidence.json` SHA256:
  `3c33b3e3a74bf85237bf60dff319b535edb400ea85482f04f597728cf3dc9ba4`.
- Migrations 1–23, pending `[]`; migration-set SHA256:
  `3e5a1ccf5c1e1fa75ef9ba66e8e9926ceebc3aac97adc7bea470c3f534ee38e3`.

Separate runtime **PASS**: real API -> spawned existing worker -> SQL-backed
synthetic response -> server restart -> persisted pending human review and RLS.
Task `6726831b-8c98-5b38-af68-6e1f294074f6`, 20 domain records, two model jobs
succeeded once. The named test executor made **zero external model calls**.
This proves infrastructure behavior, not model quality or real backtesting.

The source was clean and application-tree hashes matched before/after:
`3965274ac48999bd9492e6e6697c76a1504e65ef66107f2fa8c51cdcdf793365`.
`runtime-state.json` SHA256:
`5e1ff5efb0a8d4876cc816e1788f77437b9a806ec17b2582f88bded68f586a65`.
Only harness-owned server/worker processes on 8805 were stopped.

Ten FORCE RLS tables; foreign workspace/environment and empty scope see zero.
A second principal in the *same workspace* legitimately sees the 20 shared
headers and their 65 revisions, but zero private rows, events, artifacts,
inbox/outbox or mutations. Foreign insertion returns SQLSTATE 42501. Shared
headers are not mislabeled as a private-data leak or claimed invisible.

The generic immutable full376 suite separately skipped 68 Agent World PG,
41 legacy PG and three platform cases without DSNs. Those skips remain skips;
this record supplies its own actual PG evidence. Seven **later** Persona
identity/concurrency tests were not in 376 and are still awaiting their new
disposable run. Subsequent source changes invalidate reuse of this runtime
receipt as final-code acceptance. Protected Local remains 2b6d0112 / beta.96.
