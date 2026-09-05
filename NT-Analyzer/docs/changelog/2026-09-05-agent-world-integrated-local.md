# Agent World — integrated Local, verified models and domain workflows

Release title: Agent World integrated Local owner review.
Change summary: preserve actual Local data, connect typed model tasks to the
existing SF Chat/worker/NinjaTrader/Desktop authorities, expose all domain tools
inside the compact AI Center, and add explicit verified SF Social publication.
Version remains `0.10.0-beta.96`; no next version or release assigned.

Business requester: project owner. Technical attribution: AI-assisted change.
Branch: `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282).
Starting SHA: `486db834850d465006a3983d2d83ee809202df60`; integrated source
`ca505d83a25356df5de2fb468f5bc20666a436d5` is committed and active on Local.
Claimed delivery/explicit roles/private-container follow-up is being verified.
PR #280/#281 are dependencies, not merged here.
Verification result: PENDING; owner acceptance not yet ready for the full delta.

Scoped automated verification result: PASS — 3906 passed, 44 skipped, 770.01 s;
legacy 13/13, Python compile, 23 JS checks, root secret/Markdown/CSP checks,
context validation, 533-file actual bundle all passed. Skips and remaining live
acceptance/CI gates below are not counted as PASS for the complete program.

## Local switch evidence

- Previous scheduled task served original dirty `7062f749` beta.93, not Unified
  beta.96. This explains the earlier version mismatch without blaming Preview.
- No active canonical job, worker job or Chief run was interrupted. Existing
  historical jobs/chat, actual account and authenticated NT heartbeat preserved.
- Initial online/cold copies cover 2607 files / approximately 234958886 bytes;
  SQLite online backup/integrity checks passed for both existing databases.
  Isolated-copy startup preserved identity/workspace and original queue/history.
- Original task XML, original runtime identity and checked manifests were saved
  outside Git. Cold manifest SHA256:
  `8de8d943b0dcbd543085f56730551843f2af48c1e8b2ca9b09d6e5f92023fde9`.
- Only the matched Local supervisor/server/worker and scheduled-task action were
  retired/replaced. NinjaTrader and other processes were not stopped.
- Clean detached `agent-world-local-runtime` at `486db834850d465006a3983d2d83ee809202df60`
  now serves 8765, beta.96, build `dev-0.10.0-beta.96-486db834850d`, dirty=false,
  Development, real owner/data root, Preview=false, live orders=false.
- Later model/domain delta activation requires a tested clean commit and another
  exact-PID/active-work check. No dirty hot-copy into that runtime is permitted.

## Implementation

[ADR-0012](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-owner-preview/NT-Analyzer/docs/adr/0012-agent-world-integrated-local.md) defines the reviewed
composition. Existing Auth/device trust/permissions/budgets/worker/jobqueue/
Desktop/SF Social/SF Chat remain authoritative. Changes include scoped session
leases and history access, private model transport and owner bindings, immutable
model/application evidence, one-page Persona/Models/Memory/Decisions/Court/
Experiments/Projects/routines/calendar/System drawers, and two-step permanent
social snapshots. No new numbered PG migration, Router replacement or trade
execution. Automatic routine execution remains disabled, not silently simulated.

Scoped implementation evidence:

- [Domain/storage/social record](2026-09-05-agent-world-domain-services.md).
- [Model/application services](2026-09-05-agent-world-model-application-services.md).
- [UI and gateway record](2026-09-04-agent-world-owner-review-ui.md).

## Verification ledger

| Check | Result and limit |
| --- | --- |
| Broad pre-final pytest | Historical 3803/44, then 3852 passed, 44 skipped; 622.61 s. Later claim/role/workspace changes require rerun |
| Follow-up contracts | 270 scoped tests, 28 delivery tests and 18 role/projection tests PASS; full follow-up run pending |
| Rating class-label regression | 96 passed; each observed model score names its specific rubric |
| Repeated actual PostgreSQL | 41 passed, zero skips, 122.71 s; isolated loopback TLS DB, non-superuser/NOBYPASSRLS roles; existing migrations 1–22 |
| Migration set | `d3bc149957d7c9eb68a4b476d3958a5bb790b0ac995cc73dc76ca9031fd53601`, no pending/applied-now migrations on repeat |
| Session authority/history | 17 passed; real disposable auth/device stores, permanent/session, revoke/expiry/foreign scope, no-write lease checks |
| Live provider/browser/application | On ca505d83: DeepSeek CONNECTION_OK, fresh SF Chat → DeepSeek → NT → same-chat original report PASS; Z.AI endpoint unavailable, not PASS. Other scenarios remain separate |
| Final static/context/bundle/CI | Pending final source; historical CI on b05ee124 not reused as current proof |

Forty-one generic Windows skips are covered by the separate actual PG run.
Two shell tests and one POSIX permissions test require Linux; skipped is not PASS.
No Production database or credentials are used to satisfy fixture acceptance.

Fresh historical backtest: model task `62182839-1c4c-563d-8186-bcef081ec599`,
SF Chat `C-1322EA65B646`, NT job `awnt_7ed6b329cead8eac1391f5c8a0f3b59ad6d2d073baca9a6f`.
SampleMACrossOver / MNQ 09-26 / 5m / 2026-08-24 to 2026-08-29 / Fast10 Slow25.
64 trades, net -969.70, PF 0.725188; actual deepseek-v4-flash response at 1256 ms,
USD 0.00006776. Original result SHA256
`202e31d6775e7e08cb3e4300110cc7ec3878f2023ead080944e119db2251bc6f`;
verified summary SHA256 `7c9e8d550e1f161a81ac59f8139a041f400ccd62f3f4435954be708f839c51be`.
This is not the excluded old manual job, synthetic data or a profit claim.

Follow-up changes: one claimed saved-result delivery path with bounded recovery;
explicit Persona application-role assignment independent of names and rights;
one overview workflow per exact linked source execution; fresh-auth navigation
and asset cache update; isolated ordinary-human personal-container endpoint and
cabinet CTA without NT pairing or owner credential copying. Existing NT gates,
budgets and owner registry remain unchanged. All added routes stay Local-only.
The intermediate full run had 3902 PASS / 44 skipped / 3 failures: two old
Persona payload assertions and a reproduced concurrent explicit-round Preview
creation race. The Preview fix preserves the first stored deadline and checks
budget/fixture equality before execution; a synchronized distinct-clock test
reproduces the race deterministically. No registration consent is automated.
The final rerun above passed; the intermediate run is preserved, not relabelled.
Ordinary test signup reached final Terms; owner confirmation and separate
OpenRouter key entry are pending. No clickwrap consent or key was supplied for
the owner. The private wizard does not support native Gemini transport.

Actual Gemini connection test `b7114186-079b-58be-98dc-e38c552c65d2` returned
CONNECTION_OK (611 ms). DeepSeek/Gemini comparisons `fe17dc14-2944-51c6-b125-7ea3065d7852`,
`c55cf8c8-e31d-5862-a12d-038df10414fe`, `5d749d7b-e4fa-564d-8f69-7626d0cd4333`
each used the same arithmetic input for both models, with three distinct input
arrays overall. Six actual outputs passed independent checks; both models have
n=3, OBSERVED, low confidence, no routing effect. Z.AI endpoint failure is
retained; only the newly created failing binding was retired, not the owner key.

## Release impact and rollback

Only Development owner review is in scope. Final artifact would include the
committed app/UI/tests/current docs/ADR/change records; no runtime database,
encrypted store, backup, operator launcher or private screenshot dump belongs in
Git. Pre-release verification must inspect the staged exact bundle and runtime
reads before Git closeout. No signing, merge, Canary or Production performed.

Restore the original task/launcher only after exact process ownership checks;
preserve later owner writes before any full data restore. The checked cold copy
and instructions remain in the ignored Local operator directory. Local readiness,
Git/CI closeout, owner design acceptance and program closure remain distinct.

Current route/requirements matrix and next safe action:
[canonical status](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-owner-preview/NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

Accepted bundle exclusions: developer-only `docs/current/`, `docs/adr/`,
`docs/archive/` and the External GPT Context Pack stay in the repository,
outside the curated server bundle. Shipped changelog references use repository
links for them; no runtime dependency on excluded documents is introduced.
