# Market-data runtime failure — 2026-07-16

```text
IMPLEMENTATION PARTIAL
RUNTIME ACCEPTANCE FAILED
NO LIVE FAILOVER AVAILABLE
STALE DATA SAFETY DEFECT
PRODUCTION BLOCKED
```

Forbidden until owner visual pass: `ENGINEERING COMPLETE`, `DEPLOYED` (verified), `ACCEPTANCE PASSED`, `PRODUCTION FAILOVER COMPLETE`.

## Timeline (owner manual stop of NinjaTrader)

| Time (approx PT) | Observation |
|---|---|
| NT stopped intentionally | Global NinjaTrader indicator red; Latency red |
| Desktop grid open | Most panels still showed candle history labeled NinjaTrader |
| One/more panels | Infinite «Ожидание данных NinjaTrader...» |
| Page reload / app restart | Long waits / timeouts across many instruments |
| After wait | Static historical snapshot appeared; looked like a working chart |
| Prices | Not updating; green/red price markers still looked “live” |
| Backup providers | None active as live |

## Runtime flow after NT disconnect (code audit)

```text
Each chart → HTTP /api/market-bars (batch) + optional WS
  → server._market_bars_payload
  → market_data.register_request (Bridge request file)   [was still written]
  → market_data.read_runtime_series (market_bars.json cache)
  → market_data_failover.apply_failover(primary_healthy=False)
       → need_external=True
       → fetch_external_series(order=databento,yahoo)
            → Databento skipped (not_configured)
            → Yahoo HTTP timeout ~12s PER SERIES (major load delay)
       → BEFORE FIX: Yahoo age within freshness window → live=True / failover_live
       → AFTER FIX: Yahoo never live_eligible; offline when no live backup
  → UI painted last bars without OFFLINE watermark
```

### Why router did not select a reserve

| Provider checked | Result |
|---|---|
| Databento | `configured=false` — no `NTA_DATABENTO_API_KEY` |
| Yahoo | Delayed only — not production failover eligible |
| Recorded / FaultInjection | Test-only |
| CME / dxFeed / Rithmic / CQG | Not connected |

### Where post-wait candles came from

| Layer | Role |
|---|---|
| `data/runtime/market_bars.json` | Last Bridge snapshot (often still `status: live` on frozen series) |
| `jobqueue.read_instrument_bars` | Historical artifact fallback |
| Yahoo (before fast-path) | Delayed root series after long timeout — could contaminate perception of “freshness” |
| In-memory `_MARKET_BARS_PAYLOAD_CACHE` | Could re-serve prior `live=True` until sanitize |

### Why panels still said NinjaTrader

Chart header used `source.provider` / `source.kind` from the **last** primary payload (`ninjatrader_runtime`), not global health.

### Why one chart stayed loading

Empty series + `status=waiting` / `subscription_requested` → UI waited for Bridge forever (`Ожидание данных NinjaTrader...`).

### Bridge DLL deployment (after NT stop)

| Item | Value |
|---|---|
| Installed | `%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.dll` |
| Size | 187904 |
| SHA256 | `C19F09A08CAE4A787B26B4BAF49715345522DD3A20C7CA16673FABD628B95E3F` |
| Matches Release build | Yes |
| Backup | `NTAnalyzerBridge.dll.bak-deploy-20260716-213853` |
| NT process at deploy | Stopped |

Build without install was previously incomplete; file is now installed. Full callback→IPC→WSS proof still needs Scenario B with NT running.

## Root causes

1. **No live backup** — nothing production-eligible to fail over to.
2. **False LIVE** — Yahoo / frozen Bridge snapshot / payload cache could claim live.
3. **Timeout storm** — per-panel external HTTP when NT dead.
4. **UI safety gap** — no global OFFLINE banner; price markers looked live; infinite loaders.
5. **Tests ≠ production** — green unit tests did not catch owner Scenario A.

## Fixes in this incident response

| Fix | Location |
|---|---|
| Yahoo never LIVE / never `live_eligible` | `market_data_failover.py` |
| `mark_offline_snapshot` + offline when primary unhealthy & no live backup | `market_data_failover.py` |
| **Skip delayed providers entirely** when NT offline and no Databento (fast OFFLINE cache) | `apply_failover` + `live_backup_candidates` |
| Circuit breaker on Bridge request writes when HB present & unhealthy | `market_data.py` (pytest fail-open) |
| Sanitize cached LIVE while NT offline; don’t cache offline as live | `server.py` |
| Historical fallback also marked OFFLINE when NT unhealthy | `server.py` |
| Desktop OFFLINE banner; never green LIVE without `live && freshness.fresh`; kill loaders; slower poll | `desktop.js` / `desktop.html` |
| Mute last-price axis tag when not LIVE (`setLivePriceEnabled`) | `chart-engine.js` |
| Provider capability split + backup matrix | `MARKET_DATA_BACKUP_MATRIX.md` |
| Tests | `tests/test_market_data_offline_safety.py` |

## Scenario table

| Scenario | Expected | Actual | PASS/FAIL | Evidence |
|---|---|---|---|---|
| A: NT off, no Databento | Fast cache, all OFFLINE, no false LIVE, no Yahoo timeout storm | Automated offline/failover contracts pass; real owner runtime scenario not repeated | **PASS automated / BLOCKED runtime** | pytest 682 |
| A UI | Global banner + muted markers + no infinite loader | DOM/JS contracts pass; visual hard-refresh not run | **PASS contract / BLOCKED visual** | `test_aurora_contracts.py` |
| B: NT on | LIVE via Bridge IPC + WSS | DLL installed and hash-matched; live callback not run | **BLOCKED runtime** | Release build + SHA-256 |
| C: NT kill mid-session | ≤2s OFFLINE/DEGRADED, no false LIVE | State-machine contracts pass; controlled live kill not run | **PASS automated / BLOCKED runtime** | market-data tests |
| C + credentialed backup | FAILOVER continues live | No accepted live entitlement | **BLOCKED credentials** | — |
| D: NT restore | Shadow + hysteresis before switchback | Router logic covered; real restore/switchback not run | **PASS automated / BLOCKED runtime** | router tests |

## Evidence commands

```text
python -m pytest tests/test_market_data_offline_safety.py tests/test_market_data.py -q
Get-FileHash …\Custom\NTAnalyzerBridge.dll
# After backend restart, with NT off:
# GET /api/market-bars?instrument=MNQ%2009-26&timeframe=5m → live:false, status:offline
```

## Remaining blockers

1. Owner visual Scenario A after backend restart + hard refresh.
2. Databento live key for moving charts when NT is off.
3. CME / commercial third backup adapters.
4. Scenario D controlled switchback.
5. Strategy/execution planes must honor `strategy_blocked` / `MARKET_DATA_UNAVAILABLE` end-to-end (flags present; broader enforcement continues).
