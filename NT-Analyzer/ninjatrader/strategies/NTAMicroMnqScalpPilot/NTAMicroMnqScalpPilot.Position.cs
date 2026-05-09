// NTAMicroMnqScalpPilot.Position.cs
// Open-position management: breakeven, trail, time-stop with MinProgressR.
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroMnqScalpPilot
    {
        private void ManageOpenPosition()
        {
            if (_lastStopTicks <= 0 || _lastEntryPrice <= 0) return;

            double rDist  = _lastStopTicks * TickSize;
            double moved  = Close[0] - _lastEntryPrice;
            double rMult  = (Position.MarketPosition == MarketPosition.Long ? moved : -moved) / rDist;

            // ----- Breakeven -----
            if (rMult >= MoveToBreakevenAtR)
            {
                if (Position.MarketPosition == MarketPosition.Long)
                    SetStopLoss("Long",  CalculationMode.Price, _lastEntryPrice, false);
                else
                    SetStopLoss("Short", CalculationMode.Price, _lastEntryPrice, false);
            }

            // ----- Trail after R -----
            if (rMult >= TrailAfterR)
            {
                double trailDist = System.Math.Max(1, _lastStopTicks / 2.0) * TickSize;
                if (Position.MarketPosition == MarketPosition.Long)
                {
                    double trail = Close[0] - trailDist;
                    if (trail > _lastEntryPrice)
                        SetStopLoss("Long", CalculationMode.Price, trail, false);
                }
                else
                {
                    double trail = Close[0] + trailDist;
                    if (trail < _lastEntryPrice)
                        SetStopLoss("Short", CalculationMode.Price, trail, false);
                }
            }

            // ----- Time-stop (scalp): exit if no meaningful progress -----
            if (UseTimeStop && _lastEntryBar > 0 && (CurrentBar - _lastEntryBar) >= TimeStopBars)
            {
                if (rMult < MinProgressR)
                {
                    if (Position.MarketPosition == MarketPosition.Long)
                        ExitLong("TimeStop", "Long");
                    else
                        ExitShort("TimeStop", "Short");
                    Print(string.Format("[EXIT:time_stop] rMult={0:F2} < {1:F2} bars={2}",
                                         rMult, MinProgressR, CurrentBar - _lastEntryBar));
                }
            }
        }
    }
}
