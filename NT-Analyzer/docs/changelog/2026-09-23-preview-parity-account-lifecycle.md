# Local Preview parity and account lifecycle

Status: BETA (Local) — IMPLEMENTATION COMPLETE; manual acceptance and regression PASS. Owner review and any release promotion remain separate.
Branch: `codex/shared-model-local-completion`; draft PR #291.
Base: `ca8e663960c3887fbb5305163588bd82094769c4`, continued WIP.
Release scope: Local only. Server, Canary and Production unchanged.

## Changes

- Active trial without a private live provider uses labelled public synthetic demo candles. Normal registration and Preview use the same resolver. Owner live and both redistribution gates remain unchanged. Demo never leases live transport or accepts owner events.
- Models separates own connections and available shared models; the inline real connection test remains in the open card.
- Deputy replies resolve the user's current main Persona, with Deputy/manager fallback. Avatar click/keyboard is the speech control. A shared model supplies execution, never the donor's identity or voice credentials.
- Social own wall is newest-first, with registration milestone last. Preview and Local project already-public posts, including organizations, into each other's feed. No account IDs, email, private content or administrative grants cross this boundary. Imported rows are stripped before persistence.
- Local account deletion requires explicit confirmation and fresh purpose/session-bound OTP. Sessions/authority freeze before own workspace, Agent World records/artifacts/model credentials, scoped chat/memory and private social data are erased. Shared access is revoked. An append-only registry retains former UUID/legacy ID, protected HMAC identifier, creation/deletion dates, bounded reason/type/security flags. Usage quantities/cost survive as deleted-user attribution.
- Exit/Reset uses the same lifecycle. Parent cleanup retains a minimal receipt before erasing a terminated child's validated disposable container. Owner and workspaces with other members remain protected.

## Verification checkpoint

- Before market edits: 58 market-data tests passed; source hashes retained locally.
- Browser reproduction: fresh shared-model Preview, active trial, graph added; redistribution refusal and no candles confirmed.
- 165 focused tests passed across Preview, Social, shared grants, Deputy presentation, OTP/auth and demo/lifecycle boundaries.
- Clean checkpoint `e157b83611da09decf7ed358c0e883b40ebb2b7c` activated only on Local; copied-data rehearsal preserved identity/workspace and SQLite integrity; 645-file bundle passed all four gates.
- Manual ordinary **new_user** registration (not a ready-made shared-model shortcut): own workspace and five active trial hours; visible demo candles; separate shared group; inline real Gemini response; normal answers to greeting/capabilities/question; only an explicit plan request created a task/review result. Avatar interaction completed browser speech playback; actual audible output was not independently recorded.
- Social: eight existing public owner/organization posts visible; two disposable publications ordered newest-first above registration milestone, visible to owner as TEST/PREVIEW; owner private posts absent. Wrong account-deletion OTP rejected; correct fresh code erased the user, returned onboarding, and both test posts disappeared. Exit removed the disposable container; parent retained one TEST/PREVIEW deletion receipt and model usage. Owner MES/MNQ charts still rendered through TopstepX. Browser console had no unexpected error/warning during those checks.
- Follow-up fixes: explicit DEMO header/price label; Deputy fallback label; separate numbered connection controls; profile modal ordering; active-usage time in cabinet; deletion retry cannot reactivate a frozen user; actual model secret/revision erasure and late usage anonymization.
- 233 related tests passed after updating the avatar-control harness. Full regression identified that old harness plus a runtime-import allowlist omission, two source-introspection checks affected by files changing during the run, and a transient loopback socket failure. These complete modules passed on rerun. The remaining partitions and final follow-up runs subsequently passed as reconciled below; the previous 6057/134 baseline is not used to certify this diff.

## Follow-up acceptance

