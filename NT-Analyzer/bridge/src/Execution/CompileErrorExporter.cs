using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Execution
{
    /// <summary>
    /// Polls NinjaTrader compile diagnostics from whichever source is actually
    /// present on this machine (CompileErrors.txt OR trace/*.txt OR trace/<date>/*.log)
    /// and emits append-only JSONL records the AI sandbox can consume to autofix
    /// the prior strategy generation.
    /// </summary>
    internal sealed class CompileErrorExporter
    {
        private const int PollIntervalMs = 1000;
        private const int StatusFlushSec = 60;
        private const int DedupCap = 4096;
        private const int JsonlTrimMax = 5000;
        private const int TraceTailLines = 2000;

        private static readonly Regex CsErrorRegex = new Regex(
            @"(?<file>[^\(\r\n]+\.cs)\((?<line>\d+),(?<col>\d+)\)\s*:\s*error\s+(?<code>CS\d+)\s*:\s*(?<msg>.+)",
            RegexOptions.Compiled | RegexOptions.CultureInvariant);

        private readonly BridgeConfig _cfg;
        private readonly string _compileErrorsTxtPath;
        private readonly string _traceDir;
        private readonly string _outJsonlPath;
        private readonly string _statusJsonPath;
        private readonly System.Threading.Timer _timer;
        private readonly object _gate = new object();
        private readonly HashSet<string> _seenShas = new HashSet<string>(StringComparer.Ordinal);
        private readonly Dictionary<string, DateTime> _fileMtimes = new Dictionary<string, DateTime>(StringComparer.OrdinalIgnoreCase);
        private bool _busy;
        private bool _stopped;
        private long _totalEmitted;
        private DateTime _lastStatusFlushUtc = DateTime.MinValue;
        private DateTime _lastEmitUtc = DateTime.MinValue;
        private string _lastEmittedSource = "";
        private string _statusKeySnapshot = "";

        public CompileErrorExporter(BridgeConfig cfg)
        {
            _cfg = cfg ?? throw new ArgumentNullException(nameof(cfg));
            _compileErrorsTxtPath = Path.Combine(cfg.NinjaTraderUserDir, "bin", "Custom", "CompileErrors.txt");
            _traceDir = Path.Combine(cfg.NinjaTraderUserDir, "trace");
            _outJsonlPath = Path.Combine(cfg.RuntimeDataDir, "compile_errors.jsonl");
            _statusJsonPath = Path.Combine(cfg.RuntimeDataDir, "compile_error_source_status.json");
            _timer = new System.Threading.Timer(_ => Tick(), null, Timeout.Infinite, Timeout.Infinite);
        }

        public void Start()
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(_outJsonlPath));
            }
            catch (Exception ex)
            {
                BridgeLog.Error("CompileErrorExporter: cannot create runtime dir", ex);
            }
            _timer.Change(PollIntervalMs, PollIntervalMs);
            BridgeLog.Info("CompileErrorExporter started (poll=" + PollIntervalMs +
                           "ms, compileErrorsTxt=" + _compileErrorsTxtPath +
                           ", traceDir=" + _traceDir + ")");
        }

        public void Stop()
        {
            _stopped = true;
            try { _timer.Change(Timeout.Infinite, Timeout.Infinite); } catch { }
            try { _timer.Dispose(); } catch { }
        }

        private void Tick()
        {
            if (_stopped) return;
            lock (_gate)
            {
                if (_busy) return;
                _busy = true;
            }
            try
            {
                int emittedThisTick = 0;
                emittedThisTick += TryProbeCompileErrorsTxt();
                emittedThisTick += TryProbeTraceFiles();
                MaybeWriteStatus();
                if (_seenShas.Count > DedupCap)
                {
                    _seenShas.Clear();
                }
                if (emittedThisTick > 0)
                {
                    TrimJsonl();
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Error("CompileErrorExporter tick failed", ex);
            }
            finally
            {
                lock (_gate) { _busy = false; }
            }
        }

        private int TryProbeCompileErrorsTxt()
        {
            try
            {
                if (!File.Exists(_compileErrorsTxtPath)) return 0;
                DateTime mtime = File.GetLastWriteTimeUtc(_compileErrorsTxtPath);
                if (!HasMtimeAdvanced(_compileErrorsTxtPath, mtime)) return 0;
                string text = SafeReadAllText(_compileErrorsTxtPath);
                if (string.IsNullOrEmpty(text)) return 0;
                return EmitFromText(text, "CompileErrors.txt");
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("CompileErrorExporter: CompileErrors.txt probe failed: " + ex.Message);
                return 0;
            }
        }

        private int TryProbeTraceFiles()
        {
            try
            {
                if (!Directory.Exists(_traceDir)) return 0;
                var candidates = new List<Tuple<string, DateTime, string>>();
                foreach (string f in SafeEnumerate(_traceDir, "*.txt", SearchOption.TopDirectoryOnly))
                {
                    candidates.Add(Tuple.Create(f, SafeMtime(f), "trace_txt"));
                }
                foreach (string sub in SafeEnumerate(_traceDir, "*", SearchOption.TopDirectoryOnly, dirsInsteadOfFiles: true))
                {
                    foreach (string f in SafeEnumerate(sub, "*.log", SearchOption.TopDirectoryOnly))
                    {
                        candidates.Add(Tuple.Create(f, SafeMtime(f), "trace_log"));
                    }
                    foreach (string f in SafeEnumerate(sub, "*.txt", SearchOption.TopDirectoryOnly))
                    {
                        candidates.Add(Tuple.Create(f, SafeMtime(f), "trace_txt"));
                    }
                }
                if (candidates.Count == 0) return 0;
                var newest = candidates.OrderByDescending(t => t.Item2).Take(3).ToList();
                int total = 0;
                foreach (var c in newest)
                {
                    if (!HasMtimeAdvanced(c.Item1, c.Item2)) continue;
                    string tail = SafeReadLastLines(c.Item1, TraceTailLines);
                    if (string.IsNullOrEmpty(tail)) continue;
                    total += EmitFromText(tail, c.Item3);
                }
                return total;
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("CompileErrorExporter: trace probe failed: " + ex.Message);
                return 0;
            }
        }

        private int EmitFromText(string text, string source)
        {
            int emitted = 0;
            MatchCollection matches = CsErrorRegex.Matches(text);
            if (matches.Count == 0) return 0;
            var sb = new StringBuilder();
            foreach (Match m in matches)
            {
                if (!m.Success) continue;
                string file = (m.Groups["file"].Value ?? "").Trim();
                string line = m.Groups["line"].Value;
                string col = m.Groups["col"].Value;
                string code = m.Groups["code"].Value;
                string msg = (m.Groups["msg"].Value ?? "").Trim();
                if (file.Length == 0 || code.Length == 0) continue;
                string sha = Sha256.OfString(file + "|" + line + "|" + code + "|" + msg);
                if (_seenShas.Contains(sha)) continue;
                _seenShas.Add(sha);
                string className = null;
                try
                {
                    if (file.EndsWith(".cs", StringComparison.OrdinalIgnoreCase))
                        className = Path.GetFileNameWithoutExtension(file);
                }
                catch { className = null; }
                var rec = new JObject
                {
                    ["class_name"] = className,
                    ["file"] = file,
                    ["line"] = int.TryParse(line, out int ln) ? ln : (int?)null,
                    ["column"] = int.TryParse(col, out int cn) ? cn : (int?)null,
                    ["code"] = code,
                    ["message"] = msg,
                    ["timestamp_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                    ["source"] = source,
                    ["sha"] = sha,
                };
                sb.AppendLine(rec.ToString(Formatting.None));
                emitted++;
            }
            if (emitted == 0) return 0;
            AppendText(_outJsonlPath, sb.ToString());
            _totalEmitted += emitted;
            _lastEmittedSource = source;
            _lastEmitUtc = DateTime.UtcNow;
            BridgeLog.Info("CompileErrorExporter: emitted " + emitted + " from " + source);
            return emitted;
        }

        private bool HasMtimeAdvanced(string path, DateTime mtime)
        {
            DateTime prev;
            bool had = _fileMtimes.TryGetValue(path, out prev);
            _fileMtimes[path] = mtime;
            if (!had) return true;
            return mtime > prev;
        }

        private void MaybeWriteStatus()
        {
            var statusKey = (_lastEmittedSource ?? "") + "|" + _totalEmitted;
            bool sourceChanged = statusKey != _statusKeySnapshot;
            bool stale = (DateTime.UtcNow - _lastStatusFlushUtc).TotalSeconds >= StatusFlushSec;
            if (!sourceChanged && !stale) return;
            _statusKeySnapshot = statusKey;
            _lastStatusFlushUtc = DateTime.UtcNow;
            try
            {
                var compileExists = File.Exists(_compileErrorsTxtPath);
                string newestTrace = null;
                DateTime newestTraceMtime = DateTime.MinValue;
                bool traceExists = Directory.Exists(_traceDir);
                if (traceExists)
                {
                    foreach (string f in SafeEnumerate(_traceDir, "*.txt", SearchOption.TopDirectoryOnly))
                    {
                        DateTime mt = SafeMtime(f);
                        if (mt > newestTraceMtime) { newestTraceMtime = mt; newestTrace = f; }
                    }
                }
                var status = new JObject
                {
                    ["checked_at_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                    ["compile_errors_txt"] = new JObject
                    {
                        ["exists"] = compileExists,
                        ["path"] = _compileErrorsTxtPath,
                    },
                    ["trace_dir"] = new JObject
                    {
                        ["exists"] = traceExists,
                        ["path"] = _traceDir,
                        ["newest_file"] = newestTrace,
                        ["newest_mtime_utc"] = newestTraceMtime == DateTime.MinValue
                            ? null
                            : (JToken)newestTraceMtime.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                    },
                    ["last_emitted_source"] = _lastEmittedSource,
                    ["last_emit_ts_utc"] = _lastEmitUtc == DateTime.MinValue
                        ? null
                        : (JToken)_lastEmitUtc.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                    ["total_emitted"] = _totalEmitted,
                };
                AtomicFile.WriteAllText(_statusJsonPath, status.ToString(Formatting.Indented));
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("CompileErrorExporter: status write failed: " + ex.Message);
            }
        }

        private static void AppendText(string path, string text)
        {
            try
            {
                using (var fs = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read))
                using (var sw = new StreamWriter(fs, new UTF8Encoding(false)))
                {
                    sw.Write(text);
                }
            }
            catch (IOException ex)
            {
                BridgeLog.Warn("CompileErrorExporter: append failed: " + ex.Message);
            }
        }

        private void TrimJsonl()
        {
            try
            {
                if (!File.Exists(_outJsonlPath)) return;
                var info = new FileInfo(_outJsonlPath);
                if (info.Length < 2_000_000) return;
                string[] lines = File.ReadAllLines(_outJsonlPath);
                if (lines.Length <= JsonlTrimMax) return;
                var keep = lines.Skip(lines.Length - JsonlTrimMax).ToArray();
                AtomicFile.WriteAllText(_outJsonlPath, string.Join(Environment.NewLine, keep) + Environment.NewLine);
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("CompileErrorExporter: trim failed: " + ex.Message);
            }
        }

        private static string SafeReadAllText(string path)
        {
            try
            {
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var sr = new StreamReader(fs))
                {
                    return sr.ReadToEnd();
                }
            }
            catch { return ""; }
        }

        private static string SafeReadLastLines(string path, int max)
        {
            try
            {
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var sr = new StreamReader(fs))
                {
                    var buf = new LinkedList<string>();
                    string line;
                    while ((line = sr.ReadLine()) != null)
                    {
                        buf.AddLast(line);
                        if (buf.Count > max) buf.RemoveFirst();
                    }
                    return string.Join("\n", buf);
                }
            }
            catch { return ""; }
        }

        private static DateTime SafeMtime(string path)
        {
            try { return File.GetLastWriteTimeUtc(path); }
            catch { return DateTime.MinValue; }
        }

        private static IEnumerable<string> SafeEnumerate(string root, string pattern, SearchOption opt, bool dirsInsteadOfFiles = false)
        {
            try
            {
                return dirsInsteadOfFiles
                    ? Directory.EnumerateDirectories(root, pattern, opt)
                    : Directory.EnumerateFiles(root, pattern, opt);
            }
            catch
            {
                return Array.Empty<string>();
            }
        }
    }
}
