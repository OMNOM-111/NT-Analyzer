# PAPER B1 ShortOnly — RUNBOOK

**Strategy class:** `NTAMicroVwapRiskPilot`
**Side label:** B1 ShortOnly
**Status:** READY FOR PAPER (live trading forbidden until paper-review pass)
**Profile:** see `PAPER_B1_SHORTONLY_PROFILE.json`
**Validation baseline:** Phase 14R / job `ui_20260501T185820607Z` — 92 trades, Adj Net +$2 738.30, Adj PF 2.49, Adj DD −$174, 8/8 positive quarters.

---

## 0. Hard rules (do not violate)

1. Do NOT change B1 trading logic.
2. Do NOT optimize parameters.
3. Live trading is FORBIDDEN until the paper-review checklist passes.
4. Acceptance backtests must use **High** fill resolution + slippage_ticks ≥ 1 + RoundTurnCommission ≥ $1.90.
5. Adjusted PnL formula: `adj = pnl_currency - 1.90 × quantity` (always quantity-aware; per-trade $1.90 is forbidden).
6. All times in this document are **PT** (America/Los_Angeles).

---

## 1. Locked parameters

| Param | Value |
| --- | --- |
| `EnableLong` | false |
| `EnableShort` | true |
| `TradeStartTime` | 635 (06:35 PT) |
| `TradeEndTime` | 700 (07:00 PT) |
| `MinStopTicks` | 12 |
| `MaxStopTicks` | 12 |
| `RewardRiskRatio` | 3.5 |
| `RiskPerTradePct` | 2.0 |
| `UserMaxContracts` | 5 |
| `RoundTurnCommission` | 1.90 |
| `SlippageTicks` | 1 |
| `IntradayOnly` | true |
| `StartingCapital` | 2000 |
| `ActiveMarginPerContract` | 50.0 |
| `MaxContractsByCapital` | 40 |
| `UseDailyBiasFilter` | false |
| `EmaFastPeriod` | 50 |
| `EmaSlowPeriod` | 200 |

---

## 2. Account assumptions

- NinjaTrader 8 Sim account (Sim101 or equivalent).
- Starting capital $2 000.
- Intraday margin $50/contract (informational; risk sizing is `RiskPerTradePct=2.0`).
- Hard cap 5 contracts per trade.
- RTH only — CME US Index Futures RTH session template.
- Auto-flatten at session close.

---

## 3. Daily start procedure (PT)

1. **05:30–06:00 PT — Pre-market check**
   - NinjaTrader running, market data flowing for the active MNQ front month.
   - Check that yesterday's session closed cleanly (no orphaned positions, no error log).
   - Verify front-month contract is still current (no roll today).
   - Verify daily/weekly/trailing limits NOT breached at session start.
2. **06:30 PT — Strategy enable**
   - Open Strategies tab → select `NTAMicroVwapRiskPilot` → load `B1_ShortOnly` template (locked params).
   - Verify all params match Section 1 above. Any drift → DO NOT START.
   - Set strategy state = Enabled.
   - Record `strategy_enabled_time_pt` in the daily journal.
3. **06:35–07:00 PT — Active trading window**
   - Strategy may open one short trade. UserMaxContracts=5 hard cap.
   - Do NOT manually intervene. If you must (broker error, platform crash), log it in `manual_intervention`.
4. **07:00 PT — Disable entry**
   - Strategy stops opening new entries (`TradeEndTime=700`).
   - Existing position is allowed to run to stop or target intraday.
5. **At intraday flatten / target / stop hit**
   - Position closes automatically.
   - Log `stop_hit_count` / `target_hit_count` in journal.
6. **End of session (RTH close, 13:00 PT / 16:00 ET)**
   - Verify position is flat (intraday-only).
   - Disable strategy.
   - Fill in the daily journal row.
   - Compute new HWM, current DD, cumulative aPF, cumulative win%.
   - Check kill switches (Section 6).

---

## 4. Trading window (canonical)

| Window | PT | ET | UTC (winter) |
| --- | --- | --- | --- |
| Entry start | 06:35 | 09:35 | 14:35 |
| Entry stop  | 07:00 | 10:00 | 15:00 |
| RTH close   | 13:00 | 16:00 | 21:00 |

---

## 5. Risk plan (paper)

