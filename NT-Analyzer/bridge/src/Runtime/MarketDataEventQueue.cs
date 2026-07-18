using System;
using System.Threading;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Runtime
{
    /// <summary>
    /// Bounded non-blocking queue for MarketData callbacks.
    /// Drop-oldest under backpressure; never blocks the NT UI thread.
    /// </summary>
    internal sealed class MarketDataEventQueue
    {
        private readonly MarketDataTick[] _buffer;
        private readonly object _gate = new object();
        private int _head;
        private int _tail;
        private int _count;
        private long _enqueued;
        private long _dequeued;
        private long _dropped;
        private long _generatedSequence;

        public MarketDataEventQueue(int capacity = 8192)
        {
            if (capacity < 16) capacity = 16;
            _buffer = new MarketDataTick[capacity];
        }

        public int Capacity { get { return _buffer.Length; } }
        public int Depth { get { lock (_gate) return _count; } }
        public long Enqueued { get { return Interlocked.Read(ref _enqueued); } }
        public long Dequeued { get { return Interlocked.Read(ref _dequeued); } }
        public long Dropped { get { return Interlocked.Read(ref _dropped); } }

        public long NextGeneratedSequence()
        {
            return Interlocked.Increment(ref _generatedSequence);
        }

        /// <summary>Non-blocking enqueue. Returns false if the tick was dropped.</summary>
        public bool TryEnqueue(MarketDataTick tick)
        {
            lock (_gate)
            {
                if (_count == _buffer.Length)
                {
                    // Drop oldest to relieve backpressure.
                    _head = (_head + 1) % _buffer.Length;
                    _count--;
                    Interlocked.Increment(ref _dropped);
                }
                _buffer[_tail] = tick;
                _tail = (_tail + 1) % _buffer.Length;
                _count++;
                Interlocked.Increment(ref _enqueued);
                Monitor.Pulse(_gate);
                return true;
            }
        }

        public bool TryDequeue(out MarketDataTick tick, int waitMs)
        {
            lock (_gate)
            {
                if (_count == 0)
                {
                    if (waitMs > 0) Monitor.Wait(_gate, waitMs);
                    if (_count == 0)
                    {
                        tick = default(MarketDataTick);
                        return false;
                    }
                }
                tick = _buffer[_head];
                _head = (_head + 1) % _buffer.Length;
                _count--;
                Interlocked.Increment(ref _dequeued);
                return true;
            }
        }

        public string MetricsJson()
        {
            return "{\"queue_depth\":" + Depth
                + ",\"queue_capacity\":" + Capacity
                + ",\"enqueued\":" + Enqueued
                + ",\"dequeued\":" + Dequeued
                + ",\"dropped\":" + Dropped
                + "}";
        }
    }
}
