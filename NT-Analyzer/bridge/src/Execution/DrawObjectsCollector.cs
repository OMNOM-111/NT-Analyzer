using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using Newtonsoft.Json.Linq;

namespace NTAnalyzerBridge.Execution
{
    /// <summary>
    /// Best-effort, universal exporter of NinjaScript Draw.* objects from a
    /// backtested strategy.
    ///
    /// Reality check: a lot of Draw.* APIs no-op when ChartControl == null,
    /// which is the norm for headless RunBacktest. We still try, because some
    /// strategies maintain their own draw object collection (e.g. by reusing
    /// the strategy.DrawObjects collection that NinjaScript exposes), and at
    /// minimum we want to write a deterministic empty file with a diagnostic
    /// reason instead of silently leaving the artifact missing.
    ///
    /// Schema (draw_objects.json):
    ///   { "version": 1, "objects": [ { id, type, tag, label, time1, price1,
    ///     time2, price2, points: [...], color, fill, strokeWidth, dash,
    ///     text, source, visible } ] }
    /// </summary>
    internal sealed class DrawObjectsCollector
    {
        public JArray Objects { get; } = new JArray();
        public List<string> Warnings { get; } = new List<string>();

        public void Collect(object strategy)
        {
            if (strategy == null)
            {
                Warnings.Add("draw_objects: strategy is null");
                return;
            }
            // NinjaScript stores Draw.* outputs in StrategyBase.DrawObjects.
            // It is an IEnumerable of NinjaTrader.NinjaScript.DrawingTools.IDrawingTool.
            object coll = ReadProperty(strategy, "DrawObjects")
                       ?? ReadProperty(strategy, "ChartObjects");
            if (coll == null)
            {
                Warnings.Add("draw_objects: strategy.DrawObjects not found (NT API exposes neither DrawObjects nor ChartObjects on this build)");
                return;
            }

            int total = 0;
            int written = 0;
            var typeCounts = new Dictionary<string, int>(StringComparer.Ordinal);
            var skipReasons = new Dictionary<string, int>(StringComparer.Ordinal);

            foreach (var obj in (IEnumerable)coll)
            {
                if (obj == null) continue;
                total++;
                try
                {
                    JObject jo = ConvertOne(obj);
                    if (jo == null)
                    {
                        Inc(skipReasons, "no_handler");
                        continue;
                    }
                    Objects.Add(jo);
                    written++;
                    Inc(typeCounts, (string)jo["type"] ?? "unknown");
                }
                catch (Exception ex)
                {
                    Inc(skipReasons, ex.GetType().Name);
                }
            }

            Warnings.Add("draw_objects: scanned " + total + ", exported " + written);
            foreach (var kv in typeCounts)
                Warnings.Add("draw_objects: type '" + kv.Key + "' = " + kv.Value);
            foreach (var kv in skipReasons)
                Warnings.Add("draw_objects: skipped '" + kv.Key + "' = " + kv.Value);
            if (total == 0)
            {
                Warnings.Add("draw_objects: collection is empty " +
                    "(NinjaScript Draw.* skips when ChartControl == null in headless RunBacktest; " +
                    "strategies that don't maintain their own draw collection won't appear here)");
            }
        }

