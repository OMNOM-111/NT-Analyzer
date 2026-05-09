// NTAMicroSessionEdgeExplorer.Position.cs
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroSessionEdgeExplorer
    {
        private void ManageOpenPosition()
        {
            if (_lastStopTicks <= 0 || _lastEntryPrice <= 0) return;

            double rDist  = _lastStopTicks * TickSize;
            double moved  = Close[0] - _lastEntryPrice;
            double rMult  = (Position.MarketPosition == MarketPosition.Long ? moved : -moved) / rDist;

            if (rMult >= MoveToBreakevenAtR)
            {
                if (Position.MarketPosition == MarketPosition.Long)
                    SetStopLoss("Long",  CalculationMode.Price, _lastEntryPrice, false);
                else
                    SetStopLoss("Short", CalculationMode.Price, _lastEntryPrice, false);
            }

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
        }
    }
}
