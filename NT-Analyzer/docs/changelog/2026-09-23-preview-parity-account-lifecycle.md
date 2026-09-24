# Local Preview parity and account lifecycle

Status: IN DEVELOPMENT — Local walkthrough completed on e157b836; follow-up UX/erasure checks and full regression pending.
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
- 233 related tests passed after updating the avatar-control harness. Full regression identified that old harness plus a runtime-import allowlist omission, two source-introspection checks affected by files changing during the run, and a transient loopback socket failure. These complete modules passed on rerun. Remaining partitions and final follow-up run are still pending. Previous 6057/134 results do not certify this diff.

Deployment impact: additive Development deletion registry and demo source. Production relational erasure is explicitly unavailable and not enabled here. No server migrations, secret replacements or release promotion.
