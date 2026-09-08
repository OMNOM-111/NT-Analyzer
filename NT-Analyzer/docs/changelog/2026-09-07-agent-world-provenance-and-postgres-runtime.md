# Agent World — provenance as a finding, and PostgreSQL as the runtime store

- Release title: Agent World — a report that fails the source check stops being
  called a NinjaTrader result, a local answer stops being credited to a
  provider, and an instance actually runs on PostgreSQL
- Change summary: an earlier claim in this branch's own report is withdrawn —
  the live "automatically verified" backtest rested on a fixture that declared
  itself a NinjaTrader run, and the verifier was right to accept what it was
  told. Re-marking it honestly exposed the real defect: everything downstream
  went on describing refused content as a NinjaTrader result. Provenance is now
  a finding carried by the verification, and a second attribution defect —
  a locally computed answer displayed as the connection provider's reply — is
  fixed the same way. Alongside that, a second instance was run end to end with
  `STRATFORGE_AGENT_WORLD_STORAGE=postgres` on a disposable database, and the
  delegation limitation is stated as the functional gap it is rather than as an
  external dependency.
- Canonical status: `IN DEVELOPMENT` unchanged. This corrects a claim and closes
  named gaps; it is not programme acceptance and not owner visual acceptance.
- Branch: `claude/agent-world-integration`, local and unpushed. No PR opened;
  PR #282, #283, #284 and their bases were not touched, and nothing was pushed
  to a Codex branch.
- Version: `0.10.0-beta.96` unchanged. No merge to main, deploy, signing, SQL
  migration, flag default change, owner-key copying, budget increase, paid call
  or trading order. Migrations remain 1–23. Local 8765 was not switched, not
  restarted and not written to; the single contact with it was one read-only
  `GET /api/auth/status`.

## Why

The previous report presented a live browser table in which a seeded backtest
showed «Автоматическая проверка завершена». That fixture's `result.json` said
`execution_source: "ninjatrader"` and carried no test marker, so the verifier
did exactly what it should with a self-consistent report claiming a real run.
The verifier was not wrong; the fixture lied, and the report repeated it.

Marking the fixture honestly produced the refusal it should always have had —
and made a second problem visible immediately: the refusal and the label sat in
the same view, contradicting each other.

## What changed

### Provenance is a finding, not a folder

`LiveBacktestService._verification` now reports `source_confirmed`, false
exactly when `ninjatrader_source_required` is among the reasons, and `synthetic`
follows it. The chat message, the task, its artifacts, its activity entries and
its contribution all read that one finding instead of a hard-coded
`synthetic: False`. A genuine run whose evidence is merely damaged keeps its
confirmed origin: damaged evidence and a refuted origin stay separate findings.

No guard was relaxed. `ninjatrader_source_required` fires on exactly the
conditions it did before, and the handoff gate still requires `passed is True`.

### A local answer is not the provider's answer

`ModelService._clean_receipt` dropped the `executor` and `external_call` the
executor reports, so a result computed on this machine reached the inspector
carrying only the connection's provider. Both fields now survive into the
receipt, the evaluation proof and the task detail, and the page says «Провайдер:
… — не вызывался», names what did answer, and states that the result says
nothing about the provider's availability.

### PostgreSQL, exercised rather than asserted

A second instance ran on the disposable database: persona and connection created
through the normal API, a safe non-trading task executed by its own worker, the
result persisted with its independent evaluation, the instance restarted, and
the same history read back unchanged. The rows are in PostgreSQL and visible to
the unprivileged `stratforge_app` role (no `SUPERUSER`, no `BYPASSRLS`); a
foreign workspace sees none of them and cannot insert into one. No Agent World
SQLite file is created in that data root at any point.

Storage selection is now pinned as well: unset gives SQLite, `postgres` without
a DSN raises `agent_world_postgres_not_configured`, any other value raises
`agent_world_storage_backend_invalid`, and a configured DSN produces the
PostgreSQL repository — there is no fallback.

### The automation drawer says what each grant is

Four grants rendered as four identical «Запись · Статус не указан» cards. Each
now names what it authorises and whether it is operational *right now*, which is
not the same as its status: an approved grant whose window has closed
authorises nothing.

## What this does not claim

- No verified NinjaTrader result exists on this branch. The trading-facts
  handoff stays blocked, and its guard was not weakened to unblock it.
- The delegated-work graph is implemented but has only one kind of root — a
  verified application result. Delegating from an ordinary verified non-trading
  task is refused with `handoff_verified_source_required`. That is a functional
  gap, recorded rather than closed.
- Nothing a synthetic run touched counts as a real user connection or a real
  model evaluation. The local test executor's answers reach neither
  `agent_registry.record_usage` nor `ai_ratings.record_rating`, and tests pin
  that.
