using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
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
            // Resolve the strategy base type explicitly so we don't depend
            // on NinjaTrader.Custom being already in the AppDomain when we run.
            _strategyBaseType = Type.GetType(
                "NinjaTrader.NinjaScript.Strategies.Strategy, NinjaTrader.Core",
                throwOnError: false);

            if (_strategyBaseType == null)
            {
                // Older/newer builds may keep Strategy in NinjaTrader.Custom
                _strategyBaseType = AppDomain.CurrentDomain.GetAssemblies()
                    .Select(a => SafeGetType(a, "NinjaTrader.NinjaScript.Strategies.Strategy"))
                    .FirstOrDefault(t => t != null);
            }

            if (_strategyBaseType == null)
                throw new InvalidOperationException(
                    "NinjaTrader.NinjaScript.Strategies.Strategy not found in current AppDomain");

            // After NinjaScript Compile, NT8 loads a NEW NinjaTrader.Custom
            // assembly into the same AppDomain side-by-side with the previous
            // one. We must pick the most recently loaded copy so that the
            // catalog reflects what NinjaTrader currently sees, not what was
            // present when the AddOn was first initialized.
            _customAssembly = AppDomain.CurrentDomain.GetAssemblies()
                .Where(a => string.Equals(
                    a.GetName().Name, "NinjaTrader.Custom", StringComparison.OrdinalIgnoreCase))
                .LastOrDefault();

            if (_customAssembly == null)
                throw new InvalidOperationException(
                    "NinjaTrader.Custom assembly not loaded in current AppDomain");

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

            BridgeLog.Info("Strategy whitelist refreshed: " + _whitelist.Count + " strategies");
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

        private static Type SafeGetType(Assembly a, string fullName)
        {
            try { return a.GetType(fullName, throwOnError: false); }
            catch { return null; }
        }
    }
}
