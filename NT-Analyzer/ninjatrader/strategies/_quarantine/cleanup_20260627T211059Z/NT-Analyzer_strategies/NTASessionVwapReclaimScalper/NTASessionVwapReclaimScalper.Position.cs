using System;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTASessionVwapReclaimScalper
    {
        private void ManageOpenPosition()
        {
            if (_lastStopTicks <= 0 || _lastEntryPrice <= 0.0) return;

            double rDist = _lastStopTicks * TickSize;
            double favorableTicks = 0.0;
            double adverseTicks = 0.0;

            if (Position.MarketPosition == MarketPosition.Long)
            {
                favorableTicks = (High[0] - _lastEntryPrice) / TickSize;
                adverseTicks = (_lastEntryPrice - Low[0]) / TickSize;
            }
            else if (Position.MarketPosition == MarketPosition.Short)
            {
                favorableTicks = (_lastEntryPrice - Low[0]) / TickSize;
                adverseTicks = (High[0] - _lastEntryPrice) / TickSize;
            }

            if (favorableTicks > _tradeMfeTicks) _tradeMfeTicks = favorableTicks;
            if (adverseTicks > _tradeMaeTicks) _tradeMaeTicks = adverseTicks;

            double moved = Close[0] - _lastEntryPrice;
            double rMult = Position.MarketPosition == MarketPosition.Long
                ? moved / rDist
                : -moved / rDist;

            if (BreakEvenTriggerR > 0.0 && rMult >= BreakEvenTriggerR)
            {
                string signal = ActiveEntrySignalForPosition();
                if (Position.MarketPosition == MarketPosition.Long)
                    SetStopLoss(signal, CalculationMode.Price, _lastEntryPrice, false);
                else if (Position.MarketPosition == MarketPosition.Short)
                    SetStopLoss(signal, CalculationMode.Price, _lastEntryPrice, false);
            }

            if (TrailMode != ReclaimTrailMode.Off && TrailTriggerR > 0.0 && rMult >= TrailTriggerR)
            {
                if (Position.MarketPosition == MarketPosition.Long)
                {
                    double trail = TrailMode == ReclaimTrailMode.EmaFast
                        ? _emaFast[0] - TickSize
                        : Close[0] - Math.Max(1, _lastStopTicks / 2.0) * TickSize;
                    if (trail > _lastEntryPrice)
                        SetStopLoss(ActiveEntrySignalForPosition(), CalculationMode.Price, trail, false);
                }
                else if (Position.MarketPosition == MarketPosition.Short)
                {
                    double trail = TrailMode == ReclaimTrailMode.EmaFast
                        ? _emaFast[0] + TickSize
                        : Close[0] + Math.Max(1, _lastStopTicks / 2.0) * TickSize;
                    if (trail < _lastEntryPrice)
                        SetStopLoss(ActiveEntrySignalForPosition(), CalculationMode.Price, trail, false);
                }
            }

            if (TimeStopBars > 0 && _lastEntryBar > 0 && CurrentBar - _lastEntryBar >= TimeStopBars)
            {
                if (rMult < MinProgressR)
                {
                    if (Position.MarketPosition == MarketPosition.Long)
                        ExitLong("TimeStop", ActiveEntrySignalForPosition());
                    else if (Position.MarketPosition == MarketPosition.Short)
                        ExitShort("TimeStop", ActiveEntrySignalForPosition());

                    Print(string.Format("[EXIT:time_stop] rMult={0:F2} < {1:F2} bars={2}",
                        rMult, MinProgressR, CurrentBar - _lastEntryBar));
                }
            }
        }
    }
}
