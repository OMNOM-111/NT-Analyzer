using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Execution;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Runtime
{
    /// <summary>
    /// Runs a server-dispatched backtest without holding up the command loop.
    ///
    /// A Strategy Analyzer run takes seconds to minutes. Executing it inline
    /// would block the consumer that reads commands, so the one command an
    /// operator needs most while a run is going -- cancel -- could not be read
    /// until the run they wanted to stop had finished on its own.
    ///
    /// So a run is started on a background task and the command loop returns
    /// immediately. One run at a time per installation: the Strategy Analyzer
    /// is not safe to drive concurrently, and inventing concurrency to look
    /// faster would produce results that cannot be trusted. A second request
    /// while one is active is answered as busy rather than queued silently.
    /// </summary>
    internal sealed class ConnectorBacktestExecutor
    {
        internal delegate void ResultWriter(
            string commandId, string status, string message, string safeResultJson);

        private sealed class ActiveRun
        {
            public string JobId;
            public string CommandId;
            public CancellationTokenSource Cancellation;
            public Task Execution;
            public DateTime StartedUtc;
            public volatile bool CancelRequested;
            // Opaque, per-start, and meaningless outside this process. It ties
            // "the run the cancel found" to "the run that produced the result"
            // -- without it, a registry hit and a completed result cannot be
            // shown to belong to the same execution.
            public string ExecutionInstanceId;
        }

        private readonly BridgeConfig _cfg;
        private readonly ResultWriter _writeResult;
        private readonly object _gate = new object();
        private readonly Dictionary<string, ActiveRun> _active =
            new Dictionary<string, ActiveRun>(StringComparer.Ordinal);
        private readonly HashSet<string> _finished =
            new HashSet<string>(StringComparer.Ordinal);

        private StrategyLoader _loader;
        private StrategyAnalyzerRunner _runner;
        private volatile bool _stopping;

        // The result channel is 16 KiB. Bounding here, before anything is
        // sent, is what keeps a large but successful backtest from becoming a
        // transport error -- and the counts travel separately so a truncated
        // list is never mistaken for the whole run.
        private const int MaxTransferredTrades = 150;
        private const int MaxSafeResultBytes = 15 * 1024;

        public ConnectorBacktestExecutor(BridgeConfig cfg, ResultWriter writeResult)
        {
            _cfg = cfg;
            _writeResult = writeResult;
        }

        public void Stop()
        {
            _stopping = true;
            List<ActiveRun> running;
            lock (_gate) { running = _active.Values.ToList(); }
            foreach (ActiveRun run in running)
            {
                try { run.Cancellation.Cancel(); }
                catch (Exception ex) { BridgeLog.Warn("backtest cancel on stop: " + ex.GetType().Name); }
            }
            foreach (ActiveRun run in running)
            {
                try { run.Execution?.Wait(TimeSpan.FromSeconds(20)); }
                catch (Exception ex) { BridgeLog.Warn("backtest drain on stop: " + ex.GetType().Name); }
            }
        }

        // ------------------------------------------------------------------
        // run_backtest
        // ------------------------------------------------------------------
        public void Start(string commandId, JObject job)
        {
            string jobId = (string)(job?["job_id"]) ?? "";
            if (string.IsNullOrWhiteSpace(jobId))
            {
                _writeResult(commandId, "rejected", "backtest job_id missing", null);
                return;
            }
            if (_stopping)
            {
                _writeResult(commandId, "rejected", "connector is shutting down", null);
                return;
            }

            lock (_gate)
            {
                if (_active.ContainsKey(jobId))
                {
                    // The same job arriving twice is a redelivery, not a second
                    // run. Starting it again would put two Strategy Analyzer
                    // sessions on the same strategy.
                    _writeResult(commandId, "accepted",
                        "backtest already running for this job", null);
                    return;
                }
                if (_finished.Contains(jobId))
                {
                    _writeResult(commandId, "accepted",
                        "backtest already completed for this job", null);
                    return;
                }
                if (_active.Count > 0)
                {
                    _writeResult(commandId, "rejected",
                        "another backtest is already running on this installation",
                        null);
                    return;
                }
            }

            Type strategyType;
            string resolveError;
            if (!TryResolveStrategy(job, out strategyType, out resolveError))
            {
                _writeResult(commandId, "rejected", resolveError, null);
                return;
            }

            ActiveRun record = new ActiveRun
            {
                JobId = jobId,
                CommandId = commandId,
                Cancellation = new CancellationTokenSource(),
                StartedUtc = DateTime.UtcNow,
                ExecutionInstanceId = Guid.NewGuid().ToString("N").Substring(0, 16),
            };
            lock (_gate) { _active[jobId] = record; }

            record.Execution = Task.Factory.StartNew(
                () => Execute(record, job, strategyType),
                record.Cancellation.Token,
                TaskCreationOptions.LongRunning,
                TaskScheduler.Default);
        }

        private bool TryResolveStrategy(JObject job, out Type strategyType, out string error)
        {
            strategyType = null;
            error = "";
            string className = (string)(job?["strategy"]?["class_name"]) ?? "";
            try
            {
                EnsureRunner();
                // Resolved only through the loader's whitelist. A name the
                // catalog does not know is refused here, so the command cannot
                // be used to reach an arbitrary type.
                strategyType = _loader.Resolve(className);
            }
            catch (Exception ex)
            {
                error = "strategy resolve failed: " + ex.GetType().Name;
                return false;
            }
            if (strategyType == null)
            {
                error = "strategy is not whitelisted: " + Truncate(className, 80);
                return false;
            }
            return true;
        }

        private void EnsureRunner()
        {
            lock (_gate)
            {
                if (_loader == null)
                {
                    _loader = new StrategyLoader(_cfg.NinjaTraderUserDir);
                    _loader.Refresh();
                }
                if (_runner == null)
                    _runner = new StrategyAnalyzerRunner(_loader, _cfg);
            }
        }

        private void Execute(ActiveRun record, JObject job, Type strategyType)
        {
            string workDir = Path.Combine(
                _cfg.RuntimeDataDir, "server-backtests", record.JobId);
            try
            {
                Directory.CreateDirectory(workDir);

                // Boundary 0. A cancel that arrived between dispatch and the
                // first line of work costs nothing to honour.
                bool cancelSeenBeforeRun = record.Cancellation.IsCancellationRequested;
                if (cancelSeenBeforeRun)
                {
                    _writeResult(record.CommandId, "cancelled",
                        "cancelled before the run started",
                        Diagnostics(record, null, true, true)
                            .ToString(Formatting.None));
                    return;
                }

                // Reported only now: the run is genuinely under way, so the
                // canonical job moves to running only when it is true.
                _writeResult(record.CommandId, "running",
                    "strategy analyzer started", null);

                JobRunOutcome outcome = _runner.Run(
                    record.JobId, job, strategyType, workDir,
                    record.Cancellation.Token);

                // The runner's own outcome is the authority, not the fact that
                // somebody asked. NinjaTrader's RunBacktest() takes no token
                // and cannot be preempted, so a cancel can arrive while the
                // run is already finishing. Reporting that as "cancelled"
                // would throw away a complete, valid result and tell the
                // operator something untrue about their own run.
                bool cancelSeenAfterRun = record.Cancellation.IsCancellationRequested;

                if (outcome != null && outcome.Status == JobStatus.Cancelled)
                {
                    _writeResult(record.CommandId, "cancelled",
                        Truncate(outcome.Message ?? "cancelled at a runner boundary", 400),
                        Diagnostics(record, outcome, cancelSeenBeforeRun,
                                    cancelSeenAfterRun).ToString(Formatting.None));
                    return;
                }

                if (record.CancelRequested)
                {
                    // Honest race: the run reached its end before any boundary
                    // could take effect. The server records this rather than
                    // presenting a finished run as a cancelled one.
                    BridgeLog.Info(
                        "ConnectorBacktestExecutor: cancel_race_completed_before_abort_boundary job="
                        + record.JobId);
                }

                if (outcome != null && outcome.Status == JobStatus.Failed)
                {
                    _writeResult(record.CommandId, "failed",
                        Truncate((outcome.ErrorType ?? "run_failed") + ": "
                                 + (outcome.Message ?? ""), 400),
                        Diagnostics(record, outcome, cancelSeenBeforeRun,
                                    cancelSeenAfterRun).ToString(Formatting.None));
                    return;
                }

                string safeResult = BuildSafeResult(
                    record, workDir, outcome, cancelSeenBeforeRun, cancelSeenAfterRun);
                _writeResult(record.CommandId, "success",
                    record.CancelRequested
                        ? "backtest completed before cancellation could take effect"
                        : "backtest completed on NinjaTrader",
                    safeResult);
            }
            catch (OperationCanceledException)
            {
                _writeResult(record.CommandId, "cancelled",
                    "backtest cancelled before completion", null);
            }
            catch (Exception ex)
            {
                BridgeLog.Error("ConnectorBacktestExecutor.Execute", ex);
                _writeResult(record.CommandId, "failed",
                    Truncate(ex.GetType().Name + ": " + ex.Message, 400), null);
            }
            finally
            {
                lock (_gate)
                {
                    _active.Remove(record.JobId);
                    _finished.Add(record.JobId);
                }
                try { record.Cancellation.Dispose(); } catch { }
                try { Directory.Delete(workDir, true); } catch { }
            }
        }

        // ------------------------------------------------------------------
        // cancel_backtest
        // ------------------------------------------------------------------
        public void Cancel(string commandId, JObject job)
        {
            string jobId = (string)(job?["job_id"]) ?? "";
            if (string.IsNullOrWhiteSpace(jobId))
            {
                _writeResult(commandId, "rejected", "cancel job_id missing", null);
                return;
            }
            ActiveRun record = null;
            int activeCount;
            bool alreadyFinished;
            lock (_gate)
            {
                _active.TryGetValue(jobId, out record);
                activeCount = _active.Count;
                alreadyFinished = _finished.Contains(jobId);
            }

            // "I cancelled it" and "there was nothing here to cancel" used to
            // look identical on the wire: both were a bare success. That is
            // how a cancel could fail to reach a run while the audit showed a
            // clean completion, and it hid a real defect for a whole release.
            // The answer now says which of the two happened. Only the job the
            // caller already named is echoed -- no other run's id, no
            // workspace data.
            JObject detail = new JObject
            {
                ["target_job_id"] = jobId,
                ["active_run_found"] = record != null,
                ["cancellation_requested"] = false,
                ["active_count"] = activeCount,
                ["already_finished"] = alreadyFinished,
                ["executor_state"] = _stopping ? "stopping" : "running",
                ["execution_instance_id"] =
                    record != null ? record.ExecutionInstanceId : "",
            };

            if (record == null)
            {
                _writeResult(commandId, "success",
                    alreadyFinished
                        ? "backtest already finished; nothing to cancel"
                        : "no active backtest for this job",
                    detail.ToString(Formatting.None));
                return;
            }

            record.CancelRequested = true;
            try
            {
                record.Cancellation.Cancel();
                detail["cancellation_requested"] = true;
            }
            catch (ObjectDisposedException)
            {
                // The run ended between the lookup and the cancel. Say so
                // rather than claiming a cancellation that reached nothing.
                detail["executor_state"] = "run_ended_before_cancel";
            }
            _writeResult(commandId, "success",
                "cancellation requested for running backtest",
                detail.ToString(Formatting.None));
        }

        // ------------------------------------------------------------------
        // Bounded result
        // ------------------------------------------------------------------
        /// <summary>
        /// What the cancellation path actually observed, as plain booleans.
        /// No object addresses, no thread internals, no workspace data -- only
        /// enough to tell a registry miss from a token that never reached the
        /// runner from a runner that saw the cancel and finished anyway.
        /// </summary>
        private static JObject Diagnostics(
            ActiveRun record, JobRunOutcome outcome,
            bool cancelSeenBeforeRun, bool cancelSeenAfterRun)
        {
            return new JObject
            {
                ["execution_instance_id"] = record.ExecutionInstanceId,
                ["cancel_requested_on_device"] = record.CancelRequested,
                ["cancel_seen_before_run"] = cancelSeenBeforeRun,
                ["cancel_seen_after_run"] = cancelSeenAfterRun,
                ["cancel_seen_before_trade_collection"] =
                    outcome != null && outcome.CancelSeenBeforeTradeCollection,
                ["outcome_status"] = outcome == null
                    ? "none" : outcome.Status.ToString(),
            };
        }

        private string BuildSafeResult(
            ActiveRun record, string workDir, JobRunOutcome outcome,
            bool cancelSeenBeforeRun, bool cancelSeenAfterRun)
        {
            JObject result = ReadJson(Path.Combine(workDir, "result.json"));
            JArray trades = ReadArray(Path.Combine(workDir, "trades.json"));
            JArray bars = ReadArray(Path.Combine(workDir, "bars.json"));

            int total = trades != null ? trades.Count : 0;
            JArray transferred = new JArray();
            if (trades != null)
                foreach (JToken row in trades.Take(MaxTransferredTrades))
                    transferred.Add(row.DeepClone());

            JObject executionDetails = result?["source"] as JObject ?? new JObject();
            executionDetails["execution_source"] = "ninjatrader";
            executionDetails["machine"] = Environment.MachineName;
            if (bars != null) executionDetails["bar_count"] = bars.Count;

            JObject payload = new JObject
            {
                ["run_hash"] = (string)result?["run_hash"] ?? "",
                ["started_at_utc"] = record.StartedUtc.ToString("o", CultureInfo.InvariantCulture),
                ["finished_at_utc"] = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                ["duration_ms"] = result?["duration_ms"] ?? JValue.CreateNull(),
                // `source` is a deliberately forbidden wire-field name. The
                // server maps this bounded transport projection back to the
                // canonical report's `source` block after validation.
                ["execution_details"] = executionDetails,
                ["metrics"] = result?["metrics"]?.DeepClone() ?? new JObject(),
                ["trades"] = transferred,
                ["trades_total"] = total,
                ["trades_truncated"] = total > transferred.Count,
                ["cancellation"] = Diagnostics(
                    record, outcome, cancelSeenBeforeRun, cancelSeenAfterRun),
            };

            // Shrink until it fits rather than letting a successful run fail in
            // transit. Each step drops rows, never counts: the report can say
            // fewer trades were transferred, but never that fewer happened.
            while (Encoding.UTF8.GetByteCount(payload.ToString(Formatting.None)) > MaxSafeResultBytes
                   && transferred.Count > 0)
            {
                int keep = Math.Max(0, transferred.Count / 2);
                while (transferred.Count > keep) transferred.RemoveAt(transferred.Count - 1);
                payload["trades"] = transferred;
                payload["trades_truncated"] = total > transferred.Count;
            }
            return payload.ToString(Formatting.None);
        }

        private static JObject ReadJson(string path)
        {
            try
            {
                if (!File.Exists(path)) return null;
                using (JsonTextReader reader = new JsonTextReader(
                    new StringReader(File.ReadAllText(path, Encoding.UTF8))))
                {
                    reader.DateParseHandling = DateParseHandling.None;
                    return JObject.Load(reader);
                }
            }
            catch { return null; }
        }

        private static JArray ReadArray(string path)
        {
            try
            {
                if (!File.Exists(path)) return null;
                using (JsonTextReader reader = new JsonTextReader(
                    new StringReader(File.ReadAllText(path, Encoding.UTF8))))
                {
                    reader.DateParseHandling = DateParseHandling.None;
                    return JArray.Load(reader);
                }
            }
            catch { return null; }
        }

        private static string Truncate(string value, int max)
        {
            if (string.IsNullOrEmpty(value)) return "";
            return value.Length <= max ? value : value.Substring(0, max);
        }
    }
}
