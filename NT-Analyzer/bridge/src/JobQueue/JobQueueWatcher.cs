using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Execution;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.JobQueue
{
    /// <summary>
    /// Single-threaded queue watcher. One claimed job at a time
    /// (parallel runs are forbidden for one NinjaTrader bridge instance).
    ///
    /// Lifecycle for one claimed job:
    ///   1. Directory.Move pending/&lt;id&gt; -> running/&lt;id&gt;
    ///   2. write heartbeat.json (PID, process name)
    ///   3. periodically refresh heartbeat + check cancel.flag
    ///   4. delegate the actual run to IHistoricalRunner
    ///   5. Directory.Move running/&lt;id&gt; -> done|failed|cancelled
    ///
    /// On startup it also recovers stale running/&lt;id&gt; folders whose
    /// heartbeat is missing or expired.
    /// </summary>
    internal sealed class JobQueueWatcher
    {
        private readonly BridgeConfig _cfg;
        private readonly StrategyLoader _strategyLoader;
        private readonly IHistoricalRunner _runner;
        private readonly System.Threading.Timer _pollTimer;
        private readonly object _gate = new object();
        private bool _busy;
        private bool _stopped;

        public JobQueueWatcher(BridgeConfig cfg, StrategyLoader strategyLoader, IHistoricalRunner runner)
        {
            _cfg = cfg ?? throw new ArgumentNullException(nameof(cfg));
            _strategyLoader = strategyLoader ?? throw new ArgumentNullException(nameof(strategyLoader));
            _runner = runner ?? throw new ArgumentNullException(nameof(runner));
            _pollTimer = new System.Threading.Timer(_ => Tick(), null, Timeout.Infinite, Timeout.Infinite);
        }

        public void Start()
        {
            EnsureQueueLayout();
            RecoverStaleRunning();
            _pollTimer.Change(0, _cfg.PollIntervalMs);
            BridgeLog.Info("Queue watcher started, project_root=" + _cfg.ProjectRoot);
        }

        public void Stop()
        {
            _stopped = true;
            try { _pollTimer.Change(Timeout.Infinite, Timeout.Infinite); } catch { }
            try { _pollTimer.Dispose(); } catch { }
            BridgeLog.Info("Queue watcher stopped");
        }

        private void EnsureQueueLayout()
        {
            foreach (var d in new[] { _cfg.PendingDir, _cfg.PendingStaging, _cfg.RunningDir,
                                      _cfg.DoneDir, _cfg.FailedDir, _cfg.CancelledDir })
            {
                try { Directory.CreateDirectory(d); }
                catch (Exception ex) { BridgeLog.Error("cannot create queue dir " + d, ex); }
            }
        }

        private void Tick()
        {
            if (_stopped) return;
            // Re-entrancy guard: only one job at a time.
            lock (_gate)
            {
                if (_busy) return;
                _busy = true;
            }
            try
            {
                ProcessOne();
            }
            catch (Exception ex)
            {
                BridgeLog.Error("watcher tick failed", ex);
            }
            finally
            {
                lock (_gate) { _busy = false; }
            }
        }

        private void ProcessOne()
        {
            string pendingJobDir = FindNextPendingJob();
            if (pendingJobDir == null) return;

            string jobId = Path.GetFileName(pendingJobDir);
            string runningJobDir = Path.Combine(_cfg.RunningDir, jobId);

            // Atomic claim. If it fails (e.g. another instance grabbed it,
            // or the directory disappeared), just skip.
            try
            {
                Directory.Move(pendingJobDir, runningJobDir);
            }
            catch (Exception ex)
            {
                BridgeLog.Info("claim skipped for " + jobId + ": " + ex.Message);
                return;
            }

            BridgeLog.Info("claimed job " + jobId);

            HeartbeatWriter heartbeat = null;
            CancellationTokenSource cts = null;
            try
            {
                WriteHeartbeat(runningJobDir); // initial beat
                heartbeat = new HeartbeatWriter(runningJobDir, _cfg.HeartbeatIntervalMs);
                heartbeat.Start();

                cts = new CancellationTokenSource();
                using (var cancelChecker = new CancelFlagChecker(runningJobDir, _cfg.HeartbeatIntervalMs, cts))
                {
                    cancelChecker.Start();

                    JobRunOutcome outcome = ExecuteJob(jobId, runningJobDir, cts.Token);

                    if (cts.IsCancellationRequested && outcome.Status != JobStatus.Cancelled)
                        outcome = JobRunOutcome.Cancelled("cancelled by user");

                    try { heartbeat?.Stop(); heartbeat = null; } catch { }
                    Finalize(jobId, runningJobDir, outcome);
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Error("job " + jobId + " failed unexpectedly", ex);
                try
                {
                    try { heartbeat?.Stop(); heartbeat = null; } catch { }
                    Finalize(jobId, runningJobDir, JobRunOutcome.Failed("unhandled_exception", ex.ToString()));
                }
                catch (Exception ex2)
                {
                    BridgeLog.Error("failed to finalize job " + jobId + " after error", ex2);
                }
            }
            finally
            {
                try { heartbeat?.Stop(); } catch { }
                try { cts?.Dispose(); } catch { }
            }
        }

        private string FindNextPendingJob()
        {
            IEnumerable<string> dirs;
            try
            {
                dirs = Directory.EnumerateDirectories(_cfg.PendingDir);
            }
            catch (Exception ex)
            {
                BridgeLog.Error("cannot enumerate pending/", ex);
                return null;
            }

            // Skip .staging and only accept dirs that already contain job.json.
            return dirs
                .Where(d => !string.Equals(Path.GetFileName(d), ".staging", StringComparison.Ordinal))
                .Where(d => !Path.GetFileName(d).StartsWith(".", StringComparison.Ordinal))
                .Where(d => File.Exists(Path.Combine(d, "job.json")))
                .OrderBy(d => Directory.GetCreationTimeUtc(d))
                .FirstOrDefault();
        }

        private JobRunOutcome ExecuteJob(string jobId, string runningJobDir, CancellationToken ct)
        {
            string jobJsonPath = Path.Combine(runningJobDir, "job.json");
            JObject job;
            try
            {
                job = JObject.Parse(File.ReadAllText(jobJsonPath));
            }
            catch (Exception ex)
            {
                return JobRunOutcome.Failed("invalid_job_json", ex.Message);
            }

            string className = (string)job.SelectToken("strategy.class_name");
            if (string.IsNullOrWhiteSpace(className))
                return JobRunOutcome.Failed("missing_class_name", "strategy.class_name is required");

            Type strategyType;
            try
            {
                strategyType = _strategyLoader.Resolve(className);
            }
            catch (Exception ex)
            {
                return JobRunOutcome.Failed("strategy_whitelist_error", ex.Message);
            }
            if (strategyType == null)
            {
                return JobRunOutcome.Failed(
                    "strategy_not_whitelisted",
                    "class '" + className + "' not found in NinjaTrader.Custom whitelist");
            }

            BridgeLog.Info("job " + jobId + " resolved strategy " + strategyType.FullName);

            return _runner.Run(jobId, job, strategyType, runningJobDir, ct);
        }

        private void Finalize(string jobId, string runningJobDir, JobRunOutcome outcome)
        {
            string targetParent;
            switch (outcome.Status)
            {
                case JobStatus.Done:      targetParent = _cfg.DoneDir;      break;
                case JobStatus.Cancelled: targetParent = _cfg.CancelledDir; break;
                case JobStatus.Failed:
                default:                  targetParent = _cfg.FailedDir;    break;
            }

            // Per docs/job-schema.md the cancel path must yield a partial
            // result.json with verification_warnings: ["cancelled by user"],
            // not an error.json. error.json is only written on failure.
            try
            {
                if (outcome.Status == JobStatus.Cancelled)
                {
                    var res = new JObject
                    {
                        ["schema_version"]   = "0.1",
                        ["job_id"]           = jobId,
                        ["finished_at_utc"]  = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                        ["status"]           = "cancelled",
                        ["verification_warnings"] = new JArray(
                            outcome.Message ?? "cancelled by user"
                        ),
                        ["trades"]           = new JArray(),
                        ["metrics"]          = new JObject()
                    };
                    AtomicFile.WriteAllText(Path.Combine(runningJobDir, "result.json"),
                        res.ToString(Formatting.Indented));
                }
                else if (outcome.Status == JobStatus.Failed)
                {
                    var err = new JObject
                    {
                        ["schema_version"]  = "0.1",
                        ["job_id"]          = jobId,
                        ["finished_at_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                        ["error_type"]      = outcome.ErrorType ?? "unknown",
                        ["message"]         = outcome.Message ?? string.Empty
                    };
                    AtomicFile.WriteAllText(Path.Combine(runningJobDir, "error.json"),
                        err.ToString(Formatting.Indented));
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Error("failed to write terminal status file for " + jobId, ex);
            }

            try
            {
                Directory.CreateDirectory(targetParent);
                string finalDir = ResolveUniqueTerminalDir(targetParent, jobId);
                Directory.Move(runningJobDir, finalDir);
                BridgeLog.Info("job " + jobId + " -> " + outcome.Status + " (" +
                               (outcome.ErrorType ?? "ok") + ") at " + Path.GetFileName(finalDir));
                AppendVitekJobEvent(jobId, outcome, finalDir);
            }
            catch (Exception ex)
            {
                // Last-resort quarantine: never leave the job stuck in running/.
                BridgeLog.Error("Directory.Move failed for " + jobId +
                                " — moving to failed/.quarantine", ex);
                try
                {
                    string quarantine = Path.Combine(_cfg.FailedDir, ".quarantine");
                    Directory.CreateDirectory(quarantine);
                    string qDir = ResolveUniqueTerminalDir(quarantine, jobId);
                    Directory.Move(runningJobDir, qDir);
                    BridgeLog.Warn("job " + jobId + " quarantined at " + qDir);
                }
                catch (Exception ex2)
                {
                    BridgeLog.Error("quarantine also failed for " + jobId +
                                    " — job remains in running/", ex2);
                }
            }
        }

        private void AppendVitekJobEvent(string jobId, JobRunOutcome outcome, string finalDir)
        {
            try
            {
                string eventType = outcome.Status == JobStatus.Done ? "job_completed"
                    : outcome.Status == JobStatus.Cancelled ? "job_cancelled" : "job_failed";
                var signal = new JObject
                {
                    ["event_type"] = eventType,
                    ["source"] = "ninjatrader_bridge",
                    ["severity"] = outcome.Status == JobStatus.Failed ? "critical" : "info",
                    ["payload"] = new JObject
                    {
                        ["job_id"] = jobId,
                        ["status"] = outcome.Status.ToString().ToLowerInvariant(),
                        ["error_type"] = outcome.ErrorType ?? string.Empty,
                        ["message"] = outcome.Message ?? string.Empty,
                        ["terminal_dir"] = finalDir ?? string.Empty
                    }
                };
                Directory.CreateDirectory(_cfg.RuntimeDataDir);
                File.AppendAllText(
                    Path.Combine(_cfg.RuntimeDataDir, "vitek_events.jsonl"),
                    signal.ToString(Formatting.None) + Environment.NewLine,
                    Encoding.UTF8
                );
            }
            catch (Exception ex)
            {
                BridgeLog.Error("failed to signal Vitek for job " + jobId, ex);
            }
        }

        /// <summary>
        /// If a terminal folder for this job_id already exists (e.g. user
        /// re-enqueued the same id during smoke-tests), append a UTC
        /// timestamp suffix instead of failing. State machine guarantees
        /// only that the job leaves running/ — uniqueness inside terminal
        /// folders is best-effort.
        /// </summary>
        private static string ResolveUniqueTerminalDir(string parent, string jobId)
        {
            string candidate = Path.Combine(parent, jobId);
            if (!Directory.Exists(candidate) && !File.Exists(candidate))
                return candidate;

            string suffix = DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffZ");
            for (int i = 0; i < 100; i++)
            {
                string s = i == 0 ? suffix : suffix + "_" + i;
                string c = Path.Combine(parent, jobId + "__" + s);
                if (!Directory.Exists(c) && !File.Exists(c))
                    return c;
            }
            // extremely unlikely; let Directory.Move throw a meaningful error
            return Path.Combine(parent, jobId + "__" + Guid.NewGuid().ToString("N"));
        }

        private void WriteHeartbeat(string runningJobDir)
        {
            var hb = new JObject
            {
                ["schema_version"] = "0.1",
                ["pid"]           = Process.GetCurrentProcess().Id,
                ["process_name"]  = Process.GetCurrentProcess().ProcessName,
                ["host"]          = Environment.MachineName,
                ["updated_at_utc"]= DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
            };
            AtomicFile.WriteAllText(Path.Combine(runningJobDir, "heartbeat.json"),
                hb.ToString(Formatting.Indented));
        }

        private void RecoverStaleRunning()
        {
            string[] dirs;
            try { dirs = Directory.GetDirectories(_cfg.RunningDir); }
            catch (Exception ex) { BridgeLog.Error("cannot enumerate running/", ex); return; }

            int myPid = Process.GetCurrentProcess().Id;

            foreach (var d in dirs)
            {
                string jobId = Path.GetFileName(d);
                string hbPath = Path.Combine(d, "heartbeat.json");

                bool stale = true;
                int? otherPid = null;
                try
                {
                    if (File.Exists(hbPath))
                    {
                        var hb = JObject.Parse(File.ReadAllText(hbPath));
                        otherPid = (int?)hb["pid"];
                        DateTime? updated = (DateTime?)hb["updated_at_utc"];
                        if (otherPid.HasValue && otherPid.Value != myPid && IsProcessAlive(otherPid.Value))
                        {
                            stale = false;
                        }
                        else if (updated.HasValue &&
                                 (DateTime.UtcNow - updated.Value).TotalMilliseconds < _cfg.HeartbeatTtlMs)
                        {
                            stale = false;
                        }
                    }
                }
                catch (Exception ex)
                {
                    BridgeLog.Warn("cannot parse heartbeat for " + jobId + ": " + ex.Message);
                }

                if (!stale)
                {
                    BridgeLog.Info("running/" + jobId + " owned by alive pid " +
                                   (otherPid?.ToString() ?? "?") + " — leaving alone");
                    continue;
                }

                BridgeLog.Warn("running/" + jobId + " is stale - recovering as failed");
                try
                {
                    var err = new JObject
                    {
                        ["schema_version"]  = "0.1",
                        ["job_id"]          = jobId,
                        ["finished_at_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                        ["error_type"]      = "stale_running_recovered",
                        ["message"]         = "no live heartbeat at AddOn startup"
                    };
                    AtomicFile.WriteAllText(Path.Combine(d, "error.json"),
                        err.ToString(Formatting.Indented));

                    Directory.CreateDirectory(_cfg.FailedDir);
                    string finalDir = ResolveUniqueTerminalDir(_cfg.FailedDir, jobId);
                    Directory.Move(d, finalDir);
                    BridgeLog.Info("recovered stale running/" + jobId + " -> failed/" + Path.GetFileName(finalDir));
                }
                catch (Exception ex)
                {
                    BridgeLog.Error("recovery failed for " + jobId +
                                    " - attempting quarantine", ex);
                    try
                    {
                        string quarantine = Path.Combine(_cfg.FailedDir, ".quarantine");
                        Directory.CreateDirectory(quarantine);
                        string qDir = ResolveUniqueTerminalDir(quarantine, jobId);
                        Directory.Move(d, qDir);
                        BridgeLog.Warn("stale job " + jobId + " quarantined at " + qDir);
                    }
                    catch (Exception ex2)
                    {
                        BridgeLog.Error("quarantine of stale " + jobId +
                                        " also failed - job remains in running/", ex2);
                    }
                }
            }
        }

        private static bool IsProcessAlive(int pid)
        {
            try
            {
                var p = Process.GetProcessById(pid);
                return p != null && !p.HasExited;
            }
            catch { return false; }
        }
    }
}
