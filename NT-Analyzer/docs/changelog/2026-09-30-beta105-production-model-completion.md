# beta.105 — завершение server model request и SF Chat delivery

Release title: Production Agent World model completion.
Change summary: Узкая server-коррекция timeout модели и fail-closed PostgreSQL
delivery claim; без новой функции, схемы или смены provider/secret architecture.
Product scope: тот же незакрытый owner-approved Local beta.95 → beta.96 пакет;
beta.105 — техническая итерация после beta.104 Production PARTIAL.
Affected subsystems: AI Center model task/test HTTP, Agent World admission,
PostgreSQL worker claim, SF Chat result delivery.
PR/source SHA/CI/artifact: pending. Verification result: Development focused
tests PASS; server stages pending.

## Production beta.104 evidence and root cause

The accepted beta.104 artifact and owner/real Professional GET path are live,
but the one bounded Professional shared-model POST reached Cloudflare 524.
Durable read-only inspection proves that this was **not** a failed provider
request: task `406d5586-f3cd-5315-b8c6-b3f853d388e8` and its single main
PostgreSQL job succeeded. Gemini transport request
`REQ-07D49CFB78B34507` produced a non-synthetic sealed receipt
`6de351c0-92e2-500c-9681-3ad4e4129c41`, 58 input/34 output tokens,
known $0.00 cost, one usage event, and matching caller/owner audit. No retry
was made. The separate terminal SF Chat delivery job exhausted three attempts
with `model_delivery_claim_required`. Its validator expected SQLite
`worker_id`/`locked_until`/`deadline_at`, whereas the live Production queue
uses `lease_owner`/`lease_token`/`leased_until`/`started_at`/`timeout_sec`.
Authenticated model POST also repeats nested authority and budget checks
across its synchronous construction path, unlike the beta.104 optimized GET.
These are application-code defects, not missing Production configuration.

## Narrow Development correction

- Within an explicit human server model task/test POST only, reuse the already
  admitted authority for nested repository construction. A fresh session,
  workspace, capability, flag and budget check still occurs immediately before
  queue dispatch and before HTTP response; PostgreSQL RLS remains on every
  record operation and the worker independently rechecks before provider
  transmission. Preview, automation, other mutations and GET are excluded.
- Validate PostgreSQL delivery claims using the queue's real lease owner,
  token, deadline, timeout, attempt, payload and scope. Preserve the existing
  SQLite claim validator. Wrong/expired/cancelled/foreign claims fail closed.
- No schema, secret, artifact, provider, Telegram or product-scope change.
  beta.104 remains immutable and Production reporting remains OFF while Local
  `StratForge Vitek` remains ON.

Focused model/shared/server security suite: 273 PASS (2026-09-30). Full
required CI, signed immutable artifact, Canary regression, same-artifact
Production promotion and final acceptance are pending. Do not repeat the
already successful Production provider call merely because its HTTP response
was ambiguous; use durable receipt/ledger evidence and a delivery-only
recovery or a separately justified new bounded call after Canary validation.

Historical beta.103 Canary PARTIAL/PASS and PR #307 remain evidence, not a
runtime fix. The last verified Production backup before beta.104 promotion is
`pre-beta104-production-peer-20260930T144651Z`; preserve beta.103 rollback,
older beta.99 slot, user records, secrets and evidence. This record must be
updated with exact final source/build/archive/runtime SHA, checks, backup and
stage results as they actually occur.
