// =============================================================================
// NTAMnqMicroOrbOpenScalp
// -----------------------------------------------------------------------------
// User-facing wrapper for the MNQ Micro ORB RR150 research baseline.
//
// This class does not duplicate trading logic. It locks the profitable research
// configuration from profile mnq_micro_orb_open_rr150_1m_research_v2 while the
// profile remains research_baseline, not paper_ready.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqMicroOrbOpenScalp : NTAMicroMnqScalpPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "NTA MNQ Micro ORB Open Scalp";
                Description =
                    "NTA MNQ Micro ORB Open Scalp - RR150 research baseline. " +
                    "Profile mnq_micro_orb_open_rr150_1m_research_v2. " +
                    "Not paper-ready: slip=2 stress is negative; use for research only.";

                // Module lock: only the MICRO_ORB family, as tested.
                UseSetupModeFilter = false;
                SetupMode = MnqScalpSetupMode.OrbContinuationScalp;
                EnableVwapReclaim = false;
                EnableEmaMomentum = false;
                EnableMicroOrb = true;
                EnableFailedBreakout = false;

                EnableLong = true;
                EnableShort = true;

                // RR150 candidate parameters.
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

                AtrStopMult = 0.35;
                MinStopTicks = 8;
                MaxStopTicks = 16;
                RewardRiskRatio = 1.50;
                MoveToBreakevenAtR = 0.7;
                TrailAfterR = 1.0;
                UseTimeStop = true;
                TimeStopBars = 3;
                MinProgressR = 0.30;

                EntryOffsetTicks = 1;
                EntryTimeoutBars = 2;

                TradeStartTime = 635;
                TradeEndTime = 830;
                UseSecondTradeWindow = true;
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
            }
        }
    }
}
