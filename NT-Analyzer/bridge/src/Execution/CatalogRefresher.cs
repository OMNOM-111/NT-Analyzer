using System;
using System.IO;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Reporting;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Execution
{
    /// <summary>
    /// Periodically rebuilds the strategy / instrument / template catalog
    /// without requiring a NinjaTrader restart.
    ///
    /// Two triggers:
    ///   1. AUTO: NinjaTrader.Custom.dll LastWriteTime increased (the user
    ///      hit Compile in NinjaScript Editor), so the in-memory whitelist
    ///      is now out of date.
    ///   2. MANUAL: a sentinel file at
    ///      &lt;project_root&gt;\data\commands\refresh_catalog.request
    ///      appears (UI button -&gt; backend writes it). The bridge picks
    ///      it up, refreshes, deletes the request and writes
    ///      refresh_catalog.response with the result.
    ///
    /// Single-threaded re-entrancy guard. Failures are logged, never thrown.
    /// </summary>
    internal sealed class CatalogRefresher
    {
        private readonly BridgeConfig _cfg;
        private readonly StrategyLoader _loader;
        private readonly string _customDllPath;
        private readonly string _commandsDir;
        private readonly string _requestFile;
        private readonly string _responseFile;
        private readonly System.Threading.Timer _timer;
        private readonly object _gate = new object();
        private DateTime _lastDllMtimeUtc = DateTime.MinValue;
        private bool _busy;
        private bool _stopped;

        public CatalogRefresher(BridgeConfig cfg, StrategyLoader loader)
        {
            _cfg = cfg ?? throw new ArgumentNullException(nameof(cfg));
            _loader = loader ?? throw new ArgumentNullException(nameof(loader));
            _customDllPath = Path.Combine(cfg.NinjaTraderUserDir, "bin", "Custom",
                                          "NinjaTrader.Custom.dll");
            _commandsDir   = Path.Combine(cfg.ProjectRoot, "data", "commands");
            _requestFile   = Path.Combine(_commandsDir, "refresh_catalog.request");
            _responseFile  = Path.Combine(_commandsDir, "refresh_catalog.response");
            _timer = new System.Threading.Timer(_ => Tick(), null,
                                                Timeout.Infinite, Timeout.Infinite);
        }

        public void Start()
        {
            try { Directory.CreateDirectory(_commandsDir); }
            catch (Exception ex) { BridgeLog.Error("CatalogRefresher: cannot create " + _commandsDir, ex); }

            // Seed the baseline so the first tick doesn't trigger a redundant
            // refresh just because we have never recorded the DLL mtime.
            _lastDllMtimeUtc = SafeGetDllMtimeUtc();

            int interval = Math.Max(500, _cfg.PollIntervalMs);
            _timer.Change(interval, interval);
            BridgeLog.Info("CatalogRefresher started (poll=" + interval + "ms, dll=" + _customDllPath + ")");
        }

        public void Stop()
        {
            _stopped = true;
            try { _timer.Change(Timeout.Infinite, Timeout.Infinite); } catch { }
            try { _timer.Dispose(); } catch { }
        }

        private void Tick()
        {
            if (_stopped) return;
            lock (_gate)
            {
                if (_busy) return;
                _busy = true;
            }
            try
            {
                CheckAutoTrigger();
                CheckManualTrigger();
            }
            catch (Exception ex)
            {
                BridgeLog.Error("CatalogRefresher tick failed", ex);
            }
            finally
            {
                lock (_gate) { _busy = false; }
            }
        }

        private void CheckAutoTrigger()
        {
            DateTime current = SafeGetDllMtimeUtc();
            if (current == DateTime.MinValue) return;
            if (current <= _lastDllMtimeUtc) return;
            DateTime previous = _lastDllMtimeUtc;
            _lastDllMtimeUtc = current;
            BridgeLog.Info("NinjaTrader.Custom.dll changed (" +
                           previous.ToString("o") + " -> " + current.ToString("o") +
                           "), refreshing catalog");
            DoRefresh("dll_changed");
        }

        private void CheckManualTrigger()
        {
            if (!File.Exists(_requestFile)) return;
            BridgeLog.Info("CatalogRefresher: manual refresh request received");
            string requestId = SafeReadRequestId();
            var result = DoRefresh("manual_request");
            try
            {
                var resp = new JObject
                {
                    ["schema_version"]   = "0.1",
                    ["request_id"]       = requestId,
                    ["responded_at_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                    ["ok"]               = result.Ok,
                    ["error"]            = result.Error ?? string.Empty,
                    ["strategies_count"] = result.StrategiesCount,
                    ["trigger"]          = "manual_request",
                };
                AtomicFile.WriteAllText(_responseFile, resp.ToString(Formatting.Indented));
            }
            catch (Exception ex)
            {
                BridgeLog.Error("CatalogRefresher: cannot write response", ex);
            }
            try { File.Delete(_requestFile); }
            catch (Exception ex) { BridgeLog.Warn("CatalogRefresher: cannot delete request: " + ex.Message); }
        }

        private RefreshResult DoRefresh(string trigger)
        {
            try
            {
                _loader.Refresh();
                CatalogWriter.WriteAll(_cfg.ProjectRoot, _cfg.NinjaTraderUserDir,
                                       _loader.WhitelistedTypes());
                int n = _loader.WhitelistedClassNames().Count;
                BridgeLog.Info("Catalog refreshed (" + trigger + "), strategies=" + n);
                return new RefreshResult { Ok = true, StrategiesCount = n };
            }
            catch (Exception ex)
            {
                BridgeLog.Error("Catalog refresh failed (" + trigger + ")", ex);
                return new RefreshResult { Ok = false, Error = ex.Message };
            }
        }

        private DateTime SafeGetDllMtimeUtc()
        {
            try
            {
                if (!File.Exists(_customDllPath)) return DateTime.MinValue;
                return File.GetLastWriteTimeUtc(_customDllPath);
            }
            catch { return DateTime.MinValue; }
        }

        private string SafeReadRequestId()
        {
            try
            {
                string txt = File.ReadAllText(_requestFile);
                if (string.IsNullOrWhiteSpace(txt)) return "";
                var jo = JObject.Parse(txt);
                return (string)jo["request_id"] ?? "";
            }
            catch { return ""; }
        }

        private struct RefreshResult
        {
            public bool   Ok;
            public string Error;
            public int    StrategiesCount;
        }
    }
}
