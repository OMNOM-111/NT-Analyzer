// =============================================================================
// B1Volume14MGC5mC005
// -----------------------------------------------------------------------------
// PURPOSE
//   User-facing deploy strategy for locked MGC CELL-005.
//
//   - Class:        B1Volume14MGC5mC005
//   - Display name: "B1 Volume14 MGC 5m c005"
//   - Engine:       inherits NTAMicroVwapRiskExplorer.
//                   No trading logic duplicated; this class only locks defaults.
//
// INTENDED USE
//   - Instrument:        MGC 06-26 (Micro Gold, current front contract)
//   - Bars period:       5 Minute
//   - Trading hours:     "Nymex Metals RTH1"
//   - Direction:         Short only
//   - Strategy family:   B1 / VWAP pullback short-only with stricter volume gate
//   - Paper/demo only:   no live use without a separate approval cycle
//
// PROVENANCE
//   Selected from data/research/mgc_cell003_b1_validation_20260522_190141.
//   Variant: cell003_vf14_filter.
//   Full 2024-2025 after commission: +$934.20, PF 1.90, DD -$157.50.
//   OOS 2025 after commission: +$189.40, PF 1.35.
//   Combined stress slip=2 + fee=$2.40: +$368.80, PF 1.33.
//   Current MGC 06-26 sample: 3 trades, +$14.60 after commission.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class B1Volume14MGC5mC005 : NTAMicroVwapRiskExplorer
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "B1 Volume14 MGC 5m c005";
                Description = "B1 Volume14 MGC 5m c005 - paper-ready deploy " +
                              "wrapper for MGC CELL-005. Profile: " +
                              "mgc_b1_volume14_5m_paper_c005. 5 Minute, " +
                              "Nymex Metals RTH1, short-only, MinVolumeFactor 1.4, " +
                              "RoundTurnCommission $1.90 project assumption.";

                EnableLong = false;
                EnableShort = true;
                TradeStartTime = 600;
                TradeEndTime = 1000;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 1030;
                SecondTradeEndTime = 1200;
                ForceFlatTime = 1245;

                EmaFastPeriod = 50;
                EmaSlowPeriod = 200;
                AtrPeriod = 14;
                AdxPeriod = 14;
                MinAdx = 22.0;
                VolumeSmaPeriod = 20;
                MinVolumeFactor = 1.4;
                PullbackLookback = 3;
                UseDailyBiasFilter = false;

                AtrStopMult = 0.75;
                MinStopTicks = 12;
                MaxStopTicks = 12;
                RewardRiskRatio = 3.5;
                MoveToBreakevenAtR = 0.8;
                TrailAfterR = 1.2;

                EntryTimeoutBars = 2;
                EntryOffsetTicks = 2;

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 200.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                MaxDailyLossPct = 2.0;
                MaxDailyProfitPct = 4.0;
                MaxTradesPerDay = 4;
                MaxConsecutiveLosses = 3;
                UserMaxContracts = 5;

                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
        }
    }
}
