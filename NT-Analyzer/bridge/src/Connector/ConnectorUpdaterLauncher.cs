using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Connector
{
    /// <summary>
    /// Starts the external updater.  This AddOn never replaces its own loaded
    /// assembly and never closes NinjaTrader; the updater waits for a safe
    /// process exit and applies only a separately verified release.
    /// </summary>
    internal static class ConnectorUpdaterLauncher
    {
        private static readonly object Sync = new object();
        private static Process _process;

        public static void TryStart(BridgeConfig cfg)
        {
            if (cfg == null || !cfg.IsProductionConnector || cfg.ProductionConnector == null)
                return;
            string stateDir = Path.GetFullPath(Environment.ExpandEnvironmentVariables(
                cfg.ProductionConnector.StateDir));
            string pending = Path.Combine(stateDir, "pending-update.json");
            bool automatic = string.Equals(
                cfg.ProductionConnector.UpdatePolicy, "safe_restart", StringComparison.Ordinal);
            if (!automatic && !File.Exists(pending)) return;
            try
            {
                JObject record = ReadObject(Path.Combine(stateDir, "install-record.json"));
                string cache = Path.GetFullPath((string)record?["release_cache_dir"] ?? "");
                string prefix = stateDir.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                if (!cache.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("release cache is outside Connector state");
                string updater = Path.Combine(cache, "StratForge.Connector.Updater.exe");
                if (!File.Exists(updater))
                {
                    BridgeLog.Warn("Connector updater is absent from the verified release cache");
                    return;
                }
                lock (Sync)
                {
                    if (_process != null)
                    {
                        if (!_process.HasExited) return;
                        _process.Dispose();
                        _process = null;
                    }
                    ProcessStartInfo start = new ProcessStartInfo
                    {
                        FileName = updater,
                        Arguments = JoinArguments(new[]
                        {
                            "--run", "--ninja-user-dir", cfg.NinjaTraderUserDir,
                            "--state-root", stateDir, "--wait-for-safe-restart",
                            "--non-interactive",
                        }),
                        WorkingDirectory = cache,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden,
                    };
                    _process = Process.Start(start);
                }
            }
            catch (Exception exc)
            {
                BridgeLog.Warn("Connector updater launch failed: " + exc.GetType().Name);
            }
        }

        public static void StoreOffer(string stateDir, JObject offer)
        {
            try
            {
                string root = Path.GetFullPath(Environment.ExpandEnvironmentVariables(stateDir));
                Directory.CreateDirectory(root);
                string path = Path.Combine(root, "update-offer.json");
                if (offer == null || !offer.HasValues)
                {
                    if (File.Exists(path)) File.Delete(path);
                    return;
                }
                // The server response is already authenticated by the Connector
                // session.  Persist only the explicit public release contract.
                string[] allowed =
                {
                    "schema_version", "version", "channel", "archive_url",
                    "archive_sha256", "manifest_sha256", "protocol_version",
                    "apply_policy", "major_approved", "health_timeout_sec",
                    "published_at_utc",
                };
                JObject clean = new JObject();
                foreach (string name in allowed)
                    if (offer[name] != null) clean[name] = offer[name].DeepClone();
                AtomicWrite(path, clean);
            }
            catch (Exception exc)
            {
                BridgeLog.Warn("Connector update offer persistence failed: " + exc.GetType().Name);
            }
        }

        public static void RecordHealth(
            string stateDir, string version, string updateState, string updateReason,
            string installationId)
        {
            try
            {
                string root = Path.GetFullPath(Environment.ExpandEnvironmentVariables(stateDir));
                JObject pending = ReadObject(Path.Combine(root, "pending-update.json"));
                if (pending == null || !string.Equals(
                    (string)pending["target_version"], version, StringComparison.Ordinal))
                    return;
                bool accepted = !string.Equals(updateState, "blocked", StringComparison.Ordinal);
                AtomicWrite(Path.Combine(root, "update-health.json"), new JObject
                {
                    ["schema_version"] = 1,
                    ["version"] = version,
                    ["health_nonce"] = (string)pending["health_nonce"] ?? "",
                    ["accepted"] = accepted,
                    ["reason"] = accepted ? "server_hello_and_heartbeat_accepted" :
                        (updateReason ?? "release_policy_blocked"),
                    ["installation_id"] = installationId ?? "",
                    ["heartbeat_at_utc"] = DateTime.UtcNow.ToString("o"),
                });
            }
            catch (Exception exc)
            {
                BridgeLog.Warn("Connector post-update health receipt failed: " + exc.GetType().Name);
            }
        }

        private static JObject ReadObject(string path)
        {
            return File.Exists(path)
                ? JObject.Parse(File.ReadAllText(path, Encoding.UTF8)) : null;
        }

        private static void AtomicWrite(string path, JObject value)
        {
            string temporary = path + ".tmp-" + Guid.NewGuid().ToString("N");
            File.WriteAllText(temporary, value.ToString(Formatting.Indented),
                new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temporary, path, null);
            else File.Move(temporary, path);
        }

        private static string JoinArguments(string[] values)
        {
            return string.Join(" ", values.Select(value => "\"" +
                (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"") + "\""));
        }
    }
}
