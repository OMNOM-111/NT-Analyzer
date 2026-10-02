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
- Syntax and the fail-fast dirty-worktree rejection passed. Clean-launch,
  Desktop shortcut, browser parity, AI_CONTEXT migration and CI governance
  gate remain **PENDING** and must not be described as PASS yet.

## Release impact and next step

No new beta or server artifact is warranted by a Local shortcut/environment
incident. Next: commit the scoped launcher/checkpoint, activate the canonical
Local on port 8765 against the preserved original data root, verify owner
Agent World and navigation, then complete the documented environment-parity
and AI_CONTEXT work. Any actual application-code defect gets its own versioned
release path. Production beta.106 remains untouched.
