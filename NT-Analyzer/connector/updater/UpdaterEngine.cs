using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using StratForge.Connector.Setup;

namespace StratForge.Connector.Updater
{
    internal sealed class UpdaterOptions
    {
        public string NinjaUserDir { get; set; } = "";
        public string StateRoot { get; set; } = "";
        public string PackagePath { get; set; } = "";
        public string OfferPath { get; set; } = "";
        public bool WaitForSafeRestart { get; set; }
        public bool ApproveMajor { get; set; }
    }

    internal sealed class UpdaterAlreadyRunningException : Exception { }

    internal static class UpdaterEngine
    {
        private const string DllName = "NTAnalyzerBridge.dll";
        private const string ConfigName = "NTAnalyzerBridge.config.json";
        private const long MaxArchiveBytes = 250L * 1024 * 1024;
        private const long MaxExtractedBytes = 500L * 1024 * 1024;
        private static readonly Regex SemVer = new Regex(
            @"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$",
            RegexOptions.CultureInvariant);

        public static JObject Run(UpdaterOptions options)
        {
            Paths paths = Validate(options);
            using (FileStream guard = AcquireUpdaterLock(paths.StateRoot))
            {
                JObject finalized = FinalizePendingCore(paths, options.WaitForSafeRestart);
                string state = (string)finalized["state"] ?? "";
                if (state == "waiting_for_health" || state == "waiting_for_safe_restart" ||
                    state == "rollback_halted" || state == "rolled_back")
                    return finalized;

                if (string.IsNullOrWhiteSpace(options.PackagePath) &&
                    !File.Exists(OfferPath(options, paths)))
                    return Result("run", "no_update_offer", paths, "");

                JObject staged = StageCore(paths, options);
                state = (string)staged["state"] ?? "";
                if (state == "up_to_date") return staged;
                if (IsNinjaTraderRunning())
                {
                    if (!options.WaitForSafeRestart)
                        return Result("run", "staged_waiting_for_safe_restart", paths,
                            (string)staged["target_version"] ?? "");
                    WaitForNinjaTraderClosed();
                }
                return ApplyStagedCore(paths);
            }
        }

        public static JObject Stage(UpdaterOptions options)
        {
            Paths paths = Validate(options);
            using (FileStream guard = AcquireUpdaterLock(paths.StateRoot))
                return StageCore(paths, options);
        }

        public static JObject ApplyStaged(UpdaterOptions options)
        {
            Paths paths = Validate(options);
            using (FileStream guard = AcquireUpdaterLock(paths.StateRoot))
            {
                if (IsNinjaTraderRunning())
                {
                    if (!options.WaitForSafeRestart)
                        return Result("apply-staged", "waiting_for_safe_restart", paths, "");
                    WaitForNinjaTraderClosed();
                }
                return ApplyStagedCore(paths);
            }
        }

        public static JObject FinalizePending(UpdaterOptions options)
        {
            Paths paths = Validate(options);
            using (FileStream guard = AcquireUpdaterLock(paths.StateRoot))
                return FinalizePendingCore(paths, options.WaitForSafeRestart);
        }

        public static JObject Diagnostics(UpdaterOptions options)
        {
            Paths paths = Validate(options);
            JObject install = ReadObject(paths.InstallRecord);
            JObject pending = ReadObject(paths.PendingUpdate);
            JObject stage = ReadObject(paths.StageRecord);
            return new JObject
            {
                ["ok"] = true,
                ["action"] = "diagnostics",
                ["state"] = pending != null ? "pending_health" : stage != null ? "staged" : "idle",
                ["ninjatrader_running"] = IsNinjaTraderRunning(),
                ["installed_version"] = (string)install?["installed_version"] ?? "",
                ["staged_version"] = (string)stage?["target_version"] ?? "",
                ["pending_version"] = (string)pending?["target_version"] ?? "",
                ["pending_deadline_utc"] = (string)pending?["health_deadline_utc"] ?? "",
                ["journal_present"] = File.Exists(paths.Journal),
                ["device_key_present"] = File.Exists(Path.Combine(paths.StateRoot, "device-key.dpapi")),
            };
        }

