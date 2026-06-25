// =============================================================================
// NTAMnqEntropyTransitionFieldC127
// -----------------------------------------------------------------------------
// User-facing deploy wrapper for MNQ CELL-127.
//
//   - Class:        NTAMnqEntropyTransitionFieldC127
//   - Display name: "Entropy Transition Field MNQ 5m c127"
//   - Engine:       inherits NTAEntropyTransitionFieldPilot.
//                   No trading logic duplicated; this class only locks defaults.
//
// INTENDED USE
//   - Instrument:        MNQ 06-26 / front MNQ
//   - Bars period:       5 Minute
//   - Trading hours:     "CME US Index Futures RTH"
//   - Direction:         Short only
//   - Strategy family:   Entropy Transition Field
//   - Status:            paper-ready candidate; no live use without paper review
//
// PROVENANCE
//   Selected after all portfolio roots were scanned first.
//   Portfolio scan: data/research/entropy_transition_field_consensus_portfolio_scan_20260610_195935.
//   Deep refine: data/research/entropy_transition_field_mnq_short_refine2_20260610_201030.
//   Final validation: data/research/entropy_transition_field_mnq_short_field1_validation_20260610_201650.
//   Variant: short_field1 / mnq_short_field1_candidate_v1.
//   Full 2024-2025 after commission: +$934.60, PF 1.55, DD -$260.10, 111 trades.
//   IS 2024 after commission: +$178.20, PF 1.18.
//   OOS 2025 after commission: +$756.40, PF 2.09.
//   Stress slip=2: +$887.50, PF 1.53.
//   Stress fee: +$898.00, PF 1.52.
//   Combined stress: +$909.70, PF 1.56.
//   Current MNQ 06-26 sample: 20 trades, +$237.50, PF 1.53.
// =============================================================================

#region Using declarations
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqEntropyTransitionFieldC127 : NTAEntropyTransitionFieldPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "Entropy Transition Field MNQ 5m c127";
                Description = "Entropy Transition Field MNQ 5m c127 - paper-ready candidate " +
                              "deploy wrapper for MNQ CELL-127. Original state-transition " +
                              "entropy model; short-only; 5 Minute; CME US Index Futures RTH; " +
                              "profile mnq_short_field1_candidate_v1.";

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 100.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                RiskPerTradePct = 0.75;
                MaxDailyLossPct = 3.0;
                MaxDailyProfitPct = 0.0;
                MaxTradesPerDay = 5;
                UserMaxContracts = 5;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;

                EnableLong = false;
                EnableShort = true;
                TradeStartTime = 600;
                TradeEndTime = 1230;
                ForceFlatTime = 1325;

                StateWindow = 780;
                MinStateSamples = 8;
                NeutralMoveTicks = 1.0;
                ReturnBucketTicks = 8.0;
                BodyBalanceThreshold = 0.25;
                VolumeLookback = 30;
                VolumeLowFactor = 0.75;
                VolumeHighFactor = 1.50;
                UseTimeState = true;
                MinForecastTicks = 3.0;
                MinDirectionalProbability = 0.62;
                MaxEntropy = 0.80;
                MinEdgeScore = 1.00;
                CostMultiple = 1.00;
                MinBarsBetweenEntries = 1;
                ShrinkageSamples = 4.0;
                UseConsensusField = true;
                ConsensusWindow = 1040;
                ConsensusMinStateSamples = 16;
                ConsensusMinDirectionalProbability = 0.54;
                ConsensusMaxEntropy = 0.96;
                ConsensusMinEdgeScore = 0.20;
                FieldMode = 1;

                MinStopTicks = 10;
                MaxStopTicks = 110;
                StopSigmaMult = 1.40;
                RewardRiskRatio = 1.25;
                MoveToBreakevenAtR = 0.80;
                TrailAfterR = 1.60;
                MaxHoldBars = 12;
            }
        }
    }
}
