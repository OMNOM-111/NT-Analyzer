// =============================================================================
// VWAPPullbackMGC5mV1  (v1.0 — friendly deploy wrapper)
// -----------------------------------------------------------------------------
// PURPOSE
//   User-facing deploy strategy for the locked SessionEdge v2 MGC profile
//   `sev2_mgc_vwappullback_shortonly_paper_v1`.
//
//   - Class:        VWAPPullbackMGC5mV1
//   - Display name: "Scalping Gold MGC 5m v1 c001"
//   - Engine:       inherits NTAMicroSessionEdgeExplorer (research engine).
//                   No logic duplicated; this class only locks defaults.
//
// INTENDED USE
//   - Instrument:        MGC 06-26 (Micro Gold, current front contract)
//   - Bars period:       5 Minute
//   - Trading hours:     "Nymex Metals RTH1"
//   - Direction:         Short only
//   - Strategy:          VwapPullback (SessionEdge SetupMode)
//   - Commission model:  RoundTurnCommission $1.90 (NinjaTrader project
//                        assumption — NOT TopStep fees)
//
// PROVENANCE
//   Defaults copied verbatim from
//   data/profiles/strategies.json -> sev2_mgc_vwappullback_shortonly_paper_v1
//   evidence: bundle session_edge_v2_20260505_2208 (Stage A, B, D).
//
// LOCKED PILOT
//   NTAMicroVwapRiskPilot (MNQ paper-ready) is untouched. This wrapper does
//   NOT inherit from it and does NOT change MNQ behavior.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class VWAPPullbackMGC5mV1 : NTAMicroSessionEdgeExplorer
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name        = "Scalping Gold MGC 5m v1 c001";
                Description = "Scalping Gold MGC 5m v1 c001 — paper-ready " +
                              "deploy of SessionEdge v2 VwapPullback shortonly " +
                              "for MGC 06-26 (5 Minute, Nymex Metals RTH1). " +
                              "Profile: sev2_mgc_vwappullback_shortonly_paper_v1. " +
                              "RoundTurnCommission $1.90 is a NinjaTrader project " +
                              "assumption (not TopStep fees).";

                // ---- Mode + direction (locked) ----
                SetupMode   = SessionEdgeSetupMode.VwapPullback;
                EnableLong  = false;
                EnableShort = true;

                // ---- Trading window (PT) ----
                TradeStartTime  = 600;
                TradeEndTime    = 1000;
                ForceFlatTime   = 1245;
                UseSecondTradeWindow = false;

                // ---- Filters (from card) ----
                MinAdx          = 22.0;
                MinVolumeFactor = 1.2;
                PullbackLookback = 3;

                // ---- Stops / targets (from card) ----
                MinStopTicks    = 12;
                MaxStopTicks    = 12;
                RewardRiskRatio = 3.5;
                AtrStopMult     = 0.75;
                MoveToBreakevenAtR = 0.8;
                TrailAfterR     = 1.2;

                // ---- Entry ----
                EntryOffsetTicks = 2;
                EntryTimeoutBars = 2;

                // ---- Risk profile (MGC card values) ----
                StartingCapital         = 2000.0;
                IntradayOnly            = true;
                ActiveMarginPerContract = 1000.0;
                MaxContractsByCapital   = 20;
                InstrumentStatus        = "allowed";
                MarginSourceBroker      = "NinjaTrader";

                // ---- Risk caps ----
                MaxDailyLossPct      = 2.0;
                MaxDailyProfitPct    = 4.0;
                MaxTradesPerDay      = 4;
                MaxConsecutiveLosses = 3;
                UserMaxContracts     = 5;

                // ---- Cost model (NinjaTrader project assumption) ----
                RoundTurnCommission = 1.90;
                SlippageTicks       = 1;

                // ---- Engine internals (kept identical to research) ----
                EmaFastPeriod   = 50;
                EmaSlowPeriod   = 200;
                AtrPeriod       = 14;
                AdxPeriod       = 14;
                VolumeSmaPeriod = 20;
                UseDailyBiasFilter = false;
            }
        }
    }
}
