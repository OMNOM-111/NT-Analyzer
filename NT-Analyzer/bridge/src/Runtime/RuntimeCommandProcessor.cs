using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;

using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Runtime
{
    /// <summary>
    /// Phase 18 - Runtime command processor.
    ///
    /// Polls data/runtime/commands.jsonl, executes enable/disable
    /// of NinjaScript Strategy instances or safe paper/demo/playback
    /// connection reconnects, and appends a result to
    /// data/runtime/command_results.jsonl.
    ///
    /// Hard safety:
    ///   * unknown account names are rejected (no defaulting to live);
    ///   * live account control is rejected; live telemetry is read-only;
    ///   * archived/rejected strategy classes cannot be launched;
    ///   * we never place orders, never modify orders, never bypass NinjaScript
    ///     state machine. We only call Strategy.SetState(State.Active|Terminated)
    ///     on existing instances enumerated from Account.Strategies.
    ///   * if no Strategy instance exists on the chosen account we report
    ///     status="failed" with a human message - operator must add the strategy
    ///     instance via NinjaTrader UI first.
    ///
    /// Processed command_ids are remembered in-memory and persisted by reading
    /// existing command_results.jsonl on startup so a process restart never
    /// re-runs a finished command.
    /// </summary>
    internal sealed class RuntimeCommandProcessor
    {
        public const string ProcessorVersion = "1.0.0";
        private const int   PollIntervalMs   = 1500;

        private readonly BridgeConfig _cfg;
        private readonly string _runtimeDir;
        private readonly string _commandsPath;
        private readonly string _resultsPath;
        private readonly Timer  _timer;
        private readonly HashSet<string> _seen = new HashSet<string>(StringComparer.Ordinal);
        private readonly object _lock = new object();
        private int _running;

        // Classes the bridge must refuse for enable_strategy, per Phase 18 spec.
        private static readonly HashSet<string> RejectedClasses = new HashSet<string>(StringComparer.Ordinal)
        {
            "NTAMicroOrbPilot",
            "NTAMicroVwapGapMirrorPilot",
            "NTAMicroVwapMeanRevertPilot",
            "NTAMnqLiquiditySweepReversalC015",
            "NTAMnqOpenDriveShortScalpC016",
            "NTAMnqLateVwapLongScalpC017",
        };

        // B1 ShortOnly locked params - must match exactly when the operator
        // queues a launch for this class. Mismatch => reject.
        private static readonly Dictionary<string, double> B1Locked = new Dictionary<string, double>
        {
            { "EnableLong",          0    }, // false
            { "EnableShort",         1    }, // true
            { "TradeStartTime",      635  },
            { "TradeEndTime",        700  },
            { "MinStopTicks",        12   },
            { "MaxStopTicks",        12   },
            { "RewardRiskRatio",     3.5  },
            { "RiskPerTradePct",     2.0  },
            { "UserMaxContracts",    5    },
            { "RoundTurnCommission", 1.90 },
            { "SlippageTicks",       1    },
        };

        public RuntimeCommandProcessor(BridgeConfig cfg)
        {
            _cfg = cfg ?? throw new ArgumentNullException(nameof(cfg));
            if (string.IsNullOrEmpty(cfg.ProjectRoot))
                throw new ArgumentNullException(nameof(cfg.ProjectRoot));
            _runtimeDir   = cfg.RuntimeDataDir;
            _commandsPath = Path.Combine(_runtimeDir, "commands.jsonl");
            _resultsPath  = Path.Combine(_runtimeDir, "command_results.jsonl");
            Directory.CreateDirectory(_runtimeDir);
            _timer = new Timer(OnTick, null, Timeout.Infinite, Timeout.Infinite);
        }

        public void Start()
        {
            BridgeLog.Info("RuntimeCommandProcessor: start runtime_dir=" + _runtimeDir);
            // Seed seen set from any existing results so we never re-execute.
            try
            {
                if (File.Exists(_resultsPath))
                {
                    foreach (var line in File.ReadAllLines(_resultsPath, Encoding.UTF8))
                    {
                        string id = ExtractJsonString(line, "command_id");
                        if (!string.IsNullOrEmpty(id)) _seen.Add(id);
                    }
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("RuntimeCommandProcessor: seed seen-set failed: " + ex.Message);
            }
            _timer.Change(0, PollIntervalMs);
        }

        public void Stop()
        {
            try { _timer.Change(Timeout.Infinite, Timeout.Infinite); } catch { }
            try { _timer.Dispose(); } catch { }
            BridgeLog.Info("RuntimeCommandProcessor: stopped");
        }

        // ------------------------------------------------------------------

        private void OnTick(object _)
        {
            if (Interlocked.CompareExchange(ref _running, 1, 0) != 0) return;
            try
            {
                if (!File.Exists(_commandsPath)) return;
                List<string> lines;
                try { lines = File.ReadAllLines(_commandsPath, Encoding.UTF8).ToList(); }
                catch { return; }

                foreach (var raw in lines)
                {
                    if (string.IsNullOrWhiteSpace(raw)) continue;
                    string cid = ExtractJsonString(raw, "command_id");
                    if (string.IsNullOrEmpty(cid)) continue;
                    lock (_lock) { if (_seen.Contains(cid)) continue; }
                    bool resultWritten = ProcessOne(raw, cid);
                    if (resultWritten)
                    {
                        lock (_lock) { _seen.Add(cid); }
                    }
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Error("RuntimeCommandProcessor.OnTick", ex);
            }
            finally { _running = 0; }
        }

        private bool ProcessOne(string rawJson, string cid)
        {
            string command           = ExtractJsonString(rawJson, "command");
            string strategyClass     = ExtractJsonString(rawJson, "strategy_class");
            string accountName       = ExtractJsonString(rawJson, "account_name");
            string instrument        = ExtractJsonString(rawJson, "instrument");
            string runtimeInstanceId = ExtractJsonString(rawJson, "runtime_instance_id");
            string connectionName    = ExtractJsonString(rawJson, "connection_name");

            try
            {
                if (command != "enable_strategy" &&
                    command != "disable_strategy" &&
                    command != "reconnect_account")
                {
                    return WriteResult(cid, "rejected", "unknown command: " + command, "");
                }

                // Resolve account.
                Account acc = FindAccount(accountName);
                if (acc == null)
                {
                    return WriteResult(cid, "failed", "account not found: " + accountName, "");
                }
                string accMode = ClassifyAccountMode(accountName, acc);
                if (accMode == "unknown")
                {
                    return WriteResult(cid, "rejected",
                        "account '" + accountName + "' could not be classified - refusing for safety", "");
                }
                if (accMode == "live")
                {
                    return WriteResult(cid, "rejected",
                        "live account control is disabled; telemetry is read-only", "");
                }

                if (command == "reconnect_account")
                {
                    if (IsSystemAccountName(accountName))
                    {
                        return WriteResult(cid, "rejected",
                            "system account '" + accountName + "' cannot be reconnected", "");
                    }
                    string reconnectMessage;
                    string reconnectStatus;
                    ReconnectAccountConnection(
                        acc, accountName, connectionName, out reconnectStatus, out reconnectMessage);
                    return WriteResult(cid, reconnectStatus, reconnectMessage, "");
                }

                if (string.IsNullOrEmpty(strategyClass))
                {
                    return WriteResult(cid, "rejected", "strategy_class is required", "");
                }
                if (command == "enable_strategy" && RejectedClasses.Contains(strategyClass))
                {
                    return WriteResult(cid, "rejected",
                        "strategy class '" + strategyClass + "' is archived/rejected by registry - launch refused",
                        "");
                }

                // Find existing strategy instance on this account (we never create
                // new ones from an AddOn - that requires the Strategies window UI).
                object strat = FindStrategy(acc, strategyClass, instrument, accountName, runtimeInstanceId);
                if (strat == null)
                {
                    string detail = string.IsNullOrEmpty(runtimeInstanceId)
                        ? "no '" + strategyClass + "' instance found on account '" + accountName + "'."
                        : "no instance with runtime_instance_id='" + runtimeInstanceId +
                          "' (class '" + strategyClass + "') found on account '" + accountName +
                          "'. Telemetry may be stale, refresh and retry.";
                    return WriteResult(cid, "failed",
                        detail + " Add it once via NinjaTrader Strategies window, " +
                        "then re-issue the command.",
                        "");
                }

                if (command == "enable_strategy")
                {
                    // B1 ShortOnly param check.
                    if (strategyClass == "NTAMicroVwapRiskPilot")
                    {
                        string mismatch = CheckB1Params(strat);
                        if (mismatch != null)
                        {
                            return WriteResult(cid, "rejected",
                                "B1 ShortOnly param mismatch: " + mismatch,
                                SafeStrategyId(strat));
                        }
                    }
                    bool ok = SetStrategyState(strat, true, out string err);
                    if (!ok)
                    {
                        return WriteResult(cid, "failed", "SetState(Active) failed: " + err, SafeStrategyId(strat));
                    }
                    return WriteResult(cid, "completed",
                        "enabled '" + strategyClass + "' on '" + accountName + "'",
                        SafeStrategyId(strat));
                }
                else // disable_strategy
                {
                    bool ok = SetStrategyState(strat, false, out string err);
                    if (!ok)
                    {
                        return WriteResult(cid, "failed", "SetState(Terminated) failed: " + err, SafeStrategyId(strat));
                    }
                    return WriteResult(cid, "completed",
                        "disabled '" + strategyClass + "' on '" + accountName + "'",
                        SafeStrategyId(strat));
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Error("RuntimeCommandProcessor.ProcessOne cid=" + cid, ex);
                try { return WriteResult(cid, "failed", "exception: " + ex.Message, ""); }
                catch { return false; }
            }
        }

        // ------------------------------------------------------------------
        // NinjaTrader interaction

        private static Account FindAccount(string name)
        {
            try
            {
                lock (Account.All)
                {
                    foreach (var a in Account.All)
                    {
                        if (a == null) continue;
                        try { if (a.Name == name) return a; } catch { }
                    }
                }
            }
            catch { }
            return null;
        }

        private static string ClassifyAccountMode(string name, Account acc)
        {
            try
            {
                string provider = SafeStringProp(acc, "Provider");
                if (!string.IsNullOrEmpty(provider))
                {
                    string p = provider.ToLowerInvariant();
                    if (p.Contains("playback")) return "playback";
                    if (p.Contains("simulator") || p.Contains("sim")) return "paper";
                }
            }
            catch { }
            string n = (name ?? "").ToLowerInvariant();
            if (n.Contains("playback")) return "playback";
            if (n.StartsWith("sim") || n.Contains("paper") || n.Contains("demo"))
                return "paper";
            if (string.IsNullOrEmpty(n)) return "unknown";
            return "live";
        }

        private static bool IsSystemAccountName(string accountName)
        {
            string value = (accountName ?? "").Trim();
            return string.Equals(value, "Backtest", StringComparison.OrdinalIgnoreCase) ||
                   string.Equals(value, "Sim101", StringComparison.OrdinalIgnoreCase) ||
                   value.StartsWith("Playback", StringComparison.OrdinalIgnoreCase);
        }

        private static object FindStrategy(Account acc, string className, string instrument,
                                           string accountName, string runtimeInstanceId)
        {
            try
            {
                var prop = acc.GetType().GetProperty("Strategies",
                    BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic);
                if (prop == null) return null;
                var col = prop.GetValue(acc) as System.Collections.IEnumerable;
                if (col == null) return null;
                object best = null;
                lock (col)
                {
                    foreach (var s in col)
                    {
                        if (s == null) continue;
                        if (s.GetType().Name != className) continue;

                        // Skip ghost objects (Finalized/Terminated) — they are
                        // not visible in the Strategies tab and not actionable.
                        string st = SafeStringProp(s, "State") ?? "";
                        if (st.Equals("Finalized", StringComparison.OrdinalIgnoreCase) ||
                            st.Equals("Terminated", StringComparison.OrdinalIgnoreCase))
                            continue;

                        // Exact targeting via runtime_instance_id (preferred):
                        // matches the same hash the telemetry exporter wrote.
                        if (!string.IsNullOrEmpty(runtimeInstanceId))
                        {
                            string sName = SafeStringProp(s, "Name");
                            string sInst = SafeInstrumentFullName(s);
                            string sid = NTAnalyzerBridge.Util.RuntimeInstanceIdUtil
                                .Compute(s, accountName, className, sInst, sName);
                            if (sid == runtimeInstanceId) return s;
                            continue; // when id is provided, only an exact match wins
                        }

                        if (best == null) best = s;
                        if (!string.IsNullOrEmpty(instrument))
                        {
                            string inst = SafeInstrumentFullName(s);
                            if (!string.IsNullOrEmpty(inst) &&
                                inst.IndexOf(instrument, StringComparison.OrdinalIgnoreCase) >= 0)
                            {
                                return s;
                            }
                        }
                    }
                }
                // If id was specified but no match found — return null (don't fall back).
                if (!string.IsNullOrEmpty(runtimeInstanceId)) return null;
                return best;
            }
            catch { return null; }
        }

        private bool ReconnectAccountConnection(Account acc, string accountName,
                                                string requestedConnectionName,
                                                out string status, out string message)
        {
            status = "failed";
            message = "reconnect failed";
            string resolvedName;
            string resolveError;
            object connectOption = ResolveReconnectConnectOption(
                acc, accountName, requestedConnectionName, out resolvedName, out resolveError);
            if (connectOption == null)
            {
                status = "rejected";
                message = resolveError;
                return false;
            }

            if (IsDataFeedConnection(connectOption))
            {
                status = "rejected";
                message = "refusing to reconnect data-feed connection '" + resolvedName +
                          "' for account '" + accountName +
                          "'; account reconnect requires an exact trading connection";
                return false;
            }

            object existingTrading = FindLiveConnection(resolvedName);
            if (existingTrading != null && IsConnectionActive(existingTrading))
            {
                status = "completed";
                message = "connection '" + resolvedName + "' already active on account '" +
                          accountName + "'; reconnect skipped";
                return true;
            }

            string disconnectWarning = "";
            object existing = FindLiveConnection(resolvedName);
            if (existing != null)
            {
                string disconnectErr;
                if (!TryDisconnectConnection(existing, out disconnectErr) &&
                    !string.IsNullOrEmpty(disconnectErr))
                {
                    disconnectWarning = " previous disconnect warning: " + disconnectErr;
                }
                else
                {
                    try { Thread.Sleep(250); } catch { }
                }
            }

            // Never mutate another connection to make this reconnect succeed.
            // In particular, silently disconnecting a data feed can interrupt a
            // user session or Strategy Analyzer. Fail closed and let the owner
            // decide which connection should remain open.
            object blockingDataFeed = FindActiveDataFeedConnection();
            if (blockingDataFeed != null)
            {
                status = "rejected";
                message = "trading connection '" + resolvedName +
                          "' was not opened because data-feed connection '" +
                          SafeConnectionOptionName(SafeGetPropValue(blockingDataFeed, "Options")) +
                          "' is active";
                return false;
            }

            string connectErr;
            string immediateStatus;
            if (!TryConnectOption(connectOption, out connectErr, out immediateStatus))
            {
                status = "failed";
                message = "Connection.Connect failed for '" + resolvedName + "': " + connectErr;
                return false;
            }

            status = "completed";
            message = "reconnect issued for connection '" + resolvedName + "' on account '" +
                      accountName + "'";
            if (!string.IsNullOrEmpty(immediateStatus))
                message += " (immediate status=" + immediateStatus + ")";
            if (!string.IsNullOrEmpty(disconnectWarning))
                message += ";" + disconnectWarning;
            return true;
        }

        private object ResolveReconnectConnectOption(Account acc, string accountName,
                                                     string requestedConnectionName,
                                                     out string resolvedName, out string error)
        {
            resolvedName = "";
            error = "";
            var options = GetConfiguredConnectOptions();
            if (options.Count == 0)
            {
                error = "no configured NinjaTrader connections found";
                return null;
            }

            string accountMode = ClassifyAccountMode(accountName, acc);
            string accountConnectionName = SafeConnectionOptionName(
                SafeGetPropValue(SafeGetPropValue(acc, "Connection"), "Options"));
            string configuredName = _cfg == null ? "" : (_cfg.RuntimeReconnectConnectionName ?? "");
            var namedCandidates = new List<string>();
            if (!string.IsNullOrWhiteSpace(requestedConnectionName))
                namedCandidates.Add(requestedConnectionName);
            if (!string.IsNullOrWhiteSpace(accountConnectionName))
                namedCandidates.Add(accountConnectionName);
            if (!string.IsNullOrWhiteSpace(configuredName) &&
                (accountMode != "playback" ||
                 configuredName.IndexOf("playback", StringComparison.OrdinalIgnoreCase) >= 0))
            {
                namedCandidates.Add(configuredName);
            }

            foreach (string candidate in namedCandidates)
            {
                object exact = FindConfiguredConnectionOption(options, candidate, false);
                if (exact != null && !IsDataFeedConnection(exact))
                {
                    resolvedName = SafeConnectionOptionName(exact);
                    return exact;
                }
            }
            foreach (string candidate in namedCandidates)
            {
                object fuzzy = FindConfiguredConnectionOption(options, candidate, true);
                if (fuzzy != null && !IsDataFeedConnection(fuzzy))
                {
                    resolvedName = SafeConnectionOptionName(fuzzy);
                    return fuzzy;
                }
            }

            var modeMatches = options
                .Where(option => OptionMatchesAccountMode(option, accountMode))
                .ToList();
            if (modeMatches.Count == 1)
            {
                resolvedName = SafeConnectionOptionName(modeMatches[0]);
                return modeMatches[0];
            }
            if (modeMatches.Count > 1)
            {
                object preferred = PreferTradingConnectOption(modeMatches, accountMode);
                if (preferred != null)
                {
                    resolvedName = SafeConnectionOptionName(preferred);
                    return preferred;
                }
                error = "multiple configured connections match account '" + accountName +
                        "': [" + string.Join(", ", modeMatches.Select(SafeConnectionOptionName)) +
                        "]. Set runtime_reconnect_connection_name in NTAnalyzerBridge.config.json.";
                return null;
            }

            error = "no configured connection matched account '" + accountName + "'" +
                    (string.IsNullOrWhiteSpace(configuredName) ? "" :
                     " (configured default '" + configuredName + "')") +
                    ". Available: [" + string.Join(", ", options.Select(SafeConnectionOptionName)) + "]";
            return null;
        }

        private static List<object> GetConfiguredConnectOptions()
        {
            var outList = new List<object>();
            try
            {
                Type globalsType = Type.GetType("NinjaTrader.Core.Globals, NinjaTrader.Core");
                if (globalsType == null) return outList;
                var prop = globalsType.GetProperty("ConnectOptions",
                    BindingFlags.Public | BindingFlags.Static);
                if (prop == null) return outList;
                var col = prop.GetValue(null, null) as System.Collections.IEnumerable;
                if (col == null) return outList;
                lock (col)
                {
                    foreach (var item in col)
                        if (item != null) outList.Add(item);
                }
            }
            catch { }
            return outList;
        }

        private static object FindConfiguredConnectionOption(List<object> options, string targetName,
                                                             bool fuzzy)
        {
            if (options == null || options.Count == 0 || string.IsNullOrWhiteSpace(targetName))
                return null;
            string wanted = targetName.Trim();
            var matches = options.Where(option =>
            {
                string name = SafeConnectionOptionName(option);
                if (string.IsNullOrEmpty(name)) return false;
                return fuzzy
                    ? name.IndexOf(wanted, StringComparison.OrdinalIgnoreCase) >= 0
                    : string.Equals(name, wanted, StringComparison.OrdinalIgnoreCase);
            }).ToList();
            return matches.Count == 1 ? matches[0] : null;
        }

        private static bool OptionMatchesAccountMode(object option, string accountMode)
        {
            if (IsDataFeedConnection(option))
                return false;
            string mode = (SafeStringProp(option, "Mode") ?? "").ToLowerInvariant();
            string name = SafeConnectionOptionName(option).ToLowerInvariant();
            if (accountMode == "playback")
                return mode.Contains("playback") || name.Contains("playback") ||
                       mode.Contains("воспроизвед") || name.Contains("воспроизвед");
            return mode.Contains("simulation") || mode.Contains("sim") ||
                   name.Contains("simulation") || name.StartsWith("sim") ||
                   mode.Contains("симуляц") || name.Contains("симуляц") ||
                   name.Contains("моделир") ||
                   name.StartsWith("demo") || name.Contains(" demo") || name.EndsWith("demo");
        }

        private static bool IsDataFeedConnection(object option)
        {
            if (option == null) return false;
            string name = SafeConnectionOptionName(option).ToLowerInvariant();
            string mode = (SafeStringProp(option, "Mode") ?? "").ToLowerInvariant();
            return name.Contains("data feed") || name.Contains("датафид") ||
                   mode.Contains("data feed") || mode.Contains("датафид");
        }

        private static object PreferTradingConnectOption(List<object> candidates, string accountMode)
        {
            if (candidates == null || candidates.Count == 0) return null;
            var tradingOnly = candidates.Where(option => !IsDataFeedConnection(option)).ToList();
            if (tradingOnly.Count == 1) return tradingOnly[0];

            Func<object, bool> isPreferred = option =>
            {
                string name = SafeConnectionOptionName(option).ToLowerInvariant();
                if (accountMode == "playback")
                    return name.Contains("playback") || name.Contains("воспроизвед");
                return name.Contains("моделир") ||
                       (name.Contains("simulation") && !name.Contains("data feed"));
            };
            var preferred = tradingOnly.Where(isPreferred).ToList();
            if (preferred.Count == 1) return preferred[0];
            return null;
        }

        private static bool IsConnectionActive(object connection)
        {
            if (connection == null) return false;
            string status = (SafeStringProp(connection, "Status") ?? "").ToLowerInvariant();
            return status.Contains("connected") || status.Contains("работает");
        }

        private static object FindActiveDataFeedConnection()
        {
            try
            {
                var prop = typeof(Connection).GetProperty("Connections",
                    BindingFlags.Public | BindingFlags.Static);
                var col = prop == null ? null : prop.GetValue(null, null) as System.Collections.IEnumerable;
                if (col == null) return null;
                lock (col)
                {
                    foreach (var item in col)
                    {
                        if (item == null || !IsConnectionActive(item)) continue;
                        object options = SafeGetPropValue(item, "Options");
                        if (IsDataFeedConnection(options))
                            return item;
                    }
                }
                return null;
            }
            catch { return null; }
        }

        private static string SafeConnectionOptionName(object option)
        {
            if (option == null) return "";
            return SafeStringProp(option, "Name");
        }

        private static object FindLiveConnection(string connectionName)
        {
            if (string.IsNullOrWhiteSpace(connectionName)) return null;
            try
            {
                var prop = typeof(Connection).GetProperty("Connections",
                    BindingFlags.Public | BindingFlags.Static);
                var col = prop == null ? null : prop.GetValue(null, null) as System.Collections.IEnumerable;
                if (col == null) return null;
                lock (col)
                {
                    foreach (var item in col)
                    {
                        if (item == null) continue;
                        string name = SafeConnectionOptionName(SafeGetPropValue(item, "Options"));
                        if (string.Equals(name, connectionName, StringComparison.OrdinalIgnoreCase))
                            return item;
                    }
                }
            }
            catch { }
            return null;
        }

        private static bool TryDisconnectConnection(object connection, out string error)
        {
            error = "";
            if (connection == null) return true;
            try
            {
                var method = connection.GetType().GetMethod("Disconnect",
                    BindingFlags.Public | BindingFlags.Instance,
                    null, Type.EmptyTypes, null);
                if (method == null) return true;
                method.Invoke(connection, null);
                return true;
            }
            catch (TargetInvocationException tex)
            {
                error = tex.InnerException != null ? tex.InnerException.Message : tex.Message;
                return false;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        private static bool TryConnectOption(object option, out string error, out string immediateStatus)
        {
            error = "";
            immediateStatus = "";
            if (option == null)
            {
                error = "connect option is null";
                return false;
            }
            try
            {
                MethodInfo connectMethod = typeof(Connection)
                    .GetMethods(BindingFlags.Public | BindingFlags.Static)
                    .FirstOrDefault(m =>
                        m.Name == "Connect" &&
                        m.GetParameters().Length == 1 &&
                        m.GetParameters()[0].ParameterType.IsAssignableFrom(option.GetType()));
                if (connectMethod == null)
                {
                    connectMethod = typeof(Connection)
                        .GetMethods(BindingFlags.Public | BindingFlags.Static)
                        .FirstOrDefault(m => m.Name == "Connect" && m.GetParameters().Length == 1);
                }
                if (connectMethod == null)
                {
                    error = "Connection.Connect(ConnectOptions) not found";
                    return false;
                }

                object connected = connectMethod.Invoke(null, new[] { option });
                immediateStatus = SafeStringProp(connected, "Status");
                if (string.IsNullOrEmpty(immediateStatus))
                {
                    object existing = FindLiveConnection(SafeConnectionOptionName(option));
                    immediateStatus = SafeStringProp(existing, "Status");
                }
                return true;
            }
            catch (TargetInvocationException tex)
            {
                error = tex.InnerException != null ? tex.InnerException.Message : tex.Message;
                return false;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        private static bool SetStrategyState(object strat, bool enable, out string err)
        {
            err = "";
            try
            {
                var t = strat.GetType();
                var setState = t.GetMethod("SetState",
                    BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic,
                    null, new[] { typeof(State) }, null);
                if (setState == null)
                {
                    err = "SetState method not found";
                    return false;
                }
                State target = enable ? State.Active : State.Terminated;
                setState.Invoke(strat, new object[] { target });
                return true;
            }
            catch (TargetInvocationException tex)
            {
                err = tex.InnerException != null ? tex.InnerException.Message : tex.Message;
                return false;
            }
            catch (Exception ex)
            {
                err = ex.Message;
                return false;
            }
        }

        private static string CheckB1Params(object strat)
        {
            var sb = new StringBuilder();
            foreach (var kv in B1Locked)
            {
                double actual;
                if (!TryGetDoubleProp(strat, kv.Key, out actual))
                {
                    sb.Append(kv.Key).Append(" missing; ");
                    continue;
                }
                if (Math.Abs(actual - kv.Value) > 0.0001)
                {
                    sb.Append(kv.Key).Append("=").Append(actual.ToString(CultureInfo.InvariantCulture))
                      .Append(" expected ").Append(kv.Value.ToString(CultureInfo.InvariantCulture))
                      .Append("; ");
                }
            }
            return sb.Length == 0 ? null : sb.ToString().TrimEnd();
        }

        private static bool TryGetDoubleProp(object o, string name, out double v)
        {
            v = 0;
            try
            {
                var pi = o.GetType().GetProperty(name);
                if (pi == null) return false;
                object raw = pi.GetValue(o, null);
                if (raw == null) return false;
                if (raw is bool b) { v = b ? 1.0 : 0.0; return true; }
                v = Convert.ToDouble(raw, CultureInfo.InvariantCulture);
                return true;
            }
            catch { return false; }
        }

        private static object SafeGetPropValue(object o, string name)
        {
            try
            {
                if (o == null) return null;
                var pi = o.GetType().GetProperty(name,
                    BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic);
                return pi == null ? null : pi.GetValue(o, null);
            }
            catch { return null; }
        }

        private static string SafeStringProp(object o, string name)
        {
            try
            {
                object v = SafeGetPropValue(o, name);
                return v == null ? "" : v.ToString();
            }
            catch { return ""; }
        }

        private static string SafeInstrumentFullName(object o)
        {
            try
            {
                var inst = o.GetType().GetProperty("Instrument")?.GetValue(o, null);
                if (inst == null) return "";
                var fp = inst.GetType().GetProperty("FullName")?.GetValue(inst, null);
                return fp == null ? "" : fp.ToString();
            }
            catch { return ""; }
        }

        private static string SafeStrategyId(object strat)
        {
            try
            {
                string cls = strat.GetType().Name;
                if (cls == "NTAMicroVwapRiskPilot") return "vwap_short_mnq_5m_v1";
                if (cls == "VWAPPullbackMGC5mV1") return "vwap_pullback_mgc_5m_v1";
                if (cls == "B1ShortOnlyMGC5mV2") return "mgc_b1_short_5m_v2";
                if (cls == "B1Stop24MGC5mC003") return "mgc_b1_stop24_5m_c003";
                if (cls == "B1Stop20MGC5mC004") return "mgc_b1_stop20_5m_c004";
                if (cls == "PullbackMNQ5mV2") return "pullback_mnq_5m_v2";
                if (cls == "NTAMicroVwapRiskExplorer") return "vwap_risk_explorer_mgc_5m_v1";
                if (cls == "NTAMicroSessionEdgeExplorer") return "session_edge_multi_5m_v2";
                if (cls == "NTAMicroMnqScalpPilot") return "scalping_mnq_1m_v1";
                if (cls == "NTAMnqMicroOrbOpenScalp") return "orb_open_scalp_mnq_1m_v1";
                if (cls == "NTAnalyzerEveryNBarLong") return "every_n_bar_long_generic_any_v1";
                if (cls == "StrategiyaUrovney") return "levels_strategy_userdefined_v1";
                return cls.ToLowerInvariant();
            }
            catch { return ""; }
        }

        // ------------------------------------------------------------------
        // Result file write & primitive JSON helpers

        private bool WriteResult(string commandId, string status, string message, string runtimeStrategyId)
        {
            var sb = new StringBuilder(256);
            sb.Append("{");
            JsField(sb, "command_id", commandId);            sb.Append(",");
            JsField(sb, "timestamp_utc", IsoNow());          sb.Append(",");
            JsField(sb, "status", status);                   sb.Append(",");
            JsField(sb, "message", message);                 sb.Append(",");
            JsField(sb, "runtime_strategy_id", runtimeStrategyId); sb.Append(",");
            JsField(sb, "processor_version", ProcessorVersion);
            sb.Append("}\n");
            try
            {
                File.AppendAllText(_resultsPath, sb.ToString(), new UTF8Encoding(false));
                BridgeLog.Info("RuntimeCommandProcessor: " + commandId + " " + status + " " + message);
                return true;
            }
            catch (Exception ex)
            {
                BridgeLog.Error("RuntimeCommandProcessor: append result failed", ex);
                return false;
            }
        }

        private static void JsField(StringBuilder sb, string k, string v)
        {
            sb.Append('"').Append(k).Append("\":").Append(JsString(v));
        }

        private static string JsString(string s)
        {
            if (s == null) return "\"\"";
            var sb = new StringBuilder(s.Length + 2);
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"':  sb.Append("\\\""); break;
                    case '\n': sb.Append("\\n");  break;
                    case '\r': sb.Append("\\r");  break;
                    case '\t': sb.Append("\\t");  break;
                    default:
                        if (c < 0x20) sb.AppendFormat("\\u{0:X4}", (int)c);
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
            return sb.ToString();
        }

        private static string IsoNow()
        {
            return DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture);
        }

        // Tiny tolerant string-field extractor - avoids pulling Newtonsoft into
        // this file. Commands are written by Python with json.dumps and known
        // schema, so this is enough for our needs.
        private static string ExtractJsonString(string json, string key)
        {
            if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key)) return "";
            string needle = "\"" + key + "\"";
            int i = json.IndexOf(needle, StringComparison.Ordinal);
            if (i < 0) return "";
            i += needle.Length;
            while (i < json.Length && (json[i] == ' ' || json[i] == ':' || json[i] == '\t')) i++;
            if (i >= json.Length || json[i] != '"') return "";
            i++;
            var sb = new StringBuilder();
            while (i < json.Length)
            {
                char c = json[i];
                if (c == '\\' && i + 1 < json.Length)
                {
                    char n = json[i + 1];
                    if (n == '"') { sb.Append('"');  i += 2; continue; }
                    if (n == '\\'){ sb.Append('\\'); i += 2; continue; }
                    if (n == 'n') { sb.Append('\n'); i += 2; continue; }
                    if (n == 'r') { sb.Append('\r'); i += 2; continue; }
                    if (n == 't') { sb.Append('\t'); i += 2; continue; }
                    sb.Append(n); i += 2; continue;
                }
                if (c == '"') break;
                sb.Append(c); i++;
            }
            return sb.ToString();
        }
    }
}
