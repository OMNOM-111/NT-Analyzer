using System;
using System.IO;

namespace NTAnalyzerBridge.Util
{
    /// <summary>
    /// File-based logger. NinjaTrader's Output window APIs differ between
    /// builds and contexts, so the bridge keeps its own append-only log.
    /// Default path: &lt;ninjatrader_user_dir&gt;\log\NTAnalyzerBridge.log
    /// (path is set via Configure(); until then writes are buffered to stderr).
    /// Logging must never throw out of the bridge.
    /// </summary>
    internal static class BridgeLog
    {
        private static readonly object _gate = new object();
        private static string _logFilePath;

        public static void Configure(string ninjaTraderUserDir)
        {
            try
            {
                string dir = Path.Combine(ninjaTraderUserDir ?? string.Empty, "log");
                Directory.CreateDirectory(dir);
                _logFilePath = Path.Combine(dir, "NTAnalyzerBridge.log");
            }
            catch
            {
                _logFilePath = null;
            }
        }

        public static void Info (string msg) { Write("INFO",  msg, null); }
        public static void Warn (string msg) { Write("WARN",  msg, null); }
        public static void Error(string msg, Exception ex = null) { Write("ERROR", msg, ex); }

        private static void Write(string level, string msg, Exception ex)
        {
            string line = string.Format(
                "{0:yyyy-MM-ddTHH:mm:ss.fffZ} [NTAnalyzerBridge] {1} {2}",
                DateTime.UtcNow, level, msg);
            if (ex != null)
                line += " | " + ex.GetType().Name + ": " + ex.Message;

            lock (_gate)
            {
                try
                {
                    if (!string.IsNullOrEmpty(_logFilePath))
                        File.AppendAllText(_logFilePath, line + Environment.NewLine);
                }
                catch { }
                try { Console.Error.WriteLine(line); } catch { }
            }
        }
    }
}
