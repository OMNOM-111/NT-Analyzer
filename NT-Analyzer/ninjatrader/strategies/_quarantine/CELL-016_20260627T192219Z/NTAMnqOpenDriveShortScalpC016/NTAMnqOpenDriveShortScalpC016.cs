// =============================================================================
// NTAMnqOpenDriveShortScalpC016
// -----------------------------------------------------------------------------
// User-facing wrapper for the MNQ CELL-016 high-frequency opening-drive scalp.
//
// This class does not duplicate trading logic. It locks the selected
// NTAMicroMnqScalpPilot research configuration from
// run_mnq_cell016_highfreq_search.py:
//   - MNQ 1 Minute
//   - short-only, all scalp modules enabled
//   - entries only 06:35-07:30 PT, force-flat 13:00 PT
//   - 4-10 tick stop box, RR=4.00
//
// Current status: paper_ready after direct wrapper validation on 2026-05-13.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqOpenDriveShortScalpC016 : NTAMicroMnqScalpPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "Scalping Open Drive Short MNQ 1m v1 c016";
                Description =
                    "Scalping Open Drive Short MNQ 1m v1 c016 - " +
                    "high-frequency short-only opening-drive scalp. " +
                    "Profile mnq_open_drive_short_scalp_1m_c016_candidate_v1.";

                UseSetupModeFilter = false;
                EnableVwapReclaim = true;
                EnableEmaMomentum = true;
                EnableMicroOrb = true;
                EnableFailedBreakout = true;

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
                TradeEndTime = 730;
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
