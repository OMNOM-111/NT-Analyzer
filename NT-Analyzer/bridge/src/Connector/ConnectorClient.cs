using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NTAnalyzerBridge.Config;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Connector
{
    internal sealed class ConnectorHttpException : Exception
    {
        public int StatusCode { get; private set; }
        public string ErrorCode { get; private set; }

        public ConnectorHttpException(int statusCode, string errorCode)
            : base("Connector API rejected request: " + statusCode + " " + (errorCode ?? ""))
        {
            StatusCode = statusCode;
            ErrorCode = errorCode ?? "";
        }
    }

    /// <summary>
    /// Outbound HTTPS long-poll Connector transport. It never opens a local
    /// inbound port and never receives broker credentials. Remote paper
    /// commands are written into the same local idempotent command spool used
    /// by RuntimeCommandProcessor; live control remains blocked.
    /// </summary>
    internal sealed class ConnectorClient
    {
        public const string ClientVersion = "0.2.0";
        private static readonly object AppendLock = new object();
        private const int MaxQueuedMarketDataBatches = 32;
        private const int MaxMarketDataFlushBurst = MaxQueuedMarketDataBatches * 2;
        private const int MaxMarketDataBarsPerBatch = 64;
        private const int MaxMarketDataBatchBytes = 128 * 1024;

        private readonly BridgeConfig _cfg;
        private readonly ProductionConnectorConfig _connector;
        private readonly string _stateDir;
        private readonly string _runtimeDir;
        private readonly HttpClient _http;
        private readonly HashSet<string> _allowedCapabilities =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<string> _queuedCommandIds =
            new HashSet<string>(StringComparer.Ordinal);
        private readonly object _marketDataGate = new object();
        private readonly Queue<PendingMarketDataBatch> _marketDataQueue =
            new Queue<PendingMarketDataBatch>();
        private readonly CancellationTokenSource _cancel = new CancellationTokenSource();
        private static readonly byte[] BootstrapEntropy =
            Encoding.UTF8.GetBytes("StratForge.Connector.Bootstrap.v1");

        private Thread _thread;
        private ConnectorDeviceIdentity _identity;
        private ConnectorState _state;
        private string _sessionToken = "";
        private string _pendingNonce = "";
        private long _sequence;
        private string _updateState = "unknown";
        private string _updateReason = "unknown";
        private DateTime _nextUpdaterCheckUtc = DateTime.MinValue;

        private sealed class PendingMarketDataBatch
        {
            public JArray Bars;
            public long SourceSequence;
        }

        public ConnectorClient(BridgeConfig cfg)
        {
            _cfg = cfg ?? throw new ArgumentNullException(nameof(cfg));
            if (!cfg.IsProductionConnector || cfg.ProductionConnector == null)
                throw new ArgumentException("production_connector mode is required", nameof(cfg));
            _connector = cfg.ProductionConnector;
            _stateDir = Environment.ExpandEnvironmentVariables(_connector.StateDir);
            _runtimeDir = cfg.RuntimeDataDir;
            Directory.CreateDirectory(_stateDir);
            Directory.CreateDirectory(_runtimeDir);

            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            HttpClientHandler handler = new HttpClientHandler
            {
                UseCookies = false,
                AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
            };
            _http = new HttpClient(handler)
            {
                BaseAddress = new Uri(_connector.ServerOrigin.TrimEnd('/') + "/"),
                Timeout = TimeSpan.FromSeconds(Math.Max(30, _connector.CommandPollSeconds + 15)),
            };
            _http.DefaultRequestHeaders.UserAgent.ParseAdd(
                "StratForge-Connector/" + (_connector.ConnectorVersion ?? ClientVersion));
        }

        public void Start()
        {
            if (_thread != null) return;
            ConnectorUpdaterLauncher.TryStart(_cfg);
            _thread = new Thread(Run)
            {
                IsBackground = true,
                Name = "StratForgeConnector",
            };
            _thread.Start();
            BridgeLog.Info("ConnectorClient: outbound transport started");
        }

        public void Stop()
        {
            try { _cancel.Cancel(); } catch { }
            try
            {
                if (_thread != null && !_thread.Join(TimeSpan.FromSeconds(10)))
                    BridgeLog.Warn("ConnectorClient: stop timeout; background thread will terminate with NinjaTrader");
            }
            catch { }
            _thread = null;
            try { _identity?.Dispose(); } catch { }
            _identity = null;
            try { _http.Dispose(); } catch { }
            BridgeLog.Info("ConnectorClient: stopped");
        }

        /// <summary>
        /// Queue a normalized, bounded OHLCV batch for asynchronous Connector upload.
        /// This method performs no HTTP or DPAPI work and is safe for a read-only
        /// NinjaTrader data producer to call from a callback thread.
        /// </summary>
        public bool QueueMarketDataBatch(JArray bars)
        {
            if (bars == null || bars.Count < 1 || bars.Count > MaxMarketDataBarsPerBatch)
                return false;
            JArray copy = new JArray();
            foreach (JToken token in bars)
            {
                JObject row = token as JObject;
                if (row == null) return false;
                copy.Add(row.DeepClone());
            }
            string serialized = copy.ToString(Formatting.None);
            if (Encoding.UTF8.GetByteCount(serialized) > MaxMarketDataBatchBytes)
                return false;
            lock (_marketDataGate)
            {
                if (_marketDataQueue.Count >= MaxQueuedMarketDataBatches)
                {
                    _marketDataQueue.Dequeue();
                    BridgeLog.Warn("ConnectorClient: dropped oldest queued market-data batch");
                }
                _marketDataQueue.Enqueue(new PendingMarketDataBatch { Bars = copy });
            }
            return true;
        }

        private void Run()
        {
            int backoffSeconds = 2;
            try
            {
                if (File.Exists(Path.Combine(_stateDir, "bootstrap.dpapi")))
                {
                    try { File.Delete(Path.Combine(_stateDir, "device-key.dpapi")); } catch { }
                    _state = ConnectorStateStore.Load(_stateDir);
                    _state.Revoked = false;
                    _state.InstallationId = null;
                    _state.PublicKeyFingerprint = null;
                    ConnectorStateStore.Save(_stateDir, _state);
                }
                _identity = ConnectorDeviceIdentity.LoadOrCreate(_stateDir);
                _state = ConnectorStateStore.Load(_stateDir);
                EnsureStateIdentity();
                SeedQueuedCommands();
                while (!_cancel.IsCancellationRequested)
                {
                    if (_state.Revoked)
                    {
                        BridgeLog.Warn("ConnectorClient: installation is revoked; commands disabled");
                        return;
                    }
                    try
                    {
                        EnsureSession();
                        SendHeartbeat();
                        FlushMarketData();
                        PollCommands();
                        ReportRuntimeResults();
                        backoffSeconds = 2;
                    }
                    catch (ConnectorHttpException ex)
                    {
                        if (ex.ErrorCode == "installation_revoked")
                        {
                            _state.Revoked = true;
                            ConnectorStateStore.Save(_stateDir, _state);
                            BridgeLog.Warn("ConnectorClient: server revoked this installation");
                            return;
                        }
                        if (ex.StatusCode == 401 || ex.ErrorCode == "session_expired")
                        {
                            _sessionToken = "";
                            _pendingNonce = "";
                        }
                        BridgeLog.Warn("ConnectorClient: API unavailable (" + ex.ErrorCode + ")");
                        WaitWithCancellation(backoffSeconds * 1000);
                        backoffSeconds = Math.Min(backoffSeconds * 2, 60);
                    }
                    catch (Exception ex)
                    {
                        BridgeLog.Warn("ConnectorClient: transient failure " + ex.GetType().Name);
                        WaitWithCancellation(backoffSeconds * 1000);
                        backoffSeconds = Math.Min(backoffSeconds * 2, 60);
                    }
                }
            }
            catch (Exception ex)
            {
                BridgeLog.Error("ConnectorClient startup failed", ex);
            }
        }

        private void EnsureStateIdentity()
        {
            string fingerprint = _identity.Fingerprint();
            if (!string.IsNullOrWhiteSpace(_state.PublicKeyFingerprint) &&
                !string.Equals(_state.PublicKeyFingerprint, fingerprint, StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "connector state fingerprint differs from DPAPI device key");
            }
            _state.PublicKeyFingerprint = fingerprint;
            if (string.IsNullOrWhiteSpace(_state.NinjaInstanceId))
                _state.NinjaInstanceId = BuildNinjaInstanceId(_cfg.NinjaTraderUserDir);
            ConnectorStateStore.Save(_stateDir, _state);
        }

        private void EnsureSession()
        {
            if (!string.IsNullOrWhiteSpace(_sessionToken)) return;
            if (string.IsNullOrWhiteSpace(_state.InstallationId))
                Enroll();
            if (string.IsNullOrWhiteSpace(_pendingNonce))
            {
                byte[] clientNonceBytes = new byte[32];
                using (RandomNumberGenerator random = RandomNumberGenerator.Create())
                    random.GetBytes(clientNonceBytes);
                JObject challengeRequest = new JObject
                {
                    ["protocol_version"] = _connector.ProtocolVersion,
                    ["installation_id"] = _state.InstallationId,
                    ["public_key_fingerprint"] = _identity.Fingerprint(),
                    ["client_nonce"] = ConnectorDeviceIdentity.Base64Url(clientNonceBytes),
                    ["requested_at"] = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                };
                challengeRequest["signature"] = _identity.SignBase64Url(
                    BuildChallengeSigningMessage(challengeRequest));
                JObject challenge = PostJson(
                    "api/connector/v1/challenge",
                    challengeRequest,
                    "");
                _pendingNonce = (string)challenge["nonce"] ?? "";
            }
            JObject hello = new JObject
            {
                ["protocol_version"] = _connector.ProtocolVersion,
                ["connector_version"] = _connector.ConnectorVersion,
                ["nt_version"] = SafeNinjaVersion(),
                ["installation_id"] = _state.InstallationId,
                ["workspace_id"] = _state.WorkspaceId,
                ["nonce"] = _pendingNonce,
                ["public_key_fingerprint"] = _identity.Fingerprint(),
                ["ninja_instance_id"] = _state.NinjaInstanceId,
            };
            hello["signature"] = _identity.SignBase64Url(
                BuildHelloSigningMessage(hello));
            JObject welcome = PostJson("api/connector/v1/hello", hello, "");
            _sessionToken = (string)welcome["session_token"] ?? "";
            if (string.IsNullOrWhiteSpace(_sessionToken))
                throw new InvalidOperationException("Connector welcome omitted session token");
            _pendingNonce = "";
            _sequence = 0;
            _allowedCapabilities.Clear();
            JArray grants = welcome["allowed_capabilities"] as JArray;
            if (grants != null)
            {
                foreach (JToken token in grants)
                {
                    string value = (string)token ?? "";
                    if (!string.IsNullOrWhiteSpace(value)) _allowedCapabilities.Add(value);
                }
            }
            _updateState = (string)welcome["update_state"] ?? "unknown";
            _updateReason = (string)welcome["update_reason"] ?? "unknown";
            ConnectorUpdaterLauncher.StoreOffer(
                _stateDir, welcome["update_offer"] as JObject);
            BridgeLog.Info("ConnectorClient: signed hello accepted; state=online update=" + _updateState);
        }

        private void Enroll()
        {
            string enrollmentCode = ResolveEnrollmentCode();
            if (string.IsNullOrWhiteSpace(enrollmentCode))
                throw new InvalidOperationException("production_connector enrollment credential is required for first start");
            JObject enrolled = PostJson("api/connector/v1/enroll", new JObject
            {
                ["code"] = enrollmentCode,
                ["public_key"] = _identity.PublicJwk(),
                ["connector_version"] = _connector.ConnectorVersion,
                ["nt_version"] = SafeNinjaVersion(),
                ["machine_label"] = Environment.MachineName,
                ["ninja_instance_id"] = _state.NinjaInstanceId,
            }, "");
            _state.InstallationId = (string)enrolled["installation_id"] ?? "";
            _state.ConnectionId = (string)enrolled["connection_id"] ?? "";
            _state.WorkspaceId = (string)enrolled["workspace_id"] ?? "";
            _state.PublicKeyFingerprint = (string)enrolled["public_key_fingerprint"] ?? "";
            _pendingNonce = (string)enrolled["nonce"] ?? "";
            if (string.IsNullOrWhiteSpace(_state.InstallationId) ||
                string.IsNullOrWhiteSpace(_state.WorkspaceId) ||
                string.IsNullOrWhiteSpace(_pendingNonce))
            {
                throw new InvalidOperationException("Connector enrollment response incomplete");
            }
            if (!string.Equals(_state.PublicKeyFingerprint, _identity.Fingerprint(), StringComparison.Ordinal))
                throw new InvalidOperationException("Connector enrollment fingerprint mismatch");
            ConnectorStateStore.Save(_stateDir, _state);
            DeleteConsumedBootstrap();
            BridgeLog.Info("ConnectorClient: one-time enrollment consumed; state=pending");
        }

        private string ResolveEnrollmentCode()
        {
            string legacy = (_connector.EnrollmentCode ?? "").Trim();
            if (!string.IsNullOrWhiteSpace(legacy)) return legacy;
            if (!string.Equals(
                    _connector.EnrollmentCredentialRef,
                    "dpapi:bootstrap-v1",
                    StringComparison.Ordinal))
                return "";
            string path = Path.Combine(_stateDir, "bootstrap.dpapi");
            if (!File.Exists(path)) return "";
            byte[] encrypted = File.ReadAllBytes(path);
            byte[] plaintext = ProtectedData.Unprotect(
                encrypted, BootstrapEntropy, DataProtectionScope.CurrentUser);
            try
            {
                return Encoding.UTF8.GetString(plaintext).Trim();
            }
            finally
            {
                Array.Clear(plaintext, 0, plaintext.Length);
            }
        }

        private void DeleteConsumedBootstrap()
        {
            if (!string.Equals(
                    _connector.EnrollmentCredentialRef,
                    "dpapi:bootstrap-v1",
                    StringComparison.Ordinal))
                return;
            string path = Path.Combine(_stateDir, "bootstrap.dpapi");
            try { if (File.Exists(path)) File.Delete(path); }
            catch (Exception ex)
            {
                BridgeLog.Warn("ConnectorClient: consumed bootstrap cleanup failed: " + ex.GetType().Name);
            }
        }

        private void SendHeartbeat()
        {
            JObject heartbeat = new JObject
            {
                ["connector_sequence"] = NextSequence(),
                ["ninja_instance_id"] = _state.NinjaInstanceId,
                ["connector_time"] = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                ["account_labels"] = ReadMaskedAccountLabels(),
            };
            JObject accountSnapshot = ReadAccountSnapshot();
            if (accountSnapshot != null && _allowedCapabilities.Contains("accounts_read"))
                heartbeat["account_snapshot"] = accountSnapshot;
            JObject response = PostJson(
                "api/connector/v1/heartbeat", heartbeat, _sessionToken);
            _updateState = (string)response["update_state"] ?? _updateState;
            _updateReason = (string)response["update_reason"] ?? _updateReason;
            ConnectorUpdaterLauncher.StoreOffer(
                _stateDir, response["update_offer"] as JObject);
            ConnectorUpdaterLauncher.RecordHealth(
                _stateDir,
                _connector.ConnectorVersion,
                _updateState,
                _updateReason,
                _state.InstallationId);
            if (DateTime.UtcNow >= _nextUpdaterCheckUtc)
            {
                ConnectorUpdaterLauncher.TryStart(_cfg);
                ScheduleNextUpdaterCheck();
            }
        }

        private void FlushMarketData()
        {
            if (!_allowedCapabilities.Contains("telemetry")) return;
            // The command endpoint is a bounded long poll. Draining only one
            // snapshot before entering that poll makes two 1 Hz streams outrun
            // the 32-item queue and leaves the server with systematically old
            // bars. Drain a bounded burst first; the cap preserves command and
            // heartbeat fairness if a producer is unusually busy.
            for (int sent = 0; sent < MaxMarketDataFlushBurst; sent++)
            {
                if (!FlushOneMarketDataBatch()) return;
            }
        }

        private bool FlushOneMarketDataBatch()
        {
            PendingMarketDataBatch batch;
            lock (_marketDataGate)
            {
                if (_marketDataQueue.Count == 0) return false;
                batch = _marketDataQueue.Peek();
            }
            if (batch.SourceSequence < 1)
            {
                long next = _state == null ? 1 : _state.MarketDataSourceSequence + 1;
                if (next < 1) throw new InvalidOperationException("market-data source sequence overflow");
                batch.SourceSequence = next;
                _state.MarketDataSourceSequence = next;
                ConnectorStateStore.Save(_stateDir, _state);
            }
            try
            {
                PostJson("api/connector/v1/market-data", new JObject
                {
                    ["connector_sequence"] = NextSequence(),
                    ["source_sequence"] = batch.SourceSequence,
                    ["bars"] = batch.Bars.DeepClone(),
                }, _sessionToken);
            }
            catch (ConnectorHttpException ex)
            {
                if (ex.ErrorCode == "invalid_market_data" ||
                    ex.ErrorCode == "invalid_market_data_batch" ||
                    ex.ErrorCode == "invalid_market_data_bar" ||
                    ex.ErrorCode == "source_sequence_conflict" ||
                    ex.ErrorCode == "source_sequence_replay")
                {
                    lock (_marketDataGate)
                    {
                        if (_marketDataQueue.Count > 0 && Object.ReferenceEquals(_marketDataQueue.Peek(), batch))
                            _marketDataQueue.Dequeue();
                    }
                    BridgeLog.Warn("ConnectorClient: dropped rejected market-data batch (" + ex.ErrorCode + ")");
                    return true;
                }
                throw;
            }
            lock (_marketDataGate)
            {
                if (_marketDataQueue.Count > 0 && Object.ReferenceEquals(_marketDataQueue.Peek(), batch))
                    _marketDataQueue.Dequeue();
            }
            return true;
        }

        private void PollCommands()
        {
            JObject response = PostJson("api/connector/v1/commands/poll", new JObject
            {
                ["connector_sequence"] = NextSequence(),
                ["wait_seconds"] = _connector.CommandPollSeconds,
                ["limit"] = 10,
            }, _sessionToken);
            JArray commands = response["commands"] as JArray;
            if (commands == null || commands.Count == 0) return;
            foreach (JObject command in commands.OfType<JObject>())
                HandleCommand(command);
        }

        private void HandleCommand(JObject envelope)
        {
            string commandId = (string)envelope["command_id"] ?? "";
            string workspaceId = (string)envelope["workspace_id"] ?? "";
            string connectionId = (string)envelope["connection_id"] ?? "";
            string capability = (string)envelope["capability"] ?? "";
            string idempotencyKey = (string)envelope["idempotency_key"] ?? "";
            JObject payload = envelope["payload"] as JObject;
            DateTime expires;
            if (string.IsNullOrWhiteSpace(commandId) ||
                !string.Equals(workspaceId, _state.WorkspaceId, StringComparison.Ordinal) ||
                !string.Equals(connectionId, _state.ConnectionId, StringComparison.Ordinal) ||
                string.IsNullOrWhiteSpace(idempotencyKey) || payload == null ||
                !_allowedCapabilities.Contains(capability))
            {
                ReportResult(commandId, idempotencyKey, "rejected",
                    "invalid command envelope", "scope_or_capability_mismatch");
                return;
            }
            if (!DateTime.TryParse(
                    (string)envelope["expires_at_utc"] ?? "",
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal,
                    out expires) || expires <= DateTime.UtcNow)
            {
                ReportResult(commandId, idempotencyKey, "rejected",
                    "command expired before execution", "expired_before_execution");
                return;
            }
            if (_updateState == "blocked" &&
                (capability == "paper_commands" || capability == "live_commands"))
            {
                ReportResult(commandId, idempotencyKey, "rejected",
                    "connector version blocked", "connector_update_required");
                return;
            }
            string commandName = (string)payload["command"] ?? "";
            if (capability == "telemetry" && commandName == "ping")
            {
                ReportResult(commandId, idempotencyKey, "completed", "pong", "");
                return;
            }
            if (capability == "telemetry" && commandName == "snapshot_runtime")
            {
                ReportResult(commandId, idempotencyKey, "completed",
                    "runtime snapshot available", "");
                return;
            }
            if (capability == "accounts_read" && commandName == "snapshot_accounts")
            {
                ReportResult(commandId, idempotencyKey, "completed",
                    "account snapshot refreshed", "");
                return;
            }
            if (capability != "paper_commands")
            {
                ReportResult(commandId, idempotencyKey, "rejected",
                    "unsupported capability", "unsupported_capability");
                return;
            }
            if (_queuedCommandIds.Contains(commandId)) return;
            JObject local = (JObject)payload.DeepClone();
            local["command_id"] = commandId;
            local["idempotency_key"] = idempotencyKey;
            local["connector_origin"] = true;
            local["workspace_id"] = workspaceId;
            local["connection_id"] = connectionId;
            local["expires_at_utc"] = expires.ToString("o", CultureInfo.InvariantCulture);
            string commandsPath = Path.Combine(_runtimeDir, "commands.jsonl");
            lock (AppendLock)
            {
                Directory.CreateDirectory(_runtimeDir);
                File.AppendAllText(
                    commandsPath,
                    local.ToString(Formatting.None) + Environment.NewLine,
                    new UTF8Encoding(false));
            }
            _queuedCommandIds.Add(commandId);
            ReportResult(commandId, idempotencyKey, "accepted",
                "queued for NinjaTrader paper command processor", "");
        }

        private void ReportRuntimeResults()
        {
            string path = Path.Combine(_runtimeDir, "command_results.jsonl");
            if (!File.Exists(path) || _queuedCommandIds.Count == 0) return;
            HashSet<string> reported = new HashSet<string>(
                _state.ReportedCommandIds ?? new List<string>(), StringComparer.Ordinal);
            foreach (string line in File.ReadLines(path, Encoding.UTF8))
            {
                JObject row;
                try { row = JObject.Parse(line); }
                catch { continue; }
                string id = (string)row["command_id"] ?? "";
                if (!_queuedCommandIds.Contains(id) || reported.Contains(id)) continue;
                string localStatus = ((string)row["status"] ?? "").ToLowerInvariant();
                string status = localStatus == "completed" || localStatus == "success"
                    ? "completed"
                    : localStatus == "rejected" ? "rejected" : "failed";
                string idempotencyKey = FindLocalIdempotencyKey(id);
                if (string.IsNullOrWhiteSpace(idempotencyKey)) continue;
                string message = (string)row["message"] ?? (string)row["error"] ?? status;
                ReportResult(id, idempotencyKey, status, Truncate(message, 1000),
                    status == "failed" ? "ninjatrader_command_failed" : "");
                reported.Add(id);
                _state.ReportedCommandIds.Add(id);
                ConnectorStateStore.Save(_stateDir, _state);
            }
        }

        private void ReportResult(
            string commandId, string idempotencyKey, string status,
            string message, string errorClass)
        {
            if (string.IsNullOrWhiteSpace(commandId) || string.IsNullOrWhiteSpace(idempotencyKey))
                return;
            PostJson("api/connector/v1/commands/result", new JObject
            {
                ["command_id"] = commandId,
                ["idempotency_key"] = idempotencyKey,
                ["status"] = status,
                ["connector_sequence"] = NextSequence(),
                ["safe_result"] = new JObject { ["message"] = Truncate(message, 1000) },
                ["error_class"] = errorClass ?? "",
            }, _sessionToken);
        }

        private JObject PostJson(string path, JObject body, string bearerToken)
        {
            using (HttpRequestMessage request = new HttpRequestMessage(HttpMethod.Post, path))
            {
                request.Content = new StringContent(
                    body.ToString(Formatting.None), Encoding.UTF8, "application/json");
                request.Headers.CacheControl = new CacheControlHeaderValue { NoCache = true };
                if (!string.IsNullOrWhiteSpace(bearerToken))
                    request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearerToken);
                using (HttpResponseMessage response = _http.SendAsync(
                    request, _cancel.Token).GetAwaiter().GetResult())
                {
                    string text = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                    JObject parsed = new JObject();
                    try { if (!string.IsNullOrWhiteSpace(text)) parsed = JObject.Parse(text); }
                    catch { }
                    if (!response.IsSuccessStatusCode)
                        throw new ConnectorHttpException(
                            (int)response.StatusCode, (string)parsed["code"] ?? "http_error");
                    return parsed;
                }
            }
        }

        internal static byte[] BuildHelloSigningMessage(JObject hello)
        {
            string[] names =
            {
                "connector_version", "installation_id", "ninja_instance_id", "nonce",
                "nt_version", "protocol_version", "public_key_fingerprint", "workspace_id",
            };
            StringBuilder json = new StringBuilder(512);
            json.Append('{');
            for (int i = 0; i < names.Length; i++)
            {
                if (i > 0) json.Append(',');
                json.Append(JsonConvert.ToString(names[i]));
                json.Append(':');
                json.Append(JsonConvert.ToString((string)hello[names[i]] ?? ""));
            }
            json.Append('}');
            return Encoding.UTF8.GetBytes(json.ToString());
        }

        internal static byte[] BuildChallengeSigningMessage(JObject challenge)
        {
            string[] names =
            {
                "client_nonce", "installation_id", "protocol_version",
                "public_key_fingerprint", "requested_at",
            };
            StringBuilder json = new StringBuilder(384);
            json.Append('{');
            for (int i = 0; i < names.Length; i++)
            {
                if (i > 0) json.Append(',');
                json.Append(JsonConvert.ToString(names[i]));
                json.Append(':');
                json.Append(JsonConvert.ToString((string)challenge[names[i]] ?? ""));
            }
            json.Append('}');
            return Encoding.UTF8.GetBytes(json.ToString());
        }

        private void ScheduleNextUpdaterCheck()
        {
            // Periodic checks use a 6..24 hour jitter window so a release does
            // not cause every Connector to hit the control plane at once.
            byte[] bytes = new byte[4];
            using (RandomNumberGenerator random = RandomNumberGenerator.Create())
                random.GetBytes(bytes);
            uint sample = BitConverter.ToUInt32(bytes, 0);
            int jitterMinutes = (int)(sample % (18 * 60 + 1));
            _nextUpdaterCheckUtc = DateTime.UtcNow.AddMinutes(6 * 60 + jitterMinutes);
        }

        private long NextSequence()
        {
            return Interlocked.Increment(ref _sequence);
        }

        private void SeedQueuedCommands()
        {
            string path = Path.Combine(_runtimeDir, "commands.jsonl");
            if (!File.Exists(path)) return;
            foreach (string line in File.ReadLines(path, Encoding.UTF8))
            {
                try
                {
                    JObject row = JObject.Parse(line);
                    if ((bool?)row["connector_origin"] != true) continue;
                    string id = (string)row["command_id"] ?? "";
                    if (!string.IsNullOrWhiteSpace(id)) _queuedCommandIds.Add(id);
                }
                catch { }
            }
        }

        private string FindLocalIdempotencyKey(string commandId)
        {
            string path = Path.Combine(_runtimeDir, "commands.jsonl");
            if (!File.Exists(path)) return "";
            foreach (string line in File.ReadLines(path, Encoding.UTF8))
            {
                try
                {
                    JObject row = JObject.Parse(line);
                    if (string.Equals((string)row["command_id"], commandId, StringComparison.Ordinal))
                        return (string)row["idempotency_key"] ?? "";
                }
                catch { }
            }
            return "";
        }

        private JArray ReadMaskedAccountLabels()
        {
            JArray labels = new JArray();
            string path = Path.Combine(_runtimeDir, "accounts.json");
            if (!File.Exists(path)) return labels;
            try
            {
                JObject root = JObject.Parse(File.ReadAllText(path));
                JArray accounts = root["accounts"] as JArray;
                if (accounts == null) return labels;
                foreach (JObject account in accounts.OfType<JObject>().Take(20))
                {
                    string raw = (string)account["account_name"] ?? "";
                    string compact = new string(raw.Where(char.IsLetterOrDigit).ToArray());
                    if (compact.Length == 0) continue;
                    labels.Add("***" + compact.Substring(Math.Max(0, compact.Length - 4)));
                }
            }
            catch { }
            return labels;
        }

        private JObject ReadAccountSnapshot()
        {
            string path = Path.Combine(_runtimeDir, "accounts.json");
            if (!File.Exists(path)) return null;
            try
            {
                FileInfo info = new FileInfo(path);
                if (info.Length <= 0 || info.Length > 48 * 1024)
                {
                    BridgeLog.Warn("ConnectorClient: accounts.json exceeds the bounded snapshot size");
                    return null;
                }
                JObject root = JObject.Parse(File.ReadAllText(path, Encoding.UTF8));
                JArray source = root["accounts"] as JArray;
                if (source == null || source.Count > 20) return null;
                JObject snapshot = new JObject
                {
                    ["generated_at_utc"] = (string)root["generated_at_utc"] ?? "",
                    ["exporter_version"] = (string)root["exporter_version"] ?? "",
                    ["accounts"] = new JArray(),
                };
                JArray accounts = (JArray)snapshot["accounts"];
                string[] fields = new[]
                {
                    "account_name", "account_mode", "cash_value", "buying_power",
                    "net_liquidation", "realized_pnl", "unrealized_pnl", "currency",
                    "connection_status", "availability_notes",
                };
                foreach (JObject account in source.OfType<JObject>().Take(20))
                {
                    JObject clean = new JObject();
                    foreach (string field in fields)
                    {
                        JToken value = account[field];
                        if (value != null) clean[field] = value.DeepClone();
                    }
                    accounts.Add(clean);
                }
                if (root["summary"] is JObject summary)
                    snapshot["summary"] = summary.DeepClone();
                return snapshot;
            }
            catch (Exception ex)
            {
                BridgeLog.Warn("ConnectorClient: account snapshot unavailable: " + ex.GetType().Name);
                return null;
            }
        }

        private static string BuildNinjaInstanceId(string ninjaTraderUserDir)
        {
            string value = Environment.MachineName + "|" + Environment.UserName + "|" +
                (ninjaTraderUserDir ?? "");
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(Encoding.UTF8.GetBytes(value));
                StringBuilder text = new StringBuilder("nt_");
                for (int i = 0; i < 12; i++) text.Append(digest[i].ToString("x2"));
                return text.ToString();
            }
        }

        private static string SafeNinjaVersion()
        {
            try
            {
                Type globals = Type.GetType("NinjaTrader.Core.Globals, NinjaTrader.Core");
                object value = globals?.GetProperty("ProductVersion")?.GetValue(null, null);
                string version = value == null ? "" : value.ToString();
                if (!string.IsNullOrWhiteSpace(version))
                    return new string(version.Where(ch => char.IsLetterOrDigit(ch) || ".+-_".Contains(ch)).ToArray());
            }
            catch { }
            return "8.0.0-unknown";
        }

        private void WaitWithCancellation(int milliseconds)
        {
            try { _cancel.Token.WaitHandle.WaitOne(Math.Max(0, milliseconds)); }
            catch { }
        }

        private static string Truncate(string value, int max)
        {
            string text = value ?? "";
            return text.Length <= max ? text : text.Substring(0, max);
        }
    }
}
