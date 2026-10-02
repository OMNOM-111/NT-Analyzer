# Local Runtime & Documentation Canonicalization

Status: **IN PROGRESS**. Owner request: 2026-10-01. This is a post-beta.106
Local/configuration and documentation task, not a new server artifact or a
reopening of the beta.95–beta.106 product release. The owner-approved product
card remains Done with 7/7 Production PASS.

## Confirmed starting point

- `main` at task start: `9483bac868d829f3891e5e09fe84c18d242cf9c6`;
  beta.106 application source `e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885`;
  Canary/Production artifact `art_7aebf504ae354ce7981c58359a1ff546`.
- Wrong Local listener `127.0.0.1:8765`: Python PID 31132 (parent py.exe
  22520), old root worktree `feat/shared-model-access` at
  `77eda536f9909afd325ffcd2c89900c17744d4f3`, dirty beta.96 build.
  Its environment lacked the exact Local Agent World workspace admission;
  owner workspace `ws_owner_training_c1fe3f2f8a52` received
  `agent_world_local_disabled` from AI Center.
- The Desktop `StratForge AI.lnk` targeted the old root launcher. The older
  accepted Local code `56945ac6` is historical evidence, not the new baseline.
  The previous correct startup was coupled to the now-disabled `StratForge
  Vitek` Scheduled Task; that task must stay disabled because Production is
  the sole operational Telegram/report sender.

## Preservation and recovery boundary

- The dirty old root remains unchanged in Git: 25 modified tracked entries
  and 36 untracked entries. A full tracked binary patch and untracked
  file/size/hash manifest are in the ignored Local recovery directory
  `local-current/.artifacts/local-recovery-20261001/`; tracked patch SHA256
  `4933c3e8d4eaeaf5a64a0b00027276ac9ce2c6285b9d1f5914f2a8a868bebe18`.
- A non-certified pre-quiesce data copy was made only as a preliminary safety
  copy. The application was then stopped by exact listener PID, not by broad
  process matching. A strict quiesced snapshot of the original owner data
  root passed the repository snapshot tool's file hashes and SQLite integrity
  checks: snapshot `a76544b4-20f8-4940-857e-dc3a140f5879`, 2,898 files,
  5 SQLite databases, data SHA256
  `ad676636cdf0bbf79c159dc179a8854ba67b0d083d323b9cef6e86fa8302bd57`.
  A subsequent WAL checkpoint and `integrity_check` passed for all five
  databases. Recovery evidence stays ignored, local, and outside Git.
- No reset, clean, deletion, dirty-file merge, Production/Canary change,
  provider call, or report-sender switch was performed.

## Scoped implementation underway

- A permanent clean worktree was created at
  `C:\Users\dimon\Documents\StratForge-worktrees\local-current` from the
  above `main` SHA, on branch `codex/local-runtime-doc-canonicalization`.
- `tools/launch_canonical_local.py` pins this path, the beta.106 application
  baseline, exact original owner data root/workspace, Development environment,
  and disabled Local Telegram/reporting. It refuses a dirty or older/wrong
  checkout before server startup and prints expected/actual path and SHA.
  The Local mechanism opt-in document is explicit and empty: previously
  accepted base Agent World functionality is enabled by the workspace gate;
  newer unaccepted mechanism flags remain OFF.
- Initial clean-launch commit `b809911c73c219b92e43c9b46d0d79b26a118b7a`
  passed source/dirty guards. Local `/live` and `/ready` returned 200; runtime
  identified `0.10.0-beta.106`, Development, that clean SHA, and the original
  data root. The new Desktop shortcut targets the canonical launcher; the
  previous `.lnk` and its hash are preserved in ignored recovery evidence.
  `start-ai-lab.ps1` now identifies itself as an explicit legacy research
  entrypoint, not the default. The scheduled `StratForge Vitek` task remains
  Disabled, and Local Telegram delivery is fail-closed.
- After the documentation commit `fa8880ac92591003172dec828e8650e871b14bc4`,
  the previous exact Local supervisor/worker were stopped, and the actual
  Desktop shortcut was invoked once. It started a single listener (PID 10160)
  with clean `dev-0.10.0-beta.106-fa8880ac9259`; `/live` and `/ready` were
  200, and the owner AI Center reopened without `agent_world_local_disabled`.
  This is a process restart/shortcut acceptance, **not** evidence of a new
  Windows reboot; the latter remains to be observed.
