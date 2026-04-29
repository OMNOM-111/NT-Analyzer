using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace NTAnalyzerBridge.Util
{
    internal static class Sha256
    {
        public static string OfString(string s)
        {
            using (var algo = SHA256.Create())
            {
                byte[] hash = algo.ComputeHash(Encoding.UTF8.GetBytes(s ?? string.Empty));
                return "sha256:" + ToHex(hash);
            }
        }

        public static string OfFile(string path)
        {
            if (!File.Exists(path)) return null;
            using (var algo = SHA256.Create())
            using (var fs = File.OpenRead(path))
            {
                byte[] hash = algo.ComputeHash(fs);
                return "sha256:" + ToHex(hash);
            }
        }

        private static string ToHex(byte[] bytes)
        {
            var sb = new StringBuilder(bytes.Length * 2);
            for (int i = 0; i < bytes.Length; i++)
                sb.Append(bytes[i].ToString("x2"));
            return sb.ToString();
        }
    }
}
