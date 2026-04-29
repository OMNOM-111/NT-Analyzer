using System;
using NinjaTrader.NinjaScript;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Execution;
using NTAnalyzerBridge.JobQueue;
using NTAnalyzerBridge.Reporting;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge
{
    /// <summary>
    /// AddOn entry point. Loaded by NinjaTrader 8 from
    /// %USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\
    /// (per the official NT8 Visual Studio AddOn workflow).
    ///
    /// Responsibilities:
    ///   - load NTAnalyzerBridge.config.json;
    ///   - build reflection whitelist from NinjaTrader.Custom.dll;
    ///   - sanity-check that SampleMACrossOver is present;
    ///   - start the file-queue watcher driving the state machine;
    ///   - delegate each claimed job to StrategyAnalyzerRunner (Variant 1);
    ///   - shut everything down cleanly on NinjaTrader exit.
    /// </summary>
    public sealed class BridgeAddOn : AddOnBase
    {
        private BridgeConfig _cfg;
        private StrategyLoader _strategyLoader;
        private JobQueueWatcher _watcher;
        private CatalogRefresher _catalogRefresher;

        protected override void OnStateChange()
        {
            if (State == NinjaTrader.NinjaScript.State.SetDefaults)
            {
                Name        = "NTAnalyzerBridge";
                Description = "NT-Analyzer file-queue bridge (Variant 1 Strategy Analyzer)";
            }
            else if (State == NinjaTrader.NinjaScript.State.Configure)
            {
                StartBridge();
            }
            else if (State == NinjaTrader.NinjaScript.State.Terminated)
            {
                StopBridge();
            }
        }

        private void StartBridge()
        {
            try
            {
                string configPath = BridgeConfig.DefaultConfigPath();
                _cfg = BridgeConfig.LoadOrNull(configPath, out string err);
                if (_cfg == null)
                {
                    // No config -> AddOn loads but stays idle. The user must
                    // copy NTAnalyzerBridge.config.example.json before runs.
                    BridgeLog.Configure(null);
                    BridgeLog.Warn("NTAnalyzerBridge: " + err + " — watcher NOT started");
                    return;
                }

                BridgeLog.Configure(_cfg.NinjaTraderUserDir);
                BridgeLog.Info("config loaded from " + configPath);
                BridgeLog.Info("project_root=" + _cfg.ProjectRoot);

                _strategyLoader = new StrategyLoader(_cfg.NinjaTraderUserDir);
                _strategyLoader.Refresh();

                var whitelist = _strategyLoader.WhitelistedClassNames();
                BridgeLog.Info("whitelisted strategies: " + whitelist.Count);
                if (_strategyLoader.Resolve("SampleMACrossOver") == null)
                {
                    BridgeLog.Warn(
                        "SampleMACrossOver not found in whitelist — open NinjaTrader " +
                        "NinjaScript editor and compile @SampleMACrossOver.cs first");
                }
                else
                {
                    BridgeLog.Info("SampleMACrossOver found in whitelist");
                }

                // Dump strategy + instrument catalog so the UI can populate
                // dropdowns from real data instead of hardcoded values.
                try
                {
                    CatalogWriter.WriteAll(_cfg.ProjectRoot, _cfg.NinjaTraderUserDir,
                        _strategyLoader.WhitelistedTypes());
                }
                catch (Exception cwex)
                {
                    BridgeLog.Error("CatalogWriter call failed", cwex);
                }

                _watcher = new JobQueueWatcher(_cfg, _strategyLoader,
                    new StrategyAnalyzerRunner(_strategyLoader, _cfg));
                _watcher.Start();

                // Auto-refresh catalog when NinjaTrader.Custom.dll is recompiled
                // and serve manual refresh requests from the UI.
                _catalogRefresher = new CatalogRefresher(_cfg, _strategyLoader);
                _catalogRefresher.Start();
            }
            catch (Exception ex)
            {
                BridgeLog.Error("StartBridge failed", ex);
            }
        }

        private void StopBridge()
        {
            try { _catalogRefresher?.Stop(); }
            catch (Exception ex) { BridgeLog.Error("StopBridge: refresher.Stop failed", ex); }
            finally { _catalogRefresher = null; }

            try { _watcher?.Stop(); }
            catch (Exception ex) { BridgeLog.Error("StopBridge: watcher.Stop failed", ex); }
            finally { _watcher = null; }
        }
    }
}