- Clean `c09dc2076498a8e9bb22018f4261eb21e7646772` Local: demo candles visibly labelled; chart minimize/restore/maximize/close and browser back/forward worked. TopStep opened its development scaffold; Documents rendered; new Memory and Tasks contained zero owner records. Model card showed numbered shared connections and an inline real response. Greeting rendered as Deputy with manager avatar and no separate speech button; avatar playback completed on the active browser tab (background-tab playback correctly stopped).
- Owner toggled the tested connection off; the same already-open Preview card refused a new call, with unchanged successful usage. Owner restored its original sharing. Separate owner usage showed tokens/cost and the previous account as deleted. Reset created a different empty user/chat; parent retained `preview_reset` and `preview_exit` receipts with correct pre-deletion flags.
- Final polish: full-width DEMO price badge; expandable shared metering history with task/agent identifiers but no prompt content; historical closed Preview callers labelled deleted; child response cache and browser storage cleared on erasure. A bounded Development migration corrects the first synthetic self-deletion receipt, which had observed the forced freeze instead of the original active state. No real-user security flags are rewritten.
- Full inventory: **292 files / 6200 collected cases; 6066 passed, 134 skipped, zero unresolved failures**, reconciled from four disjoint partitions plus complete affected-module reruns and five added cases. This is not represented as one unchanged-tree run. Follow-up groups: 233, 125, 31 and 128 passed. Evidence: local `.artifacts/parity-full-regression/reconciled-result.json` and associated logs. Root secret scan PASS. No live-data mutation guard failure.

Deployment impact: additive Development deletion registry and demo source. Production relational erasure is explicitly unavailable and not enabled here. No server migrations, secret replacements or release promotion.

## Final Local acceptance — 2026-09-24 UTC

Implementation source: `2421b2108fcc9e799917052d940b766f3d265ae5`, above checkpoints `e157b836` and `c09dc207`. The final closeout also removes obsolete seven-day trial copy from the owner panel and registration notifications; active-time entitlement logic is unchanged. PR: [#291](https://github.com/OMNOM-111/NT-Analyzer/pull/291).

- Fresh `ai_denied_user` Preview retained the ordinary five-hour trial and working DEMO chart while AI navigation remained denied. This scenario is an explicit QA permission override; ordinary new-user provisioning is not restricted. The full price badge visibly included DEMO. Console errors/warnings: none in the final normal flow.
- Exit returned to owner Local and removed the final disposable container. Parent registry contained four minimal TEST/PREVIEW receipts: one self-confirmed deletion, one reset and two exits. All original active-state flags were correct after the bounded v2 correction. No test identity remains active.
- Owner expanded the shared-call history in the real model card: deleted-user attribution, task/conversation and agent identifiers, input/output tokens and cost were visible without private prompt content. The tested sharing toggle was restored to its initial ON state.
- Owner access metadata before/after matched exactly: two users, one workspace, three memberships; SHA256 `dfcdf0b471112eb88388f3651350b5a5efb6082c172935de1209658af3011ccd`. Public owner content remained visible after test publications disappeared; this is content/access verification, not a claim that read-time Social metadata is byte-identical.
- Legacy runner: **13/13 suites PASS**. Final 645-file artifact-content rehearsal passed bundle static references, runtime reads, Python compilation and shipped JavaScript syntax. Context Pack validation and repository-root secrets scan passed. Full pytest evidence and rerun qualifications are recorded above.

Local verification covers registration, demo Desktop and chart-window controls, TopStep scaffold, Documents, isolated Memory/Tasks, model test and revoke, normal Deputy conversation and a real work request, avatar playback state, Social public/profile feeds, explicit deletion and automatic Reset/Exit. Speech playback completion was observed; audible sound was not independently recorded. Provider-specific live connections and Production account erasure are outside this Local acceptance.

Owner read-only Users registry was opened manually: exactly the original two active accounts and four TEST/PREVIEW deleted receipts; no restoration or edit controls on deleted rows.

Final trial-copy follow-up: 181 auth, registration, active-trial and Aurora contract tests PASS; 645-file pre-release bundle PASS after the copy/documentation changes. Repository-root secret scan and Context Pack validation PASS.
