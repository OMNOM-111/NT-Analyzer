// NTAMicroSessionEdgeExplorer.Time.cs
using System;
using System.Collections.Generic;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroSessionEdgeExplorer
    {
        private int ToTimeHHMM(DateTime t) { return ToTime(t) / 100; }

        private bool IsInTradeWindow(int todHHMM)
        {
            bool inMain = (TradeStartTime <= 0 || TradeEndTime <= 0)
                          ? false
                          : (todHHMM >= TradeStartTime && todHHMM <= TradeEndTime);
            bool inSecond = UseSecondTradeWindow
                            && SecondTradeStartTime > 0 && SecondTradeEndTime > 0
                            && todHHMM >= SecondTradeStartTime && todHHMM <= SecondTradeEndTime;
            return inMain || inSecond;
        }

        private bool IsInNewsBlackout(int todHHMM)
        {
            if (_newsBlackoutHHMM.Count == 0) return false;
            int todMin = (todHHMM / 100) * 60 + (todHHMM % 100);
            for (int i = 0; i < _newsBlackoutHHMM.Count; i++)
            {
                int n = _newsBlackoutHHMM[i];
                int nMin = (n / 100) * 60 + (n % 100);
                if (Math.Abs(todMin - nMin) <= _newsBlackoutWindowMinutes) return true;
            }
            return false;
        }
    }
}
