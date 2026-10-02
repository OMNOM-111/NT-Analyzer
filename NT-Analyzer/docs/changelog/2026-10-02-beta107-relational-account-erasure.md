# beta.107 — PostgreSQL account erasure and second-account lifecycle

Release title: Server relational account erasure.
Release summary: Bring the accepted Local account-delete contract to Canary and
Production through scoped PostgreSQL/RLS transactions. Preserve minimal
deletion and usage evidence while removing the account's private identity,
workspace, Social, SF Chat, Agent World, model-secret and object data.
Release PRs: #314 (Development; required CI pending).
Affected subsystems: Auth and device trust, workspaces, entitlements,
Community/SF Chat, Agent World, ServerSecrets, AI usage, PostgreSQL schema 0025.
Release impact: New additive server migration; a verified backup, exact
environment-specific rollout and real delete/re-register QA are mandatory.
No beta.107 artifact or server deployment exists at this Development checkpoint.
Verification result: Development PARTIAL — disposable PostgreSQL/RLS
integration plus relevant Local regression 170/170 PASS; required PR/final-main
CI, Canary and Production remain pending.

## What changes

- Self-delete retains exact `УДАЛИТЬ`, fresh session/purpose-bound OTP and
  owner/service/shared-workspace protections. Admin deletion still requires
  `users.manage`; no client-declared owner authority is trusted.
- The server first freezes account authority and model sharing. One later
  PostgreSQL transaction removes exact private rows; failure leaves a blocked,
  retryable account, not a partially active identity.
- Historical usage/cost and model-call audit remain with a deleted-user
  attribution. Identity history is revoked; an old provider subject can be
  linked to a new canonical identity without exposing old private data.
- Referenced file payloads and exact legacy per-user orchestrator scopes are
  cleaned after commit from a durable database manifest. Canary and Production
  never fall back to Local SQLite or DPAPI for relational erasure.

## Current gates

The current server deployment remains beta.106. A signed immutable beta.107
artifact requires merged source and final-main CI; Canary/Production delete
and re-registration have **not** occurred. The prior API admission incident
was recovered without changing the beta.106 artifact, but its exact retained
handler trigger remains unproven. See
[the incident evidence and Development checkpoint](2026-10-02-api-admission-recovery-and-beta107-erasure.md).
