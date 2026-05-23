using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json;
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

        // ----- instruments.json -------------------------------------------

        // Cached lookup methods from NinjaTrader.Cbi.Instrument.GetInstrument(string).
        // Resolved per WriteInstruments call (so a manual refresh after NT
        // becomes ready will retry rather than caching the initial null).
        private static System.Reflection.MethodInfo _instrumentGetMethod;
        private static int _instrumentGetMethodArity; // 1 or 2
        private static bool _instrumentGetMethodWarned;

        private static void WriteInstruments(string path, string ntUserDir)
        {
            var rows = new List<Dictionary<string, object>>();
            int enrichedOk   = 0;
            int enrichedFail = 0;
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

            rows = rows.OrderBy(r => (string)r["instrument"]).ToList();

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
            var commission = new List<Dictionary<string, object>>();
            var thours     = new List<Dictionary<string, object>>();
            var notes      = new List<string>();

            // Always include the synthetic "None / 0 commission" template
            // because the bridge currently applies *no* commission regardless
            // of NT settings. UI shows it as the only enabled option.
            commission.Add(new Dictionary<string, object>
            {
                ["name"]      = "None",
                ["display"]   = "None / 0 commission",
                ["supported"] = true,
                ["source"]    = "synthetic",
            });

            try
            {
                string commDir = Path.Combine(ntUserDir, "templates", "Commission");
                if (Directory.Exists(commDir))
                {
                    foreach (var f in Directory.GetFiles(commDir, "*.xml"))
                    {
                        commission.Add(new Dictionary<string, object>
                        {
                            ["name"]      = Path.GetFileNameWithoutExtension(f),
                            ["display"]   = Path.GetFileNameWithoutExtension(f),
                            ["supported"] = true,
                            ["source"]    = "ntuser:templates/Commission",
                        });
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
    }
}
