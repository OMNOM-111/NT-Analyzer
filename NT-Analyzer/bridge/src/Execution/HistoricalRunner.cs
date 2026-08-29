using System;
using System.Threading;
using Newtonsoft.Json.Linq;

namespace NTAnalyzerBridge.Execution
{
    internal enum JobStatus
    {
        Done,
        Failed,
        Cancelled
    }

    /// <summary>
    /// Outcome of running one job.
    /// </summary>
    internal sealed class JobRunOutcome
    {
        public JobStatus Status { get; }
        public string ErrorType { get; }
        public string Message { get; }

        /// <summary>
        /// Diagnostics only. True when the boundary that guards the work after
        /// NinjaTrader's uninterruptible RunBacktest() actually observed a
        /// cancelled token. It answers what the outcome alone cannot: whether
        /// the runner was handed the same cancellation the operator asked for,
        /// or a different one it never saw.
        /// </summary>
        public bool CancelSeenBeforeTradeCollection { get; set; }

        /// <summary>
        /// Diagnostics only: the name of the boundary that observed the
        /// cancel. Empty when the run was not cancelled.
        /// </summary>
        public string CancelBoundary { get; set; }

        private JobRunOutcome(JobStatus status, string errorType, string message)
        {
            Status = status;
            ErrorType = errorType;
            Message = message;
        }

        public static JobRunOutcome Done() => new JobRunOutcome(JobStatus.Done, null, null);
        public static JobRunOutcome Failed(string errorType, string message)
            => new JobRunOutcome(JobStatus.Failed, errorType, message);
        public static JobRunOutcome Cancelled(string message)
            => new JobRunOutcome(JobStatus.Cancelled, "cancelled", message);
    }

    internal interface IHistoricalRunner
    {
        /// <summary>
        /// Run a single backtest job. The runner is responsible for writing
        /// result.json (and any auxiliary artifacts) into <paramref name="runningJobDir"/>
        /// when the outcome is Done. JobQueueWatcher.Finalize handles the
        /// Cancelled/Failed status files itself.
        /// </summary>
        string VariantId { get; }

        JobRunOutcome Run(string jobId, JObject job, Type strategyType,
                          string runningJobDir, CancellationToken ct);
    }

}
