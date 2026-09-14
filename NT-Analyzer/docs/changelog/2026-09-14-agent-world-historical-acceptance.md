# AW-FINAL-1 — accepted history survives later automation withdrawal

Status: IN DEVELOPMENT. Development-only correction, not a release or owner acceptance.
Branch: `codex/agent-world-final-acceptance`, PR #287. Base: `d3b179dc` over candidate
`09c4e859c1bc950c703feaddf3094300978bb0e4`. Final code/receipt SHAs and gate results follow after verification.

## Change and boundary

The aggregate human-review snapshot mixed current execution authority with historical
evidence. Withdrawing `ai_automation` changed its hash, making an already accepted graph
look blocked/stale. The independent browser read on port 8816 reproduced that contradiction:
the aggregate was paused while the root and all three required reviews remained accepted.

The correction validates the original complete immutable receipt, then compares historical
evidence separately from its authority snapshot. Later authority loss does not change the
recorded acceptance/hash. Current authority is separately available in the graph read model;
it is not serialized into the immutable SF Chat completion envelope. Actual result, source,
lineage, cancellation or review drift remains stale. No records are rewritten or deleted.

Pending review, new commission, queued/claimed execution and resume retain their existing
authority checks. No flags are enabled, grants extended, credentials copied or new features added.
Local 8765, candidate-2 data, main, Canary and Production are untouched. Version stays beta.96.
Rollback is the previous source `d3b179dc`; no database migration is involved.

## Independent audit of candidate 2 (historical, not new-code gates)

- CI `34788775463` head exactly `09c4e859`: Ubuntu 5800 passed / 128 skipped;
  Windows 5797 passed / 131 skipped; Static passed. Counts read from GitHub job logs.
- PostgreSQL XML: 70 Agent World + 18 external/Persona + 41 legacy = 129 passed,
  no failures/errors/skips. Stored under `.artifacts/pg-runtime-acceptance-final-candidate-2/`.
- The claimed 15/15 browser guide is scenario coverage, not unconditional acceptance:
  AW-FINAL-1 remains in its own findings; real BYOK, real registration, provider diversity,
  audible voice and full visual design are explicitly unverified/owner-dependent.
- Implementation remains 34/36 = 94%; readiness remains the historical 28.5/36 = 79%
  while the new candidate's gates are pending. No implementation credit for this correction.

## New-code evidence and continuation

Focused tests: `.artifacts/aw-final-1-focused.xml` / `.log` (running; not yet PASS).
Includes accepted completed graph after capability withdrawal, unchanged immutable evaluation
and SF Chat envelope, denied next commission, denied claimed-worker resume, and no new Task IDs.
Grant/flag withdrawal is tested separately from actual source disconnect/cancellation.

Next: finalize focused result; static/context/bundle; exact commit; full workflow_dispatch CI;
fresh disposable PostgreSQL gate; isolated new-SHA browser lifecycle. Do not inherit old PASS.
IMPLEMENTATION COMPLETE: pending verification. GIT CLOSEOUT COMPLETE: no. STAGE CLOSED: no.
