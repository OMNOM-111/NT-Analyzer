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

Pending review, queued/claimed delegation execution and resume retain their existing
authority checks. New commission now uses the existing automation subject/entitlement check
before creating work and again immediately before its root dispatch. No flags are enabled,
grants extended, credentials copied or new features added.
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

First correction `e1d5d24d74622e00d8ac26e9f49a1354e14b3008` is a failed gate, not a final candidate:
focused `.artifacts/aw-final-1-focused.xml` = 46 passed / 1 failed; CI `34833248985`
= Static PASS, Ubuntu 5801 passed / 1 failed / 128 skipped, Windows cancelled.
The failing new test exposed dynamic transport capabilities in SF Chat's exact envelope
comparison. PostgreSQL on that SHA separately passed 70 + 41 + 18 = 129, no skips,
under `.artifacts/pg-runtime-acceptance-aw-final-1-tls/`; this does not override the failure.

The follow-up excludes only transport `scope.capabilities` from historical envelope matching.
Every other identity/session field and the entire result/evidence remain exact-match guarded;
delivery uses freshly authorized scope, never the envelope's obsolete capability snapshot.
The second local run (`withdrawal-v2`) reached the final refusal assertion, finding that a
new Coordinator commission still started its normal-model root without automation entitlement
(1 passed / 1 failed). The follow-up binds new commission to the existing automation policy;
ordinary non-Coordinator model tasks are unchanged. Neither failed run is hidden or counted as PASS.
Focused withdrawal tests: `.artifacts/aw-final-1-withdrawal-v3.xml` / `.log`:
**2 passed, 0 failed, 0 skipped**, 294.97 seconds. Bundle: 612 files, all four gates PASS;
Python syntax, repository static CSP/secrets/Markdown, Context Pack and diff checks PASS.
Coverage includes immutable Evaluation/result after withdrawal, current capabilities denied,
foreign workspace/user/session and result forgery refused, denied next commission, denied
claimed-worker resume, and no new Task IDs. Grant/flag loss remains distinct from source drift.

Next: finalize focused result; static/context/bundle; exact commit; full workflow_dispatch CI;
fresh disposable PostgreSQL gate; isolated new-SHA browser lifecycle. Do not inherit old PASS.
IMPLEMENTATION COMPLETE: pending verification. GIT CLOSEOUT COMPLETE: no. STAGE CLOSED: no.
