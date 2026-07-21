using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;

using Newtonsoft.Json;

namespace NTAnalyzerBridge.Connector
{
    internal sealed class ConnectorState
    {
        [JsonProperty("schema_version")]
        public int SchemaVersion { get; set; } = 1;

        [JsonProperty("installation_id")]
        public string InstallationId { get; set; } = "";

        [JsonProperty("connection_id")]
        public string ConnectionId { get; set; } = "";

        [JsonProperty("workspace_id")]
        public string WorkspaceId { get; set; } = "";

        [JsonProperty("public_key_fingerprint")]
        public string PublicKeyFingerprint { get; set; } = "";

        [JsonProperty("ninja_instance_id")]
        public string NinjaInstanceId { get; set; } = "";

        [JsonProperty("revoked")]
        public bool Revoked { get; set; }

        [JsonProperty("reported_command_ids")]
        public List<string> ReportedCommandIds { get; set; } = new List<string>();
    }

    internal static class ConnectorStateStore
    {
        private static readonly byte[] Entropy =
            Encoding.UTF8.GetBytes("StratForge.Connector.State.v1");

        public static ConnectorState Load(string stateDir)
        {
            string path = Path.Combine(stateDir, "connector-state.dpapi");
            if (!File.Exists(path)) return new ConnectorState();
            byte[] protectedPayload = File.ReadAllBytes(path);
            byte[] plaintext = ProtectedData.Unprotect(
                protectedPayload, Entropy, DataProtectionScope.CurrentUser);
            try
            {
                ConnectorState state = JsonConvert.DeserializeObject<ConnectorState>(
                    Encoding.UTF8.GetString(plaintext));
                return state ?? new ConnectorState();
            }
            finally
            {
                Array.Clear(plaintext, 0, plaintext.Length);
            }
        }

        public static void Save(string stateDir, ConnectorState state)
        {
            if (state == null) throw new ArgumentNullException(nameof(state));
            Directory.CreateDirectory(stateDir);
            if (state.ReportedCommandIds == null)
                state.ReportedCommandIds = new List<string>();
            if (state.ReportedCommandIds.Count > 1000)
                state.ReportedCommandIds.RemoveRange(0, state.ReportedCommandIds.Count - 1000);
            byte[] plaintext = Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(state));
            try
            {
                byte[] encrypted = ProtectedData.Protect(
                    plaintext, Entropy, DataProtectionScope.CurrentUser);
                string path = Path.Combine(stateDir, "connector-state.dpapi");
                string tmp = path + ".tmp";
                File.WriteAllBytes(tmp, encrypted);
                if (File.Exists(path)) File.Replace(tmp, path, null);
                else File.Move(tmp, path);
                try { File.SetAttributes(path, FileAttributes.Hidden); } catch { }
            }
            finally
            {
                Array.Clear(plaintext, 0, plaintext.Length);
            }
        }
    }
}
