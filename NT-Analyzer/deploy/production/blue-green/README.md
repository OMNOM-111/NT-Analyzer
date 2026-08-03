# Blue-green deployment assets (Phase 9)

This directory is the **template-only**, secret-free contract for zero/minimal
downtime blue-green Production deployment of the single canonical host
`app.stratforges.com`. It contains examples only; tunnel credentials, database
DSNs, signing keys, bot tokens and OAuth secrets never belong in a release
artifact, in Git or in any script here.

> Phase 9 status: the real blue-green **executor is not wired**. The Release
> Center (`app/release_center.py`) drives the blue-green plan through
> `app/blue_green.py` as a **fail-closed dry-run**: it produces the ordered
> slot / expand-migrate / drain / switch / rollback plan and records evidence,
> but performs no SSH, systemd, symlink switch, DNS, Cloudflare or database
> command. Every external result stays `pending`, never a real `pass`.

## Deployment model (owner decision #7 — symlink/current-release switch)

Two release slots, one atomic `current` symlink:

```
~/apps/stratforge/
  releases/
    <build_id_A>/        # slot "blue"  (currently live)
    <build_id_B>/        # slot "green" (staged next release)
  current -> releases/<build_id_A>
  shared/                # persistent data, sockets, logs (never per-slot)
```

Deploy = stage the new immutable artifact into the idle slot, run only
online-safe **expand** migrations, gate on **green readiness**, gracefully
**drain** the outgoing (blue) workers, then atomically repoint `current` to
green. Destructive **contract** migrations are deferred until green is stable.
Rollback = repoint `current` back to the previous known-compatible slot while
persistent data under `shared/` is preserved.

## Files

- `switch-release.sh.example` — reference symlink-switch script. Refuses to run
  unless `STRATFORGE_BLUEGREEN_CONFIRM=1` is set, and prints the intended action
  first. Illustrates the atomic `ln -sfn` swap and `systemctl --user reload`.
- `stratforge-release@.service.example` — templated per-slot API unit example
  (`stratforge-release@green.service`) for running blue and green side by side
  behind the edge before the traffic switch.

## Expand → migrate → contract discipline

Only additive **expand** migrations may run before the switch so that old (blue)
and new (green) code remain schema-compatible during the overlap. Any migration
that drops a table/column/constraint, rewrites a column type, sets `NOT NULL`,
renames, truncates or deletes rows is classified **contract** and is deferred
until green is stable and blue is retired. `app/blue_green.classify_migrations`
computes this split; the Release Center blocks the online expand stage when a
pending contract migration is detected.

## Worker drain, webhook/outbox de-duplication

Before the switch, blue stops accepting new intake and its in-flight NinjaTrader
resource leases and jobs are allowed to finish within
`worker_shutdown_grace_sec`. A dry-run never force-terminates in-flight work.
During the brief overlap both slots may observe the same Telegram webhook update
or outbox message; `app/blue_green.dedupe_events` provides the idempotency keys
so neither slot double-processes a delivery.

## Do not

Do not expose the release slots, port 18765, RDP, NinjaTrader IPC, a Windows
share, debug routes or metrics to the Internet. Do not place secrets in a slot
directory; they live only under the protected `~/.config/stratforge/` and
`shared/` outside the release artifact.
