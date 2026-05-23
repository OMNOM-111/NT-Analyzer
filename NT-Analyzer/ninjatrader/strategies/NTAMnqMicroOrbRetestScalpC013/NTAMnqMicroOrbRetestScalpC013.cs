// =============================================================================
// NTAMnqMicroOrbRetestScalpC013
// -----------------------------------------------------------------------------
// User-facing wrapper for the MNQ Micro ORB retest scalping profile.
//
// This class does not duplicate trading logic. It locks the approved CELL-013
// short-only OrbRetestScalp configuration from the portfolio profile.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqMicroOrbRetestScalpC013 : NTAMicroMnqScalpPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "Scalping Orb Retest MNQ 1m v1 c013";
                Description =
                    "Scalping Orb Retest MNQ 1m v1 c013 - approved short-only ORB retest scalp. " +
                    "Profile mnq_micro_orb_retest_1m_c013_ready_v1. " +
                    "Locked CELL-013 paper-forward defaults.";

                // Module lock: only the MICRO_ORB retest branch, as tested.
                UseSetupModeFilter = true;
                SetupMode = MnqScalpSetupMode.OrbRetestScalp;
                EnableVwapReclaim = false;
                EnableEmaMomentum = false;
                EnableMicroOrb = true;
                EnableFailedBreakout = false;

                EnableLong = false;
                EnableShort = true;

                // Approved CELL-013 parameters.
                StartingCapital = 2000.0;
                RiskPerTradePct = 0.35;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxTradesPerDay = 20;
                HardMaxTradesPerDay = 25;
                MaxDailyLossUsd = 60.0;
                MaxWeeklyLossUsd = 150.0;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 15;

                RoundTurnCommission = 1.90;
                SlippageTicks = 1;

                AtrStopMult = 0.30;
                MinStopTicks = 6;
                MaxStopTicks = 12;
                RewardRiskRatio = 1.50;
                MoveToBreakevenAtR = 0.7;
                TrailAfterR = 1.0;
                UseTimeStop = true;
                TimeStopBars = 3;
                MinProgressR = 0.30;

                EntryOffsetTicks = 0;
                EntryTimeoutBars = 2;

                TradeStartTime = 635;
                TradeEndTime = 1230;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 1030;
                SecondTradeEndTime = 1200;
                ForceFlatTime = 1245;

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
                MinVolumeFactor = 0.8;
                PullbackLookback = 3;
                RequireSlowTrend = false;
            }
        }
    }
}
