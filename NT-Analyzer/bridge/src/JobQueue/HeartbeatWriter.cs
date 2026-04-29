using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.JobQueue
{
    /// <summary>
    /// Periodically refreshes &lt;runningJobDir&gt;/heartbeat.json via
    /// write-temp-then-rename. Runs on a background timer so the watcher
    /// thread stays free to drive the actual job.
    /// </summary>
    internal sealed class HeartbeatWriter
    {
        private readonly string _runningJobDir;
        private readonly int _intervalMs;
        private readonly System.Threading.Timer _timer;
        // 0 = idle, 1 = beat in progress. Prevents the timer from firing
        // a second Beat() while AtomicFile.WriteAllText still holds
        // heartbeat.json.tmp open from the previous tick.
        private int _beatInFlight;

        public HeartbeatWriter(string runningJobDir, int intervalMs)
        {
            _runningJobDir = runningJobDir ?? throw new ArgumentNullException(nameof(runningJobDir));
            _intervalMs = Math.Max(500, intervalMs);
            _timer = new System.Threading.Timer(_ => Beat(), null, Timeout.Infinite, Timeout.Infinite);
        }

        public void Start() { _timer.Change(_intervalMs, _intervalMs); }

        public void Stop()
        {
            try { _timer.Change(Timeout.Infinite, Timeout.Infinite); } catch { }
            try { _timer.Dispose(); } catch { }
        }

        private void Beat()
        {
            // Skip this tick if the previous Beat() is still running.
            if (Interlocked.CompareExchange(ref _beatInFlight, 1, 0) != 0) return;
            try
            {
                if (!Directory.Exists(_runningJobDir)) return;
                var hb = new JObject
                {
                    ["schema_version"]  = "0.1",
                    ["pid"]             = Process.GetCurrentProcess().Id,
                    ["process_name"]    = Process.GetCurrentProcess().ProcessName,
                    ["host"]            = Environment.MachineName,
                    ["updated_at_utc"]  = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
                };
                AtomicFile.WriteAllText(Path.Combine(_runningJobDir, "heartbeat.json"),
                    hb.ToString(Formatting.Indented));
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("heartbeat write failed: " + ex.Message);
            }
            finally
            {
                Interlocked.Exchange(ref _beatInFlight, 0);
            }
        }
    }
}
