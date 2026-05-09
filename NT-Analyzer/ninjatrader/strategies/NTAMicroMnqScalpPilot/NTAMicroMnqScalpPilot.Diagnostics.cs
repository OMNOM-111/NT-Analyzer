// NTAMicroMnqScalpPilot.Diagnostics.cs
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class NTAMicroMnqScalpPilot
    {
        private void LogSkip(string reason)
        {
            if (CurrentBar == _lastSkipBar && reason == _lastSkipReason) return;
            _lastSkipBar    = CurrentBar;
            _lastSkipReason = reason;
            Print(string.Format("[SKIP:{0}] bar={1} time={2:HH:mm} px={3:F2}",
                                reason, CurrentBar, Time[0], Close[0]));
        }
    }
}
