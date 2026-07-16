# StratForge Codex run state — 2026-07-16

Last checkpoint: 2026-07-16 08:34 PT

## Git

- Active branch: `codex/stratforge-release-20260716`
- HEAD before the investigation checkpoint: `9f95446f8be5ed3b2f2e5deec34d01a3c900e506`
- Safety branch: `codex/stratforge-pre-separation-safety`
- Safety commit: `3019a571de43fccec3e928ee350f5e18de03bb5e`
- Working tree before adding this file: clean.
- No hard reset, history rewrite or deletion of the safety branch was performed.

## Completed

1. Captured the entire original dirty tree, including tracked and untracked files, in the safety branch.
2. Created the clean release branch.
3. Separated the preserved work into seven atomic commits:
   - `77cb0d04` avatar/TTS profiles, media, API and UI;
   - `e0ac20aa` refreshed catalog/governance metadata;
   - `8cc4cc8a` tenant, auth and product contours;
   - `ae86373f` durable AI/chart worker execution;
   - `82229aa0` staging mutable-state isolation and recovery tooling;
   - `2a84b291` secure HTTP and Aurora integration;
   - `24a89735` release plan and audit documentation.
4. Verified that `NT-Analyzer/STRATFORGE_PLAN_TEMP.md` is byte-identical to the copy in the safety commit before removing it from the release worktree. It remains recoverable from the safety branch.
5. Started the backend from the release branch. The background supervisor currently self-heals the local listener.
6. Started the authorized in-app Browser QA and captured the initial unauthenticated production desktop state. No full role/device matrix has been claimed.
7. Completed the premature-exit investigation. Evidence and conclusion are recorded in `docs/CODEX_CRASH_INVESTIGATION_2026-07-16.md`.

## Branch preservation audit

| Branch | Commit | Purpose | State | Preservation check |
| --- | --- | --- | --- | --- |
| `codex/stratforge-pre-separation-safety` | `3019a571de43fccec3e928ee350f5e18de03bb5e` | Complete original dirty tracked+untracked snapshot | Immutable safety ref, 746 files | Tree `044c9d0774b08d84637378efc77e2a75d0cf0ef6`; scratch plan present |
| `codex/stratforge-release-20260716` | `9f95446f8be5ed3b2f2e5deec34d01a3c900e506` before this checkpoint | Atomic release history plus run-state mechanism | Clean, 746 files | Seven separated implementation commits plus checkpoint; no uncommitted files |

The release/safety differences are intentional and auditable: the scratch `STRATFORGE_PLAN_TEMP.md` stays only in safety; the release audit contains corrected branch metadata; one diagnostic-script trailing space was removed; the release branch adds the run-state file. No original file is unrecoverable.

## Verified

- Release branch was clean after the seven commits.
- Safety and release refs exist.
- Initial production UI loads and presents a Telegram login gate.
- Previous automated evidence before history separation: 618 pytest tests, 13/13 legacy suites, Python/JavaScript/static scans and bridge build passed. These results must be rerun from the final post-failover HEAD.

## Not completed

- Full Browser/mobile/Telegram Mini App and role/impersonation matrix.
- Visual repair and acceptance of Practice Trading.
- Safe product decision and UI for Micro Live.
- TopStep scaffold review.
- NinjaTrader/Strategy Analyzer manual checks.
- Independent market-data provider, failover, freshness and gap recovery.
- Final full regression and updated acceptance documentation.

The file `STRATFORGE_MARKET_DATA_FAILOVER_TASK_RU.md` was not found in the workspace, Git refs or common attachment folders. Its required scope has been restored from the owner's attached text: provider abstraction, a source independent of NinjaTrader, freshness control, automatic failover, gap detection/recovery, unified bars, source status UI and a NinjaTrader-stop test.

## Exact next action

Resume the existing authorized Browser session at `http://127.0.0.1:8765/ui/`. Record guest/free-preview and Practice Trading results at 1920×1080 and 390×844, collect console evidence, diagnose the empty chart, then checkpoint before any implementation change.
