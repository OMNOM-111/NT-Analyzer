using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Reporting;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Execution
{
    /// <summary>
    /// Variant 1 runner: drives a NinjaTrader Strategy Analyzer-equivalent
    /// backtest in-process via the Optimizer machinery.
    ///
    /// Strategy:
    ///  1. Build and configure a StrategyBase template (Instrument, BarsPeriod,
    ///     From/To, Calculate, Account, etc.).
    ///  2. Try Path A — invoke the private static
    ///     NinjaTrader.NinjaScript.Optimizers.Optimizer.RunBacktest(template, no params)
    ///     via reflection. This is the single entry point Strategy Analyzer
    ///     itself calls per iteration.
    ///  3. If Path A is unavailable / throws, try Path B — subclass Optimizer
    ///     and drive the public lifecycle SetState→RunIteration→WaitForIterationsCompleted.
    ///  4. Extract trades + metrics from StrategyBase.SystemPerformance.
    ///
    /// Failure policy: failed strategy runs are surfaced as failed jobs, not
    /// silently converted into successful reports.
    ///   never silently fall back to Variant 2. If Variant 1 fails at step N,
    ///   return Failed("variant1_unavailable", &lt;step&gt;: &lt;exception&gt;) with
    ///   the FULL diagnostic trail so the user can see exactly which API
    ///   misbehaved.
    /// </summary>
    internal sealed class StrategyAnalyzerRunner : IHistoricalRunner
    {
        private readonly StrategyLoader _loader;
        private readonly BridgeConfig _cfg;

        public StrategyAnalyzerRunner(StrategyLoader loader, BridgeConfig cfg)
        {
            _loader = loader ?? throw new ArgumentNullException(nameof(loader));
            _cfg    = cfg ?? throw new ArgumentNullException(nameof(cfg));
        }

        public string VariantId => "1_strategy_analyzer";

        public JobRunOutcome Run(string jobId, JObject job, Type strategyType,
                                 string runningDir, CancellationToken ct)
        {
            var diag = new List<string>();
            var rb = new ResultBuilder
            {
                AddOnVersion        = "0.1.0",
                NinjaTraderVersion  = SafeNtVersion(),
                CustomDllSha256     = Sha256.OfFile(Path.Combine(_cfg.NinjaTraderUserDir,
                                                                 "bin", "Custom",
                                                                 "NinjaTrader.Custom.dll")),
                ResolvedSourceFile  = ResultBuilder.FindSourceFile(_cfg.NinjaTraderUserDir,
                                                                   strategyType?.Name),
                RdVariantUsed       = VariantId,
                StartedAtUtc        = DateTime.UtcNow
            };
            if (rb.ResolvedSourceFile != null)
            {
                rb.SourceFileSha256   = Sha256.OfFile(rb.ResolvedSourceFile);
                try { rb.SourceFileMtimeUtc = File.GetLastWriteTimeUtc(rb.ResolvedSourceFile); }
                catch { }
            }

            // Each backtest path gets a FRESH ConfigureStrategy(...) template
            // so that a partial side-effect from a failed earlier path
            // (state machine half-advanced, Bars half-loaded, SystemPerformance
            // dirty, etc.) cannot cause a false negative on the next path.
            // ConfigureStrategy is fail-fast on its own, so any None result
            // is a definitive abort — no point re-trying.

            // 1a) sanity build of an initial template purely so that any
            //     configuration error (bad instrument, bad period, ...) is
            //     reported BEFORE we burn any backtest path.
            object sanityTemplate;
            try
            {
                sanityTemplate = ConfigureStrategy(strategyType, job, diag);
                if (sanityTemplate == null)
                {
                    return WriteFailure(jobId, runningDir, "variant1_unavailable",
                        "ConfigureStrategy returned null", diag, rb, job, strategyType);
                }
            }
            catch (Exception ex)
            {
                AppendExceptionChain(diag, "ConfigureStrategy", ex);
                return WriteFailure(jobId, runningDir, "variant1_unavailable",
                    "configure_strategy_failed", diag, rb, job, strategyType);
            }
            // sanityTemplate is intentionally discarded — used only for early validation.
            sanityTemplate = null;

            if (ct.IsCancellationRequested)
                return JobRunOutcome.Cancelled("cancelled before backtest start");

            // Backtest path order:
            //   PathA2 first \u2014 verified working on NinjaTrader 8.1.6.3.
            //   PathA  only if explicitly enabled in config (R&D toggle):
            //          private static Optimizer.RunBacktest reliably throws
            //          NullReferenceException outside Strategy Analyzer host.
            //   PathB  is still a stub.
            object backtested = null;

            // 2) PathA2 \u2014 public StrategyBase.RunBacktest() instance call.
            try
            {
                diag.Add("PathA2: configuring fresh template");
                object t = ConfigureStrategy(strategyType, job, diag);
                if (t != null)
                {
                    if (_cfg.EnableVerboseDiagnostics)
                        DumpDateRangeProperties(t, "PathA2.before-run", diag);
                    backtested = TryPathA2_InstanceRunBacktest(t, diag);
                    if (backtested != null && _cfg.EnableVerboseDiagnostics)
                        DumpDateRangeProperties(backtested, "PathA2.after-run", diag);
                }
            }
            catch (Exception ex)
            {
                AppendExceptionChain(diag, "PathA2(InstanceRunBacktest)", ex);
            }

            if (ct.IsCancellationRequested)
                return JobRunOutcome.Cancelled("cancelled after PathA2");

            // 2b) PathA \u2014 private static Optimizer.RunBacktest (R&D, opt-in).
            if (backtested == null && _cfg.EnablePathAOptimizerRunBacktest)
            {
                try
                {
                    diag.Add("PathA: configuring fresh template (enabled by config)");
                    object t = ConfigureStrategy(strategyType, job, diag);
                    if (t != null)
                        backtested = TryPathA_StaticRunBacktest(t, diag);
                }
                catch (Exception ex)
                {
                    AppendExceptionChain(diag, "PathA(StaticRunBacktest)", ex);
                }
            }
            else if (backtested == null)
            {
                diag.Add("PathA: skipped (enable_path_a_optimizer_runbacktest=false)");
            }

            if (ct.IsCancellationRequested)
                return JobRunOutcome.Cancelled("cancelled after PathA");

            // 3) PathB \u2014 subclass + lifecycle.
            if (backtested == null)
            {
                try
                {
                    diag.Add("PathB: configuring fresh template");
                    object t = ConfigureStrategy(strategyType, job, diag);
                    if (t != null)
                        backtested = TryPathB_LifecycleSubclass(t, diag, ct);
                }
                catch (OperationCanceledException)
                {
                    return JobRunOutcome.Cancelled("cancelled during PathB");
                }
                catch (Exception ex)
                {
                    AppendExceptionChain(diag, "PathB(LifecycleSubclass)", ex);
                }
            }

            if (backtested == null)
            {
                return WriteFailure(jobId, runningDir, "variant1_unavailable",
                    "no_backtest_path_succeeded", diag, rb, job, strategyType);
            }

            // Boundary: the computation NinjaTrader would not let us stop is
            // over. Everything below -- collecting trades, building metrics,
            // serialising the report -- is ours and is skipped outright when a
            // cancel is pending. It is the earliest supported point at which a
            // cancel can actually save work.
            if (ct.IsCancellationRequested)
                return JobRunOutcome.Cancelled("cancelled before trade collection");

            // 4) Extract trades + metrics.
            var collector = new TradeCollector { EnableVerboseDiagnostics = _cfg.EnableVerboseDiagnostics };
            try { collector.Collect(backtested); }
            catch (Exception ex)
            {
                diag.Add("TradeCollector: " + ex.GetType().Name + ": " + ex.Message);
            }
            // Last-resort fill for winning_pct from the trades list (NT 8.1.6.3
            // does not expose WinningTrades publicly on TradesPerformance).
            try { collector.FinaliseWinningPctFromTrades(); } catch { }
            diag.AddRange(collector.Warnings);

            // 4a) Consistency guard: SystemPerformance metrics show N trades
            // but the per-trade list is empty. result.json would not be
            // self-sufficient (UI/AI can't reconstruct trades from aggregates),
            // so fail-fast instead of silently writing Done.
            int metricsTradeCount = 0;
            try
            {
                var jt = collector.Metrics["trade_count"];
                if (jt != null && jt.Type == JTokenType.Integer) metricsTradeCount = (int)jt;
            }
            catch { }
            if (metricsTradeCount > 0 && collector.Trades.Count == 0)
            {
                diag.Add("FATAL: metrics.trade_count=" + metricsTradeCount +
                         " but trades list is empty. Likely cause: NinjaScript" +
                         " did not retain per-trade history. Verify" +
                         " StrategyBase.IncludeTradeHistoryInBacktest=true was" +
                         " applied before backtest start.");
                return WriteFailure(jobId, runningDir, "variant1_incomplete",
                    "metrics_trade_count_" + metricsTradeCount + "_but_trades_empty",
                    diag, rb, job, strategyType);
            }

            // 4b) Period invariant: every trade entry/exit must fall inside
            // [from_utc, to_utc] (with a small TZ/session tolerance). If
            // RunBacktest silently used a different range (DaysToLoad,
            // BarsLoaded, default lookback), the result.json would mis-
            // describe the prog\u0440on and any manual cross-check vs Strategy
            // Analyzer UI would compare two different runs.
            string periodErr = CheckPeriodInvariant(job, collector.Trades, diag);
            if (periodErr != null)
            {
                return WriteFailure(jobId, runningDir, "period_mismatch",
                    periodErr, diag, rb, job, strategyType);
            }

            // 5) Build result.json.
            var finalParams = ExtractFinalParameters(backtested, diag);

            // 5a) Best-effort dump of the primary OHLCV series so the UI
            // can render a chart with trade markers without round-tripping
            // through NinjaTrader. Failures are non-fatal — chart tab will
            // show "bars artifact missing".
            var barsCollector = new BarsCollector();
            try
            {
                JObject pr2 = (JObject)job["period"];
                DateTime fromUtc = ParseDate((string)pr2?["from_utc"]);
                DateTime toUtc   = ParseDate((string)pr2?["to_utc"]);
                barsCollector.Collect(backtested, fromUtc, toUtc);
            }
            catch (Exception ex)
            {
                diag.Add("BarsCollector: " + ex.GetType().Name + ": " + ex.Message);
            }
            diag.AddRange(barsCollector.Warnings);
            bool barsFileWritten = barsCollector.Bars.Count > 0;

            // A void/successful RunBacktest invocation does not prove that NT
            // actually attached a historical series.  Treat an empty/null
            // BarsArray as an infrastructure failure, never as a legitimate
            // zero-trade strategy result.
            if (!barsFileWritten)
            {
                diag.Add("FATAL: no historical bars were attached to the backtested strategy; " +
                         "zero-trade metrics are not valid strategy evidence.");
                return WriteFailure(jobId, runningDir, "variant1_no_historical_bars",
                    "historical_bars_missing", diag, rb, job, strategyType);
            }

            // Stage 2: compute a REAL historical_data_fingerprint from the exact
            // OHLCV series the backtest consumed. This replaces the placeholder
            // and (via ResultBuilder) participates in run_hash, so two runs over
            // different NT history no longer collide on the same hash. Method is
            // sha256 over the canonical bar series; falls back to placeholder
            // only when no bars survived.
            JObject dataFingerprint;
            if (barsFileWritten)
            {
                string barsCanon = barsCollector.Bars.ToString(Newtonsoft.Json.Formatting.None);
                dataFingerprint = new JObject
                {
                    ["method"] = "sha256_of_primary_bar_series",
                    ["value"]  = NTAnalyzerBridge.Util.Sha256.OfString(barsCanon),
                    ["bar_count"] = barsCollector.Bars.Count,
                    ["files"] = new JArray("bars.json")
                };
            }
            else
            {
                dataFingerprint = new JObject
                {
                    ["method"] = "placeholder",
                    ["value"]  = "sha256:placeholder",
                    ["files"]  = new JArray()
                };
            }

            // 5b) Best-effort export of strategy Draw.* objects (universal
            // schema). For headless RunBacktest most strategies will export
            // zero objects; we still write the file with the diagnostic so
            // the UI can show "not exported" honestly instead of guessing.
            var drawCollector = new DrawObjectsCollector();
            try { drawCollector.Collect(backtested); }
            catch (Exception ex)
            {
                diag.Add("DrawObjectsCollector: " + ex.GetType().Name + ": " + ex.Message);
            }
            diag.AddRange(drawCollector.Warnings);
            try
            {
                var drawFile = new JObject
                {
                    ["version"] = 1,
                    ["objects"] = drawCollector.Objects,
                    ["diagnostics"] = new JArray(drawCollector.Warnings),
                };
                AtomicFile.WriteAllText(
                    Path.Combine(runningDir, "draw_objects.json"),
                    drawFile.ToString(Newtonsoft.Json.Formatting.None));
            }
            catch (Exception ex)
            {
                diag.Add("DrawObjectsCollector: write draw_objects.json failed: " + ex.Message);
            }

            var result = rb.Build(jobId, job, strategyType, finalParams,
                                  collector.Trades, collector.Metrics, diag, dataFingerprint);
            // Patch the artifacts.bars_file pointer to reflect what we
            // actually wrote (null when no bars survived).
            try
            {
                var arts = (JObject)result["artifacts"];
                if (arts != null)
                    arts["bars_file"] = barsFileWritten ? (JToken)"bars.json" : JValue.CreateNull();
            }
            catch { }

            // Write result.json + trades.json + raw.json (+ bars.json if present).
            WriteJobOutputs(runningDir, result, collector.Trades);
            if (barsFileWritten)
            {
                try
                {
                    AtomicFile.WriteAllText(
                        Path.Combine(runningDir, "bars.json"),
                        barsCollector.Bars.ToString(Newtonsoft.Json.Formatting.None));
                }
                catch (Exception ex)
                {
                    diag.Add("BarsCollector: write bars.json failed: " + ex.Message);
                }
            }

            return JobRunOutcome.Done();
        }

        // ---------------------- configure ----------------------------------

        private object ConfigureStrategy(Type strategyType, JObject job, List<string> diag)
        {
            object s = Activator.CreateInstance(strategyType);
            diag.Add("strategy.activate: ok (" + strategyType.FullName + ")");

            // Run NinjaScript SetDefaults BEFORE we touch anything else.
            // For SampleMACrossOver this is where Fast=10/Slow=25 are
            // assigned in OnStateChange. Without this, [NinjaScriptProperty]
            // backing fields are left at their CLR defaults (0/null), and
            // job.strategy.parameters can only override values it explicitly
            // names.
            if (!InvokeSetState(s, "SetDefaults", diag)) return null;

            // ---- Trade history (REQUIRED for trades.json) -----------------
            // SystemPerformance always computes aggregate metrics, but the
            // per-trade list (sp.AllTrades / LongTrades / ShortTrades) stays
            // empty unless StrategyBase.IncludeTradeHistoryInBacktest is
            // explicitly set to true before the backtest runs. Without this,
            // metrics.trade_count == 9232 but trades == [].
            if (!TrySetRequired(s, "IncludeTradeHistoryInBacktest", true, diag)) return null;

            // ---- Instrument (required) ------------------------------------
            string instrumentName = (string)job["instrument"];
            object instrument = ResolveInstrument(instrumentName, diag);
            if (instrument == null) { diag.Add("FATAL: instrument unresolved"); return null; }
            if (!TrySetRequired(s, "Instrument", instrument, diag)) return null;

            // ---- BarsPeriod (required) ------------------------------------
            JObject tf = (JObject)job["timeframe"];
            if (tf == null) { diag.Add("FATAL: timeframe missing"); return null; }
            object barsPeriod = BuildBarsPeriod((string)tf["bars_period_type"],
                                                (int?)tf["value"] ?? 1, diag);
            if (barsPeriod == null) { diag.Add("FATAL: bars_period unresolved"); return null; }
            if (!TrySetRequired(s, "BarsPeriod", barsPeriod, diag)) return null;

            // ---- Period: From / To (required) -----------------------------
            // Job schema field names are 'from_utc' / 'to_utc'.
            JObject pr = (JObject)job["period"];
            string fromStr = (string)pr?["from_utc"];
            string toStr   = (string)pr?["to_utc"];
            DateTime from  = ParseDate(fromStr);
            DateTime to    = ParseDate(toStr);
            if (from == DateTime.MinValue || to == DateTime.MinValue || to <= from)
            {
                diag.Add("FATAL: period invalid period.from_utc='" + (fromStr ?? "") +
                         "' / period.to_utc='" + (toStr ?? "") + "'");
                return null;
            }
            if (!TrySetRequired(s, "From", from, diag)) return null;
            if (!TrySetRequired(s, "To",   to,   diag)) return null;

            // ---- Execution context (from job, not hard-coded) -------------
            if (!ApplyExecution(s, (JObject)job["execution"], diag)) return null;

            // ---- Account (strict: Backtest / Sim101 only) ----------------
            object account = ResolveBacktestAccount(diag);
            if (account == null) { diag.Add("FATAL: no Backtest/Sim101 account"); return null; }
            if (!TrySetRequired(s, "Account", account, diag)) return null;

            // ---- Commission template (must be applied AFTER Account) ------
            if (!ApplyCommissionTemplate(s, account, (JObject)job["execution"], diag))
                return null;

            // ---- BarsToLoad / DaysToLoad: do NOT override -----------------
            // Earlier code unconditionally did
            //     TrySet(s, "BarsToLoad", 200000)
            // which made NT load 200000 bars BACK from `To`, ignoring `From`
            // entirely (loaded 2025-09-30 instead of requested 2026-03-12,
            // see "period_mismatch" investigation 2026-04-27). Strategy
            // Analyzer UI itself relies purely on From/To for the bar window,
            // so we do the same and let NinjaTrader compute warmup from
            // BarsRequiredToTrade.

            // ---- Strategy parameters (strict; unknown/type mismatch = fatal)
            if (!ApplyStrategyParameters(s, (JObject)job.SelectToken("strategy.parameters"),
                                         strategyType, diag)) return null;

            return s;
        }

        /// <summary>
        /// Apply job.execution to the StrategyBase template.
        /// Supported keys (silently ignored if absent in job):
        ///   calculate              — enum NinjaTrader.NinjaScript.Calculate (required-ish: defaults to OnBarClose)
        ///   is_tick_replay         — bool
        ///   order_fill_resolution  — enum NinjaTrader.NinjaScript.OrderFillResolution (Standard / High)
        ///   slippage_ticks         — int
        ///   commission             — not yet supported — fail-fast if a non-zero value is requested
        ///   session_template       — string — sets TradingHours via TradingHours.Get(name)
        ///   timezone               — informational only; must be "UTC" or absent
        /// Returns false on any unsupported / unparseable value.
        /// </summary>
        private bool ApplyExecution(object s, JObject exec, List<string> diag)
        {
            if (exec == null)
            {
                diag.Add("FATAL: execution block missing in job.json");
                return false;
            }

            // calculate (default OnBarClose)
            string calcName = (string)exec["calculate"] ?? "OnBarClose";
            object calc = ResolveEnum("NinjaTrader.NinjaScript.Calculate, NinjaTrader.Core",
                                      calcName, diag);
            if (calc == null) { diag.Add("FATAL: execution.calculate='" + calcName + "' unresolved"); return false; }
            if (!TrySetRequired(s, "Calculate", calc, diag)) return false;

            // is_tick_replay (default false)
            bool tickReplay = (bool?)exec["is_tick_replay"] ?? false;
            if (!TrySetRequired(s, "IsTickReplay", tickReplay, diag)) return false;

            // order_fill_resolution (optional; default Standard)
            string ofrName = (string)exec["order_fill_resolution"];
            if (!string.IsNullOrEmpty(ofrName))
            {
                object ofr = ResolveEnum("NinjaTrader.NinjaScript.OrderFillResolution, NinjaTrader.Core",
                                         ofrName, diag);
                if (ofr == null) { diag.Add("FATAL: execution.order_fill_resolution='" + ofrName + "' unresolved"); return false; }
                if (!TrySetRequired(s, "OrderFillResolution", ofr, diag)) return false;
            }

            // slippage_ticks (optional; default 0)
            int slippage = (int?)exec["slippage_ticks"] ?? 0;
            if (!TrySetRequired(s, "Slippage", slippage, diag)) return false;

            // commission (numeric): bridge applies *only* commission_template.
            // A numeric commission setting has no NT-side hook here, so we
            // refuse non-zero values to avoid silent metric drift.
            decimal commission = (decimal?)exec["commission"] ?? 0m;
            if (commission != 0m)
            {
                diag.Add("FATAL: execution.commission=" + commission +
                         " not supported (bridge applies commission_template only). " +
                         "Set commission=0 and use commission_template.");
                return false;
            }
            // Commission template is applied AFTER Account is bound (see
            // ApplyCommissionTemplate). Just record the requested name here so
            // diagnostics show the full intent even if account binding fails.
            string requestedTmpl = (string)exec["commission_template"];
            diag.Add("commission_template: requested='" +
                     (string.IsNullOrEmpty(requestedTmpl) ? "None" : requestedTmpl) + "'");

            // session_template (optional). Resolve via TradingHours.Get(name).
            string sessionName = (string)exec["session_template"];
            if (!string.IsNullOrEmpty(sessionName))
            {
                object th = ResolveTradingHours(sessionName, diag);
                if (th == null) { diag.Add("FATAL: execution.session_template='" + sessionName + "' unresolved"); return false; }
                if (!TrySetRequired(s, "TradingHours", th, diag)) return false;
            }

            // timezone — informational. We always interpret From/To as UTC.
            string tz = (string)exec["timezone"];
            if (!string.IsNullOrEmpty(tz) && !string.Equals(tz, "UTC", StringComparison.OrdinalIgnoreCase))
            {
                diag.Add("FATAL: execution.timezone='" + tz + "' — only 'UTC' supported by the current bridge");
                return false;
            }

            return true;
        }

        private object ResolveTradingHours(string name, List<string> diag)
        {
            try
            {
                var t = Type.GetType("NinjaTrader.Data.TradingHours, NinjaTrader.Core");
                if (t == null) { diag.Add("trading_hours: type not found"); return null; }
                var m = t.GetMethod("Get", BindingFlags.Public | BindingFlags.Static,
                                    null, new[] { typeof(string) }, null);
                if (m == null) { diag.Add("trading_hours: TradingHours.Get(string) not found"); return null; }
                object th = m.Invoke(null, new object[] { name });
                if (th == null) diag.Add("trading_hours: Get('" + name + "') returned null");
                else diag.Add("trading_hours: resolved '" + name + "'");
                return th;
            }
            catch (Exception ex)
            {
                diag.Add("trading_hours: " + ex.GetType().Name + ": " + ex.Message);
                return null;
            }
        }

        /// <summary>
        /// Apply commission template to the strategy's bound Account. The template
        /// name is taken from execution.commission_template. If absent / empty /
        /// "None", we *explicitly* clear any commission on the account so two runs
        /// with template="None" vs. a real template differ deterministically.
        ///
        /// Resolution probes (NT-internal types are accessed via reflection because
        /// they are not part of the public NinjaScript surface):
        ///   1) Cbi.Commission.Get(string) / GetByName / FromName
        ///   2) iterate Cbi.Commission.All / Cbi.Globals.AllCommissions by Name
        ///   3) deserialize ntUserDir/templates/Commission/&lt;name&gt;.xml directly
        ///
        /// Application probes:
        ///   A) account.Commission = c (Cbi.Account.Commission setter)
        ///   B) strategy.Commission = c (StrategyBase.Commission setter)
        ///   C) account.SetCommission(c) method
        /// We try all of A/B/C and report which succeeded. If none work we
        /// fail-fast — silent zero-commission would invalidate the report.
        /// </summary>
        private bool ApplyCommissionTemplate(object strategy, object account,
                                             JObject exec, List<string> diag)
        {
            string name = (string)exec["commission_template"];
            bool isNone = string.IsNullOrEmpty(name) ||
                          string.Equals(name, "None", StringComparison.OrdinalIgnoreCase);

            if (isNone)
            {
                // No commission template requested. Best-effort clear so a previous
                // run on a long-lived process can't leak a stale Commission object.
                TryClearCommission(strategy, account, diag);
                diag.Add("commission_template: skipped (None / no template)");
                return true;
            }

            object commission = ResolveCommissionTemplate(name, diag);
            if (commission == null)
            {
                diag.Add("FATAL: commission_template '" + name + "' could not be resolved " +
                         "(probed Commission.Get, Commission.All, XML deserialise — see diag above)");
                return false;
            }

            DumpCommissionMembers(strategy, "strategy", diag);
            DumpCommissionMembers(account,  "account",  diag);

            var appliedVia = TryApplyCommissionEverywhere(strategy, account, commission, name, diag);
            if (appliedVia.Count == 0)
            {
                diag.Add("FATAL: commission_template '" + name + "' resolved but no setter " +
                         "accepted it (probed Strategy/Account properties + fields)");
                return false;
            }

            // Force-enable commission inclusion in PnL — defaults vary across NT builds.
            string incRes = TryAssign(strategy, "IncludeCommission", true);
            diag.Add("commission_template: IncludeCommission = true -> " +
                     (incRes == null ? "ok" : incRes));

            diag.Add("commission_template: applied '" + name + "' via " +
                     string.Join(", ", appliedVia));
            return true;
        }

        // Apply the commission object to every plausible target and report all that
        // accepted it. NT's standalone RunBacktest path may consult either the
        // strategy or the account at fill time, so we set both.
        private List<string> TryApplyCommissionEverywhere(object strategy, object account,
                                                          object commission, string name,
                                                          List<string> diag)
        {
            var applied = new List<string>();

            foreach (var pair in new[] {
                Tuple.Create(strategy, "strategy"),
                Tuple.Create(account,  "account"),
            })
            {
                object target = pair.Item1;
                string label  = pair.Item2;
                if (target == null) continue;

                // Object-typed Commission member (property or field).
                foreach (var member in new[] { "Commission", "CommissionObject", "CommissionTemplate" })
                {
                    string r = TryAssignAny(target, member, commission);
                    if (r == null) { applied.Add(label + "." + member); }
                    else if (!r.StartsWith("no member")) {
                        diag.Add("commission_template: " + label + "." + member + " rejected: " + r);
                    }
                }

                // String-typed name slots that some NT builds expose.
                foreach (var member in new[] { "CommissionName", "CommissionType",
                                               "CommissionTemplateName" })
                {
                    string r = TryAssignAny(target, member, name);
                    if (r == null) applied.Add(label + "." + member + " (name)");
                }
            }

            // Setter method fallback on the account (some builds expose SetCommission).
            try
            {
                var m = account?.GetType().GetMethod("SetCommission",
                            BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic,
                            null, new[] { commission.GetType() }, null);
                if (m != null) { m.Invoke(account, new[] { commission });
                                 applied.Add("Account.SetCommission()"); }
            }
            catch (Exception ex)
            {
                diag.Add("commission_template: Account.SetCommission threw " +
                         ex.GetType().Name + ": " + (ex.InnerException?.Message ?? ex.Message));
            }
            return applied;
        }

        // One-shot discovery dump: list every public/non-public member whose name
        // contains "commission". Helps us see what NT actually exposes on this build.
        private static void DumpCommissionMembers(object target, string label, List<string> diag)
        {
            if (target == null) return;
            var t = target.GetType();
            const BindingFlags BF = BindingFlags.Public | BindingFlags.NonPublic
                                  | BindingFlags.Instance | BindingFlags.FlattenHierarchy;
            var found = new List<string>();
            foreach (var p in t.GetProperties(BF))
                if (p.Name.IndexOf("commission", StringComparison.OrdinalIgnoreCase) >= 0)
                    found.Add("prop " + p.Name + ":" + p.PropertyType.Name +
                              (p.CanWrite ? "(rw)" : "(ro)"));
            foreach (var f in t.GetFields(BF))
                if (f.Name.IndexOf("commission", StringComparison.OrdinalIgnoreCase) >= 0)
                    found.Add("field " + f.Name + ":" + f.FieldType.Name);
            if (found.Count > 0)
                diag.Add("commission_template: " + label + " members: " +
                         string.Join("; ", found));
        }

        private object ResolveCommissionTemplate(string name, List<string> diag)
        {
            Type cT = Type.GetType("NinjaTrader.Cbi.Commission, NinjaTrader.Core");
            if (cT == null)
            {
                diag.Add("commission_template: Cbi.Commission type not found");
            }
            else
            {
                // Path 1: static factory methods.
                foreach (var mname in new[] { "Get", "GetByName", "FromName", "Load" })
                {
                    var m = cT.GetMethod(mname,
                        BindingFlags.Public | BindingFlags.Static | BindingFlags.NonPublic,
                        null, new[] { typeof(string) }, null);
                    if (m == null) continue;
                    try
                    {
                        object res = m.Invoke(null, new object[] { name });
                        if (res != null)
                        {
                            diag.Add("commission_template: resolved via Commission." + mname + "(string)");
                            return res;
                        }
                    }
                    catch (Exception ex)
                    {
                        diag.Add("commission_template: Commission." + mname +
                                 " threw " + ex.GetType().Name + ": " +
                                 (ex.InnerException?.Message ?? ex.Message));
                    }
                }

                // Path 2: enumerate static collection by Name.
                foreach (var pname in new[] { "All", "Commissions" })
                {
                    var p = cT.GetProperty(pname, BindingFlags.Public | BindingFlags.Static);
                    var coll = p?.GetValue(null, null) as System.Collections.IEnumerable;
                    if (coll == null) continue;
                    foreach (var c in coll)
                    {
                        var nm = c?.GetType().GetProperty("Name")?.GetValue(c, null) as string;
                        if (string.Equals(nm, name, StringComparison.OrdinalIgnoreCase))
                        {
                            diag.Add("commission_template: resolved via Commission." + pname + "[Name]");
                            return c;
                        }
                    }
                }

                // Path 2b: NinjaTrader.Cbi.Globals.AllCommissions.
                var globT = Type.GetType("NinjaTrader.Cbi.Globals, NinjaTrader.Core");
                var globProp = globT?.GetProperty("AllCommissions",
                                BindingFlags.Public | BindingFlags.Static)
                              ?? globT?.GetProperty("Commissions",
                                BindingFlags.Public | BindingFlags.Static);
                var globColl = globProp?.GetValue(null, null) as System.Collections.IEnumerable;
                if (globColl != null)
                {
                    foreach (var c in globColl)
                    {
                        var nm = c?.GetType().GetProperty("Name")?.GetValue(c, null) as string;
                        if (string.Equals(nm, name, StringComparison.OrdinalIgnoreCase))
                        {
                            diag.Add("commission_template: resolved via Globals." +
                                     globProp.Name + "[Name]");
                            return c;
                        }
                    }
                }
            }

            // Path 3: deserialise the XML template directly.
            try
            {
                string xmlPath = Path.Combine(_cfg.NinjaTraderUserDir,
                                              "templates", "Commission", name + ".xml");
                if (!File.Exists(xmlPath))
                {
                    diag.Add("commission_template: XML not found at " + xmlPath);
                    return null;
                }
                if (cT == null) return null;
                var ser = new System.Xml.Serialization.XmlSerializer(cT);
                using (var fs = File.OpenRead(xmlPath))
                {
                    // NT XML wraps the Commission element under <NinjaTrader><Commission>.
                    var doc = new System.Xml.XmlDocument();
                    doc.Load(fs);
                    var node = doc.SelectSingleNode("//Commission");
                    if (node == null)
                    {
                        diag.Add("commission_template: <Commission> node missing in " + xmlPath);
                        return null;
                    }
                    using (var sr = new StringReader(node.OuterXml))
                    {
                        object res = ser.Deserialize(sr);
                        if (res != null)
                            diag.Add("commission_template: resolved via XML deserialisation");
                        return res;
                    }
                }
            }
            catch (Exception ex)
            {
                diag.Add("commission_template: XML path threw " +
                         ex.GetType().Name + ": " + ex.Message);
                return null;
            }
        }

        private string TryApplyCommissionObject_OBSOLETE(object strategy, object account,
                                                object commission, List<string> diag)
        {
            return null; // superseded by TryApplyCommissionEverywhere
        }

        // Assigns to property OR field (whichever exists & is writable).
        // Returns null on success, otherwise a short diagnostic string.
        private static string TryAssignAny(object target, string memberName, object value)
        {
            if (target == null) return "target=null";
            const BindingFlags BF = BindingFlags.Public | BindingFlags.NonPublic
                                  | BindingFlags.Instance | BindingFlags.FlattenHierarchy;
            var t = target.GetType();
            try
            {
                var p = t.GetProperty(memberName, BF);
                if (p != null)
                {
                    if (!p.CanWrite) return "'" + memberName + "' is read-only property";
                    if (value != null && !p.PropertyType.IsAssignableFrom(value.GetType()))
                        return "type mismatch (" + value.GetType().Name + " -> " + p.PropertyType.Name + ")";
                    p.SetValue(target, value, null);
                    return null;
                }
                var f = t.GetField(memberName, BF);
                if (f != null)
                {
                    if (value != null && !f.FieldType.IsAssignableFrom(value.GetType()))
                        return "type mismatch (" + value.GetType().Name + " -> " + f.FieldType.Name + ")";
                    f.SetValue(target, value);
                    return null;
                }
                return "no member '" + memberName + "'";
            }
            catch (Exception ex)
            {
                return ex.GetType().Name + ": " + (ex.InnerException?.Message ?? ex.Message);
            }
        }

        private static string TryAssign(object target, string propName, object value)
        {
            if (target == null) return "target=null";
            try
            {
                var p = target.GetType().GetProperty(propName,
                            BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic);
                if (p == null) return "no property '" + propName + "'";
                if (!p.CanWrite) return "'" + propName + "' is read-only";
                if (value != null && !p.PropertyType.IsAssignableFrom(value.GetType()))
                    return "type mismatch (" + value.GetType().Name + " -> " + p.PropertyType.Name + ")";
                p.SetValue(target, value, null);
                return null;
            }
            catch (Exception ex)
            {
                return ex.GetType().Name + ": " + (ex.InnerException?.Message ?? ex.Message);
            }
        }

        private void TryClearCommission(object strategy, object account, List<string> diag)
        {
            // Best-effort: assign null so a previous template doesn't leak.
            TryAssign(account, "Commission", null);
            TryAssign(strategy, "Commission", null);
        }

        /// <summary>
        /// Strict parameter application:
        ///   - only public read-write properties declared on the concrete strategy
        ///     type, OR carrying [NinjaScriptProperty], are eligible;
        ///   - unknown name OR type-conversion failure aborts the entire job.
        /// </summary>
        private static bool ApplyStrategyParameters(object strategy, JObject parameters,
                                                    Type strategyType, List<string> diag)
        {
            if (parameters == null || parameters.Count == 0)
            {
                diag.Add("strategy_parameters: none supplied — using defaults");
                return true;
            }

            // Build whitelist of allowed property names.
            // Contract: ONLY properties carrying [NinjaScriptProperty]
            // are user-tunable parameters. A plain public setter on the
            // strategy class is NOT enough — that would let job.json reach
            // into internal/auxiliary state and break reproducibility.
            var allowed = new Dictionary<string, PropertyInfo>(StringComparer.Ordinal);
            foreach (var p in strategyType.GetProperties(BindingFlags.Public | BindingFlags.Instance))
            {
                if (!p.CanRead || !p.CanWrite) continue;
                bool hasNsProp = p.GetCustomAttributes(inherit: false)
                                  .Any(a => a.GetType().Name == "NinjaScriptPropertyAttribute");
                if (hasNsProp) allowed[p.Name] = p;
            }

            foreach (var kv in parameters)
            {
                string name = kv.Key;
                JToken val  = kv.Value;
                if (!allowed.TryGetValue(name, out var p))
                {
                    diag.Add("FATAL: strategy_parameter '" + name +
                             "' not in whitelist for " + strategyType.FullName +
                             " (only properties marked with [NinjaScriptProperty] are allowed). " +
                             "Allowed: [" + string.Join(",", allowed.Keys) + "]");
                    return false;
                }
                try
                {
                    object converted = ConvertJsonToPropertyType(val, p.PropertyType);
                    p.SetValue(strategy, converted, null);
                    diag.Add("strategy_parameter '" + name + "' = " + converted);
                }
                catch (Exception ex)
                {
                    diag.Add("FATAL: strategy_parameter '" + name + "': " +
                             ex.GetType().Name + ": " + ex.Message);
                    return false;
                }
            }
            return true;
        }

        private static object ConvertJsonToPropertyType(JToken token, Type targetType)
        {
            if (targetType.IsEnum)
            {
                return Enum.Parse(targetType,
                    token.Type == JTokenType.Integer ? token.ToString() : (string)token,
                    ignoreCase: true);
            }
            // Nullable<T>
            var nullableInner = Nullable.GetUnderlyingType(targetType);
            if (nullableInner != null)
                return token.Type == JTokenType.Null ? null : ConvertJsonToPropertyType(token, nullableInner);
            return token.ToObject(targetType);
        }

        private object ResolveInstrument(string name, List<string> diag)
        {
            if (string.IsNullOrWhiteSpace(name)) { diag.Add("instrument: name empty"); return null; }
            try
            {
                var t = Type.GetType("NinjaTrader.Cbi.Instrument, NinjaTrader.Core");
                if (t == null) { diag.Add("instrument: type Cbi.Instrument not found"); return null; }
                var m = t.GetMethod("GetInstrument", BindingFlags.Public | BindingFlags.Static,
                                    null, new[] { typeof(string) }, null)
                       ?? t.GetMethod("GetInstrument", BindingFlags.Public | BindingFlags.Static,
                                      null, new[] { typeof(string), typeof(bool) }, null);
                if (m == null) { diag.Add("instrument: GetInstrument(string) not found"); return null; }
                object[] args = m.GetParameters().Length == 1
                              ? new object[] { name }
                              : new object[] { name, true };
                object inst = m.Invoke(null, args);
                if (inst == null) diag.Add("instrument: GetInstrument returned null for '" + name + "'");
                else diag.Add("instrument: resolved '" + name + "'");
                return inst;
            }
            catch (Exception ex)
            {
                diag.Add("instrument: " + ex.GetType().Name + ": " + ex.Message);
                return null;
            }
        }

        private object BuildBarsPeriod(string typeName, int value, List<string> diag)
        {
            try
            {
                var bpType = Type.GetType("NinjaTrader.Data.BarsPeriod, NinjaTrader.Core");
                var bptEnum = Type.GetType("NinjaTrader.Data.BarsPeriodType, NinjaTrader.Core");
                if (bpType == null || bptEnum == null)
                {
                    diag.Add("bars_period: BarsPeriod / BarsPeriodType not found");
                    return null;
                }
                object bp = Activator.CreateInstance(bpType);
                object bpt = Enum.Parse(bptEnum, string.IsNullOrEmpty(typeName) ? "Minute" : typeName, true);
                bpType.GetProperty("BarsPeriodType")?.SetValue(bp, bpt, null);
                bpType.GetProperty("Value")?.SetValue(bp, value, null);
                bpType.GetProperty("BaseBarsPeriodType")?.SetValue(bp, bpt, null);
                bpType.GetProperty("BaseBarsPeriodValue")?.SetValue(bp, value, null);
                diag.Add("bars_period: " + typeName + "/" + value);
                return bp;
            }
            catch (Exception ex)
            {
                diag.Add("bars_period: " + ex.GetType().Name + ": " + ex.Message);
                return null;
            }
        }

        private object ResolveEnum(string typeAqn, string name, List<string> diag)
        {
            try
            {
                var t = Type.GetType(typeAqn);
                if (t == null) { diag.Add("enum_resolve: type not found: " + typeAqn); return null; }
                return Enum.Parse(t, name, true);
            }
            catch (Exception ex)
            {
                diag.Add("enum_resolve(" + typeAqn + "." + name + "): " + ex.Message);
                return null;
            }
        }

        private object ResolveBacktestAccount(List<string> diag)
        {
            try
            {
                var accT = Type.GetType("NinjaTrader.Cbi.Account, NinjaTrader.Core");
                if (accT == null) { diag.Add("account: Cbi.Account not found"); return null; }
                var allProp = accT.GetProperty("All", BindingFlags.Public | BindingFlags.Static);
                var all = allProp?.GetValue(null, null) as System.Collections.IEnumerable;
                if (all == null) { diag.Add("account: Account.All unavailable"); return null; }

                // Strict whitelist: only the canonical local-only sim accounts.
                // No fallback to "first available account" — a real broker account
                // would silently bind the backtest to live infrastructure.
                var allowedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
                {
                    "Backtest", "Sim101", "Playback"
                };
                var seen = new List<string>();
                foreach (var a in all)
                {
                    var nm = a?.GetType().GetProperty("Name")?.GetValue(a, null) as string;
                    if (!string.IsNullOrEmpty(nm)) seen.Add(nm);
                    if (nm != null && allowedNames.Contains(nm))
                    {
                        diag.Add("account: using '" + nm + "'");
                        return a;
                    }
                }
                diag.Add("account: no Backtest/Sim101/Playback in Account.All. Seen: [" +
                         string.Join(",", seen) + "]");
            }
            catch (Exception ex) { diag.Add("account: " + ex.GetType().Name + ": " + ex.Message); }
            return null;
        }

        // ---------------------- Path A: static RunBacktest -----------------

        private object TryPathA_StaticRunBacktest(object template, List<string> diag)
        {
            var optType = Type.GetType("NinjaTrader.NinjaScript.Optimizers.Optimizer, NinjaTrader.Core");
            if (optType == null) { diag.Add("PathA: Optimizer type not found"); return null; }

            // Find the private static RunBacktest(StrategyBase, Parameter[]).
            var paramType = Type.GetType("NinjaTrader.NinjaScript.Optimizers.Parameter, NinjaTrader.Core")
                         ?? Type.GetType("NinjaTrader.NinjaScript.Parameter, NinjaTrader.Core");
            MethodInfo m = null;
            foreach (var c in optType.GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public))
            {
                if (!string.Equals(c.Name, "RunBacktest", StringComparison.Ordinal)) continue;
                var ps = c.GetParameters();
                if (ps.Length == 2) { m = c; break; }
            }
            if (m == null) { diag.Add("PathA: static RunBacktest(template,parameters[]) not found"); return null; }

            var ps2 = m.GetParameters();
            object emptyParams;
            try { emptyParams = Array.CreateInstance(ps2[1].ParameterType.GetElementType()
                                                     ?? paramType ?? typeof(object), 0); }
            catch { emptyParams = null; }

            diag.Add("PathA: invoking Optimizer.RunBacktest(template, Parameter[0])");
            object ret;
            try { ret = m.Invoke(null, new object[] { template, emptyParams }); }
            catch (TargetInvocationException tie)
            {
                AppendExceptionChain(diag, "PathA: Optimizer.RunBacktest threw", tie.InnerException ?? tie);
                throw;
            }
            diag.Add("PathA: returned " + (ret == null ? "null" : ret.GetType().FullName));
            // RunBacktest typically returns the backtested StrategyBase (possibly the same instance).
            return ret ?? template;
        }

        // ---------------------- Path A2: instance RunBacktest --------------

        private object TryPathA2_InstanceRunBacktest(object template, List<string> diag)
        {
            var t = template.GetType();
            // Look for a parameterless public StrategyBase.RunBacktest().
            var m = t.GetMethod("RunBacktest",
                                BindingFlags.Public | BindingFlags.Instance |
                                BindingFlags.FlattenHierarchy,
                                null, Type.EmptyTypes, null);
            if (m == null)
            {
                // Fall back to NonPublic (RunBacktestInternal).
                m = t.GetMethod("RunBacktestInternal",
                                BindingFlags.Public | BindingFlags.NonPublic |
                                BindingFlags.Instance | BindingFlags.FlattenHierarchy,
                                null, Type.EmptyTypes, null);
            }
            if (m == null) { diag.Add("PathA2: no instance RunBacktest()/RunBacktestInternal() found"); return null; }

            diag.Add("PathA2: invoking " + m.DeclaringType.FullName + "." + m.Name + "()");
            object ret;
            try { ret = m.Invoke(template, null); }
            catch (TargetInvocationException tie)
            {
                AppendExceptionChain(diag, "PathA2: " + m.Name + " threw", tie.InnerException ?? tie);
                throw;
            }
            diag.Add("PathA2: returned " + (ret == null ? "void/null" : ret.GetType().FullName));
            // RunBacktest()/RunBacktestInternal() typically return void; the
            // backtest state lives on the same StrategyBase instance.
            return template;
        }

        // ---------------------- Path B: subclass + lifecycle ---------------

        private object TryPathB_LifecycleSubclass(object template, List<string> diag, CancellationToken ct)
        {
            diag.Add("PathB: not yet implemented (would require runtime-emitted Optimizer subclass; " +
                     "Optimizer.ctor is protected and OnOptimize is protected internal)");
            // Implementing this cleanly requires either (a) shipping a small
            // helper Optimizer-subclass that lives in NinjaTrader.Custom.dll
            // (so 'protected internal' OnOptimize is reachable from the same
            // assembly), or (b) Reflection.Emit a runtime subclass. Both are
            // possible but out of scope for the first cut — Path A covers
            // the canonical Strategy-Analyzer single-shot semantics.
            return null;
        }

        // ---------------------- helpers ------------------------------------

        /// <summary>
        /// Walk the InnerException chain (incl. unwrapping TargetInvocationException)
        /// and emit one diagnostic line per frame: type, message, target site,
        /// and the first line of the stack trace. Loses nothing from the
        /// original exception so post-mortem on result.partial.json is enough
        /// to triage NT-side failures.
        /// </summary>
        private static void AppendExceptionChain(List<string> diag, string label, Exception ex)
        {
            int depth = 0;
            for (var cur = ex; cur != null && depth < 8; cur = cur.InnerException, depth++)
            {
                string indent = depth == 0 ? "" : new string(' ', depth * 2) + "-> ";
                string target = cur.TargetSite != null
                    ? (cur.TargetSite.DeclaringType?.FullName + "." + cur.TargetSite.Name)
                    : "<no target site>";
                diag.Add(label + (depth == 0 ? "" : (".inner[" + depth + "]")) +
                         ": " + indent + cur.GetType().FullName + ": " + cur.Message +
                         " @ " + target);
                string st = cur.StackTrace;
                if (!string.IsNullOrEmpty(st))
                {
                    // First two stack frames — enough to point at the offending NT code.
                    foreach (var line in st.Split(new[] { '\r', '\n' },
                                                  StringSplitOptions.RemoveEmptyEntries).Take(2))
                        diag.Add(label + ".stack: " + line.Trim());
                }
            }
        }

        /// <summary>
        /// Invoke the public NinjaScriptBase.SetState(State state) lifecycle
        /// hook by name ("SetDefaults" / "Configure" / "DataLoaded" / "Active").
        /// </summary>
        private static bool InvokeSetState(object obj, string stateName, List<string> diag)
        {
            try
            {
                var stateType = Type.GetType("NinjaTrader.NinjaScript.State, NinjaTrader.Core");
                if (stateType == null) { diag.Add("FATAL: SetState — NinjaScript.State type not found"); return false; }
                object stateValue = Enum.Parse(stateType, stateName, true);
                var m = obj.GetType().GetMethod("SetState",
                    BindingFlags.Public | BindingFlags.Instance | BindingFlags.FlattenHierarchy,
                    null, new[] { stateType }, null);
                if (m == null) { diag.Add("FATAL: SetState(" + stateName + ") method not found"); return false; }
                m.Invoke(obj, new[] { stateValue });
                diag.Add("SetState(" + stateName + "): ok");
                return true;
            }
            catch (TargetInvocationException tie)
            {
                AppendExceptionChain(diag, "FATAL: SetState(" + stateName + ")",
                                     tie.InnerException ?? tie);
                return false;
            }
            catch (Exception ex)
            {
                AppendExceptionChain(diag, "FATAL: SetState(" + stateName + ")", ex);
                return false;
            }
        }

        private static DateTime ParseDate(string s)
        {
            if (DateTime.TryParse(s, System.Globalization.CultureInfo.InvariantCulture,
                                  System.Globalization.DateTimeStyles.AssumeUniversal |
                                  System.Globalization.DateTimeStyles.AdjustToUniversal,
                                  out var dt))
                return dt;
            return DateTime.MinValue;
        }

        /// <summary>
        /// Diagnostic-only: enumerate every readable instance property whose
        /// name suggests it controls the backtest date/bar range, and emit
        /// "name : Type = value" to diag. Used to discover, on the actual
        /// NinjaTrader build at hand, which property StrategyBase.RunBacktest()
        /// truly honours (From/To, BacktestStartDate, DaysToLoad, BarsArray
        /// MinDate/MaxDate, etc.).
        /// </summary>
        private static void DumpDateRangeProperties(object obj, string label, List<string> diag)
        {
            if (obj == null) return;
            try
            {
                var t = obj.GetType();
                var rx = new System.Text.RegularExpressions.Regex(
                    "from|to|date|time|range|days|bars",
                    System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.NonPublic |
                                                  BindingFlags.Instance | BindingFlags.FlattenHierarchy)
                                   .OrderBy(x => x.Name))
                {
                    if (!p.CanRead) continue;
                    if (p.GetIndexParameters().Length > 0) continue;
                    if (!rx.IsMatch(p.Name)) continue;
                    string val;
                    try
                    {
                        var v = p.GetValue(obj, null);
                        val = v == null ? "<null>" : v.ToString();
                        if (val != null && val.Length > 80) val = val.Substring(0, 80) + "...";
                    }
                    catch (Exception ex) { val = "<get-threw " + ex.GetType().Name + ">"; }
                    diag.Add(label + ": " + p.Name + " : " + p.PropertyType.Name + " = " + val);
                }
            }
            catch (Exception ex)
            {
                diag.Add(label + ": dump failed — " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        /// <summary>
        /// Verify that all collected trades fall within the requested
        /// [from_utc, to_utc] window with a fixed ±1 day tolerance to absorb
        /// session/TZ boundary effects. Returns null on success, or an
        /// error string suitable for error.detail otherwise.
        /// </summary>
        private static string CheckPeriodInvariant(JObject job, JArray trades, List<string> diag)
        {
            if (trades == null || trades.Count == 0) return null;

            string fromStr = (string)job.SelectToken("period.from_utc");
            string toStr   = (string)job.SelectToken("period.to_utc");
            DateTime from  = ParseDate(fromStr);
            DateTime to    = ParseDate(toStr);
            if (from == DateTime.MinValue || to == DateTime.MinValue)
            {
                diag.Add("period_invariant: skipped (period dates unparseable)");
                return null;
            }

            // ±1 day tolerance for TZ/session boundary slip. Anything
            // beyond that is a real range mismatch.
            TimeSpan tol = TimeSpan.FromDays(1);
            DateTime lo = from - tol;
            DateTime hi = to   + tol;

            int before = 0, after = 0;
            DateTime firstEntry = DateTime.MaxValue, lastEntry = DateTime.MinValue;
            foreach (var jt in trades)
            {
                string es = (string)jt["entry_time_utc"];
                string xs = (string)jt["exit_time_utc"];
                DateTime et = ParseDate(es);
                DateTime xt = ParseDate(xs);
                if (et != DateTime.MinValue)
                {
                    if (et < firstEntry) firstEntry = et;
                    if (et > lastEntry)  lastEntry  = et;
                    if (et < lo) before++;
                    if (et > hi) after++;
                }
                if (xt != DateTime.MinValue && xt > hi) after++;
            }

            diag.Add("period_invariant: requested " + from.ToString("o") + " .. " + to.ToString("o"));
            diag.Add("period_invariant: trades_first_entry=" +
                     (firstEntry == DateTime.MaxValue ? "<none>" : firstEntry.ToString("o")) +
                     " trades_last_entry=" +
                     (lastEntry  == DateTime.MinValue ? "<none>" : lastEntry.ToString("o")));
            diag.Add("period_invariant: before_from=" + before + " after_to=" + after +
                     " (tolerance=" + tol.TotalDays + "d)");

            if (before > 0 || after > 0)
            {
                return "trades outside requested period: " + before +
                       " before from_utc, " + after + " after to_utc " +
                       "(first_entry=" + (firstEntry == DateTime.MaxValue ? "n/a" : firstEntry.ToString("o")) +
                       ", last_entry="  + (lastEntry  == DateTime.MinValue ? "n/a" : lastEntry.ToString("o")) +
                       ", requested_from=" + from.ToString("o") +
                       ", requested_to=" + to.ToString("o") + ")";
            }
            return null;
        }

        private static void TrySet(object obj, string prop, object value, List<string> diag)
        {
            try
            {
                var p = obj.GetType().GetProperty(prop,
                    BindingFlags.Public | BindingFlags.NonPublic |
                    BindingFlags.Instance | BindingFlags.FlattenHierarchy);
                if (p == null || !p.CanWrite) { diag.Add("set " + prop + ": no writable property"); return; }
                p.SetValue(obj, value, null);
                diag.Add("set " + prop + ": ok");
            }
            catch (Exception ex)
            {
                diag.Add("set " + prop + ": " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        /// <summary>
        /// Same as TrySet but returns false on any failure so the caller can
        /// abort BEFORE invoking RunBacktest with a half-configured template.
        /// </summary>
        private static bool TrySetRequired(object obj, string prop, object value, List<string> diag)
        {
            try
            {
                var p = obj.GetType().GetProperty(prop,
                    BindingFlags.Public | BindingFlags.NonPublic |
                    BindingFlags.Instance | BindingFlags.FlattenHierarchy);
                if (p == null || !p.CanWrite)
                {
                    diag.Add("FATAL: set " + prop + " — no writable property on " + obj.GetType().FullName);
                    return false;
                }
                p.SetValue(obj, value, null);
                diag.Add("set " + prop + ": ok");
                return true;
            }
            catch (Exception ex)
            {
                diag.Add("FATAL: set " + prop + ": " + ex.GetType().Name + ": " + ex.Message);
                return false;
            }
        }

        private static string SafeNtVersion()
        {
            try
            {
                var asm = AppDomain.CurrentDomain.GetAssemblies()
                    .FirstOrDefault(a => string.Equals(a.GetName().Name, "NinjaTrader.Core",
                                                       StringComparison.OrdinalIgnoreCase));
                return asm?.GetName().Version?.ToString() ?? "unknown";
            }
            catch { return "unknown"; }
        }

        private static JObject ExtractFinalParameters(object strategy, List<string> diag)
        {
            var jo = new JObject();
            if (strategy == null) return jo;
            try
            {
                // Surface ONLY properties carrying [NinjaScriptProperty] —
                // the same contract used by ApplyStrategyParameters.
                // This guarantees that result.final_parameters is always
                // exactly the set the user/AI is allowed to tune (and that
                // run_hash stays meaningful).
                var t = strategy.GetType();
                foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
                {
                    if (!p.CanRead || !p.CanWrite) continue;
                    bool hasNsProp = p.GetCustomAttributes(inherit: false)
                                      .Any(a => a.GetType().Name == "NinjaScriptPropertyAttribute");
                    if (!hasNsProp) continue;
                    var pt = p.PropertyType;
                    if (pt != typeof(int) && pt != typeof(double) && pt != typeof(bool) &&
                        pt != typeof(long) && pt != typeof(decimal) && pt != typeof(string) &&
                        !pt.IsEnum) continue;
                    try { jo[p.Name] = JToken.FromObject(p.GetValue(strategy, null)); }
                    catch { }
                }
            }
            catch (Exception ex) { diag.Add("final_parameters: " + ex.Message); }
            return jo;
        }

        private JobRunOutcome WriteFailure(string jobId, string runningDir,
                                           string errorType, string detail,
                                           List<string> diag, ResultBuilder rb,
                                           JObject job, Type strategyType)
        {
            // Even on failure we write a partial result.json so the operator
            // sees the diagnostic trail without having to dig in logs.
            try
            {
                var partial = rb.Build(jobId, job, strategyType,
                                       new JObject(), new JArray(), new JObject(), diag);
                partial["partial"] = true;
                partial["error"] = new JObject
                {
                    ["error_type"] = errorType,
                    ["message"]    = detail
                };
                AtomicFile.WriteAllText(Path.Combine(runningDir, "result.partial.json"),
                                        partial.ToString(Newtonsoft.Json.Formatting.Indented));
            }
            catch { /* best-effort */ }
            return JobRunOutcome.Failed(errorType, detail + "\n" + string.Join("\n", diag));
        }

        private static void WriteJobOutputs(string runningDir, JObject result, JArray trades)
        {
            AtomicFile.WriteAllText(Path.Combine(runningDir, "result.json"),
                                    result.ToString(Newtonsoft.Json.Formatting.Indented));
            AtomicFile.WriteAllText(Path.Combine(runningDir, "trades.json"),
                                    (trades ?? new JArray()).ToString(Newtonsoft.Json.Formatting.Indented));
            // raw.json: minimal raw bridge data (currently mirrors result.json sans warnings).
            var raw = (JObject)result.DeepClone();
            AtomicFile.WriteAllText(Path.Combine(runningDir, "raw.json"),
                                    raw.ToString(Newtonsoft.Json.Formatting.Indented));
        }
    }
}
