# Entry Patterns — Curated Reference

## Verified NT8 Entry Pattern Code Snippets

### Pattern 1: EMA Crossover Entry (next bar open)
```csharp
// Declare in SetDefaults
private int fastPeriod = 9;
private int slowPeriod = 21;
private bool wasBullish = false;

// In OnBarUpdate (only at bar close: if (IsFirstTickOfBar && !IsFirstBar) return;)
bool isBullishCross = EMA(fastPeriod)[0] > EMA(slowPeriod)[0]
                    && EMA(fastPeriod)[1] <= EMA(slowPeriod)[1];
bool isBearishCross = EMA(fastPeriod)[0] < EMA(slowPeriod)[0]
                    && EMA(fastPeriod)[1] >= EMA(slowPeriod)[1];

if (isBullishCross && Position.MarketPosition == MarketPosition.Flat)
    EnterLong(qty, "EMA_Long");
if (isBearishCross && Position.MarketPosition == MarketPosition.Flat)
    EnterShort(qty, "EMA_Short");
```

### Pattern 2: ORB Formation and Breakout
```csharp
// Declare
private double orbHigh = double.MinValue;
private double orbLow = double.MaxValue;
private bool orbFormed = false;
private TimeSpan orbEndTime = new TimeSpan(10, 0, 0); // 10:00 AM ET

// In OnBarUpdate
if (Bars.IsFirstBarOfSession)
{
    orbHigh = double.MinValue;
    orbLow = double.MaxValue;
    orbFormed = false;
}

TimeSpan barTime = Times[0][0].TimeOfDay;
if (!orbFormed && barTime < orbEndTime)
{
    orbHigh = Math.Max(orbHigh, High[0]);
    orbLow = Math.Min(orbLow, Low[0]);
}
else if (!orbFormed && barTime >= orbEndTime)
{
    orbFormed = true;
}

// Breakout entry after ORB formed
if (orbFormed && Position.MarketPosition == MarketPosition.Flat)
{
    if (Close[0] > orbHigh && Close[0] > VWAP()[0]) // VWAP filter
        EnterLong(qty, "ORB_Long");
    if (Close[0] < orbLow && Close[0] < VWAP()[0])
        EnterShort(qty, "ORB_Short");
}
```

### Pattern 3: VWAP Pullback Entry
```csharp
// Declare
private int sessionBufferMinutes = 30; // wait 30 min after open

// In OnBarUpdate
TimeSpan barTime = Times[0][0].TimeOfDay;
TimeSpan sessionStart = new TimeSpan(9, 30, 0);
bool pastBuffer = barTime >= sessionStart.Add(TimeSpan.FromMinutes(sessionBufferMinutes));

bool priceAboveVwap = Close[1] > VWAP()[1]; // was above VWAP
bool pullbackToVwap = Math.Abs(Low[0] - VWAP()[0]) <= ATR(14)[0] * 0.5;
bool recoveringFromVwap = Close[0] > VWAP()[0]; // bouncing

if (pastBuffer && priceAboveVwap && pullbackToVwap && recoveringFromVwap
    && Position.MarketPosition == MarketPosition.Flat && EMA(20)[0] > EMA(50)[0])
{
    EnterLong(qty, "VWAP_Pullback_Long");
}
```

### Pattern 4: RSI Extreme + Confirmation
```csharp
// Declare
private double rsiOversold = 35.0;
private double rsiOverbought = 65.0;

// In OnBarUpdate
bool rsiOversoldSignal = RSI(14, RSIType.Wilder)[0] < rsiOversold
                       && RSI(14, RSIType.Wilder)[1] < rsiOversold; // confirmed 2 bars
bool bullishBar = Close[0] > Open[0]; // bullish recovery bar

if (rsiOversoldSignal && bullishBar && Close[0] < VWAP()[0] + ATR(14)[0]
    && Position.MarketPosition == MarketPosition.Flat)
{
    EnterLong(qty, "RSI_Long");
}
```

