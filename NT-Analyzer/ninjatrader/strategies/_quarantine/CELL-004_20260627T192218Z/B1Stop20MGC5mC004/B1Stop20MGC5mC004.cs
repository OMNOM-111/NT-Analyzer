// =============================================================================
// B1Stop20MGC5mC004
// -----------------------------------------------------------------------------
// PURPOSE
//   User-facing deploy strategy for locked MGC CELL-004.
//
//   - Class:        B1Stop20MGC5mC004
//   - Display name: "B1 Stop20 MGC 5m c004"
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
//   Variant: cell003_stop20_0600_1000.
//   Full 2024-2025 after commission: +$819.10, PF 1.80, DD -$202.20.
//   OOS 2025 after commission: +$257.10, PF 1.63.
//   Combined stress slip=2 + fee=$2.40: +$367.60, PF 1.42.
//   Current MGC 06-26 sample: 2 trades, +$43.20 after commission.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class B1Stop20MGC5mC004 : NTAMicroVwapRiskExplorer
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "B1 Stop20 MGC 5m c004";
                Description = "B1 Stop20 MGC 5m c004 - paper-ready deploy " +
                              "wrapper for MGC CELL-004. Profile: " +
                              "mgc_b1_stop20_5m_paper_c004. 5 Minute, " +
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
                MinStopTicks = 20;
                MaxStopTicks = 20;
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
