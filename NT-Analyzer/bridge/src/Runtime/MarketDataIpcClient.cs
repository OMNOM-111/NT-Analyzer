using System;
using System.Globalization;
using System.IO;
using System.Threading;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Runtime.Ipc;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Runtime
{
    /// <summary>
    /// Writer-thread IPC client: drains the bounded queue and streams events
    /// to the localhost backend. Never runs on the MarketData callback thread.
    /// </summary>
    internal sealed class MarketDataIpcClient : IDisposable
    {
        private readonly MarketDataEventQueue _queue;
        private readonly string _runtimeDir;
        private readonly string _transportName;
        private readonly string _host;
        private readonly int _port;
        private readonly string _pipeName;
        private readonly string _wsUrl;
        private readonly int _sourceEpoch;
        private Thread _thread;
        private volatile bool _running;
        private IMarketDataTransport _transport;
        private string _authToken = "";
        private string _connectionId = Guid.NewGuid().ToString("N");
        private long _connectionSequence;
        private long _reconnects;
        private DateTime _lastHeartbeatUtc = DateTime.MinValue;
        private DateTime _lastMetricsWriteUtc = DateTime.MinValue;

        public MarketDataIpcClient(
            MarketDataEventQueue queue,
            string runtimeDir,
            string transportName = "tcp",
            string host = "127.0.0.1",
            int port = 18765,
            string pipeName = @"\\.\pipe\stratforge-market-data",
            string wsUrl = "ws://127.0.0.1:18765/bridge/market-events",
            int sourceEpoch = 1)
        {
            _queue = queue ?? throw new ArgumentNullException(nameof(queue));
            _runtimeDir = runtimeDir;
            _transportName = string.IsNullOrWhiteSpace(transportName) ? "tcp" : transportName;
            _host = string.IsNullOrWhiteSpace(host) ? "127.0.0.1" : host;
            _port = port > 0 ? port : 18765;
            _pipeName = pipeName;
            _wsUrl = wsUrl;
            _sourceEpoch = sourceEpoch > 0 ? sourceEpoch : 1;
        }

        public long Reconnects { get { return Interlocked.Read(ref _reconnects); } }
        public string ConnectionId { get { return _connectionId; } }
        public bool IsConnected { get { return _transport != null && _transport.IsConnected; } }

        private DateTime _lastTickUtc = DateTime.MinValue;
        public int SubscriptionCount { get; set; }
        public string ActiveContracts { get; set; } = "[]";

        public void ForceReconnect()
        {
            BridgeLog.Info("MarketDataIpcClient: ForceReconnect requested.");
            CloseTransport();
        }

        public void Start()
        {
            if (_running) return;
            _running = true;
            _thread = new Thread(WriterLoop) { IsBackground = true, Name = "NTA-MarketDataIpc" };
            _thread.Start();
            BridgeLog.Info("MarketDataIpcClient: started transport=" + _transportName);
        }

        public void Stop()
        {
            _running = false;
            try
            {
                if (_thread != null && _thread.IsAlive)
                    _thread.Join(2000);
            }
            catch { }
            CloseTransport();
            BridgeLog.Info("MarketDataIpcClient: stopped");
        }

        public void Dispose()
        {
            Stop();
        }

        private void WriterLoop()
        {
            while (_running)
            {
                try
                {
                    EnsureConnected();
                    MaybeHeartbeat();
                    MarketDataTick tick;
                    if (!_queue.TryDequeue(out tick, 50))
                    {
                        MaybeWriteMetrics();
                        continue;
                    }
                    long seq = Interlocked.Increment(ref _connectionSequence);
                    string json = tick.ToJsonObject(_connectionId, seq, _sourceEpoch);
                    _transport.SendUtf8(json);
                    _lastTickUtc = DateTime.UtcNow;
                    MaybeWriteMetrics();
                }
                catch (Exception ex)
                {
                    BridgeLog.Warn("MarketDataIpcClient: writer error: " + ex.Message);
                    CloseTransport();
                    Thread.Sleep(500);
                    Interlocked.Increment(ref _reconnects);
                }
            }
            CloseTransport();
        }

        private void EnsureConnected()
        {
            if (_transport != null && _transport.IsConnected) return;
            CloseTransport();
            _authToken = LoadAuthToken();
            if (string.IsNullOrEmpty(_authToken))
                throw new InvalidOperationException("IPC auth token missing in " + TokenPath());
            _connectionId = Guid.NewGuid().ToString("N");
            Interlocked.Exchange(ref _connectionSequence, 0);
            _transport = MarketDataTransportFactory.Create(
                _transportName, _host, _port, _pipeName, _wsUrl);
            _transport.Connect(_authToken, _connectionId, "NTAnalyzerBridge");
            _lastHeartbeatUtc = DateTime.UtcNow;
            BridgeLog.Info("MarketDataIpcClient: connected via " + _transport.Name
                + " connection_id=" + _connectionId);
        }

        private void MaybeHeartbeat()
        {
            if (_transport == null || !_transport.IsConnected) return;
            if ((DateTime.UtcNow - _lastHeartbeatUtc).TotalSeconds < 2.0) return;
            _transport.SendUtf8("{\"type\":\"heartbeat\",\"connection_id\":\""
                + _connectionId + "\",\"client_time_utc\":\""
                + DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture) + "\"}");
            try { _transport.ReceiveUtf8(2000); } catch { /* ack optional under load */ }
            _lastHeartbeatUtc = DateTime.UtcNow;
        }

        private void MaybeWriteMetrics()
        {
            if ((DateTime.UtcNow - _lastMetricsWriteUtc).TotalMilliseconds < 1000) return;
            _lastMetricsWriteUtc = DateTime.UtcNow;
            try
            {
                Directory.CreateDirectory(_runtimeDir);
                string path = Path.Combine(_runtimeDir, "market_data_ipc_bridge_metrics.json");
                string json = "{"
                    + "\"generated_at_utc\":\"" + DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture) + "\","
                    + "\"transport\":\"" + _transportName + "\","
                    + "\"connection_id\":\"" + _connectionId + "\","
                    + "\"reconnects\":" + Reconnects + ","
                    + "\"connected\":" + (IsConnected ? "true" : "false") + ","
                    + "\"last_tick_at_utc\":\"" + (_lastTickUtc == DateTime.MinValue ? "" : _lastTickUtc.ToString("o", CultureInfo.InvariantCulture)) + "\","
                    + "\"subscription_count\":" + SubscriptionCount + ","
                    + "\"active_contracts\":" + (string.IsNullOrEmpty(ActiveContracts) ? "[]" : ActiveContracts) + ","
                    + "\"queue\":" + _queue.MetricsJson()
                    + "}";
                AtomicFile.WriteAllText(path, json);
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("MarketDataIpcClient: metrics write failed: " + ex.Message);
            }
        }

        private string TokenPath()
        {
            return Path.Combine(_runtimeDir, "market_data_ipc_token.json");
        }

        private string LoadAuthToken()
        {
            string path = TokenPath();
            if (!File.Exists(path)) return "";
            try
            {
                JObject doc = JObject.Parse(File.ReadAllText(path));
                return ((string)doc["token"] ?? "").Trim();
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("MarketDataIpcClient: token unreadable: " + ex.Message);
                return "";
            }
        }

        private void CloseTransport()
        {
            try
            {
                if (_transport != null) _transport.CloseGracefully();
            }
            catch { }
            try
            {
                if (_transport != null) _transport.Dispose();
            }
            catch { }
            _transport = null;
        }
    }
}
