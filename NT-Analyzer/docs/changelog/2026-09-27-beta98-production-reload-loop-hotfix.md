# beta.98 — Production overview reload-loop hotfix

Release title: Production overview reload-loop hotfix

Change summary: Stop the authenticated Aurora overview from issuing an endless
full-page reload when the connector account snapshot is already offline or
unconfirmed. Preserve the one-time refresh for a real selected-account
transition from live to offline; do not weaken login, device confirmation or
session checks.

Release PRs: #295

Source checkpoint SHA: `8246237c`; final source SHA is assigned only by the
verified merge to `main`.

Verification result: IN PROGRESS (targeted regression PASS; full pre-release,
PR CI, merged-main CI, immutable artifact, Canary and Production remain gated)

Affected subsystems: Aurora overview, runtime account status, authenticated
owner/professional sessions, release/version records. No auth/device, Telegram,
report scheduler, market-data or user-data code is changed.

Release impact: new immutable release cycle `0.10.0-beta.98`; no Production
hotfix or in-place artifact mutation is permitted.

Дата: 2026-09-27. Статус: **BETA / hotfix candidate**. Инициатор решения:
владелец проекта. Реализация: AI-assisted change.

## Live incident evidence

Production currently serves `0.10.0-beta.97`, source
`4f6bb0b3a0d20712f249afdc9c93538567fd6a8d`, build
`sf-0.10.0-beta.97-4f6bb0b3a0d2-20260927T060203Z`, artifact
`art_8fec9cdd6ed14dd19cb762291a2a756f`. Archive SHA256 is
`F7B522C845D4DEA93BFB15F09C37F5B25A95A0C474052FB70F27A2F6DA6F8FF3`;
manifest/runtime SHA256 is
`B5FC667474ED38CD5AA3600F22E4DD97495958DCC906BCEAD1CA80CF2838F9D2`.

Live CDP evidence showed a genuine Document navigation with type `reload`, no
redirect and no service-worker controller. Authentication status, device
confirmation, support polling and telemetry returned normally; the active owner
session was neither expired nor revoked. No runtime exception initiated the
navigation.

The exact loop was:

1. `wireSystemStatus()` receives a graded runtime-account response with
   `confirmed_live=false`.
2. `assets/ui.js` clears the already absent selected account and unconditionally
   emits `nt-account-change` with `detail:null`.
3. `assets/pages/overview.js` responds with `location.reload()`.
4. The new page repeats the same cold-start branch.

Blast radius: authenticated non-Beginner overview sessions (owner and ordinary
Professional users) whenever the connector/account runtime is graded offline or
unconfirmed. Beginner shell and pages without the overview listener are not in
this loop. beta.92 contains the same two trigger lines, so switching to the
preserved beta.92 slot would not reliably resolve the incident under the same
runtime state; rollback was therefore not executed.

## Scoped correction

The runtime-account callback now remembers whether an account was actually
selected before it clears offline state. It emits the null account-change event
only for a real selected-account transition. A cold page load that is already
offline emits no event, so the overview remains stable. Manual account selection
and the live-to-offline notification contract remain unchanged.

Targeted verification:

- offline cold start: zero account-change events;
- repeated offline evaluation: zero events;
- confirmed-live account load: selection preserved, zero false events;
- live-to-offline transition: exactly one null event, then stable;
- manual account selection dispatch contract remains present;
- affected Aurora/release/pre-release suite: 143 PASS;
- `python tools/pre_release_check.py`: PASS for the 651-file production bundle;
- `python tools/validate_external_gpt_context.py`: PASS;
- `node --check` and `git diff --check`: PASS.

## Telegram multi-user acceptance finding

The requested real second-user Telegram-to-SF-Chat acceptance is **EXTERNAL
BLOCKED by the current application architecture**, not passed. beta.97 has one
shared bot and strong scoped SF Chat records, durable delivery/dedupe and worker
scope revalidation, but ordinary users do not receive their own Telegram forum
topics or bidirectional mirror. The topic registry is global by conversation
inside one shared forum, and Telegram itself cannot hide one forum's topic
history from other members. Adding a second user to the owner forum would be an
unsafe test, so it was not done.

The existing foreign-topic refusal remains fail-closed and does not invoke the
foreign user's agents, but its UX is plain text and lacks a safe own-chat/pairing
action. Completing the requested contract requires a separate scoped design and
release: the same bot token with a private per-user/workspace container (or
private bot DM without native topics), a registry keyed by user/workspace/
conversation/chat/thread, sender and thread validation, fail-closed legacy
unscoped topics, and an explicit own-chat/create/pair CTA.

## Operational safety during the incident

- Production periodic-report scheduler remains OFF.
- Local Windows task `StratForge Vitek` remains ON until a verified Production
  replacement exists.
- The preserved rollback slot remains beta.92; no data, message history, report,
  key, model or rollback evidence was deleted.
- The verified pre-beta.97 backup remains at
  `/home/stratforge/production_data/backups/pre-beta97-production-peer-20260927T163711Z`.
- The backup-role `BYPASSRLS` defect remains separate infrastructure debt.

Current closeout: **IMPLEMENTATION COMPLETE pending full verification**;
**GIT CLOSEOUT IN PROGRESS**; **STAGE NOT CLOSED**.
