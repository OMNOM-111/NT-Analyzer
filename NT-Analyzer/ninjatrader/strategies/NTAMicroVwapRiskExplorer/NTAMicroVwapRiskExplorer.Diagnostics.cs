// NTAMicroVwapRiskExplorer.Diagnostics.cs
// Skip-logging helper with per-bar+reason deduplication.
// Part of partial class NTAMicroVwapRiskExplorer.

using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract partial class NTAMicroVwapRiskExplorer
    {
        #region Skip logging
        private void LogSkip(string reason)
        {
            // Dedupe: print once per bar per reason to avoid spam on tick/bar recalc.
            if (CurrentBar == _lastSkipBar && reason == _lastSkipReason) return;
            _lastSkipBar    = CurrentBar;
            _lastSkipReason = reason;
            Print(string.Format("[SKIP:{0}] bar={1} time={2:HH:mm} px={3:F2}",
                                reason, CurrentBar, Time[0], Close[0]));
        }
        #endregion
    }
}
