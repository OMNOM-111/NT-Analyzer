// =============================================================================
// NTAMnqDailyOpenScalpC018
// -----------------------------------------------------------------------------
// User-facing wrapper for the MNQ CELL-018 daily-open all-modules scalp.
//
// This class does not duplicate trading logic. It locks the selected
// NTAMicroMnqScalpPilot configuration from the validated CELL-018 profile:
//   - MNQ 1 Minute
//   - both directions, all scalp modules enabled
//   - entries only 06:35-08:35 PT, force-flat 13:00 PT
//   - 4-10 tick stop box, RR=4.00
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqDailyOpenScalpC018 : NTAMicroMnqScalpPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "Scalping MNQ 1m v1 c018";
                Description =
                    "Scalping MNQ 1m v1 c018 - " +
                    "daily-open all-modules scalp. " +
                    "Profile mnq_daily_open_allmodules_2h_1m_c018_ready_v1.";

                UseSetupModeFilter = false;
                EnableVwapReclaim = true;
                EnableEmaMomentum = true;
                EnableMicroOrb = true;
                EnableFailedBreakout = true;

                EnableLong = true;
                EnableShort = true;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                RiskPerTradePct = 0.35;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxTradesPerDay = 20;
                HardMaxTradesPerDay = 25;
                MaxDailyLossUsd = 60.0;
                MaxWeeklyLossUsd = 150.0;
                MaxDailyLossPct = 3.0;
                MaxDailyProfitPct = 0.0;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 15;

                RoundTurnCommission = 1.90;
                SlippageTicks = 1;

                AtrStopMult = 0.30;
                MinStopTicks = 4;
                MaxStopTicks = 10;
                RewardRiskRatio = 4.00;
                MoveToBreakevenAtR = 0.7;
                TrailAfterR = 1.0;
                UseTimeStop = true;
                TimeStopBars = 3;
                MinProgressR = 0.30;

                EntryOffsetTicks = 0;
                EntryTimeoutBars = 2;

                TradeStartTime = 635;
                TradeEndTime = 835;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 1030;
                SecondTradeEndTime = 1200;
                ForceFlatTime = 1300;
                NewsBlackoutTimes = "";
                NewsBlackoutWindowMin = 5;

                OrbStartTime = 630;
                OrbDurationMinutes = 3;
                OrbBreakoutBuffer = 1;
                OrbRetestBars = 5;
                OrbFailedLookback = 3;

                EmaFastPeriod = 9;
                EmaMidPeriod = 21;
                EmaSlowPeriod = 50;
                AtrPeriod = 14;
                AdxPeriod = 14;
                MinAdx = 0.0;
                VolumeSmaPeriod = 20;
                MinVolumeFactor = 0.7;
                PullbackLookback = 3;
                RequireSlowTrend = false;
                EmaImpulseLookback = 3;
            }
        }
    }
}
