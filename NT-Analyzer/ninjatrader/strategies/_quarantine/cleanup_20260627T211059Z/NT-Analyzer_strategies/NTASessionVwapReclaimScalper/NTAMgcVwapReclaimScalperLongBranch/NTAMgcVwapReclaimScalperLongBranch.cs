using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMgcVwapReclaimScalperLongBranch : NTASessionVwapReclaimScalper
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();
            if (State == State.SetDefaults)
            {
                Name = "Scalping MGC VWAP Reclaim Long branch";
                Description = "MGC branch design only. Prior MGC CELL-003 VWAP Reclaim was rejected; do not promote without new evidence.";
                InstrumentName = "MGC";
                ContractName = "MGC 06-26";
                SessionTemplateName = "Nymex Metals RTH1";
                BaseTimeframeSeconds = 60;
                ActiveMarginPerContract = 200.0;
                EnableLong = true;
                EnableShort = false;
                LockGoldDefaults();
            }
        }
    }
}
