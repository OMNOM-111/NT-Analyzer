// =============================================================================
// B1Stop24MGC5mC003
// -----------------------------------------------------------------------------
// PURPOSE
//   User-facing deploy strategy for locked MGC CELL-003.
//
//   - Class:        B1Stop24MGC5mC003
//   - Display name: "B1 Stop24 MGC 5m c003"
//   - Engine:       inherits NTAMicroVwapRiskExplorer.
//                   No trading logic duplicated; this class only locks defaults.
//
// INTENDED USE
//   - Instrument:        MGC 06-26 (Micro Gold, current front contract)
//   - Bars period:       5 Minute
//   - Trading hours:     "Nymex Metals RTH1"
//   - Direction:         Short only
//   - Strategy family:   B1 / VWAP pullback short-only
//   - Paper/demo only:   no live use without a separate approval cycle
//
// PROVENANCE
//   Selected from data/research/mgc_cell003_b1_validation_20260511_211307.
//   Winner variant: cell003_stop24_rr30.
//   Full 2024-2025 after commission: +$604.80, PF 1.72, DD -$111.60.
//   OOS 2025 after commission: +$301.90, PF 1.68.
//   Combined stress slip=2 + fee=$2.40: +$481.80, PF 1.53.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class B1Stop24MGC5mC003 : NTAMicroVwapRiskExplorer
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "B1 Stop24 MGC 5m c003";
                Description = "B1 Stop24 MGC 5m c003 - paper-ready deploy " +
                              "wrapper for MGC CELL-003. Profile: " +
                              "mgc_b1_stop24_5m_paper_c003. 5 Minute, " +
                              "Nymex Metals RTH1, short-only, " +
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
                MinVolumeFactor = 1.2;
                PullbackLookback = 3;
                UseDailyBiasFilter = false;

                AtrStopMult = 0.75;
                MinStopTicks = 24;
                MaxStopTicks = 24;
                RewardRiskRatio = 3.0;
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
