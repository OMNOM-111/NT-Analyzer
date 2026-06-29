using System;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTASessionVwapReclaimScalper
    {
        private void LogSkip(string reason)
        {
            if (CurrentBar == _lastSkipBar && reason == _lastSkipReason) return;
            _lastSkipBar = CurrentBar;
            _lastSkipReason = reason;
            Print(string.Format("[SKIP:{0}] bar={1} time={2:HH:mm} px={3:F2} vwap={4:F2}",
                reason, CurrentBar, Time[0], Close[0], _vwapSeries == null ? 0.0 : _vwapSeries[0]));
        }

        private void PrintSetupState(string stage)
        {
            Print(string.Format(
                "[SETUP:{0}] time={1:yyyy-MM-dd HH:mm} bias={2} vwapDist={3:F1} pullDepth={4:F1} or={5}",
                stage,
                Time[0],
                _activeBias,
                _impulseVwapDistanceTicks,
                _pullbackDepthTicks,
                OrbStateText()));
        }

        private void LogEntryPlan(string tag, string direction, double trigger, double stop, double target, int stopTicks, int qty)
        {
            double vwapDistance = Math.Abs((trigger - _vwapSeries[0]) / TickSize);
            double emaSpread = Math.Abs((_emaFast[0] - _emaSlow[0]) / TickSize);
            double volFactor = VolumeFactor(0);

            _lastEntryVwapDistanceTicks = vwapDistance;
            _lastEntryEmaSpreadTicks = emaSpread;
            _lastEntryVolumeFactor = volFactor;
            _lastEntryOrbState = OrbStateText();

            Print(string.Format(
                "[ENTRY_PLAN] time={0:yyyy-MM-dd HH:mm} dir={1} setup={2} qty={3} trigger={4:F2} stop={5:F2} target={6:F2} stopTicks={7} vwapDist={8:F1} orState={9} emaSpread={10:F1} volFactor={11:F2} delta={12}",
                Time[0],
                direction,
                tag,
                qty,
                trigger,
                stop,
                target,
                stopTicks,
                vwapDistance,
                _lastEntryOrbState,
                emaSpread,
                volFactor,
                _lastDeltaState));
        }

        private void LogClosedTrade(NinjaTrader.Cbi.Trade trade, double adjustedPnl)
        {
            int holdBars = _lastEntryBar > 0 ? CurrentBar - _lastEntryBar : 0;
            TimeSpan holdTime = _lastEntryTime == DateTime.MinValue
                ? TimeSpan.Zero
                : Time[0] - _lastEntryTime;

            Print(string.Format(
                "[TRADE_DIAG] entryTime={0:yyyy-MM-dd HH:mm} exitTime={1:yyyy-MM-dd HH:mm} dir={2} setup={3} vwapDist={4:F1} orState={5} emaSpread={6:F1} volFactor={7:F2} delta={8} stopTicks={9} mfeTicks={10:F1} maeTicks={11:F1} holdBars={12} holdSeconds={13:F0} adjPnl={14:F2}",
                _lastEntryTime,
                Time[0],
                _lastDirection,
                _lastSetupTag,
                _lastEntryVwapDistanceTicks,
                _lastEntryOrbState,
                _lastEntryEmaSpreadTicks,
                _lastEntryVolumeFactor,
                _lastDeltaState,
                _lastStopTicks,
                _tradeMfeTicks,
                _tradeMaeTicks,
                holdBars,
                holdTime.TotalSeconds,
                adjustedPnl));
        }

        private string OrbStateText()
        {
            if (!_orbBuilt) return "building";
            return string.Format("built:{0:F2}-{1:F2}", _orbLow, _orbHigh);
        }
    }
}
