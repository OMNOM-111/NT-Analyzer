# Production Operations Maintenance

`stratforge-operations.timer` runs one short Production-only maintenance pass
per minute. The pass evaluates stale/degraded service heartbeats and removes
expired Stage 8 records in bounded batches. It uses PostgreSQL only and refuses
Development, API-only, or local-storage execution.

## Install

1. Apply the checksum-confirmed schema migrations before enabling the timer.
2. Install both files from `deploy/production/` into
   `~/.config/systemd/user/`.
3. Keep the protected Production environment file mode `0600`.
4. Enable the timer, not a permanently running duplicate process:

```bash
systemctl --user daemon-reload
systemctl --user enable --now stratforge-operations.timer
systemctl --user list-timers stratforge-operations.timer
```

The timer starts `stratforge-operations.service` with
`STRATFORGE_DEPLOYMENT_ROLE=worker`. Each execution runs the same Production
preflight as the API, worker, and Telegram units.

## Dashboard And Alert Contract

The owner-only Operations dashboard reads PostgreSQL service heartbeats,
connector installations and sessions, job/Telegram queues, dead-letter rows,
and open operational incidents. Ordinary workspace users cannot read this
control-plane or the aggregate AI provider/usage registry.

One open incident is kept per stable fingerprint and notification dedupe key.
The maintenance pass raises or resolves these conditions:

- missing, stale, degraded, failed, or stopping required service heartbeat;
- any job dead-letter (critical), Telegram inbox dead-letter (warning), or
  Telegram outbox dead-letter (critical);
- oldest queued job over 300 seconds;
- oldest Telegram inbox or outbox row over 120 seconds.

Open incidents and active/leased Telegram rows are never deleted by retention,
even if their timestamp has expired. Resolution notifications are emitted once
per incident lifecycle through the same durable Telegram outbox.

## Retention Policy

Cleanup is bounded to at most 5,000 rows per table per pass by default:

| Data | Default retention/removal gate |
|---|---|
| completed/dead-letter Telegram inbox and sent/dead-letter outbox | 30 days |
| AI usage/cost records | 400 days |
| Connector market ingest batch metadata | 7 days |
| stale market snapshots and expired/deleted subscriptions | additional 7 days |
| resolved operational incidents | 730 days |
| audit events | 730 days |
| revoked/expired Connector sessions | additional 90 days |
| service heartbeats / expired leases | 30 days / 1 day |
| expired AI reservations, rate-limit buckets, idempotency keys | after expiry |

Changing these periods requires an owner-approved policy change and a verified,
recoverable database backup. Artifact/report/research retention remains governed
by its object-storage metadata and is not silently deleted by this timer.

## Redaction

Operational payloads, audit details, terminal Telegram errors, and dashboard
documents pass through the shared recursive redactor before persistence or
display. Tokens, passwords, cookies, authorization headers, API keys, pairing
codes, and private-key material must never appear in journal output or alert
messages. Storage errors expose stable error codes, not connection strings.

## Verify And Recover

```bash
systemctl --user start stratforge-operations.service
systemctl --user status stratforge-operations.timer --no-pager
journalctl --user -u stratforge-operations.service -n 100 --no-pager
```

An unsuccessful pass must be investigated from the redacted journal and the
owner Operations dashboard. Do not run the command against a live database
outside systemd, change retention with ad hoc SQL, or substitute Development
storage. The next timer invocation retries a failed pass; a persistent storage
failure remains visible through readiness and the unit result.

To roll back Stage 8 operations, disable the timer and optional alert delivery;
do not delete its tables or queued records. Keep API/Connector commands in
paper/read-only mode, restore the checksum-matched database backup when a schema
rollback is required, and re-enable maintenance only after dashboard/readiness
and a dry run against the restored copy succeed.
