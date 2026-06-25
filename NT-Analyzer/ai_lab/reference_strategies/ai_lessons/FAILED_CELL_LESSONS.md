# Failed AI-CELL Lessons Archive

## Purpose
Detailed lessons from each failed AI-CELL for future reference.
AI must read relevant sections before generating similar strategies.

---

## AI-CELL-004 Lessons

### What Was Attempted
AI-generated strategy, early generation. Specific details in AI-CELL-004 folder.

### Key Failures Documented
- AI generated strategy from scratch without reference patterns
- Missing proper NT8 API usage
- Strategy concept not grounded in real market structure

### Lessons for Future AI
1. Don't invent strategies from empty context
2. Start from a known reference pattern (now available in REF-001 to REF-025)
3. Verify NT8 API existence before using it (no ExecutionEventArgs, no BarsSinceEntry)

---

## AI-CELL-005 Lessons

### What Was Attempted
AI-generated strategy, second generation attempt.

### Key Failures Documented
- Overtrading: unlimited entries per day
- Mean reversion during trending market conditions
- High same-bar% indicating stops too tight

### Specific Lessons
1. **Max trades/day = 2–3 MAXIMUM** (never unlimited)
2. **Session filter required** — don't trade during extreme trending hours without filter
3. **ADX filter** — if ADX > 25, avoid mean-reversion signals
4. **Commission arithmetic**: check gross_per_trade > $5 before building

---

## AI-CELL-006 Lessons

### What Was Attempted
AI-generated strategy with GPT-OSS model.

### Key Failures Documented
From docs/ai/CLAUDE_FINAL_AI_LAB_COMPLETION_TASK.md:
- Invalid NT8 APIs used: `ExecutionEventArgs`, `readonly DisplayName`,
  `SystemPerformance.GetCurrentValue`, `BarsSinceEntry`
- Compile errors despite AI claiming code was correct
- Model generated plausible-looking but non-functional code

### Specific Lessons
1. **NT8 API verification required** — AI must use ONLY verified NT8 APIs:
   - Use `Close[0]`, `High[0]`, `Low[0]` (not BarsSinceEntry)
   - `EnterLong()`, `ExitLong()` (not position-direct methods)
   - `ATR(period)[0]` for ATR value
   - No `ExecutionEventArgs` — use `OnExecutionUpdate`
   - `DisplayName` is read-only — don't assign it
   - No `SystemPerformance.GetCurrentValue` — use `SystemPerformance.AllTrades.TradesPerformance`
2. **Compile test is mandatory** before backtest
3. **AI autofix**: limited to 1-2 simple fixes; if more errors, reject and restart

### NT8 APIs That AI Must Not Use (Known Bad List)
```
ExecutionEventArgs         → use OnExecutionUpdate(Execution exec, ...)
DisplayName = "..."        → read-only in SetDefaults, cannot assign
SystemPerformance.GetCurrentValue() → does not exist in NT8
BarsSinceEntry(...)        → replaced by BarsSinceEntry() no args or track manually
IsExitOnSessionEnd = ...   → use IsExitOnSessionCloseStrategy instead
Enabled = ...              → not assignable in OnBarUpdate
```

### NT8 APIs AI Should Use (Known Good List)
```csharp
// Market data
Close[0], High[0], Low[0], Open[0], Volume[0]
High[1], Low[1]  // prior bar

// Position
Position.MarketPosition == MarketPosition.Long
Position.Quantity

// Indicators
EMA(period)[0]
SMA(period)[0]
ATR(period)[0]
RSI(period, RSIType.Wilder)[0]
MACD(fast, slow, signal)
VWAP()[0]  // requires correct session setup
Bollinger(period, numStdDevs)
ADX(period)[0]

// Orders
EnterLong(quantity, "entry_name")
EnterShort(quantity, "entry_name")
ExitLong(quantity, "exit_name", "entry_name")
ExitShort(quantity, "exit_name", "entry_name")
SetStopLoss("entry_name", CalculationMode.Ticks, stopTicks, false)
SetProfitTarget("entry_name", CalculationMode.Ticks, targetTicks)
SetTrailStop("entry_name", CalculationMode.Ticks, trailTicks, false)

// Session
Times[0][0]  // current time
Bars.IsFirstBarOfSession

// Strategy state
State == State.Historical
State == State.Realtime
IsFirstTickOfBar
```

