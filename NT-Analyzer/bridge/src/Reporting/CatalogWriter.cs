using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Reporting
{
    /// <summary>
    /// On AddOn startup, dumps two JSON catalogs into
    /// &lt;project_root&gt;\data\catalog\:
    ///   strategies.json   – whitelisted strategies + [NinjaScriptProperty] params
    ///   instruments.json  – instruments that have local NT minute data
    /// The Python backend reads these to populate the Run form.
    /// All operations are best-effort: failures are logged, never thrown.
    /// </summary>
    internal static class CatalogWriter
    {
        private const string NS_PROPERTY_ATTR = "NinjaTrader.NinjaScript.NinjaScriptPropertyAttribute";
        private const string RANGE_ATTR       = "System.ComponentModel.DataAnnotations.RangeAttribute";
        private const string DISPLAY_ATTR     = "System.ComponentModel.DataAnnotations.DisplayAttribute";

        public static void WriteAll(string projectRoot, string ntUserDir,
                                    IReadOnlyList<Type> strategyTypes)
        {
            try
            {
                if (string.IsNullOrWhiteSpace(projectRoot)) return;
                string dir = Path.Combine(projectRoot, "data", "catalog");
                Directory.CreateDirectory(dir);

                WriteStrategies(Path.Combine(dir, "strategies.json"),
                                strategyTypes ?? new List<Type>(), ntUserDir);
                WriteInstruments(Path.Combine(dir, "instruments.json"), ntUserDir);
                WriteTemplates(Path.Combine(dir, "templates.json"), ntUserDir);
                BridgeLog.Info("CatalogWriter: wrote " + dir);
            }
            catch (Exception ex)
            {
                BridgeLog.Error("CatalogWriter.WriteAll failed", ex);
            }
        }

        /// <summary>
        /// Compact device-backed catalog for the existing Connector
        /// snapshot_runtime command. Parameter schemas stay local in this first
        /// bounded projection: pretending an omitted schema was an empty schema
        /// would make the server accept inputs the device never advertised.
        /// </summary>
        public static JObject BuildConnectorCatalog(
            string ntUserDir, IReadOnlyList<Type> strategyTypes)
        {
            return BuildConnectorCatalogPage(ntUserDir, strategyTypes, 0);
        }

        /// <summary>
        /// One signed page of the runtime catalog. The server assembles the
        /// pages of a single catalog_id and activates them atomically, so a
        /// half-delivered snapshot never replaces a working catalog.
        /// </summary>
        public static JObject BuildConnectorCatalogPage(
            string ntUserDir, IReadOnlyList<Type> strategyTypes, int pageIndex)
        {
            JArray strategies = new JArray();
            foreach (Type type in (strategyTypes ?? new List<Type>()).OrderBy(t => t.Name))
            {
                try
                {
                    Dictionary<string, object> full = BuildStrategyEntry(type, ntUserDir);
                    strategies.Add(new JObject
                    {
                        ["class_name"] = Convert.ToString(full["class_name"]),
                        ["display_name"] = Convert.ToString(full["display_name"]),
                        ["stable_id"] = Convert.ToString(full["stable_id"]),
                    });
                }
                catch (Exception ex)
                {
                    BridgeLog.Warn("Connector catalog skipped " + type.FullName + ": " + ex.Message);
                }
            }

            List<string> notes = new List<string>();
            JArray commission = JArray.FromObject(
                ScanCommissionTemplates(ntUserDir, notes, false));

            // Concrete contracts, not bare roots. A server has no NinjaTrader
            // database, so without these it can only offer "MNQ" and every
            // backtest fails on an unresolvable contract month.
            // Instruments get whatever the 16 KiB command result has left after
            // the strategies and templates, so a large Strategies folder can
            // never push the whole snapshot over the transport cap.
            int scannedTotal;
            List<JObject> ordered = BuildConnectorInstruments(ntUserDir, out scannedTotal);
            string generatedAt = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
            string catalogId = ComputeCatalogId(ordered, generatedAt);

            // Page 0 carries strategies and templates so later pages stay small.
            List<List<JObject>> pages = PaginateInstruments(
                ordered,
                strategies.ToString(Formatting.None).Length
                + commission.ToString(Formatting.None).Length);
            if (pages.Count == 0) pages.Add(new List<JObject>());
            if (pageIndex < 0 || pageIndex >= pages.Count) pageIndex = 0;
            bool first = pageIndex == 0;

            JArray instruments = new JArray();
            foreach (JObject row in pages[pageIndex]) instruments.Add(row);

            int strategyCount = strategies.Count;
            int templateCount = commission.Count;
            JObject doc = new JObject
            {
                ["schema_version"] = 1,
                ["generated_at_utc"] = generatedAt,
                ["catalog_id"] = catalogId,
                ["page_index"] = pageIndex,
                ["page_count"] = pages.Count,
                ["total_count"] = ordered.Count,
                ["strategies"] = first ? strategies : new JArray(),
                ["commission_templates"] = first ? commission : new JArray(),
                ["instruments"] = instruments,
                ["strategy_count"] = first ? strategyCount : 0,
                ["commission_template_count"] = first ? templateCount : 0,
                ["instrument_count"] = instruments.Count,
                ["instruments_scanned"] = scannedTotal,
                ["instruments_truncated"] = false,
                ["parameter_schemas_included"] = false,
                ["truncated"] = false,
            };

            // The command result channel is 16 KiB including its envelope and
            // message. Leave headroom and remove tail rows deterministically;
            // counts and the truncation bit keep the projection honest.
            const int maxCatalogBytes = 14 * 1024;
            while (Encoding.UTF8.GetByteCount(doc.ToString(Formatting.None)) > maxCatalogBytes
                   && strategies.Count > 0)
            {
                strategies.RemoveAt(strategies.Count - 1);
                doc["truncated"] = true;
            }
            while (Encoding.UTF8.GetByteCount(doc.ToString(Formatting.None)) > maxCatalogBytes
                   && commission.Count > 1)
            {
                commission.RemoveAt(commission.Count - 1);
                doc["truncated"] = true;
            }
            return doc;
        }

        // ----- strategies.json --------------------------------------------

        private static void WriteStrategies(string path, IReadOnlyList<Type> types, string ntUserDir)
        {
            var arr = new List<Dictionary<string, object>>();
            foreach (var t in types)
            {
                try { arr.Add(BuildStrategyEntry(t, ntUserDir)); }
                catch (Exception ex)
                {
                    BridgeLog.Warn("CatalogWriter: skipped " + t.FullName + ": " + ex.Message);
                }
            }
            var doc = new Dictionary<string, object>
            {
                ["generated_at_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                ["count"]            = arr.Count,
                ["strategies"]       = arr,
            };
            AtomicFile.WriteAllText(path, JsonConvert.SerializeObject(doc, Formatting.Indented));
        }

        private static Dictionary<string, object> BuildStrategyEntry(Type t, string ntUserDir)
        {
            // Try to instantiate + invoke SetState(SetDefaults) so that user defaults
            // (set inside if (State == State.SetDefaults) blocks) are populated.
            object instance = null;
            try { instance = Activator.CreateInstance(t); } catch { }
            if (instance != null) TryInvokeSetDefaults(instance);

            var parameters = new List<Dictionary<string, object>>();
            foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
            {
                bool hasNS = p.GetCustomAttributes(true)
                    .Any(a => a.GetType().FullName == NS_PROPERTY_ATTR);
                if (!hasNS) continue;
                if (p.GetSetMethod() == null) continue;

                object def = null;
                if (instance != null)
                {
                    try { def = p.GetValue(instance); } catch { }
                }

                object min = null, max = null;
                var rng = p.GetCustomAttributes(true)
                    .FirstOrDefault(a => a.GetType().FullName == RANGE_ATTR);
                if (rng != null)
                {
                    min = ReadProp(rng, "Minimum");
                    max = ReadProp(rng, "Maximum");
                }

                string label = p.Name;
                int order = 0;
                string group = null;
                var disp = p.GetCustomAttributes(true)
                    .FirstOrDefault(a => a.GetType().FullName == DISPLAY_ATTR);
                if (disp != null)
                {
                    var n = ReadProp(disp, "Name") as string;
                    if (!string.IsNullOrWhiteSpace(n)) label = n;
                    var o = ReadProp(disp, "Order");
                    if (o is int oi) order = oi;
                    group = ReadProp(disp, "GroupName") as string;
                }

                string kind = ClassifyType(p.PropertyType);
                List<string> enumValues = null;
                if (p.PropertyType.IsEnum)
                    enumValues = Enum.GetNames(p.PropertyType).ToList();

                parameters.Add(new Dictionary<string, object>
                {
                    ["name"]        = p.Name,
                    ["label"]       = label,
                    ["kind"]        = kind,
                    ["type"]        = p.PropertyType.FullName,
                    ["default"]     = JsonSafe(def),
                    ["min"]         = JsonSafe(min),
                    ["max"]         = JsonSafe(max),
                    ["order"]       = order,
                    ["group"]       = group,
                    ["enum_values"] = enumValues,
                });
            }

            parameters = parameters
                .OrderBy(d => Convert.ToInt32(d["order"]))
                .ThenBy(d => (string)d["name"])
                .ToList();

            return new Dictionary<string, object>
            {
                ["class_name"]   = t.Name,
                ["full_name"]    = t.FullName,
                ["display_name"] = ReadStrategyDisplayName(instance, t.Name),
                ["stable_id"]    = StableIdForClass(t.Name),
                ["legacy_strategy_ids"] = LegacyIdsForClass(t.Name),
                ["source_file"]  = TryGuessSourceFile(t, ntUserDir),
                ["parameters"]   = parameters,
            };
        }

        private static string ReadStrategyDisplayName(object instance, string fallback)
        {
            if (instance == null) return fallback;
            try
            {
                var pi = instance.GetType().GetProperty("Name", BindingFlags.Public | BindingFlags.Instance);
                object raw = pi != null ? pi.GetValue(instance) : null;
                string value = raw == null ? null : raw.ToString();
                return string.IsNullOrWhiteSpace(value) ? fallback : value;
            }
            catch { return fallback; }
        }

        private static string StableIdForClass(string className)
        {
            switch (className)
            {
                case "PullbackMNQ5mV2": return "pullback_mnq_5m_v2";
                case "VWAPPullbackMGC5mV1": return "vwap_pullback_mgc_5m_v1";
                case "B1ShortOnlyMGC5mV2": return "mgc_b1_short_5m_v2";
                case "B1Stop24MGC5mC003": return "mgc_b1_stop24_5m_c003";
                case "B1Stop20MGC5mC004": return "mgc_b1_stop20_5m_c004";
                case "NTAMicroVwapRiskPilot": return "vwap_short_mnq_5m_v1";
                case "NTAMicroVwapRiskExplorer": return "vwap_risk_explorer_mgc_5m_v1";
                case "NTAMicroSessionEdgeExplorer": return "session_edge_multi_5m_v2";
                case "NTAMicroMnqScalpPilot": return "scalping_mnq_1m_v1";
                case "NTAMnqMicroOrbOpenScalp": return "orb_open_scalp_mnq_1m_v1";
                case "NTAnalyzerEveryNBarLong": return "every_n_bar_long_generic_any_v1";
                case "StrategiyaUrovney": return "levels_strategy_userdefined_v1";
                default: return className == null ? "" : className.ToLowerInvariant();
            }
        }

        private static List<string> LegacyIdsForClass(string className)
        {
            if (className == "NTAMicroVwapRiskPilot")
                return new List<string> { "b1_shortonly" };
            if (className == "VWAPPullbackMGC5mV1")
                return new List<string> { "vwappullbackmgc5mv1" };
            if (className == "B1ShortOnlyMGC5mV2")
                return new List<string> { "mgc_b1_shortonly_5m_v2" };
            if (className == "B1Stop24MGC5mC003")
                return new List<string> { "b1stop24mgc5mc003" };
            if (className == "B1Stop20MGC5mC004")
                return new List<string> { "b1stop20mgc5mc004" };
            if (className == "NTAMnqMicroOrbOpenScalp")
                return new List<string> { "ntamnqmicroorbopenscalp" };
            return new List<string>();
        }

        private static string ClassifyType(Type t)
        {
            if (t == typeof(int) || t == typeof(long) || t == typeof(short) ||
                t == typeof(uint) || t == typeof(ulong) || t == typeof(ushort) ||
                t == typeof(byte) || t == typeof(sbyte))
                return "int";
            if (t == typeof(double) || t == typeof(float) || t == typeof(decimal))
                return "float";
            if (t == typeof(bool))   return "bool";
            if (t == typeof(string)) return "string";
            if (t.IsEnum)            return "enum";
            return "unsupported";
        }

        private static object JsonSafe(object v)
        {
            if (v == null) return null;
            var t = v.GetType();
            if (t.IsEnum) return v.ToString();
            if (t == typeof(int) || t == typeof(long) || t == typeof(short) ||
                t == typeof(uint) || t == typeof(ulong) || t == typeof(ushort) ||
                t == typeof(byte) || t == typeof(sbyte) ||
                t == typeof(double) || t == typeof(float) || t == typeof(decimal) ||
                t == typeof(bool) || t == typeof(string))
                return v;
            try { return Convert.ToString(v); } catch { return null; }
        }

        private static object ReadProp(object o, string name)
        {
            try { return o.GetType().GetProperty(name)?.GetValue(o); }
            catch { return null; }
        }

        private static void TryInvokeSetDefaults(object instance)
        {
            try
            {
                var stateProp = instance.GetType().GetProperty("State",
                    BindingFlags.Public | BindingFlags.Instance);
                if (stateProp == null) return;

                var stateType = stateProp.PropertyType;
                if (!stateType.IsEnum) return;
                var setDefaults = Enum.Parse(stateType, "SetDefaults");

                // Prefer SetState(State) which raises OnStateChange in NT8.
                var setState = instance.GetType().GetMethod("SetState",
                    BindingFlags.Public | BindingFlags.Instance, null,
                    new[] { stateType }, null);
                if (setState != null)
                {
                    setState.Invoke(instance, new[] { setDefaults });
                    return;
                }
                stateProp.SetValue(instance, setDefaults);
            }
            catch { /* defaults remain default(T) */ }
        }

        private static string TryGuessSourceFile(Type t, string ntUserDir)
        {
            if (string.IsNullOrWhiteSpace(ntUserDir)) return null;
            string baseDir = Path.Combine(ntUserDir, "bin", "Custom", "Strategies");
            if (!Directory.Exists(baseDir)) return null;
            try
            {
                foreach (var name in new[] { t.Name + ".cs", "@" + t.Name + ".cs" })
                {
                    var hit = Directory.GetFiles(baseDir, name,
                        SearchOption.AllDirectories).FirstOrDefault();
                    if (hit != null) return hit;
                }
            }
            catch { return null; }
            return null;
        }

        // Contracts the server may legitimately offer for a backtest: real
        // minute data, recent enough that NinjaTrader still has bars.
        //
        // The command result this travels in is capped at 16 KiB by the server
        // (`_safe_result`), so the selection is bounded by measured bytes, not
        // by a row count that silently becomes wrong as the catalog grows.
        // Roots are filled round-robin newest-first, so the budget can never
        // evict an entire root -- every root gets its live month before any
        // root gets a second contract.
        // A page, not the catalog. The server refuses a result over 16 KiB and
        // any list over 100 items, so the full 400-day set is delivered as
        // several bounded pages rather than truncated: dropping valid contracts
        // is what left the server offering bare roots.
        internal const int ConnectorPageTargetBytes = 12 * 1024;
        internal const int ConnectorInstrumentsPerPage = 80;
        internal const int EnvelopeReserveBytes = 512;
        internal const int ConnectorInstrumentMaxAgeDays = 400;

        // NinjaTrader's own instrument universe, which exists before any bars are
        // cached. db\minute only records what has been downloaded, so deriving
        // the catalog from it hides every instrument the user has not backtested
        // yet. MasterInstrument/Instrument is where NinjaTrader itself knows a
        // contract exists, and Strategy Analyzer downloads the history on demand.
        //
        // Returns the nearest unexpired contract per futures root, keyed by root.
        private static Dictionary<string, Dictionary<string, object>> CanonicalFutureFrontMonths()
        {
            var byRoot = new Dictionary<string, Dictionary<string, object>>(
                StringComparer.OrdinalIgnoreCase);
            var expiryByRoot = new Dictionary<string, DateTime>(StringComparer.OrdinalIgnoreCase);
            try
            {
                Type instrType = Type.GetType("NinjaTrader.Cbi.Instrument, NinjaTrader.Core",
                                              throwOnError: false)
                    ?? AppDomain.CurrentDomain.GetAssemblies()
                        .Select(a => SafeGetType(a, "NinjaTrader.Cbi.Instrument"))
                        .FirstOrDefault(t => t != null);
                if (instrType == null) return byRoot;

                var allProp = instrType.GetProperty("All",
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static);
                var all = allProp?.GetValue(null, null) as System.Collections.IEnumerable;
                if (all == null) return byRoot;

                DateTime today = DateTime.UtcNow.Date;
                foreach (object instrument in all)
                {
                    if (instrument == null) continue;
                    object master = ReadProp(instrument, "MasterInstrument");
                    if (master == null) continue;
                    string kind = ReadProp(master, "InstrumentType")?.ToString();
                    if (!string.Equals(kind, "Future", StringComparison.OrdinalIgnoreCase)) continue;

                    string full = ReadProp(instrument, "FullName")?.ToString();
                    if (string.IsNullOrWhiteSpace(full) || full.IndexOf(' ') < 0) continue;

                    object expiryRaw = ReadProp(instrument, "Expiry");
                    if (!(expiryRaw is DateTime)) continue;
                    DateTime expiry = ((DateTime)expiryRaw).Date;
                    if (expiry < today) continue;

                    string root = ReadProp(master, "Name")?.ToString();
                    if (string.IsNullOrWhiteSpace(root)) root = ParseRoot(full);
                    if (string.IsNullOrWhiteSpace(root)) continue;

                    DateTime held;
                    if (expiryByRoot.TryGetValue(root, out held) && held <= expiry) continue;

                    double? tickSize = TryReadDouble(master, "TickSize");
                    double? pointValue = TryReadDouble(master, "PointValue");
                    var row = new Dictionary<string, object>
                    {
                        ["instrument"] = full,
                        ["root"] = root,
                        ["expiry"] = ParseExpiry(full),
                        ["data_first"] = null,
                        ["data_last"] = null,
                        ["has_minute_data"] = false,
                        ["tick_size"] = tickSize.HasValue ? (object)tickSize.Value : null,
                        ["point_value"] = pointValue.HasValue ? (object)pointValue.Value : null,
                        ["tick_value"] = (tickSize.HasValue && pointValue.HasValue)
                            ? (object)Math.Round(tickSize.Value * pointValue.Value, 8) : null,
                    };
                    byRoot[root] = row;
                    expiryByRoot[root] = expiry;
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("CatalogWriter: canonical instrument enumeration failed: " + ex.Message);
            }
            return byRoot;
        }

        private static List<JObject> BuildConnectorInstruments(
            string ntUserDir, out int scannedTotal)
        {
            int ok, fail;
            List<Dictionary<string, object>> rows = ScanInstruments(ntUserDir, out ok, out fail);
            scannedTotal = rows.Count;

            DateTime cutoff = DateTime.UtcNow.Date.AddDays(-ConnectorInstrumentMaxAgeDays);
            var byRoot = new Dictionary<string, List<KeyValuePair<DateTime, Dictionary<string, object>>>>();
            foreach (Dictionary<string, object> row in rows)
            {
                if (!(row["has_minute_data"] is bool) || !(bool)row["has_minute_data"]) continue;
                string lastText = Convert.ToString(row["data_last"]);
                if (string.IsNullOrWhiteSpace(lastText)) continue;
                DateTime last;
                if (!DateTime.TryParse(lastText, System.Globalization.CultureInfo.InvariantCulture,
                                       System.Globalization.DateTimeStyles.None, out last)) continue;
                if (last < cutoff) continue;
                string root = Convert.ToString(row["root"]);
                if (string.IsNullOrWhiteSpace(root)) continue;
                if (!byRoot.ContainsKey(root))
                    byRoot[root] = new List<KeyValuePair<DateTime, Dictionary<string, object>>>();
                byRoot[root].Add(new KeyValuePair<DateTime, Dictionary<string, object>>(last, row));
            }

            // Every futures root NinjaTrader knows about gets its current contract,
            // even with nothing cached yet, so the selector offers the instrument
            // before its first backtest instead of after it. A root that already
            // has cached bars keeps those rows and their real data ranges.
            foreach (KeyValuePair<string, Dictionary<string, object>> entry in
                     CanonicalFutureFrontMonths())
            {
                if (byRoot.ContainsKey(entry.Key)) continue;
                byRoot[entry.Key] = new List<KeyValuePair<DateTime, Dictionary<string, object>>>
                {
                    new KeyValuePair<DateTime, Dictionary<string, object>>(
                        DateTime.MinValue, entry.Value),
                };
            }

            List<string> roots = byRoot.Keys.ToList();
            roots.Sort(StringComparer.Ordinal);
            foreach (string root in roots)
                byRoot[root].Sort((a, b) => b.Key.CompareTo(a.Key));

            // Round-robin: every root's live month lands on the earliest page,
            // and the rest of the eligible set follows on later pages. Nothing
            // eligible is discarded.
            var ordered = new List<JObject>();
            int depth = 0;
            bool addedThisPass = true;
            while (addedThisPass)
            {
                addedThisPass = false;
                foreach (string root in roots)
                {
                    List<KeyValuePair<DateTime, Dictionary<string, object>>> group = byRoot[root];
                    if (depth >= group.Count) continue;
                    ordered.Add(ProjectConnectorInstrument(group[depth].Value));
                    addedThisPass = true;
                }
                depth++;
            }
            return ordered;
        }

        // Stable identity for one snapshot, so the server can tell pages of the
        // same catalog from a newer scan that started mid-delivery.
        private static string ComputeCatalogId(List<JObject> ordered, string generatedAt)
        {
            var builder = new System.Text.StringBuilder(generatedAt);
            foreach (JObject row in ordered)
            {
                builder.Append('|').Append(Convert.ToString(row["instrument"]));
                builder.Append('@').Append(Convert.ToString(row["data_last"]));
            }
            using (var sha = System.Security.Cryptography.SHA256.Create())
            {
                byte[] hash = sha.ComputeHash(
                    System.Text.Encoding.UTF8.GetBytes(builder.ToString()));
                return BitConverter.ToString(hash, 0, 16)
                    .Replace("-", string.Empty).ToLowerInvariant();
            }
        }

        // Split by measured serialized bytes and item count, never an estimate.
        private static List<List<JObject>> PaginateInstruments(
            List<JObject> ordered, int firstPageExtraBytes)
        {
            var pages = new List<List<JObject>>();
            var current = new List<JObject>();
            int used = 0;
            int extra = firstPageExtraBytes;
            foreach (JObject row in ordered)
            {
                int cost = row.ToString(Formatting.None).Length + 1;
                bool full = current.Count >= ConnectorInstrumentsPerPage
                            || used + cost + extra + EnvelopeReserveBytes
                               > ConnectorPageTargetBytes;
                if (full && current.Count > 0)
                {
                    pages.Add(current);
                    current = new List<JObject>();
                    used = 0;
                    extra = 0;
                }
                current.Add(row);
                used += cost;
            }
            if (current.Count > 0) pages.Add(current);
            return pages;
        }

        // Only what a server cannot derive itself. root/expiry come from the
        // instrument name; asset_class is classified server-side.
        private static JObject ProjectConnectorInstrument(Dictionary<string, object> row)
        {
            return new JObject
            {
                ["instrument"] = Convert.ToString(row["instrument"]),
                ["data_first"] = Convert.ToString(row["data_first"]),
                ["data_last"] = Convert.ToString(row["data_last"]),
                ["tick_size"] = row["tick_size"] == null ? null : new JValue(row["tick_size"]),
                ["point_value"] = row["point_value"] == null ? null : new JValue(row["point_value"]),
                ["tick_value"] = row["tick_value"] == null ? null : new JValue(row["tick_value"]),
            };
        }

        // ----- instruments.json -------------------------------------------

        // Cached lookup methods from NinjaTrader.Cbi.Instrument.GetInstrument(string).
        // Resolved per WriteInstruments call (so a manual refresh after NT
        // becomes ready will retry rather than caching the initial null).
        private static System.Reflection.MethodInfo _instrumentGetMethod;
        private static int _instrumentGetMethodArity; // 1 or 2
        private static bool _instrumentGetMethodWarned;

        private static void WriteInstruments(string path, string ntUserDir)
        {
            int enrichedOk, enrichedFail;
            List<Dictionary<string, object>> rows =
                ScanInstruments(ntUserDir, out enrichedOk, out enrichedFail);

            BridgeLog.Info("CatalogWriter: instrument metadata enrichment ok=" +
                           enrichedOk + " fail=" + enrichedFail);

            var doc = new Dictionary<string, object>
            {
                ["generated_at_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                ["count"]            = rows.Count,
                ["source"]           = @"scan: db\minute\* + Cbi.Instrument.GetInstrument",
                ["enrichment"]       = new Dictionary<string, object>
                {
                    ["ok"]   = enrichedOk,
                    ["fail"] = enrichedFail,
                },
                ["instruments"]      = rows,
            };
            AtomicFile.WriteAllText(path, JsonConvert.SerializeObject(doc, Formatting.Indented));
        }

        /// <summary>
        /// One scan of db\minute\*, shared by instruments.json and the bounded
        /// Connector snapshot so a server never has to guess a contract month.
        /// </summary>
        private static List<Dictionary<string, object>> ScanInstruments(
            string ntUserDir, out int enrichedOk, out int enrichedFail)
        {
            var rows = new List<Dictionary<string, object>>();
            enrichedOk   = 0;
            enrichedFail = 0;
            try
            {
                string minuteDir = Path.Combine(ntUserDir, "db", "minute");
                if (Directory.Exists(minuteDir))
                {
                    foreach (var d in Directory.GetDirectories(minuteDir))
                    {
                        string name = Path.GetFileName(d);
                        if (string.IsNullOrWhiteSpace(name)) continue;
                        DateTime? min = null, max = null;
                        try
                        {
                            foreach (var f in Directory.GetFiles(d, "*.*"))
                            {
                                var fn = Path.GetFileNameWithoutExtension(f);
                                if (fn.Length >= 8 &&
                                    long.TryParse(fn.Substring(0, 8), out long ymd))
                                {
                                    var dt = ParseYmd(ymd);
                                    if (dt.HasValue)
                                    {
                                        if (!min.HasValue || dt < min) min = dt;
                                        if (!max.HasValue || dt > max) max = dt;
                                    }
                                }
                            }
                        }
                        catch { }

                        var row = new Dictionary<string, object>
                        {
                            ["instrument"]      = name,
                            ["root"]            = ParseRoot(name),
                            ["expiry"]          = ParseExpiry(name),
                            ["data_first"]      = min?.ToString("yyyy-MM-dd"),
                            ["data_last"]       = max?.ToString("yyyy-MM-dd"),
                            ["asset_class"]     = ClassifyInstrument(name),
                            ["has_minute_data"] = min.HasValue && max.HasValue,
                            // Defaults — overwritten by EnrichWithNtMetadata when NT lookup succeeds.
                            ["tick_size"]        = null,
                            ["point_value"]      = null,
                            ["tick_value"]       = null,
                            ["currency"]         = null,
                            ["exchange"]         = null,
                            ["instrument_type"]  = null,
                            ["master_instrument"] = null,
                        };

                        if (EnrichWithNtMetadata(name, row))
                            enrichedOk++;
                        else
                            enrichedFail++;

                        rows.Add(row);
                    }
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("CatalogWriter.WriteInstruments scan failed: " + ex.Message);
            }

            return rows.OrderBy(r => (string)r["instrument"]).ToList();
        }

        // Try to resolve the instrument via NinjaTrader.Cbi.Instrument.GetInstrument
        // and pull TickSize / PointValue / Currency / Exchange / InstrumentType
        // from MasterInstrument. All field reads are reflection-guarded so a
        // missing / renamed property in some NT build never crashes the catalog.
        private static bool EnrichWithNtMetadata(string instrumentName, Dictionary<string, object> row)
        {
            try
            {
                if (_instrumentGetMethod == null)
                {
                    var instrType = Type.GetType("NinjaTrader.Cbi.Instrument, NinjaTrader.Core",
                                                 throwOnError: false);
                    if (instrType == null)
                    {
                        instrType = AppDomain.CurrentDomain.GetAssemblies()
                            .Select(a => SafeGetType(a, "NinjaTrader.Cbi.Instrument"))
                            .FirstOrDefault(t => t != null);
                    }
                    if (instrType != null)
                    {
                        var m1 = instrType.GetMethod("GetInstrument",
                            System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static,
                            null, new[] { typeof(string) }, null);
                        if (m1 != null) { _instrumentGetMethod = m1; _instrumentGetMethodArity = 1; }
                        else
                        {
                            var m2 = instrType.GetMethod("GetInstrument",
                                System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static,
                                null, new[] { typeof(string), typeof(bool) }, null);
                            if (m2 != null) { _instrumentGetMethod = m2; _instrumentGetMethodArity = 2; }
                        }
                    }
                    if (_instrumentGetMethod == null)
                    {
                        if (!_instrumentGetMethodWarned)
                        {
                            _instrumentGetMethodWarned = true;
                            BridgeLog.Warn("CatalogWriter: NinjaTrader.Cbi.Instrument.GetInstrument not found - tick/point fields will be null (instrType=" + (instrType?.AssemblyQualifiedName ?? "null") + ")");
                        }
                        return false;
                    }
                }

                object[] args = _instrumentGetMethodArity == 1
                    ? new object[] { instrumentName }
                    : new object[] { instrumentName, false };
                object instr = _instrumentGetMethod.Invoke(null, args);
                if (instr == null) return false;

                object master = ReadProp(instr, "MasterInstrument") ?? instr;

                double? tickSize   = TryReadDouble(master, "TickSize");
                double? pointValue = TryReadDouble(master, "PointValue");
                string  currency   = ReadProp(master, "Currency")?.ToString();
                object  exchanges  = ReadProp(instr, "Exchange") ?? ReadProp(master, "Exchange");
                string  exchange   = exchanges?.ToString();
                string  instrType2 = ReadProp(master, "InstrumentType")?.ToString();
                string  fullName   = ReadProp(master, "Name")?.ToString();

                if (tickSize.HasValue)   row["tick_size"]   = tickSize.Value;
                if (pointValue.HasValue) row["point_value"] = pointValue.Value;
                if (tickSize.HasValue && pointValue.HasValue)
                    row["tick_value"] = Math.Round(tickSize.Value * pointValue.Value, 8);
                if (!string.IsNullOrWhiteSpace(currency))   row["currency"]         = currency;
                if (!string.IsNullOrWhiteSpace(exchange))   row["exchange"]         = exchange;
                if (!string.IsNullOrWhiteSpace(instrType2)) row["instrument_type"]  = instrType2;
                if (!string.IsNullOrWhiteSpace(fullName))   row["master_instrument"]= fullName;
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static double? TryReadDouble(object o, string propName)
        {
            try
            {
                var v = ReadProp(o, propName);
                if (v == null) return null;
                if (v is double d)  return d;
                if (v is float f)   return (double)f;
                if (v is decimal m) return (double)m;
                if (v is int i)     return (double)i;
                if (v is long l)    return (double)l;
                return Convert.ToDouble(v);
            }
            catch { return null; }
        }

        private static Type SafeGetType(System.Reflection.Assembly a, string fullName)
        {
            try { return a.GetType(fullName, throwOnError: false); }
            catch { return null; }
        }

        // "MES 06-26" -> "MES" ; "EURUSD" -> "EURUSD"
        private static string ParseRoot(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return null;
            int sp = name.IndexOf(' ');
            return sp > 0 ? name.Substring(0, sp) : name;
        }

        // "MES 06-26" -> "06-26" ; "EURUSD" -> null
        private static string ParseExpiry(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return null;
            int sp = name.IndexOf(' ');
            return sp > 0 && sp + 1 < name.Length ? name.Substring(sp + 1) : null;
        }

        private static DateTime? ParseYmd(long ymd)
        {
            try
            {
                int y = (int)(ymd / 10000);
                int m = (int)((ymd / 100) % 100);
                int d = (int)(ymd % 100);
                if (y < 1900 || y > 2200 || m < 1 || m > 12 || d < 1 || d > 31) return null;
                return new DateTime(y, m, d);
            }
            catch { return null; }
        }

        // Cheap classifier good enough for Run-form filters. Pure string pattern,
        // no NT API needed (Cbi.Instrument lookup would force NT to be ready).
        private static readonly System.Text.RegularExpressions.Regex _futuresRe =
            new System.Text.RegularExpressions.Regex(
                @"^[A-Z0-9.]{1,8}\s+\d{2}-\d{2}$",
                System.Text.RegularExpressions.RegexOptions.Compiled);
        private static readonly System.Text.RegularExpressions.Regex _forexRe =
            new System.Text.RegularExpressions.Regex(
                @"^[A-Z]{6}$",
                System.Text.RegularExpressions.RegexOptions.Compiled);

        private static string ClassifyInstrument(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return "other";
            if (_futuresRe.IsMatch(name)) return "futures";
            if (_forexRe.IsMatch(name))   return "forex";
            return "other";
        }

        // ----- templates.json (commission + trading hours) -----------------

        private static void WriteTemplates(string path, string ntUserDir)
        {
            var thours     = new List<Dictionary<string, object>>();
            var notes      = new List<string>();
            var commission = ScanCommissionTemplates(ntUserDir, notes, true);

            try
            {
                string thDir = Path.Combine(ntUserDir, "templates", "TradingHours");
                if (Directory.Exists(thDir))
                {
                    foreach (var f in Directory.GetFiles(thDir, "*.xml"))
                    {
                        string n = Path.GetFileNameWithoutExtension(f);
                        thours.Add(new Dictionary<string, object>
                        {
                            ["name"]      = n,
                            ["display"]   = n,
                            ["supported"] = string.Equals(n, "CME US Index Futures RTH",
                                                          StringComparison.Ordinal),
                            ["source"]    = "ntuser:templates/TradingHours",
                        });
                    }
                }
                else
                {
                    notes.Add("trading-hours template dir not found: " + thDir);
                }
            }
            catch (Exception ex)
            {
                notes.Add("scan templates/TradingHours failed: " + ex.Message);
            }

            commission = commission.OrderBy(c => (string)c["name"]).ToList();
            thours     = thours.OrderBy(t => (string)t["name"]).ToList();

            var doc = new Dictionary<string, object>
            {
                ["generated_at_utc"]      = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                ["commission_templates"]  = commission,
                ["trading_hours_templates"] = thours,
                ["notes"]                 = notes,
            };
            AtomicFile.WriteAllText(path, JsonConvert.SerializeObject(doc, Formatting.Indented));
        }

        private static List<Dictionary<string, object>> ScanCommissionTemplates(
            string ntUserDir, List<string> notes, bool includeSource)
        {
            var commission = new List<Dictionary<string, object>>();
            var none = new Dictionary<string, object>
            {
                ["name"]      = "None",
                ["display"]   = "None / 0 commission",
                ["supported"] = true,
            };
            if (includeSource) none["source"] = "synthetic";
            commission.Add(none);
            try
            {
                string commDir = Path.Combine(ntUserDir, "templates", "Commission");
                if (Directory.Exists(commDir))
                {
                    foreach (string file in Directory.GetFiles(commDir, "*.xml"))
                    {
                        string name = Path.GetFileNameWithoutExtension(file);
                        var row = new Dictionary<string, object>
                        {
                            ["name"] = name,
                            ["display"] = name,
                            ["supported"] = true,
                        };
                        if (includeSource) row["source"] = "ntuser:templates/Commission";
                        commission.Add(row);
                    }
                }
                else
                {
                    notes.Add("commission template dir not found: " + commDir);
                }
            }
            catch (Exception ex)
            {
                notes.Add("scan templates/Commission failed: " + ex.Message);
            }
            return commission.OrderBy(c => (string)c["name"]).ToList();
        }
    }
}
