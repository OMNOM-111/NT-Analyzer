using System.Globalization;
using System.Runtime.CompilerServices;

namespace NTAnalyzerBridge.Util
{
    /// <summary>
    /// Computes a stable-per-process id for a NinjaScript Strategy instance.
    /// Same formula MUST be used by the telemetry exporter and the command
    /// processor, so a command issued from the UI targets the exact same
    /// object the UI saw in strategies.json.
    /// </summary>
    internal static class RuntimeInstanceIdUtil
    {
        public static string Compute(object strat, string accountName,
                                     string className, string instrumentFullName,
                                     string strategyName)
        {
            int identity = strat == null ? 0 : RuntimeHelpers.GetHashCode(strat);
            string raw = (accountName ?? "") + "|" + (className ?? "") + "|"
                       + (instrumentFullName ?? "") + "|" + (strategyName ?? "") + "|"
                       + identity.ToString(CultureInfo.InvariantCulture);
            return Sha256.OfString(raw).Substring(0, 16);
        }
    }
}
