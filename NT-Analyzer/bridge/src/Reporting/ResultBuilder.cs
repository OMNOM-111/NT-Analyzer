using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Reporting
{
    /// <summary>
    /// Assembles result.json per docs/job-schema.md, contract v0.1.
    ///
    /// The result is intentionally self-sufficient: it does NOT reference
    /// job.json by file path — every field needed to understand the run
    /// is duplicated into context.
    /// </summary>
    internal sealed class ResultBuilder
    {
        public string AddOnVersion { get; set; } = "0.1.0";
        public string NinjaTraderVersion { get; set; }
        public string CustomDllSha256 { get; set; }
        public string ResolvedSourceFile { get; set; }
        public string SourceFileSha256 { get; set; }
        public DateTime? SourceFileMtimeUtc { get; set; }
        public string RdVariantUsed { get; set; } = "1_strategy_analyzer";

        public DateTime StartedAtUtc { get; set; } = DateTime.UtcNow;

        public JObject Build(string jobId, JObject job, Type strategyType,
                             JObject finalParameters,
                             JArray trades, JObject metrics,
                             IEnumerable<string> verificationWarnings)
        {
            DateTime finished = DateTime.UtcNow;
            int duration = (int)Math.Max(0, (finished - StartedAtUtc).TotalMilliseconds);

            string instrument = (string)job["instrument"];
            JObject timeframe = (JObject)job["timeframe"];
            JObject period    = (JObject)job["period"];
            JObject execution = (JObject)job["execution"];

            // Build a "context" object that mirrors job context but with
            // resolved/canonical values.
            var context = new JObject
            {
                ["strategy"] = new JObject
                {
                    ["class_name"]                    = strategyType?.Name,
                    ["resolved_source_file"]          = ResolvedSourceFile ?? string.Empty,
                    ["source_file_sha256"]            = SourceFileSha256 ?? "sha256:placeholder",
                    ["ninjatrader_custom_dll_sha256"] = CustomDllSha256 ?? "sha256:placeholder",
                    ["final_parameters"]              = finalParameters ?? new JObject()
                },
                ["instrument"] = instrument,
                ["timeframe"]  = timeframe?.DeepClone() ?? new JObject(),
                ["period"]     = period?.DeepClone() ?? new JObject(),
                ["historical_data_fingerprint"] = new JObject
                {
                    ["method"] = "placeholder",
                    ["value"]  = "sha256:placeholder",
                    ["files"]  = new JArray()
                },
                ["execution"]  = execution?.DeepClone() ?? new JObject()
            };

            string runHash = RunHashCalculator.Compute(context, AddOnVersion,
                CustomDllSha256, SourceFileSha256);

            var result = new JObject
            {
                ["schema_version"]   = "0.1",
                ["job_id"]           = jobId,
                ["run_hash"]         = runHash,
                ["started_at_utc"]   = StartedAtUtc.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                ["finished_at_utc"]  = finished.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                ["duration_ms"]      = duration,
                ["source"] = new JObject
                {
                    ["execution_source"]              = "ninjatrader",
                    ["ninjatrader_version"]           = NinjaTraderVersion ?? "unknown",
                    ["addon_version"]                 = AddOnVersion,
                    ["rd_variant_used"]               = RdVariantUsed,
                    ["ninjatrader_custom_dll_sha256"] = CustomDllSha256 ?? "sha256:placeholder"
                },
                ["strategy_version"] = new JObject
                {
                    ["source_file_sha256"]   = SourceFileSha256 ?? "sha256:placeholder",
                    ["source_file_mtime_utc"] = SourceFileMtimeUtc.HasValue
                        ? SourceFileMtimeUtc.Value.ToString("yyyy-MM-ddTHH:mm:ssZ")
                        : null
                },
                ["context"] = context,
                ["metrics"] = metrics ?? new JObject(),
                ["trades"]  = trades  ?? new JArray(),
                ["artifacts"] = new JObject
                {
                    ["trades_file"]          = "trades.json",
                    ["bars_file"]            = JValue.CreateNull(),
                    ["equity_curve_file"]    = JValue.CreateNull(),
                    ["drawdown_curve_file"]  = JValue.CreateNull(),
                    ["logs_file"]            = "ninjascript.log",
                    ["raw_bridge_result_file"] = "raw.json"
                },
                ["verification_warnings"] = new JArray(
                    (verificationWarnings ?? Enumerable.Empty<string>()).Select(s => (JToken)s).ToArray())
            };

            return result;
        }

        /// <summary>
        /// Best-effort discovery of the .cs source file for a strategy class
        /// inside %USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\Strategies\.
        /// Used for source_file_sha256 / mtime / resolved_source_file.
        /// Returns null if not found.
        /// </summary>
        public static string FindSourceFile(string ninjaTraderUserDir, string className)
        {
            if (string.IsNullOrWhiteSpace(ninjaTraderUserDir) || string.IsNullOrWhiteSpace(className))
                return null;
            string root = Path.Combine(ninjaTraderUserDir, "bin", "Custom", "Strategies");
            if (!Directory.Exists(root)) return null;
            try
            {
                // NinjaTrader sample strategies are prefixed with '@' on disk
                // (e.g. @SampleMACrossOver.cs) — match either form.
                var candidates = new[]
                {
                    className + ".cs",
                    "@" + className + ".cs"
                };
                foreach (var name in candidates)
                {
                    var hit = Directory.EnumerateFiles(root, name, SearchOption.AllDirectories)
                                       .FirstOrDefault();
                    if (hit != null) return hit;
                }
            }
            catch { }
            return null;
        }
    }
}