        private static JObject StageCore(Paths paths, UpdaterOptions options)
        {
            JObject install = RequireInstalled(paths);
            string currentVersion = RequireSemVer(
                (string)install["installed_version"], "installed version");
            JObject offer = null;
            string archivePath;
            if (!string.IsNullOrWhiteSpace(options.PackagePath))
            {
                archivePath = Path.GetFullPath(options.PackagePath);
                if (!File.Exists(archivePath))
                    throw new FileNotFoundException("Update package does not exist.");
                string configuredOffer = OfferPath(options, paths);
                if (File.Exists(configuredOffer)) offer = ReadAndValidateOffer(configuredOffer);
            }
            else
            {
                offer = ReadAndValidateOffer(OfferPath(options, paths));
                archivePath = DownloadOffer(paths, offer);
            }
            if (new FileInfo(archivePath).Length <= 0 ||
                new FileInfo(archivePath).Length > MaxArchiveBytes)
                throw new InvalidDataException("Update package size is outside the allowed range.");
            if (offer != null)
            {
                string expectedArchive = (string)offer["archive_sha256"] ?? "";
                if (!FixedEquals(ReleaseManifestVerifier.Sha256(archivePath), expectedArchive))
                    throw new CryptographicException("Downloaded update archive hash mismatch.");
            }

            string extraction = ExtractVerifiedArchive(paths, archivePath);
            VerifiedRelease release;
            try
            {
                release = ReleaseManifestVerifier.Verify(extraction);
                ValidateReleaseForUpdate(release, offer, currentVersion, options.ApproveMajor);
                if (string.Equals(
                        (string)install["update_policy"], "manual", StringComparison.Ordinal)
                    && !options.ApproveMajor)
                    throw new InvalidOperationException(
                        "Installed Connector policy requires explicit update approval.");
                JObject blocked = ReadObject(paths.BlockedUpdate);
                if (blocked != null && string.Equals(
                        (string)blocked["version"], release.Version, StringComparison.Ordinal)
                    && !options.ApproveMajor)
                    throw new InvalidOperationException(
                        "This release was rolled back and automatic retry is blocked.");
            }
            catch
            {
                SafeDeleteGeneratedDirectory(paths, extraction);
                throw;
            }
            int comparison = CompareVersions(release.Version, currentVersion);
            if (comparison <= 0)
            {
                SafeDeleteGeneratedDirectory(paths, extraction);
                Journal(paths, "stage", release.Version, "up_to_date", "");
                return Result("stage", "up_to_date", paths, release.Version);
            }

            string stagedRoot = Path.Combine(paths.StagedRoot, SafeVersion(release.Version));
            Directory.CreateDirectory(paths.StagedRoot);
            if (Directory.Exists(stagedRoot)) SafeDeleteGeneratedDirectory(paths, stagedRoot);
            Directory.Move(extraction, stagedRoot);
            int healthTimeout = offer == null ? 900 : (int?)offer["health_timeout_sec"] ?? 900;
            JObject record = new JObject
            {
                ["schema_version"] = 1,
                ["current_version"] = currentVersion,
                ["target_version"] = release.Version,
                ["channel"] = release.Channel,
                ["manifest_sha256"] = release.ManifestSha256,
                ["archive_sha256"] = ReleaseManifestVerifier.Sha256(archivePath),
                ["staged_root"] = stagedRoot,
                ["health_timeout_sec"] = healthTimeout,
                ["staged_at_utc"] = UtcNow(),
            };
            AtomicWrite(paths.StageRecord, record);
            Journal(paths, "stage", release.Version, "success", "verified_and_staged");
            return Result("stage", "staged", paths, release.Version);
        }

