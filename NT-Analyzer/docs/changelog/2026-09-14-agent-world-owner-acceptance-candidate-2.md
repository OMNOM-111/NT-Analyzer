# Agent World — owner acceptance, candidate 2 (2026-09-14)

Receipt for the final automated gates and the owner-acceptance browser walk on one exact
candidate. The evidence files (screenshots, ledgers, logs) live in the ignored folder
`NT-Analyzer/.artifacts/owner-acceptance-final-09c4e859-evidence/` on the integration machine. This
receipt names them so an auditor can open each one.

## Identity

| Item | Value |
| --- | --- |
| Candidate SHA | `09c4e859c1bc950c703feaddf3094300978bb0e4` (docs-only freeze over `85828323`) |
| Branch | `codex/agent-world-final-acceptance` — nothing merged to `main`, no Canary or Production deploy |
| Acceptance build | http://127.0.0.1:8816/ui/ai-command-center.html — left running |
| Runtime identity | `/api/runtime/env`: `git_commit_sha` = candidate, `dirty` = false, build `dev-0.10.0-beta.96-09c4e859c1bc`; launcher `build_dirty` = 0 |
| Data root | `.artifacts/owner-acceptance-final-09c4e859` — disposable, loopback network guard, zero external calls |
| Rollback | Stop the launcher process (`agent-world-owner-acceptance.py --port 8816`) |
| Local 8765 | PID 21060 before and after the walk — untouched |

## Gates on this exact SHA

| Gate | Result |
| --- | --- |
| CI run 34788775463 (workflow_dispatch) | Static gates PASS · Tests ubuntu-latest PASS · Tests windows-self-hosted **5797 passed / 0 failed / 131 skipped**, 1:19:52 |
| Disposable PostgreSQL (`.artifacts/pg-runtime-acceptance-final-candidate-2`) | **129 passed / 0 failed / 0 skipped** (agent-world 70, external agent + Persona 18, legacy 41) + runtime run PASS (external calls 0, migrations at version 23) |
| Legacy runner | 13/13 suites |
| Static | CSP, secrets, Markdown PASS · Context Pack PASS · compileall PASS · JS syntax 24 files PASS · `git diff --check` PASS |
| Pre-release bundle | 610 files, PASS |
| Local full pytest | Intentionally stopped: superseded by the full green CI on the same SHA. The log reached 38% with 0 F/E markers. Not counted as PASS and not counted as failure. |

## Browser walk — OWNER_ACCEPTANCE_GUIDE, 15/15

Every row was walked in a real Chromium window (1600×1000) on the build above.

| # | Row | Result | Evidence (under `…-evidence/`) |
| --- | --- | --- | --- |
| 1 | Обзор | PASS | `part1/01-overview.png` |
| 2 | Persona и чат | PASS | `part1/02-personas.png`, `part1/03-chat-ambiguous-choice.png`, `part1/03-chat-after-explicit-choice.png` |
| 3 | Intent | PASS | `part2/04-chat-clarification-offered.png`, `part2/04-intent-clarification-form.png` |
| 4 | Координатор | PASS | `part2/05-plan-not-approved-no-child-runs.png` (supplement), `part2/05-coordinator-plan-awaiting-approval.png`, `part2/06-delegation-graph.png`, `part2/06-delegation-graph-completed-loaded.png` |
| 5 | Результат | PASS | `part2/07-result-in-sf-chat.png`, `part2/07-result-reviewed.png` |
| 6 | Проверка | PASS | `part2/07-result-reviewed.png`, `part2/07-result-in-sf-chat.png` |
| 7 | Репутация | PASS | `part2/08-reputation-scopes.png` |
| 8 | Court | PASS | `part2/09-court-votes.png` — 2-of-3, three sessions, execution not allowed, SYNTHETIC |
| 9 | Память | PASS | `part2/10-memory-owner.png`, `part2/10-memory-ordinary-user.png`, `part2/10-memory-revoked.png` |
| 10 | Автоматизация | PASS | `part2/11-routine-accepted-schedule-proposed.png`, `part2/11-schedule-occurrence.png`, `part2/11-scheduled-run-result-and-history.png`, `part2/11-schedule-revoked.png`, `part2/11-next-run-refused-after-revoke.png` |
| 11 | Внешний агент | PASS | `part2/12-external-agent-active-with-result.png`, `part2/12-external-agent-revoked.png` — next dispatch `409 external_agent_revoked` |
| 12 | Собственная модель | PASS | `part1/13-models.png`, `part1/13-task-selection-provenance.png`, `part1/13-connection-disconnected.png`, `part2/13-ordinary-user-connect-empty-key.png` |
| 13 | SF Social | PASS | `part2/14-social-synthetic-preview.png` — preview only, nothing stored or published |
| 14 | Owner Preview | PASS | `preview/14-*.png` (29): Telegram with QR, Google, e-mail/OTP; manual consent; Device Confirmation permanent and session; new client asked again; Reset; Exit restored the acceptance owner |
| 15 | System | PASS | `part2/15-system.png`, `part2/15-owner-preview-entry.png` |

