using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAM2kVwapReclaimScalperLong : NTASessionVwapReclaimScalper
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();
            if (State == State.SetDefaults)
            {
                Name = "Scalping M2K VWAP Reclaim Long branch";
                Description = "M2K reusable long-only Session VWAP Reclaim branch; research only until gates pass.";
                InstrumentName = "M2K";
                ContractName = "M2K 06-26";
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 60;
                ActiveMarginPerContract = 50.0;
                EnableLong = true;
                EnableShort = false;
                LockIndexDefaults();
                VwapDistanceThresholdTicks = 8;
                MinImpulseMoveTicks = 8;
                MinOpeningRangeTicks = 6;
                StopMinTicks = 6;
                StopMaxTicks = 16;
                RewardRiskRatio = 1.70;
            }
        }
    }
}
