using System;
using System.IO;
using System.Threading;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.JobQueue
{
    /// <summary>
    /// Polls &lt;runningJobDir&gt;/cancel.flag and signals the supplied
    /// CancellationTokenSource the moment the flag appears. The actual job
    /// transition to cancelled/&lt;id&gt; is owned by JobQueueWatcher.
    /// </summary>
    internal sealed class CancelFlagChecker : IDisposable
    {
        private readonly string _flagPath;
        private readonly int _intervalMs;
        private readonly CancellationTokenSource _cts;
        private readonly System.Threading.Timer _timer;

        public CancelFlagChecker(string runningJobDir, int intervalMs, CancellationTokenSource cts)
        {
            if (string.IsNullOrWhiteSpace(runningJobDir))
                throw new ArgumentNullException(nameof(runningJobDir));
            _flagPath = Path.Combine(runningJobDir, "cancel.flag");
            _intervalMs = Math.Max(500, intervalMs);
            _cts = cts ?? throw new ArgumentNullException(nameof(cts));
            _timer = new System.Threading.Timer(_ => Poll(), null, Timeout.Infinite, Timeout.Infinite);
        }

        public void Start() { _timer.Change(_intervalMs, _intervalMs); }

        public void Dispose()
        {
            try { _timer.Change(Timeout.Infinite, Timeout.Infinite); } catch { }
            try { _timer.Dispose(); } catch { }
        }

        private void Poll()
        {
            try
            {
                if (File.Exists(_flagPath) && !_cts.IsCancellationRequested)
                {
                    BridgeLog.Info("cancel.flag detected at " + _flagPath);
                    _cts.Cancel();
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("cancel.flag poll failed: " + ex.Message);
            }
        }
    }
}
