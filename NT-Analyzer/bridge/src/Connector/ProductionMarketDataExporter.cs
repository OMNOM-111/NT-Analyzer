using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading;

using Newtonsoft.Json.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Connector
{
    /// <summary>
    /// Read-only Production Connector bar source. It is configured locally,
    /// has no server-driven stream selection, and never uses development IPC.
    /// </summary>
    internal sealed class ProductionMarketDataExporter
    {
        private const int MaxBarsPerBatch = 64;
        private const int MaxQueuedBatches = 32;
        private const int MinimumCaptureIntervalMs = 1000;

        private readonly List<ProductionMarketDataStreamConfig> _configured;
        private readonly Func<JArray, bool> _queueConnectorBatch;
        private readonly object _subscriptionsGate = new object();
        private readonly List<Subscription> _subscriptions = new List<Subscription>();
        private readonly object _pendingGate = new object();
        private readonly Queue<PendingBatch> _pending = new Queue<PendingBatch>();
        private readonly AutoResetEvent _pendingSignal = new AutoResetEvent(false);

        private Thread _sender;
        private volatile bool _running;
        private long _droppedBatches;

        private sealed class Subscription
        {
            public readonly object Gate = new object();
            public ProductionMarketDataStreamConfig Config;
            public BarsRequest Request;
            public EventHandler<BarsUpdateEventArgs> UpdateHandler;
            public DateTime LastCaptureUtc;
        }

        private sealed class BarSample
        {
            public string Timestamp;
            public double Open;
            public double High;
            public double Low;
            public double Close;
            public long Volume;
        }

        private sealed class PendingBatch
        {
            public ProductionMarketDataStreamConfig Config;
            public List<BarSample> Bars;
        }

        public ProductionMarketDataExporter(
            IEnumerable<ProductionMarketDataStreamConfig> streams,
            Func<JArray, bool> queueConnectorBatch)
        {
            _configured = (streams ?? Enumerable.Empty<ProductionMarketDataStreamConfig>()).ToList();
            _queueConnectorBatch = queueConnectorBatch ??
                throw new ArgumentNullException(nameof(queueConnectorBatch));
        }

        public void Start()
        {
            if (_running) return;
            _running = true;
            _sender = new Thread(SenderLoop)
            {
                IsBackground = true,
                Name = "StratForgeProductionBars",
            };
            _sender.Start();
            foreach (ProductionMarketDataStreamConfig stream in _configured)
                StartSubscription(stream);
            BridgeLog.Info("ProductionMarketDataExporter: started streams=" + _configured.Count);
        }

        public void Stop()
        {
            _running = false;
            _pendingSignal.Set();
            try
            {
                if (_sender != null && _sender.IsAlive) _sender.Join(2000);
            }
            catch { }
            _sender = null;

            List<Subscription> subscriptions;
            lock (_subscriptionsGate)
            {
                subscriptions = _subscriptions.ToList();
                _subscriptions.Clear();
            }
            foreach (Subscription subscription in subscriptions) DisposeSubscription(subscription);
            BridgeLog.Info(
                "ProductionMarketDataExporter: stopped dropped=" +
                Interlocked.Read(ref _droppedBatches));
        }

        private void StartSubscription(ProductionMarketDataStreamConfig stream)
        {
            try
            {
                Instrument instrument = Instrument.GetInstrument(stream.ExactContract);
                if (instrument == null)
                    throw new InvalidOperationException(
                        "NinjaTrader instrument not found: " + stream.ExactContract);
                BarsRequest request = new BarsRequest(instrument, MaxBarsPerBatch);
                request.BarsPeriod = ParseBarsPeriod(stream.Timeframe);
                try { request.TradingHours = TradingHours.Get("Default 24 x 7"); }
                catch { }

                var subscription = new Subscription { Config = stream, Request = request };
                subscription.UpdateHandler = (sender, args) => Capture(subscription, false);
                request.Update += subscription.UpdateHandler;
                lock (_subscriptionsGate) _subscriptions.Add(subscription);
                request.Request(new Action<BarsRequest, ErrorCode, string>((bars, code, message) =>
                {
                    if (code != ErrorCode.NoError)
                    {
                        BridgeLog.Warn("ProductionMarketDataExporter: request failed " + code);
                        return;
                    }
                    Capture(subscription, true);
                }));
                BridgeLog.Info(
                    "ProductionMarketDataExporter: subscribed " +
                    stream.ExactContract + " " + stream.Timeframe);
            }
            catch (Exception ex)
            {
                BridgeLog.Warn(
                    "ProductionMarketDataExporter: subscription failed " +
                    ex.GetType().Name);
            }
        }

        /// <summary>
        /// NinjaTrader callback path: copy a capped primitive snapshot and
        /// return. JSON construction and Connector enqueue happen on sender.
        /// </summary>
        private void Capture(Subscription subscription, bool force)
        {
            if (!_running || subscription == null || subscription.Request == null) return;
            Bars bars = subscription.Request.Bars;
            if (bars == null) return;
            DateTime now = DateTime.UtcNow;
            lock (subscription.Gate)
            {
                if (!force &&
                    (now - subscription.LastCaptureUtc).TotalMilliseconds < MinimumCaptureIntervalMs)
                    return;
                subscription.LastCaptureUtc = now;
            }

            List<BarSample> samples;
            try
            {
                int count = bars.Count;
                if (count < 1) return;
                int start = Math.Max(0, count - MaxBarsPerBatch);
                samples = new List<BarSample>(count - start);
                for (int index = start; index < count; index++)
                {
                    double open = bars.GetOpen(index);
                    double high = bars.GetHigh(index);
                    double low = bars.GetLow(index);
                    double close = bars.GetClose(index);
                    if (!IsValidOhlc(open, high, low, close)) continue;
                    long volume;
                    try { volume = Math.Max(0L, Convert.ToInt64(bars.GetVolume(index))); }
                    catch { continue; }
                    samples.Add(new BarSample
                    {
                        Timestamp = bars.GetTime(index).ToUniversalTime().ToString(
                            "o", CultureInfo.InvariantCulture),
                        Open = open,
                        High = high,
                        Low = low,
                        Close = close,
                        Volume = volume,
                    });
                }
            }
            catch { return; }

            if (samples.Count > 0)
                QueuePending(new PendingBatch { Config = subscription.Config, Bars = samples });
        }

        private void QueuePending(PendingBatch batch)
        {
            if (!_running || batch == null || batch.Bars == null || batch.Bars.Count == 0) return;
            lock (_pendingGate)
            {
                if (_pending.Count >= MaxQueuedBatches)
                {
                    _pending.Dequeue();
                    Interlocked.Increment(ref _droppedBatches);
                }
                _pending.Enqueue(batch);
            }
            try { _pendingSignal.Set(); }
            catch { }
        }

        private void SenderLoop()
        {
            while (_running)
            {
                _pendingSignal.WaitOne(250);
                while (_running)
                {
                    PendingBatch batch;
                    lock (_pendingGate)
                    {
                        if (_pending.Count == 0) break;
                        batch = _pending.Dequeue();
                    }
                    try
                    {
                        if (!_queueConnectorBatch(ToPayload(batch)))
                            Interlocked.Increment(ref _droppedBatches);
                    }
                    catch
                    {
                        Interlocked.Increment(ref _droppedBatches);
                    }
                }
            }
        }

        private static JArray ToPayload(PendingBatch batch)
        {
            var rows = new JArray();
            foreach (BarSample bar in batch.Bars.Take(MaxBarsPerBatch))
            {
                rows.Add(new JObject
                {
                    ["timestamp"] = bar.Timestamp,
                    ["open"] = bar.Open,
                    ["high"] = bar.High,
                    ["low"] = bar.Low,
                    ["close"] = bar.Close,
                    ["volume"] = bar.Volume,
                    ["exact_contract"] = batch.Config.ExactContract,
                    ["timeframe"] = batch.Config.Timeframe,
                });
            }
            return rows;
        }

        private static bool IsValidOhlc(double open, double high, double low, double close)
        {
            return !double.IsNaN(open) && !double.IsNaN(high) &&
                !double.IsNaN(low) && !double.IsNaN(close) &&
                !double.IsInfinity(open) && !double.IsInfinity(high) &&
                !double.IsInfinity(low) && !double.IsInfinity(close) &&
                high >= low && open >= low && open <= high &&
                close >= low && close <= high;
        }

        private static BarsPeriod ParseBarsPeriod(string timeframe)
        {
            string value = (timeframe ?? "").Trim().ToLowerInvariant();
            if (value == "1d")
                return new BarsPeriod { BarsPeriodType = BarsPeriodType.Day, Value = 1 };
            int amount;
            if (value.EndsWith("h") &&
                int.TryParse(value.Substring(0, value.Length - 1), out amount))
                return new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = amount * 60 };
            if (value.EndsWith("m") &&
                int.TryParse(value.Substring(0, value.Length - 1), out amount))
                return new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = amount };
            throw new InvalidOperationException("Invalid configured production market-data timeframe.");
        }

        private static void DisposeSubscription(Subscription subscription)
        {
            if (subscription == null || subscription.Request == null) return;
            try
            {
                if (subscription.UpdateHandler != null)
                    subscription.Request.Update -= subscription.UpdateHandler;
            }
            catch { }
            try { subscription.Request.Dispose(); }
            catch { }
            subscription.Request = null;
        }
    }
}