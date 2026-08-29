using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Execution
{
    /// <summary>
    /// Pulls trades + basic metrics off a backtested StrategyBase via reflection.
    ///
    /// NinjaTrader's SystemPerformance API has changed shape between minor
    /// builds (AllTrades vs Performance.Currency.AllTrades vs ...), so we
    /// probe a couple of well-known paths and degrade to verification_warnings
    /// when something is missing instead of throwing.
    ///
    /// Output shape mirrors result.json contract v0.1:
    ///   trades : JArray of { trade_no, direction, entry_time_utc, entry_price,
    ///                        exit_time_utc, exit_price, quantity,
    ///                        pnl_currency, pnl_ticks }
    ///   metrics: JObject with trade_count, winning_pct, gross_profit,
    ///                        gross_loss, net_profit, profit_factor, max_drawdown
    /// </summary>
    internal sealed class TradeCollector
    {
        public JArray Trades { get; } = new JArray();
        public JObject Metrics { get; } = new JObject();
        public List<string> Warnings { get; } = new List<string>();

        /// <summary>
        /// When false (default), the noisy `metrics_shape` reflection dump
        /// is suppressed. The short "metric not found / fallback used"
        /// lines are still emitted. Toggled by
        /// BridgeConfig.EnableVerboseDiagnostics.
        /// </summary>
        public bool EnableVerboseDiagnostics { get; set; } = false;

        // A finished backtest can hold tens of thousands of trades, and
        // walking them is our own work, not NinjaTrader's. Checking once at
        // the start would mean a cancel arriving on the second trade is only
        // honoured after the forty-eight thousandth.
        private const int CancelCheckEveryTrades = 256;

        public bool Collect(object strategyBase)
        {
            return Collect(strategyBase, CancellationToken.None);
        }

        public bool Collect(object strategyBase, CancellationToken ct)
        {
            if (strategyBase == null)
            {
                Warnings.Add("trade_collector: strategy is null");
                return false;
            }

            object sp = ReadProperty(strategyBase, "SystemPerformance");
            if (sp == null)
            {
                Warnings.Add("trade_collector: StrategyBase.SystemPerformance is null");
                return false;
            }

            // Find the BEST trade collection: probe known paths, count items,
            // pick the one with the most items. Empty enumerables no longer
            // win over later, populated ones.
            object tradeCollection = ProbeTradeCollection(sp);
            if (tradeCollection == null)
            {
                Warnings.Add("trade_collector: no Trade-bearing IEnumerable found on SystemPerformance");
                DumpSystemPerformanceShape(sp);
            }
            else
            {
                ExtractTrades(tradeCollection, ct);
            }

            object metricsHost = ProbeMetricsHost(sp);
            if (metricsHost == null)
            {
                Warnings.Add("trade_collector: no metrics host found on SystemPerformance");
            }
            else
            {
                ExtractMetrics(metricsHost);
            }

            // If we got metrics but no trades, dump the SystemPerformance shape
            // anyway so the operator can see exactly which property holds the
            // populated trade list in this NT build.
            if (Trades.Count == 0 && Metrics.Properties().Any())
            {
                Warnings.Add("trade_collector: 0 trades extracted but metrics non-empty \u2014 dumping SystemPerformance shape:");
                DumpSystemPerformanceShape(sp);
            }

            return Trades.Count > 0 || Metrics.Properties().Any();
        }

        private object ProbeTradeCollection(object sp)
        {
            // Known candidate paths (known names from various NT8 builds).
            var paths = new[]
            {
                "AllTrades",                             // sp.AllTrades is itself IEnumerable<Trade>
                "AllTrades.Trades",
                "Performance.AllTrades",
                "Performance.AllTrades.Trades",
                "RealTimeTrades",
                "RealTimeTrades.Trades"
            };

            object best = null;
            int bestCount = 0;
            string bestPath = null;
            foreach (var path in paths)
            {
                object v = ReadPath(sp, path);
                if (!(v is IEnumerable e) || v is string) continue;
                int cnt = TryCount(v);
                if (cnt > bestCount)
                {
                    best = v;
                    bestCount = cnt;
                    bestPath = path;
                }
            }

            if (best == null)
            {
                // Last-resort generic walk: look at every property on
                // SystemPerformance whose runtime value is an IEnumerable
                // of items whose type name contains "Trade".
                foreach (var p in sp.GetType().GetProperties(BindingFlags.Public | BindingFlags.Instance))
                {
                    object v;
                    try { v = p.GetValue(sp, null); } catch { continue; }
                    if (!(v is IEnumerable e) || v is string) continue;
                    int cnt = TryCount(v);
                    if (cnt == 0) continue;
                    string elemTypeName = FirstItemTypeName(v);
                    if (elemTypeName == null ||
                        elemTypeName.IndexOf("Trade", StringComparison.OrdinalIgnoreCase) < 0) continue;
                    if (cnt > bestCount)
                    {
                        best = v;
                        bestCount = cnt;
                        bestPath = p.Name + " (generic walk, element=" + elemTypeName + ")";
                    }
                }
            }

            if (best != null)
                Warnings.Add("trade_collector: chose collection at sp." + bestPath + " (count=" + bestCount + ")");
            return best;
        }

        private static int TryCount(object enumerable)
        {
            // Prefer an O(1) Count property if present.
            var t = enumerable.GetType();
            var cp = t.GetProperty("Count", BindingFlags.Public | BindingFlags.Instance);
            if (cp != null && cp.PropertyType == typeof(int))
            {
                try { return (int)cp.GetValue(enumerable, null); } catch { }
            }
            // Fall back to iteration but cap to avoid surprises.
            int n = 0;
            try
            {
                foreach (var _ in (IEnumerable)enumerable)
                {
                    n++;
                    if (n > 10_000_000) break;
                }
            }
            catch { return -1; }
            return n;
        }

        private static string FirstItemTypeName(object enumerable)
        {
            try
            {
                foreach (var item in (IEnumerable)enumerable)
                {
                    if (item != null) return item.GetType().FullName;
                }
            }
            catch { }
            return null;
        }

        private void DumpSystemPerformanceShape(object sp)
        {
            try
            {
                var t = sp.GetType();
                Warnings.Add("trade_collector.shape: SystemPerformance type = " + t.FullName);
                foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
                {
                    string vinfo;
                    object v = null;
                    try { v = p.GetValue(sp, null); }
                    catch (Exception ex) { Warnings.Add("trade_collector.shape:   " + p.Name + " : <get threw " + ex.GetType().Name + ">"); continue; }
                    if (v == null) { vinfo = "null"; }
                    else if (v is IEnumerable && !(v is string))
                    {
                        int c = TryCount(v);
                        string en = FirstItemTypeName(v) ?? "?";
                        vinfo = "IEnumerable<" + en + ">  count=" + c;
                    }
                    else { vinfo = v.GetType().FullName; }
                    Warnings.Add("trade_collector.shape:   " + p.Name + " : " + p.PropertyType.FullName + " = " + vinfo);
                }
            }
            catch (Exception ex) { Warnings.Add("trade_collector.shape: dump failed " + ex.Message); }
        }

        private object ProbeMetricsHost(object sp)
        {
            foreach (var path in new[]
                     {
                         "AllTrades.TradesPerformance",
                         "AllTrades.Performance",
                         "Performance.AllTrades.TradesPerformance",
                         "Performance.Currency",
                         "Performance"
                     })
            {
                object v = ReadPath(sp, path);
                if (v != null) return v;
            }
            return null;
        }

        private void ExtractTrades(object tradeCollection, CancellationToken ct)
        {
            int n = 0;
            foreach (var t in (IEnumerable)tradeCollection)
            {
                if (t == null) continue;
                n++;
                if (n % CancelCheckEveryTrades == 0) ct.ThrowIfCancellationRequested();
                try
                {
                    Trades.Add(BuildTradeJson(t, n));
                }
                catch (Exception ex)
                {
                    Warnings.Add("trade_collector: failed to read trade #" + n + ": " + ex.Message);
                }
            }
        }

        private JObject BuildTradeJson(object trade, int n)
        {
            // NinjaTrader Trade type members (typical):
            //   .Entry : Execution { .Time, .Price, .MarketPosition, .Quantity }
            //   .Exit  : Execution { .Time, .Price }
            //   .Quantity, .ProfitCurrency, .ProfitPoints, .ProfitTicks
            object entry = ReadProperty(trade, "Entry");
            object exit  = ReadProperty(trade, "Exit");

            string dir = "unknown";
            object mp = ReadProperty(entry, "MarketPosition");
            if (mp != null)
            {
                string s = mp.ToString();
                if (s.IndexOf("Long",  StringComparison.OrdinalIgnoreCase) >= 0) dir = "long";
                else if (s.IndexOf("Short", StringComparison.OrdinalIgnoreCase) >= 0) dir = "short";
            }

            return new JObject
            {
                ["trade_no"]       = n,
                ["direction"]      = dir,
                ["entry_time_utc"] = ToIsoUtc(ReadProperty(entry, "Time")),
                ["entry_price"]    = ToDouble(ReadProperty(entry, "Price")),
                ["exit_time_utc"]  = ToIsoUtc(ReadProperty(exit,  "Time")),
                ["exit_price"]     = ToDouble(ReadProperty(exit,  "Price")),
                ["quantity"]       = ToInt(ReadProperty(trade, "Quantity")),
                ["pnl_currency"]   = ToDouble(ReadProperty(trade, "ProfitCurrency")),
                ["pnl_ticks"]      = ToInt(ReadProperty(trade, "ProfitTicks")),
                // Per-trade commission as charged by NT for the round trip
                // (Entry.Commission + Exit.Commission). Falls back to a direct
                // Trade.Commission if NT exposes one. Used by UI to compute
                // per-side commission totals in Performance Summary.
                ["commission"]     = ToDouble(ReadCommission(trade, entry, exit))
            };
        }

        // Sum up commission across the trade's executions. NT 8 stores
        // commission on Execution objects; some builds also expose a
        // Trade.Commission shortcut. Returns null if nothing is found.
        private static object ReadCommission(object trade, object entry, object exit)
        {
            double sum = 0;
            bool any = false;
            foreach (var src in new[] { trade, entry, exit })
            {
                if (src == null) continue;
                var v = ReadProperty(src, "Commission");
                if (v == null) continue;
                try { sum += Convert.ToDouble(v); any = true; }
                catch { /* ignore non-numeric */ }
                // Avoid double-counting: if Trade.Commission already
                // represents the round trip, don't add Entry/Exit too.
                if (ReferenceEquals(src, trade) && Math.Abs(sum) > 0) break;
            }
            return any ? (object)sum : null;
        }

        private void ExtractMetrics(object host)
        {
            // NT 8.1.6.3 shape (verified via DumpMetricsHostShape):
            //   host = NinjaTrader.Cbi.TradesPerformance
            //     .TradesCount              : int
            //     .GrossProfit / .GrossLoss / .NetProfit / .ProfitFactor : double
            //     .Currency / .Percent / .Pips / .Points / .Ticks : TradesPerformanceValues
            //   TradesPerformanceValues exposes per-unit fields like
            //   .MaxDrawDown, .Winners (count), and friends.
            TrySetMetric("trade_count",   host, "TradesCount", "Count");
            TrySetMetric("gross_profit",  host, "GrossProfit");
            TrySetMetric("gross_loss",    host, "GrossLoss");
            TrySetMetric("net_profit",    host, "NetProfit");
            TrySetMetric("profit_factor", host, "ProfitFactor");
            // Aggregate commission charged across all trades. NT 8.1.6.3
            // exposes it as TradesPerformance.Commission (positive number).
            TrySetMetric("commission",    host, "Commission", "TotalCommission");

            // First try direct names on host (older NT builds may flatten these).
            TrySetMetric("winning_pct", host, "PercentWinningTrades", "WinningPercent", "PercentProfitable");

            // NT 8.1.6.3: winning count is on the Percent wrapper (already a
            // ratio in [0..1]) or computable from Currency.Winners / TradesCount.
            if (Metrics["winning_pct"] == null)
            {
                object percentWrapper = ReadProperty(host, "Percent");
                if (percentWrapper != null)
                {
                    foreach (var name in new[] { "Winners", "PercentProfitable", "WinPercent", "Profitable" })
                    {
                        object v = ReadProperty(percentWrapper, name);
                        double? d = ToDoubleOrNull(v);
                        if (d.HasValue)
                        {
                            // NT typically stores 0.51 to mean 51%. Normalize.
                            double pct = Math.Abs(d.Value) <= 1.0001 ? d.Value * 100.0 : d.Value;
                            Metrics["winning_pct"] = Math.Round(pct, 4);
                            Warnings.Add("trade_collector: winning_pct from Percent." + name + " = " + d.Value);
                            break;
                        }
                    }
                }
            }

            // Fallback: WinningTrades on host or Currency.Winners / TradesCount.
            if (Metrics["winning_pct"] == null)
            {
                int? total = ToIntOrNull(Metrics["trade_count"]);
                int? win = ToIntOrNull(ReadProperty(host, "WinningTrades"));
                if (!win.HasValue)
                {
                    object cur = ReadProperty(host, "Currency");
                    if (cur != null) win = ToIntOrNull(ReadProperty(cur, "Winners"));
                }
                if (win.HasValue && total.HasValue && total.Value > 0)
                {
                    Metrics["winning_pct"] = Math.Round(100.0 * win.Value / total.Value, 4);
                    Warnings.Add("trade_collector: winning_pct computed from Winners/TradesCount = " +
                                 win.Value + "/" + total.Value);
                }
            }

            // max_drawdown: NT 8.1.6.3 exposes it as Currency.MaxDrawDown (negative double).
            TrySetMetric("max_drawdown", host,
                "MaxDrawDownDollars", "DrawDownDollars",
                "MaxDrawDownCurrency", "DrawDownCurrency",
                "MaxDrawDownValue", "DrawDownValue");
            if (Metrics["max_drawdown"] == null)
            {
                object cur = ReadProperty(host, "Currency");
                if (cur != null)
                {
                    foreach (var name in new[] { "MaxDrawDown", "DrawDown", "MaxDrawdown", "Drawdown" })
                    {
                        double? d = ToDoubleOrNull(ReadProperty(cur, name));
                        if (d.HasValue) { Metrics["max_drawdown"] = d.Value; Warnings.Add("trade_collector: max_drawdown from Currency." + name); break; }
                    }
                }
            }
            if (Metrics["max_drawdown"] == null)
            {
                foreach (var name in new[] { "MaxDrawDown", "DrawDown" })
                {
                    object dd = ReadProperty(host, name);
                    if (dd == null) continue;
                    object dv = ReadProperty(dd, "Currency");
                    if (dv == null) dv = ReadProperty(dd, "Value");
                    if (dv == null) dv = ReadProperty(dd, "Dollars");
                    double? n = ToDoubleOrNull(dv);
                    if (n.HasValue) { Metrics["max_drawdown"] = n.Value; break; }
                }
            }
            if (Metrics["max_drawdown"] == null)
            {
                Warnings.Add("trade_collector: max_drawdown not extracted (NT 8.1.x property name unknown for this build)");
            }

            // If either of the build-dependent metrics is still missing, dump
            // the metrics host shape so we can learn the real property names
            // for this NT build. Verbose-only — by default the short
            // "metric not found / fallback used" lines are enough.
            if (EnableVerboseDiagnostics &&
                (Metrics["winning_pct"] == null || Metrics["max_drawdown"] == null))
            {
                DumpMetricsHostShape(host);
                // Also dump the Currency / Percent wrappers to learn the real
                // nested property names (NT 8.1.6.3 hides Winners/Losers there).
                foreach (var wrapName in new[] { "Currency", "Percent" })
                {
                    object w = ReadProperty(host, wrapName);
                    if (w != null) DumpMetricsHostShape(w);
                }
            }
        }

        // Last-resort winning_pct: count trades with positive pnl_currency from
        // the already-collected Trades list. NT 8.1.6.3 does not expose
        // WinningTrades/Winners on the public TradesPerformance surface.
        public void FinaliseWinningPctFromTrades()
        {
            if (Metrics["winning_pct"] != null) return;
            if (Trades.Count == 0) return;
            int win = 0;
            int total = 0;
            foreach (var t in Trades)
            {
                var pnl = t["pnl_currency"];
                if (pnl == null || pnl.Type == JTokenType.Null) continue;
                total++;
                if ((double)pnl > 0) win++;
            }
            if (total > 0)
            {
                Metrics["winning_pct"] = Math.Round(100.0 * win / total, 4);
                Warnings.Add("trade_collector: winning_pct computed from collected trades = " + win + "/" + total);
            }
        }

        private void DumpMetricsHostShape(object host)
        {
            try
            {
                var t = host.GetType();
                Warnings.Add("trade_collector.metrics_shape: host type = " + t.FullName);
                foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
                {
                    object v = null;
                    string vinfo;
                    try { v = p.GetValue(host, null); }
                    catch (Exception ex) { Warnings.Add("trade_collector.metrics_shape:   " + p.Name + " : <get threw " + ex.GetType().Name + ">"); continue; }
                    if (v == null) vinfo = "null";
                    else if (v is string s) vinfo = "\"" + s + "\"";
                    else if (v is IEnumerable && !(v is string)) vinfo = "IEnumerable count=" + TryCount(v);
                    else vinfo = v.ToString();
                    Warnings.Add("trade_collector.metrics_shape:   " + p.Name + " : " + p.PropertyType.Name + " = " + vinfo);
                }
            }
            catch (Exception ex) { Warnings.Add("trade_collector.metrics_shape: dump failed " + ex.Message); }
        }

        private static int? ToIntOrNull(object v)
        {
            if (v == null) return null;
            if (v is JToken jt)
            {
                if (jt.Type == JTokenType.Integer) return (int)jt;
                if (jt.Type == JTokenType.Float)   return (int)(double)jt;
                return null;
            }
            try { return Convert.ToInt32(v); } catch { return null; }
        }

        private static double? ToDoubleOrNull(object v)
        {
            if (v == null) return null;
            try { return Convert.ToDouble(v); } catch { return null; }
        }

        private void TrySetMetric(string outName, object host, params string[] candidates)
        {
            foreach (var name in candidates)
            {
                object v = ReadProperty(host, name);
                if (v == null) continue;
                try
                {
                    if (v is double d)       Metrics[outName] = d;
                    else if (v is float f)   Metrics[outName] = (double)f;
                    else if (v is int i)     Metrics[outName] = i;
                    else if (v is long l)    Metrics[outName] = l;
                    else if (v is decimal m) Metrics[outName] = (double)m;
                    else                     Metrics[outName] = Convert.ToDouble(v);
                    return;
                }
                catch { /* fall through, try next candidate */ }
            }
            Warnings.Add("trade_collector: metric '" + outName + "' not found (tried: " +
                         string.Join(",", candidates) + ")");
        }

        // ------- reflection helpers --------------------------------------

        private static object ReadPath(object obj, string dottedPath)
        {
            object cur = obj;
            foreach (var part in dottedPath.Split('.'))
            {
                if (cur == null) return null;
                cur = ReadProperty(cur, part);
            }
            return cur;
        }

        private static object ReadProperty(object obj, string name)
        {
            if (obj == null || string.IsNullOrEmpty(name)) return null;
            try
            {
                var t = obj.GetType();
                var p = t.GetProperty(name,
                    BindingFlags.Public | BindingFlags.NonPublic |
                    BindingFlags.Instance | BindingFlags.FlattenHierarchy);
                if (p != null) return p.GetValue(obj, null);

                var f = t.GetField(name,
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                if (f != null) return f.GetValue(obj);
            }
            catch { }
            return null;
        }

        private static JToken ToIsoUtc(object o)
        {
            if (o is DateTime dt)
            {
                var u = dt.Kind == DateTimeKind.Utc ? dt : dt.ToUniversalTime();
                return u.ToString("yyyy-MM-ddTHH:mm:ssZ");
            }
            return JValue.CreateNull();
        }

        private static JToken ToDouble(object o)
        {
            if (o == null) return JValue.CreateNull();
            try { return Convert.ToDouble(o); } catch { return JValue.CreateNull(); }
        }

        private static JToken ToInt(object o)
        {
            if (o == null) return JValue.CreateNull();
            try { return Convert.ToInt32(o); } catch { return JValue.CreateNull(); }
        }
    }
}