- The 15 tracked context files were moved by `git mv` to repository-root
  `AI_CONTEXT/`; all relative links were rebased and validated. The exporter,
  governance instructions, link references and CI documentation gate were
  updated together. Focused documentation tests: 21 PASS. PR/main adoption
  and post-reboot startup observation remain pending.

## Dirty old checkout classification — no deletion

The 25 modified tracked and 36 untracked porcelain entries are fully listed
with hashes in the ignored inventory. Disposition is by category, not a blind
copy to current main:

| Category | Entries | Disposition |
| --- | --- | --- |
| KEEP | `data/ai_control_center`, `data/ai_lab` SQLite/registries, `data/governance` and `data/development/governance` journals/source, catalog/rating state | User/runtime state; retained in original data root and verified snapshot. Do not commit or delete. |
| ARCHIVE | old `docs/current`/governance/context edits, three old change records, old root `timeline.html`, `ИСТОРИЯ_РАЗРАБОТКИ.md`, `TIMELINE_КРАТКАЯ.txt`, `CLAUDE.md`, nested `.worktrees/*` and `timeline-review-worktree` | Preserve in old checkout and recovery inventory for later comparison; historical decisions are not automatically merged. |
| GENERATED | `data/*/governance-rendered/*`, SQLite `-wal`/`-shm`, cached report summaries, release-center DPAPI backup, legacy AI archive and `documents.json.backup-*` | Preserve as generated/runtime/rollback evidence, never ordinary Git staging. |
| MERGE | No old dirty file merged into this branch. Current governance and AI_CONTEXT edits were written against clean main plus evidence. | Review any genuinely unique old material separately after release; no automated merge. |
| DELETE | None. | No potentially user-owned file was proved disposable. |

## Fresh visual/technical parity — scoped post-release check

This is **not** a repeat of the previously accepted beta.106 7/7 product
release. A fresh read-only click-through was attempted, without provider
calls, new users, posts, messages or server changes. `PASS` below means the
stated surface was observed now; `PARTIAL` identifies a narrower observation,
not a regression verdict.

| Capability | Local | Canary | Production |
| --- | --- | --- | --- |
| SF Social | PASS: feed/profile/company and 9-post owner feed | PASS: owner page/feed/profile | PASS: owner page/feed/profile |
| SF Chat | PASS: dialogs/history/topics/Deputy selector | PASS: owner dialog/history/Deputy | PASS: owner dialog/history/Deputy |
| Registration | PARTIAL: current owner session and accepted code, fresh guest step not reached | PASS: public Professional → Register → step 1/3, Telegram/Google choices | PASS: same public step 1/3 |
| Device trust | PARTIAL: owner session works; two-mode settings not freshly walked | PARTIAL: same | PARTIAL: same |
| Agent World / AI Center | PASS: owner overview and all six tabs, no denial | PASS: owner overview and all six tabs | PASS: owner overview and all six tabs |
| Shared models | PASS: owner model cards/history, no key plaintext | PASS: owner model cards, no invocation repeated | PASS: four owner model cards in “Мои модели”; no invocation repeated |
| New/test-user charts | PARTIAL: owner UI only; no fresh separate-new-user chart | PARTIAL: real Chrome non-owner trial expired; historical MBT candle acceptance retained | PARTIAL: real Chrome non-owner trial expired; historical Production acceptance retained |

Technical identity: Local canonical clean `b809911c` on beta.106 app source;
Canary and Production unchanged `e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885`,
same signed artifact `art_7aebf504ae354ce7981c58359a1ff546` and build
`sf-0.10.0-beta.106-e7ecd2133c65-20261001T150927Z`; all `/live` and
`/ready` probes returned 200. Local uses the original Windows owner data and
DPAPI path, not Production secrets; server environments keep isolated
PostgreSQL/SecretStore state. Production remains sole Telegram/report sender,
Canary non-sender, Local Vitek Disabled.

The real Chrome Professional trial has expired in both Canary and Production,
so fresh non-owner chart/security click-through cannot be represented as PASS
without a legitimate entitlement action. The previous beta.106 product-card
7/7 Production PASS remains historically valid. This new canonicalization
card remains In progress; no new server artifact or release iteration exists.

## Release impact and next step

No new beta or server artifact is warranted by a Local shortcut/environment
incident. Next: finish scoped Git/PR and CI review of this documentation and
launcher work, then obtain a fresh real non-owner visual chart/security check
through ordinary access before marking the new task Done. A clean startup
after a future actual reboot is still unobserved. Any proved application-code
defect would follow a new versioned release path. Production beta.106 remains
untouched.
