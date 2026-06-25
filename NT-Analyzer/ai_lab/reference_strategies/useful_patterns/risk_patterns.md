# Risk Management Patterns — Curated Reference

## $2k MNQ Account Risk Framework

This is the specific risk framework for our NT-Analyzer $2k MNQ account.
All new strategies MUST comply with these parameters.

---

## Hard Rules (Non-Negotiable)

```
OrderFillResolution = High
slippage_ticks >= 1  (minimum 1 tick slippage in backtest)
RoundTurnCommission >= 1.90  (minimum $1.90/RT in backtest)
MaxDailyLossUsd <= 120  (recommended: $80-100)
UserMaxContracts = 1  (only 1 contract at a time)
IsExitOnSessionCloseStrategy = true  (mandatory for intraday)
```

---

## Position Sizing Template (NT8 C#)

```csharp
private int ComputeQuantity(double stopTicks)
{
    double tickValue = Instrument.MasterInstrument.PointValue * TickSize;
    double contractRisk = stopTicks * tickValue
                        + RoundTurnCommission
                        + SlippageTicks * tickValue;

    // Risk budget approach
    double riskBudget = StartingCapital * RiskPerTradePct / 100.0;
    int byRisk = (int)Math.Floor(riskBudget / contractRisk);

    // Margin approach (simplified)
    double marginPerContract = InitialMargin; // from instrument
    int byMargin = (int)Math.Floor(Account.Get(AccountItem.CashValue, Currency.UsDollar)
                   / marginPerContract);

    // User cap
    int byUser = UserMaxContracts;

    // CRITICAL FIX: floor to 1 when risk budget rounds to 0
    // Without this, wide ATR stops silently produce 0 contracts
    int qty = Math.Min(byUser, Math.Min(byRisk, byMargin));

    // Floor fix: use 1 if all capacity checks pass but risk rounds down
    if (qty == 0 && byMargin >= 1 && byUser >= 1
        && contractRisk <= MaxDailyLossUsd)
    {
        qty = 1; // minimum 1 contract with MaxDailyLossUsd as hard cap
    }

    return qty;
}
```

---

## Daily P&L Tracking Template

```csharp
private double realizedPnlToday = 0;
private DateTime lastPnlResetDate = DateTime.MinValue;
private bool pauseTrading = false;
private int consecutiveLosses = 0;

private void ResetDailyRisk()
{
    if (Times[0][0].Date != lastPnlResetDate.Date)
    {
        realizedPnlToday = 0;
        pauseTrading = false;
        consecutiveLosses = 0;
        lastPnlResetDate = Times[0][0];
    }
}

protected override void OnPositionUpdate(Position position,
    double averagePrice, int quantity, MarketPosition marketPosition)
{
    // Track closed trade P&L
    // Note: OnPositionUpdate fires when position changes
    // For realized P&L use SystemPerformance.AllTrades
}

// Simple approach: check MaxDailyLossUsd before any entry
private bool CanEnterTrade()
{
    if (pauseTrading) return false;
    if (realizedPnlToday <= -MaxDailyLossUsd)
    {
        pauseTrading = true;
        return false;
    }
    if (consecutiveLosses >= MaxConsecutiveLosses) // [Range(0, 20)]
    {
        pauseTrading = true;
        return false;
    }
    return true;
}
```

---

## Risk Parameters Standard Set

```csharp
[NinjaScriptProperty]
[Display(GroupName = "Risk", Order = 1, Name = "Max Daily Loss USD")]
[Range(10.0, 500.0)]
public double MaxDailyLossUsd { get; set; } = 100.0;

[NinjaScriptProperty]
[Display(GroupName = "Risk", Order = 2, Name = "Max Consecutive Losses")]
[Range(0, 20)] // CRITICAL: never use Range > 20 for this parameter
public int MaxConsecutiveLosses { get; set; } = 3;

[NinjaScriptProperty]
[Display(GroupName = "Risk", Order = 3, Name = "Pause After Consecutive Losses (min)")]
[Range(0, 480)] // CRITICAL: never exceed 480 (NinjaTrader Range limit)
public int PauseMinutesAfterLosses { get; set; } = 60;

[NinjaScriptProperty]
[Display(GroupName = "Risk", Order = 4, Name = "User Max Contracts")]
[Range(1, 10)]
public int UserMaxContracts { get; set; } = 1;

[NinjaScriptProperty]
[Display(GroupName = "Risk", Order = 5, Name = "Risk Per Trade Pct")]
[Range(0.1, 5.0)]
public double RiskPerTradePct { get; set; } = 0.6;

[NinjaScriptProperty]
[Display(GroupName = "Risk", Order = 6, Name = "Min Stop Ticks")]
[Range(2, 50)]
public int MinStopTicks { get; set; } = 8;

[NinjaScriptProperty]
[Display(GroupName = "Risk", Order = 7, Name = "Max Stop Ticks")]
[Range(5, 100)]
public int MaxStopTicks { get; set; } = 25;
```

---

## Backtest Configuration Requirements

When submitting a job through NT-Analyzer, ALWAYS include:
```json
{
  "order_fill_resolution": "High",
  "slippage_ticks": 1,
  "round_turn_commission": 1.90,
  "starting_capital": 2000
}
```

These are hard requirements. Do not submit backtest with:
- `slippage_ticks = 0` (unrealistic fills)
- `round_turn_commission = 0` (ignores real cost)
- `order_fill_resolution != "High"` (inaccurate bar-level fills)

---

## Common [Range] Violations (Bug Reference)

From CELL-019/020 experience, these parameters have MANDATORY range limits:

| Parameter | Safe Range | Danger |
|-----------|-----------|--------|
| MaxConsecutiveLosses | [0, 20] | >20 kills ALL backtests silently |
| PauseAfterConsecutiveLosses | [0, 480] | >480 kills ALL trades silently |
| AnyIntegerParam | [1, N] | Must NOT send value outside declared Range |
| AtrPeriod | [1, 100] | typically [10, 30] declared |
| EmaFastPeriod | [1, 100] | typically [5, 30] declared |

**Rule:** When job submits a parameter value, verify it's within the declared [Range].
If value is outside Range, NT8 silently aborts the backtest (trade_count=0, fast completion).

---

*Last updated: 2026-06-06*
