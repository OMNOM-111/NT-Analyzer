# beta.105 — завершение server model request и SF Chat delivery

Release title: Production Agent World model completion.
Release summary: Узкая server-коррекция timeout модели и fail-closed PostgreSQL
delivery claim; без новой функции, схемы или смены provider/secret architecture.
Release PRs: #309
Product scope: тот же незакрытый owner-approved Local beta.95 → beta.96 пакет;
beta.105 — техническая итерация после beta.104 Production PARTIAL.
Affected subsystems: AI Center model task/test HTTP, Agent World admission,
PostgreSQL worker claim, SF Chat result delivery.
Source SHA: `91d8a4c1ac25f988b643ff71e119502a1df3d3f7`.
Verification result: **Canary PASS; Production focused smoke PASS**. Operational
report cutover completed for the one Production control audit; future daily,
weekly, monthly and quarterly flags are scheduled to activate after the PT
date changes, avoiding duplicate 30 September reports already sent by Local.

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
stage results as they actually occur; the sections below supply those facts.

## Final source, immutable artifact and Canary (2026-10-01 UTC)

Owner-authorized [PR #309](https://github.com/OMNOM-111/NT-Analyzer/pull/309)
merged into exact `main` SHA
`91d8a4c1ac25f988b643ff71e119502a1df3d3f7`; mandatory final-main
[CI 36790534580](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36790534580)
passed both required jobs. One signed immutable artifact was built from this
clean SHA, without rebuilding for Production:

- Version `0.10.0-beta.105`; build
  `sf-0.10.0-beta.105-91d8a4c1ac25-20261001T001822Z`;
- artifact `art_dda57f0beab14b83a3375d6ecff1caa8`, candidate
  `rc_0a3fed127f03454898e20dd8cd4da903`;
- archive SHA256
  `2D1DD117E550A5DAD9EB07951DE938AD60BCD44B0F1E4994C258CD9DBAFF482F`;
- signed manifest/runtime SHA256
  `0BE1FDFD05880F589F8CA36EFEFDB24719A44E57379E825AD662D31614DBFDF9`;
- signature verified, production trust tier, Release Center verification PASS.

Verified Canary backup `pre-beta105-canary-peer-20261001T001844Z` retained
database, config, runtime and rollback. Canary deployment
`dep_0a786778906148c4aedd711c39429c34` used this exact artifact.
Focused owner test task `e4d6783b-c39b-5130-a58d-c11a535d3ad2` completed
with a real non-synthetic provider receipt (`REQ-90268773556E4E3A`), one
PostgreSQL worker attempt, one SF Chat delivery attempt, 26/3 tokens, recorded
cost and UI result. `/live` and `/ready` were 200. Final Canary check
`chk_a940ce8e8b8947749fd01dbafe9c8875` is PASS. The previously accepted
beta.103 full-package Canary evidence remains historical; only the beta.105
fix path was rechecked, as the owner requested.

## Same-artifact Production and focused smoke

Verified quiesced Production backup
`pre-beta105-production-peer-20261001T003341Z` retained PostgreSQL (82 tables),
runtime, config and rollback. Its dump SHA256 is
`EE7C68700309BFCBE86668025A3785ECB0359A4894A42BD2C34A3D63BCA9313B`;
runtime archive SHA256
`185ADDC8E8203DD39BCCFBDE35B069C4F1B295543634F7E9F4327067D3239F3C`;
manifest SHA256
`716E8B69664B7A983D483EE8BB0CF7204509A9FBC94D17E7D1EE367D42F34A7F`.
The configured backup role still lacks `BYPASSRLS`, so the verified peer
PostgreSQL path was used; the role defect is separate infrastructure debt.

Release Center initially refused promotion because the signed changelog used
`Change summary:` instead of its required `Release summary:` label. The
candidate's missing metadata was completed from the same shipped text after
protected release-ledger backup
`.artifacts/release-beta105/release-center-pre-summary-20261001T003836Z.dpapi`
(SHA256 `3499C1E19B1DE6F0219FAECD45CF76D85A757887A61EBB7B388C36274D5CD643`).
This was an audited release-record correction only; code, artifact, checks
and trust gates were not changed. The source label is corrected in this
post-deployment documentation closeout.

Production deployment `dep_bd3962b2deda4395bad61cf972a61bf7` switched
the exact Canary release dir
`/home/stratforge/production_data/releases/0.10.0-beta.105-91d8a4c1ac25`.
Both `canary-current` and Production `current` resolve there; Production
`previous` resolves to beta.104
`/home/stratforge/production_data/releases/0.10.0-beta.104-ef263f75a5f5`.
Runtime version/source/build/manifest match the artifact, schema 24 remains
ready, and `/live` and `/ready` returned 200.

One authenticated real Professional shared-model POST task
`b1f7b256-85fd-53c6-b1d9-45a65b2e0862` completed without 524. The
PostgreSQL worker handled it once; Gemini request `REQ-C1ABF81B4DF643B9`
returned a non-synthetic sealed provider receipt, 26 input/3 output tokens,
recorded $0.00 cost, one usage event and matching caller/owner audit. Terminal
SF Chat delivery also succeeded in one attempt and the UI showed
`CONNECTION_OK` and the linked chat result. Owner then disabled sharing for
exact model `0a476279-1a62-591a-bdaa-8d96f96ac5dc`. Exactly one new
Professional request returned “Владелец закрыл доступ к модели”; read-only
inspection found no new task, PostgreSQL job, provider receipt or usage.
History of the preceding response remained. Post-test `/live` and `/ready`
were 200. This is the requested final Production focused smoke PASS, not a
claim to have repeated the full beta.96 acceptance.

## Operational report sender transition

The Production `background-ai-coordinator` has one active PostgreSQL lease;
Production is the explicit operational Telegram owner, Canary is not, and
the owner workspace is resolved. The still-running legacy Local task had
already delivered its 30 September daily, monthly and quarterly summaries.
Enabling those Production flags before the PT date changed would have sent
duplicates, so both settings files were backed up before cutover. Local
settings backup SHA256 is
`226685A8636D75828EDA9FAEBDD964373002C04D491CCECB1A9F714ECFCF0612`;
Production settings backup SHA256 is
`14B085CFC639671ACF464EDDEC2304D396BDD3702B524E080208919C415C9AD0`.

Local Telegram notifications were paused first while its task stayed in
place. Production then enabled only `chief_agent_reports`: the Deputy
controller emitted one `backtest-audit:2026-09-30` event. It completed in one
attempt, produced SF Chat message `MSG-72C68BD8C118`, and exactly one
Production Telegram outbox record `tgo_902fca40f5f647259c1773c4d61d0848`
was marked `sent` on its first attempt at 01:12:54 UTC. No Local/Canary sender
competed. The Local `StratForge Vitek` Scheduled Task definition was backed up
under ignored `.artifacts/release-beta105/` (SHA256
`BEB54D713DD2B50C1503C095738C035B9632A380A1353507878480E69A5803C0`),
then disabled and its remaining launcher/backend processes stopped; no Local
data, reports or prior architecture were deleted. Rollback of the cutover is
the preserved settings backups plus re-enabling this task, never a data wipe.

Daily, weekly, monthly and quarterly Production flags remain OFF for the
remainder of 30 September PT to avoid repeating reports that Local already
sent. A single guarded watcher will activate and verify them after 00:02 PT
on 1 October, provided Local remains OFF, Canary remains non-owner and the
Production singleton lease/live/ready remain healthy. Until its PASS receipt,
full periodic cutover is **PARTIAL** even though the control audit and
Production product smoke are PASS. Preserve the previous-slot beta.104,
beta.103/beta.99 backups, user data and all release evidence. Ordinary-user
Telegram issue #296, the backup-role privilege defect and noncritical UI/UX
remain outside this finished product artifact; Cloudflare Web Analytics/CSP
is a separate post-release stage.

## 30 September 22:54–22:57 PT — owner-approved immediate report cutover PARTIAL

The owner explicitly accepted possible duplicate 30 September reports and
authorized immediate activation instead of waiting until 00:02 PT. The old
watcher PID 41432 was stopped and no second watcher remained. The Local task
stayed Disabled, Local Telegram notifications stayed OFF, Canary operational
delivery was false, and Production had one active coordinator lease. The
verified Production settings backup above remained intact. An operational
helper's explicit same-day owner-approved path enabled the four scheduled
Production settings without changing beta.105 code, artifact or schema.

Production `/live` and `/ready` stayed HTTP 200. The Production controller
published `daily:2026-09-30` once to SF Chat message `MSG-9E555D9F4351` and
Telegram outbox `tgo_b07fe747dbe44116ab05b01f2482566c` was `sent` on
attempt 1. Monthly `monthly:2026-09` and quarterly
`quarterly:2026-Q3` were claimed three times each and ended `failed` before
provider dispatch with `Нет доступной enabled-модели для роли orchestrator`.
No monthly/quarterly report or provider receipt was created. The failed
events remain durable evidence, not a reason to replay them blindly.

Read-only inspection of the exact Production runtime showed the legacy
`agent_router` registry contains 0 models and 0 enabled chat models with a
key; its `app.secure_store` is Windows DPAPI-only and unavailable on Linux.
Daily reporting is deterministic, whereas weekly/monthly/quarterly
`generate_periodic_report()` invokes this legacy `orchestrator` router. The
new owner models and Production SecretStore work through the server AI Center
path, but this periodic route does not consume them. This is a concrete
application-code integration gap, not a missing env flag or permission.
No new code was authorized in this cutover instruction; beta.105 remains
immutable, Production product/model smoke PASS, **full periodic reporting
PARTIAL**, and the current product card must stay In progress rather than Done.
Local remains OFF as directed; Canary is non-sender. Future weekly/monthly/
quarterly delivery requires a narrow reviewed code iteration and real
Canary/Production acceptance, not a direct DB/secret change or silent fallback.