        private static JObject ApplyStagedCore(Paths paths)
        {
            if (IsNinjaTraderRunning())
                throw new InvalidOperationException(
                    "NinjaTrader is running; update remains staged for the next safe restart.");
            if (File.Exists(paths.PendingUpdate))
                throw new InvalidOperationException("A previous update is still awaiting health.");
            JObject stage = ReadObject(paths.StageRecord);
            if (stage == null) throw new InvalidOperationException("No verified staged update exists.");
            JObject install = RequireInstalled(paths);
            string current = RequireSemVer((string)install["installed_version"], "installed version");
            string expectedCurrent = RequireSemVer((string)stage["current_version"], "staged current version");
            string target = RequireSemVer((string)stage["target_version"], "staged target version");
            if (!string.Equals(current, expectedCurrent, StringComparison.Ordinal))
                throw new InvalidOperationException("Staged update is stale for the installed version.");
            string stagedRoot = RequireGeneratedDirectory(paths, (string)stage["staged_root"]);
            VerifiedRelease release = ReleaseManifestVerifier.Verify(stagedRoot);
            if (!string.Equals(release.Version, target, StringComparison.Ordinal) ||
                !FixedEquals(release.ManifestSha256, (string)stage["manifest_sha256"] ?? ""))
                throw new CryptographicException("Staged release metadata changed after verification.");

            string lastKnownGood = CreateLastKnownGood(paths, current, install);
            string deviceKey = Path.Combine(paths.StateRoot, "device-key.dpapi");
            string deviceKeyHash = File.Exists(deviceKey) ? ReleaseManifestVerifier.Sha256(deviceKey) : "";
            try
            {
                RunSetup(paths, release, stage);
                VerifyInstalledPayload(paths, release);
                ValidatePreservedConfig(
                    Path.Combine(lastKnownGood, ConfigName), paths.ConfigTarget);
                if (File.Exists(deviceKey) != (deviceKeyHash != "") ||
                    (deviceKeyHash != "" && !FixedEquals(
                        deviceKeyHash, ReleaseManifestVerifier.Sha256(deviceKey))))
                    throw new CryptographicException("Connector device key changed during update.");
                string nonce = RandomNonce();
                int timeout = Math.Max(300, Math.Min(3600,
                    (int?)stage["health_timeout_sec"] ?? 900));
                double deadline = EpochNow() + timeout;
                JObject pending = new JObject
                {
                    ["schema_version"] = 1,
                    ["previous_version"] = current,
                    ["target_version"] = target,
                    ["channel"] = release.Channel,
                    ["health_nonce"] = nonce,
                    ["health_deadline_epoch"] = deadline,
                    ["health_deadline_utc"] = UtcNow(deadline),
                    ["last_known_good_root"] = lastKnownGood,
                    ["rollback_attempted"] = false,
                    ["applied_at_utc"] = UtcNow(),
                    ["manifest_sha256"] = release.ManifestSha256,
                };
                AtomicWrite(paths.PendingUpdate, pending);
                if (File.Exists(paths.HealthReceipt)) File.Delete(paths.HealthReceipt);
                if (File.Exists(paths.StageRecord)) File.Delete(paths.StageRecord);
                Journal(paths, "apply", target, "pending_health", "safe_restart_install");
                return Result("apply-staged", "pending_health", paths, target);
            }
            catch (Exception exc)
            {
                RestoreLastKnownGood(paths, lastKnownGood);
                Journal(paths, "apply", target, "rolled_back", exc.GetType().Name);
                throw;
            }
        }

        private static JObject FinalizePendingCore(Paths paths, bool wait)
        {
            JObject pending = ReadObject(paths.PendingUpdate);
            if (pending == null) return Result("finalize", "nothing_pending", paths, "");
            string target = RequireSemVer((string)pending["target_version"], "pending target version");
            while (true)
            {
                JObject health = ReadObject(paths.HealthReceipt);
                if (HealthMatches(pending, health))
                {
                    if ((bool?)health["accepted"] == true)
                    {
                        JObject completed = (JObject)pending.DeepClone();
                        completed["result"] = "health_accepted";
                        completed["completed_at_utc"] = UtcNow();
                        completed.Remove("health_nonce");
                        AtomicWrite(paths.LastResult, completed);
                        File.Delete(paths.PendingUpdate);
                        File.Delete(paths.HealthReceipt);
                        Journal(paths, "health", target, "accepted", "hello_and_heartbeat");
                        return Result("finalize", "health_accepted", paths, target);
                    }
                    return RollbackPending(paths, pending,
                        (string)health["reason"] ?? "server_health_rejected", wait);
                }
                if (EpochNow() >= (double?)pending["health_deadline_epoch"])
                    return RollbackPending(paths, pending, "health_timeout", wait);
                if (!wait) return Result("finalize", "waiting_for_health", paths, target);
                Thread.Sleep(2000);
                pending = ReadObject(paths.PendingUpdate);
                if (pending == null) return Result("finalize", "nothing_pending", paths, "");
            }
        }

        private static JObject RollbackPending(
            Paths paths, JObject pending, string reason, bool wait)
        {
            string target = (string)pending["target_version"] ?? "";
            if ((bool?)pending["rollback_attempted"] == true)
            {
                Journal(paths, "rollback", target, "halted", "one_shot_guard");
                return Result("rollback", "rollback_halted", paths, target);
            }
            pending["rollback_attempted"] = true;
            pending["rollback_reason"] = SafeReason(reason);
            pending["rollback_started_at_utc"] = UtcNow();
            AtomicWrite(paths.PendingUpdate, pending);
            if (IsNinjaTraderRunning())
            {
                if (!wait)
                    return Result("rollback", "waiting_for_safe_restart", paths, target);
                WaitForNinjaTraderClosed();
            }
            string root = RequireGeneratedDirectory(
                paths, (string)pending["last_known_good_root"]);
            RestoreLastKnownGood(paths, root);
            JObject result = (JObject)pending.DeepClone();
            result["result"] = "rolled_back";
            result["completed_at_utc"] = UtcNow();
            result.Remove("health_nonce");
            AtomicWrite(paths.LastResult, result);
            AtomicWrite(paths.BlockedUpdate, new JObject
            {
                ["schema_version"] = 1,
                ["version"] = target,
                ["reason"] = SafeReason(reason),
                ["blocked_at_utc"] = UtcNow(),
                ["automatic_retry_allowed"] = false,
            });
            File.Delete(paths.PendingUpdate);
            if (File.Exists(paths.HealthReceipt)) File.Delete(paths.HealthReceipt);
            Journal(paths, "rollback", target, "success", SafeReason(reason));
            return Result("rollback", "rolled_back", paths, target);
        }

