using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

using Newtonsoft.Json.Linq;

namespace StratForge.Connector.Setup
{
    internal sealed class VerifiedRelease
    {
        public string Root { get; set; }
        public JObject Manifest { get; set; }
        public string ManifestSha256 { get; set; }
        public string Version => (string)Manifest["version"] ?? "";
        public string Channel => (string)Manifest["channel"] ?? "";
        public string TrustTier => (string)Manifest["trust_tier"] ?? "";
    }

    internal static class ReleaseManifestVerifier
    {
        public static VerifiedRelease Verify(string releaseRoot)
        {
            string root = Path.GetFullPath(releaseRoot ?? "");
            string manifestPath = Path.Combine(root, "manifest.json");
            string signaturePath = Path.Combine(root, "manifest.sig");
            if (!File.Exists(manifestPath) || !File.Exists(signaturePath))
                throw new InvalidDataException("Release manifest or signature is missing.");
            if (string.IsNullOrWhiteSpace(ReleaseTrust.PublicKeyX) ||
                string.IsNullOrWhiteSpace(ReleaseTrust.PublicKeyY) ||
                string.IsNullOrWhiteSpace(ReleaseTrust.KeyFingerprint))
                throw new InvalidOperationException("Installer release trust is not configured.");

            byte[] manifestBytes = File.ReadAllBytes(manifestPath);
            byte[] signature = Base64UrlDecode(File.ReadAllText(signaturePath).Trim());
            if (signature.Length != 64)
                throw new CryptographicException("Manifest signature must be a 64-byte P-256 value.");
            using (ECDsaCng verifier = CreateVerifier())
            {
                if (!verifier.VerifyData(manifestBytes, signature, HashAlgorithmName.SHA256))
                    throw new CryptographicException("Release manifest signature is invalid.");
            }

            JObject manifest = JObject.Parse(Encoding.UTF8.GetString(manifestBytes));
            ValidateManifestShape(manifest);
            string fingerprint = (string)manifest["signing"]?["key_fingerprint"] ?? "";
            if (!FixedEquals(fingerprint, ReleaseTrust.KeyFingerprint))
                throw new CryptographicException("Manifest signing key fingerprint is not trusted.");
            string tier = (string)manifest["trust_tier"] ?? "";
            if (!string.Equals(tier, ReleaseTrust.TrustTier, StringComparison.Ordinal))
                throw new CryptographicException("Manifest trust tier differs from the installer trust anchor.");

            string rootPrefix = root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (JObject row in (manifest["files"] as JArray ?? new JArray()).OfType<JObject>())
            {
                string relative = ((string)row["path"] ?? "").Replace('/', Path.DirectorySeparatorChar);
                if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative))
                    throw new InvalidDataException("Manifest contains an unsafe file path.");
                string full = Path.GetFullPath(Path.Combine(root, relative));
                if (!full.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase) || !seen.Add(full))
                    throw new InvalidDataException("Manifest contains a duplicate or escaping file path.");
                if (!File.Exists(full))
                    throw new FileNotFoundException("Release payload is missing: " + relative);
                long expectedSize = (long?)row["size"] ?? -1;
                if (new FileInfo(full).Length != expectedSize)
                    throw new InvalidDataException("Release payload size mismatch: " + relative);
                string expectedHash = ((string)row["sha256"] ?? "").ToUpperInvariant();
                string actualHash = Sha256(full);
                if (!FixedEquals(expectedHash, actualHash))
                    throw new CryptographicException("Release payload hash mismatch: " + relative);
            }
            return new VerifiedRelease
            {
                Root = root,
                Manifest = manifest,
                ManifestSha256 = Sha256(manifestPath),
            };
        }

        private static void ValidateManifestShape(JObject manifest)
        {
            HashSet<string> allowed = new HashSet<string>(StringComparer.Ordinal)
            {
                "schema_version", "product", "version", "channel", "trust_tier",
                "source_revision", "built_at_utc", "protocol_version",
                "config_schema_version", "migration_version", "compatibility",
                "rollback", "signing", "files",
            };
            foreach (JProperty property in manifest.Properties())
                if (!allowed.Contains(property.Name))
                    throw new InvalidDataException("Unknown manifest field: " + property.Name);
            if ((int?)manifest["schema_version"] != 1 ||
                !string.Equals((string)manifest["product"], "StratForge Connector", StringComparison.Ordinal) ||
                string.IsNullOrWhiteSpace((string)manifest["version"]) ||
                (manifest["files"] as JArray) == null)
                throw new InvalidDataException("Release manifest contract is incomplete.");
            JObject signing = manifest["signing"] as JObject;
            if (signing == null ||
                !string.Equals((string)signing["algorithm"], "ECDSA_P256_SHA256_RAW", StringComparison.Ordinal))
                throw new InvalidDataException("Unsupported manifest signature algorithm.");
        }

        private static ECDsaCng CreateVerifier()
        {
            byte[] x = Base64UrlDecode(ReleaseTrust.PublicKeyX);
            byte[] y = Base64UrlDecode(ReleaseTrust.PublicKeyY);
            if (x.Length != 32 || y.Length != 32)
                throw new CryptographicException("Trusted P-256 public key is invalid.");
            byte[] blob = new byte[8 + x.Length + y.Length];
            Buffer.BlockCopy(BitConverter.GetBytes(0x31534345), 0, blob, 0, 4); // BCRYPT_ECDSA_PUBLIC_P256_MAGIC
            Buffer.BlockCopy(BitConverter.GetBytes(32), 0, blob, 4, 4);
            Buffer.BlockCopy(x, 0, blob, 8, 32);
            Buffer.BlockCopy(y, 0, blob, 40, 32);
            CngKey key = CngKey.Import(blob, CngKeyBlobFormat.EccPublicBlob);
            return new ECDsaCng(key) { HashAlgorithm = CngAlgorithm.Sha256 };
        }

        internal static string Sha256(string path)
        {
            using (FileStream stream = File.OpenRead(path))
            using (SHA256 sha = SHA256.Create())
                return Hex(sha.ComputeHash(stream));
        }

        internal static string Hex(byte[] value)
        {
            StringBuilder text = new StringBuilder(value.Length * 2);
            foreach (byte item in value) text.Append(item.ToString("X2"));
            return text.ToString();
        }

        internal static byte[] Base64UrlDecode(string value)
        {
            string text = (value ?? "").Replace('-', '+').Replace('_', '/');
            text += new string('=', (4 - text.Length % 4) % 4);
            return Convert.FromBase64String(text);
        }

        private static bool FixedEquals(string left, string right)
        {
            byte[] a = Encoding.UTF8.GetBytes(left ?? "");
            byte[] b = Encoding.UTF8.GetBytes(right ?? "");
            if (a.Length != b.Length) return false;
            int diff = 0;
            for (int index = 0; index < a.Length; index++) diff |= a[index] ^ b[index];
            return diff == 0;
        }
    }
}
