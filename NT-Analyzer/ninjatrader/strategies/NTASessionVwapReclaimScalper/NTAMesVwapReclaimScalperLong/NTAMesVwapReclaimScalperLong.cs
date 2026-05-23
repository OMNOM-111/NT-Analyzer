using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMesVwapReclaimScalperLong : NTASessionVwapReclaimScalper
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();
            if (State == State.SetDefaults)
            {
                Name = "Scalping MES VWAP Reclaim Long branch";
                Description = "MES reusable long-only Session VWAP Reclaim branch; research only until gates pass.";
                InstrumentName = "MES";
                ContractName = "MES 06-26";
                SessionTemplateName = "CME US Index Futures RTH";
                BaseTimeframeSeconds = 60;
                ActiveMarginPerContract = 50.0;
                EnableLong = true;
                EnableShort = false;
                LockIndexDefaults();
                VwapDistanceThresholdTicks = 10;
                MinImpulseMoveTicks = 10;
                StopMinTicks = 6;
                StopMaxTicks = 14;
                RewardRiskRatio = 1.70;
            }
        }
    }
}
