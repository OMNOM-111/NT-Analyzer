# beta.106 — server route for periodic owner reports

Release title: Periodic owner report server route.
Release summary: Monthly, quarterly and weekly SF Chat reports use the existing
owner-scoped Agent World model and ServerSecrets on Canary and Production,
while daily remains deterministic and Local keeps its legacy route.
Release PRs: [#311](https://github.com/OMNOM-111/NT-Analyzer/pull/311).
Affected subsystems: SF Chat periodic reporting, Agent World model execution,
PostgreSQL owner records, ServerSecrets, provider budget and usage accounting.
Release impact: Narrow correction of the beta.105 Production reporting blocker;
no new secrets, permissions, schema, provider, product feature or sender.

## What changes

- Server-only non-daily reports resolve the one active general owner model from
  the existing PostgreSQL Agent World store and decrypt its existing credential
  through the existing ServerSecrets path.
- Every read and provider transmission revalidates the exact owner runtime,
  active account, workspace membership, capabilities and workspace budget.
- Daily reports remain deterministic; Development/Local keeps the legacy
  orchestrator registry; the scheduler, delivery idempotency and sender gates
  remain unchanged.

## Root cause and boundaries

Production beta.105 successfully delivered `daily:2026-09-30`, but
`monthly:2026-09` and `quarterly:2026-Q3` failed before provider dispatch.
The Linux periodic path still called the legacy `agent_router`, whose DPAPI-only
Local registry is intentionally empty on the server. The already verified
owner Gemini connection lived in PostgreSQL and ServerSecrets, but this route
did not consume it.

This change does not add or copy credentials, change sharing, grant access,
change schedules, add a model fallback, or enable another sender. Selection
fails closed unless there is exactly one active owner general Persona model.
Production beta.105 remains the previous/rollback boundary. The durable failed
beta.105 events remain evidence of the original route failure.

## Development verification

- Python compilation: PASS for both application files and both changed test
  files.
- New route/cache/deterministic tests: 8 PASS.
- Related aggregate regression (`chief_agent`, periodic route, Agent World
  models/server parity, owner-model migration and Vitek delivery): 336 PASS.
- Full repository collection with a repository-local `--basetemp`: 6,131 PASS,
  140 skipped and 13 intentional isolation failures because the temporary root
  was inside the repository. The complete affected isolation/preflight subset
  was repeated with an external temporary root: 91 PASS, 1 skipped, 0 failed.
  Clean PR and final-main CI are PASS.
- `NT-Analyzer/.pytest-tmp/` contains local pytest runtime output only and is
  excluded from the release commit.

## Release evidence

- PR #311 merged to exact `main`
  `e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885`; mandatory final-main CI
  [36857075970](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36857075970)
  PASS.
- Candidate `rc_2243013e617841c3864dee1a09c77dc4` produced one signed immutable
  artifact `art_7aebf504ae354ce7981c58359a1ff546`, build
  `sf-0.10.0-beta.106-e7ecd2133c65-20261001T150927Z`, archive SHA256
  `6BD446E5ACB60D74425765550DDA09F2059481822586F24EB78579544128EA25`
  and manifest/runtime SHA256
  `0579C9C3FFD089EC91426D6F75B4E7ED257C612D9FBDD1F958561A50BEB0929C`.
- Canary deployment `dep_5e468f9b9cb04df68aec4e9184882dc4` passed public
  `/live`, `/ready`, identity and non-sender checks. Acceptance check
  `chk_8da170bf754e47f3aa03dd0e1e666642` recorded PASS.
- The same artifact reached Production as deployment
  `dep_bf86528c36c944d1a5906f0586126b93`; Release Center recorded
  `production_live`, `same_immutable_artifact=true`, signature/readiness PASS.
  Public Production `/live` and `/ready` return beta.106, the exact source SHA,
  build and runtime artifact; all readiness checks are green.

## Final Production periodic acceptance — 2026-10-01

The real Production owner session in Microsoft Edge identified the owner and
loaded the shipped beta.106 UI. Three acceptance events were submitted through
that page's existing `window.API.http.vitekEvent` client, which supplies its
session-bound CSRF token to the existing owner-only `POST /api/vitek/events`.
No cookie or secret was copied, no synthetic user/scheduler or direct database
write was used, and each type received **one accepted request** with its own
stable acceptance key. A preliminary raw same-origin POST without the app's
CSRF header received HTTP 403 before admission; read-only status confirmed
zero queued/running events and no provider dispatch. It was not a report run.

| Type / acceptance key | Event / attempts | Owner provider receipt | SF Chat | Telegram outbox |
| --- | --- | --- | --- | --- |
| Weekly `accept-beta106:weekly:2026-10-01-01` | `VE-7B4E4B776973F6D835FD`, completed, 1 | Gemini 2.5 Flash; `REQ-A23C9BAD2BBB494C`; 684 input / 621 output tokens; cost $0.00; report `ORCH-REPORT-BAD1AE85F9` | `MSG-D19294251929` | `tgo_6b5bde80694c43ed8aee6f846e71fb2e`, sent, 1 |
| Monthly `accept-beta106:monthly:2026-10-01-01` | `VE-716D96950E7107DD8155`, completed, 1 | Gemini 2.5 Flash; `REQ-1B569A3B22E94B8E`; 684 / 470 tokens; cost $0.00; report `ORCH-REPORT-AC148D5D9E` | `MSG-73A2D64809F8` | `tgo_c634051b060948feb09081c3706cf2ef`, sent, 1 |
| Quarterly `accept-beta106:quarterly:2026-10-01-01` | `VE-7E1156B9462B4ADF1383`, completed, 1 | Gemini 2.5 Flash; `REQ-CAEE2452A5424E18`; 682 / 464 tokens; cost $0.00; report `ORCH-REPORT-F574835C77` | `MSG-AB1DDD0B3A14` | `tgo_bebee078fed64f5e93a9c83d748ac625`, sent, 1 |

For each key, read-only Production inspection found exactly one completed event,
one successful PostgreSQL `sf_ai_usage_events` row in the owner workspace, one
persisted report file with real non-empty provider response, one indexed and
physically persisted SF Chat message whose content hash matches that report,
and one matching `sf_telegram_outbox` stable-key hash. Outbox documents were
redacted after delivery by normal privacy policy; their status, attempts,
dedupe hash and sent timestamp remain. The model executor disables hidden
provider retries. Report-file reuse, SF Chat `request_id` replay handling and
the outbox's `(bot_identity_hash, dedupe_hash)` uniqueness prevent a repeated
delivery for the same key without issuing a second provider call to test it.
The owner's visible SF Chat displayed all three reports. Daily remains the
unchanged deterministic route already accepted on beta.105; no extra daily
provider call was made.

Final public Production `/live` and `/ready`: HTTP 200 on beta.106 source
`e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885`, runtime artifact SHA256
`0579C9C3FFD089EC91426D6F75B4E7ED257C612D9FBDD1F958561A50BEB0929C`.
One Production coordinator lease remained active; Canary operational delivery
and all report gates stayed OFF; Local `StratForge Vitek` remained Disabled.
The beta.105 monthly/quarterly failed events are retained as historical
evidence, not overwritten. No code, schema, provider, SecretStore, artifact or
environment configuration changed during this acceptance. Production
reporting and the seven-task owner-approved product package are **PASS**.

Verification result: **FINAL Production PASS; Stage Closed.** Release Center's
terminal candidate state is `production_live` (there is no separate literal
`completed` state); the product closeout is recorded here and in Timeline.
