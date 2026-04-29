using System;
using System.Collections.Generic;
using System.Reflection;
using Newtonsoft.Json.Linq;

namespace NTAnalyzerBridge.Execution
{
    /// <summary>
    /// Best-effort dump of OHLCV bars from a backtested StrategyBase, so the
    /// UI can render a chart with trade markers without re-fetching data
    /// from NinjaTrader.
    ///
    /// Strategy:
    ///   1. strategy.BarsArray[0] -> NinjaTrader.Data.Bars
    ///   2. iterate by index (Bars.Count, GetTime/GetOpen/GetHigh/GetLow/
    ///      GetClose/GetVolume) — public API on Bars.
    ///   3. Clip to [from_utc, to_utc] requested period (matches the
    ///      period_invariant guard so chart and trades agree on the window).
    ///
    /// Anything that throws (or shape we can't recognise) is logged into
    /// Warnings; the collector silently produces an empty array. Caller
    /// decides whether to write bars.json.
    /// </summary>
    internal sealed class BarsCollector
    {
        public JArray Bars { get; } = new JArray();
        public List<string> Warnings { get; } = new List<string>();

        public bool Collect(object strategyBase, DateTime fromUtc, DateTime toUtc)
        {
            if (strategyBase == null)
            {
                Warnings.Add("bars_collector: strategy is null");
                return false;
            }

            object bars = ResolvePrimaryBars(strategyBase);
            if (bars == null)
            {
                Warnings.Add("bars_collector: BarsArray[0] not found / null");
                return false;
            }

            int count;
            try { count = (int)ReadProperty(bars, "Count"); }
            catch (Exception ex)
            {
                Warnings.Add("bars_collector: Bars.Count failed: " + ex.Message);
                return false;
            }
            if (count <= 0)
            {
                Warnings.Add("bars_collector: Bars.Count=0 — backtest produced no bars");
                return false;
            }

            var t = bars.GetType();
            MethodInfo mTime = t.GetMethod("GetTime",   new[] { typeof(int) });
            MethodInfo mOpen = t.GetMethod("GetOpen",   new[] { typeof(int) });
            MethodInfo mHigh = t.GetMethod("GetHigh",   new[] { typeof(int) });
            MethodInfo mLow  = t.GetMethod("GetLow",    new[] { typeof(int) });
            MethodInfo mCls  = t.GetMethod("GetClose",  new[] { typeof(int) });
            MethodInfo mVol  = t.GetMethod("GetVolume", new[] { typeof(int) });
            if (mTime == null || mOpen == null || mHigh == null ||
                mLow  == null || mCls  == null)
            {
                Warnings.Add("bars_collector: Bars Get* accessors not found via reflection");
                return false;
            }

            int kept = 0, skippedOutside = 0;
            // Bars.GetTime() returns local NinjaTrader time (per the user's
            // configured timezone). We treat it as already-UTC since the job
            // contract pins timezone="UTC" and the period_invariant check
            // applies the same convention. If the operator configured a
            // non-UTC NT installation that's a separate problem flagged by
            // the period_invariant guard.
            for (int i = 0; i < count; i++)
            {
                DateTime ts;
                try { ts = (DateTime)mTime.Invoke(bars, new object[] { i }); }
                catch { continue; }

                DateTime tsUtc = ts.Kind == DateTimeKind.Utc
                                    ? ts
                                    : DateTime.SpecifyKind(ts, DateTimeKind.Utc);
                if (tsUtc < fromUtc || tsUtc > toUtc)
                {
                    skippedOutside++;
                    continue;
                }

                double open, high, low, close;
                double volume = 0;
                try
                {
                    open  = (double)mOpen.Invoke(bars, new object[] { i });
                    high  = (double)mHigh.Invoke(bars, new object[] { i });
                    low   = (double)mLow .Invoke(bars, new object[] { i });
                    close = (double)mCls .Invoke(bars, new object[] { i });
                    if (mVol != null)
                    {
                        try { volume = Convert.ToDouble(mVol.Invoke(bars, new object[] { i })); }
                        catch { volume = 0; }
                    }
                }
                catch { continue; }

                Bars.Add(new JObject
                {
                    ["t"] = tsUtc.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                    ["o"] = open,
                    ["h"] = high,
                    ["l"] = low,
                    ["c"] = close,
                    ["v"] = volume,
                });
                kept++;
            }

            Warnings.Add(
                "bars_collector: kept=" + kept + " skipped_outside_period=" +
                skippedOutside + " bars_total=" + count);
            return kept > 0;
        }

        private static object ResolvePrimaryBars(object strategyBase)
        {
            // Prefer strategy.Bars (always primary series). Fallback to
            // strategy.BarsArray[0].
            object bars = ReadProperty(strategyBase, "Bars");
            if (bars != null) return bars;

            object arr = ReadProperty(strategyBase, "BarsArray");
            if (arr is Array a && a.Length > 0)
                return a.GetValue(0);
            return null;
        }

        private static object ReadProperty(object obj, string name)
        {
            if (obj == null) return null;
            try
            {
                var p = obj.GetType().GetProperty(
                    name, BindingFlags.Public | BindingFlags.Instance);
                return p?.GetValue(obj, null);
            }
            catch { return null; }
        }
    }
}
