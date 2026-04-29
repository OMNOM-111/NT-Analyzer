using System;
using System.IO;

namespace NTAnalyzerBridge.Util
{
    /// <summary>
    /// write-temp-then-rename helper. All writes inside the queue must
    /// go through this to keep the partial file invisible to readers.
    ///
    /// Implementation guarantees:
    ///   - When the destination does not exist, uses File.Move (atomic on NTFS).
    ///   - When the destination already exists, uses File.Replace which
    ///     atomically swaps the file in place — readers always see either
    ///     the old or the new full contents, never a missing file.
    /// </summary>
    internal static class AtomicFile
    {
        public static void WriteAllText(string finalPath, string content)
        {
            string dir = Path.GetDirectoryName(finalPath);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);

            string tmp = finalPath + ".tmp";
            // overwrite stale tmp from a previous crashed write
            if (File.Exists(tmp))
                File.Delete(tmp);

            File.WriteAllText(tmp, content);

            if (File.Exists(finalPath))
            {
                // Atomic swap, no missing-file window for readers.
                // backupFileName=null => no backup kept.
                File.Replace(tmp, finalPath, destinationBackupFileName: null,
                             ignoreMetadataErrors: true);
            }
            else
            {
                File.Move(tmp, finalPath);
            }
        }
    }
}
