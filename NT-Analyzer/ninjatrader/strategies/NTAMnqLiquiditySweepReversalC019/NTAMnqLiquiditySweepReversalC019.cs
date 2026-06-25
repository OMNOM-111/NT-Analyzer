// =============================================================================
// NTAMnqLiquiditySweepReversalC019
// -----------------------------------------------------------------------------
// Research-only copy of CELL-015.
//
// Purpose:
//   Preserve the corrected C015 hypothesis for controlled tick/market-replay
//   testing without promoting the failed paper-forward profile back into the
//   active portfolio.
//
// Current status:
//   RESEARCH ONLY / NOT PAPER_READY. Preliminary 2026-05-27 audit showed the
//   copy remains too dependent on optimistic same-bar 1-minute fills and fails
//   the full-history slip=3 stress gate.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqLiquiditySweepReversalC019 : NTAMnqLiquiditySweepReversalC015
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "RESEARCH ONLY Copy C015 Fixed MNQ 1m c019";
                Description =
                    "Research-only corrected copy of C015. " +
                    "Requires tick/market-replay validation before any paper-forward use.";

                OpenPressureMinScore = 2;
                SweepLookbackBars = 4;
                MomentumLookbackBars = 2;
                MinBarRangeTicks = 3;
                MinBodyRangePct = 0.05;
                MinCloseLocationPct = 0.25;
                MinVolumeFactor = 0.8;

                StopBufferTicks = 2;
                MinStopTicks = 6;
                MaxStopTicks = 14;
                RewardRiskRatio = 3.0;
                EntryOffsetTicks = 1;
                EntryTimeoutBars = 1;

                TradeStartTime = 635;
                TradeEndTime = 830;
                ForceFlatTime = 1300;

                DailyLossLimit = 25.0;
                WeeklyLossLimit = 75.0;
                MaxTradesPerDay = 6;
                HardMaxTradesPerDay = 8;
                MaxConsecutiveLosses = 2;
                PauseAfterConsecutiveLosses = 1;
                PauseMinutesAfterLosses = 30;

                SlippageTicks = 3;
            }
        }
    }
}
