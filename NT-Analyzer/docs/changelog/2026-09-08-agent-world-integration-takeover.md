# Agent World — preserved unified integration and remaining acceptance work

- Release title: Agent World unified integration intake
- Change summary: preserve the latest combined implementation and the outstanding
  Claude handoff without modifying either source worktree; continue from the
  combined code rather than reapplying already integrated mechanisms.
- Canonical status: IN DEVELOPMENT. This checkpoint is preservation, not release
  readiness, complete regression evidence or owner acceptance.
- Branch: `codex/agent-world-unified-acceptance`.
- Source / rollback: `f0bafe8ea46653827bc836afcb2197964390cf08`, the exact HEAD of
  `claude/agent-world-integration` at intake on 2026-09-08.
- Version: beta.96 unchanged. No Local activation, merge, deployment, paid call,
  trading operation or working-database migration.

## Provenance and stable WIP manifest

`db85773f5d2c50386744d63972d467b5a60af244` (Codex mechanisms) and
`7d347d204ea99103e33abdd2a011eee500028fff` (Claude review) are both ancestors
of the accepted source. The combined history includes merge `922c5d52`, code
checkpoint `92436698` and later automation/provenance work through `f0bafe8e`.
No duplicate cherry-picks, branch rewrites or PR base changes were performed.

The five remaining documentation files were copied from the original Claude
worktree. For each file, source-before, destination and source-after SHA256
matched. These are raw file-byte hashes before Git's normal CRLF normalization:

| Path under NT-Analyzer | SHA256 |
| --- | --- |
| docs/changelog/2026-09-07-agent-world-integration-branch.md | `6d86eb07f9d32b424bd44a45c2e68eb4e3f9974daa58265c768ac38935949dc2` |
| docs/changelog/2026-09-07-agent-world-mechanism-domains.md | `c1dce4f8c6f299b97b8640566d835d33493fe4a7e38dcdd401471a3548af8cdf` |
| docs/current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md | `b6d1276f2c16532ceb04f3c094724e3cd506d43ac47a845fc059fdbc643bcf21` |
| docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md | `5c55d566cddea38cd44a49e55cca4e1598d83b5e8b890eda41bd6f00c3808041` |
| docs/changelog/2026-09-07-agent-world-provenance-and-postgres-runtime.md | `fc8f01ef6d3b41b67350ccaa5d5a402ce075a64e9b41e386c8b1bd38e7a72642` |

The Codex worktree contains one residual untracked file,
`tests/test_agent_world_mechanism_flags.py`, SHA256
`99db9ff3f321c526f1b5da3f3b3fc4f850f492e6dbbc8c27b985c1383c8c5bff`.
That exact hash is recorded in the already integrated file's provenance header:
21 functions, 73 parametrized cases. It is accounted for, not duplicated.
A byte-for-byte intake copy is retained outside Git in
`.artifacts/integration-intake-20260908/` in the integration worktree.

Seven tracked runtime changes in the Claude worktree were deliberately not
overlaid: five `data/development/governance-rendered/*.md` files and
`data/development/governance/{change_log.jsonl,documents.json}`. They remain in
their original worktree. Ignored artifacts, registries, caches, databases,
credentials and cookies were not imported. No original file was reverted,
deleted, stashed or staged.

## Evidence boundaries at intake

- The last documented full regression is **4537 passed / 110 skipped / 0 failed**
  on code `92436698`, with legacy runner 13/13. This does not certify later code.
- Claude's later Part E reports an isolated PostgreSQL application/worker run,
  persistence across restart and RLS denials. This is inherited evidence pending
  reproduction with the accepted runtime; it is not a live process assertion.
- Historical Agent World PostgreSQL suite: 69 cases, with 68 requiring a server.
  Historical legacy PostgreSQL suites: 41 separate cases. Missing-DSN skips
  are not PASS, and neither suite is interchangeable with runtime acceptance.
- The synthetic backtest verification claim withdrawn in Part E remains
  withdrawn. Corrections and original error history are preserved. Real owner
  results on the protected Local are unrelated and are not reclassified.
- The Local test executor proves test execution, not an external provider's
  availability or professional quality. Downstream aggregate isolation still
  requires behavioral verification on the new final code.
