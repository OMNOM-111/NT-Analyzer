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

    /// <summary>
    /// Stub runner kept as a fallback / for future tests.
    /// Production wiring uses StrategyAnalyzerRunner (Variant 1).
    /// </summary>
    internal sealed class NotImplementedHistoricalRunner : IHistoricalRunner
    {
        public string VariantId => "0_stub";

        public JobRunOutcome Run(string jobId, JObject job, Type strategyType,
                                 string runningJobDir, CancellationToken ct)
        {
            if (ct.IsCancellationRequested)
                return JobRunOutcome.Cancelled("cancelled before execution started");

            return JobRunOutcome.Failed(
                "not_implemented",
                "Stub runner — wire StrategyAnalyzerRunner instead");
        }
    }
}