| Limit | Value | Action on breach |
| --- | --- | --- |
| Max daily loss | −$200 | Disable strategy for the rest of the trading day |
| Max weekly loss | −$400 | Disable strategy until next Monday 06:35 PT |
| Max trailing DD from paper HWM | −$300 | Disable strategy + open paper review |
| Consecutive losing trading days | 4 | Pause + review |
| Hard contract cap | 5 | Strategy already enforces via `UserMaxContracts` |
| Median slippage > 1.5 ticks (5 consecutive days) | — | Flag for review |

---

## 6. Kill switches

- **Daily loss breach** → disable strategy, no override until next session.
- **Weekly loss breach** → disable until next Monday 06:35 PT.
- **Trailing DD breach (−$300 from paper HWM)** → disable + paper review.
- **Slippage median > 1.5 ticks for 5 consecutive days** → pause + investigate data feed.
- **Disconnect with open position** → manual flatten via NT, log `platform_error` and `manual_intervention`.
- **Front-month roll** → disable strategy T-2 trading days before expiry, switch to next front month at session start, re-enable next session.

---

## 7. Incident handling

### 7.1 NinjaTrader disconnect / restart
- If position open: attempt manual flatten via order book or broker GUI.
- After reconnect, do NOT re-enable strategy mid-session. Wait until next session.
- Log `platform_error=1`, `manual_intervention=1` and notes.

### 7.2 Partial fill / order error
- Strategy is single-entry per session. Partial fills should auto-complete; if rejected, manually cancel any orphaned working order.
- Log `manual_intervention=1` and notes describing the partial fill / rejection.

### 7.3 Front-month roll
- 2 trading days before contract expiry (e.g., third Friday of March/June/Sep/Dec for MNQ): disable strategy at session end.
- Update strategy instrument to next front month (e.g., MNQ 06-26 → MNQ 09-26).
- Re-verify all locked parameters.
- Re-enable next trading session.
- Log `notes`: "front-month roll executed".

### 7.4 Data issue (gap, bad tick, missing bars)
- If suspected during session: do NOT manually flatten unless position is at risk.
- After session: log `data_issue=1` and describe in notes.
- If repeated 3+ times in 10 trading days, pause and investigate feed.

---

## 8. Daily journal

Use `PAPER_B1_SHORTONLY_DAILY_JOURNAL.xlsx` (preferred — has formulas) or `.csv` (raw).
Fill in one row per trading day (including no-trade days). Columns are documented in the file header.

The XLSX auto-computes:
- cumulative adjusted PnL
- high-water mark
- current drawdown
- cumulative win %
- cumulative adjusted PF
- average trade
- pass/fail flags vs the risk plan

---

## 9. Paper duration & review rules

### 9.1 Duration

- Minimum **60 trading days** AND minimum **25 completed trades**, whichever is later.
- Expected from backtest frequency (~46 trades/year): **6–7 calendar months**.
- No live-review before BOTH are satisfied.

### 9.2 PASS to live-review (all of the following)

- paper adj PF ≥ 1.50
- paper win % ≥ 45 %
- max paper DD ≤ $300
- no daily / weekly / trailing risk breach
- no recurring platform / data / fill errors
- actual slippage acceptable (median ≤ 1.5 ticks)
- distribution not obviously worse than backtest (avg trade not below ~$10)

### 9.3 FAIL → return to research

- adj PF < 1.20
- DD > $300
- fewer than 10 trades after 90 trading days
- repeated execution / platform issues
- live behavior diverges from locked backtest

---

## 10. Source-tree state (post-Phase-15A)