- Current intake has no new full-regression or browser PASS. Short checkpoint
  gates: root CSP/secrets/Markdown scan PASS; Context Pack PASS (historical
  deployment-anchor warning retained); staged pre-release bundle PASS, 565 files,
  including shipped runtime reads, Python compilation and JS syntax; diff check
  PASS. An initial Context Pack header-position error was corrected, not waived.
  No executable file changed relative to source `f0bafe8e` in this intake.

## Protected runtime and ownership

A read-only health check confirms Local 8765 still serves
`2b6d0112bef88c5bfb73970de64ec5518443e56b`, build
`dev-0.10.0-beta.96-2b6d0112bef8`. It was not restarted or switched. The
initial mixed-object PowerShell display hid the listener row; the direct HTTP
check and an explicit JSON listener read resolved that display ambiguity.
No test instance or disposable PostgreSQL listener was running at intake.

Root is the sole integration owner for server.py, ui.js, permissions.py,
storage selection, migration numbering, shared projection and current status.
Independent workers receive non-overlapping file sets only in this new worktree.
Original Claude/Codex worktrees and PR #282/#283/#284 are preserved.

## Next operation and remaining work

### Core preservation checkpoint after intake `1409553a`

Draft integration PR: [#285](https://github.com/OMNOM-111/NT-Analyzer/pull/285),
base `codex/agent-world-owner-preview`. Original PR bases are unchanged.
The commit containing this section preserves the following isolated core work;
it remains **IN DEVELOPMENT**, before shared API/Chat/UI integration:

- Bounded non-trading Coordinator, strict verified-data handoff, multilevel
  delegation and separate human reviews for source, children and aggregate.
  Earlier core focused run: 77 PASS. Coordinator/manual-review regression:
  30 PASS; the final small CAS hardening still requires its exact-code rerun.
  Strict NinjaTrader source verification was not replaced by model assertions.
- Persona partial-update preservation, voice/presentation contracts and safe
  browser-audio controller: 57 focused PASS. No audible browser or paid TTS
  acceptance is claimed. Generic speaking clips are not phoneme lip-sync.
- Process Intelligence over verified scoped work, durable dedup/cooldown and
  explicit suggestion/acceptance: 28 PASS. API/UI integration is still pending;
  no automation is enabled by creating a suggestion.
- E-mail registration expired/used challenge now exposes the existing
  `registration_expired` recovery contract: 72 focused PASS. Consent, TTL and
  replay protection are unchanged. Final browser rerun is pending.
- Disposable PostgreSQL: 69 Agent World cases and 41 legacy cases passed
  separately, zero skips. Actual application/API/worker/restart/RLS acceptance
  passed on the earlier frozen 214-file application WIP hash documented in
  the [runtime receipt](2026-09-08-agent-world-postgres-unified-acceptance.md).
  It does not certify subsequently added code. Harness checks: 42 PASS.

The current full-Aurora QA instance is `http://localhost:8804/` with fresh,
isolated synthetic owner data. It is not a replacement for Local 8765. Browser
observations include explicit Google registration, QR confirmation, permanent
first-device trust, unknown-client OTP and session-only access. E-mail expiry
was observed and remains a negative-path receipt, not a positive-flow PASS.
All of these observations precede the final shared integration. No full pytest
result is claimed for this core checkpoint.

Only named source, tests and canonical change records are staged. Ignored test
databases, logs, receipts and launchers remain outside Git. Subsequent model
provenance, shared API/worker/Chat wiring and UI work are a separate delta.
Next operation: finish these shared hooks, then rerun focused/browser/runtime
gates on one exact source identity before the final full regression.

1. Preserve this intake checkpoint with exact staging and short mandatory gates.
2. Reuse and inspect the existing disposable launchers, repositories and test
   executor. Run one full Aurora instance on an isolated address and fresh data;
   keep Local 8765 and original queues untouched.
3. Recheck Preview/Auth/device contracts, then finish the strict non-trading
   Coordinator/delegation root without weakening NinjaTrader source verification.
4. Complete the remaining Persona, connection, memory, Process Intelligence,
   automation and usability gaps against the original canonical plan; retain
   one task projection and existing authority/queue/budget mechanisms.
5. Bind focused, runtime/PostgreSQL, browser and final full/static/CI evidence
   to exact source identities. Registration consent, own key, permanent owner
   Social publication and visual design acceptance remain owner actions.

OWNER ACCEPTANCE READY: NO. VISUAL DESIGN ACCEPTED: NO.
LOCAL 8765 UPDATED: NO. MERGE / DEPLOY: NOT PERFORMED.
