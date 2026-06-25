# Exit Patterns — Curated Reference

## Verified NT8 Exit Pattern Code Snippets

### Pattern 1: ATR-Based Stop Loss
```csharp
// Recommended: set stop in Configure() using SetStopLoss
// This is called once per trade entry, NT8 tracks it automatically
protected override void OnBarUpdate()
{
    if (Position.MarketPosition == MarketPosition.Flat && entryCondition)
    {
        int stopTicks = (int)Math.Max(MinStopTicks, Math.Min(MaxStopTicks,
            ATR(14)[0] / TickSize * AtrStopMult));
        EnterLong(qty, "Long");
        SetStopLoss("Long", CalculationMode.Ticks, stopTicks, false);
        SetProfitTarget("Long", CalculationMode.Ticks, stopTicks * RiskRewardRatio);
    }
}
```

### Pattern 2: Dynamic Trailing Stop (ATR)
```csharp
// Trail stop by ATR once in profit
private double trailPrice = 0;

if (Position.MarketPosition == MarketPosition.Long)
{
    double newTrail = High[0] - ATR(14)[0] * TrailAtrMult;
    if (newTrail > trailPrice)
    {
        trailPrice = newTrail;
        SetStopLoss("Long", CalculationMode.Price, trailPrice, false);
    }
}
```

### Pattern 3: VWAP Target Exit
```csharp
// Exit long when price reaches VWAP (mean reversion target)
if (Position.MarketPosition == MarketPosition.Long)
{
    if (Close[0] >= VWAP()[0]) // reached VWAP target
    {
        ExitLong("VWAP_Target", "Long");
    }
}
```

### Pattern 4: EMA Cross Exit (trend end)
```csharp
// Exit long when EMA fast crosses below EMA slow (trend reversal)
bool emaBearishCross = EMA(FastPeriod)[0] < EMA(SlowPeriod)[0]
                     && EMA(FastPeriod)[1] >= EMA(SlowPeriod)[1];

if (Position.MarketPosition == MarketPosition.Long && emaBearishCross)
{
    ExitLong("EMA_Exit", "Long");
}
```

### Pattern 5: Time Stop (session end)
```csharp
// Exit before session close
TimeSpan exitDeadline = new TimeSpan(14, 30, 0); // 2:30 PM ET
TimeSpan barTime = Times[0][0].TimeOfDay;

if (Position.MarketPosition != MarketPosition.Flat && barTime >= exitDeadline)
{
    ExitLong("Time_Exit", "Long");
    ExitShort("Time_Exit", "Short");
}

// Better: use IsExitOnSessionCloseStrategy = true in SetDefaults
// This is more reliable than manual time check
```

### Pattern 6: RSI Exit (momentum reversal)
```csharp
// Exit long when RSI reaches overbought (momentum exhaustion)
double rsiExitLevel = 65.0;

if (Position.MarketPosition == MarketPosition.Long
    && RSI(14, RSIType.Wilder)[0] >= rsiExitLevel)
{
    ExitLong("RSI_Exit", "Long");
}
```

### Pattern 7: Max Daily Loss Stop
```csharp
// Declare
private double realizedPnlToday = 0;
private DateTime lastResetDate = DateTime.MinValue;

// In OnPositionUpdate or track manually
void TrackPnl()
{
    if (Times[0][0].Date != lastResetDate.Date)
    {
        realizedPnlToday = 0;
        lastResetDate = Times[0][0];
    }
}

// In OnBarUpdate, before any entry:
if (realizedPnlToday <= -MaxDailyLossUsd) return; // stop trading for the day
```

### Pattern 8: IsExitOnSessionCloseStrategy (recommended)
```csharp
// In SetDefaults — NT8 handles session end exit automatically
protected override void SetDefaults()
{
    IsExitOnSessionCloseStrategy = true; // recommended for all intraday
    // Exits all positions at session close bar
}
```

---

## Exit Rules Priority Order

For any NT8 strategy, apply exits in this priority order:
1. Hard stop loss (SetStopLoss) — always set, prevents catastrophic loss
2. Profit target (SetProfitTarget) — set fixed R:R target
3. Indicator-based exit (EMA cross, RSI extreme, VWAP target)
4. Max daily loss stop — stop trading if too much lost today
5. Time stop (IsExitOnSessionCloseStrategy = true) — last resort

---

## Exit Sizing Guide (MNQ $2k Account)

| Stop | Target (R:R 2:1) | Target (R:R 2.5:1) | Gross per trade |
|------|---------|---------|---------|
| 8 ticks ($4) | 16 ticks ($8) | 20 ticks ($10) | $8-10 ✓ |
| 12 ticks ($6) | 24 ticks ($12) | 30 ticks ($15) | $12-15 ✓ |
| 16 ticks ($8) | 32 ticks ($16) | 40 ticks ($20) | $16-20 ✓ |
| 20 ticks ($10) | 40 ticks ($20) | 50 ticks ($25) | $20-25 ✓ |

All above are viable after $1.90 commission.
Below 8 ticks stop = target < $8 = marginal at commission.

---

## Anti-Patterns for Exits

### Anti-Pattern 1: No stop loss
```csharp
// WRONG: no SetStopLoss called
EnterLong(qty, "Long");
// No stop → unlimited loss if trade goes wrong
```

### Anti-Pattern 2: Stop too tight for timeframe ATR
```csharp
// WRONG on 15m bar (ATR ≈ 20 ticks): 4-tick stop = instant same-bar stop-out
SetStopLoss("Long", CalculationMode.Ticks, 4, false);
// Fix: use ATR * 1.0 minimum
```

### Anti-Pattern 3: Martingale exit (DO NOT USE)
```csharp
// ABSOLUTELY WRONG: adding to losing position
// If in loss, double the position size
// This is disqualified - flag: martingale
if (Position.MarketPosition == MarketPosition.Long && Close[0] < entryPrice - ATR(14)[0])
    EnterLong(qty * 2, "Martingale_Add"); // FORBIDDEN
```

---

*Last updated: 2026-06-06*
