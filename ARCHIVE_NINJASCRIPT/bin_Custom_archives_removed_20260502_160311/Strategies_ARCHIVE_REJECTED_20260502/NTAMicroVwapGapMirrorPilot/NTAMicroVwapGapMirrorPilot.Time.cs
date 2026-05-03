// NTAMicroVwapGapMirrorPilot.Time.cs
// Trading window helpers and news blackout filtering.
// Part of partial class NTAMicroVwapGapMirrorPilot.
//
// TIMEZONE NOTE (v0.5):
//   This PC runs Pacific Time (PST=UTC-8, PDT=UTC-7).
//   NT8 Time[0] = PC local time = Pacific Time.
//   All window parameters (TradeStartTime, TradeEndTime, etc.) are in HHMM Pacific Time.
//   ET is always PT + 3h (both zones observe DST on the same date, so offset is constant).
//   Mapping:
//     09:35 ET = 06:35 PT -> TradeStartTime = 635
//     11:30 ET = 08:30 PT -> TradeEndTime   = 830
//     13:30 ET = 10:30 PT -> SecondTradeStartTime = 1030
//     15:00 ET = 12:00 PT -> SecondTradeEndTime   = 1200
//     15:45 ET = 12:45 PT -> ForceFlatTime = 1245
//   Verification: [TZ-DIAG] prints on bars 1-3 to confirm actual HHMM vs window.

using System;
using System.Collections.Generic;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroVwapGapMirrorPilot
    {
        #region Time helpers
        // ToTime returns HHMMSS as int. We compare in HHMM precision.
        private int ToTimeHHMM(DateTime t)
        {
            return ToTime(t) / 100;
        }

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
            // Simple HHMM-based window. Convert to minutes from midnight for arithmetic.
            int todMin = (todHHMM / 100) * 60 + (todHHMM % 100);
            for (int i = 0; i < _newsBlackoutHHMM.Count; i++)
            {
                int n = _newsBlackoutHHMM[i];
                int nMin = (n / 100) * 60 + (n % 100);
                if (Math.Abs(todMin - nMin) <= _newsBlackoutWindowMinutes) return true;
            }
            return false;
        }
        #endregion
    }
}
