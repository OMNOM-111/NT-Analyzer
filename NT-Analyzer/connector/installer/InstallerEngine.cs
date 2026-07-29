using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

using Microsoft.Win32;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace StratForge.Connector.Setup
{
    internal sealed class InstallOptions
    {
        public string NinjaUserDir { get; set; }
        public string ServerOrigin { get; set; } = "https://app.stratforges.com";
        public string EnrollmentCode { get; set; } = "";
        public string Channel { get; set; } = "stable";
        public string UpdatePolicy { get; set; } = "safe_restart";
        public string StateRoot { get; set; } = "";
        public bool MigrateLocal { get; set; }
        public bool SkipUriRegistration { get; set; }
    }

    internal static class InstallerEngine
    {
        private const string DllName = "NTAnalyzerBridge.dll";
        private const string ConfigName = "NTAnalyzerBridge.config.json";
        private static readonly byte[] BootstrapEntropy =
            Encoding.UTF8.GetBytes("StratForge.Connector.Bootstrap.v1");

        public static IList<string> DetectNinjaUserDirs()
        {
            List<string> candidates = new List<string>();
            AddCandidate(candidates, Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "NinjaTrader 8"));
            string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            AddCandidate(candidates, Path.Combine(profile, "Documents", "NinjaTrader 8"));
            foreach (string variable in new[] { "OneDrive", "OneDriveConsumer", "OneDriveCommercial" })
            {
                string root = Environment.GetEnvironmentVariable(variable) ?? "";
                if (!string.IsNullOrWhiteSpace(root))
                    AddCandidate(candidates, Path.Combine(root, "Documents", "NinjaTrader 8"));
            }
            return candidates;
        }

        public static JObject InstallOrRepair(
            VerifiedRelease release, InstallOptions options, bool repair)
        {
            ValidateOptions(release, options);
            EnsureNinjaTraderClosed();
            string ninjaDir = RequireNinjaDirectory(options.NinjaUserDir);
            string customDir = Path.Combine(ninjaDir, "bin", "Custom");
            Directory.CreateDirectory(customDir);
            string stateDir = ResolveStateDir(options, ninjaDir);
            Directory.CreateDirectory(stateDir);
            using (FileStream operationLock = AcquireLock(stateDir))
            {
                string recordPath = Path.Combine(stateDir, "install-record.json");
                JObject record = ReadObject(recordPath);
                bool firstInstall = record == null || (string)record["ninja_user_dir"] != ninjaDir;
                string dllTarget = Path.Combine(customDir, DllName);
                string configTarget = Path.Combine(customDir, ConfigName);
                if (firstInstall)
                    record = CreateOriginalRollbackRecord(
                        release, ninjaDir, customDir, stateDir, dllTarget, configTarget);
                else if (!repair && string.Equals((string)record["status"], "installed", StringComparison.Ordinal))
                    throw new InvalidOperationException(
                        "Connector is already installed. Use Repair or Uninstall.");
                JObject config = BuildProductionConfig(
                    release, options, ninjaDir, stateDir, configTarget, repair);
                string normalizedCode = NormalizeEnrollmentCode(options.EnrollmentCode);
                string bootstrapPath = Path.Combine(stateDir, "bootstrap.dpapi");
                bool bootstrapExisted = File.Exists(bootstrapPath);
                if (normalizedCode == "" &&
                    !File.Exists(Path.Combine(stateDir, "connector-state.dpapi")) &&
                    !bootstrapExisted)
                    throw new InvalidOperationException(
                        "A one-time enrollment code is required for the first installation.");
                JObject operationBackup = CreateOperationBackup(
                    stateDir, dllTarget, configTarget, recordPath, bootstrapPath,
                    repair ? "repair" : "install");
                try
                {
                    string payloadDll = Path.Combine(release.Root, "payload", DllName);
                    AtomicCopy(payloadDll, dllTarget);
                    AtomicWriteText(configTarget, config.ToString(Formatting.Indented));
                    if (normalizedCode != "") StoreBootstrap(stateDir, normalizedCode);
                    string cacheDir = CacheVerifiedRelease(release, stateDir);
                    if (!options.SkipUriRegistration)
                        RegisterPairingScheme(Path.Combine(cacheDir, "StratForge.Connector.Setup.exe"));
                    record["schema_version"] = 1;
                    record["status"] = "installed";
                    record["installed_version"] = release.Version;
                    record["manifest_sha256"] = release.ManifestSha256;
                    record["channel"] = options.Channel;
                    record["update_policy"] = options.UpdatePolicy;
                    record["last_action"] = repair ? "repair" : "install";
                    record["updated_at_utc"] = UtcNow();
                    record["release_cache_dir"] = cacheDir;
                    AtomicWriteText(recordPath, record.ToString(Formatting.Indented));
                    Journal(stateDir, repair ? "repair" : "install", release.Version, "success", "");
                    return Result(repair ? "repair" : "install", release, ninjaDir, stateDir, dllTarget, configTarget);
                }
                catch (Exception exc)
                {
                    RestoreOperationBackup(
                        operationBackup, dllTarget, configTarget, recordPath, bootstrapPath);
                    Journal(stateDir, repair ? "repair" : "install", release.Version,
                        "rolled_back", exc.GetType().Name);
                    throw;
                }
            }
        }

        public static JObject Uninstall(VerifiedRelease release, InstallOptions options)
        {
            EnsureNinjaTraderClosed();
            string ninjaDir = RequireNinjaDirectory(options.NinjaUserDir);
            string customDir = Path.Combine(ninjaDir, "bin", "Custom");
            string stateDir = ResolveStateDir(options, ninjaDir);
            Directory.CreateDirectory(stateDir);
            using (FileStream operationLock = AcquireLock(stateDir))
            {
                string recordPath = Path.Combine(stateDir, "install-record.json");
                JObject record = ReadObject(recordPath);
                if (record == null)
                    throw new InvalidOperationException("No Connector installation record was found.");
                string dllTarget = Path.Combine(customDir, DllName);
                string configTarget = Path.Combine(customDir, ConfigName);
                string bootstrapPath = Path.Combine(stateDir, "bootstrap.dpapi");
                JObject operationBackup = CreateOperationBackup(
                    stateDir, dllTarget, configTarget, recordPath, bootstrapPath, "uninstall");
                try
                {
                    RestoreOriginal(record, "dll", dllTarget);
                    RestoreOriginal(record, "config", configTarget);
                    record["status"] = "uninstalled";
                    record["last_action"] = "uninstall";
                    record["updated_at_utc"] = UtcNow();
                    AtomicWriteText(recordPath, record.ToString(Formatting.Indented));
                    if (!options.SkipUriRegistration) UnregisterPairingScheme();
                    Journal(stateDir, "uninstall", release.Version, "success", "state_preserved");
                    return Result("uninstall", release, ninjaDir, stateDir, dllTarget, configTarget);
                }
                catch (Exception exc)
                {
                    RestoreOperationBackup(
                        operationBackup, dllTarget, configTarget, recordPath, bootstrapPath);
                    Journal(stateDir, "uninstall", release.Version, "rolled_back", exc.GetType().Name);
                    throw;
                }
            }
        }

        public static JObject Diagnostics(VerifiedRelease release, InstallOptions options)
        {
            string ninjaDir = RequireNinjaDirectory(options.NinjaUserDir);
            string customDir = Path.Combine(ninjaDir, "bin", "Custom");
            string stateDir = ResolveStateDir(options, ninjaDir);
            string dll = Path.Combine(customDir, DllName);
            string config = Path.Combine(customDir, ConfigName);
            JObject configDoc = ReadObject(config);
            return new JObject
            {
                ["ok"] = File.Exists(dll) && configDoc != null,
                ["action"] = "diagnostics",
                ["release_version"] = release.Version,
                ["ninjatrader_running"] = IsNinjaTraderRunning(),
                ["ninja_user_dir"] = ninjaDir,
                ["dll_present"] = File.Exists(dll),
                ["dll_sha256"] = File.Exists(dll) ? ReleaseManifestVerifier.Sha256(dll) : "",
                ["config_present"] = configDoc != null,
                ["config_schema_version"] = (int?)configDoc?["schema_version"] ?? 0,
                ["config_mode"] = (string)configDoc?["mode"] ?? "",
                ["device_key_present"] = File.Exists(Path.Combine(stateDir, "device-key.dpapi")),
                ["bootstrap_present"] = File.Exists(Path.Combine(stateDir, "bootstrap.dpapi")),
                ["install_record_present"] = File.Exists(Path.Combine(stateDir, "install-record.json")),
            };
        }

        private static JObject BuildProductionConfig(
            VerifiedRelease release, InstallOptions options, string ninjaDir,
            string stateDir, string target, bool repair)
        {
            JObject existing = ReadObject(target);
            if (existing != null)
            {
                string mode = (string)existing["mode"] ?? "local_development";
                if (!string.Equals(mode, "production_connector", StringComparison.Ordinal) &&
                    !options.MigrateLocal)
                    throw new InvalidOperationException(
                        "Existing local_development config requires explicit --migrate-local.");
                if (string.Equals(mode, "production_connector", StringComparison.Ordinal))
                    ValidateExistingProductionConfig(existing);
            }
            JObject connector = existing?["production_connector"] as JObject ?? new JObject();
            connector.Remove("enrollment_code");
            connector["enabled"] = true;
            connector["server_origin"] = NormalizeOrigin(
                (string)connector["server_origin"] ?? options.ServerOrigin);
            connector["protocol_version"] = (string)release.Manifest["protocol_version"] ?? "1.0";
            connector["connector_version"] = release.Version;
            connector["enrollment_credential_ref"] = "dpapi:bootstrap-v1";
            connector["state_dir"] = stateDir;
            connector["heartbeat_interval_ms"] = (int?)connector["heartbeat_interval_ms"] ?? 15000;
            connector["command_poll_seconds"] = (int?)connector["command_poll_seconds"] ?? 15;
            connector["release_channel"] = options.Channel;
            connector["update_policy"] = options.UpdatePolicy;
            JObject config = new JObject
            {
                ["schema_version"] = (int?)release.Manifest["config_schema_version"] ?? 3,
                ["mode"] = "production_connector",
                ["ninjatrader_user_dir"] = ninjaDir,
                ["runtime_data_dir"] = Path.Combine(stateDir, "spool"),
                ["production_connector"] = connector,
            };
            if (existing?["extensions"] is JObject extensions)
                config["extensions"] = extensions.DeepClone();
            return config;
        }

        private static void ValidateExistingProductionConfig(JObject config)
        {
            HashSet<string> top = new HashSet<string>(StringComparer.Ordinal)
            {
                "schema_version", "mode", "ninjatrader_user_dir", "runtime_data_dir",
                "production_connector", "extensions",
            };
            foreach (JProperty property in config.Properties())
                if (!top.Contains(property.Name))
                    throw new InvalidDataException(
                        "Existing Production config has an unsupported field: " + property.Name);
            JObject connector = config["production_connector"] as JObject;
            if (connector == null)
                throw new InvalidDataException("Existing Production config has no connector block.");
            HashSet<string> fields = new HashSet<string>(StringComparer.Ordinal)
            {
                "enabled", "server_origin", "protocol_version", "connector_version",
                "enrollment_code", "enrollment_credential_ref", "state_dir",
                "heartbeat_interval_ms", "command_poll_seconds", "release_channel",
                "update_policy", "extensions",
            };
            foreach (JProperty property in connector.Properties())
                if (!fields.Contains(property.Name))
                    throw new InvalidDataException(
                        "Existing Production connector config has an unsupported field: " + property.Name);
        }

        private static JObject CreateOriginalRollbackRecord(
            VerifiedRelease release, string ninjaDir, string customDir, string stateDir,
            string dllTarget, string configTarget)
        {
            string backupDir = Path.Combine(stateDir, "backups", UtcStamp() + "-original");
            Directory.CreateDirectory(backupDir);
            JObject original = new JObject();
            CaptureOriginal(original, "dll", dllTarget, Path.Combine(backupDir, DllName));
            CaptureOriginal(original, "config", configTarget, Path.Combine(backupDir, ConfigName));
            return new JObject
            {
                ["schema_version"] = 1,
                ["product"] = "StratForge Connector",
                ["ninja_user_dir"] = ninjaDir,
                ["custom_dir"] = customDir,
                ["state_dir"] = stateDir,
                ["created_at_utc"] = UtcNow(),
                ["original"] = original,
                ["status"] = "installing",
                ["release_version"] = release.Version,
            };
        }

        private static void CaptureOriginal(
            JObject original, string name, string source, string backup)
        {
            bool existed = File.Exists(source);
            if (existed) RetryIo(delegate { File.Copy(source, backup, true); });
            original[name] = new JObject
            {
                ["existed"] = existed,
                ["backup_path"] = existed ? backup : "",
                ["sha256"] = existed ? ReleaseManifestVerifier.Sha256(source) : "",
            };
        }

        private static void RestoreOriginal(JObject record, string name, string target)
        {
            JObject row = record["original"]?[name] as JObject;
            if (row == null) throw new InvalidDataException("Rollback metadata is incomplete.");
            if ((bool?)row["existed"] == true)
            {
                string source = (string)row["backup_path"] ?? "";
                if (!File.Exists(source))
                    throw new FileNotFoundException("Original rollback file is missing: " + name);
                AtomicCopy(source, target);
                string expected = (string)row["sha256"] ?? "";
                if (!string.Equals(
                        ReleaseManifestVerifier.Sha256(target), expected,
                        StringComparison.OrdinalIgnoreCase))
                    throw new CryptographicException("Restored rollback hash mismatch: " + name);
            }
            else if (File.Exists(target)) RetryIo(delegate { File.Delete(target); });
        }

        private static JObject CreateOperationBackup(
            string stateDir, string dllTarget, string configTarget,
            string recordPath, string bootstrapPath, string action)
        {
            string root = Path.Combine(stateDir, "backups", UtcStamp() + "-pre-" + action);
            Directory.CreateDirectory(root);
            JObject result = new JObject { ["root"] = root };
            CaptureOperation(result, "dll", dllTarget, Path.Combine(root, DllName));
            CaptureOperation(result, "config", configTarget, Path.Combine(root, ConfigName));
            CaptureOperation(
                result, "install_record", recordPath, Path.Combine(root, "install-record.json"));
            CaptureOperation(
                result, "bootstrap", bootstrapPath, Path.Combine(root, "bootstrap.dpapi"));
            return result;
        }

        private static void CaptureOperation(
            JObject operation, string name, string source, string backup)
        {
            bool existed = File.Exists(source);
            string sha256 = "";
            if (existed)
            {
                sha256 = ReleaseManifestVerifier.Sha256(source);
                RetryIo(delegate { File.Copy(source, backup, true); });
                if (!string.Equals(
                        ReleaseManifestVerifier.Sha256(backup), sha256,
                        StringComparison.OrdinalIgnoreCase))
                    throw new CryptographicException(
                        "Operation backup hash mismatch: " + name);
            }
            operation[name] = new JObject
            {
                ["existed"] = existed,
                ["backup_path"] = existed ? backup : "",
                ["sha256"] = sha256,
            };
        }

        private static void RestoreOperationBackup(
            JObject operation, string dllTarget, string configTarget,
            string recordPath, string bootstrapPath)
        {
            RestoreOperationFile(operation["dll"] as JObject, dllTarget);
            RestoreOperationFile(operation["config"] as JObject, configTarget);
            RestoreOperationFile(operation["install_record"] as JObject, recordPath);
            RestoreOperationFile(operation["bootstrap"] as JObject, bootstrapPath);
        }

        private static void RestoreOperationFile(JObject row, string target)
        {
            if (row == null) throw new InvalidDataException("Operation rollback metadata is missing.");
            if ((bool?)row["existed"] == true)
            {
                AtomicCopy((string)row["backup_path"], target);
                string expected = (string)row["sha256"] ?? "";
                if (string.IsNullOrWhiteSpace(expected) || !string.Equals(
                        ReleaseManifestVerifier.Sha256(target), expected,
                        StringComparison.OrdinalIgnoreCase))
                    throw new CryptographicException(
                        "Restored operation backup hash mismatch: " + Path.GetFileName(target));
            }
            else if (File.Exists(target)) RetryIo(delegate { File.Delete(target); });
        }

        private static string CacheVerifiedRelease(VerifiedRelease release, string stateDir)
        {
            string target = Path.Combine(stateDir, "release-cache", release.Version);
            string sourceRoot = Path.GetFullPath(release.Root).TrimEnd('\\', '/');
            string targetRoot = Path.GetFullPath(target).TrimEnd('\\', '/');
            if (string.Equals(sourceRoot, targetRoot, StringComparison.OrdinalIgnoreCase))
                return target;

            if (Directory.Exists(target))
            {
                VerifiedRelease cached = ReleaseManifestVerifier.Verify(target);
                if (!string.Equals(cached.Version, release.Version, StringComparison.Ordinal) ||
                    !string.Equals(
                        cached.ManifestSha256, release.ManifestSha256,
                        StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException(
                        "A different Connector release is already cached under version " +
                        release.Version + ".");
                return target;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(target));
            string temporary = target + ".stratforge-cache-" + Guid.NewGuid().ToString("N");
            Directory.CreateDirectory(temporary);
            try
            {
                CopyExact(
                    Path.Combine(release.Root, "manifest.json"),
                    Path.Combine(temporary, "manifest.json"));
                CopyExact(
                    Path.Combine(release.Root, "manifest.sig"),
                    Path.Combine(temporary, "manifest.sig"));
                foreach (JObject row in
                    (release.Manifest["files"] as JArray ?? new JArray()).OfType<JObject>())
                {
                    string relative = ((string)row["path"] ?? "")
                        .Replace('/', Path.DirectorySeparatorChar);
                    CopyExact(
                        Path.Combine(release.Root, relative),
                        Path.Combine(temporary, relative));
                }
                VerifiedRelease cached = ReleaseManifestVerifier.Verify(temporary);
                if (!string.Equals(
                        cached.ManifestSha256, release.ManifestSha256,
                        StringComparison.OrdinalIgnoreCase))
                    throw new CryptographicException(
                        "Cached Connector release manifest changed during copy.");
                Directory.Move(temporary, target);
                return target;
            }
            catch
            {
                if (Directory.Exists(temporary)) Directory.Delete(temporary, true);
                throw;
            }
        }

        private static string NormalizeEnrollmentCode(string value)
        {
            string compact = Regex.Replace((value ?? "").ToUpperInvariant(), "[^A-Z0-9]", "");
            if (compact == "") return "";
            if (!Regex.IsMatch(compact, "^[2-9A-HJ-NP-Z]{16}$"))
                throw new InvalidDataException("Enrollment code format is invalid.");
            return compact;
        }

        private static void StoreBootstrap(string stateDir, string compact)
        {
            byte[] plaintext = Encoding.UTF8.GetBytes(compact);
            try
            {
                byte[] encrypted = ProtectedData.Protect(
                    plaintext, BootstrapEntropy, DataProtectionScope.CurrentUser);
                AtomicWriteBytes(Path.Combine(stateDir, "bootstrap.dpapi"), encrypted);
                try { File.SetAttributes(
                    Path.Combine(stateDir, "bootstrap.dpapi"), FileAttributes.Hidden); } catch { }
            }
            finally
            {
                Array.Clear(plaintext, 0, plaintext.Length);
            }
        }

        private static void ValidateOptions(VerifiedRelease release, InstallOptions options)
        {
            if (release == null || options == null) throw new ArgumentNullException();
            options.ServerOrigin = NormalizeOrigin(options.ServerOrigin);
            if (options.Channel != "stable" && options.Channel != "canary")
                throw new InvalidDataException("Release channel must be stable or canary.");
            if (options.UpdatePolicy != "safe_restart" && options.UpdatePolicy != "manual")
                throw new InvalidDataException("Update policy must be safe_restart or manual.");
            if (!string.Equals(release.Channel, options.Channel, StringComparison.Ordinal) &&
                !string.Equals(release.Channel, "stable", StringComparison.Ordinal))
                throw new InvalidDataException("Release bundle channel is incompatible with the selected channel.");
        }

        private static string NormalizeOrigin(string value)
        {
            Uri uri;
            if (!Uri.TryCreate(value ?? "", UriKind.Absolute, out uri) ||
                uri.Scheme != Uri.UriSchemeHttps || uri.PathAndQuery != "/" ||
                !string.IsNullOrEmpty(uri.UserInfo))
                throw new InvalidDataException("Server origin must be an HTTPS origin without path or credentials.");
            return uri.GetLeftPart(UriPartial.Authority);
        }

        private static string RequireNinjaDirectory(string value)
        {
            string path = Path.GetFullPath(value ?? "");
            if (!Directory.Exists(path))
                throw new DirectoryNotFoundException("NinjaTrader user directory does not exist: " + path);
            return path.TrimEnd(Path.DirectorySeparatorChar);
        }

        private static string ResolveStateDir(InstallOptions options, string ninjaDir)
        {
            string root = string.IsNullOrWhiteSpace(options.StateRoot)
                ? Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "StratForge", "Connector")
                : Path.GetFullPath(options.StateRoot);
            // Updater receives the already-resolved per-installation state_dir
            // from strict Connector config.  Accept it only when its existing
            // installation record proves it belongs to this NinjaTrader path;
            // first-time Setup still derives an isolated installation root.
            JObject direct = ReadObject(Path.Combine(root, "install-record.json"));
            if (direct != null)
            {
                string recordedNinja = Path.GetFullPath(
                    (string)direct["ninja_user_dir"] ?? "");
                if (!string.Equals(recordedNinja, ninjaDir, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException(
                        "Connector state belongs to a different NinjaTrader user directory.");
                return root;
            }
            using (SHA256 sha = SHA256.Create())
            {
                byte[] hash = sha.ComputeHash(Encoding.UTF8.GetBytes(ninjaDir.ToUpperInvariant()));
                return Path.Combine(root, "installations", ReleaseManifestVerifier.Hex(hash).Substring(0, 16));
            }
        }

        private static void EnsureNinjaTraderClosed()
        {
            if (IsNinjaTraderRunning())
                throw new InvalidOperationException(
                    "NinjaTrader is running. Close it explicitly before install, repair or uninstall.");
        }

        private static bool IsNinjaTraderRunning()
        {
            try { return Process.GetProcessesByName("NinjaTrader").Length > 0; }
            catch { return true; }
        }

        private static FileStream AcquireLock(string stateDir)
        {
            return new FileStream(
                Path.Combine(stateDir, "installer.lock"), FileMode.OpenOrCreate,
                FileAccess.ReadWrite, FileShare.None);
        }

        private static void AtomicCopy(string source, string target)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            string temporary = target + ".stratforge-new";
            RetryIo(delegate
            {
                if (File.Exists(temporary)) File.Delete(temporary);
                File.Copy(source, temporary, true);
            });
            if (!string.Equals(
                    ReleaseManifestVerifier.Sha256(source),
                    ReleaseManifestVerifier.Sha256(temporary),
                    StringComparison.OrdinalIgnoreCase))
                throw new CryptographicException("Staged payload hash mismatch.");
            RetryIo(delegate
            {
                if (File.Exists(target)) File.Replace(temporary, target, null);
                else File.Move(temporary, target);
            });
        }

        private static void AtomicWriteText(string target, string value)
        {
            AtomicWriteBytes(target, new UTF8Encoding(false).GetBytes(value ?? ""));
        }

        private static void AtomicWriteBytes(string target, byte[] value)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            string temporary = target + ".stratforge-new";
            RetryIo(delegate
            {
                if (File.Exists(temporary)) File.Delete(temporary);
                File.WriteAllBytes(temporary, value);
            });
            RetryIo(delegate
            {
                if (File.Exists(target)) File.Replace(temporary, target, null);
                else File.Move(temporary, target);
            });
        }

        private static void CopyExact(string source, string target)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            RetryIo(delegate { File.Copy(source, target, true); });
        }

        private static void RetryIo(Action action)
        {
            for (int attempt = 1; ; attempt++)
            {
                try
                {
                    action();
                    return;
                }
                catch (IOException exc)
                {
                    if (IsNinjaTraderRunning())
                        throw new InvalidOperationException(
                            "NinjaTrader started while Connector files were being changed; " +
                            "the operation was stopped for a safe restart.", exc);
                    if (attempt >= 4) throw;
                    Thread.Sleep(250 * attempt);
                }
            }
        }

        private static JObject ReadObject(string path)
        {
            if (!File.Exists(path)) return null;
            return JObject.Parse(File.ReadAllText(path, Encoding.UTF8));
        }

        private static void Journal(
            string stateDir, string action, string version, string result, string detail)
        {
            JObject row = new JObject
            {
                ["timestamp_utc"] = UtcNow(),
                ["action"] = action,
                ["version"] = version,
                ["result"] = result,
                ["detail"] = detail ?? "",
            };
            File.AppendAllText(
                Path.Combine(stateDir, "installer-journal.jsonl"),
                row.ToString(Formatting.None) + Environment.NewLine,
                new UTF8Encoding(false));
        }

        private static JObject Result(
            string action, VerifiedRelease release, string ninjaDir,
            string stateDir, string dllPath, string configPath)
        {
            return new JObject
            {
                ["ok"] = true,
                ["action"] = action,
                ["version"] = release.Version,
                ["trust_tier"] = release.TrustTier,
                ["ninja_user_dir"] = ninjaDir,
                ["state_dir"] = stateDir,
                ["dll_present"] = File.Exists(dllPath),
                ["config_present"] = File.Exists(configPath),
                ["restart_required"] = action != "uninstall",
            };
        }

        private static void RegisterPairingScheme(string setupPath)
        {
            using (RegistryKey root = Registry.CurrentUser.CreateSubKey(
                @"Software\Classes\stratforge-connector"))
            {
                root.SetValue("", "URL:StratForge Connector Pairing");
                root.SetValue("URL Protocol", "");
                using (RegistryKey icon = root.CreateSubKey("DefaultIcon"))
                    icon.SetValue("", "\"" + setupPath + "\",0");
                using (RegistryKey command = root.CreateSubKey(@"shell\open\command"))
                    command.SetValue("", "\"" + setupPath + "\" --pairing-uri \"%1\"");
            }
        }

        private static void UnregisterPairingScheme()
        {
            try { Registry.CurrentUser.DeleteSubKeyTree(
                @"Software\Classes\stratforge-connector", false); } catch { }
        }

        private static void AddCandidate(ICollection<string> values, string candidate)
        {
            if (string.IsNullOrWhiteSpace(candidate) || !Directory.Exists(candidate)) return;
            string full = Path.GetFullPath(candidate).TrimEnd(Path.DirectorySeparatorChar);
            if (!values.Contains(full, StringComparer.OrdinalIgnoreCase)) values.Add(full);
        }

        private static string UtcNow()
        {
            return DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'");
        }

        private static string UtcStamp()
        {
            return DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff");
        }
    }
}
