# beta.104 — bounded authenticated AI Center reads

Release summary: Ускорение авторизованного чтения AI Центра без изменения прав или provider path.
Release PRs: pending
Affected subsystems: AI Center read projection, Agent World admission, PostgreSQL server read path.
Release impact: Новый source/CI/artifact/Canary обязателен; beta.103 Production не изменяется до принятого same-artifact promotion.

Status: Development implementation and focused Local tests PASS; PR/main CI,
artifact, Canary and Production are pending. This is a technical release
iteration of the existing owner-approved Local beta.95 → beta.96 product card,
not a new product milestone. Production beta.103 remains live; its scheduler is
OFF and Local `StratForge Vitek` remains ON. No Production provider call has
been made for this correction.

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
