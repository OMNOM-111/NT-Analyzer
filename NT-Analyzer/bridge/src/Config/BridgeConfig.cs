using System;
using System.IO;
using Newtonsoft.Json;

namespace NTAnalyzerBridge.Config
{
    internal sealed class ProductionConnectorConfig
    {
        [JsonProperty("enabled")]
        public bool Enabled { get; set; } = true;

        [JsonProperty("server_origin")]
        public string ServerOrigin { get; set; } = "https://app.stratforges.com";

        [JsonProperty("protocol_version")]
        public string ProtocolVersion { get; set; } = "1.0";

        [JsonProperty("connector_version")]
        public string ConnectorVersion { get; set; } = "0.2.0";

        [JsonProperty("enrollment_code")]
        public string EnrollmentCode { get; set; } = "";

        [JsonProperty("state_dir")]
        public string StateDir { get; set; } = "";

        [JsonProperty("heartbeat_interval_ms")]
        public int HeartbeatIntervalMs { get; set; } = 15000;

        [JsonProperty("command_poll_seconds")]
        public int CommandPollSeconds { get; set; } = 15;
    }

    /// <summary>
    /// Strongly-typed bridge configuration loaded from
    /// %USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.config.json
    /// (lives next to the deployed NTAnalyzerBridge.dll, per NinjaTrader's
    /// Visual Studio AddOn workflow). Schema mirrors
    /// NTAnalyzerBridge.config.example.json in repo.
    /// </summary>
    internal sealed class BridgeConfig
    {
        [JsonProperty("schema_version")]
        public int SchemaVersion { get; set; } = 1;

        [JsonProperty("mode")]
        public string Mode { get; set; } = "local_development";

        [JsonProperty("project_root")]
        public string ProjectRoot { get; set; }

        [JsonProperty("ninjatrader_user_dir")]
        public string NinjaTraderUserDir { get; set; }

        [JsonProperty("jobs_dir")]
        public string JobsDirOverride { get; set; }

        [JsonProperty("runtime_data_dir")]
        public string RuntimeDataDirOverride { get; set; }

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

        [JsonProperty("production_connector")]
        public ProductionConnectorConfig ProductionConnector { get; set; }

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

        public static string DefaultNinjaTraderUserDir()
        {
            string documents = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            return Path.Combine(documents, "NinjaTrader 8");
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
                if (string.IsNullOrWhiteSpace(cfg.NinjaTraderUserDir))
                {
                    cfg.NinjaTraderUserDir = DefaultNinjaTraderUserDir();
                }
                if (cfg.IsProductionConnector)
                {
                    if (cfg.ProductionConnector == null || !cfg.ProductionConnector.Enabled)
                    {
                        error = "config: production_connector must be enabled";
                        return null;
                    }
                    if (!string.Equals(cfg.ProductionConnector.ProtocolVersion, "1.0", StringComparison.Ordinal))
                    {
                        error = "config: unsupported production_connector.protocol_version";
                        return null;
                    }
                    Uri endpoint;
                    if (!Uri.TryCreate(cfg.ProductionConnector.ServerOrigin, UriKind.Absolute, out endpoint) ||
                        !string.Equals(endpoint.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase) ||
                        endpoint.PathAndQuery != "/" || !string.IsNullOrEmpty(endpoint.UserInfo))
                    {
                        error = "config: production_connector.server_origin must be an HTTPS origin without path or credentials";
                        return null;
                    }
                    cfg.ProductionConnector.ServerOrigin = endpoint.GetLeftPart(UriPartial.Authority);
                    if (string.IsNullOrWhiteSpace(cfg.ProductionConnector.StateDir))
                    {
                        cfg.ProductionConnector.StateDir = Path.Combine(
                            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                            "StratForge", "Connector");
                    }
                    if (cfg.ProductionConnector.HeartbeatIntervalMs < 5000 ||
                        cfg.ProductionConnector.HeartbeatIntervalMs > 60000)
                    {
                        error = "config: production_connector.heartbeat_interval_ms must be 5000..60000";
                        return null;
                    }
                    if (cfg.ProductionConnector.CommandPollSeconds < 1 ||
                        cfg.ProductionConnector.CommandPollSeconds > 20)
                    {
                        error = "config: production_connector.command_poll_seconds must be 1..20";
                        return null;
                    }
                }
                else
                {
                    if (!string.Equals(cfg.Mode, "local_development", StringComparison.Ordinal))
                    {
                        error = "config: mode must be local_development or production_connector";
                        return null;
                    }
                    if (string.IsNullOrWhiteSpace(cfg.ProjectRoot))
                    {
                        error = "config: 'project_root' is required in local_development mode";
                        return null;
                    }
                    if (!Directory.Exists(cfg.ProjectRoot))
                    {
                        error = "config: 'project_root' does not exist: " + cfg.ProjectRoot;
                        return null;
                    }
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
            if (Path.IsPathRooted(path)) return path;
            return string.IsNullOrWhiteSpace(ProjectRoot) ? null : Path.Combine(ProjectRoot, path);
        }

        public bool IsProductionConnector =>
            string.Equals(Mode, "production_connector", StringComparison.Ordinal);

        // Convenience accessors for queue layout.
        public string JobsDir       => ResolveProjectPath(JobsDirOverride) ?? Path.Combine(ProjectRoot, "jobs");
        public string RuntimeDataDir
        {
            get
            {
                string configured = ResolveProjectPath(RuntimeDataDirOverride);
                if (!string.IsNullOrWhiteSpace(configured)) return configured;
                if (IsProductionConnector && ProductionConnector != null)
                    return Path.Combine(ProductionConnector.StateDir, "spool");
                return Path.Combine(ProjectRoot, "data", "runtime");
            }
        }
        public string PendingDir    => Path.Combine(JobsDir, "pending");
        public string PendingStaging=> Path.Combine(PendingDir, ".staging");
        public string RunningDir    => Path.Combine(JobsDir, "running");
        public string DoneDir       => Path.Combine(JobsDir, "done");
        public string FailedDir     => Path.Combine(JobsDir, "failed");
        public string CancelledDir  => Path.Combine(JobsDir, "cancelled");
    }
}