---

## AI-CELL-019 FULL LESSONS (Manual Pipeline)

CELL-019 was a comprehensive manual testing cycle that exhausted 9+ engine families.
This is the most complete set of lessons available.

### Engine #1: Post-Cluster Squeeze Breakout
- Window: 13:00–15:30 PT, BB+Keltner squeeze, ADX+RSI
- Smoke: 24 variants → 3 positive, best +$19.50 PF 1.20 (5 trades)
- Failure: too sparse (5-13 trades/year), same-bar 50-77%
- **Lesson:** Breakout direction wrong = regime is mean-reverting at this window

### Engine #2: Post-Cluster VWAP Fade
- Window: 13:00–15:30 PT, 5m VWAP fade
- Smoke: 3 positive out of 24, best +$16.50 PF 1.15 (15 trades)
- Structural failure: 518 trades / gross $756 = $1.46/trade < $1.90 commission
- Same-bar 76-93% = stops too tight for 5m MNQ ATR
- **Lesson:** High-frequency mean reversion on 5m micros = structural loser at $1.90 RT

### Engine #3: Overnight Settlement Reversion
- Smoke: deeply negative
- **Lesson:** Gap fade on equity index micros is STRUCTURALLY wrong in 2024-2025

### Engine #4: Overnight Settlement Breakout
- Smoke mirage: M2K +446.7 PF 1.166 → Full -31.6 PF 0.994
- **Lesson:** Strong smoke positive = WARNING sign of overfit, not success

### Engine #5: RTH VWAP Pullback
- Near-pass on MGC: Full PF 1.171 DD -$298, IS PF 1.281, OOS PF 1.052
- OOS PF 1.052 < 1.25 gate; Full PF 1.171 < 1.35 gate
- **Lesson:** VWAP pullback has real edge but current gates are tight; MGC better than MNQ

### Engine #6: RTH Trend Day H1 (ORB after bar 1, EMA+ADX)
- 2024 PF 1.44, 2025 PF 1.07 DD -$483
- Regime experiment: 2024 clean (PF 9-17!) but 2025 always negative PF 0.12-0.71
- **Lesson:** Regime SHIFT confirmed. 2025 MNQ H1 trend setups REVERSE more than 2024.

### Engine #7: RTH ORB Retest H1
- Cross-year positives existed but OOS gates failed
- **Lesson:** ORB retest needs directional bias; pattern alone insufficient

### Engine #8: RTH ORB Retest 15m
- Same result as H1: REJECTED
- **Lesson:** Scaling down TF doesn't fix missing directional filter

### Engine #9: RTH Gap Go H1
- Fixed two real bugs: prior-day tracking, one-bar confirmation
- 2025 cross-year: negative on both H1 and 15m
- **Lesson:** Even with correct code and bugs fixed, 2025 regime is harder for trend entries

### Cross-Instrument Portfolio Scan Result
- Scanned: M2K, M6A, M6B, M6E, MCL, MES, MGC, MHG, MNG, MYM, SIL
- No paper candidate on ANY instrument for Post-Cluster Squeeze
- **Lesson:** When window/pattern fails on primary, don't try all instruments; change family

### Meta-Lesson CELL-019
- 6+ engines × smoke/refine/regime cycles = all rejected
- $2k MNQ gates (PF>=1.35 Full, OOS PF>=1.25, DD <= 15% of StartingCapital, sb<=50%) are HARD
- Possible next paths: (a) different instrument, (b) loosen gates, (c) multi-asset portfolio

---

## Recommended Reference Strategy for Each Failed Pattern

| Failed Pattern | Failed CELL | Better Reference |
|----------------|-------------|-----------------|
| Gap fade | CELL-019 E3/E4 | REF-019 (gap fade — learn what NOT to do) |
| VWAP fade 5m | CELL-019 E2 | REF-009 (commission drag lesson) |
| Compression no direction | CELL-019 E1,PreCash | REF-015 (needs directional filter) |
| VWAP pullback (near) | CELL-019 E5 | REF-008 (tweak filters) |
| Trend day H1 | CELL-019 E6 | REF-020 (regime filter critical) |
| ORB retest | CELL-019 E7/E8 | REF-012 + REF-021 (add VWAP) |
| Settlement breakout | CELL-019 E4 | Smoke mirage lesson; not in library |

---

*Last updated: 2026-06-06*
