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
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Runtime
{
    /// <summary>
    /// Phase 17 - NinjaTrader runtime telemetry exporter.
    ///
    /// Writes JSON snapshots and JSONL append-only event streams under
    ///   {project_root}/data/runtime/
    /// so the NT-Analyzer Strategy Control Center (app/runtime.py) can
    /// merge real Ninja runtime state with its registry/state machine.
    ///
    /// SAFETY: read-only. No order placement. No strategy enable/disable.
    /// Live accounts are exported as `account_mode=live` purely so the UI
    /// can display them as read-only; the backend will refuse all control.
    /// </summary>
    internal sealed class RuntimeTelemetryExporter
    {
        public const string ExporterVersion = "1.2.2";
        private const int   TickIntervalMs  = 5000;

        private readonly string _runtimeDir;
        private readonly Timer  _timer;
        private int _running;
        private readonly object _writeLock = new object();
        private readonly Dictionary<string, StrategyHistoryState> _lastStrategyStates =
            new Dictionary<string, StrategyHistoryState>(StringComparer.Ordinal);
        // Tracks execution_ids already written this session to suppress historical-replay duplicates.
        private readonly HashSet<string> _knownExecutionIds =
            new HashSet<string>(StringComparer.Ordinal);

        public RuntimeTelemetryExporter(string projectRoot)
        {
            if (string.IsNullOrEmpty(projectRoot))
                throw new ArgumentNullException(nameof(projectRoot));
            _runtimeDir = Path.Combine(projectRoot, "data", "runtime");
            Directory.CreateDirectory(_runtimeDir);
            LoadKnownExecutionIds();
            _timer = new Timer(OnTick, null, Timeout.Infinite, Timeout.Infinite);
        }

        public void Start()
        {
            BridgeLog.Info("RuntimeTelemetryExporter: start runtime_dir=" + _runtimeDir);
            HookAccountEvents();
            _timer.Change(0, TickIntervalMs);
        }

        /// <summary>Reads existing executions.jsonl at startup to pre-populate the known-IDs set,
        /// so that historical-replay ExecutionUpdate events don't create duplicates.</summary>
        private void LoadKnownExecutionIds()
        {
            try
            {
                string path = Path.Combine(_runtimeDir, "executions.jsonl");
                if (!File.Exists(path)) return;
                foreach (string line in File.ReadLines(path))
                {
                    // Fast scan: look for "execution_id":"<value>" without full JSON parse.
                    const string key = "\"execution_id\":\"";
                    int start = line.IndexOf(key, StringComparison.Ordinal);
                    if (start < 0) continue;
                    start += key.Length;
                    int end = line.IndexOf('"', start);
                    if (end <= start) continue;
                    _knownExecutionIds.Add(line.Substring(start, end - start));
                }
                BridgeLog.Info($"RuntimeTelemetryExporter: pre-loaded {_knownExecutionIds.Count} known execution IDs");
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("RuntimeTelemetryExporter: failed to load known execution IDs: " + ex.Message);
            }
        }


        public void Stop()
        {
            try { _timer.Change(Timeout.Infinite, Timeout.Infinite); }
            catch { }
            try { _timer.Dispose(); } catch { }
            try { AppendStrategyStopEvents("exporter_stop"); } catch { }
            try { UnhookAccountEvents(); } catch { }
            BridgeLog.Info("RuntimeTelemetryExporter: stopped");
        }

        // ---------------- timer tick ---------------------------------------

        private void OnTick(object _)
        {
            if (Interlocked.CompareExchange(ref _running, 1, 0) != 0) return;
            try
            {
                HookAccountEvents();
                WriteHeartbeat();
                WriteAccounts();
                WriteStrategiesAndPositions();
            }
            catch (Exception ex)
            {
                AppendError("tick", ex);
            }
            finally { _running = 0; }
        }

        // ---------------- heartbeat ----------------------------------------

        private void WriteHeartbeat()
        {
            var sb = new StringBuilder(256);
            sb.Append("{");
            AppendKv(sb, "timestamp_utc", IsoNow());                Sep(sb);
            AppendKv(sb, "ninja_version", SafeNinjaVersion());      Sep(sb);
            AppendKv(sb, "machine",       Environment.MachineName); Sep(sb);
            AppendKv(sb, "exporter_version", ExporterVersion);
            sb.Append("}");
            AtomicFile.WriteAllText(Path.Combine(_runtimeDir, "heartbeat.json"),
                                    sb.ToString());
        }

        // ---------------- accounts ----------------------------------------

        /// <summary>
        /// Write a snapshot of NinjaTrader accounts to accounts.json so the
        /// Trading Online UI can list them with cash/buying power and an
        /// honest paper/live classification. Read-only — never controls.
        /// </summary>
        private void WriteAccounts()
        {
            var sb = new StringBuilder(1024);
            sb.Append("{\"generated_at_utc\":").Append(JsStr(IsoNow()))
              .Append(",\"exporter_version\":").Append(JsStr(ExporterVersion))
              .Append(",\"accounts\":[");
            int n = 0;
            int liveCount = 0, paperCount = 0, playbackCount = 0, unknownCount = 0;
            string topLevelNote = "";
            try
            {
                foreach (var acc in SafeAllAccounts())
                {
                    if (acc == null) continue;
                    string accName = SafeAccountName(acc);
                    string accMode = ClassifyAccountMode(accName, acc);
                    if (accMode == "live") liveCount++;
                    else if (accMode == "paper") paperCount++;
                    else if (accMode == "playback") playbackCount++;
                    else unknownCount++;

                    // Read each numeric value individually so partial provider
                    // support doesn't drop the entire account record. Each null
                    // is reported in availability_notes so the UI can explain
                    // exactly which field NinjaTrader did not expose.
                    double? cash    = SafeAccountValue(acc, "CashValue");
                    double? bp      = SafeAccountValue(acc, "BuyingPower");
                    double? nlv     = SafeAccountValue(acc, "NetLiquidation");
                    double? rpnl    = SafeAccountValue(acc, "RealizedProfitLoss");
                    double? upnl    = SafeAccountValue(acc, "UnrealizedProfitLoss");
                    string ccy      = GetStringProp(acc, "Denomination");
                    string connStat = GetStringProp(acc, "ConnectionStatus");

                    var notes = new List<string>();
                    if (cash    == null) notes.Add("cash_value");
                    if (bp      == null) notes.Add("buying_power");
                    if (nlv     == null) notes.Add("net_liquidation");
                    if (rpnl    == null) notes.Add("realized_pnl");
                    if (upnl    == null) notes.Add("unrealized_pnl");

                    if (n > 0) sb.Append(",");
                    sb.Append("{");
                    AppendKv(sb, "account_name",      accName);                          Sep(sb);
                    AppendKv(sb, "account_mode",      accMode);                          Sep(sb);
                    AppendKv(sb, "cash_value",        cash);                             Sep(sb);
                    AppendKv(sb, "buying_power",      bp);                               Sep(sb);
                    AppendKv(sb, "net_liquidation",   nlv);                              Sep(sb);
                    AppendKv(sb, "realized_pnl",      rpnl);                             Sep(sb);
                    AppendKv(sb, "unrealized_pnl",    upnl);                             Sep(sb);
                    AppendKv(sb, "currency",          ccy);                              Sep(sb);
                    AppendKv(sb, "connection_status", connStat);                         Sep(sb);
                    sb.Append("\"availability_notes\":").Append(SerializeStringList(notes));
                    sb.Append("}");
                    n++;
                }
            }
            catch (Exception ex)
            {
                AppendError("accounts", ex);
                topLevelNote = "exception_during_enumeration: " + (ex.Message ?? "");
            }
            sb.Append("],\"summary\":{");
            AppendKv(sb, "total",    n);              Sep(sb);
            AppendKv(sb, "live",     liveCount);      Sep(sb);
            AppendKv(sb, "paper",    paperCount);     Sep(sb);
            AppendKv(sb, "playback", playbackCount);  Sep(sb);
            AppendKv(sb, "unknown",  unknownCount);
            sb.Append("}");
            if (!string.IsNullOrEmpty(topLevelNote))
            {
                sb.Append(",\"note\":").Append(JsStr(topLevelNote));
            }
            sb.Append("}");
            // Always write — even on zero accounts — so the UI can stop showing
            // the "bridge does not expose accounts.json" fallback message.
            AtomicFile.WriteAllText(Path.Combine(_runtimeDir, "accounts.json"),
                                    sb.ToString());
        }

        private static string SerializeStringList(List<string> items)
        {
            if (items == null || items.Count == 0) return "[]";
            var sb = new StringBuilder(64);
            sb.Append("[");
            for (int i = 0; i < items.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append(JsStr(items[i] ?? ""));
            }
            sb.Append("]");
            return sb.ToString();
        }

        /// <summary>
        /// Read a numeric account value via NinjaTrader's
        /// `Account.Get(AccountItem item, Currency)` reflection helper.
        /// Returns null if the account does not expose the metric (not all
        /// account providers do — the UI must tolerate nulls).
        /// </summary>
        private static double? SafeAccountValue(Account acc, string itemName)
        {
            try
            {
                var get = acc.GetType().GetMethod("Get",
                    BindingFlags.Public | BindingFlags.Instance);
                if (get == null) return null;
                var paramsInfo = get.GetParameters();
                if (paramsInfo.Length < 1) return null;
                var itemType = paramsInfo[0].ParameterType;
                if (!itemType.IsEnum) return null;
                object itemEnum;
                try { itemEnum = Enum.Parse(itemType, itemName); }
                catch { return null; }
                object result;
                if (paramsInfo.Length == 1)
                {
                    result = get.Invoke(acc, new object[] { itemEnum });
                }
                else
                {
                    var ccyType = paramsInfo[1].ParameterType;
                    object ccy = null;
                    try
                    {
                        var denomProp = acc.GetType().GetProperty("Denomination");
                        ccy = denomProp != null ? denomProp.GetValue(acc) : null;
                    }
                    catch { }
                    if (ccy == null && ccyType.IsEnum)
                    {
                        try { ccy = Enum.GetValues(ccyType).GetValue(0); } catch { }
                    }
                    result = get.Invoke(acc, new object[] { itemEnum, ccy });
                }
                if (result == null) return null;
                return Convert.ToDouble(result, CultureInfo.InvariantCulture);
            }
            catch { return null; }
        }

        // ---------------- strategies + positions ---------------------------

        private void WriteStrategiesAndPositions()
        {
            var strategiesJson = new StringBuilder(2048);
            var positionsJson  = new StringBuilder(1024);
            var historyStates  = new List<StrategyHistoryState>();
            strategiesJson.Append("{\"generated_at_utc\":").Append(JsStr(IsoNow()))
                          .Append(",\"strategies\":[");
            positionsJson.Append("{");

            int sCount = 0, pCount = 0;
            try
            {
                IEnumerable<Account> accounts = SafeAllAccounts();
                foreach (var acc in accounts)
                {
                    if (acc == null) continue;
                    string accName = SafeAccountName(acc);
                    string accMode = ClassifyAccountMode(accName, acc);

                    // ---- positions per account
                    if (pCount > 0) positionsJson.Append(",");
                    pCount++;
                    positionsJson.Append(JsStr(accName)).Append(":[");
                    int posI = 0;
                    foreach (var pos in SafePositions(acc))
                    {
                        if (posI > 0) positionsJson.Append(",");
                        positionsJson.Append(SerializePosition(pos));
                        posI++;
                    }
                    positionsJson.Append("]");

                    // ---- enabled strategies on account
                    foreach (var strat in SafeStrategies(acc))
                    {
                        if (strat == null) continue;
                        // Filter out ghost objects: Finalized/Terminated instances
                        // are not visible in NinjaTrader Strategies tab and must
                        // not appear in our telemetry as live rows.
                        string stState = GetStringProp(strat, "State") ?? "";
                        if (stState.Equals("Finalized", StringComparison.OrdinalIgnoreCase) ||
                            stState.Equals("Terminated", StringComparison.OrdinalIgnoreCase))
                            continue;
                        if (sCount > 0) strategiesJson.Append(",");
                        strategiesJson.Append(SerializeStrategy(strat, accName, accMode));
                        historyStates.Add(BuildStrategyHistoryState(strat, accName, accMode));
                        sCount++;
                    }
                }
            }
            catch (Exception ex)
            {
                AppendError("enumerate", ex);
            }

            strategiesJson.Append("]}");
            positionsJson.Append("}");

            AtomicFile.WriteAllText(Path.Combine(_runtimeDir, "strategies.json"),
                                    strategiesJson.ToString());
            AtomicFile.WriteAllText(Path.Combine(_runtimeDir, "positions.json"),
                                    positionsJson.ToString());
            UpdateStrategyHistory(historyStates);
        }

        // ---------------- per-strategy serialization -----------------------

        private string SerializeStrategy(object strat, string accName, string accMode)
        {
            var sb = new StringBuilder(1024);
            sb.Append("{");
            AppendKv(sb, "timestamp_utc",    IsoNow());                                 Sep(sb);
            AppendKv(sb, "account_name",     accName);                                  Sep(sb);
            AppendKv(sb, "account_mode",     accMode);                                  Sep(sb);
            AppendKv(sb, "strategy_id",      InferStrategyId(strat));                   Sep(sb);
            AppendKv(sb, "strategy_class",   strat.GetType().Name);                     Sep(sb);
            AppendKv(sb, "strategy_name",    GetStringProp(strat, "Name"));             Sep(sb);
            AppendKv(sb, "instrument",       GetInstrumentFullName(strat));             Sep(sb);
            AppendKv(sb, "contract_month",   GetInstrumentFullName(strat));             Sep(sb);
            AppendKv(sb, "enabled",          IsStrategyEnabled(strat));                 Sep(sb);
            AppendKv(sb, "state",            GetStringProp(strat, "State"));            Sep(sb);
            AppendKv(sb, "connection_status", GetStringProp(strat, "ConnectionStatus")); Sep(sb);

            // Phase 1.A — primary data series / timeframe export.
            // Surfaces "5 Minute" so the Trading Online UI can stop showing TF=—.
            AppendKv(sb, "timeframe",         GetTimeframeString(strat));               Sep(sb);
            AppendKv(sb, "bars_period_type",  GetTimeframeType(strat));                 Sep(sb);
            AppendKv(sb, "bars_period_value", GetTimeframeValue(strat));                Sep(sb);
            AppendKv(sb, "data_series_count", GetDataSeriesCount(strat));               Sep(sb);

            var pos = GetSubObject(strat, "Position");
            AppendKv(sb, "position_market_position", GetStringProp(pos, "MarketPosition")); Sep(sb);
            AppendKv(sb, "position_qty",     GetIntProp(pos, "Quantity"));              Sep(sb);
            AppendKv(sb, "avg_price",        GetDoubleProp(pos, "AveragePrice"));       Sep(sb);
            AppendKv(sb, "unrealized_pnl",   GetDoubleProp(strat, "UnrealizedPnL"));    Sep(sb);
            AppendKv(sb, "realized_pnl",     GetDoubleProp(strat, "RealizedPnL"));      Sep(sb);
            AppendKv(sb, "session_trades_count", GetIntProp(strat, "SystemPerformance.AllTrades.Count")); Sep(sb);

            var paramsDict = GatherStrategyParams(strat);
            string paramsJson = SerializeDict(paramsDict);
            sb.Append("\"params\":").Append(paramsJson); Sep(sb);
            AppendKv(sb, "params_hash", Sha256.OfString(CanonicalParams(paramsDict))); Sep(sb);
            // Phase 19+: ID derived from runtime object identity so that two
            // instances of the same class on the same account/instrument are
            // distinguishable. Stable for the lifetime of the NinjaTrader
            // process; changes when the strategy is re-added in the UI.
            AppendKv(sb, "runtime_instance_id",
                RuntimeInstanceIdUtil.Compute(strat, accName, strat.GetType().Name,
                    GetInstrumentFullName(strat), GetStringProp(strat, "Name")));
            sb.Append("}");
            return sb.ToString();
        }

        private string SerializePosition(object pos)
        {
            var sb = new StringBuilder(256);
            sb.Append("{");
            AppendKv(sb, "instrument", GetInstrumentFullName(pos)); Sep(sb);
            AppendKv(sb, "market_position", GetStringProp(pos, "MarketPosition")); Sep(sb);
            AppendKv(sb, "quantity", GetIntProp(pos, "Quantity")); Sep(sb);
            AppendKv(sb, "avg_price", GetDoubleProp(pos, "AveragePrice")); Sep(sb);
            AppendKv(sb, "unrealized_pnl", TryGetPositionUnrealizedPnl(pos));
            sb.Append("}");
            return sb.ToString();
        }

        /// <summary>
        /// Best-effort unrealized P/L for this instrument position (currency of account).
        /// Different NT8 builds expose different member names; missing values stay null.
        /// </summary>
        private static double? TryGetPositionUnrealizedPnl(object pos)
        {
            if (pos == null) return null;
            foreach (string name in new[] {
                "UnrealizedProfitLoss", "UnrealizedPnL", "UnrealizedPL"
            })
            {
                double? v = GetDoubleProp(pos, name);
                if (v != null) return v;
            }
            try
            {
                var mi = pos.GetType().GetMethod("GetUnrealizedProfitLoss",
                    BindingFlags.Public | BindingFlags.Instance);
                if (mi != null && mi.GetParameters().Length == 0)
                {
                    object r = mi.Invoke(pos, null);
                    if (r != null) return Convert.ToDouble(r, CultureInfo.InvariantCulture);
                }
            }
            catch { }
            return null;
        }

        // ---------------- strategy runtime history ------------------------

        private sealed class StrategyHistoryState
        {
            public string RuntimeInstanceId;
            public string StrategyId;
            public string StrategyClass;
            public string StrategyName;
            public string AccountName;
            public string AccountMode;
            public string Instrument;
            public string Timeframe;
            public bool Enabled;
            public string State;
            public int PositionQty;
            public double RealizedPnl;
            public double UnrealizedPnl;
        }

        private StrategyHistoryState BuildStrategyHistoryState(object strat, string accName, string accMode)
        {
            string cls  = strat.GetType().Name;
            string name = GetStringProp(strat, "Name");
            string inst = GetInstrumentFullName(strat);
            return new StrategyHistoryState
            {
                RuntimeInstanceId = RuntimeInstanceIdUtil.Compute(strat, accName, cls, inst, name),
                StrategyId        = InferStrategyId(strat),
                StrategyClass     = cls,
                StrategyName      = name,
                AccountName       = accName,
                AccountMode       = accMode,
                Instrument        = inst,
                Timeframe         = GetTimeframeString(strat),
                Enabled           = IsStrategyEnabled(strat),
                State             = GetStringProp(strat, "State"),
                PositionQty       = GetIntProp(GetSubObject(strat, "Position"), "Quantity"),
                RealizedPnl       = GetDoubleProp(strat, "RealizedPnL"),
                UnrealizedPnl     = GetDoubleProp(strat, "UnrealizedPnL"),
            };
        }

        private void UpdateStrategyHistory(List<StrategyHistoryState> current)
        {
            lock (_writeLock)
            {
                var seen = new HashSet<string>(StringComparer.Ordinal);
                foreach (var cur in current)
                {
                    if (cur == null || string.IsNullOrEmpty(cur.RuntimeInstanceId))
                        continue;
                    seen.Add(cur.RuntimeInstanceId);
                    StrategyHistoryState prev;
                    if (!_lastStrategyStates.TryGetValue(cur.RuntimeInstanceId, out prev))
                    {
                        AppendStrategyHistoryLine(
                            cur.Enabled ? "observed_start" : "observed", cur, "first_seen");
                    }
                    else
                    {
                        if (!prev.Enabled && cur.Enabled)
                            AppendStrategyHistoryLine("started", cur, "enabled_true");
                        else if (prev.Enabled && !cur.Enabled)
                            AppendStrategyHistoryLine("stopped", cur, "enabled_false");
                        else if (!string.Equals(prev.State ?? "", cur.State ?? "",
                                 StringComparison.OrdinalIgnoreCase))
                            AppendStrategyHistoryLine("state_changed", cur, "state_changed");
                    }
                    _lastStrategyStates[cur.RuntimeInstanceId] = cur;
                }

                var missing = _lastStrategyStates.Keys
                    .Where(k => !seen.Contains(k)).ToList();
                foreach (var key in missing)
                {
                    var prev = _lastStrategyStates[key];
                    AppendStrategyHistoryLine(
                        prev.Enabled ? "stopped" : "disappeared", prev, "not_seen");
                    _lastStrategyStates.Remove(key);
                }
            }
        }

        private void AppendStrategyStopEvents(string reason)
        {
            lock (_writeLock)
            {
                foreach (var st in _lastStrategyStates.Values.ToList())
                {
                    if (st != null && st.Enabled)
                        AppendStrategyHistoryLine("exporter_stop", st, reason);
                }
                _lastStrategyStates.Clear();
            }
        }

        private void AppendStrategyHistoryLine(string eventName, StrategyHistoryState st, string reason)
        {
            if (st == null) return;
            var sb = new StringBuilder(512);
            sb.Append("{");
            AppendKv(sb, "timestamp_utc",       IsoNow());              Sep(sb);
            AppendKv(sb, "event",               eventName ?? "");       Sep(sb);
            AppendKv(sb, "reason",              reason ?? "");          Sep(sb);
            AppendKv(sb, "runtime_instance_id", st.RuntimeInstanceId);  Sep(sb);
            AppendKv(sb, "strategy_id",         st.StrategyId);         Sep(sb);
            AppendKv(sb, "strategy_class",      st.StrategyClass);      Sep(sb);
            AppendKv(sb, "strategy_name",       st.StrategyName);       Sep(sb);
            AppendKv(sb, "account_name",        st.AccountName);        Sep(sb);
            AppendKv(sb, "account_mode",        st.AccountMode);        Sep(sb);
            AppendKv(sb, "instrument",          st.Instrument);         Sep(sb);
            AppendKv(sb, "timeframe",           st.Timeframe);          Sep(sb);
            AppendKv(sb, "enabled",             st.Enabled);            Sep(sb);
            AppendKv(sb, "state",               st.State);              Sep(sb);
            AppendKv(sb, "position_qty",        st.PositionQty);        Sep(sb);
            AppendKv(sb, "realized_pnl",        st.RealizedPnl);        Sep(sb);
            AppendKv(sb, "unrealized_pnl",      st.UnrealizedPnl);
            sb.Append("}");
            AppendLine(Path.Combine(_runtimeDir, "strategy_history.jsonl"), sb.ToString());
        }

        // ---------------- account hookup -----------------------------------

        private readonly Dictionary<string, Account> _hookedAccounts =
            new Dictionary<string, Account>(StringComparer.OrdinalIgnoreCase);

        private void HookAccountEvents()
        {
            try
            {
                foreach (var acc in SafeAllAccounts())
                {
                    if (acc == null) continue;
                    string key = SafeAccountName(acc);
                    if (string.IsNullOrEmpty(key))
                        key = "account@" + acc.GetHashCode().ToString(CultureInfo.InvariantCulture);
                    Account existing;
                    if (_hookedAccounts.TryGetValue(key, out existing) &&
                        object.ReferenceEquals(existing, acc))
                        continue;
                    try
                    {
                        if (existing != null)
                        {
                            try { existing.ExecutionUpdate -= OnExecutionUpdate; } catch { }
                            try { existing.OrderUpdate     -= OnOrderUpdate;     } catch { }
                        }
                        acc.ExecutionUpdate += OnExecutionUpdate;
                        acc.OrderUpdate     += OnOrderUpdate;
                        _hookedAccounts[key] = acc;
                    }
                    catch (Exception ex) { AppendError("hook " + SafeAccountName(acc), ex); }
                }
            }
            catch (Exception ex) { AppendError("HookAccountEvents", ex); }
        }

        private void UnhookAccountEvents()
        {
            foreach (var acc in _hookedAccounts.Values.ToList())
            {
                if (acc == null) continue;
                try { acc.ExecutionUpdate -= OnExecutionUpdate; } catch { }
                try { acc.OrderUpdate     -= OnOrderUpdate;     } catch { }
            }
            _hookedAccounts.Clear();
        }

        private void OnExecutionUpdate(object sender, ExecutionEventArgs e)
        {
            try { AppendExecution(e); }
            catch (Exception ex) { AppendError("OnExecutionUpdate", ex); }
        }

        private void OnOrderUpdate(object sender, OrderEventArgs e)
        {
            try { AppendOrder(e); }
            catch (Exception ex) { AppendError("OnOrderUpdate", ex); }
        }

        // ---------------- executions / orders / errors append --------------

        private void AppendExecution(ExecutionEventArgs e)
        {
            var ex = e?.Execution;
            if (ex == null) return;
            var order = GetSubObject(ex, "Order") ?? GetSubObject(e, "Order");
            var sb = new StringBuilder(512);
            sb.Append("{");
            // Use the exchange/fill clock for this execution — not export wall time —
            // so jsonl survives NT restarts (replay dedupe + correct PT "today" bucketing).
            AppendKv(sb, "timestamp_utc", IsoExecutionTimeUtc(ex));                 Sep(sb);
            string execId = GetStringProp(ex, "ExecutionId");
            AppendKv(sb, "execution_id",  execId);                                  Sep(sb);
            // Deduplicate: skip historical-replay fills already written in a prior session.
            if (!string.IsNullOrEmpty(execId))
            {
                lock (_writeLock)
                {
                    if (!_knownExecutionIds.Add(execId))
                        return;
                }
            }
            string accName = GetStringProp(GetSubObject(ex, "Account"), "Name");
            string instrument  = GetInstrumentFullName(ex);
            AppendKv(sb, "account_name",  accName);                                 Sep(sb);
            AppendKv(sb, "order_id",       FirstNonEmpty(
                GetStringProp(order, "Id"),
                GetStringProp(order, "OrderId"),
                GetStringProp(ex, "OrderId")));                                      Sep(sb);
            string orderName = GetStringProp(order, "Name");
            // For exits during historical replay the Order may be null; read FromEntrySignal
            // directly off the Execution object as fallback (NT preserves it on the fill record).
            string fromEntrySignal = FirstNonEmpty(
                GetStringProp(order, "FromEntrySignal"),
                GetStringProp(ex, "FromEntrySignal"));

            // Phase 19: get strategy class/id from Order.Strategy directly when possible,
            // fall back to FromEntrySignal (a signal name, not a class name).
            var exStrat = ResolveStrategyFromOrder(order, accName, instrument);
            string stratClass  = exStrat != null ? exStrat.GetType().Name
                                                 : StrategyClassFromSignal(fromEntrySignal, orderName);
            string stratId     = exStrat != null ? InferStrategyId(exStrat)
                                                 : InferStrategyIdFromClass(stratClass);
            string stratName   = exStrat != null ? GetStringProp(exStrat, "Name") : "";
            string runtimeId   = exStrat != null
                ? RuntimeInstanceIdUtil.Compute(exStrat, accName, stratClass, instrument, stratName)
                : "";

            AppendKv(sb, "strategy_id",   stratId);                                 Sep(sb);
            AppendKv(sb, "strategy_class", stratClass);                             Sep(sb);
            AppendKv(sb, "strategy_name", stratName);                               Sep(sb);
            AppendKv(sb, "runtime_instance_id", runtimeId);                         Sep(sb);
            AppendKv(sb, "order_name",    orderName);                               Sep(sb);
            AppendKv(sb, "from_entry_signal", fromEntrySignal);                     Sep(sb);
            AppendKv(sb, "instrument",    instrument);                              Sep(sb);
            AppendKv(sb, "market_position", GetStringProp(ex, "MarketPosition"));   Sep(sb);
            AppendKv(sb, "order_action",  FirstNonEmpty(
                GetStringProp(order, "OrderAction"),
                GetStringProp(ex, "Order.OrderAction"),
                GetStringProp(ex, "OrderAction")));                                 Sep(sb);
            AppendKv(sb, "order_type",    FirstNonEmpty(
                GetStringProp(order, "OrderType"),
                GetStringProp(ex, "Order.OrderType"),
                GetStringProp(ex, "OrderType")));                                   Sep(sb);
            AppendKv(sb, "order_state",   FirstNonEmpty(
                GetStringProp(order, "OrderState"),
                GetStringProp(ex, "Order.OrderState"),
                GetStringProp(ex, "OrderState")));                                  Sep(sb);
            AppendKv(sb, "limit_price",   GetDoubleProp(order, "LimitPrice"));      Sep(sb);
            AppendKv(sb, "stop_price",    GetDoubleProp(order, "StopPrice"));       Sep(sb);
            AppendKv(sb, "avg_fill",      GetDoubleProp(order, "AverageFillPrice"));Sep(sb);
            AppendKv(sb, "position_action", GetStringProp(ex, "PositionAction"));   Sep(sb);
            AppendKv(sb, "role",          ClassifyExecutionRole(ex));               Sep(sb);
            AppendKv(sb, "exit_reason",   ClassifyExitReason(ex));                  Sep(sb);
            AppendKv(sb, "quantity",      GetIntProp(ex, "Quantity"));              Sep(sb);
            AppendKv(sb, "price",         GetDoubleProp(ex, "Price"));              Sep(sb);
            AppendKv(sb, "commission",    GetDoubleProp(ex, "Commission"));         Sep(sb);
            AppendKv(sb, "realized_pnl",  null);
            sb.Append("}");
            AppendLine(Path.Combine(_runtimeDir, "executions.jsonl"), sb.ToString());
        }

        private void AppendOrder(OrderEventArgs e)
        {
            var o = e?.Order;
            if (o == null) return;
            var sb = new StringBuilder(512);
            sb.Append("{");
            AppendKv(sb, "timestamp_utc", IsoNow());                       Sep(sb);
            AppendKv(sb, "order_id",      GetStringProp(o, "Id"));         Sep(sb);
            string accName = GetStringProp(GetSubObject(o, "Account"), "Name");
            string instrument = GetInstrumentFullName(o);
            string orderName = GetStringProp(o, "Name");
            string fromEntrySignal = GetStringProp(o, "FromEntrySignal");
            var orderStrat = ResolveStrategyFromOrder(o, accName, instrument);
            string stratClass = orderStrat != null ? orderStrat.GetType().Name : "";
            string stratId = orderStrat != null ? InferStrategyId(orderStrat)
                                                : "";
            if (orderStrat == null)
            {
                stratClass = StrategyClassFromSignal(fromEntrySignal, orderName);
                stratId = InferStrategyIdFromClass(stratClass);
            }
            string stratName = orderStrat != null ? GetStringProp(orderStrat, "Name") : "";
            string runtimeId = orderStrat != null
                ? RuntimeInstanceIdUtil.Compute(orderStrat, accName, stratClass, instrument, stratName)
                : "";

            AppendKv(sb, "account_name",  accName);                         Sep(sb);
            AppendKv(sb, "strategy_id",   stratId);                         Sep(sb);
            AppendKv(sb, "strategy_class", stratClass);                     Sep(sb);
            AppendKv(sb, "strategy_name", stratName);                       Sep(sb);
            AppendKv(sb, "runtime_instance_id", runtimeId);                 Sep(sb);
            AppendKv(sb, "order_name",    orderName);                       Sep(sb);
            AppendKv(sb, "from_entry_signal", fromEntrySignal);             Sep(sb);
            AppendKv(sb, "instrument",    instrument);                      Sep(sb);
            AppendKv(sb, "order_state",   GetStringProp(o, "OrderState"));  Sep(sb);
            AppendKv(sb, "order_action",  GetStringProp(o, "OrderAction")); Sep(sb);
            AppendKv(sb, "order_type",    GetStringProp(o, "OrderType"));   Sep(sb);
            AppendKv(sb, "quantity",      GetIntProp(o, "Quantity"));       Sep(sb);
            AppendKv(sb, "filled",        GetIntProp(o, "Filled"));         Sep(sb);
            AppendKv(sb, "limit_price",   GetDoubleProp(o, "LimitPrice"));  Sep(sb);
            AppendKv(sb, "stop_price",    GetDoubleProp(o, "StopPrice"));   Sep(sb);
            AppendKv(sb, "avg_fill",      GetDoubleProp(o, "AverageFillPrice"));
            sb.Append("}");
            AppendLine(Path.Combine(_runtimeDir, "orders.jsonl"), sb.ToString());
        }

        private void AppendError(string where, Exception ex)
        {
            try
            {
                var sb = new StringBuilder(512);
                sb.Append("{");
                AppendKv(sb, "timestamp_utc", IsoNow());                  Sep(sb);
                AppendKv(sb, "where",         where ?? "");               Sep(sb);
                AppendKv(sb, "type",          ex == null ? "" : ex.GetType().FullName); Sep(sb);
                AppendKv(sb, "message",       ex == null ? "" : (ex.Message ?? "")); Sep(sb);
                AppendKv(sb, "stack",         ex == null ? "" : (ex.StackTrace ?? ""));
                sb.Append("}");
                AppendLine(Path.Combine(_runtimeDir, "errors.jsonl"), sb.ToString());
            }
            catch { /* swallow - never throw from error path */ }
        }

        private void AppendLine(string path, string line)
        {
            lock (_writeLock)
            {
                try
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    File.AppendAllText(path, line + Environment.NewLine, Encoding.UTF8);
                }
                catch (Exception ex)
                {
                    BridgeLog.Error("RuntimeExporter AppendLine " + path, ex);
                }
            }
        }

        // ---------------- helpers / safe reflection ------------------------

        private static IEnumerable<Account> SafeAllAccounts()
        {
            try
            {
                lock (Account.All)
                {
                    return Account.All.ToList();
                }
            }
            catch { return Enumerable.Empty<Account>(); }
        }

        private static IEnumerable<object> SafeStrategies(Account acc)
        {
            // try Account.Strategies via reflection (different NT8 builds)
            try
            {
                var prop = acc.GetType().GetProperty("Strategies",
                    BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic);
                if (prop != null)
                {
                    var col = prop.GetValue(acc) as System.Collections.IEnumerable;
                    if (col != null)
                    {
                        var list = new List<object>();
                        lock (col) { foreach (var x in col) if (x != null) list.Add(x); }
                        return list;
                    }
                }
            }
            catch { }
            return Enumerable.Empty<object>();
        }

        private static IEnumerable<object> SafePositions(Account acc)
        {
            try
            {
                var prop = acc.GetType().GetProperty("Positions");
                if (prop != null)
                {
                    var col = prop.GetValue(acc) as System.Collections.IEnumerable;
                    if (col != null)
                    {
                        var list = new List<object>();
                        lock (col) { foreach (var x in col) if (x != null) list.Add(x); }
                        return list;
                    }
                }
            }
            catch { }
            return Enumerable.Empty<object>();
        }

        private static string SafeAccountName(Account acc)
        {
            try { return acc.Name ?? ""; } catch { return ""; }
        }

        private static string ClassifyAccountMode(string name, Account acc)
        {
            try
            {
                // Try Account.Provider or AccountConnection or similar
                string provider = GetStringProp(acc, "Provider");
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

        private static bool IsStrategyEnabled(object strat)
        {
            try
            {
                string state = GetStringProp(strat, "State");
                if (!string.IsNullOrEmpty(state))
                {
                    string s = state.ToLowerInvariant();
                    if (s == "realtime" || s == "historical" || s == "active") return true;
                    if (s == "terminated" || s == "finalized") return false;
                }
            }
            catch { }
            return false;
        }

        private static string InferStrategyId(object strat)
        {
            // Map class -> canonical stable_id used by NT-Analyzer.
            string cls = strat.GetType().Name;
            return InferStrategyIdFromClass(cls);
        }

        private static string InferStrategyIdFromClass(string cls)
        {
            if (string.IsNullOrEmpty(cls)) return "";
            if (cls == "PullbackMNQ5mV2") return "pullback_mnq_5m_v2";
            if (cls == "VWAPPullbackMGC5mV1") return "vwap_pullback_mgc_5m_v1";
            if (cls == "B1ShortOnlyMGC5mV2") return "mgc_b1_short_5m_v2";
            if (cls == "B1Stop24MGC5mC003") return "mgc_b1_stop24_5m_c003";
            if (cls == "B1Stop20MGC5mC004") return "mgc_b1_stop20_5m_c004";
            if (cls == "NTAMnqMicroOrbRetestScalpC013") return "ntamnqmicroorbretestscalpc013";
            if (cls == "NTAMnqFullSessionOrbRetestScalpC014") return "ntamnqfullsessionorbretestscalpc014";
            if (cls == "NTAMnqLiquiditySweepReversalC015") return "ntamnqliquiditysweepreversalc015";
            if (cls == "NTAMnqOpenDriveShortScalpC016") return "ntamnqopendriveshortscalpc016";
            if (cls == "NTAMicroVwapRiskPilot") return "vwap_short_mnq_5m_v1";
            if (cls == "NTAMicroVwapRiskExplorer") return "vwap_risk_explorer_mgc_5m_v1";
            if (cls == "NTAMicroSessionEdgeExplorer") return "session_edge_multi_5m_v2";
            if (cls == "NTAMicroMnqScalpPilot") return "scalping_mnq_1m_v1";
            if (cls == "NTAMnqMicroOrbOpenScalp") return "orb_open_scalp_mnq_1m_v1";
            if (cls == "NTAMicroGoldSessionSweepReversalPilot") return "ntamicrogoldsessionsweepreversalpilot";
            if (cls == "NTAnalyzerEveryNBarLong") return "every_n_bar_long_generic_any_v1";
            if (cls == "StrategiyaUrovney") return "levels_strategy_userdefined_v1";
            if (cls == "NTAMicroOrbPilot")      return "ntamicroorbpilot";
            if (cls == "NTAMicroVwapGapMirrorPilot") return "ntamicrovwapgapmirrorpilot";
            if (cls == "NTAMicroVwapMeanRevertPilot") return "ntamicrovwapmeanrevertpilot";
            return cls.ToLowerInvariant();
        }

        // ---------------- timeframe / data series ---------------------------
        // Phase 1.A: NinjaTrader Strategy doesn't always expose BarsPeriod
        // directly during Configure/SetDefaults; it lives on
        // BarsArray[0].BarsPeriod once data is loaded. We probe several
        // shapes and stay null-safe so the exporter never throws.

        private static object FindPrimaryBarsPeriod(object strat)
        {
            if (strat == null) return null;
            try
            {
                // 1) BarsArray[0].BarsPeriod  (most reliable when data loaded)
                var barsArray = SimpleGet(strat, "BarsArray") as System.Collections.IEnumerable;
                if (barsArray != null)
                {
                    foreach (var b in barsArray)
                    {
                        if (b == null) continue;
                        var bp = SimpleGet(b, "BarsPeriod");
                        if (bp != null) return bp;
                    }
                }
            }
            catch { }
            try
            {
                // 2) Strategy.BarsPeriod (primary series convenience accessor)
                var bp = SimpleGet(strat, "BarsPeriod");
                if (bp != null) return bp;
            }
            catch { }
            try
            {
                // 3) BarsPeriods[0] (multi-series declarations before load)
                var bps = SimpleGet(strat, "BarsPeriods") as System.Collections.IEnumerable;
                if (bps != null)
                {
                    foreach (var b in bps)
                    {
                        if (b != null) return b;
                    }
                }
            }
            catch { }
            return null;
        }

        private static string GetTimeframeType(object strat)
        {
            var bp = FindPrimaryBarsPeriod(strat);
            return bp == null ? "" : (GetStringProp(bp, "BarsPeriodType") ?? "");
        }

        private static int GetTimeframeValue(object strat)
        {
            var bp = FindPrimaryBarsPeriod(strat);
            return bp == null ? 0 : GetIntProp(bp, "Value");
        }

        private static string GetTimeframeString(object strat)
        {
            try
            {
                string type = GetTimeframeType(strat);
                int value   = GetTimeframeValue(strat);
                if (string.IsNullOrEmpty(type)) return "";
                if (value <= 0) return type;
                // NinjaTrader UI shows "5 Minute", "1 Hour", "1 Day" etc.
                return value.ToString(CultureInfo.InvariantCulture) + " " + type;
            }
            catch { return ""; }
        }

        private static int GetDataSeriesCount(object strat)
        {
            try
            {
                var barsArray = SimpleGet(strat, "BarsArray") as System.Collections.IEnumerable;
                if (barsArray == null) return 0;
                int n = 0;
                foreach (var b in barsArray) { if (b != null) n++; }
                return n;
            }
            catch { return 0; }
        }

        private static string GetStrategyIdFromExecution(object ex)
        {
            try
            {
                var order = GetSubObject(ex, "Order");
                if (order == null) return "";
                var strat = ResolveStrategyFromOrder(order,
                    GetStringProp(GetSubObject(ex, "Account"), "Name"),
                    GetInstrumentFullName(ex));
                if (strat == null)
                {
                    string cls = StrategyClassFromSignal(
                        GetStringProp(order, "FromEntrySignal"),
                        GetStringProp(order, "Name"));
                    return InferStrategyIdFromClass(cls);
                }
                return InferStrategyId(strat);
            }
            catch { return ""; }
        }

        private static object ResolveStrategyFromOrder(object order, string accountName, string instrument)
        {
            if (order == null) return null;

            string[] directNames = {
                "Strategy", "OwnerStrategy", "NinjaScript", "Owner", "StrategyBase"
            };
            foreach (string name in directNames)
            {
                object candidate = SimpleGet(order, name);
                if (IsStrategyObject(candidate)) return candidate;
            }

            try
            {
                const BindingFlags flags = BindingFlags.Public
                    | BindingFlags.NonPublic
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly;

                Type t = order.GetType();
                while (t != null)
                {
                    foreach (var p in t.GetProperties(flags))
                    {
                        if (p == null || p.GetIndexParameters().Length != 0)
                            continue;
                        if (!LooksLikeStrategyMember(p.Name, p.PropertyType))
                            continue;
                        try
                        {
                            object candidate = p.GetValue(order, null);
                            if (IsStrategyObject(candidate)) return candidate;
                        }
                        catch { }
                    }

                    foreach (var f in t.GetFields(flags))
                    {
                        if (f == null || !LooksLikeStrategyMember(f.Name, f.FieldType))
                            continue;
                        try
                        {
                            object candidate = f.GetValue(order);
                            if (IsStrategyObject(candidate)) return candidate;
                        }
                        catch { }
                    }

                    t = t.BaseType;
                }
            }
            catch { }

            string signalClass = StrategyClassFromSignal(
                GetStringProp(order, "FromEntrySignal"),
                GetStringProp(order, "Name"));
            if (!string.IsNullOrEmpty(signalClass))
            {
                var bySignal = FindStrategyByClass(accountName, instrument, signalClass);
                if (bySignal != null) return bySignal;
            }

            var only = FindSingleStrategyForAccountInstrument(accountName, instrument);
            if (only != null) return only;
            return null;
        }

        private static string StrategyClassFromSignal(params string[] values)
        {
            if (values == null) return "";
            foreach (var raw in values)
            {
                string s = (raw ?? "").Trim();
                if (string.IsNullOrEmpty(s)) continue;
                foreach (var sep in new[] { '.', ':', '|' })
                {
                    int idx = s.IndexOf(sep);
                    if (idx <= 0) continue;
                    string head = s.Substring(0, idx).Trim();
                    if (LooksLikeStrategyClassName(head)) return head;
                }
                if (LooksLikeStrategyClassName(s)) return s;
            }
            return "";
        }

        private static bool LooksLikeStrategyClassName(string value)
        {
            if (string.IsNullOrEmpty(value)) return false;
            if (value == "Long" || value == "Short" || value == "Entry" || value == "Exit")
                return false;
            return value.StartsWith("NTA", StringComparison.Ordinal)
                || value.StartsWith("B1", StringComparison.Ordinal)
                || value == "VWAPPullbackMGC5mV1"
                || value == "PullbackMNQ5mV2"
                || value == "StrategiyaUrovney";
        }

        private static object FindStrategyByClass(string accountName, string instrument, string className)
        {
            if (string.IsNullOrEmpty(className)) return null;
            try
            {
                foreach (var acc in SafeAllAccounts())
                {
                    if (acc == null) continue;
                    if (!string.IsNullOrEmpty(accountName) &&
                        !string.Equals(SafeAccountName(acc), accountName, StringComparison.OrdinalIgnoreCase))
                        continue;
                    foreach (var strat in SafeStrategies(acc))
                    {
                        if (strat == null) continue;
                        if (!string.Equals(strat.GetType().Name, className, StringComparison.Ordinal))
                            continue;
                        if (!SameInstrumentRoot(GetInstrumentFullName(strat), instrument))
                            continue;
                        return strat;
                    }
                }
            }
            catch { }
            return null;
        }

        private static object FindSingleStrategyForAccountInstrument(string accountName, string instrument)
        {
            var matches = new List<object>();
            try
            {
                foreach (var acc in SafeAllAccounts())
                {
                    if (acc == null) continue;
                    if (!string.IsNullOrEmpty(accountName) &&
                        !string.Equals(SafeAccountName(acc), accountName, StringComparison.OrdinalIgnoreCase))
                        continue;
                    foreach (var strat in SafeStrategies(acc))
                    {
                        if (strat == null) continue;
                        if (!SameInstrumentRoot(GetInstrumentFullName(strat), instrument))
                            continue;
                        matches.Add(strat);
                    }
                }
            }
            catch { return null; }
            return matches.Count == 1 ? matches[0] : null;
        }

        private static bool SameInstrumentRoot(string a, string b)
        {
            string ar = InstrumentRoot(a);
            string br = InstrumentRoot(b);
            if (string.IsNullOrEmpty(ar) || string.IsNullOrEmpty(br)) return false;
            return string.Equals(ar, br, StringComparison.OrdinalIgnoreCase);
        }

        private static string InstrumentRoot(string value)
        {
            string s = (value ?? "").Trim();
            if (string.IsNullOrEmpty(s)) return "";
            int i = 0;
            while (i < s.Length && char.IsLetterOrDigit(s[i])) i++;
            return i <= 0 ? "" : s.Substring(0, i).ToUpperInvariant();
        }

        private static bool LooksLikeStrategyMember(string memberName, Type memberType)
        {
            string n = (memberName ?? "").ToLowerInvariant();
            string tn = memberType == null ? "" : (memberType.FullName ?? memberType.Name ?? "");
            if (n.Contains("strategy") || n.Contains("ninjascript")) return true;
            return tn.Contains("NinjaTrader.NinjaScript.Strategies")
                || tn.EndsWith(".Strategy", StringComparison.Ordinal)
                || tn.EndsWith(".StrategyBase", StringComparison.Ordinal)
                || tn.IndexOf("Strategy", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static bool IsStrategyObject(object candidate)
        {
            if (candidate == null) return false;
            Type t = candidate.GetType();
            while (t != null)
            {
                string full = t.FullName ?? t.Name ?? "";
                if (full.Contains("NinjaTrader.NinjaScript.Strategies"))
                    return true;
                if (t.Name == "Strategy" || t.Name == "StrategyBase")
                    return true;
                t = t.BaseType;
            }
            return false;
        }

        private static string ClassifyExecutionRole(object ex)
        {
            try
            {
                string pa = (GetStringProp(ex, "PositionAction") ?? "").ToLowerInvariant();
                if (pa.Contains("entry")) return "entry";
                if (pa.Contains("exit"))  return "exit";
                string nm = (GetStringProp(GetSubObject(ex, "Order"), "Name") ?? "").ToLowerInvariant();
                if (nm.Contains("stop"))   return "exit";
                if (nm.Contains("target") || nm.Contains("profit")) return "exit";
            }
            catch { }
            return "";
        }

        private static string ClassifyExitReason(object ex)
        {
            try
            {
                string nm = (GetStringProp(GetSubObject(ex, "Order"), "Name") ?? "").ToLowerInvariant();
                if (nm.Contains("stop"))   return "stop";
                if (nm.Contains("target")) return "target";
                if (nm.Contains("profit")) return "target";
            }
            catch { }
            return "";
        }

        private static IDictionary<string, object> GatherStrategyParams(object strat)
        {
            var d = new SortedDictionary<string, object>(StringComparer.Ordinal);
            try
            {
                var t = strat.GetType();
                foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
                {
                    if (!p.CanRead) continue;
                    bool isParam = false;
                    foreach (var a in p.GetCustomAttributes(true))
                    {
                        var an = a.GetType().Name;
                        if (an == "NinjaScriptPropertyAttribute" || an == "RangeAttribute"
                            || an == "DisplayAttribute")
                        { isParam = true; break; }
                    }
                    if (!isParam) continue;
                    object v;
                    try { v = p.GetValue(strat, null); } catch { continue; }
                    if (v == null || v is string || v.GetType().IsPrimitive
                        || v is decimal)
                        d[p.Name] = v;
                }
            }
            catch { }
            return d;
        }

        private static string CanonicalParams(IDictionary<string, object> d)
        {
            var sb = new StringBuilder();
            foreach (var kv in d)
            {
                sb.Append(kv.Key).Append('=').Append(JsValueRaw(kv.Value)).Append(';');
            }
            return sb.ToString();
        }

        private static string GetInstrumentFullName(object o)
        {
            try
            {
                var inst = GetSubObject(o, "Instrument");
                if (inst == null) return "";
                string s = GetStringProp(inst, "FullName");
                if (!string.IsNullOrEmpty(s)) return s;
                var mc = GetSubObject(inst, "MasterInstrument");
                return GetStringProp(mc, "Name") ?? "";
            }
            catch { return ""; }
        }

        private static object GetSubObject(object o, string path)
        {
            if (o == null || string.IsNullOrEmpty(path)) return null;
            try
            {
                object cur = o;
                foreach (var part in path.Split('.'))
                {
                    if (cur == null) return null;
                    cur = SimpleGet(cur, part);
                }
                return cur;
            }
            catch { return null; }
        }

        private static string GetStringProp(object o, string path)
        {
            object v = (path != null && path.Contains(".")) ?
                GetSubValue(o, path) : SimpleGet(o, path);
            return v == null ? "" : v.ToString();
        }

        private static int GetIntProp(object o, string path)
        {
            object v = (path != null && path.Contains(".")) ?
                GetSubValue(o, path) : SimpleGet(o, path);
            if (v == null) return 0;
            try { return Convert.ToInt32(v, CultureInfo.InvariantCulture); }
            catch { return 0; }
        }

        private static double GetDoubleProp(object o, string path)
        {
            object v = (path != null && path.Contains(".")) ?
                GetSubValue(o, path) : SimpleGet(o, path);
            if (v == null) return 0.0;
            try { return Convert.ToDouble(v, CultureInfo.InvariantCulture); }
            catch { return 0.0; }
        }

        private static object SimpleGet(object o, string name)
        {
            if (o == null || string.IsNullOrEmpty(name)) return null;
            try
            {
                const BindingFlags flags = BindingFlags.Public
                    | BindingFlags.NonPublic
                    | BindingFlags.Instance;
                Type t = o.GetType();
                while (t != null)
                {
                    var pi = t.GetProperty(name, flags | BindingFlags.DeclaredOnly);
                    if (pi != null && pi.GetIndexParameters().Length == 0)
                        return pi.GetValue(o, null);
                    var fi = t.GetField(name, flags | BindingFlags.DeclaredOnly);
                    if (fi != null) return fi.GetValue(o);
                    t = t.BaseType;
                }
            }
            catch { }
            return null;
        }

        private static string FirstNonEmpty(params string[] values)
        {
            if (values == null) return "";
            foreach (var value in values)
            {
                if (!string.IsNullOrWhiteSpace(value)) return value;
            }
            return "";
        }

        private static object GetSubValue(object o, string path)
        {
            if (o == null) return null;
            object cur = o;
            foreach (var part in path.Split('.'))
            {
                if (cur == null) return null;
                cur = SimpleGet(cur, part);
            }
            return cur;
        }

        private static string SafeNinjaVersion()
        {
            try
            {
                var t = Type.GetType("NinjaTrader.Core.Globals, NinjaTrader.Core");
                if (t != null)
                {
                    var p = t.GetProperty("Version") ?? t.GetProperty("ProductVersion");
                    if (p != null)
                    {
                        var v = p.GetValue(null, null);
                        if (v != null) return v.ToString();
                    }
                }
            }
            catch { }
            return "unknown";
        }

        private static string IsoNow()
        {
            return DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss",
                                            CultureInfo.InvariantCulture) + "Z";
        }

        /// <summary>
        /// Fill time in UTC ISO-8601 (ms) for jsonl rows. Falls back to IsoNow() if Time is missing.
        /// </summary>
        private static string IsoExecutionTimeUtc(object ex)
        {
            try
            {
                object tObj = SimpleGet(ex, "Time");
                if (tObj is DateTime dt)
                {
                    DateTime utc;
                    if (dt.Kind == DateTimeKind.Utc)
                        utc = dt;
                    else if (dt.Kind == DateTimeKind.Local)
                        utc = dt.ToUniversalTime();
                    else
                    {
                        // NinjaTrader commonly surfaces Unspecified; treat like local workstation time.
                        utc = DateTime.SpecifyKind(dt, DateTimeKind.Local).ToUniversalTime();
                    }
                    return utc.ToString("yyyy-MM-ddTHH:mm:ss.fff",
                                        CultureInfo.InvariantCulture) + "Z";
                }
            }
            catch { /* fall through */ }
            return IsoNow();
        }

        // ---- micro JSON helpers (no Newtonsoft dependency) ----------------

        private static void AppendKv(StringBuilder sb, string k, object v)
        {
            sb.Append(JsStr(k)).Append(":").Append(JsValueRaw(v));
        }

        private static void Sep(StringBuilder sb) { sb.Append(","); }

        private static string JsStr(string s)
        {
            if (s == null) return "null";
            var sb = new StringBuilder(s.Length + 2);
            sb.Append('"');
            foreach (var c in s)
            {
                if (c == '"') sb.Append("\\\"");
                else if (c == '\\') sb.Append("\\\\");
                else if (c == '\n') sb.Append("\\n");
                else if (c == '\r') sb.Append("\\r");
                else if (c == '\t') sb.Append("\\t");
                else if (c < 0x20) sb.AppendFormat("\\u{0:x4}", (int)c);
                else sb.Append(c);
            }
            sb.Append('"');
            return sb.ToString();
        }

        private static string JsValueRaw(object v)
        {
            if (v == null) return "null";
            if (v is bool b) return b ? "true" : "false";
            if (v is string s) return JsStr(s);
            if (v is double d) return double.IsNaN(d) || double.IsInfinity(d)
                                       ? "null"
                                       : d.ToString("R", CultureInfo.InvariantCulture);
            if (v is float f)  return float.IsNaN(f) || float.IsInfinity(f)
                                       ? "null"
                                       : f.ToString("R", CultureInfo.InvariantCulture);
            if (v is decimal m) return m.ToString(CultureInfo.InvariantCulture);
            if (v is int || v is long || v is short || v is byte
                || v is uint || v is ulong || v is ushort || v is sbyte)
                return Convert.ToString(v, CultureInfo.InvariantCulture);
            return JsStr(v.ToString());
        }

        private static string SerializeDict(IDictionary<string, object> d)
        {
            var sb = new StringBuilder(256);
            sb.Append("{");
            int i = 0;
            foreach (var kv in d)
            {
                if (i > 0) sb.Append(",");
                sb.Append(JsStr(kv.Key)).Append(":").Append(JsValueRaw(kv.Value));
                i++;
            }
            sb.Append("}");
            return sb.ToString();
        }
    }
}