### Pattern 5: Previous Day High/Low Detection
```csharp
// Declare
private double prevDayHigh = 0;
private double prevDayLow = 0;
private DateTime lastSessionDate = DateTime.MinValue;

// In OnBarUpdate
if (Bars.IsFirstBarOfSession)
{
    // Save prior day's levels from yesterday's session
    // Note: requires careful implementation to track across sessions
    // Best approach: use built-in PriorDayOHLC indicator
    prevDayHigh = PriorDayOHLC().PriorHigh[0];
    prevDayLow = PriorDayOHLC().PriorLow[0];
}

// Breakout
if (Close[0] > prevDayHigh && Close[1] <= prevDayHigh
    && Position.MarketPosition == MarketPosition.Flat)
{
    EnterLong(qty, "PDH_Break_Long");
}
```

### Pattern 6: ATR-Based Daily Trade Counter
```csharp
// Declare
private int dailyTradeCount = 0;
private DateTime lastResetDate = DateTime.MinValue;
private int maxTradesPerDay = 2;

// In OnBarUpdate
if (Times[0][0].Date != lastResetDate.Date)
{
    dailyTradeCount = 0;
    lastResetDate = Times[0][0];
}

// Check before entry
if (dailyTradeCount >= maxTradesPerDay) return;

// After entry confirmed (in OnExecutionUpdate or after EnterLong)
// dailyTradeCount++;
```

### Pattern 7: Compression Detection (NR7)
```csharp
// Detect NR7: current bar range is smallest of last 7 bars
private bool IsNarrowRange(int nBars = 7)
{
    double currentRange = High[0] - Low[0];
    for (int i = 1; i < nBars; i++)
    {
        if (High[i] - Low[i] <= currentRange) return false; // prior bar is tighter
    }
    return true; // current is the narrowest
}
```

### Pattern 8: ADX Trend Filter
```csharp
// ADX filter: only enter if trend is present
bool trendPresent = ADX(14)[0] > 25.0;
bool bullishEmaStack = EMA(8)[0] > EMA(21)[0] && EMA(21)[0] > EMA(50)[0];

if (trendPresent && bullishEmaStack)
{
    // Enter long
}
```

### Pattern 9: Inside Bar Breakout (from REPO-016 ayb/ninjatrader-automated-trading-strategy MIT)
```csharp
// Inside Bar: current bar's high/low contained within prior bar's range
// Signal bar is 1 bar back (High[1] < High[2] means bar1 inside bar2)
bool insideBar = (High[1] < High[2]) && (Low[1] > Low[2]);

// Entry: price breaks out of inside bar
if (insideBar && CrossAbove(Close, High[2], 1)) // Break above inside bar high
    EnterLong(qty, "IB_Long");
if (insideBar && CrossBelow(Close, Low[2], 1)) // Break below inside bar low
    EnterShort(qty, "IB_Short");

// ATR Trailing Stop (for longs):
// ATRStop initialized at entry: entryPrice - ATR * mult
// Each bar: if new trailing level > current stop, move stop up
private double atrStop = 0;
// In OnPositionUpdate when going long: atrStop = High[1] - ATRMult * ATR(ATRLen)[1];
// In OnBarUpdate when long:
double newTrail = High[1] - (ATRMultiplier * ATR(ATRLen)[1]);
if (newTrail > atrStop)
{
    atrStop = newTrail;
    ExitLongStopMarket(0, true, qty, atrStop, "Trail_Stop", "IB_Long");
}
```

**Reference:** REPO-016, MIT license. Pattern explicit for MES/MNQ/MYM/M2K.
**Timeframe:** 5m or 15m. **Pattern characteristic:** Low-frequency, high-quality setup.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Same-bar entry AND stop
```csharp
// WRONG: sets stop immediately in same OnBarUpdate as entry
// Can cause same-bar stop-out when ATR bar range > stop
EnterLong(qty, "Long");
SetStopLoss("Long", CalculationMode.Ticks, 4, false); // 4 ticks too tight for ATR bar
```

### Anti-Pattern 2: No session filter
```csharp
// WRONG: no time filter, trades during thin overnight sessions
if (EMA(9)[0] > EMA(21)[0]) EnterLong(qty, "Long"); // trades at 2:00 AM
```

### Anti-Pattern 3: Unlimited daily trades
```csharp
// WRONG: every crossover triggers, no daily limit
if (IsBullishCross()) EnterLong(qty, "Long"); // 10-20 trades/day possible
```

---

*Last updated: 2026-06-06*
