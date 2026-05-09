using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Execution
{
    /// <summary>
    /// Reflection-only access to user strategies compiled inside
    /// NinjaTrader.Custom.dll. The single trusted selector is class_name
    /// from job.json. source_file_hint is NEVER consulted to load code.
    ///
    /// Whitelist rules (must ALL hold):
    ///   - type lives in the assembly whose CodeBase points to
    ///     &lt;ninjatrader_user_dir&gt;\bin\Custom\NinjaTrader.Custom.dll;
    ///   - type derives from NinjaTrader.NinjaScript.Strategies.Strategy;
    ///   - type is a non-abstract concrete class;
    ///   - Type.Name equals the requested class_name.
    /// </summary>
    internal sealed class StrategyLoader
    {
        private readonly string _expectedCustomDllFullPath;
        private Assembly _customAssembly;
        private Type _strategyBaseType;
        private List<Type> _whitelist;
        private DateTime _customAssemblyDiskMtimeUtc = DateTime.MinValue;

        public StrategyLoader(string ninjaTraderUserDir)
        {
            if (string.IsNullOrWhiteSpace(ninjaTraderUserDir))
                throw new ArgumentException("ninjaTraderUserDir is required", nameof(ninjaTraderUserDir));

            _expectedCustomDllFullPath = System.IO.Path.GetFullPath(
                System.IO.Path.Combine(ninjaTraderUserDir, "bin", "Custom", "NinjaTrader.Custom.dll"));
        }

        /// <summary>
        /// Builds (or rebuilds) the whitelist. Safe to call repeatedly.
        /// </summary>
        public void Refresh()
        {
            // Prefer the assembly already loaded by NinjaTrader. Strategy
            // Analyzer execution expects strategy types from NT's AppDomain;
            // byte-loaded copies can enumerate incorrectly because their base
            // Strategy type is not the same runtime identity.
            _customAssembly = FindLoadedCustomAssembly()
                              ?? TryLoadCurrentCustomDllBytes();

            if (_customAssembly == null)
                throw new InvalidOperationException(
                    "NinjaTrader.Custom assembly not loaded in current AppDomain");

            _strategyBaseType = ResolveStrategyBaseType(_customAssembly);
            if (_strategyBaseType == null)
                throw new InvalidOperationException(
                    "NinjaTrader.NinjaScript.Strategies.Strategy not found");

            // Verify physical location matches the configured NinjaTrader user dir.
            string actualLocation = TryGetAssemblyLocation(_customAssembly);
            if (!string.IsNullOrEmpty(actualLocation))
            {
                string actualFull = System.IO.Path.GetFullPath(actualLocation);
                if (!string.Equals(actualFull, _expectedCustomDllFullPath, StringComparison.OrdinalIgnoreCase))
                {
                    BridgeLog.Warn(
                        "NinjaTrader.Custom loaded from '" + actualFull +
                        "' but config expects '" + _expectedCustomDllFullPath +
                        "'. Whitelist will still use the loaded assembly.");
                }
            }

            Type[] types;
            try { types = _customAssembly.GetTypes(); }
            catch (ReflectionTypeLoadException rtle)
            {
                types = rtle.Types.Where(t => t != null).ToArray();
                BridgeLog.Warn("ReflectionTypeLoadException while enumerating strategies: " +
                               rtle.LoaderExceptions.Length + " loader errors");
            }

            _whitelist = types
                .Where(t => t != null
                            && t.IsClass
                            && !t.IsAbstract
                            && t != _strategyBaseType
                            && _strategyBaseType.IsAssignableFrom(t))
                .ToList();

            BridgeLog.Info("Strategy whitelist refreshed: " + _whitelist.Count +
                           " strategies [" + string.Join(", ", WhitelistedClassNames()) + "]");
        }

        public IReadOnlyList<string> WhitelistedClassNames()
        {
            return (_whitelist ?? new List<Type>()).Select(t => t.Name).OrderBy(n => n).ToList();
        }

        /// <summary>
        /// Returns the typed whitelist (used by CatalogWriter to dump
        /// per-strategy parameter metadata to data\catalog\strategies.json).
        /// </summary>
        public IReadOnlyList<Type> WhitelistedTypes()
        {
            return (_whitelist ?? new List<Type>()).OrderBy(t => t.Name).ToList();
        }

        /// <summary>
        /// Resolves a class_name to a strategy Type. Returns null if not whitelisted.
        /// </summary>
        public Type Resolve(string className)
        {
            if (_whitelist == null) Refresh();
            if (string.IsNullOrWhiteSpace(className)) return null;

            return _whitelist.FirstOrDefault(t =>
                string.Equals(t.Name, className, StringComparison.Ordinal));
        }

        private static string TryGetAssemblyLocation(Assembly a)
        {
            try { return a.Location; } catch { }
            try
            {
                if (!string.IsNullOrEmpty(a.CodeBase))
                    return new Uri(a.CodeBase).LocalPath;
            }
            catch { }
            return null;
        }

        private Assembly TryLoadCurrentCustomDllBytes()
        {
            DateTime mtime = SafeGetFileMtimeUtc(_expectedCustomDllFullPath);
            if (mtime == DateTime.MinValue)
                return null;

            if (_customAssembly != null && mtime == _customAssemblyDiskMtimeUtc)
                return _customAssembly;

            Exception lastError = null;
            for (int attempt = 0; attempt < 5; attempt++)
            {
                try
                {
                    byte[] raw = ReadAllBytesShared(_expectedCustomDllFullPath);
                    var asm = Assembly.Load(raw);
                    _customAssemblyDiskMtimeUtc = mtime;
                    BridgeLog.Info("StrategyLoader: loaded NinjaTrader.Custom from disk bytes " +
                                   "(mtime=" + mtime.ToString("o") +
                                   ", bytes=" + raw.Length + ")");
                    return asm;
                }
                catch (IOException ex)
                {
                    lastError = ex;
                }
                catch (UnauthorizedAccessException ex)
                {
                    lastError = ex;
                }
                catch (BadImageFormatException ex)
                {
                    lastError = ex;
                    break;
                }

                Thread.Sleep(150);
            }

            if (lastError != null)
                BridgeLog.Warn("StrategyLoader: could not load current NinjaTrader.Custom.dll bytes; " +
                               "falling back to AppDomain assembly: " + lastError.Message);
            return null;
        }

        private static Assembly FindLoadedCustomAssembly()
        {
            return AppDomain.CurrentDomain.GetAssemblies()
                .Where(a => string.Equals(
                    a.GetName().Name, "NinjaTrader.Custom", StringComparison.OrdinalIgnoreCase))
                .LastOrDefault();
        }

        private static Type ResolveStrategyBaseType(Assembly customAssembly)
        {
            var t = Type.GetType(
                "NinjaTrader.NinjaScript.Strategies.Strategy, NinjaTrader.Core",
                throwOnError: false);
            if (t != null) return t;

            t = AppDomain.CurrentDomain.GetAssemblies()
                .Select(a => SafeGetType(a, "NinjaTrader.NinjaScript.Strategies.Strategy"))
                .FirstOrDefault(x => x != null);
            if (t != null) return t;

            return customAssembly == null
                ? null
                : SafeGetType(customAssembly, "NinjaTrader.NinjaScript.Strategies.Strategy");
        }

        private static DateTime SafeGetFileMtimeUtc(string path)
        {
            try
            {
                if (!File.Exists(path)) return DateTime.MinValue;
                return File.GetLastWriteTimeUtc(path);
            }
            catch { return DateTime.MinValue; }
        }

        private static byte[] ReadAllBytesShared(string path)
        {
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read,
                                           FileShare.ReadWrite | FileShare.Delete))
            {
                if (fs.Length > int.MaxValue)
                    throw new IOException("assembly is too large to load into memory: " + fs.Length);
                byte[] bytes = new byte[(int)fs.Length];
                int offset = 0;
                while (offset < bytes.Length)
                {
                    int n = fs.Read(bytes, offset, bytes.Length - offset);
                    if (n <= 0) break;
                    offset += n;
                }
                if (offset == bytes.Length) return bytes;

                byte[] trimmed = new byte[offset];
                Buffer.BlockCopy(bytes, 0, trimmed, 0, offset);
                return trimmed;
            }
        }

        private static Type SafeGetType(Assembly a, string fullName)
        {
            try { return a.GetType(fullName, throwOnError: false); }
            catch { return null; }
        }
    }
}
