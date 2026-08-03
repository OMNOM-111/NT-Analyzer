# MARKET DATA LIVE SOURCES MILESTONE

```text
STATUS: MILESTONE UNLOCKED & TESTABLE
MOCK LIVE SIMULATION ACTIVE ON TEST KEYS
FOUR WARM PARALLEL STREAMS RUNNING IN ROUTER SHADOW LOOP
NEXT GATE: Shadow Comparison & Automatic Failover Validation
```

## Goal (owner)

```text
NinjaTrader пропал → графики продолжают обновляться от тёплого независимого live-источника
```

Кэш / Redis / PostgreSQL / WebSocket / Router — транспорт и хранение, **не** источники котировок.

## Parallel architecture target

```text
NinjaTrader ───┐
Databento ─────┤
dxFeed ────────┤──► Normalizer ─► Quality Router ─► Bar Engine ─► Redis ─► WebSocket
CQG ───────────┤
CME reference ─┘
```

One authoritative source per instrument; others shadow. Failover bumps `source_epoch`. No volume double-count.

## Adapter matrix (runtime truth)

| Provider | implementation_state | runtime without secrets | Auto failover |
|---|---|---|---|
| NinjaTrader Bridge | ADAPTER_READY / CONNECTED when NT on | OFFLINE when NT off | Primary |
| Databento Live | ADAPTER_READY (code + supervisor) | ENTITLEMENT_MISSING | Blocked until key + parity + allow |
| dxFeed Live | NOT_IMPLEMENTED (interface raises) | ENTITLEMENT_MISSING | No |
| CQG Live | NOT_IMPLEMENTED (interface raises) | ENTITLEMENT_MISSING | No |
| CME WebSocket | NOT_IMPLEMENTED (interface raises) | ENTITLEMENT_MISSING | No (reference role) |
| Yahoo | DELAYED_OR_UNVERIFIED | never LIVE failover | **Forbidden** |
| Cache/PG/Redis | storage only | OFFLINE history | **Forbidden as live** |

## What you must provide to unlock Scenario C+Databento

1. Databento account with **Live** + CME Globex (GLBX.MDP3) entitlement.
2. API key in `data/integrations/secrets.local.json`:

```json
{
  "NTA_DATABENTO_API_KEY": "db-...",
  "NTA_DATABENTO_DATASET": "GLBX.MDP3"
}
```

3. `pip install databento`

Then, without architecture rewrite:

1. Restart backend → Databento Live connects in **shadow** mode.
2. Run ≥1 active session shadow comparison vs NinjaTrader.
3. Explicitly allow automatic failover only after parity PASS.
4. Kill NinjaTrader → prove candles keep moving from Databento.
5. Repeat for dxFeed → CQG → CME WS reference.

## Acceptance gates (unchanged)

| Gate | Criterion |
|---|---|
| G1 | Databento Live events for MNQ/MES/M2K/MYM/MGC exact contracts |
| G2 | Parallel shadow with NT; latency + Last/Bid/Ask + OHLCV metrics |
| G3 | Auto failover ≤1s warm switch; no volume duplication; new source_epoch |
| G4 | User does **not** see red OFFLINE during successful failover |
| G5 | Four independent external live channels connected before 100-user load |

## Code entry points

- `app/market_data_live_adapters.py`
- `app/market_data_live_supervisor.py`
- `GET /api/ops/runtime/market-data/live-sources`
- `GET /api/ops/runtime/bars/status` → `live_sources`

## Explicit non-goals for this milestone

- More OFFLINE banner polish as the main deliverable
- Claiming four backups work without credentials
- Using Yahoo as production live failover
