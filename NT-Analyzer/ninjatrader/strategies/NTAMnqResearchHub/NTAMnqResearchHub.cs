// =============================================================================
// NTAMnqResearchHub
// -----------------------------------------------------------------------------
// Stable MNQ Research Hub.
//
// Purpose:
//   Long-lived, mode-driven research class for new MNQ ideas. It intentionally
//   does not reserve a portfolio cell and should not be used as a paper/live
//   deploy strategy. Promotion still requires a separate deploy wrapper with
//   locked parameters and evidence.
//
// Engine:
//   Inherits NTAMnqSessionEdgeEngineC020, the current MNQ session-edge engine.
//   That keeps the existing Mode contract and risk shell intact while giving
//   future research a stable class name that is not tied to CELL-020.
// =============================================================================

#region Using
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NTAMnqResearchHub : NTAMnqSessionEdgeEngineC020
    {
        protected override void OnStateChange()
        {
            base.OnStateChange();

            if (State == State.SetDefaults)
            {
                Name = "MNQ Research Hub";
                Description =
                    "MNQ mode-driven Research Hub. Use Mode plus job parameters " +
                    "for smoke/full/IS/OOS/stress research without creating a new " +
                    "deploy class for every hypothesis. Do not run this class as " +
                    "paper/live; promote only through a locked deploy wrapper.";
            }
        }
    }
}
