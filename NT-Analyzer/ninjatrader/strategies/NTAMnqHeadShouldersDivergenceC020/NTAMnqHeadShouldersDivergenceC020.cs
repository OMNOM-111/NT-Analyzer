// =============================================================================
// NTAMnqHeadShouldersDivergenceC020
// -----------------------------------------------------------------------------
// Deploy wrapper for MNQ CELL-020.
//
// Research path:
//   Hub:    NTAMnqResearchHub
//   Mode:   HeadAndShouldersLive
//   Bundle: NT-Analyzer/data/research/
//           mnq_hns_1m_live_time_dow_validation_20260603_213032
//
// Promotion evidence:
//   Label: hns_1m_liveconf_s3_m17_0730_0755
//   Full:  +$460.30, PF 1.519, DD -$216.30, 53 trades, same-bar 0.00%
//   IS:    +$50.30
//   OOS:   +$410.00, PF 2.129
//   Stress slip2+fee2.40: +$373.30, PF 1.400
//   Current30D: $0.00, 0 trades
//
// This profile deliberately starts five minutes after CELL-019. It is
// paper-forward only until correlation/overlap is reviewed.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqHeadShouldersDivergenceC020 : NTAMnqResearchHub
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "HeadShoulders Divergence MNQ 1m v1 c020";
                Description =
                    "CELL-020 MNQ Head & Shoulders live right-shoulder short with RSI divergence. " +
                    "Locked from NTAMnqResearchHub label hns_1m_liveconf_s3_m17_0730_0755.";

                InstrumentName = "MNQ";
                ContractName = "MNQ 06-26";
                SessionTemplateName = "CME US Index Futures ETH";
                BaseTimeframeSeconds = 60;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = false;
                EnableShort = true;
                Mode = "HeadAndShouldersLive";

                RangeStartTime = 0;
                RangeEndTime = 630;
                TradeStartTime = 730;
                TradeEndTime = 755;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 100;
                SecondTradeEndTime = 300;
                ForceFlatTime = 800;
                AllowedWeekdayMask = 17; // Monday + Friday.

                EntryTimeoutBars = 3;
                PullbackTicks = 48;
                DriveTicks = 28;
                FailReturnTicks = 5;
                RejectWickTicks = 6;
                ReclaimBufferTicks = 6;

                RequireEmaStack = false;
                RequireVwapAgreement = true;
                RequireEmaAgreement = true;
                RequireEmaSlope = false;
                EmaFastPeriod = 9;
                EmaMidPeriod = 21;
                EmaSlowPeriod = 50;
                AtrPeriod = 14;
                VolumeSmaPeriod = 20;
                MinVolumeFactor = 0.55;

                StopBufferTicks = 4;
                MinStopTicks = 8;
                MaxStopTicks = 150;
                AtrStopMult = 0.0;
                RewardRiskRatio = 0.90;
                MinTargetTicks = 14;
                EntryOffsetTicks = 4;
                MoveToBreakevenAtR = 0.0;
                BreakevenPlusTicks = 2;
                UseTrailingStop = false;
                TrailAfterR = 1.5;
                TrailDistanceTicks = 12;
                UseTimeStop = true;
                TimeStopBars = 18;
                MinProgressR = 0.20;

                RiskPerTradePct = 0.75;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                MaxDailyLossUsd = 80.0;
                MaxWeeklyLossUsd = 200.0;
                MaxTradesPerDay = 3;
                HardMaxTradesPerDay = 5;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 60;

                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
        }
    }
}
