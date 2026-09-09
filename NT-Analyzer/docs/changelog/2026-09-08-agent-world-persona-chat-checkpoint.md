# Persona chat and response-only checkpoint

Status: **IN DEVELOPMENT**. Branch `codex/agent-world-unified-acceptance`,
draft [PR #285](https://github.com/OMNOM-111/NT-Analyzer/pull/285).
Source baseline: `376b400dc3c8ab3a008f1e45800d401dd02c4b6f`.
This record belongs to the following code checkpoint; its exact SHA is recorded
at preservation in the handoff. It is not a release or owner acceptance.

## Change summary

Selected Persona UUID now travels independently of the legacy role through the
existing HTTP, durable worker and SF Chat ingress. Names, aliases and main
assistant selection resolve to existing scoped profiles; exact revision is
pinned at task construction and rechecked before provider transmission. No
binding, ambiguity, revision change or refusal silently selects owner credentials
or another agent. Existing queued request IDs cannot replace a selected identity
or its original message. History and old profiles remain unchanged.

`assistant_response` is a bounded one-off text request over the existing model
worker (up to 4,000 input characters and existing 512 output-token limit).
Its verifier confirms text delivery only: `quality_claim=false`,
`semantic_verified=false`, `observed_score_pct=null`, mandatory separate human
review. Even forged/self-awarded scores in this class cannot affect reputation.
It cannot enter Router, delegation, comparison, Court or autonomous scheduling.
It supplies no tools, browser, private history or permission to publish/trade.
Native chart/backtest requests still use their existing explicit adapter.

Private connections expose `chat_completions_v1` and read-only capabilities:
text, not remote tools/tasks, MCP, A2A or artifact execution. Unsupported protocol
values fail before credential storage/transmission. Existing owner registry
bindings retain their existing transport; no keys are copied. The separate
Development test executor produces an explicitly SYNTHETIC echo, never a real
answer or model-quality observation.

User-facing Persona selection, preserved avatar/voice and the reused drawer's
accessible name are described in the [Persona identity record](2026-09-08-agent-world-persona-identity.md).
Shared API/UI script query versions are refreshed mechanically across the same
15 Aurora entry pages; page composition and product version are unchanged.

## Exact baseline evidence and later checks

- Immutable `376b400d`: **5262 PASS / 1 FAIL / 112 SKIP**, 3816.60 s.
  Legacy runner **13/13 PASS**, 61.96 s. Report under the detached regression
  worktree's `.artifacts/qa-376b400d/REPORT.md`, SHA256
  `8bb557ec1f96c8ba873ef01611286fb85ff897e6eca1944331b4e92bf95a84a2`.
- Its sole failure was a stale cancel-observability unit call missing the now
  required authenticated `command`. This checkpoint supplies that argument and
  asserts binding-verifier invocation. The production guard remains strict;
  the complete real loopback cancel-dispatch test still runs separately.
- Later scoped response/Persona worker tests: **58 PASS**, 11.63 s. Explicit
  synthetic worker -> saved ordinary-user SF Chat message -> response -> pending
  review -> idempotent replay, plus revision changes and refusal without fallback.
- HTTP/queue/Chief and existing review-boundary regressions: **154 PASS**,
  28.64 s. Combined model/identity/worker checks: **200 PASS**, 62.65 s.
- Corrected cancel observability, trusted Connector HTTP and Persona execution:
  **67 PASS**, 17.78 s. These focused suites overlap; they are not a full total.
- New seven Persona PostgreSQL cases were skipped without explicit disposable
  opt-in. They require a new real run, separate from previous PG PASS receipts.
- Full immutable regression, fresh PostgreSQL and browser on this new checkpoint
  are pending. Local Python compilation and whitespace checks passed before
  preservation; final artifact/static/context results are recorded at closeout.
- Final bounded combined rerun: **329 PASS**, 46.11 s, including Aurora/cache,
  Persona, actual handler, Chat/worker, response-only and cancel-observability
  contracts. The first rerun exposed an old pinned cache-query expectation;
  both cache tests now require the new exact shared version (not a weakened
  arbitrary-version match). Root static scan CSP/SECRETS/MARKDOWN PASS,
  External GPT Context validator PASS with the historical deployment-anchor
  warning, staged diff-check PASS, **593-file pre-release bundle PASS**
  (static scan, runtime reads, Python and shipped JavaScript).

## Isolation and rollback

Protected Local 8765 remains `2b6d0112bef88c5bfb73970de64ec5518443e56b`.
Only isolated 8804 was moved to immutable `376b400d`, with a cold backup of its
41 synthetic data files and matching SHA256 checks. This is not an owner Local
backup or authorization to activate this code. No source/DB migration is needed
to return isolated QA to the previous checkpoint; never delete new data/history.

No paid/model/TTS calls, real registration consent, owner-key copying, permanent
real Social publication, protected flag change, merge, release or deploy.
Actual provider quality, real data results and owner design acceptance remain
separate. Next: preserve exact source, run immutable regression + fresh PG,
then finish the full-Aurora browser route and update the canonical program matrix.