Index files: `GUIDE_WALK.md`, `guide-index.json`, `guide-index.txt`. Ledgers: `part1/walk-ledger.json`,
`part2/walk-ledger.json`, `part2/plan-preview-supplement.json`, `preview/preview-registration.json`.
Identity: `runtime-identity.json`, `acceptance-metadata.json`, `local-8765.txt`.

### ai_automation

- **Granted:** to the disposable QA test owner 991881401 only, through the existing owner
  permission route, at 01:28:59Z.
- **Withdrawn:** at 02:06:54Z. No other grant was made on this build.
- **First scheduled run:** due 01:39:24; it produced a verified result that is awaiting review.
- **Revoke:** at 01:45:01, before the second due time (01:59:24). The second occurrence never got a
  task.
- **After the withdraw:** enabling a new schedule was refused with
  `403 automation_entitlement_required`.
- **Rehearsal builds:** 8830 and 8831 (now stopped) each granted and withdrew ai_automation for their
  own disposable QA owner while the walk scripts were being hardened. Disclosed; not counted as evidence.

## Findings

**AW-FINAL-1 · P2 · open, not fixed in this candidate.** After ai_automation is withdrawn, an
owner-accepted delegation graph reads as «Приостановлено: нужно решение» with no actions.

- Graph `2c187b5f` was accepted at 01:33:58Z; its record has not changed since.
- The read projection re-checks the automation grant, so the snapshot hash changes and
  `task_review.py:226` reports `stale` (`blocked_reason: automation_entitlement_required`).
- No execution and no data loss: the recorded decision and the results are kept.
- Fixing it needs a product decision and a new candidate. The Delegation row therefore stays P.

Walk-script defects, fixed in the scripts only, with no product code change:

- **Row 4, plan screenshot:** the original plan screenshot showed the root task. A supplement opened a
  new commission's plan preview without approving it. The API confirmed no delegation graph and no
  child tasks.
- **Row 4, completed graph:** that screenshot had caught the loading state. It was re-taken; the swap
  is recorded in the ledger and the placeholder is kept on disk.

Full notes: `FINDINGS.md` in the evidence folder.

## Recount (same 36-row method)

- **Implementation coverage:** 94% (34.0 / 36), unchanged.
- **Owner acceptance readiness:** 68% → 79% (24.5 → 28.5 / 36).
  - Rows moved: Coordinator, Memory, Process Intelligence, Routines, Scheduler, Owner Preview and
    Git/CI P→Y; UI/UX N→P.
  - Delegation stays P because of AW-FINAL-1.

## Remaining

- **OWNER ACTION REQUIRED:**
  - a real BYOK key;
  - audible voice/TTS;
  - real registration with real providers;
  - real multi-provider Court and Router credentials;
  - budget for a paid remote external agent;
  - a permanent SF Social publication;
  - the product decision on routing `assistant_response` (P1-MM, P1 PARTIAL).
- **P3:** visual taste and redesign; full mockup composition (eight sections behind three tabs).
- **Open finding:** AW-FINAL-1 (P2).
