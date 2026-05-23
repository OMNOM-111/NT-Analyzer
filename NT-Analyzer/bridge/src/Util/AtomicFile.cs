using System;
using System.IO;
using System.Threading;

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
        public static void WriteAllText(string finalPath, string content, bool createDirectory = true)
        {
            string dir = Path.GetDirectoryName(finalPath);
            if (!string.IsNullOrEmpty(dir))
            {
                if (createDirectory)
                    Directory.CreateDirectory(dir);
                else if (!Directory.Exists(dir))
                    throw new DirectoryNotFoundException(dir);
            }

            string tmp = finalPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(tmp, content);

                if (File.Exists(finalPath))
                {
                    ReplaceWithRetry(tmp, finalPath);
                }
                else
                {
                    MoveWithRetry(tmp, finalPath);
                }
            }
            finally
            {
                TryDelete(tmp);
            }
        }

        private static void ReplaceWithRetry(string tmp, string finalPath)
        {
            // Atomic swap, no missing-file window for readers. Windows can
            // briefly reject the replace while Python/backend readers hold the
            // old file handle, so retry instead of surfacing false bridge errors.
            RetryFileOp(delegate
            {
                File.Replace(tmp, finalPath, destinationBackupFileName: null,
                             ignoreMetadataErrors: true);
            });
        }

        private static void MoveWithRetry(string tmp, string finalPath)
        {
            RetryFileOp(delegate { File.Move(tmp, finalPath); });
        }

        private static void RetryFileOp(Action op)
        {
            Exception last = null;
            for (int i = 0; i < 12; i++)
            {
                try
                {
                    op();
                    return;
                }
                catch (IOException ex)
                {
                    last = ex;
                }
                catch (UnauthorizedAccessException ex)
                {
                    last = ex;
                }
                Thread.Sleep(40 * (i + 1));
            }
            if (last != null)
                throw last;
        }

        private static void TryDelete(string path)
        {
            try
            {
                if (File.Exists(path))
                    File.Delete(path);
            }
            catch { }
        }
    }
}
