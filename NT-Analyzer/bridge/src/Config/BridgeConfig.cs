using System;
using System.IO;
using Newtonsoft.Json;

namespace NTAnalyzerBridge.Config
{
    /// <summary>
    /// Strongly-typed bridge configuration loaded from
    /// %USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.config.json
    /// (lives next to the deployed NTAnalyzerBridge.dll, per NinjaTrader's
    /// Visual Studio AddOn workflow). Schema mirrors
    /// NTAnalyzerBridge.config.example.json in repo.
    /// </summary>
    internal sealed class BridgeConfig
    {
        [JsonProperty("project_root")]
        public string ProjectRoot { get; set; }

        [JsonProperty("ninjatrader_user_dir")]
        public string NinjaTraderUserDir { get; set; }

        [JsonProperty("jobs_dir")]
        public string JobsDirOverride { get; set; }

        [JsonProperty("poll_interval_ms")]
        public int PollIntervalMs { get; set; } = 1500;

        [JsonProperty("heartbeat_interval_ms")]
        public int HeartbeatIntervalMs { get; set; } = 5000;

        [JsonProperty("heartbeat_ttl_ms")]
        public int HeartbeatTtlMs { get; set; } = 60000;

        [JsonProperty("rd_variant_preferred")]
        public string RdVariantPreferred { get; set; } = "1_strategy_analyzer";

        [JsonProperty("rd_variant_fallback_allowed")]
        public bool RdVariantFallbackAllowed { get; set; } = false;

        [JsonProperty("runtime_reconnect_connection_name")]
        public string RuntimeReconnectConnectionName { get; set; } = "";

        /// <summary>
        /// R&amp;D toggle for the private static
        /// NinjaTrader.NinjaScript.Optimizers.Optimizer.RunBacktest(template, Parameter[])
        /// path (a.k.a. PathA). PathA2
        /// (public StrategyBase.RunBacktest()) is ALWAYS attempted first and
        /// is the verified working path on NT 8.1.6.3. PathA is attempted
        /// ONLY when this flag is true AND PathA2 produced no result — in
        /// 8.1.6.3 it reliably throws NullReferenceException because the
        /// optimizer expects context that isn't set up outside Strategy
        /// Analyzer. Default = false. Set to true only when
        /// investigating Optimizer internals.
        /// </summary>
        [JsonProperty("enable_path_a_optimizer_runbacktest")]
        public bool EnablePathAOptimizerRunBacktest { get; set; } = false;

        /// <summary>
        /// When true, the bridge appends verbose diagnostic dumps to
        /// result.json/verification_warnings: full StrategyBase date/range
        /// reflection (DumpDateRangeProperties) and the raw
        /// TradesPerformance metrics_shape probe. Useful when investigating
        /// "why is metric X missing / wrong", but for normal use it adds
        /// ~200 lines of noise per job. Default = false.
        /// </summary>
        [JsonProperty("enable_verbose_diagnostics")]
        public bool EnableVerboseDiagnostics { get; set; } = false;

        public static string DefaultConfigPath()
        {
            // The DLL is deployed to <NinjaTraderUserDir>\bin\Custom\NTAnalyzerBridge.dll
            // (per NinjaTrader's Visual Studio AddOn workflow).
            // Config file lives next to it as NTAnalyzerBridge.config.json.
            string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(userProfile,
                "Documents", "NinjaTrader 8", "bin", "Custom",
                "NTAnalyzerBridge.config.json");
        }

        public static BridgeConfig LoadOrNull(string path, out string error)
        {
            error = null;
            try
            {
                if (!File.Exists(path))
                {
                    error = "config file not found: " + path;
                    return null;
                }
                string json = File.ReadAllText(path);
                var cfg = JsonConvert.DeserializeObject<BridgeConfig>(json);
                if (cfg == null)
                {
                    error = "config file is empty or invalid JSON: " + path;
                    return null;
                }
                if (string.IsNullOrWhiteSpace(cfg.ProjectRoot))
                {
                    error = "config: 'project_root' is required";
                    return null;
                }
                if (!Directory.Exists(cfg.ProjectRoot))
                {
                    error = "config: 'project_root' does not exist: " + cfg.ProjectRoot;
                    return null;
                }
                if (string.IsNullOrWhiteSpace(cfg.NinjaTraderUserDir))
                {
                    error = "config: 'ninjatrader_user_dir' is required";
                    return null;
                }
                return cfg;
            }
            catch (Exception ex)
            {
                error = "failed to read config: " + ex.Message;
                return null;
            }
        }

        private string ResolveProjectPath(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
                return null;
            return Path.IsPathRooted(path) ? path : Path.Combine(ProjectRoot, path);
        }

        // Convenience accessors for queue layout.
        public string JobsDir       => ResolveProjectPath(JobsDirOverride) ?? Path.Combine(ProjectRoot, "jobs");
        public string PendingDir    => Path.Combine(JobsDir, "pending");
        public string PendingStaging=> Path.Combine(PendingDir, ".staging");
        public string RunningDir    => Path.Combine(JobsDir, "running");
        public string DoneDir       => Path.Combine(JobsDir, "done");
        public string FailedDir     => Path.Combine(JobsDir, "failed");
        public string CancelledDir  => Path.Combine(JobsDir, "cancelled");
    }
}
