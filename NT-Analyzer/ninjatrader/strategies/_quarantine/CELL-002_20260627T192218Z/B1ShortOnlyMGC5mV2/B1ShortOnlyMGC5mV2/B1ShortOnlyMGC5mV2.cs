// =============================================================================
// B1ShortOnlyMGC5mV2  (v2.0 — friendly deploy wrapper)
// -----------------------------------------------------------------------------
// PURPOSE
//   User-facing deploy strategy for the locked MGC profile
//   `mgc_b1_shortonly_5m_paper_v2`.
//
//   - Class:        B1ShortOnlyMGC5mV2
//   - Display name: "B1 ShortOnly MGC 5m v2 c002"
//   - Engine:       inherits NTAMicroVwapRiskExplorer (research engine).
//                   No trading logic duplicated; this class only locks defaults.
//
// INTENDED USE
//   - Instrument:        MGC 06-26 (Micro Gold, current front contract)
//   - Bars period:       5 Minute
//   - Trading hours:     "Nymex Metals RTH1"
//   - Direction:         Short only
//   - Strategy family:   B1 / VWAP pullback short-only
//   - Commission model:  RoundTurnCommission $1.90 (NinjaTrader project
//                        assumption — NOT prop-firm fees)
//
// PROVENANCE
//   Defaults copied verbatim from
//   data/profiles/strategies.json -> mgc_b1_shortonly_5m_paper_v2
//   evidence: bundle mgc_b1_clone_v2_20260510_034104 plus follow-up stress
//   validation (manual commission-adjusted metrics).
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class B1ShortOnlyMGC5mV2 : NTAMicroVwapRiskExplorer
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "B1 ShortOnly MGC 5m v2 c002";
                Description = "B1 ShortOnly MGC 5m v2 c002 — paper-ready deploy " +
                              "wrapper for the gold port of MNQ CELL-011. " +
                              "Profile: mgc_b1_shortonly_5m_paper_v2. " +
                              "5 Minute, Nymex Metals RTH1, short-only, " +
                              "RoundTurnCommission $1.90 project assumption.";

                // ---- Direction + timing (gold profile lock) ----
                EnableLong = false;
                EnableShort = true;
                TradeStartTime = 600;
                TradeEndTime = 1000;
                UseSecondTradeWindow = false;
                SecondTradeStartTime = 1030;
                SecondTradeEndTime = 1200;
                ForceFlatTime = 1245;

                // ---- Signal filters ----
                EmaFastPeriod = 50;
                EmaSlowPeriod = 200;
                AtrPeriod = 14;
                AdxPeriod = 14;
                MinAdx = 22.0;
                VolumeSmaPeriod = 20;
                MinVolumeFactor = 1.2;
                PullbackLookback = 3;
                UseDailyBiasFilter = false;

                // ---- Stops / targets ----
                AtrStopMult = 0.75;
                MinStopTicks = 12;
                MaxStopTicks = 12;
                RewardRiskRatio = 3.5;
                MoveToBreakevenAtR = 0.8;
                TrailAfterR = 1.2;

                // ---- Entry ----
                EntryTimeoutBars = 2;
                EntryOffsetTicks = 2;

                // ---- Risk profile ----
                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 200.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                // ---- Risk caps ----
                MaxDailyLossPct = 2.0;
                MaxDailyProfitPct = 4.0;
                MaxTradesPerDay = 4;
                MaxConsecutiveLosses = 3;
                UserMaxContracts = 5;

                // ---- Cost model ----
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;
            }
        }
    }
}
