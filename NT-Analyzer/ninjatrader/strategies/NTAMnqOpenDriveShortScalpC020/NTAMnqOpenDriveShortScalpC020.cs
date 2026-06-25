// =============================================================================
// NTAMnqOpenDriveShortScalpC020
// -----------------------------------------------------------------------------
// Research-only copy of CELL-016.
//
// Purpose:
//   Preserve the corrected C016 hypothesis as a separate CELL-020 wrapper while
//   preventing the failed all-module C016 profile from being treated as active.
//
// Current status:
//   RESEARCH ONLY / NOT PAPER_READY. Preliminary 2026-05-27 audit showed that
//   the ORB+failed-breakout repair still fails full-history slip=3 stress and
//   remains same-bar-fill dependent.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqOpenDriveShortScalpC020 : NTAMicroMnqScalpPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "RESEARCH ONLY Copy C016 Fixed MNQ 1m c020";
                Description =
                    "Research-only corrected copy of C016. " +
                    "Requires tick/market-replay validation before any paper-forward use.";

                UseSetupModeFilter = false;
                EnableLong = false;
                EnableShort = true;

                EnableVwapReclaim = false;
                EnableEmaMomentum = false;
                EnableMicroOrb = true;
                EnableFailedBreakout = true;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                RiskPerTradePct = 0.35;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxTradesPerDay = 6;
                HardMaxTradesPerDay = 8;
                MaxDailyLossUsd = 25.0;
                MaxWeeklyLossUsd = 75.0;
                MaxDailyLossPct = 3.0;
                MaxDailyProfitPct = 0.0;
                MaxConsecutiveLosses = 2;
                PauseAfterConsecutiveLosses = 1;
                PauseMinutesAfterLosses = 30;

                RoundTurnCommission = 1.90;
                SlippageTicks = 3;

                AtrStopMult = 0.30;
                MinStopTicks = 6;
                MaxStopTicks = 14;
                RewardRiskRatio = 2.00;
                MoveToBreakevenAtR = 0.7;
                TrailAfterR = 1.0;
                UseTimeStop = true;
                TimeStopBars = 3;
                MinProgressR = 0.30;

                EntryOffsetTicks = 1;
                EntryTimeoutBars = 1;

                TradeStartTime = 635;
                TradeEndTime = 700;
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
                MinVolumeFactor = 1.0;
                PullbackLookback = 3;
                RequireSlowTrend = false;
                EmaImpulseLookback = 3;
            }
        }
    }
}
