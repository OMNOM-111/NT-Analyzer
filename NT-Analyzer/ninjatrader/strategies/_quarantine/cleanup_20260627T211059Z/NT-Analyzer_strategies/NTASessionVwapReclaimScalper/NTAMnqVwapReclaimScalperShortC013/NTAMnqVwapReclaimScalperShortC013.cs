using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqVwapReclaimScalperShortC013 : NTASessionVwapReclaimScalper
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();
            if (State == State.SetDefaults)
            {
                Name = "Scalping MNQ VWAP Reclaim Short 1m c013";
                Description = "MNQ CELL-013 branch: short-only Session VWAP Reclaim Scalper. Requires full validation before paper/live.";
                InstrumentName = "MNQ";
                ContractName = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 60;
                ActiveMarginPerContract = 100.0;
                EnableLong = false;
                EnableShort = true;
                LockIndexDefaults();
                VwapDistanceThresholdTicks = 18;
                MinImpulseMoveTicks = 16;
                MinVolumeFactor = 1.10;
                StopMinTicks = 8;
                StopMaxTicks = 18;
                RewardRiskRatio = 1.60;
            }
        }
    }
}
