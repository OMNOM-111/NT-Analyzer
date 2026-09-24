# Local Preview parity and account lifecycle

Status: IN DEVELOPMENT — focused verification passed; manual acceptance and full regression pending.
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
- Remaining: concurrency/footprint checks, new Local manual walkthrough and full regression. Previous 6057/134 results do not certify this diff.

Deployment impact: additive Development deletion registry and demo source. Production relational erasure is explicitly unavailable and not enabled here. No server migrations, secret replacements or release promotion.