        private static string DownloadOffer(Paths paths, JObject offer)
        {
            string version = RequireSemVer((string)offer["version"], "offer version");
            Uri uri;
            if (!Uri.TryCreate((string)offer["archive_url"], UriKind.Absolute, out uri) ||
                uri.Scheme != Uri.UriSchemeHttps || !string.IsNullOrEmpty(uri.UserInfo) ||
                !string.IsNullOrEmpty(uri.Fragment))
                throw new InvalidDataException("Update offer archive_url must be HTTPS.");
            Directory.CreateDirectory(paths.DownloadRoot);
            string target = Path.Combine(paths.DownloadRoot, SafeVersion(version) + ".zip");
            string temporary = target + ".partial-" + Guid.NewGuid().ToString("N");
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            try
            {
                using (HttpClient client = new HttpClient(new HttpClientHandler
                {
                    UseCookies = false,
                    AutomaticDecompression = DecompressionMethods.None,
                }))
                using (HttpResponseMessage response = client.GetAsync(
                    uri, HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult())
                {
                    response.EnsureSuccessStatusCode();
                    if (response.Content.Headers.ContentLength.HasValue &&
                        response.Content.Headers.ContentLength.Value > MaxArchiveBytes)
                        throw new InvalidDataException("Update download is too large.");
                    using (Stream input = response.Content.ReadAsStreamAsync().GetAwaiter().GetResult())
                    using (FileStream output = new FileStream(
                        temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    {
                        byte[] buffer = new byte[1024 * 1024];
                        long total = 0;
                        int read;
                        while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                        {
                            total += read;
                            if (total > MaxArchiveBytes)
                                throw new InvalidDataException("Update download exceeded the size limit.");
                            output.Write(buffer, 0, read);
                        }
                        output.Flush(true);
                    }
                }
                string expected = (string)offer["archive_sha256"] ?? "";
                if (!FixedEquals(ReleaseManifestVerifier.Sha256(temporary), expected))
                    throw new CryptographicException("Downloaded update archive hash mismatch.");
                AtomicMove(temporary, target);
                return target;
            }
            catch
            {
                if (File.Exists(temporary)) File.Delete(temporary);
                throw;
            }
        }

        private static string ExtractVerifiedArchive(Paths paths, string archivePath)
        {
            Directory.CreateDirectory(paths.StagedRoot);
            string root = Path.Combine(paths.StagedRoot, ".extract-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            string prefix = root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            long total = 0;
            try
            {
                using (ZipArchive archive = ZipFile.OpenRead(archivePath))
                {
                    if (archive.Entries.Count == 0 || archive.Entries.Count > 100)
                        throw new InvalidDataException("Update archive file count is invalid.");
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        string relative = (entry.FullName ?? "").Replace('/', Path.DirectorySeparatorChar);
                        if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative))
                            throw new InvalidDataException("Update archive contains an unsafe path.");
                        string destination = Path.GetFullPath(Path.Combine(root, relative));
                        if (!destination.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ||
                            !seen.Add(destination))
                            throw new InvalidDataException("Update archive path escapes or is duplicated.");
                        int unixType = (entry.ExternalAttributes >> 16) & 0xF000;
                        if (unixType == 0xA000)
                            throw new InvalidDataException("Update archive symlinks are forbidden.");
                        if (string.IsNullOrEmpty(entry.Name))
                        {
                            Directory.CreateDirectory(destination);
                            continue;
                        }
                        total += entry.Length;
                        if (entry.Length < 0 || total > MaxExtractedBytes)
                            throw new InvalidDataException("Update archive expands beyond the size limit.");
                        Directory.CreateDirectory(Path.GetDirectoryName(destination));
                        using (Stream input = entry.Open())
                        using (FileStream output = new FileStream(
                            destination, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                            input.CopyTo(output);
                    }
                }
                ReleaseManifestVerifier.Verify(root);
                return root;
            }
            catch
            {
                SafeDeleteGeneratedDirectory(paths, root);
                throw;
            }
        }

        private static void ValidateReleaseForUpdate(
            VerifiedRelease release, JObject offer, string currentVersion, bool approveMajor)
        {
            RequireSemVer(release.Version, "release version");
            if (release.Channel != "stable" && release.Channel != "canary")
                throw new InvalidDataException("Release channel is unsupported.");
            string protocol = (string)release.Manifest["protocol_version"] ?? "";
            if (protocol != "1.0")
                throw new InvalidDataException("Release protocol is incompatible.");
            int currentMajor = VersionParts(currentVersion)[0];
            int targetMajor = VersionParts(release.Version)[0];
            if (targetMajor != currentMajor && !approveMajor &&
                (offer == null || (bool?)offer["major_approved"] != true))
                throw new InvalidOperationException("Major update requires explicit compatibility approval.");
            if (offer == null) return;
            if (!string.Equals((string)offer["version"], release.Version, StringComparison.Ordinal) ||
                !string.Equals((string)offer["channel"], release.Channel, StringComparison.Ordinal) ||
                !FixedEquals((string)offer["manifest_sha256"] ?? "", release.ManifestSha256) ||
                !string.Equals((string)offer["protocol_version"], protocol, StringComparison.Ordinal))
                throw new CryptographicException("Signed release does not match the server update offer.");
            string policy = (string)offer["apply_policy"] ?? "";
            if (policy == "manual" && !approveMajor && (bool?)offer["major_approved"] != true)
                throw new InvalidOperationException("Server policy requires manual update approval.");
        }

        private static JObject ReadAndValidateOffer(string path)
        {
            JObject offer = ReadObject(path);
            if (offer == null) throw new InvalidDataException("Update offer is missing or invalid.");
            HashSet<string> allowed = new HashSet<string>(StringComparer.Ordinal)
            {
                "schema_version", "version", "channel", "archive_url",
                "archive_sha256", "manifest_sha256", "protocol_version",
                "apply_policy", "major_approved", "health_timeout_sec",
                "published_at_utc",
            };
            foreach (JProperty property in offer.Properties())
                if (!allowed.Contains(property.Name))
                    throw new InvalidDataException("Update offer contains an unknown field.");
            if ((int?)offer["schema_version"] != 1)
                throw new InvalidDataException("Update offer schema is unsupported.");
            RequireSemVer((string)offer["version"], "offer version");
            string channel = (string)offer["channel"] ?? "";
            if (channel != "stable" && channel != "canary")
                throw new InvalidDataException("Update offer channel is invalid.");
            foreach (string field in new[] { "archive_sha256", "manifest_sha256" })
                if (!Regex.IsMatch((string)offer[field] ?? "", "^[0-9A-Fa-f]{64}$"))
                    throw new InvalidDataException("Update offer contains an invalid SHA-256.");
            int timeout = (int?)offer["health_timeout_sec"] ?? 0;
            if (timeout < 300 || timeout > 3600)
                throw new InvalidDataException("Update health timeout is outside 300..3600 seconds.");
            return offer;
        }

        private static void RunSetup(Paths paths, VerifiedRelease release, JObject stage)
        {
            string setup = Path.Combine(release.Root, "StratForge.Connector.Setup.exe");
            if (!File.Exists(setup)) throw new FileNotFoundException("Verified release has no Setup.");
            JObject install = RequireInstalled(paths);
            string updatePolicy = (string)install["update_policy"] ?? "safe_restart";
            ProcessStartInfo start = new ProcessStartInfo
            {
                FileName = setup,
                Arguments = JoinArguments(new[]
                {
                    "--repair", "--ninja-user-dir", paths.NinjaUserDir,
                    "--state-root", paths.StateRoot,
                    "--channel", (string)stage["channel"] ?? release.Channel,
                    "--update-policy", updatePolicy,
                    "--skip-uri-registration", "--non-interactive",
                }),
                WorkingDirectory = release.Root,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using (Process process = Process.Start(start))
            {
                string stdout = process.StandardOutput.ReadToEnd();
                string stderr = process.StandardError.ReadToEnd();
                if (!process.WaitForExit(120000))
                {
                    try { process.Kill(); } catch { }
                    throw new TimeoutException("Setup did not finish within 120 seconds.");
                }
                if (process.ExitCode != 0)
                    throw new InvalidOperationException(
                        "Verified Setup rejected update: " + SafeReason(stdout + " " + stderr));
            }
        }

        private static string CreateLastKnownGood(Paths paths, string version, JObject install)
        {
            string root = Path.Combine(paths.BackupRoot,
                DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffZ", CultureInfo.InvariantCulture) +
                "-update-from-" + SafeVersion(version));
            Directory.CreateDirectory(root);
            CaptureRequired(paths.DllTarget, Path.Combine(root, DllName));
            CaptureRequired(paths.ConfigTarget, Path.Combine(root, ConfigName));
            CaptureRequired(paths.InstallRecord, Path.Combine(root, "install-record.json"));
            JObject metadata = new JObject
            {
                ["schema_version"] = 1,
                ["version"] = version,
                ["created_at_utc"] = UtcNow(),
                ["dll_sha256"] = ReleaseManifestVerifier.Sha256(Path.Combine(root, DllName)),
                ["config_sha256"] = ReleaseManifestVerifier.Sha256(Path.Combine(root, ConfigName)),
                ["install_record_sha256"] = ReleaseManifestVerifier.Sha256(
                    Path.Combine(root, "install-record.json")),
                ["release_cache_dir"] = (string)install["release_cache_dir"] ?? "",
            };
            AtomicWrite(Path.Combine(root, "lkg.json"), metadata);
            return root;
        }

        private static void RestoreLastKnownGood(Paths paths, string root)
        {
            string safe = RequireGeneratedDirectory(paths, root);
            JObject metadata = ReadObject(Path.Combine(safe, "lkg.json"));
            if (metadata == null) throw new InvalidDataException("Last-known-good metadata is missing.");
            RestoreVerified(Path.Combine(safe, DllName), paths.DllTarget,
                (string)metadata["dll_sha256"] ?? "");
            RestoreVerified(Path.Combine(safe, ConfigName), paths.ConfigTarget,
                (string)metadata["config_sha256"] ?? "");
            RestoreVerified(Path.Combine(safe, "install-record.json"), paths.InstallRecord,
                (string)metadata["install_record_sha256"] ?? "");
        }

        private static void VerifyInstalledPayload(Paths paths, VerifiedRelease release)
        {
            JObject row = (release.Manifest["files"] as JArray ?? new JArray())
                .OfType<JObject>()
                .FirstOrDefault(item => string.Equals(
                    (string)item["path"], "payload/" + DllName, StringComparison.Ordinal));
            if (row == null || !File.Exists(paths.DllTarget) || !FixedEquals(
                (string)row["sha256"] ?? "", ReleaseManifestVerifier.Sha256(paths.DllTarget)))
                throw new CryptographicException("Installed Connector DLL differs from signed release.");
        }

        private static void ValidatePreservedConfig(string beforePath, string afterPath)
        {
            JObject before = ReadObject(beforePath);
            JObject after = ReadObject(afterPath);
            if (before == null || after == null)
                throw new InvalidDataException("Connector config was lost during update.");
            foreach (string field in new[] { "mode", "ninjatrader_user_dir", "runtime_data_dir" })
                if (!JToken.DeepEquals(before[field], after[field]))
                    throw new InvalidDataException("Update changed protected config field: " + field);
            JObject left = before["production_connector"] as JObject;
            JObject right = after["production_connector"] as JObject;
            if (left == null || right == null)
                throw new InvalidDataException("Production Connector config block was lost.");
            foreach (string field in new[]
            {
                "server_origin", "protocol_version", "enrollment_credential_ref",
                "state_dir", "heartbeat_interval_ms", "command_poll_seconds",
                "update_policy",
            })
                if (!JToken.DeepEquals(left[field], right[field]))
                    throw new InvalidDataException("Update changed protected connector field: " + field);
        }

        private static bool HealthMatches(JObject pending, JObject health)
        {
            return health != null &&
                string.Equals((string)pending["target_version"], (string)health["version"],
                    StringComparison.Ordinal) &&
                string.Equals((string)pending["health_nonce"], (string)health["health_nonce"],
                    StringComparison.Ordinal) &&
                !string.IsNullOrWhiteSpace((string)health["heartbeat_at_utc"]);
        }

        private static JObject RequireInstalled(Paths paths)
        {
            JObject install = ReadObject(paths.InstallRecord);
            if (install == null || !string.Equals(
                (string)install["status"], "installed", StringComparison.Ordinal))
                throw new InvalidOperationException("Connector is not installed by verified Setup.");
            return install;
        }

        private static Paths Validate(UpdaterOptions options)
        {
            string ninja = Path.GetFullPath(Environment.ExpandEnvironmentVariables(
                options.NinjaUserDir ?? ""));
            string state = Path.GetFullPath(Environment.ExpandEnvironmentVariables(
                options.StateRoot ?? ""));
            if (!Directory.Exists(ninja))
                throw new DirectoryNotFoundException("NinjaTrader user directory does not exist.");
            Directory.CreateDirectory(state);
            return new Paths(ninja, state);
        }

        private static FileStream AcquireUpdaterLock(string stateRoot)
        {
            try
            {
                return new FileStream(Path.Combine(stateRoot, "updater.lock"),
                    FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            }
            catch (IOException)
            {
                throw new UpdaterAlreadyRunningException();
            }
        }

        private static bool IsNinjaTraderRunning()
        {
            foreach (string name in new[] { "NinjaTrader", "NinjaTrader.Core" })
            {
                Process[] processes = Process.GetProcessesByName(name);
                try { if (processes.Length > 0) return true; }
                finally { foreach (Process process in processes) process.Dispose(); }
            }
            return false;
        }

        private static void WaitForNinjaTraderClosed()
        {
            while (IsNinjaTraderRunning()) Thread.Sleep(2000);
        }

        private static string OfferPath(UpdaterOptions options, Paths paths)
        {
            return string.IsNullOrWhiteSpace(options.OfferPath)
                ? paths.UpdateOffer : Path.GetFullPath(options.OfferPath);
        }

        private static JObject Result(
            string action, string state, Paths paths, string targetVersion)
        {
            return new JObject
            {
                ["ok"] = true,
                ["action"] = action,
                ["state"] = state,
                ["target_version"] = targetVersion ?? "",
                ["ninjatrader_running"] = IsNinjaTraderRunning(),
                ["config_preserved"] = File.Exists(paths.ConfigTarget),
                ["device_key_preserved"] = File.Exists(
                    Path.Combine(paths.StateRoot, "device-key.dpapi")),
            };
        }

        private static JObject ReadObject(string path)
        {
            if (!File.Exists(path)) return null;
            try { return JObject.Parse(File.ReadAllText(path, Encoding.UTF8)); }
            catch (JsonException) { throw new InvalidDataException("Updater state JSON is corrupt."); }
        }

        private static void AtomicWrite(string target, JObject value)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            string temporary = target + ".tmp-" + Guid.NewGuid().ToString("N");
            File.WriteAllText(temporary, value.ToString(Formatting.Indented), new UTF8Encoding(false));
            AtomicMove(temporary, target);
        }

        private static void AtomicMove(string source, string target)
        {
            if (File.Exists(target)) File.Replace(source, target, null);
            else File.Move(source, target);
        }

        private static void AtomicCopy(string source, string target)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            string temporary = target + ".tmp-" + Guid.NewGuid().ToString("N");
            File.Copy(source, temporary, false);
            AtomicMove(temporary, target);
        }

        private static void CaptureRequired(string source, string target)
        {
            if (!File.Exists(source)) throw new FileNotFoundException("Required rollback file is missing.");
            File.Copy(source, target, false);
        }

        private static void RestoreVerified(string source, string target, string expectedHash)
        {
            if (!File.Exists(source) || !FixedEquals(
                ReleaseManifestVerifier.Sha256(source), expectedHash))
                throw new CryptographicException("Last-known-good file failed hash verification.");
            AtomicCopy(source, target);
            if (!FixedEquals(ReleaseManifestVerifier.Sha256(target), expectedHash))
                throw new CryptographicException("Restored last-known-good file hash mismatch.");
        }

        private static string RequireGeneratedDirectory(Paths paths, string value)
        {
            string full = Path.GetFullPath(value ?? "");
            string prefix = paths.StateRoot.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) || !Directory.Exists(full))
                throw new InvalidDataException("Updater state points outside its state root.");
            return full;
        }

        private static void SafeDeleteGeneratedDirectory(Paths paths, string value)
        {
            string full = Path.GetFullPath(value ?? "");
            string prefix = paths.StagedRoot.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Refusing to delete outside the updater staging root.");
            if (Directory.Exists(full)) Directory.Delete(full, true);
        }

        private static string RequireSemVer(string value, string field)
        {
            string text = (value ?? "").Trim();
            Match match = SemVer.Match(text);
            if (!match.Success || match.Groups[4].Value.Split('.').Any(
                    item => item.Length > 1 && item[0] == '0' && item.All(char.IsDigit)))
                throw new InvalidDataException(field + " is not semantic versioning.");
            return text;
        }

        private static int[] VersionParts(string value)
        {
            Match match = SemVer.Match(RequireSemVer(value, "version"));
            return new[] { int.Parse(match.Groups[1].Value), int.Parse(match.Groups[2].Value),
                int.Parse(match.Groups[3].Value) };
        }

        private static int CompareVersions(string left, string right)
        {
            string normalizedLeft = RequireSemVer(left, "version");
            string normalizedRight = RequireSemVer(right, "version");
            Match leftMatch = SemVer.Match(normalizedLeft);
            Match rightMatch = SemVer.Match(normalizedRight);
            int[] a = VersionParts(normalizedLeft);
            int[] b = VersionParts(normalizedRight);
            for (int index = 0; index < 3; index++)
                if (a[index] != b[index]) return a[index].CompareTo(b[index]);
            bool aPre = leftMatch.Groups[4].Success;
            bool bPre = rightMatch.Groups[4].Success;
            if (aPre != bPre) return aPre ? -1 : 1;
            if (!aPre) return 0;
            string[] leftParts = leftMatch.Groups[4].Value.Split('.');
            string[] rightParts = rightMatch.Groups[4].Value.Split('.');
            int common = Math.Min(leftParts.Length, rightParts.Length);
            for (int index = 0; index < common; index++)
            {
                string leftPart = leftParts[index];
                string rightPart = rightParts[index];
                if (leftPart == rightPart) continue;
                bool leftNumeric = leftPart.All(char.IsDigit);
                bool rightNumeric = rightPart.All(char.IsDigit);
                if (leftNumeric && rightNumeric)
                {
                    if (leftPart.Length != rightPart.Length)
                        return leftPart.Length.CompareTo(rightPart.Length);
                    return string.CompareOrdinal(leftPart, rightPart);
                }
                if (leftNumeric != rightNumeric) return leftNumeric ? -1 : 1;
                return string.CompareOrdinal(leftPart, rightPart);
            }
            return leftParts.Length.CompareTo(rightParts.Length);
        }

        private static string SafeVersion(string value)
        {
            string version = RequireSemVer(value, "version");
            return Regex.Replace(version, "[^0-9A-Za-z._-]", "_");
        }

        private static string RandomNonce()
        {
            byte[] value = new byte[32];
            using (RandomNumberGenerator random = RandomNumberGenerator.Create()) random.GetBytes(value);
            return Convert.ToBase64String(value).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        }

        private static bool FixedEquals(string left, string right)
        {
            byte[] a = Encoding.ASCII.GetBytes((left ?? "").ToUpperInvariant());
            byte[] b = Encoding.ASCII.GetBytes((right ?? "").ToUpperInvariant());
            if (a.Length != b.Length) return false;
            int diff = 0;
            for (int index = 0; index < a.Length; index++) diff |= a[index] ^ b[index];
            return diff == 0;
        }

        private static string JoinArguments(IEnumerable<string> values)
        {
            return string.Join(" ", values.Select(value => "\"" +
                (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"") + "\""));
        }

        private static void Journal(Paths paths, string action, string version, string result, string reason)
        {
            JObject row = new JObject
            {
                ["timestamp_utc"] = UtcNow(),
                ["action"] = action,
                ["version"] = version ?? "",
                ["result"] = result,
                ["reason"] = SafeReason(reason),
            };
            Directory.CreateDirectory(Path.GetDirectoryName(paths.Journal));
            File.AppendAllText(paths.Journal, row.ToString(Formatting.None) + Environment.NewLine,
                new UTF8Encoding(false));
        }

        private static string SafeReason(string value)
        {
            string clean = Regex.Replace(value ?? "", @"[\r\n\t]+", " ").Trim();
            return clean.Length <= 240 ? clean : clean.Substring(0, 240);
        }

        private static double EpochNow()
        {
            return (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0,
                DateTimeKind.Utc)).TotalSeconds;
        }

