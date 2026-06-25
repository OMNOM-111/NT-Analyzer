using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Reporting
{
    /// <summary>
    /// Computes run_hash per docs/job-schema.md, contract 0.2 rule:
    /// hash of the canonical job context (strategy class + final parameters
    /// + instrument + timeframe + period + execution + addon_version
    /// + ninjatrader_custom_dll_sha256 + source_file_sha256
    /// + historical_data_fingerprint).
    ///
    /// Contract change vs 0.1: historical_data_fingerprint, session_template,
    /// slippage, commission and fill model (carried inside execution) ARE now
    /// mixed in, so two runs over different NT history / session / fill
    /// assumptions no longer collide on the same run_hash. See the Stage 2
    /// runtime/backtest mismatch audit.
    /// </summary>
    internal static class RunHashCalculator
    {
        public const string ContractVersion = "0.2";

        public static string Compute(JObject jobContext, string addonVersion,
            string customDllSha256, string sourceFileSha256)
        {
            var canonical = new JObject
            {
                ["schema_version"]              = ContractVersion,
                ["addon_version"]               = addonVersion ?? string.Empty,
                ["ninjatrader_custom_dll_sha256"] = customDllSha256 ?? string.Empty,
                ["source_file_sha256"]          = sourceFileSha256 ?? string.Empty,
                ["strategy"]                    = jobContext["strategy"],
                ["instrument"]                  = jobContext["instrument"],
                ["timeframe"]                   = jobContext["timeframe"],
                ["period"]                      = jobContext["period"],
                ["execution"]                   = jobContext["execution"],
                ["historical_data_fingerprint"] = jobContext["historical_data_fingerprint"]
            };
            // Stable serialization: indented, properties sorted alphabetically.
            string canon = SortedJson(canonical);
            return Sha256.OfString(canon);
        }

        private static string SortedJson(JToken token)
        {
            JToken sorted = SortToken(token);
            return sorted.ToString(Formatting.None);
        }

        private static JToken SortToken(JToken token)
        {
            if (token is JObject obj)
            {
                var sorted = new JObject();
                foreach (var prop in obj.Properties().OrderBy(p => p.Name, StringComparer.Ordinal))
                    sorted[prop.Name] = SortToken(prop.Value);
                return sorted;
            }
            if (token is JArray arr)
            {
                var sortedArr = new JArray();
                foreach (var item in arr) sortedArr.Add(SortToken(item));
                return sortedArr;
            }
            return token.DeepClone();
        }
    }
}
