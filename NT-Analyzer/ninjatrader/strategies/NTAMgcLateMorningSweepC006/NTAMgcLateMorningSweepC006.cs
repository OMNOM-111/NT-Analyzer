// =============================================================================
// NTAMgcLateMorningSweepC006
// -----------------------------------------------------------------------------
// Deploy wrapper for MGC CELL-006 late-session free window.
//
// Hypothesis: after morning gold profiles (06:00-10:00 PT), fade liquidity
// sweeps beyond the 06:00-10:00 opening range and target session VWAP.
//
// Engine: NTAMicroGoldSessionSweepReversalPilot (no duplicated logic).
// Research runner: run_mgc_cell006_morning_sweep.py
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMgcLateMorningSweepC006 : NTAMicroGoldSessionSweepReversalPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "Scalping Late Morning Sweep MGC 1m v1 c006";
                Description =
                    "Scalping Late Morning Sweep MGC 1m v1 c006 - " +
                    "late-session sweep fade of 06:00-10:00 opening range. " +
                    "Profile mgc_late_morning_sweep_1m_c006_candidate_v1.";

                InstrumentName = "MGC";
                ContractName = "MGC 06-26";
                SessionTemplateName = "Nymex Metals RTH1";
                BaseTimeframeSeconds = 60;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 200.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                EnableLong = false;
                EnableShort = true;
                AnchorMode = GoldSweepAnchorMode.OpeningRange;
                TargetMode = GoldSweepTargetMode.VwapThenRR;

                TradeStartTime = 1000;
                TradeEndTime = 1325;
                ForceFlatTime = 1330;
                OpeningRangeStartTime = 930;
                OpeningRangeMinutes = 30;

                EmaFastPeriod = 9;
                EmaSlowPeriod = 34;
                AtrPeriod = 14;
                AdxPeriod = 14;
                VolumeSmaPeriod = 20;
                MinAdx = 0.0;
                MinVolumeFactor = 1.0;
                MinBodyRangePct = 0.25;
                MinCloseLocationPct = 0.55;
                UseTrendFilter = false;
                UseVwapSideFilter = true;
                MinDistanceToVwapTicks = 3;

                SweepDistanceTicks = 2;
                ReturnInsideTicks = 1;
                SweepMaxBarsToReturn = 3;
                MinOpeningRangeTicks = 8;
                MaxOpeningRangeTicks = 120;

                StopBeyondSweepTicks = 2;
                ClampStopToMaxTicks = true;
                MinStopTicks = 10;
                MaxStopTicks = 10;
                MaxOpeningRangeTicks = 90;
                AtrStopMult = 0.35;
                RewardRiskRatio = 2.0;
                EntryOffsetTicks = 1;
                EntryTimeoutBars = 2;
                MinTargetTicks = 8;
                VwapTargetOffsetTicks = 1;
                TimeStopBars = 8;
                MinProgressR = 0.12;

                RiskPerTradePct = 1.0;
                UserMaxContracts = 1;
                MaxOpenPositions = 1;
                DailyLossLimit = 60.0;
                WeeklyLossLimit = 150.0;
                MaxTradesPerDay = 4;
                HardMaxTradesPerDay = 6;
                MaxConsecutiveLosses = 3;
                PauseAfterConsecutiveLosses = 2;
                PauseMinutesAfterLosses = 15;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
        }
    }
}
