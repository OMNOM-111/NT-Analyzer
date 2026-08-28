using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;

namespace NTAnalyzerBridge.Runtime
{
    /// <summary>
    /// One in-process file boundary for the Connector and command processor.
    ///
    /// The transport reads the same JSONL files that the NinjaTrader command
    /// processor appends. File.ReadLines keeps a handle open for the whole
    /// enumeration; on Windows that handle used to race File.AppendAllText and
    /// a completed Strategy Analyzer run could lose both its running and final
    /// result. Snapshot reads under one gate, and append with a short bounded
    /// retry for external scanners, so a transient share violation is not a
    /// lost job.
    /// </summary>
    internal static class RuntimeCommandSpool
    {
        private static readonly object Gate = new object();
        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);
        private const int AppendAttempts = 8;

        internal static string[] ReadAllLines(string path)
        {
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
                return new string[0];
            lock (Gate)
            {
                using (FileStream stream = new FileStream(
                    path, FileMode.Open, FileAccess.Read,
                    FileShare.ReadWrite | FileShare.Delete))
                using (StreamReader reader = new StreamReader(
                    stream, Utf8, true, 4096, false))
                {
                    List<string> lines = new List<string>();
                    string line;
                    while ((line = reader.ReadLine()) != null)
                        lines.Add(line);
                    return lines.ToArray();
                }
            }
        }

        internal static void AppendLine(string path, string line)
        {
            if (string.IsNullOrWhiteSpace(path))
                throw new ArgumentNullException(nameof(path));
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            IOException last = null;
            for (int attempt = 0; attempt < AppendAttempts; attempt++)
            {
                try
                {
                    lock (Gate)
                    {
                        using (FileStream stream = new FileStream(
                            path, FileMode.Append, FileAccess.Write, FileShare.Read))
                        using (StreamWriter writer = new StreamWriter(stream, Utf8, 4096, false))
                        {
                            writer.WriteLine(line ?? "");
                            writer.Flush();
                            stream.Flush(true);
                        }
                    }
                    return;
                }
                catch (IOException ex)
                {
                    last = ex;
                    if (attempt + 1 < AppendAttempts)
                        Thread.Sleep(25 * (attempt + 1));
                }
            }
            throw last ?? new IOException("runtime command spool append failed");
        }
    }
}
