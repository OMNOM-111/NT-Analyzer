// =============================================================================
// NTAMnqPostActiveScalpC017
// -----------------------------------------------------------------------------
// User-facing wrapper for the MNQ CELL-017 post-active all-modules scalp.
//
// This class locks the validated NTAMicroMnqScalpPilot configuration:
//   - MNQ 1 Minute
//   - both directions, all scalp modules enabled
//   - entries only 12:50-13:25 PT, force-flat 13:30 PT
//   - 4-10 tick stop box, RR=6.00, RiskPerTradePct=0.50
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqPostActiveScalpC017 : NTAMicroMnqScalpPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "Scalping Post-Active MNQ 1m v1 c017";
                Description =
                    "Scalping Post-Active MNQ 1m v1 c017 - " +
                    "post-active all-modules scalp. " +
                    "Profile mnq_postactive_allmodules_1m_c017_ready_v1.";

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

                RiskPerTradePct = 0.50;
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
                RewardRiskRatio = 6.00;
                MoveToBreakevenAtR = 0.7;
                TrailAfterR = 1.0;
                UseTimeStop = true;
                TimeStopBars = 3;
                MinProgressR = 0.30;

                EntryOffsetTicks = 0;
                EntryTimeoutBars = 2;

                TradeStartTime = 1250;
                TradeEndTime = 1325;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 0;
                SecondTradeEndTime = 0;
                ForceFlatTime = 1330;
                NewsBlackoutTimes = "";
                NewsBlackoutWindowMin = 5;

                OrbStartTime = 1245;
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
                MinVolumeFactor = 0.5;
                PullbackLookback = 3;
                RequireSlowTrend = false;
                EmaImpulseLookback = 3;
            }
        }
    }
}
