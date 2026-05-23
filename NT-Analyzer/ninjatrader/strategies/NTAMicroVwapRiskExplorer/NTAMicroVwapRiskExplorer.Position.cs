// NTAMicroVwapRiskExplorer.Position.cs
// Open position management: breakeven move and trailing stop.
// Part of partial class NTAMicroVwapRiskExplorer.

using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTAMicroVwapRiskExplorer
    {
        #region Position management (breakeven / trail)
        private void ManageOpenPosition()
        {
            if (_lastStopTicks <= 0 || _lastEntryPrice <= 0) return;

            double rDist  = _lastStopTicks * TickSize;
            double moved  = Close[0] - _lastEntryPrice;
            double rMult  = (Position.MarketPosition == MarketPosition.Long ? moved : -moved) / rDist;

            if (rMult >= MoveToBreakevenAtR)
            {
                string signal = ActiveEntrySignalForPosition();
                if (Position.MarketPosition == MarketPosition.Long)
                    SetStopLoss(signal, CalculationMode.Price, _lastEntryPrice, false);
                else
                    SetStopLoss(signal, CalculationMode.Price, _lastEntryPrice, false);
            }

            if (rMult >= TrailAfterR)
            {
                double trailDist = System.Math.Max(1, _lastStopTicks / 2.0) * TickSize;
                if (Position.MarketPosition == MarketPosition.Long)
                {
                    double trail = Close[0] - trailDist;
                    if (trail > _lastEntryPrice)
                        SetStopLoss(ActiveEntrySignalForPosition(), CalculationMode.Price, trail, false);
                }
                else
                {
                    double trail = Close[0] + trailDist;
                    if (trail < _lastEntryPrice)
                        SetStopLoss(ActiveEntrySignalForPosition(), CalculationMode.Price, trail, false);
                }
            }
        }
        #endregion
    }
}
