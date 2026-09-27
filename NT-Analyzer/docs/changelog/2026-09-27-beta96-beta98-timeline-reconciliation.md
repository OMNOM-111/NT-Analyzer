# beta.96 → beta.97 → beta.98 Timeline reconciliation

Change title: Preserve the Development-to-server release chronology

Change summary: Reconcile the owner-facing Timeline and current handoff with
the already executed release stages without renaming versions or rewriting
history. This is documentation/evidence only; it changes no application code,
runtime, database, artifact or environment.

Дата: 2026-09-27. Статус: **DOCUMENTATION / PARTIAL RELEASE CLOSEOUT**.
Инициатор решения: владелец проекта. Реализация: AI-assisted change.

## Canonical line

1. `0.10.0-beta.96` is the original Development/Local feature package. The
   owner accepted the current Local version as the release basis on 2026-09-26;
   non-critical visual polish was deferred. The recorded Local runtime is
   source `56945ac68e94cb7ffa031ef2312dec5a9ad80a54`, build
   `dev-0.10.0-beta.96-56945ac68e94`.
2. `0.10.0-beta.97` is the first server release derived from that feature
   package after additional release integration and a new verified main SHA.
   Source `4f6bb0b3a0d20712f249afdc9c93538567fd6a8d`, artifact
   `art_8fec9cdd6ed14dd19cb762291a2a756f`, build
   `sf-0.10.0-beta.97-4f6bb0b3a0d2-20260927T060203Z`, archive SHA256
   `F7B522C845D4DEA93BFB15F09C37F5B25A95A0C474052FB70F27A2F6DA6F8FF3`,
   manifest/runtime SHA256
   `B5FC667474ED38CD5AA3600F22E4DD97495958DCC906BCEAD1CA80CF2838F9D2`.
   The owner authorized PR #294 merge and separately approved Production
   promotion of this exact artifact. Canary acceptance and Production
   publication completed; final closeout later stopped on the live reload-loop.
3. `0.10.0-beta.98` is the next immutable hotfix cycle for that confirmed
   reload-loop. Source `0b9233d7c8983adc0a3a6c37350a3974770cb738`, final-main
   CI run `36346357025` PASS, artifact
   `art_b05720a1f2d44672805b45b513f0203e`, candidate
   `rc_8b8b51c156f844ce9829edeceb70e484`, build
   `sf-0.10.0-beta.98-0b9233d7c898-20260927T210136Z`, archive SHA256
   `FEC858A913F5B90455ED34E10071204859D2CB2CC64EC1E0BC8024FD50CB5029`,
   manifest/runtime SHA256
   `F0E48884C3933E487349C8AB3673989FC5FEF180B85B72F7A507EE7EAA312D43`.
   It is deployed to Canary. Identity/readiness, restart persistence and owner
   offline cold-start are PASS; real separate Professional cold-start acceptance
   remains pending. Production remains beta.97 and no beta.98 Production approval
   has been requested.

## Telegram/reporting facts carried by beta.97

- a real owner SF Chat ↔ Telegram exchange passed in both directions in the
  intended conversation;
- the topic/conversation binding survived restart;
- stable message/request/report keys prevent duplicate delivery, loops and
  repeated model invocation;
- periodic reporting was consolidated to
  `Пользователь → Заместитель → команда`, with Vitek acting as the technical
  controller for the Deputy role rather than an extra organizational layer;
- Production accepted operational ownership for the shared owner Telegram
  route, while final report-scheduler cutover remains paused during beta.98;
  Local `StratForge Vitek` stays enabled until the model/orchestrator route and
  Production closeout are separately accepted.

Ordinary-user multi-user Telegram is **not** a completed beta.97/beta.98
capability. Issue #296 remains the next separate work item. A new real Google
Professional user reproduced a pairing defect: registration/linking → Open
Telegram → Start produced no expected confirmation/linking step. The user was
not added to the owner forum. Exact acceptance must later cover personal
user/workspace/conversation/chat/thread binding and fail-closed isolation.

## Mandatory chronology rule

Before development, merge, artifact creation or release, every agent reads the
root Timeline and current handoff. Work either extends the still-open current
package or, after Production publication, starts a new version/card. A version
must exist as a concrete source/commit with Development/CI evidence and a
Timeline entry before its immutable artifact reaches Canary or Production. Any
application-code change during release increments the version. Timeline and
handoff are updated immediately after merge, artifact creation, Canary
acceptance and Production promotion.

This record is intentionally not part of the already signed beta.98 archive.
It records operational evidence without rebuilding or mutating
`art_b05720a1f2d44672805b45b513f0203e`.
