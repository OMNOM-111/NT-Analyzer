// =============================================================================
// B1EarlyWindowMGC5mC008
// -----------------------------------------------------------------------------
// PURPOSE
//   User-facing deploy wrapper for MGC CELL-008.
//
//   - Class:        B1EarlyWindowMGC5mC008
//   - Display name: "B1 ShortOnly MGC 5m v4 c008"
//   - Engine:       inherits B1EarlyWindowMGC5mC006 / NTAMicroVwapRiskExplorer.
//                   No trading logic duplicated; this class locks the selected
//                   C008 parameter delta.
//
// PROVENANCE
//   Manual R&D 2026-07-03, branch C008 v4.
//   Change vs C006: MinAdx 22 -> 24 to remove weaker early-window shocks.
//   Full 2024-2025 after commission: +$686.00, PF 2.19, DD -$95.60, 35 trades.
//   IS 2024 after commission: +$321.00, PF 2.66.
//   OOS 2025 after commission: +$158.60, PF 1.74.
//   Current 2026 YTD after commission: +$196.70, PF 3.74.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class B1EarlyWindowMGC5mC008 : B1EarlyWindowMGC5mC006
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "B1 ShortOnly MGC 5m v4 c008";
                Description = "B1 ShortOnly MGC 5m v4 c008 - MGC CELL-008 " +
                              "deploy wrapper. Based on C006 B1 early-window " +
                              "short-only profile with MinAdx raised to 24. " +
                              "5 Minute, Nymex Metals RTH1, 06:00-08:00 PT, " +
                              "fixed 20-tick stop, RewardRiskRatio 3.5, " +
                              "RoundTurnCommission $1.90 project assumption.";

                MinAdx = 24.0;
            }
        }
    }
}