        // Map a NinjaScript drawing tool object to the universal schema.
        // Falls back to type name + best-effort tag/label when the type is
        // unrecognised, so the UI at least sees *something* per object.
        private static JObject ConvertOne(object obj)
        {
            Type t = obj.GetType();
            string typeName = t.Name;       // e.g. HorizontalLine, Line, Rectangle, Region, Text, Arrow
            string mapped = MapType(typeName);
            string tag    = ReadProperty(obj, "Tag") as string ?? "";
            string label  = ReadProperty(obj, "DisplayName") as string ?? "";
            string text   = ReadProperty(obj, "Text") as string ?? "";

            // Anchors: NT 8 stores these as ChartAnchor objects on properties
            // named StartAnchor/EndAnchor (Line, Rectangle, Ray) or just
            // Anchor (HorizontalLine, Text). Some types have an Anchors
            // IEnumerable instead.
            var pts = new JArray();
            TryAddAnchor(pts, ReadProperty(obj, "StartAnchor"));
            TryAddAnchor(pts, ReadProperty(obj, "EndAnchor"));
            if (pts.Count == 0) TryAddAnchor(pts, ReadProperty(obj, "Anchor"));
            if (pts.Count == 0)
            {
                var anchors = ReadProperty(obj, "Anchors") as IEnumerable;
                if (anchors != null) foreach (var a in anchors) TryAddAnchor(pts, a);
            }

            string color = ColorOf(ReadProperty(obj, "Stroke")
                                ?? ReadProperty(obj, "OutlineStroke")
                                ?? ReadProperty(obj, "TextColor"));
            string fill  = ColorOf(ReadProperty(obj, "AreaBrush")
                                ?? ReadProperty(obj, "Fill"));
            int    width = ToInt(ReadProperty(ReadProperty(obj, "Stroke"), "Width")) ?? 1;

            var jo = new JObject
            {
                ["id"]          = tag != "" ? tag : (typeName + "_" + Math.Abs(obj.GetHashCode())),
                ["type"]        = mapped,
                ["tag"]         = tag,
                ["label"]       = label,
                ["color"]       = color ?? "#ffaa00",
                ["fill"]        = fill,
                ["strokeWidth"] = width,
                ["text"]        = text,
                ["source"]      = "strategy",
                ["visible"]     = true,
                ["points"]      = pts,
                ["nt_type"]     = typeName,
            };
            // Convenience time1/price1/time2/price2 mirrors of points[0..1].
            if (pts.Count >= 1)
            {
                jo["time1"]  = pts[0]?["time"];
                jo["price1"] = pts[0]?["price"];
            }
            if (pts.Count >= 2)
            {
                jo["time2"]  = pts[1]?["time"];
                jo["price2"] = pts[1]?["price"];
            }
            return jo;
        }

        private static string MapType(string ntType)
        {
            switch (ntType)
            {
                case "HorizontalLine": return "horizontal_line";
                case "VerticalLine":   return "vertical_line";
                case "Ray":            return "ray";
                case "Line":           return "line";
                case "TrendLine":      return "line";
                case "Rectangle":      return "rectangle";
                case "Region":         return "region";
                case "Text":
                case "TextFixed":      return "text";
                case "ArrowUp":
                case "ArrowDown":
                case "Arrow":          return "arrow";
                case "Dot":
                case "Diamond":
                case "Square":
                case "Triangle":       return "marker";
            }
            return ntType.ToLowerInvariant();
        }

        private static void TryAddAnchor(JArray pts, object anchor)
        {
            if (anchor == null) return;
            object t = ReadProperty(anchor, "Time");
            object p = ReadProperty(anchor, "Price");
            if (t == null && p == null) return;
            string iso = null;
            if (t is DateTime dt) iso = dt.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ");
            double? price = ToDouble(p);
            pts.Add(new JObject
            {
                ["time"]  = iso,
                ["price"] = price.HasValue ? (JToken)price.Value : JValue.CreateNull(),
            });
        }

        private static string ColorOf(object brushOrColor)
        {
            if (brushOrColor == null) return null;
            // NT 8 uses Stroke wrappers — try .Brush.Color first.
            object inner = ReadProperty(brushOrColor, "Brush") ?? brushOrColor;
            object color = ReadProperty(inner, "Color") ?? inner;
            // System.Windows.Media.Color exposes A/R/G/B byte properties.
            int? a = ToInt(ReadProperty(color, "A"));
            int? r = ToInt(ReadProperty(color, "R"));
            int? g = ToInt(ReadProperty(color, "G"));
            int? b = ToInt(ReadProperty(color, "B"));
            if (r.HasValue && g.HasValue && b.HasValue)
            {
                if (a.HasValue && a.Value < 255)
                    return "rgba(" + r + "," + g + "," + b + "," +
                           (a.Value / 255.0).ToString("0.00",
                               System.Globalization.CultureInfo.InvariantCulture) + ")";
                return "#" + r.Value.ToString("X2") + g.Value.ToString("X2") + b.Value.ToString("X2");
            }
            return null;
        }

        private static object ReadProperty(object o, string name)
        {
            if (o == null || string.IsNullOrEmpty(name)) return null;
            try
            {
                var p = o.GetType().GetProperty(name,
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.FlattenHierarchy);
                if (p != null) return p.GetValue(o, null);
                var f = o.GetType().GetField(name,
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.FlattenHierarchy);
                return f?.GetValue(o);
            }
            catch { return null; }
        }

        private static int? ToInt(object v)
        {
            if (v == null) return null;
            try { return Convert.ToInt32(v); } catch { return null; }
        }
        private static double? ToDouble(object v)
        {
            if (v == null) return null;
            try { return Convert.ToDouble(v); } catch { return null; }
        }
        private static void Inc(Dictionary<string, int> d, string k)
        {
            d[k] = (d.TryGetValue(k, out int n) ? n : 0) + 1;
        }
    }
}
