# Production blue-green deployment runbook (Phase 9)

This runbook describes the zero/minimal-downtime blue-green Production
deployment procedure for the single canonical host `app.stratforges.com`. In
this phase the real executor is **not wired**: the Release Center
(`app/release_center.py`) drives the blue-green plan through `app/blue_green.py`
as a **fail-closed dry-run**, so every step below is planned and recorded but no
SSH, systemd, symlink switch, DNS, Cloudflare or database command is performed.
The external result of every step stays `pending`, never a real `pass`. Real
Canary deployment and exact-artifact Production promotion remain owner-gated.

The deployment templates live in
[deploy/production/blue-green/README.md](../deploy/production/blue-green/README.md).

## Preconditions

1. The exact immutable artifact has passed Canary and holds a live owner
   approval bound to the same artifact SHA, manifest SHA, commit SHA and build id
   (Phase 8 exact-artifact invariants).
2. A fresh owner step-up grant exists for the promotion action.
3. `app/blue_green.classify_migrations` reports the pending migration set is
   **online-safe** (no contract migration in the expand phase). If a contract
   migration is pending, the online expand stage is blocked and the contract
   migration must be deferred behind green stability.

## Deployment stages

The blue-green plan is an ordered, idempotent stage list. `current` is the
atomic symlink; `blue` is the live slot, `green` the idle target slot.

1. **prepare_green** — stage the promoted artifact into the idle slot
   (`releases/<build_id>`). No traffic yet.
2. **expand_migrate** — apply only online-safe expand (additive) migrations so
   blue and green stay schema-compatible. Contract migrations are NOT run here.
3. **start_green** — start the green instance beside blue behind the edge.
4. **green_readiness** — gate on the full readiness contract
   (`service_readiness`): database, queue, object storage, signing key,
   connector control and telegram consumer must all be ready. Never switch to a
   not-ready green.
5. **drain_blue** — stop new intake on blue and let in-flight NinjaTrader
   resource leases and jobs finish within `worker_shutdown_grace_sec`. A dry-run
   never force-terminates in-flight work.
6. **switch_traffic** — atomically repoint `current` to green (`ln -sfn`) inside
   a recorded maintenance window. Old and new webhook/outbox deliveries are
   de-duplicated by idempotency key so neither slot double-processes.
7. **verify_live** — confirm green is serving and healthy; publish the
   `reload_available` notification.
8. **contract_migrate** — only after green is stable and blue is retired, run any
   deferred destructive contract migrations.

## Rollback

Rollback is the reverse symlink switch to the previous known-compatible slot
(`app/blue_green.plan_rollback_switch`). Persistent data under `shared/` is
preserved; rollback only targets a previously Production-deployed artifact
(Release Center `rollback_incompatible` guard). After rollback, verify readiness
and drain the failed slot.

## Rehearsal (safe, dry-run)

Owners and delegated release admins can rehearse the whole plan without any live
effect via the Release Center detail drawer («Репетиция blue-green») or
`POST /api/admin/releases/{id}/rehearse-bluegreen`. The rehearsal reports
`online_safe`, any `blocked_stages`, the drain plan, the green readiness
contract, the traffic-switch plan and the rollback path. Nothing is deployed,
migrated, drained or switched.

## What is intentionally NOT done in this phase

- No real Canary deployment and no real exact-artifact Production promotion.
- No SSH, systemd, symlink switch, DNS, Cloudflare or database command.
- No real signing key, Production credential, Telegram credential or Connector
  session is used. Missing external infrastructure is reported as
  PENDING/BLOCKED, never as PASS.
