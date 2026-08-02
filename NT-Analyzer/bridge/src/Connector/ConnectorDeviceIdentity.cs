using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

using Newtonsoft.Json.Linq;

namespace NTAnalyzerBridge.Connector
{
    /// <summary>
    /// Device-owned P-256 key protected with Windows DPAPI CurrentUser. The
    /// server receives only the public JWK and SHA-256 fingerprint.
    /// </summary>
    internal sealed class ConnectorDeviceIdentity : IDisposable
    {
        private static readonly byte[] Entropy =
            Encoding.UTF8.GetBytes("StratForge.Connector.DeviceKey.v1");

        private readonly ECDsaCng _key;

        private ConnectorDeviceIdentity(ECDsaCng key)
        {
            _key = key ?? throw new ArgumentNullException(nameof(key));
            _key.HashAlgorithm = CngAlgorithm.Sha256;
        }

        public static ConnectorDeviceIdentity LoadOrCreate(string stateDir)
        {
            if (string.IsNullOrWhiteSpace(stateDir))
                throw new ArgumentNullException(nameof(stateDir));
            Directory.CreateDirectory(stateDir);
            string path = Path.Combine(stateDir, "device-key.dpapi");
            if (File.Exists(path))
            {
                byte[] protectedBlob = File.ReadAllBytes(path);
                byte[] privateBlob = ProtectedData.Unprotect(
                    protectedBlob, Entropy, DataProtectionScope.CurrentUser);
                try
                {
                    CngKey imported = CngKey.Import(
                        privateBlob, CngKeyBlobFormat.EccPrivateBlob);
                    return new ConnectorDeviceIdentity(new ECDsaCng(imported));
                }
                finally
                {
                    Array.Clear(privateBlob, 0, privateBlob.Length);
                }
            }

            CngKeyCreationParameters creation = new CngKeyCreationParameters
            {
                ExportPolicy = CngExportPolicies.AllowPlaintextExport,
                KeyUsage = CngKeyUsages.Signing,
            };
            CngKey created = CngKey.Create(CngAlgorithm.ECDsaP256, null, creation);
            ECDsaCng ecdsa = new ECDsaCng(created);
            byte[] raw = created.Export(CngKeyBlobFormat.EccPrivateBlob);
            try
            {
                byte[] encrypted = ProtectedData.Protect(
                    raw, Entropy, DataProtectionScope.CurrentUser);
                AtomicWrite(path, encrypted);
                try { File.SetAttributes(path, FileAttributes.Hidden); } catch { }
            }
            finally
            {
                Array.Clear(raw, 0, raw.Length);
            }
            return new ConnectorDeviceIdentity(ecdsa);
        }

        public JObject PublicJwk()
        {
            ECParameters parameters = _key.ExportParameters(false);
            return new JObject
            {
                ["kty"] = "EC",
                ["crv"] = "P-256",
                ["x"] = Base64Url(parameters.Q.X),
                ["y"] = Base64Url(parameters.Q.Y),
            };
        }

        public string Fingerprint()
        {
            ECParameters parameters = _key.ExportParameters(false);
            byte[] point = new byte[65];
            point[0] = 0x04;
            Buffer.BlockCopy(parameters.Q.X, 0, point, 1, 32);
            Buffer.BlockCopy(parameters.Q.Y, 0, point, 33, 32);
            using (SHA256 sha = SHA256.Create())
            {
                return "SHA256:" + Hex(sha.ComputeHash(point));
            }
        }

        public string SignBase64Url(byte[] message)
        {
            if (message == null) throw new ArgumentNullException(nameof(message));
            byte[] signature = _key.SignData(message, HashAlgorithmName.SHA256);
            return Base64Url(signature);
        }

        public void Dispose()
        {
            try { _key.Dispose(); } catch { }
        }

        private static void AtomicWrite(string path, byte[] data)
        {
            string tmp = path + ".tmp";
            File.WriteAllBytes(tmp, data);
            if (File.Exists(path))
                File.Replace(tmp, path, null);
            else
                File.Move(tmp, path);
        }

        internal static string Base64Url(byte[] value)
        {
            return Convert.ToBase64String(value ?? new byte[0])
                .TrimEnd('=').Replace('+', '-').Replace('/', '_');
        }

        private static string Hex(byte[] value)
        {
            StringBuilder text = new StringBuilder(value.Length * 2);
            foreach (byte b in value) text.Append(b.ToString("x2"));
            return text.ToString();
        }
    }
}
