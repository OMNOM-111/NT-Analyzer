# beta.104 — bounded authenticated AI Center reads

Release summary: Ускорение авторизованного чтения AI Центра без изменения прав или provider path.
Release PRs: #308 (merged)
Affected subsystems: AI Center read projection, Agent World admission, PostgreSQL server read path.
Release impact: Новый source/CI/artifact/Canary обязателен; beta.103 Production не изменяется до принятого same-artifact promotion.

Status: PR #308, final-main CI, signed artifact and focused Canary PASS;
Production beta.104 live/ready but final model/SF Chat smoke PARTIAL. This is a
technical release iteration of the existing owner-approved Local beta.95 →
beta.96 product card, not a new product milestone. Production scheduler is OFF
and Local `StratForge Vitek` remains ON.

## Why

After the beta.103 Production Agent World allowlist was corrected for the exact
owner and Professional workspaces, both confirmed sessions passed auth, device,
workspace, entitlement and PostgreSQL/RLS checks. The authenticated AI Center
model/overview reads nevertheless took tens of seconds and sometimes returned
Cloudflare 524; anonymous 401, `/live` and `/ready` answered quickly.

A read-only Production diagnostic using the exact beta.103 code and existing
confirmed owner/non-owner sessions measured the boundary without provider
dispatch or secret output. One owner model list opened 310 PostgreSQL
connections and took 3.8–4.1 s; one complete owner overview opened about 1,321
additional connections and took about 17 s. The Professional path behaved
similarly (235 connections for models, about 1,128 more for overview). Most time
was repeated recursive authority/admission refresh in nested read projections;
PostgreSQL connection setup alone accumulated about 14–16 s per full path.
Browser Network observed a 200 overview after 33 s and a 200 models list after
58 s; another authenticated models request reached Cloudflare 524. There was
no long PostgreSQL lock, missing SecretStore, worker wait or provider request on
this ordinary GET path.

## Narrow correction

`read_projection_authority` reuses the already-validated authorization only
inside one read-only AI Center HTTP projection. Repository reads still use
scoped PostgreSQL RLS. Before response serialization it rechecks the real
session, workspace, capability and Agent World flag snapshot; changed authority
fails closed. Writes, automation, Preview, worker dispatch and provider paths
are untouched. Applied only to the model GET and fresh overview GET that were
measured as slow. No timeout increase, security bypass, DB/schema/config change
or beta.103 artifact rebuild.

The same isolated Production diagnostic, with this request-local behavior
simulated solely in a separate read-only process, reduced owner model list to
0.40 s / 35 connections and overview enrichment plus summaries to about
1.2 s / 96 connections; non-owner model list to 0.11 s / 7 connections and
overview to about 0.35 s / 26 connections. The final fresh authority check
remained present. These measurements are Development evidence, not a claim that
beta.104 has reached Canary or Production.

## Verification and next gates

- Focused domain/server parity suite: 112 PASS; targeted HTTP regression PASS.
- Regression covers bounded repeated admission, final session/capability
  revalidation, failed write-mode refresh and actual models/overview HTTP GET.
- Required next sequence: PR checks → owner-authorized merge → CI on final main
  SHA → one signed immutable beta.104 artifact → focused Canary regression and
  `/live`/`ready` → same artifact in Production → owner and real Professional AI
  Center reads, then the previously agreed one-call shared-model smoke.
- beta.103 Canary PASS and Production preflight evidence, including PR #307,
  remain historical facts; beta.104 does not rename or replace those records.

Production beta.103 identity remains source
`d695a8ddc5dccfc1252f0e94d59bb4e5325bc601`, artifact
`art_9d38fcd7bd33454786fdbfaf0e9cc25a`. Its Product card cannot be marked
Done before the real Production acceptance and operational reporting cutover.

## Actual release and Production PARTIAL (2026-09-30)

PR #308 merged to final `main` SHA
`ef263f75a5f5ec8c42e652738199e852cac8b677`; mandatory final-main CI
`36717621054` PASS. Immutable signed beta.104 artifact
`art_b2ab8a4e5a19476b84fc2a3c1c8bfe89` (candidate
`rc_25e812dbc75a4755b8543c56569892d0`, build
`sf-0.10.0-beta.104-ef263f75a5f5-20260930T142556Z`) has archive SHA256
`6AB34734C0D3406634AE4E050AE957D05FCBB296B281FD9DF015C3D533D9BD1A`
and runtime/manifest SHA256
`53074CE10A09D717D591E8CF79D7CA6D77325CCC6CEA029E9375935A1EB61C29`.
Verified Canary backup `pre-beta104-canary-peer-20260930T143153Z` preceded
deployment `dep_c99644fdfec74a56854d323cf6d5ae96`; owner and genuine
Professional GET paths returned 200 without 524, with `/live` and `/ready` 200.
Release Center focused Canary check `chk_8d0858b26ede49428aa06d394d229655`
is PASS. Verified Production backup
`pre-beta104-production-peer-20260930T144651Z` (82 PostgreSQL tables,
`pg_restore` verification, runtime/config snapshot) preceded same-artifact
Production deployment `dep_71fc9281696a47c0aed6c9b2fad657c5`. Production
version, source/runtime SHA, `/live` and `/ready` matched beta.104; owner and
Professional authenticated GET paths returned 200.

Exactly one new bounded Professional shared-model task
`406d5586-f3cd-5315-b8c6-b3f853d388e8` was submitted. The HTTP POST
reached Cloudflare 524, but read-only durable inspection established that the
PostgreSQL worker completed one genuine Gemini request
`REQ-07D49CFB78B34507`: non-synthetic receipt
`6de351c0-92e2-500c-9681-3ad4e4129c41`, 58/34 tokens, $0.00, one usage
event and matching caller/owner model-call audit. No retry was made. Separate
terminal SF Chat delivery job
`wj_aw_delivery_406d5586f3cd5315b8c6b3f853d388e8_abf5860f7d8550efa6a1b6d3d3a2254b`
dead-lettered with `model_delivery_claim_required`: its claim validator expects
Local SQLite `worker_id`/`locked_until`/`deadline_at`, but Production queue
supplies PostgreSQL `lease_owner`/`lease_token`/`leased_until`/`started_at`/
`timeout_sec`. Thus provider/receipt/ledger PASS is not whole-path PASS.
Authenticated model POST still has repeated nested admission and expensive
budget reads, unlike the beta.104 optimized GET. A narrow beta.105 code fix
and new release cycle are required; beta.104 remains immutable. Share remains
on for one existing model until acceptance, scheduler OFF, Local task ON. PR
#307 remains historical PARTIAL/Canary evidence, not a runtime fix.
