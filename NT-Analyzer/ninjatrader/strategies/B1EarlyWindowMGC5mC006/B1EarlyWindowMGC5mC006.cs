// =============================================================================
// B1EarlyWindowMGC5mC006
// -----------------------------------------------------------------------------
// PURPOSE
//   User-facing deploy wrapper for MGC CELL-006.
//
//   - Class:        B1EarlyWindowMGC5mC006
//   - Display name: "B1 ShortOnly MGC 5m v3 c006"
//   - Engine:       inherits NTAMicroVwapRiskExplorer.
//                   No trading logic duplicated; this class only locks defaults.
//
// INTENDED USE
//   - Instrument:        MGC 06-26
//   - Bars period:       5 Minute
//   - Trading hours:     "Nymex Metals RTH1"
//   - Direction:         Short only
//   - Strategy family:   MGC B1 / VWAP pullback transfer
//   - Status:            paper candidate; no live use without paper-forward review
//
// PROVENANCE
//   Selected from data/research/mgc_cell006_b1_early_window_20260609_210551.
//   Variant: c006_stop20_vf14_0600_0800.
//   Full 2024-2025 after commission: +$852.30, PF 2.11, DD -$147.00, 44 trades.
//   OOS 2025 after commission: +$265.30, PF 1.86.
//   Combined stress slip=2 + fee=$2.40: +$393.80, PF 1.58.
//   Current MGC 06-26 sample: 0 trades, $0.00; sparse-current warning.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class B1EarlyWindowMGC5mC006 : NTAMicroVwapRiskExplorer
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "B1 ShortOnly MGC 5m v3 c006";
                Description = "B1 ShortOnly MGC 5m v3 c006 - paper-candidate " +
                              "deploy wrapper for MGC CELL-006. Profile: " +
                              "mgc_b1_early_window_5m_c006_candidate_v1. " +
                              "5 Minute, Nymex Metals RTH1, short-only, " +
                              "06:00-08:00 PT, MinVolumeFactor 1.4, fixed " +
                              "20-tick stop, RoundTurnCommission $1.90 project assumption.";

                EnableLong = false;
                EnableShort = true;
                TradeStartTime = 600;
                TradeEndTime = 800;
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
