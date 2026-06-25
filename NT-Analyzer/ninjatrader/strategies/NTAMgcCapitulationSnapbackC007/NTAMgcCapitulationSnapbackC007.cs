// =============================================================================
// NTAMgcCapitulationSnapbackC007
// -----------------------------------------------------------------------------
// PURPOSE
//   User-facing deploy wrapper for MGC CELL-007.
//
//   - Class:        NTAMgcCapitulationSnapbackC007
//   - Display name: "Capitulation Snapback MGC 5m c007"
//   - Engine:       inherits NTACapitulationSnapbackPilot.
//                   No trading logic duplicated; this class only locks defaults.
//
// INTENDED USE
//   - Instrument:        MGC 06-26 / front MGC
//   - Bars period:       5 Minute
//   - Trading hours:     "Nymex Metals RTH1"
//   - Direction:         Short only
//   - Strategy family:   MGC capitulation snapback
//   - Status:            paper candidate; no live use without paper-forward review
//
// PROVENANCE
//   Selected from data/research/capitulation_snapback_refine_20260609_234850.
//   Variant: mgc_short_loose_noext_confirm20.
//   Full 2024-2025 after commission: +$904.60, PF 1.61, DD -$298.80, 85 trades.
//   IS 2024 after commission: +$170.50, PF 1.23.
//   OOS 2025 after commission: +$734.10, PF 2.01.
//   Stress slip=2: +$604.60, PF 1.38.
//   Stress fee x2: +$741.20, PF 1.48.
//   Current MGC 08-26 sample: 1 trade, +$142.10; sparse-current warning.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMgcCapitulationSnapbackC007 : NTACapitulationSnapbackPilot
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "Capitulation Snapback MGC 5m c007";
                Description = "Capitulation Snapback MGC 5m c007 - paper-candidate " +
                              "deploy wrapper for MGC CELL-007. Profile: " +
                              "mgc_capitulation_snapback_5m_c007_candidate_v1. " +
                              "5 Minute, Nymex Metals RTH1, short-only, " +
                              "06:35-10:00 PT, no-extreme-break confirm, " +
                              "RoundTurnCommission $1.90 project assumption.";

                StartingCapital = 2000.0;
                IntradayOnly = true;
                ActiveMarginPerContract = 200.0;
                MaxContractsByCapital = 20;
                InstrumentStatus = "allowed";
                MarginSourceBroker = "NinjaTrader";

                RiskPerTradePct = 1.0;
                MaxDailyLossPct = 3.0;
                MaxDailyProfitPct = 0.0;
                MaxTradesPerDay = 8;
                UserMaxContracts = 5;
                RoundTurnCommission = 1.90;
                SlippageTicks = 1;

                EnableLong = false;
                EnableShort = true;
                TradeStartTime = 635;
                TradeEndTime = 1000;
                ForceFlatTime = 1325;

                AtrPeriod = 14;
                AdxPeriod = 14;
                EmaPeriod = 50;
                VolumeSmaPeriod = 20;
                MinAdx = 0.0;
                MaxAdx = 100.0;
                MinVolumeFactor = 1.4;
                ShockAtrMult = 0.95;
                ExtensionAtr = 0.6;
                MinBodyFraction = 0.55;
                ReclaimFraction = 0.35;
                ExtremeLookbackBars = 12;
                MinConfirmBodyFraction = 0.20;
                RequireNoExtremeBreak = true;
                RequireReclaimPrevOpen = false;
                RequireVwapReclaim = false;

                MinStopTicks = 10;
                MaxStopTicks = 120;
                StopBufferTicks = 2;
                RewardRiskRatio = 1.2;
                MoveToBreakevenAtR = 0.8;
                TrailAfterR = 1.6;
                MaxHoldBars = 18;
            }
        }
    }
}
