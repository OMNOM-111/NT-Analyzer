using System;
using System.IO;
using System.Reflection;

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

internal static class Program
{
    private static int Main(string[] args)
    {
        if (args.Length != 2)
        {
            Console.Error.WriteLine("usage: ConnectorInteropHarness <bridge-dll> <state-dir>");
            return 2;
        }
        string bridgePath = Path.GetFullPath(args[0]);
        string stateDir = Path.GetFullPath(args[1]);
        Directory.CreateDirectory(stateDir);
        Assembly bridge = Assembly.LoadFrom(bridgePath);
        Type identityType = bridge.GetType(
            "NTAnalyzerBridge.Connector.ConnectorDeviceIdentity", true);
        Type clientType = bridge.GetType(
            "NTAnalyzerBridge.Connector.ConnectorClient", true);
        Type configType = bridge.GetType(
            "NTAnalyzerBridge.Config.BridgeConfig", true);
        object identity = identityType.GetMethod(
            "LoadOrCreate", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            .Invoke(null, new object[] { stateDir });
        try
        {
            JObject publicKey = (JObject)identityType.GetMethod(
                "PublicJwk", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
                .Invoke(identity, null);
            string fingerprint = (string)identityType.GetMethod(
                "Fingerprint", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
                .Invoke(identity, null);
            JObject hello = new JObject
            {
                ["protocol_version"] = "1.0",
                ["connector_version"] = "0.2.0-probe",
                ["nt_version"] = "8.1.6.3",
                ["installation_id"] = "inst_interop_probe_0001",
                ["workspace_id"] = "ws_interop_probe_0001",
                ["nonce"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY",
                ["public_key_fingerprint"] = fingerprint,
                ["ninja_instance_id"] = "nt_interop_probe_0001",
            };
            byte[] message = (byte[])clientType.GetMethod(
                "BuildHelloSigningMessage",
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
                .Invoke(null, new object[] { hello });
            string signature = (string)identityType.GetMethod(
                "SignBase64Url", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
                .Invoke(identity, new object[] { message });
            hello["signature"] = signature;
            JObject challenge = new JObject
            {
                ["protocol_version"] = "1.0",
                ["installation_id"] = "inst_interop_probe_0001",
                ["public_key_fingerprint"] = fingerprint,
                ["client_nonce"] = "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M",
                ["requested_at"] = "2026-07-21T12:00:00.0000000Z",
            };
            byte[] challengeMessage = (byte[])clientType.GetMethod(
                "BuildChallengeSigningMessage",
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
                .Invoke(null, new object[] { challenge });
            challenge["signature"] = (string)identityType.GetMethod(
                "SignBase64Url", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
                .Invoke(identity, new object[] { challengeMessage });
            JObject validConfig = new JObject
            {
                ["schema_version"] = 3,
                ["mode"] = "production_connector",
                ["ninjatrader_user_dir"] = stateDir,
                ["runtime_data_dir"] = Path.Combine(stateDir, "spool"),
                ["production_connector"] = new JObject
                {
                    ["enabled"] = true,
                    ["server_origin"] = "https://app.stratforges.com",
                    ["protocol_version"] = "1.0",
                    ["connector_version"] = "0.4.0-probe",
                    ["enrollment_credential_ref"] = "dpapi:bootstrap-v1",
                    ["state_dir"] = stateDir,
                    ["heartbeat_interval_ms"] = 15000,
                    ["command_poll_seconds"] = 15,
                    ["release_channel"] = "stable",
                    ["update_policy"] = "safe_restart",
                },
            };
            bool validConfigAccepted = LoadConfig(configType, stateDir, "valid.json", validConfig);
            JObject unknownConfig = (JObject)validConfig.DeepClone();
            unknownConfig["production_connector"]["unexpected_network_field"] = true;
            bool unknownConfigRejected = !LoadConfig(
                configType, stateDir, "unknown.json", unknownConfig);
            JObject plaintextConfig = (JObject)validConfig.DeepClone();
            plaintextConfig["production_connector"]["enrollment_code"] = "23456789ABCDEFGH";
            bool plaintextCodeRejected = !LoadConfig(
                configType, stateDir, "plaintext.json", plaintextConfig);
            JObject output = new JObject
            {
                ["public_key"] = publicKey,
                ["fingerprint"] = fingerprint,
                ["message_base64"] = Convert.ToBase64String(message),
                ["hello"] = hello,
                ["challenge_message_base64"] = Convert.ToBase64String(challengeMessage),
                ["challenge"] = challenge,
                ["config_contract"] = new JObject
                {
                    ["schema3_without_project_root"] = validConfigAccepted,
                    ["unknown_production_field_rejected"] = unknownConfigRejected,
                    ["plaintext_enrollment_code_rejected"] = plaintextCodeRejected,
                },
            };
            Console.WriteLine(output.ToString(Formatting.None));
            return 0;
        }
        finally
        {
            IDisposable disposable = identity as IDisposable;
            if (disposable != null) disposable.Dispose();
        }
    }

    private static bool LoadConfig(
        Type configType, string stateDir, string name, JObject value)
    {
        string path = Path.Combine(stateDir, name);
        File.WriteAllText(path, value.ToString(Formatting.None));
        object[] arguments = new object[] { path, null };
        object loaded = configType.GetMethod(
            "LoadOrNull", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            .Invoke(null, arguments);
        return loaded != null && string.IsNullOrWhiteSpace(arguments[1] as string);
    }
}
