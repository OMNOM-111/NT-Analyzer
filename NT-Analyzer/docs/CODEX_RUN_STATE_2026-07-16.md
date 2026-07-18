# StratForge Codex run state — 2026-07-16

Last checkpoint: 2026-07-16 09:30 PT

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
6. Started the authorized in-app Browser QA and captured the initial unauthenticated production desktop state. The browser-client retry then correlated with another Codex desktop restart; no full role/device matrix has been claimed.
7. Completed the premature-exit investigation. Evidence and conclusion are recorded in `docs/CODEX_CRASH_INVESTIGATION_2026-07-16.md`.
8. Added a standalone watchdog that preserves five-second process/package/reboot/resource/Git checkpoints and warns on detectable restart risks without controlling or terminating Codex.
9. Implemented independent Databento/Yahoo providers, provider health/cooldown, automatic failover, gap recovery, freshness/quote/source metadata and a read-only status API.
10. Completed the real NinjaTrader-stop test: 180 independent bars and a valid PNG remained available; after restart, root `MNQ` resolved to `MNQ 09-26` and primary Bridge bars resumed in six seconds.
11. Repaired Practice Trading data states/controls/reset/cancel/close, made Micro Live production UI fail-closed/coming-soon, and confirmed TopStep as safe scaffold.
12. Re-ran pytest, legacy suites, static release scan, worker crash/HTTP probes, staging probe and Bridge Release build. Exact final evidence is recorded in the release audit.
13. Found and fixed a pre-existing subscription test that lacked its temp-store fixture and could touch production DPAPI data. Added unique temp names plus bounded Windows sharing retries, backed up the encrypted store, removed only five rows proven to be created during this session, and restored the prior entitlement state.
14. **2026-07-16 PT ~10:45 — Azure TTS:** wired `AGT-B8F24346E288` (`gpt-4o-mini-tts` on `tratforge-openai-1`) into `agent_tts.resolve_tts_credentials` (prefer Speech models even if chat-disabled; require `model` in Azure speech JSON; passthrough `/audio/speech` base_url). Live synthesize vitek/marina → MP3. Docs: `AGENTS.md`, `UI_API_MAP.md`, `Agents/README.md`.
15. **2026-07-16 PT ~13:20 — TTS preview CSP:** browser error `Failed to load because no supported source was found` on «Прослушать голос» was CSP blocking `blob:` MP3 (`default-src 'self'` without `media-src`). Added `media-src 'self' blob:` to `STATIC_CSP` + all Aurora page meta tags; hardened preview/avatar audio blob typing.
16. **2026-07-16 PT ~19:15 — NinjaTrader autostart off:** blocked default `NinjaTrader.exe` launch from bootstrap/reconnect/runner/AI Lab UI/`start-ai-lab.ps1` (login lockout after reboot). Opt-in only via `NTA_ALLOW_AUTOSTART_NINJATRADER=1` + explicit flag.
17. **2026-07-17 PT — tail audit:** implemented the missing bootstrap env gate,
    corrected ProjectX SignalR targets/contract IDs, removed duplicate browser WS,
    added scoped cache keys, fixed IPC benchmark port allocation, reconciled BYOMD
    documentation, and installed the hash-matched Bridge DLL. Automated evidence:
    682 pytest tests and 13/13 legacy suites pass; production acceptance remains
    blocked on owner-controlled live/visual/credential/load scenarios.
18. **2026-07-17 PT — orchestrator backlog 1–210:** mapped the owner's new issue
    register to eight root causes; implemented durable scoped authorization,
    idempotent decisions, canonical lifecycle state, `SESSION_CLOSED`, preview/apply
    reconciliation, task/event leases, restart recovery and frontend telemetry.
    Backed up the real Vitek store, applied 40 safe repairs with no record deletion,
    and confirmed a zero-action second preview. Final evidence for this block:
    690 pytest tests, 217 focused tests and 13/13 project suites pass.

## Branch preservation audit

| Branch | Commit | Purpose | State | Preservation check |
| --- | --- | --- | --- | --- |
| `codex/stratforge-pre-separation-safety` | `3019a571de43fccec3e928ee350f5e18de03bb5e` | Complete original dirty tracked+untracked snapshot | Immutable safety ref, 746 files | Tree `044c9d0774b08d84637378efc77e2a75d0cf0ef6`; scratch plan present |
| `codex/stratforge-release-20260716` | Current tip; authoritative hash is the final `git log` entry | Atomic release history, recovery controls, failover and audit | Clean after final documentation commit | Separate implementation/recovery/data/documentation commits; no history rewrite |

The release/safety differences are intentional and auditable: the scratch `STRATFORGE_PLAN_TEMP.md` stays only in safety; the release branch adds implementation, tests, watchdog/run-state, failover task and corrected audit documents. No original file is unrecoverable.

## Verified

- Release branch was clean after the seven commits.
- Safety and release refs exist.
- Initial production UI loads and presents a Telegram login gate.
- Final post-failover evidence: 628 pytest tests, 13/13 legacy suites, Python/JavaScript/static scans, worker/recovery probes, staging isolation and Bridge Release build passed.

## External/manual blockers (not incomplete code claims)

- Full visual/mobile/Telegram Mini App and two-profile role/impersonation matrix in user-controlled Chrome.
- Real Google OAuth and separate Community Telegram destination.
- NinjaTrader Strategy Analyzer manual comparison.
- Credentialed Databento entitlement (current independent Yahoo chart fallback is delayed and chart-only).
- Real payment/broker sandbox adapters and separate authorization for any money/order test.

The originally referenced `STRATFORGE_MARKET_DATA_FAILOVER_TASK_RU.md` was absent, so its scope was restored from the owner's attachment and the completed implementation/evidence report now exists at the project root under that name.

## Exact next action

Run the remaining human visual/role matrix in an already-open user-controlled Chrome window, then perform the separately credentialed Google/Community/Databento/payment/broker/Strategy Analyzer checks. Do not initialize the in-app browser runtime again.
