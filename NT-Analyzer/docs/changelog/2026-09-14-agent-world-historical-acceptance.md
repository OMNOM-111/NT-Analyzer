# AW-FINAL-1 — accepted history survives later automation withdrawal

Status: CLOSED on code `2debb2d62ab1af9cba4da2e8d9bbaee9832316d2` (independent verification, 2026-09-14).
Development-only correction, not a release. Branch: `codex/agent-world-final-acceptance`, PR #287.
Base: `d3b179dc` over candidate `09c4e859c1bc950c703feaddf3094300978bb0e4`.

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

## Development history of the correction

First correction `e1d5d24d74622e00d8ac26e9f49a1354e14b3008` is a failed gate, not a final candidate:
focused `.artifacts/aw-final-1-focused.xml` = 46 passed / 1 failed; CI `34833248985`
= Static PASS, Ubuntu 5801 passed / 1 failed / 128 skipped, Windows cancelled.
The failing new test exposed dynamic transport capabilities in SF Chat's exact envelope
comparison. PostgreSQL on that SHA separately passed 70 + 41 + 18 = 129, no skips,
under `.artifacts/pg-runtime-acceptance-aw-final-1-tls/`; this does not override the failure.

The follow-up excludes only transport `scope.capabilities` from historical envelope matching.
Every other identity/session field and the entire result/evidence remain exact-match guarded;
delivery uses freshly authorized scope, never the envelope's obsolete capability snapshot.
The second local run (`withdrawal-v2`) found that a new Coordinator commission still started its
normal-model root without automation entitlement (1 passed / 1 failed); the follow-up binds new
commission to the existing automation policy. Focused withdrawal tests
`.artifacts/aw-final-1-withdrawal-v3.xml`: 2 passed, 0 failed, 0 skipped, 294.97 s.

## Final verification on `2debb2d6` (takeover after the previous executor stopped)

State taken over: HEAD = origin = `2debb2d6`, tree clean, no stash; the acceptance build on
:8818 served `2debb2d6` with `dirty=false` and held only fixtures. Nothing was inherited as PASS.

- CI `34863855186`: Static PASS; Ubuntu **5802 passed / 0 failed / 128 skipped**; Windows attempt 1
  cancelled by the 120-minute job limit at 42% with 0 failures while this machine also ran the gates
  below; Windows attempt 3 5799 passed / 0 failed / 131 skipped, 1:54:34 (attempts 1-2 cancelled at the 120-minute job limit under shared-host load with 0 failures; not counted).
- PostgreSQL, fresh TLS disposable cluster (`.artifacts/pg-runtime-acceptance-2debb2d6`,
  NOSUPERUSER/NOBYPASSRLS): agent-world 70 + legacy 41 + external/Persona 18 =
  **129 passed / 0 failed / 0 skipped**; runtime PASS (10 FORCE RLS tables, foreign insert `42501`,
  foreign/empty/other-environment scopes read 0, restart and replay, no SQLite fallback).
- Browser, isolated :8818 (loopback network guard, zero external calls), evidence in
  `.artifacts/owner-acceptance-final-2debb2d6-evidence`: guide **15/15 PASS**.
- AW-FINAL-1 lifecycle, 20/20 checks: grant -> SF Chat «Координатор» -> commission -> plan ->
  approve -> graph `5749de2f` -> root and 3 nodes accepted -> aggregate accepted 17:18:29Z ->
  SF Chat result delivered -> withdraw 17:36:05Z -> the same graph reads «Проверка завершена»,
  review `accepted`, source hash `78d7a9be…c1af524`, Evaluation `492f070c` rev 1, completion event
  `0e726df7…` and SF Chat result message unchanged; current authority `automation_entitlement_required`.
  New commission 403 (API and page), approval of a pending commission 403, reconcile 403, no new
  records; after the full walk a new schedule 403, a pending scheduled occurrence never ran, new
  commission 403 again. Pair: `part2/aw-pair.png`.
- Probe with the application's own functions: 15/15 at withdraw time; after the full walk 15/15 with
  the authority reason `automation_approval_expired` (the grant had expired and expiry is checked
  before entitlement — both deny). 16 forged SF Chat envelopes refused.
- Walker defects (scripts only): short chat/page waits and one unchecked form confirmation; recaptures
  recorded with the originals kept. One interrupted walker's commission and graph were cancelled through
  the product's cancel action before the clean walk.
- Docs-tree gates on this branch: repository static scan CSP/SECRETS/MARKDOWN PASS; Context Pack PASS; compileall PASS; git diff --check PASS; pre-release bundle 612 files, 4/4 gates PASS.

IMPLEMENTATION COMPLETE: yes. Implementation 94% (no credit for fixing an existing defect);
readiness 80% (Delegation E2E P->Y). Owner-dependent items remain open, none closed artificially.
Local 8765 (PID 21060, `2b6d0112`), main, Canary, Production and Production DB were not touched.