- Active: `Documents\NinjaTrader 8\bin\Custom\Strategies\NTAMicroVwapRiskPilot\` (9 partial files)
- Archived: `Documents\NinjaTrader 8\bin\Custom\Strategies_ARCHIVE_REJECTED_20260501\` (NTAMicroOrbPilot, NTAMicroVwapGapMirrorPilot, NTAMicroVwapMeanRevertPilot, plus an empty stub)
- See archive manifest: `Strategies_ARCHIVE_REJECTED_20260501\ARCHIVE_MANIFEST.md`
- **F5 compile required after archive** before paper start.

---

## 11. References

- `02_РЕЗУЛЬТАТЫ_ТЕСТОВ_v0.5.md` § 14R — full validation rationale, edge tables, slip stress.
- `ПЛАН_РАЗРАБОТКИ_СТРАТЕГИЙ.md` — Phase 14R + Verdict A apex guard rails + Phase 15 entry.
- `03_РЕЕСТР_КАНДИДАТОВ.md` — candidate registry, B1 ShortOnly status PAPER ACTIVE.
- `PAPER_B1_SHORTONLY_PROFILE.json` — machine-readable profile.
- `PAPER_B1_SHORTONLY_CHECKLIST.md` — pre-launch + per-day + review checklists.


---

## Phase 16 — Strategy Control Center

Paper-операции теперь запускаются из NT-Analyzer:
<http://127.0.0.1:8765/ui/ops.html> → карточка **B1 ShortOnly**.

Workflow:
1. `Arm` → `Start Intent` → включить стратегию вручную в NinjaTrader (PAPER/SIM-аккаунт, locked params) → `Confirm Started`.
2. Конец сессии: `Stop Intent` → выключить в NT → `Confirm Stopped`.
3. Заполнить строку дня во вкладке **Daily Journal** (`Append day`).
4. Каждое действие пишется в audit-log.

Live-trading заблокирован API, требует отдельного manual unlock после paper-review (≥60 дней и ≥25 сделок). См. `OPERATIONS_CONTROL_CENTER.md`.


---

## Phase 17 update (2026-05-01) — runtime auto-detection & journal auto-fill

Steps that were manual in Phase 16 are now (partially) automated by the
NinjaTrader runtime bridge.

### Daily flow with runtime bridge

1. Start NinjaTrader. Verify in `data/runtime/heartbeat.json` that the exporter
   is publishing (or just open `http://127.0.0.1:8765/ui/ops.html` — header chip
   shows `NT runtime: live (hb Ns)`).
2. Enable **B1 ShortOnly** on **Sim101** in NinjaTrader (manual click is fine).
3. In Control Center → strategy card now shows
   `Runtime: enabled · params OK · Sim101 (paper)`.
4. Banner appears: *“Runtime enabled but not confirmed in Control Center”*. Click
   **Confirm Runtime Started** to bridge the registry to `paper_running`.
5. Trade the session. The Runtime tab shows live executions/orders/positions.
6. After session end, click **Auto-fill today's journal** in the Runtime tab.
   The `PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv` row for today is computed from
   `executions.jsonl` with quantity-aware metrics. Add freeform notes manually if
   needed; only the today row is overwritten.
7. Disable B1 ShortOnly in NinjaTrader. Banner switches to *“Runtime stopped
   outside Control Center”*; click **Confirm Runtime Stopped**.

### Hard rules unchanged

* No live trading. `account_mode=live` is read-only and all confirm/auto-fill
  endpoints refuse with `live_locked`.
* Locked B1 params must match exactly. Any mismatch ⇒ PARAM_MISMATCH and
  paper-state advancement is blocked.
* `RoundTurnCommission` stays 1.90 and is the only commission applied in
  `adjusted_pnl = gross_pnl - 1.90 * total_qty`.

### Blocker if exporter not loaded

If `data/runtime/heartbeat.json` never appears:

* Open NinjaTrader → NinjaScript Editor → press **F5** (compile).
* Restart NinjaTrader.
* Check `bridge/logs/bridge-*.log` and `data/runtime/errors.jsonl`.

Until the exporter publishes a fresh heartbeat the UI will say
`NT runtime: offline` and runtime_detected stays `false` — registry-only Phase 16
flow continues to work as a fallback.


---

## Phase 18 — запуск через Strategy Control Center

После Phase 18 вы можете запускать NTAMicroVwapRiskPilot прямо из
`/ui/ops.html` (правая панель → «▶ Запустить (paper/sim)»).

Что делает кнопка:

1. Шлёт `enable_strategy` команду в `data/runtime/commands.jsonl`.
2. C# `RuntimeCommandProcessor` в NinjaTrader читает её.
3. Bridge проверяет: paper/sim account? class не rejected? B1 locked params совпадают?
4. Если всё ОК — вызывает `Strategy.SetState(Active)` на существующем экземпляре.
5. Результат пишется в `data/runtime/command_results.jsonl`,
   панель показывает его на вкладке «Команды NT».

**Один раз** перед первым запуском — добавьте экземпляр стратегии
вручную через NinjaTrader («New → Strategy» → NTAMicroVwapRiskPilot →
account=Sim101 → MNQ 06-26 → выставить B1 ShortOnly locked params).
AddOn не создаёт новые экземпляры, только включает/выключает.

Любой mismatch B1 параметров (Long включен, RR ≠ 3.5, и т.д.) — bridge
отклонит команду с подробным сообщением в `command_results.jsonl`.
