using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Runtime
{
    /// <summary>
    /// Dynamic, read-only BarsRequest registry for the web desktop.
    /// The backend writes requested instrument/timeframe pairs and this class
    /// keeps one NinjaTrader subscription per pair, publishing atomic snapshots.
    /// </summary>
    internal sealed class RuntimeMarketDataExporter
    {
        private const int TickMs = 1000;
        private const int SnapshotMinIntervalMs = 125;
        private const int RequestTtlSec = 180;
        private readonly string _runtimeDir;
        private readonly string _requestPath;
        private readonly string _snapshotPath;
        private readonly Timer _timer;
        private readonly object _gate = new object();
        private readonly Dictionary<string, Subscription> _subscriptions =
            new Dictionary<string, Subscription>(StringComparer.OrdinalIgnoreCase);
        private readonly MarketDataEventQueue _eventQueue = new MarketDataEventQueue(8192);
        private MarketDataIpcClient _ipcClient;
        private int _running;
        private int _snapshotQueued;
        private volatile bool _started;
        private DateTime _lastSnapshotWriteUtc = DateTime.MinValue;
        private string _lastIpcConnectionId = "";

        private sealed class Subscription
        {
            public string Key;
            public string Instrument;
            public string Timeframe;
            public int Limit;
            public int RangeDays;
            public string FromDate;
            public string ToDate;
            public DateTime RequestedAtUtc;
            public DateTime UpdatedAtUtc;
            public DateTime LastCaptureUtc;
            public DateTime LastMarketDataUtc;
            public string Status = "starting";
            public string Error = "";
            public JArray Bars = new JArray();
            public int SourceStart;
            public int SourceCount;
            public BarsRequest Request;
            public EventHandler<BarsUpdateEventArgs> UpdateHandler;
            public MarketData MarketData;
            public EventHandler<MarketDataEventArgs> MarketDataHandler;
        }

        public RuntimeMarketDataExporter(string projectRoot, string runtimeDir = null)
        {
            if (string.IsNullOrWhiteSpace(projectRoot))
                throw new ArgumentNullException(nameof(projectRoot));
            _runtimeDir = string.IsNullOrWhiteSpace(runtimeDir) ? Path.Combine(projectRoot, "data", "runtime") : runtimeDir;
            Directory.CreateDirectory(_runtimeDir);
            _requestPath = Path.Combine(_runtimeDir, "market_data_requests.json");
            _snapshotPath = Path.Combine(_runtimeDir, "market_bars.json");
            _timer = new Timer(OnTick, null, Timeout.Infinite, Timeout.Infinite);
        }

        public void Start()
        {
            BridgeLog.Info("RuntimeMarketDataExporter: started");
            _started = true;
            try
            {
                // IPC writer is optional at boot: if the backend token/server is
                // not ready yet the client reconnects. File snapshot fallback
                // remains active regardless.
                _ipcClient = new MarketDataIpcClient(_eventQueue, _runtimeDir);
                _ipcClient.Start();
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("RuntimeMarketDataExporter: IPC client not started: " + ex.Message);
            }
            _timer.Change(0, TickMs);
        }

        public void Stop()
        {
            _started = false;
            try { _timer.Change(Timeout.Infinite, Timeout.Infinite); } catch { }
            try { _timer.Dispose(); } catch { }
            try { if (_ipcClient != null) _ipcClient.Stop(); } catch { }
            _ipcClient = null;
            List<Subscription> rows;
            lock (_gate)
            {
                rows = _subscriptions.Values.ToList();
                _subscriptions.Clear();
            }
            foreach (var row in rows) DisposeSubscription(row);
            BridgeLog.Info("RuntimeMarketDataExporter: stopped queue=" + _eventQueue.MetricsJson());
        }

        private void OnTick(object state)
        {
            if (Interlocked.CompareExchange(ref _running, 1, 0) != 0) return;
            try
            {
                CheckIpcReconnect();
                SyncRequests();
                CaptureMarketDataPoll();
                RequestSnapshotWrite();
            }
            catch (Exception ex)
            {
                BridgeLog.Error("RuntimeMarketDataExporter tick failed", ex);
            }
            finally { Interlocked.Exchange(ref _running, 0); }
        }

        private void SyncRequests()
        {
            JObject doc;
            try
            {
                if (!File.Exists(_requestPath)) return;
                doc = JObject.Parse(File.ReadAllText(_requestPath));
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("RuntimeMarketDataExporter: request file unreadable: " + ex.Message);
                return;
            }

            DateTime now = DateTime.UtcNow;
            var wanted = new Dictionary<string, Subscription>(StringComparer.OrdinalIgnoreCase);
            foreach (JObject row in (doc["requests"] as JArray ?? new JArray()).OfType<JObject>())
            {
                string instrument = ((string)row["instrument"] ?? "").Trim();
                string timeframe = ((string)row["timeframe"] ?? "5m").Trim();
                string key = ((string)row["key"] ?? (instrument.ToUpperInvariant() + "|" + timeframe.ToLowerInvariant())).Trim();
                if (instrument.Length == 0 || key.Length == 0) continue;
                DateTime requestedAt;
                if (!DateTime.TryParse((string)row["requested_at_utc"], CultureInfo.InvariantCulture,
                    DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out requestedAt))
                    requestedAt = now;
                if ((now - requestedAt).TotalSeconds > RequestTtlSec) continue;
                wanted[key] = new Subscription
                {
                    Key = key, Instrument = instrument, Timeframe = timeframe,
                    Limit = Math.Max(100, Math.Min(50000, (int?)row["limit"] ?? 1500)),
                    RangeDays = Math.Max(0, Math.Min(3660, (int?)row["range_days"] ?? 0)),
                    FromDate = ((string)row["from"] ?? "").Trim(),
                    ToDate = ((string)row["to"] ?? "").Trim(),
                    RequestedAtUtc = requestedAt,
                };
            }

            List<Subscription> removed = new List<Subscription>();
            List<Subscription> added = new List<Subscription>();
            lock (_gate)
            {
                foreach (string key in _subscriptions.Keys.ToList())
                {
                    if (!wanted.ContainsKey(key))
                    {
                        removed.Add(_subscriptions[key]);
                        _subscriptions.Remove(key);
                    }
                }
                foreach (var pair in wanted)
                {
                    Subscription current;
                    if (_subscriptions.TryGetValue(pair.Key, out current))
                    {
                        bool changed = current.Limit != pair.Value.Limit || current.RangeDays != pair.Value.RangeDays
                            || !string.Equals(current.FromDate, pair.Value.FromDate, StringComparison.Ordinal)
                            || !string.Equals(current.ToDate, pair.Value.ToDate, StringComparison.Ordinal);
                        if (changed)
                        {
                            removed.Add(current);
                            _subscriptions[pair.Key] = pair.Value;
                            added.Add(pair.Value);
                        }
                        else current.RequestedAtUtc = pair.Value.RequestedAtUtc;
                    }
                    else
                    {
                        _subscriptions[pair.Key] = pair.Value;
                        added.Add(pair.Value);
                    }
                }
            }
            foreach (var sub in removed) DisposeSubscription(sub);
            foreach (var sub in added) StartSubscription(sub);

            if (_ipcClient != null)
            {
                lock (_gate)
                {
                    _ipcClient.SubscriptionCount = _subscriptions.Count;
                    var contracts = _subscriptions.Values.Select(s => "\"" + s.Instrument + "\"").ToList();
                    _ipcClient.ActiveContracts = "[" + string.Join(",", contracts) + "]";
                }
            }
        }

        private void CheckIpcReconnect()
        {
            if (_ipcClient == null) return;
            string currentId = _ipcClient.ConnectionId;
            bool connected = _ipcClient.IsConnected;
            if (connected && !string.IsNullOrEmpty(currentId) && !string.Equals(_lastIpcConnectionId, currentId, StringComparison.Ordinal))
            {
                BridgeLog.Info("RuntimeMarketDataExporter: IPC reconnect detected. Resetting subscriptions. Old ID=" + _lastIpcConnectionId + ", New ID=" + currentId);
                _lastIpcConnectionId = currentId;

                List<Subscription> rows;
                lock (_gate)
                {
                    rows = _subscriptions.Values.ToList();
                    _subscriptions.Clear();
                }
                foreach (var row in rows) DisposeSubscription(row);
            }
        }

        public void ForceResubscribe()
        {
            BridgeLog.Info("RuntimeMarketDataExporter: ForceResubscribe requested.");
            lock (_gate)
            {
                _lastIpcConnectionId = "";
            }
            if (_ipcClient != null)
            {
                _ipcClient.ForceReconnect();
            }
        }

        public void ResubscribeInstrument(string instrument)
        {
            if (string.IsNullOrEmpty(instrument)) return;
            BridgeLog.Info("RuntimeMarketDataExporter: ResubscribeInstrument requested for " + instrument);

            Subscription oldSub = null;
            string keyToRecreate = null;

            lock (_gate)
            {
                foreach (var pair in _subscriptions)
                {
                    if (string.Equals(pair.Value.Instrument, instrument, StringComparison.OrdinalIgnoreCase))
                    {
                        keyToRecreate = pair.Key;
                        oldSub = pair.Value;
                        break;
                    }
                }
                if (keyToRecreate != null)
                {
                    _subscriptions.Remove(keyToRecreate);
                }
            }

            if (oldSub != null && keyToRecreate != null)
            {
                BridgeLog.Info("RuntimeMarketDataExporter: Recreating subscription for " + instrument + " (Key: " + keyToRecreate + ")");
                DisposeSubscription(oldSub);

                Subscription newSub = new Subscription
                {
                    Key = oldSub.Key,
                    Instrument = oldSub.Instrument,
                    Timeframe = oldSub.Timeframe,
                    Limit = oldSub.Limit,
                    RangeDays = oldSub.RangeDays,
                    FromDate = oldSub.FromDate,
                    ToDate = oldSub.ToDate,
                    RequestedAtUtc = oldSub.RequestedAtUtc,
                    UpdatedAtUtc = DateTime.UtcNow,
                    Status = "starting"
                };

                StartSubscription(newSub);

                lock (_gate)
                {
                    if (_subscriptions.TryGetValue(keyToRecreate, out var duplicate))
                    {
                        BridgeLog.Warn("RuntimeMarketDataExporter: Duplicate subscription detected for key " + keyToRecreate + " during resubscribe. Disposing existing.");
                        DisposeSubscription(duplicate);
                        _subscriptions.Remove(keyToRecreate);
                    }
                    _subscriptions.Add(keyToRecreate, newSub);
                    BridgeLog.Info("RuntimeMarketDataExporter: Atomically added new subscription for " + keyToRecreate + ". Dict count=" + _subscriptions.Count);
                }
            }
            else
            {
                BridgeLog.Warn("RuntimeMarketDataExporter: Subscription not found for " + instrument);
            }
        }

        private void StartSubscription(Subscription sub)
        {
            try
            {
                Instrument instrument = Instrument.GetInstrument(sub.Instrument);
                if (instrument == null)
                    throw new InvalidOperationException("NinjaTrader instrument not found: " + sub.Instrument);
                BarsRequest request;
                DateTime fromLocal, toLocal;
                if (DateTime.TryParse(sub.FromDate, out fromLocal) && DateTime.TryParse(sub.ToDate, out toLocal))
                    request = new BarsRequest(instrument, fromLocal.Date, toLocal.Date.AddDays(1));
                else if (sub.RangeDays > 0)
                    request = new BarsRequest(instrument, DateTime.Now.AddDays(-sub.RangeDays), DateTime.Now);
                else
                    request = new BarsRequest(instrument, sub.Limit);
                request.BarsPeriod = ParseBarsPeriod(sub.Timeframe);
                try { request.TradingHours = TradingHours.Get("Default 24 x 7"); }
                catch { /* provider/instrument default remains valid */ }
                sub.Request = request;
                sub.UpdateHandler = (sender, args) => CaptureUpdate(sub, args);
                request.Update += sub.UpdateHandler;
                try
                {
                    sub.MarketData = new MarketData(instrument);
                    sub.MarketDataHandler = (sender, args) => CaptureMarketData(sub, args);
                    sub.MarketData.Update += sub.MarketDataHandler;
                }
                catch (Exception mdex)
                {
                    BridgeLog.Warn("RuntimeMarketDataExporter: " + sub.Key + " live ticks unavailable: " + mdex.Message);
                }
                request.Request(new Action<BarsRequest, ErrorCode, string>((bars, code, message) =>
                {
                    if (code != ErrorCode.NoError)
                    {
                        lock (_gate)
                        {
                            sub.Status = "error";
                            sub.Error = code + (string.IsNullOrWhiteSpace(message) ? "" : ": " + message);
                            sub.UpdatedAtUtc = DateTime.UtcNow;
                        }
                        RequestSnapshotWrite();
                        return;
                    }
                    Capture(sub, bars.Bars, true);
                }));
                BridgeLog.Info("RuntimeMarketDataExporter: subscribed " + sub.Key);
            }
            catch (Exception ex)
            {
                lock (_gate)
                {
                    sub.Status = "error";
                    sub.Error = ex.Message;
                    sub.UpdatedAtUtc = DateTime.UtcNow;
                }
                RequestSnapshotWrite();
                BridgeLog.Warn("RuntimeMarketDataExporter: " + sub.Key + " failed: " + ex.Message);
            }
        }

        private static BarsPeriod ParseBarsPeriod(string timeframe)
        {
            string tf = (timeframe ?? "5m").Trim().ToLowerInvariant();
            if (tf == "1d") return new BarsPeriod { BarsPeriodType = BarsPeriodType.Day, Value = 1 };
            int value;
            if (tf.EndsWith("h") && int.TryParse(tf.Substring(0, tf.Length - 1), out value))
                return new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = value * 60 };
            if (tf.EndsWith("m") && int.TryParse(tf.Substring(0, tf.Length - 1), out value))
                return new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = value };
            return new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = 5 };
        }

        private void Capture(Subscription sub, Bars bars, bool force = false)
        {
            if (bars == null) return;
            DateTime now = DateTime.UtcNow;
            lock (_gate)
            {
                if (!force && (now - sub.LastCaptureUtc).TotalMilliseconds < 500) return;
                sub.LastCaptureUtc = now;
            }
            try
            {
                int count = bars.Count;
                int start = Math.Max(0, count - sub.Limit);
                var arr = new JArray();
                for (int i = start; i < count; i++)
                    arr.Add(SerializeBar(bars, i));
                lock (_gate)
                {
                    sub.Bars = arr;
                    sub.SourceStart = start;
                    sub.SourceCount = count;
                    sub.Status = arr.Count > 0 ? "live" : "waiting";
                    sub.Error = "";
                    sub.UpdatedAtUtc = now;
                }
            }
            catch (Exception ex)
            {
                lock (_gate)
                {
                    sub.Status = "error";
                    sub.Error = ex.Message;
                    sub.UpdatedAtUtc = now;
                }
            }
            RequestSnapshotWrite();
        }

        /// <summary>
        /// MarketData callback path: ONLY read Last/Bid/Ask/Volume, minimal
        /// normalize, timestamp, bounded non-blocking enqueue, return.
        /// No file I/O, HTTP, large serialization, or candle building here.
        /// </summary>
        private void CaptureMarketData(Subscription sub, MarketDataEventArgs args)
        {
            if (sub == null || args == null) return;
            string eventType = null;
            if (args.MarketDataType == MarketDataType.Last) eventType = "trade";
            else if (args.MarketDataType == MarketDataType.Bid) eventType = "bid";
            else if (args.MarketDataType == MarketDataType.Ask) eventType = "ask";
            else return;

            double price = args.Price;
            if (double.IsNaN(price) || double.IsInfinity(price) || price < 0) return;
            if (eventType == "trade" && price <= 0) return;

            // MarketDataEventArgs does not expose a reliable exchange timestamp
            // across NT builds; record receive/enqueue time and never invent
            // exchange_sequence.
            DateTime tsEventUtc = DateTime.UtcNow;

            long volume = 0;
            try { volume = Convert.ToInt64(args.Volume); } catch { volume = 0; }

            double bid = 0, ask = 0;
            try
            {
                if (sub.MarketData != null)
                {
                    if (sub.MarketData.Bid != null) bid = sub.MarketData.Bid.Price;
                    if (sub.MarketData.Ask != null) ask = sub.MarketData.Ask.Price;
                }
            }
            catch { }

            var tick = new MarketDataTick
            {
                EventType = eventType,
                Instrument = sub.Instrument,
                SubscriptionId = sub.Key,
                Price = price,
                Bid = bid,
                Ask = ask,
                Volume = volume,
                TsEventUtc = tsEventUtc,
                TsEnqueuedUtc = DateTime.UtcNow,
                GeneratedSequence = _eventQueue.NextGeneratedSequence(),
                ExchangeSequence = null, // never invent exchange sequence
                ProviderSequence = null,
            };
            _eventQueue.TryEnqueue(tick);
        }

        /// <summary>
        /// Timer-path compatibility: refresh last bar close for market_bars.json
        /// fallback. Intentionally NOT used from the MarketData callback.
        /// </summary>
        private void ApplyLastToBarsFallback(Subscription sub, MarketDataEventArgs args)
        {
            if (sub == null || args == null || args.MarketDataType != MarketDataType.Last) return;
            double price = args.Price;
            if (double.IsNaN(price) || double.IsInfinity(price) || price <= 0) return;
            DateTime now = DateTime.UtcNow;
            lock (_gate)
            {
                if ((now - sub.LastMarketDataUtc).TotalMilliseconds < 80) return;
                if (sub.Bars == null || sub.Bars.Count == 0) return;
                JObject last = sub.Bars[sub.Bars.Count - 1] as JObject;
                if (last == null) return;
                sub.LastMarketDataUtc = now;
                double high = JsonDouble(last, "h", price);
                double low = JsonDouble(last, "l", price);
                last["c"] = price;
                last["h"] = Math.Max(high, price);
                last["l"] = Math.Min(low, price);
                sub.Status = "live";
                sub.Error = "";
                sub.UpdatedAtUtc = now;
            }
            RequestSnapshotWrite();
        }

        private void CaptureMarketDataPoll()
        {
            List<Subscription> rows;
            lock (_gate) rows = _subscriptions.Values.ToList();
            foreach (var sub in rows)
            {
                try
                {
                    if (sub.MarketData == null) continue;
                    // File-snapshot fallback only (not the IPC callback path).
                    ApplyLastToBarsFallback(sub, sub.MarketData.Last);
                }
                catch { }
            }
        }

        private void CaptureUpdate(Subscription sub, BarsUpdateEventArgs args)
        {
            Bars bars = sub.Request == null ? null : sub.Request.Bars;
            if (bars == null || args == null) return;
            DateTime now = DateTime.UtcNow;
            lock (_gate)
            {
                if ((now - sub.LastCaptureUtc).TotalMilliseconds < 100) return;
                sub.LastCaptureUtc = now;
                int count = bars.Count;
                int start = Math.Max(0, count - sub.Limit);
                int expected = count - start;
                if (sub.Bars == null || sub.Bars.Count != expected || sub.SourceStart != start)
                {
                    // A new bar can shift the fixed-size window by one without
                    // rebuilding tens of thousands of historical bars.
                    if (sub.Bars != null && count == sub.SourceCount + 1 &&
                        (start == sub.SourceStart || start == sub.SourceStart + 1))
                    {
                        if (start > sub.SourceStart && sub.Bars.Count > 0) sub.Bars.RemoveAt(0);
                        sub.Bars.Add(SerializeBar(bars, count - 1));
                    }
                    else
                    {
                        // Rare path: reconnect/range change/correction.
                        ThreadPool.QueueUserWorkItem(_ => Capture(sub, bars, true));
                        return;
                    }
                }
                else
                {
                    int min = Math.Max(start, args.MinIndex);
                    int max = Math.Min(count - 1, args.MaxIndex);
                    for (int i = min; i <= max; i++) sub.Bars[i - start] = SerializeBar(bars, i);
                }
                sub.SourceStart = start; sub.SourceCount = count;
                sub.Status = sub.Bars.Count > 0 ? "live" : "waiting";
                sub.Error = ""; sub.UpdatedAtUtc = now;
            }
            RequestSnapshotWrite();
        }

        private static JObject SerializeBar(Bars bars, int i)
        {
            return new JObject
            {
                ["t"] = bars.GetTime(i).ToUniversalTime().ToString("o", CultureInfo.InvariantCulture),
                ["o"] = bars.GetOpen(i), ["h"] = bars.GetHigh(i),
                ["l"] = bars.GetLow(i), ["c"] = bars.GetClose(i),
                ["v"] = bars.GetVolume(i),
            };
        }

        private static double JsonDouble(JObject row, string name, double fallback)
        {
            if (row == null) return fallback;
            JToken token = row[name];
            if (token == null) return fallback;
            double value;
            if (double.TryParse(token.ToString(), NumberStyles.Any, CultureInfo.InvariantCulture, out value))
                return value;
            return fallback;
        }

        private void RequestSnapshotWrite()
        {
            if (!_started) return;
            DateTime now = DateTime.UtcNow;
            int delayMs = 0;
            lock (_gate)
            {
                double elapsed = (now - _lastSnapshotWriteUtc).TotalMilliseconds;
                if (_lastSnapshotWriteUtc == DateTime.MinValue || elapsed >= SnapshotMinIntervalMs)
                {
                    _lastSnapshotWriteUtc = now;
                }
                else
                {
                    if (_snapshotQueued != 0) return;
                    _snapshotQueued = 1;
                    delayMs = Math.Max(20, SnapshotMinIntervalMs - (int)elapsed);
                }
            }
            if (delayMs <= 0)
            {
                WriteSnapshotSafe();
                return;
            }
            ThreadPool.QueueUserWorkItem(delegate
            {
                Thread.Sleep(delayMs);
                if (!_started) return;
                lock (_gate)
                {
                    _snapshotQueued = 0;
                    _lastSnapshotWriteUtc = DateTime.UtcNow;
                }
                WriteSnapshotSafe();
            });
        }

        private void WriteSnapshotSafe()
        {
            try { WriteSnapshot(); }
            catch (Exception ex) { BridgeLog.Error("RuntimeMarketDataExporter snapshot write failed", ex); }
        }

        private void WriteSnapshot()
        {
            JArray rows = new JArray();
            lock (_gate)
            {
                foreach (Subscription sub in _subscriptions.Values.OrderBy(x => x.Key))
                {
                    rows.Add(new JObject
                    {
                        ["key"] = sub.Key, ["instrument"] = sub.Instrument,
                        ["timeframe"] = sub.Timeframe, ["status"] = sub.Status,
                        ["error"] = sub.Error, ["requested_at_utc"] = sub.RequestedAtUtc.ToString("o"),
                        ["updated_at_utc"] = sub.UpdatedAtUtc == default(DateTime) ? null : sub.UpdatedAtUtc.ToString("o"),
                        ["bars"] = sub.Bars == null ? new JArray() : new JArray(sub.Bars),
                    });
                }
            }
            var doc = new JObject
            {
                ["version"] = 1,
                ["generated_at_utc"] = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                ["series"] = rows,
            };
            AtomicFile.WriteAllText(_snapshotPath, doc.ToString(Formatting.None));
        }

        private static void DisposeSubscription(Subscription sub)
        {
            if (sub == null || sub.Request == null) return;
            try
            {
                if (sub.UpdateHandler != null) sub.Request.Update -= sub.UpdateHandler;
            }
            catch { }
            try
            {
                if (sub.MarketData != null && sub.MarketDataHandler != null)
                    sub.MarketData.Update -= sub.MarketDataHandler;
            }
            catch { }
            sub.MarketData = null;
            try { sub.Request.Dispose(); } catch { }
            sub.Request = null;
        }
    }
}
