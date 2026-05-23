// =============================================================================
// NTAMnqFullSessionOrbRetestScalpC014
// -----------------------------------------------------------------------------
// User-facing wrapper for the MNQ full-session ORB retest scalp candidate.
//
// This class does not duplicate trading logic. It locks the selected CELL-014
// research configuration from run_mnq_full_session_c014.py:
//   - MNQ 1 Minute
//   - short-only OrbRetestScalp
//   - full active-session window 06:35-12:45 PT, force-flat 13:00 PT
//   - RR=1.75 after cost/stress validation
//
// Current status: paper_ready after direct wrapper validation on 2026-05-13.
// Existing paper-ready c011-c013 wrappers are intentionally untouched.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqFullSessionOrbRetestScalpC014 : NTAMicroMnqScalpPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "Scalping Full Session ORB Retest MNQ 1m v1 c014";
                Description =
                    "Scalping Full Session ORB Retest MNQ 1m v1 c014 - " +
                    "short-only full active-session ORB retest candidate. " +
                    "Profile mnq_full_session_orb_retest_1m_c014_candidate_v1.";

                UseSetupModeFilter = true;
                SetupMode = MnqScalpSetupMode.OrbRetestScalp;
                EnableVwapReclaim = false;
                EnableEmaMomentum = false;
                EnableMicroOrb = true;
                EnableFailedBreakout = false;

                EnableLong = false;
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
                MinStopTicks = 6;
                MaxStopTicks = 12;
                RewardRiskRatio = 1.75;
                MoveToBreakevenAtR = 0.7;
                TrailAfterR = 1.0;
                UseTimeStop = true;
                TimeStopBars = 3;
                MinProgressR = 0.30;

                EntryOffsetTicks = 0;
                EntryTimeoutBars = 2;

                TradeStartTime = 635;
                TradeEndTime = 1245;
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
                MinVolumeFactor = 0.8;
                PullbackLookback = 3;
                RequireSlowTrend = false;
                EmaImpulseLookback = 3;
            }
        }
    }
}