        private static string UtcNow(double? epoch = null)
        {
            DateTime value = epoch.HasValue
                ? new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(epoch.Value)
                : DateTime.UtcNow;
            return value.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture);
        }

        private sealed class Paths
        {
            public Paths(string ninjaUserDir, string stateRoot)
            {
                NinjaUserDir = ninjaUserDir;
                StateRoot = stateRoot;
                string custom = Path.Combine(ninjaUserDir, "bin", "Custom");
                DllTarget = Path.Combine(custom, DllName);
                ConfigTarget = Path.Combine(custom, ConfigName);
                InstallRecord = Path.Combine(stateRoot, "install-record.json");
                StageRecord = Path.Combine(stateRoot, "update-stage.json");
                PendingUpdate = Path.Combine(stateRoot, "pending-update.json");
                HealthReceipt = Path.Combine(stateRoot, "update-health.json");
                UpdateOffer = Path.Combine(stateRoot, "update-offer.json");
                LastResult = Path.Combine(stateRoot, "update-last-result.json");
                BlockedUpdate = Path.Combine(stateRoot, "blocked-update.json");
                Journal = Path.Combine(stateRoot, "update-journal.jsonl");
                StagedRoot = Path.Combine(stateRoot, "staged-updates");
                DownloadRoot = Path.Combine(stateRoot, "downloads");
                BackupRoot = Path.Combine(stateRoot, "backups");
            }

            public string NinjaUserDir { get; private set; }
            public string StateRoot { get; private set; }
            public string DllTarget { get; private set; }
            public string ConfigTarget { get; private set; }
            public string InstallRecord { get; private set; }
            public string StageRecord { get; private set; }
            public string PendingUpdate { get; private set; }
            public string HealthReceipt { get; private set; }
            public string UpdateOffer { get; private set; }
            public string LastResult { get; private set; }
            public string BlockedUpdate { get; private set; }
            public string Journal { get; private set; }
            public string StagedRoot { get; private set; }
            public string DownloadRoot { get; private set; }
            public string BackupRoot { get; private set; }
        }
    }
}
